from typing import Literal

from sqlalchemy import Column, JSON, String
from sqlmodel import Field, SQLModel

Tier = Literal["perishable", "semi_perishable", "staple"]


class Ingredient(SQLModel, table=True):
    __tablename__ = "ingredients"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    tier: Tier = Field(sa_column=Column(String, nullable=False))
    purchase_unit: str
    unit_conversions: dict[str, float] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    notes: str | None = None
