from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Field, Session, SQLModel, select

from app.db import get_session
from app.models.ingredient import Ingredient
from app.models.pantry import PantryEntry
from app.models.recipe import Recipe, RecipeIngredient
from app.models.user import User
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


def _to_response(result: PlanResult) -> PlanPreviewResponse:
    return PlanPreviewResponse(
        plan=[
            PlanEntryRead(recipe_id=e.recipe_id, doubled=e.doubled)
            for e in result.plan
        ],
        score_breakdown=ScoreBreakdownRead(
            waste=result.score_breakdown.waste,
            preference=result.score_breakdown.preference,
            recency=result.score_breakdown.recency,
            variety=result.score_breakdown.variety,
            total=result.score_breakdown.total,
        ),
        grocery_list=[
            GroceryItemRead(
                ingredient_id=g.ingredient_id,
                name=g.name,
                purchase_unit=g.purchase_unit,
                quantity=g.quantity,
                projected_waste=g.projected_waste,
            )
            for g in result.grocery_list
        ],
        warnings=[
            PlanWarningRead(
                recipe_id=w.recipe_id,
                message=w.message,
                excluding_user_ids=list(w.excluding_user_ids),
            )
            for w in result.warnings
        ],
    )


def _load_ingredients(session: Session) -> dict[int, Ingredient]:
    return {i.id: i for i in session.exec(select(Ingredient)).all()}


def _build_candidates(
    session: Session,
    ingredients_by_id: dict[int, Ingredient],
    today: date,
) -> list[RecipeCandidate]:
    recipes = session.exec(select(Recipe).order_by(Recipe.id)).all()
    if not recipes:
        return []

    rows = session.exec(select(RecipeIngredient)).all()
    by_recipe: dict[int, list[RecipeIngredient]] = {}
    for ri in rows:
        by_recipe.setdefault(ri.recipe_id, []).append(ri)

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


@router.post("/preview", response_model=PlanPreviewResponse)
def preview_plan(
    payload: PlanPreviewRequest,
    session: Session = Depends(get_session),
) -> PlanPreviewResponse:
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
    effective_weights = {**DEFAULT_WEIGHTS, **(payload.weights or {})}

    ingredients_by_id = _load_ingredients(session)
    candidates = _build_candidates(session, ingredients_by_id, date.today())
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
    return _to_response(result)
