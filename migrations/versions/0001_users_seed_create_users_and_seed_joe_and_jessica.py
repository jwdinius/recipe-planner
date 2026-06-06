"""create users and seed joe and jessica

Revision ID: 0001_users_seed
Revises:
Create Date: 2026-06-06 15:29:52.036656

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_users_seed"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    users = op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.UniqueConstraint("name", name="uq_users_name"),
    )
    op.create_index("ix_users_name", "users", ["name"], unique=True)
    op.bulk_insert(users, [{"name": "joe"}, {"name": "jessica"}])


def downgrade() -> None:
    op.drop_index("ix_users_name", table_name="users")
    op.drop_table("users")
