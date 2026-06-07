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
    RecipeCandidate,
    ScoreBreakdown,
)

# CP-SAT is integer-only. Recipe demands and carryover live in purchase-unit
# space as floats; we multiply by SCALE and round before entering the model.
SCALE = 1000

DEFAULT_WEIGHTS: dict[str, float] = {
    "waste": 10.0,
    "preference": -3.0,
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
    # In this slice hard-exclude wins over pins; warnings come in #8.
    excluded_ids = {c.id for c in candidates if c.hard_excluded}
    effective_pins = [p for p in pins if p.recipe_id not in excluded_ids]

    w_waste = weights["waste"]
    w_pref = weights["preference"]

    # Aggregate per-recipe demand by ingredient (some recipes might list the
    # same ingredient twice — sum them) and convert to scaled integers.
    raw_demand: dict[int, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    for c in candidates:
        for d in c.demands:
            raw_demand[c.id][d.ingredient_id] += d.quantity_purchase_units

    scaled_demand: dict[int, dict[int, int]] = defaultdict(dict)
    demand_per_ing: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for recipe_id, by_ing in raw_demand.items():
        for ing_id, qty in by_ing.items():
            scaled = round(SCALE * qty)
            if scaled <= 0:
                continue
            scaled_demand[recipe_id][ing_id] = scaled
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
        if c.hard_excluded:
            model.Add(selected[c.id] == 0)

    for pin in effective_pins:
        if pin.recipe_id not in selected:
            # Unknown pin recipe — caller validates and raises 422 before us;
            # if we get here it's a bug in the route. Silently ignore.
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
        # SCALE * packages[i] >= total_demand_scaled - carryover_scaled
        model.Add(SCALE * packages[ing_id] >= demand_expr - carry)

    # Objective: weighted sum, minimize. CONTEXT.md weights are used directly
    # (preference is negative → reward). Weights and tier multipliers are
    # integer-valued at v1 (no per-request overrides until #8), so int() is
    # safe — but we validate at the boundary to fail loud on a future float.
    iw_waste = _to_int_weight("waste", w_waste)
    iw_pref = _to_int_weight("preference", w_pref)

    waste_terms = []
    for ing_id in tracked_ingredients:
        tier_mult = int(TIER_MULTIPLIERS[ingredients[ing_id].tier])
        coeff = iw_waste * tier_mult
        if coeff == 0:
            continue
        demand_expr = sum(
            qty * selected[r_id] + qty * doubled[r_id]
            for r_id, qty in demand_per_ing[ing_id]
        )
        carry = carryover_scaled.get(ing_id, 0)
        waste_terms.append(
            coeff * (SCALE * packages[ing_id] - demand_expr + carry)
        )

    pref_terms = [
        iw_pref * c.preference_points * selected[c.id]
        for c in candidates
        if c.preference_points != 0
    ]

    model.Minimize(sum(waste_terms) + sum(pref_terms))

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

    waste_score = 0.0
    grocery: list[GroceryItem] = []
    for ing_id in tracked_ingredients:
        tier_mult = TIER_MULTIPLIERS[ingredients[ing_id].tier]
        pkg = solver.Value(packages[ing_id])
        demand_scaled = sum(
            qty * (selected_vals[r_id] + doubled_vals[r_id])
            for r_id, qty in demand_per_ing[ing_id]
        )
        carry = carryover_scaled.get(ing_id, 0)
        waste_pu = (SCALE * pkg - demand_scaled + carry) / SCALE
        if waste_pu < 0:
            waste_pu = 0.0
        waste_score += w_waste * tier_mult * waste_pu

        if pkg > 0:
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

    grocery.sort(key=lambda g: g.ingredient_id)

    return PlanResult(
        plan=tuple(plan_entries),
        score_breakdown=ScoreBreakdown(
            waste=waste_score,
            preference=pref_score,
            total=waste_score + pref_score,
        ),
        grocery_list=tuple(grocery),
    )


def _to_int_weight(name: str, value: float) -> int:
    rounded = int(round(value))
    if rounded != value:
        raise ValueError(
            f"weight '{name}'={value} must be integer-valued in this slice "
            "(per-request float overrides arrive in #8)"
        )
    return rounded
