from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, select

from app.db import get_session
from app.models.ingredient import Ingredient, Tier

router = APIRouter(prefix="/ingredients", tags=["ingredients"])


class IngredientCreate(SQLModel):
    name: str
    tier: Tier
    purchase_unit: str
    unit_conversions: dict[str, float] = {}
    notes: str | None = None


class IngredientUpdate(SQLModel):
    name: str | None = None
    tier: Tier | None = None
    purchase_unit: str | None = None
    unit_conversions: dict[str, float] | None = None
    notes: str | None = None


class IngredientRead(SQLModel):
    id: int
    name: str
    tier: Tier
    purchase_unit: str
    unit_conversions: dict[str, float]
    notes: str | None


@router.post("", response_model=IngredientRead, status_code=status.HTTP_201_CREATED)
def create_ingredient(
    payload: IngredientCreate, session: Session = Depends(get_session)
) -> Ingredient:
    ingredient = Ingredient(**payload.model_dump())
    session.add(ingredient)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"ingredient with name '{payload.name}' already exists",
        )
    session.refresh(ingredient)
    return ingredient


@router.get("", response_model=list[IngredientRead])
def list_ingredients(session: Session = Depends(get_session)) -> list[Ingredient]:
    return list(session.exec(select(Ingredient).order_by(Ingredient.name)).all())


@router.get("/{ingredient_id}", response_model=IngredientRead)
def get_ingredient(
    ingredient_id: int, session: Session = Depends(get_session)
) -> Ingredient:
    ingredient = session.get(Ingredient, ingredient_id)
    if ingredient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return ingredient


@router.patch("/{ingredient_id}", response_model=IngredientRead)
def update_ingredient(
    ingredient_id: int,
    payload: IngredientUpdate,
    session: Session = Depends(get_session),
) -> Ingredient:
    ingredient = session.get(Ingredient, ingredient_id)
    if ingredient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")

    data = payload.model_dump(exclude_unset=True)
    conversions_patch = data.pop("unit_conversions", None)
    for field, value in data.items():
        setattr(ingredient, field, value)
    if conversions_patch is not None:
        ingredient.unit_conversions = {**ingredient.unit_conversions, **conversions_patch}

    session.add(ingredient)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="ingredient name conflict",
        )
    session.refresh(ingredient)
    return ingredient


@router.delete("/{ingredient_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_ingredient(
    ingredient_id: int, session: Session = Depends(get_session)
) -> None:
    ingredient = session.get(Ingredient, ingredient_id)
    if ingredient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    session.delete(ingredient)
    session.commit()
