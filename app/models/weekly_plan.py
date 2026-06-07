from datetime import datetime

from sqlmodel import Field, Relationship, SQLModel


class WeeklyPlanEntry(SQLModel, table=True):
    __tablename__ = "weekly_plan_entries"

    id: int | None = Field(default=None, primary_key=True)
    plan_id: int = Field(foreign_key="weekly_plans.id", index=True)
    recipe_id: int = Field(foreign_key="recipes.id", index=True)
    doubled: bool = False

    plan: "WeeklyPlan" = Relationship(back_populates="entries")


class WeeklyPlan(SQLModel, table=True):
    __tablename__ = "weekly_plans"

    id: int | None = Field(default=None, primary_key=True)
    committed_at: datetime
    target_slots: int

    entries: list[WeeklyPlanEntry] = Relationship(
        back_populates="plan",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
