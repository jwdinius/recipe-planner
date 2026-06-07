"""CP-SAT model for the plan preview (ADR-0003).

Pure function over plain dataclasses (see app/optimizer/types.py). The
solver is HTTP-unaware — translation from SQLModel rows happens in
app/routes/plans.py.
"""
from __future__ import annotations

import math
from collections import defaultdict

from ortools.sat.python import cp_model

from app.optimizer.types import (
    GroceryItem,
    IngredientInfo,
    PantryQty,
    Pin,
    PlanEntry,
    PlanResult,
    PlanWarning,
    RecipeCandidate,
    ScoreBreakdown,
)

# CP-SAT is integer-only. SCALE handles fractional purchase-unit quantities;
# WEIGHT_SCALE lets float weights (incl. per-request overrides, recency curve,
# tier multipliers) survive the trip into the integer objective.
SCALE = 1000
WEIGHT_SCALE = 100

DEFAULT_WEIGHTS: dict[str, float] = {
    "waste": 10.0,
    "preference": -3.0,
    "recency": -2.0,
    "variety": 5.0,
}

TIER_MULTIPLIERS: dict[str, float] = {
    "perishable": 3.0,
    "semi_perishable": 1.0,
    "staple": 0.0,
}

WASTE_TIERS = ("perishable", "semi_perishable")


