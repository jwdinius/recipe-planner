from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, SQLModel, select

from app.db import get_session
from app.models.ingredient import Ingredient
from app.models.recipe import Recipe, RecipeIngredient

router = APIRouter(prefix="/recipes", tags=["recipes"])


class RecipeIngredientIn(SQLModel):
    ingredient_id: int
    quantity: float
    unit: str


class RecipeIngredientRead(SQLModel):
    ingredient_id: int
    quantity: float
    unit: str


class RecipeCreate(SQLModel):
    title: str
    cuisine: str
    prep_minutes: int
    cook_minutes: int
    instructions: str
    source_url: str | None = None
    dietary_tags: list[str] = []
    ingredients: list[RecipeIngredientIn] = []


class RecipeUpdate(SQLModel):
    title: str | None = None
    cuisine: str | None = None
    prep_minutes: int | None = None
    cook_minutes: int | None = None
    instructions: str | None = None
    source_url: str | None = None
    dietary_tags: list[str] | None = None
    ingredients: list[RecipeIngredientIn] | None = None


class RecipeRead(SQLModel):
    id: int
    title: str
    cuisine: str
    prep_minutes: int
    cook_minutes: int
    instructions: str
    source_url: str | None
    dietary_tags: list[str]
    last_cooked_at: date | None
    ingredients: list[RecipeIngredientRead]


def _validate_ingredient_units(
    items: list[RecipeIngredientIn], session: Session
) -> None:
    if not items:
        return
    ids = {item.ingredient_id for item in items}
    rows = session.exec(select(Ingredient).where(Ingredient.id.in_(ids))).all()
    by_id: dict[int, Ingredient] = {row.id: row for row in rows}

    missing = sorted(ids - by_id.keys())
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"unknown ingredient_id(s): {missing}",
        )

    for item in items:
        ing = by_id[item.ingredient_id]
        if item.unit != ing.purchase_unit and item.unit not in ing.unit_conversions:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    f"unit '{item.unit}' is not defined for ingredient "
                    f"'{ing.name}' (purchase_unit='{ing.purchase_unit}', "
                    f"known units={sorted(ing.unit_conversions.keys())})"
                ),
            )


def _to_read(recipe: Recipe) -> RecipeRead:
    return RecipeRead(
        id=recipe.id,
        title=recipe.title,
        cuisine=recipe.cuisine,
        prep_minutes=recipe.prep_minutes,
        cook_minutes=recipe.cook_minutes,
        instructions=recipe.instructions,
        source_url=recipe.source_url,
        dietary_tags=recipe.dietary_tags,
        last_cooked_at=recipe.last_cooked_at,
        ingredients=[
            RecipeIngredientRead(
                ingredient_id=ri.ingredient_id,
                quantity=ri.quantity,
                unit=ri.unit,
            )
            for ri in recipe.ingredients
        ],
    )


@router.post("", response_model=RecipeRead, status_code=status.HTTP_201_CREATED)
def create_recipe(
    payload: RecipeCreate, session: Session = Depends(get_session)
) -> RecipeRead:
    _validate_ingredient_units(payload.ingredients, session)

    recipe = Recipe(
        title=payload.title,
        cuisine=payload.cuisine,
        prep_minutes=payload.prep_minutes,
        cook_minutes=payload.cook_minutes,
        instructions=payload.instructions,
        source_url=payload.source_url,
        dietary_tags=payload.dietary_tags,
    )
    recipe.ingredients = [
        RecipeIngredient(
            ingredient_id=item.ingredient_id,
            quantity=item.quantity,
            unit=item.unit,
        )
        for item in payload.ingredients
    ]
    session.add(recipe)
    session.commit()
    session.refresh(recipe)
    return _to_read(recipe)


@router.get("", response_model=list[RecipeRead])
def list_recipes(session: Session = Depends(get_session)) -> list[RecipeRead]:
    recipes = session.exec(select(Recipe).order_by(Recipe.title)).all()
    return [_to_read(r) for r in recipes]


@router.get("/{recipe_id}", response_model=RecipeRead)
def get_recipe(
    recipe_id: int, session: Session = Depends(get_session)
) -> RecipeRead:
    recipe = session.get(Recipe, recipe_id)
    if recipe is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return _to_read(recipe)


@router.patch("/{recipe_id}", response_model=RecipeRead)
def update_recipe(
    recipe_id: int,
    payload: RecipeUpdate,
    session: Session = Depends(get_session),
) -> RecipeRead:
    recipe = session.get(Recipe, recipe_id)
    if recipe is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")

    data = payload.model_dump(exclude_unset=True)
    new_ingredients = data.pop("ingredients", None)
    for field, value in data.items():
        setattr(recipe, field, value)

    if new_ingredients is not None:
        items = [RecipeIngredientIn(**item) for item in new_ingredients]
        _validate_ingredient_units(items, session)
        recipe.ingredients = [
            RecipeIngredient(
                ingredient_id=item.ingredient_id,
                quantity=item.quantity,
                unit=item.unit,
            )
            for item in items
        ]

    session.add(recipe)
    session.commit()
    session.refresh(recipe)
    return _to_read(recipe)


@router.delete("/{recipe_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_recipe(
    recipe_id: int, session: Session = Depends(get_session)
) -> None:
    recipe = session.get(Recipe, recipe_id)
    if recipe is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    session.delete(recipe)
    session.commit()
