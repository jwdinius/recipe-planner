from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class Rating(SQLModel, table=True):
    __tablename__ = "ratings"
    __table_args__ = (
        UniqueConstraint("user_id", "recipe_id", name="uq_ratings_user_recipe"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    recipe_id: int = Field(foreign_key="recipes.id", index=True)
    value: str
