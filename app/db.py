import os
from collections.abc import Iterator

from sqlmodel import Session, create_engine

DATABASE_URL = os.environ.get("RECIPE_PLANNER_DB_URL", "sqlite:///recipe-planner.db")

engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