def solve_plan(
    candidates: list[RecipeCandidate],
    ingredients: dict[int, IngredientInfo],
    pins: list[Pin],
    carryover: list[PantryQty],
    weights: dict[str, float],
    target_slots: int,
) -> PlanResult | None:
    """Solve the plan preview problem. Returns None if INFEASIBLE."""
    pinned_ids = {p.recipe_id for p in pins}
    candidates_by_id = {c.id: c for c in candidates}

    # Pin overrides hard exclude (ADR-0003). Emit a warning per pinned-and-
    # excluded recipe so the API surfaces the conflict.
    warnings_out: list[PlanWarning] = []
    for pin in pins:
        c = candidates_by_id.get(pin.recipe_id)
        if c is None or not c.hard_excluded:
            continue
        warnings_out.append(
            PlanWarning(
                recipe_id=pin.recipe_id,
                message=(
                    "pinned recipe was hard-excluded by user(s); pin overrides exclude"
                ),
                excluding_user_ids=c.excluded_by_user_ids,
            )
        )

    w_waste = weights["waste"]
    w_pref = weights["preference"]
    w_recency = weights["recency"]
    w_variety = weights["variety"]

    # Aggregate per-recipe demand by ingredient (some recipes might list the
    # same ingredient twice — sum them) and convert to scaled integers.
    raw_demand: dict[int, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    for c in candidates:
        for d in c.demands:
            raw_demand[c.id][d.ingredient_id] += d.quantity_purchase_units

    demand_per_ing: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for recipe_id, by_ing in raw_demand.items():
        for ing_id, qty in by_ing.items():
            scaled = round(SCALE * qty)
            if scaled <= 0:
                continue
            demand_per_ing[ing_id].append((recipe_id, scaled))

    carryover_scaled: dict[int, int] = {
        p.ingredient_id: round(SCALE * p.quantity_purchase_units)
        for p in carryover
    }

    tracked_ingredients = sorted(
        ing_id
        for ing_id in demand_per_ing
        if ing_id in ingredients
        and ingredients[ing_id].tier in WASTE_TIERS
    )

    model = cp_model.CpModel()

    selected = {c.id: model.NewBoolVar(f"sel_{c.id}") for c in candidates}
    doubled = {c.id: model.NewBoolVar(f"dbl_{c.id}") for c in candidates}

    for c in candidates:
        model.Add(doubled[c.id] <= selected[c.id])
        # Hard exclude wins UNLESS pinned (pin overrides exclude per ADR-0003).
        if c.hard_excluded and c.id not in pinned_ids:
            model.Add(selected[c.id] == 0)

    for pin in pins:
        if pin.recipe_id not in selected:
            # Route validates; defensive no-op.
            continue
        model.Add(selected[pin.recipe_id] == 1)
        model.Add(doubled[pin.recipe_id] == (1 if pin.doubled else 0))

    slot_sum = sum(selected[c.id] + doubled[c.id] for c in candidates)
    model.Add(slot_sum == target_slots)

    packages: dict[int, cp_model.IntVar] = {}
    for ing_id in tracked_ingredients:
        max_demand_scaled = 2 * sum(qty for _, qty in demand_per_ing[ing_id])
        max_packages = math.ceil(max_demand_scaled / SCALE) + 1
        packages[ing_id] = model.NewIntVar(0, max_packages, f"pkg_{ing_id}")

        demand_expr = sum(
            qty * selected[r_id] + qty * doubled[r_id]
            for r_id, qty in demand_per_ing[ing_id]
        )
        carry = carryover_scaled.get(ing_id, 0)
        model.Add(SCALE * packages[ing_id] >= demand_expr - carry)

    # Variety: per distinct cuisine, excess = max(0, count - 2). Encoded as
    # excess >= count - 2 (with excess in [0, target_slots]); the positive
    # variety weight pulls excess down to its floor at optimum.
    cuisines: dict[str, list[int]] = defaultdict(list)
    for c in candidates:
        if c.cuisine:
            cuisines[c.cuisine].append(c.id)

    excess: dict[str, cp_model.IntVar] = {}
    for idx, cuisine in enumerate(sorted(cuisines)):
        rids = cuisines[cuisine]
        ev = model.NewIntVar(0, target_slots, f"excess_{idx}")
        excess[cuisine] = ev
        model.Add(ev >= sum(selected[r] for r in rids) - 2)

    # --- Objective. CP-SAT is integer-only; we multiply every float
    # coefficient by WEIGHT_SCALE so per-request float overrides and the
    # recency curve survive. Waste internally carries an extra SCALE factor
    # from the scaled-quantity expression; that ratio is preserved from #7.
    objective_terms = []

    for ing_id in tracked_ingredients:
        tier_mult = TIER_MULTIPLIERS[ingredients[ing_id].tier]
        coeff = round(w_waste * tier_mult * WEIGHT_SCALE)
        if coeff == 0:
            continue
        demand_expr = sum(
            qty * selected[r_id] + qty * doubled[r_id]
            for r_id, qty in demand_per_ing[ing_id]
        )
        carry = carryover_scaled.get(ing_id, 0)
        objective_terms.append(
            coeff * (SCALE * packages[ing_id] - demand_expr + carry)
        )

    iw_pref = round(w_pref * WEIGHT_SCALE)
    if iw_pref != 0:
        for c in candidates:
            if c.preference_points != 0:
                objective_terms.append(
                    iw_pref * c.preference_points * selected[c.id]
                )

    for c in candidates:
        if c.recency_value == 0.0:
            continue
        coeff = round(w_recency * c.recency_value * WEIGHT_SCALE)
        if coeff == 0:
            continue
        objective_terms.append(coeff * selected[c.id])

    iw_variety = round(w_variety * WEIGHT_SCALE)
    if iw_variety != 0:
        for ev in excess.values():
            objective_terms.append(iw_variety * ev)

    if objective_terms:
        model.Minimize(sum(objective_terms))

    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None

    plan_entries: list[PlanEntry] = []
    for c in candidates:
        if solver.Value(selected[c.id]) == 1:
            plan_entries.append(
                PlanEntry(
                    recipe_id=c.id,
                    doubled=bool(solver.Value(doubled[c.id])),
                )
            )
    plan_entries.sort(key=lambda e: e.recipe_id)

    selected_vals = {c.id: solver.Value(selected[c.id]) for c in candidates}
    doubled_vals = {c.id: solver.Value(doubled[c.id]) for c in candidates}

    # Derive the grocery list from selected/doubled directly. When the waste
    # weight is 0 the solver leaves `packages[i]` free; the user-facing answer
    # is still "buy the minimum that covers demand minus carryover."
    waste_score = 0.0
    grocery: list[GroceryItem] = []
    for ing_id in tracked_ingredients:
        tier_mult = TIER_MULTIPLIERS[ingredients[ing_id].tier]
        demand_scaled = sum(
            qty * (selected_vals[r_id] + doubled_vals[r_id])
            for r_id, qty in demand_per_ing[ing_id]
        )
        carry = carryover_scaled.get(ing_id, 0)
        net_scaled = demand_scaled - carry
        if net_scaled <= 0:
            continue
        pkg = math.ceil(net_scaled / SCALE)
        waste_pu = (SCALE * pkg - demand_scaled + carry) / SCALE
        if waste_pu < 0:
            waste_pu = 0.0
        waste_score += w_waste * tier_mult * waste_pu

        info = ingredients[ing_id]
        grocery.append(
            GroceryItem(
                ingredient_id=ing_id,
                name=info.name,
                purchase_unit=info.purchase_unit,
                quantity=int(pkg),
                projected_waste=waste_pu,
            )
        )

    pref_score = sum(
        w_pref * c.preference_points * selected_vals[c.id]
        for c in candidates
    )

    recency_score = sum(
        w_recency * c.recency_value * selected_vals[c.id]
        for c in candidates
    )

    # Variety: real per-cuisine excess from the chosen plan, recomputed
    # independent of the solver's excess vars (which are free-floating when
    # iw_variety == 0).
    variety_score = 0.0
    for cuisine, rids in cuisines.items():
        count = sum(selected_vals[r] for r in rids)
        excess_val = max(0, count - 2)
        variety_score += w_variety * excess_val

    grocery.sort(key=lambda g: g.ingredient_id)
    total = waste_score + pref_score + recency_score + variety_score

    return PlanResult(
        plan=tuple(plan_entries),
        score_breakdown=ScoreBreakdown(
            waste=waste_score,
            preference=pref_score,
            recency=recency_score,
            variety=variety_score,
            total=total,
        ),
        grocery_list=tuple(grocery),
        warnings=tuple(warnings_out),
    )
