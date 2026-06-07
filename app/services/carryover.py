from dataclasses import dataclass

from sqlmodel import Session, select

from app.models.ingredient import Ingredient
from app.models.pantry import PantryEntry
from app.models.recipe import Recipe, RecipeIngredient
from app.services.units import to_purchase_units


@dataclass(frozen=True)
class CarryoverFit:
    value: float
    overlap_ingredient_names: tuple[str, ...]


def carryover_fit(session: Session, recipe_id: int) -> CarryoverFit:
    recipe = session.get(Recipe, recipe_id)
    if recipe is None:
        return CarryoverFit(value=0.0, overlap_ingredient_names=())

    recipe_ingredients = session.exec(
        select(RecipeIngredient).where(RecipeIngredient.recipe_id == recipe_id)
    ).all()
    if not recipe_ingredients:
        return CarryoverFit(value=0.0, overlap_ingredient_names=())

    ingredient_ids = [ri.ingredient_id for ri in recipe_ingredients]
    pantry_by_ingredient: dict[int, PantryEntry] = {
        p.ingredient_id: p
        for p in session.exec(
            select(PantryEntry).where(
                PantryEntry.ingredient_id.in_(ingredient_ids)
            )
        ).all()
    }
    if not pantry_by_ingredient:
        return CarryoverFit(value=0.0, overlap_ingredient_names=())

    ingredients_by_id: dict[int, Ingredient] = {
        i.id: i
        for i in session.exec(
            select(Ingredient).where(Ingredient.id.in_(ingredient_ids))
        ).all()
    }

    total = 0.0
    overlaps: list[str] = []
    for ri in recipe_ingredients:
        pantry = pantry_by_ingredient.get(ri.ingredient_id)
        if pantry is None:
            continue
        ingredient = ingredients_by_id[ri.ingredient_id]
        recipe_qty_pu = to_purchase_units(ri.quantity, ri.unit, ingredient)
        pantry_qty_pu = to_purchase_units(
            pantry.quantity, pantry.unit, ingredient
        )
        if pantry_qty_pu <= 0:
            continue
        total += min(1.0, recipe_qty_pu / pantry_qty_pu)
        overlaps.append(ingredient.name)

    return CarryoverFit(
        value=total, overlap_ingredient_names=tuple(overlaps)
    )
