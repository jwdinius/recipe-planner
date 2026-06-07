from collections import defaultdict
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Field, Session, SQLModel, select

from app.db import get_session
from app.models.ingredient import Ingredient
from app.models.pantry import PantryEntry
from app.models.recipe import Recipe, RecipeIngredient
from app.models.user import User
from app.models.weekly_plan import WeeklyPlan, WeeklyPlanEntry
from app.optimizer.model import DEFAULT_WEIGHTS, solve_plan
from app.optimizer.types import (
    IngredientInfo,
    PantryQty,
    Pin,
    PlanResult,
    RecipeCandidate,
    RecipeDemand,
)
from app.services.ratings import (
    hard_exclude_user_ids,
    is_hard_excluded,
    preference_points,
)
from app.services.scoring import recency_value, weeks_since
from app.services.units import to_purchase_units

router = APIRouter(prefix="/plans", tags=["plans"])


class PinIn(SQLModel):
    recipe_id: int
    doubled: bool = False


class PlanPreviewRequest(SQLModel):
    user_id: int
    target_slots: int = Field(default=4, ge=3, le=6)
    pins: list[PinIn] = Field(default_factory=list)
    weights: dict[str, float] | None = None


class PlanEntryRead(SQLModel):
    recipe_id: int
    doubled: bool


class ScoreBreakdownRead(SQLModel):
    waste: float
    preference: float
    recency: float
    variety: float
    total: float


class GroceryItemRead(SQLModel):
    ingredient_id: int
    name: str
    purchase_unit: str
    quantity: int
    projected_waste: float


class PlanWarningRead(SQLModel):
    recipe_id: int
    message: str
    excluding_user_ids: list[int]


class PlanPreviewResponse(SQLModel):
    plan: list[PlanEntryRead]
    score_breakdown: ScoreBreakdownRead
    grocery_list: list[GroceryItemRead]
    warnings: list[PlanWarningRead] = Field(default_factory=list)


class ProjectedPantryItem(SQLModel):
    ingredient_id: int
    name: str
    purchase_unit: str
    quantity: float


class PlanCommitResponse(SQLModel):
    plan_id: int
    committed_at: datetime
    plan: list[PlanEntryRead]
    score_breakdown: ScoreBreakdownRead
    grocery_list: list[GroceryItemRead]
    projected_pantry: list[ProjectedPantryItem]
    warnings: list[PlanWarningRead] = Field(default_factory=list)


def _to_plan_entries(result: PlanResult) -> list[PlanEntryRead]:
    return [
        PlanEntryRead(recipe_id=e.recipe_id, doubled=e.doubled)
        for e in result.plan
    ]


def _to_score_breakdown(result: PlanResult) -> ScoreBreakdownRead:
    sb = result.score_breakdown
    return ScoreBreakdownRead(
        waste=sb.waste,
        preference=sb.preference,
        recency=sb.recency,
        variety=sb.variety,
        total=sb.total,
    )


def _to_grocery(result: PlanResult) -> list[GroceryItemRead]:
    return [
        GroceryItemRead(
            ingredient_id=g.ingredient_id,
            name=g.name,
            purchase_unit=g.purchase_unit,
            quantity=g.quantity,
            projected_waste=g.projected_waste,
        )
        for g in result.grocery_list
    ]


def _to_warnings(result: PlanResult) -> list[PlanWarningRead]:
    return [
        PlanWarningRead(
            recipe_id=w.recipe_id,
            message=w.message,
            excluding_user_ids=list(w.excluding_user_ids),
        )
        for w in result.warnings
    ]


def _load_ingredients(session: Session) -> dict[int, Ingredient]:
    return {i.id: i for i in session.exec(select(Ingredient)).all()}


def _load_recipe_ingredients(
    session: Session,
) -> dict[int, list[RecipeIngredient]]:
    rows = session.exec(select(RecipeIngredient)).all()
    by_recipe: dict[int, list[RecipeIngredient]] = {}
    for ri in rows:
        by_recipe.setdefault(ri.recipe_id, []).append(ri)
    return by_recipe


