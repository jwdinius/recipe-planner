from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, SQLModel, select

from app.db import get_session
from app.models.ingredient import Ingredient
from app.models.pantry import PantryEntry
from app.services.units import fetch_and_validate_units

router = APIRouter(prefix="/pantry", tags=["pantry"])


class PantryEntryIn(SQLModel):
    ingredient_id: int
    quantity: float
    unit: str
    as_of: date | None = None


class PantryPatchItem(SQLModel):
    ingredient_id: int
    quantity_delta: float
    unit: str


class IngredientRef(SQLModel):
    id: int
    name: str
    tier: str
    purchase_unit: str


class PantryEntryRead(SQLModel):
    ingredient_id: int
    quantity: float
    unit: str
    as_of: date | None
    ingredient: IngredientRef


def _reject_staples(by_id: dict[int, Ingredient]) -> None:
    staples = sorted(
        ing.name for ing in by_id.values() if ing.tier == "staple"
    )
    if staples:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"staple ingredients cannot be tracked in the pantry: {staples}"
            ),
        )


def _reject_duplicate_ingredient_ids(ids: list[int]) -> None:
    seen: set[int] = set()
    dupes: list[int] = []
    for i in ids:
        if i in seen and i not in dupes:
            dupes.append(i)
        seen.add(i)
    if dupes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"duplicate ingredient_id(s) in request: {sorted(dupes)}",
        )


def _validate_pantry_writes(
    items: list[tuple[int, str]], session: Session
) -> dict[int, Ingredient]:
    by_id = fetch_and_validate_units(items, session)
    _reject_staples(by_id)
    return by_id


def _entries_with_ingredients(
    session: Session,
) -> list[tuple[PantryEntry, Ingredient]]:
    rows = session.exec(
        select(PantryEntry, Ingredient)
        .join(Ingredient, Ingredient.id == PantryEntry.ingredient_id)
        .order_by(Ingredient.name)
    ).all()
    return list(rows)


def _to_read(entry: PantryEntry, ingredient: Ingredient) -> PantryEntryRead:
    return PantryEntryRead(
        ingredient_id=entry.ingredient_id,
        quantity=entry.quantity,
        unit=entry.unit,
        as_of=entry.as_of,
        ingredient=IngredientRef(
            id=ingredient.id,
            name=ingredient.name,
            tier=ingredient.tier,
            purchase_unit=ingredient.purchase_unit,
        ),
    )


def _list(session: Session) -> list[PantryEntryRead]:
    return [_to_read(e, i) for e, i in _entries_with_ingredients(session)]


@router.get("", response_model=list[PantryEntryRead])
def list_pantry(session: Session = Depends(get_session)) -> list[PantryEntryRead]:
    return _list(session)


@router.put("", response_model=list[PantryEntryRead])
def replace_pantry(
    payload: list[PantryEntryIn], session: Session = Depends(get_session)
) -> list[PantryEntryRead]:
    _reject_duplicate_ingredient_ids([item.ingredient_id for item in payload])
    _validate_pantry_writes(
        [(item.ingredient_id, item.unit) for item in payload], session
    )

    for existing in session.exec(select(PantryEntry)).all():
        session.delete(existing)
    session.flush()

    for item in payload:
        session.add(
            PantryEntry(
                ingredient_id=item.ingredient_id,
                quantity=item.quantity,
                unit=item.unit,
                as_of=item.as_of,
            )
        )
    session.commit()
    return _list(session)


@router.patch("", response_model=list[PantryEntryRead])
def patch_pantry(
    payload: list[PantryPatchItem], session: Session = Depends(get_session)
) -> list[PantryEntryRead]:
    _reject_duplicate_ingredient_ids([item.ingredient_id for item in payload])
    _validate_pantry_writes(
        [(item.ingredient_id, item.unit) for item in payload], session
    )

    existing_by_id: dict[int, PantryEntry] = {
        e.ingredient_id: e for e in session.exec(select(PantryEntry)).all()
    }

    for item in payload:
        current = existing_by_id.get(item.ingredient_id)
        if current is None:
            if item.quantity_delta <= 0:
                continue
            session.add(
                PantryEntry(
                    ingredient_id=item.ingredient_id,
                    quantity=item.quantity_delta,
                    unit=item.unit,
                )
            )
            continue

        if item.unit != current.unit:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    f"unit '{item.unit}' does not match existing pantry entry "
                    f"unit '{current.unit}' for ingredient_id={item.ingredient_id}"
                ),
            )

        new_quantity = current.quantity + item.quantity_delta
        if new_quantity <= 0:
            session.delete(current)
        else:
            current.quantity = new_quantity
            session.add(current)

    session.commit()
    return _list(session)
