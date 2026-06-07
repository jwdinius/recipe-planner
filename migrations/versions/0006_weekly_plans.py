"""create weekly_plans and weekly_plan_entries tables

Revision ID: 0006_weekly_plans
Revises: 0005_ratings
Create Date: 2026-06-07 18:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_weekly_plans"
down_revision: Union[str, Sequence[str], None] = "0005_ratings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "weekly_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("committed_at", sa.DateTime(), nullable=False),
        sa.Column("target_slots", sa.Integer(), nullable=False),
    )
    op.create_table(
        "weekly_plan_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("recipe_id", sa.Integer(), nullable=False),
        sa.Column("doubled", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["weekly_plans.id"],
            name="fk_weekly_plan_entries_plan_id",
        ),
        sa.ForeignKeyConstraint(
            ["recipe_id"], ["recipes.id"],
            name="fk_weekly_plan_entries_recipe_id",
        ),
    )
    op.create_index(
        "ix_weekly_plan_entries_plan_id",
        "weekly_plan_entries",
        ["plan_id"],
    )
    op.create_index(
        "ix_weekly_plan_entries_recipe_id",
        "weekly_plan_entries",
        ["recipe_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_weekly_plan_entries_recipe_id", table_name="weekly_plan_entries"
    )
    op.drop_index(
        "ix_weekly_plan_entries_plan_id", table_name="weekly_plan_entries"
    )
    op.drop_table("weekly_plan_entries")
    op.drop_table("weekly_plans")