def _build_candidates(
    session: Session,
    ingredients_by_id: dict[int, Ingredient],
    by_recipe: dict[int, list[RecipeIngredient]],
    today: date,
) -> list[RecipeCandidate]:
    recipes = session.exec(select(Recipe).order_by(Recipe.id)).all()
    candidates: list[RecipeCandidate] = []
    for r in recipes:
        demands = tuple(
            RecipeDemand(
                ingredient_id=ri.ingredient_id,
                quantity_purchase_units=to_purchase_units(
                    ri.quantity, ri.unit, ingredients_by_id[ri.ingredient_id]
                ),
            )
            for ri in by_recipe.get(r.id, [])
        )
        hard_excluded = is_hard_excluded(session, r.id)
        excluding = (
            tuple(hard_exclude_user_ids(session, r.id)) if hard_excluded else ()
        )
        candidates.append(
            RecipeCandidate(
                id=r.id,
                preference_points=preference_points(session, r.id),
                hard_excluded=hard_excluded,
                demands=demands,
                recency_value=recency_value(
                    weeks_since(r.last_cooked_at, today)
                ),
                cuisine=r.cuisine,
                excluded_by_user_ids=excluding,
            )
        )
    return candidates


def _build_carryover(
    session: Session, ingredients_by_id: dict[int, Ingredient]
) -> list[PantryQty]:
    entries = session.exec(select(PantryEntry)).all()
    return [
        PantryQty(
            ingredient_id=e.ingredient_id,
            quantity_purchase_units=to_purchase_units(
                e.quantity, e.unit, ingredients_by_id[e.ingredient_id]
            ),
        )
        for e in entries
        if e.ingredient_id in ingredients_by_id
    ]


def _validate_request(payload: PlanPreviewRequest, session: Session) -> None:
    if session.get(User, payload.user_id) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"unknown user_id: {payload.user_id}",
        )

    pin_ids = [pin.recipe_id for pin in payload.pins]
    if len(set(pin_ids)) != len(pin_ids):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="duplicate recipe_id in pins",
        )
    for rid in pin_ids:
        if session.get(Recipe, rid) is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"unknown recipe_id in pins: {rid}",
            )

    if payload.weights is not None:
        unknown = set(payload.weights) - set(DEFAULT_WEIGHTS)
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"unknown weight key(s): {sorted(unknown)}",
            )


def _run_solver(
    payload: PlanPreviewRequest,
    session: Session,
    today: date,
) -> tuple[
    PlanResult,
    dict[int, Ingredient],
    dict[int, list[RecipeIngredient]],
]:
    _validate_request(payload, session)
    effective_weights = {**DEFAULT_WEIGHTS, **(payload.weights or {})}

    ingredients_by_id = _load_ingredients(session)
    by_recipe = _load_recipe_ingredients(session)
    candidates = _build_candidates(session, ingredients_by_id, by_recipe, today)
    carryover = _build_carryover(session, ingredients_by_id)
    ingredient_info = {
        ing_id: IngredientInfo(
            id=ing.id,
            name=ing.name,
            tier=ing.tier,
            purchase_unit=ing.purchase_unit,
        )
        for ing_id, ing in ingredients_by_id.items()
    }
    pins = [Pin(recipe_id=p.recipe_id, doubled=p.doubled) for p in payload.pins]

    result = solve_plan(
        candidates=candidates,
        ingredients=ingredient_info,
        pins=pins,
        carryover=carryover,
        weights=effective_weights,
        target_slots=payload.target_slots,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="no feasible plan for the given pins and target_slots",
        )
    return result, ingredients_by_id, by_recipe


@router.post("/preview", response_model=PlanPreviewResponse)
def preview_plan(
    payload: PlanPreviewRequest,
    session: Session = Depends(get_session),
) -> PlanPreviewResponse:
    result, _, _ = _run_solver(payload, session, date.today())
    return PlanPreviewResponse(
        plan=_to_plan_entries(result),
        score_breakdown=_to_score_breakdown(result),
        grocery_list=_to_grocery(result),
        warnings=_to_warnings(result),
    )


