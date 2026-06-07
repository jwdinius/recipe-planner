"""create pantry_entries table

Revision ID: 0004_pantry
Revises: 0003_recipes
Create Date: 2026-06-06 23:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_pantry"
down_revision: Union[str, Sequence[str], None] = "0003_recipes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pantry_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ingredient_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(
            ["ingredient_id"],
            ["ingredients.id"],
            name="fk_pantry_entries_ingredient_id",
        ),
        sa.UniqueConstraint("ingredient_id", name="uq_pantry_entries_ingredient_id"),
    )
    op.create_index(
        "ix_pantry_entries_ingredient_id",
        "pantry_entries",
        ["ingredient_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_pantry_entries_ingredient_id", table_name="pantry_entries")
    op.drop_table("pantry_entries")
