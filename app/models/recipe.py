from datetime import date

from sqlalchemy import Column, JSON
from sqlmodel import Field, Relationship, SQLModel


class RecipeIngredient(SQLModel, table=True):
    __tablename__ = "recipe_ingredients"

    id: int | None = Field(default=None, primary_key=True)
    recipe_id: int = Field(foreign_key="recipes.id", index=True)
    ingredient_id: int = Field(foreign_key="ingredients.id", index=True)
    quantity: float
    unit: str

    recipe: "Recipe" = Relationship(back_populates="ingredients")


class Recipe(SQLModel, table=True):
    __tablename__ = "recipes"

    id: int | None = Field(default=None, primary_key=True)
    title: str = Field(index=True)
    cuisine: str = Field(index=True)
    prep_minutes: int
    cook_minutes: int
    instructions: str
    source_url: str | None = None
    dietary_tags: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    last_cooked_at: date | None = None

    ingredients: list[RecipeIngredient] = Relationship(
        back_populates="recipe",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
