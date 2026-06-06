"""create recipes and recipe_ingredients tables

Revision ID: 0003_recipes
Revises: 0002_ingredients
Create Date: 2026-06-06 23:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_recipes"
down_revision: Union[str, Sequence[str], None] = "0002_ingredients"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "recipes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("cuisine", sa.String(), nullable=False),
        sa.Column("prep_minutes", sa.Integer(), nullable=False),
        sa.Column("cook_minutes", sa.Integer(), nullable=False),
        sa.Column("instructions", sa.String(), nullable=False),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column("dietary_tags", sa.JSON(), nullable=False),
        sa.Column("last_cooked_at", sa.Date(), nullable=True),
    )
    op.create_index("ix_recipes_title", "recipes", ["title"])
    op.create_index("ix_recipes_cuisine", "recipes", ["cuisine"])

    op.create_table(
        "recipe_ingredients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("recipe_id", sa.Integer(), nullable=False),
        sa.Column("ingredient_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["recipe_id"], ["recipes.id"], name="fk_recipe_ingredients_recipe_id"
        ),
        sa.ForeignKeyConstraint(
            ["ingredient_id"],
            ["ingredients.id"],
            name="fk_recipe_ingredients_ingredient_id",
        ),
    )
    op.create_index(
        "ix_recipe_ingredients_recipe_id", "recipe_ingredients", ["recipe_id"]
    )
    op.create_index(
        "ix_recipe_ingredients_ingredient_id",
        "recipe_ingredients",
        ["ingredient_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_recipe_ingredients_ingredient_id", table_name="recipe_ingredients"
    )
    op.drop_index("ix_recipe_ingredients_recipe_id", table_name="recipe_ingredients")
    op.drop_table("recipe_ingredients")
    op.drop_index("ix_recipes_cuisine", table_name="recipes")
    op.drop_index("ix_recipes_title", table_name="recipes")
    op.drop_table("recipes")
