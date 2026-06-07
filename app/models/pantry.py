from datetime import date

from sqlmodel import Field, SQLModel


class PantryEntry(SQLModel, table=True):
    __tablename__ = "pantry_entries"

    id: int | None = Field(default=None, primary_key=True)
    ingredient_id: int = Field(
        foreign_key="ingredients.id", unique=True, index=True
    )
    quantity: float
    unit: str
    as_of: date | None = None
