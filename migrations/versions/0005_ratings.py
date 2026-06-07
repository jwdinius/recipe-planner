"""create ratings table

Revision ID: 0005_ratings
Revises: 0004_pantry
Create Date: 2026-06-07 09:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_ratings"
down_revision: Union[str, Sequence[str], None] = "0004_pantry"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ratings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("recipe_id", sa.Integer(), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_ratings_user_id"
        ),
        sa.ForeignKeyConstraint(
            ["recipe_id"], ["recipes.id"], name="fk_ratings_recipe_id"
        ),
        sa.UniqueConstraint(
            "user_id", "recipe_id", name="uq_ratings_user_recipe"
        ),
    )
    op.create_index("ix_ratings_user_id", "ratings", ["user_id"])
    op.create_index("ix_ratings_recipe_id", "ratings", ["recipe_id"])


def downgrade() -> None:
    op.drop_index("ix_ratings_recipe_id", table_name="ratings")
    op.drop_index("ix_ratings_user_id", table_name="ratings")
    op.drop_table("ratings")