def _demand_by_ingredient(
    result: PlanResult,
    by_recipe: dict[int, list[RecipeIngredient]],
    ingredients_by_id: dict[int, Ingredient],
) -> dict[int, float]:
    demand: dict[int, float] = defaultdict(float)
    for entry in result.plan:
        mult = 2 if entry.doubled else 1
        for ri in by_recipe.get(entry.recipe_id, []):
            ing = ingredients_by_id.get(ri.ingredient_id)
            if ing is None:
                continue
            demand[ri.ingredient_id] += mult * to_purchase_units(
                ri.quantity, ri.unit, ing
            )
    return demand


def _projected_pantry(
    result: PlanResult,
    by_recipe: dict[int, list[RecipeIngredient]],
    ingredients_by_id: dict[int, Ingredient],
    current_pantry: list[PantryEntry],
) -> dict[int, float]:
    """Returns ingredient_id -> projected post-cook quantity (purchase units).
    Drops staples and non-positive results.
    """
    EPS = 1e-9
    demand_pu = _demand_by_ingredient(result, by_recipe, ingredients_by_id)
    purchased_pu = {g.ingredient_id: float(g.quantity) for g in result.grocery_list}

    current_pu: dict[int, float] = {}
    for entry in current_pantry:
        ing = ingredients_by_id.get(entry.ingredient_id)
        if ing is None or ing.tier == "staple":
            continue
        current_pu[entry.ingredient_id] = to_purchase_units(
            entry.quantity, entry.unit, ing
        )

    touched_ids = set(current_pu) | set(purchased_pu) | set(demand_pu)
    projected: dict[int, float] = {}
    for ing_id in touched_ids:
        ing = ingredients_by_id.get(ing_id)
        if ing is None or ing.tier == "staple":
            continue
        qty = (
            current_pu.get(ing_id, 0.0)
            + purchased_pu.get(ing_id, 0.0)
            - demand_pu.get(ing_id, 0.0)
        )
        if qty > EPS:
            projected[ing_id] = qty
    return projected


@router.post("/commit", response_model=PlanCommitResponse)
def commit_plan(
    payload: PlanPreviewRequest,
    session: Session = Depends(get_session),
) -> PlanCommitResponse:
    committed_at = datetime.now(UTC).replace(tzinfo=None)
    result, ingredients_by_id, by_recipe = _run_solver(
        payload, session, committed_at.date()
    )

    current_pantry = list(session.exec(select(PantryEntry)).all())
    projected_pu = _projected_pantry(
        result, by_recipe, ingredients_by_id, current_pantry
    )

    plan = WeeklyPlan(
        committed_at=committed_at,
        target_slots=payload.target_slots,
    )
    plan.entries = [
        WeeklyPlanEntry(recipe_id=e.recipe_id, doubled=e.doubled)
        for e in result.plan
    ]
    session.add(plan)
    session.flush()

    for entry in result.plan:
        recipe = session.get(Recipe, entry.recipe_id)
        if recipe is not None:
            recipe.last_cooked_at = committed_at.date()
            session.add(recipe)

    for existing in current_pantry:
        session.delete(existing)
    session.flush()

    for ing_id, qty in projected_pu.items():
        ing = ingredients_by_id[ing_id]
        session.add(
            PantryEntry(
                ingredient_id=ing_id,
                quantity=qty,
                unit=ing.purchase_unit,
            )
        )

    session.commit()
    session.refresh(plan)

    projected_pantry = [
        ProjectedPantryItem(
            ingredient_id=ing_id,
            name=ingredients_by_id[ing_id].name,
            purchase_unit=ingredients_by_id[ing_id].purchase_unit,
            quantity=qty,
        )
        for ing_id, qty in sorted(projected_pu.items())
    ]

    return PlanCommitResponse(
        plan_id=plan.id,
        committed_at=committed_at,
        plan=_to_plan_entries(result),
        score_breakdown=_to_score_breakdown(result),
        grocery_list=_to_grocery(result),
        projected_pantry=projected_pantry,
        warnings=_to_warnings(result),
    )
