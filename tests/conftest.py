import os
import tempfile
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel


@pytest.fixture
def client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("RECIPE_PLANNER_DB_URL", f"sqlite:///{db_path}")

    import importlib
    import app.db as db_mod
    import app.main as main_mod
    import app.routes.health as health_mod
    import app.routes.ingredients as ingredients_mod

    importlib.reload(db_mod)
    importlib.reload(health_mod)
    importlib.reload(ingredients_mod)
    importlib.reload(main_mod)

    from app.models import User  # noqa: F401
    from app.models import Ingredient  # noqa: F401

    SQLModel.metadata.create_all(db_mod.engine)
    with db_mod.Session(db_mod.engine) as s:
        s.add(User(name="joe"))
        s.add(User(name="jessica"))
        s.commit()

    with TestClient(main_mod.app) as c:
        yield c
