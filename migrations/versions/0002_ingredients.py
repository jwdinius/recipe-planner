"""create ingredients table

Revision ID: 0002_ingredients
Revises: 0001_users_seed
Create Date: 2026-06-06 22:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_ingredients"
down_revision: Union[str, Sequence[str], None] = "0001_users_seed"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ingredients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("tier", sa.String(), nullable=False),
        sa.Column("purchase_unit", sa.String(), nullable=False),
        sa.Column("unit_conversions", sa.JSON(), nullable=False),
        sa.Column("notes", sa.String(), nullable=True),
        sa.UniqueConstraint("name", name="uq_ingredients_name"),
    )
    op.create_index("ix_ingredients_name", "ingredients", ["name"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_ingredients_name", table_name="ingredients")
    op.drop_table("ingredients")
