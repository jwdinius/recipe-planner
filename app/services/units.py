from collections.abc import Iterable

from fastapi import HTTPException, status
from sqlmodel import Session, select

from app.models.ingredient import Ingredient


def fetch_and_validate_units(
    items: Iterable[tuple[int, str]], session: Session
) -> dict[int, Ingredient]:
    pairs = list(items)
    if not pairs:
        return {}
    ids = {ingredient_id for ingredient_id, _ in pairs}
    rows = session.exec(select(Ingredient).where(Ingredient.id.in_(ids))).all()
    by_id: dict[int, Ingredient] = {row.id: row for row in rows}

    missing = sorted(ids - by_id.keys())
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"unknown ingredient_id(s): {missing}",
        )

    for ingredient_id, unit in pairs:
        ing = by_id[ingredient_id]
        if unit != ing.purchase_unit and unit not in ing.unit_conversions:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    f"unit '{unit}' is not defined for ingredient "
                    f"'{ing.name}' (purchase_unit='{ing.purchase_unit}', "
                    f"known units={sorted(ing.unit_conversions.keys())})"
                ),
            )
    return by_id


def to_purchase_units(
    quantity: float, unit: str, ingredient: Ingredient
) -> float:
    if unit == ingredient.purchase_unit:
        return quantity
    factor = ingredient.unit_conversions.get(unit)
    if factor is None:
        raise ValueError(
            f"unit '{unit}' has no conversion to purchase_unit "
            f"'{ingredient.purchase_unit}' for ingredient '{ingredient.name}'"
        )
    return quantity * factor
