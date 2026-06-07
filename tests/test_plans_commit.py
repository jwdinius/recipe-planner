from datetime import date

import pytest


# --- Helpers ------------------------------------------------------------


def _post_ingredient(
    client,
    name: str,
    tier: str = "perishable",
    purchase_unit: str = "bunch",
    unit_conversions: dict[str, float] | None = None,
) -> int:
    r = client.post(
        "/ingredients",
        json={
            "name": name,
            "tier": tier,
            "purchase_unit": purchase_unit,
            "unit_conversions": unit_conversions or {},
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _post_recipe(
    client,
    title: str,
    cuisine: str = "American",
    ingredients: list[dict] | None = None,
) -> int:
    r = client.post(
        "/recipes",
        json={
            "title": title,
            "cuisine": cuisine,
            "prep_minutes": 10,
            "cook_minutes": 15,
            "instructions": "toss",
            "dietary_tags": [],
            "ingredients": ingredients or [],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _commit(client, **body):
    body.setdefault("user_id", 1)
    return client.post("/plans/commit", json=body)


@pytest.fixture
def kale_id(client) -> int:
    return _post_ingredient(
        client, "kale", purchase_unit="bunch",
        unit_conversions={"cup chopped": 0.25},
    )


@pytest.fixture
def olive_oil_id(client) -> int:
    return _post_ingredient(
        client, "olive oil", tier="staple", purchase_unit="bottle",
        unit_conversions={"tbsp": 0.01},
    )


# --- Validation ---------------------------------------------------------


def test_commit_validates_user_id(client):
    r = _commit(client, user_id=999, target_slots=3)
    assert r.status_code == 422
    assert "unknown user_id" in r.json()["detail"]


def test_commit_unknown_pin_recipe_returns_422(client):
    _post_recipe(client, "r0")
    r = _commit(client, target_slots=3, pins=[{"recipe_id": 999}])
    assert r.status_code == 422


def test_commit_infeasible_returns_422(client):
    rid = _post_recipe(client, "lonely")
    r = _commit(client, target_slots=4)
    assert r.status_code == 422
    recipe = client.get(f"/recipes/{rid}").json()
    assert recipe["last_cooked_at"] is None


# --- End-to-end commit --------------------------------------------------


def test_commit_persists_weekly_plan_and_entries(client, session):
    from app.models.weekly_plan import WeeklyPlan, WeeklyPlanEntry

    for i in range(5):
        _post_recipe(client, f"r{i}", cuisine=f"c{i}")
    r = _commit(client, target_slots=3)
    assert r.status_code == 200, r.text
    body = r.json()

    plans = session.exec(
        __import__("sqlmodel").select(WeeklyPlan)
    ).all()
    assert len(plans) == 1
    assert plans[0].id == body["plan_id"]
    assert plans[0].target_slots == 3

    entries = session.exec(
        __import__("sqlmodel").select(WeeklyPlanEntry).where(
            WeeklyPlanEntry.plan_id == body["plan_id"]
        )
    ).all()
    persisted_ids = sorted(e.recipe_id for e in entries)
    response_ids = sorted(e["recipe_id"] for e in body["plan"])
    assert persisted_ids == response_ids


def test_commit_advances_last_cooked_at_for_selected_recipes(client):
    today = date.today()
    rids = [_post_recipe(client, f"r{i}", cuisine=f"c{i}") for i in range(5)]
    r = _commit(client, target_slots=3)
    assert r.status_code == 200, r.text

    selected = {e["recipe_id"] for e in r.json()["plan"]}
    for rid in rids:
        recipe = client.get(f"/recipes/{rid}").json()
        if rid in selected:
            assert recipe["last_cooked_at"] == today.isoformat()
        else:
            assert recipe["last_cooked_at"] is None


def test_commit_advances_last_cooked_for_doubled_too(client):
    pinned = _post_recipe(client, "double-me", cuisine="A")
    for i in range(3):
        _post_recipe(client, f"f{i}", cuisine=f"c{i}")
    r = _commit(
        client, target_slots=4,
        pins=[{"recipe_id": pinned, "doubled": True}],
    )
    assert r.status_code == 200, r.text
    recipe = client.get(f"/recipes/{pinned}").json()
    assert recipe["last_cooked_at"] == date.today().isoformat()


# --- Pantry recompute ---------------------------------------------------


def test_commit_pantry_diff_basic_kale(client, kale_id):
    # One kale recipe demands 0.5 bunch; buy 1 → 0.5 bunch projected
    # carryover.
    pinned = _post_recipe(
        client, "kale solo", cuisine="A",
        ingredients=[
            {"ingredient_id": kale_id, "quantity": 0.5, "unit": "bunch"},
        ],
    )
    _post_recipe(client, "f1", cuisine="B")
    _post_recipe(client, "f2", cuisine="C")
    r = _commit(client, target_slots=3, pins=[{"recipe_id": pinned}])
    assert r.status_code == 200, r.text
    body = r.json()
    kale = next(p for p in body["projected_pantry"] if p["ingredient_id"] == kale_id)
    assert kale["quantity"] == pytest.approx(0.5)
    assert kale["purchase_unit"] == "bunch"

    # Pantry GET reflects the projection.
    pantry = client.get("/pantry").json()
    kale_entry = next(p for p in pantry if p["ingredient_id"] == kale_id)
    assert kale_entry["quantity"] == pytest.approx(0.5)
    assert kale_entry["unit"] == "bunch"


def test_commit_pantry_carryover_consumed(client, kale_id):
    # Start with 0.5 bunch kale in the pantry; a single 0.5-bunch recipe
    # consumes it exactly → no purchase, no projected carryover.
    pinned = _post_recipe(
        client, "kale solo", cuisine="A",
        ingredients=[
            {"ingredient_id": kale_id, "quantity": 0.5, "unit": "bunch"},
        ],
    )
    _post_recipe(client, "f1", cuisine="B")
    _post_recipe(client, "f2", cuisine="C")
    client.put(
        "/pantry",
        json=[{"ingredient_id": kale_id, "quantity": 0.5, "unit": "bunch"}],
    )
    r = _commit(client, target_slots=3, pins=[{"recipe_id": pinned}])
    assert r.status_code == 200, r.text
    body = r.json()
    assert all(
        p["ingredient_id"] != kale_id for p in body["projected_pantry"]
    )
    pantry = client.get("/pantry").json()
    assert all(p["ingredient_id"] != kale_id for p in pantry)


def test_commit_pantry_preserves_untouched_perishables(client, kale_id):
    # Untouched ingredients in the current pantry survive the commit.
    capers_id = _post_ingredient(
        client, "capers", tier="semi_perishable", purchase_unit="jar",
    )
    pinned = _post_recipe(
        client, "kale solo", cuisine="A",
        ingredients=[
            {"ingredient_id": kale_id, "quantity": 0.5, "unit": "bunch"},
        ],
    )
    _post_recipe(client, "f1", cuisine="B")
    _post_recipe(client, "f2", cuisine="C")
    client.put(
        "/pantry",
        json=[{"ingredient_id": capers_id, "quantity": 0.3, "unit": "jar"}],
    )
    r = _commit(client, target_slots=3, pins=[{"recipe_id": pinned}])
    assert r.status_code == 200, r.text
    pantry = client.get("/pantry").json()
    capers_entry = next(p for p in pantry if p["ingredient_id"] == capers_id)
    assert capers_entry["quantity"] == pytest.approx(0.3)


def test_commit_pantry_never_writes_staples(client, kale_id, olive_oil_id):
    # A staple in the recipe must not appear in projected pantry or pantry GET
    # even though it's purchased / demanded.
    pinned = _post_recipe(
        client, "kale + oil", cuisine="A",
        ingredients=[
            {"ingredient_id": kale_id, "quantity": 0.5, "unit": "bunch"},
            {"ingredient_id": olive_oil_id, "quantity": 2.0, "unit": "tbsp"},
        ],
    )
    _post_recipe(client, "f1", cuisine="B")
    _post_recipe(client, "f2", cuisine="C")
    r = _commit(client, target_slots=3, pins=[{"recipe_id": pinned}])
    assert r.status_code == 200, r.text
    body = r.json()
    assert all(
        p["ingredient_id"] != olive_oil_id for p in body["projected_pantry"]
    )
    # Staples never appear in grocery list either.
    assert all(
        g["ingredient_id"] != olive_oil_id for g in body["grocery_list"]
    )
    pantry = client.get("/pantry").json()
    assert all(p["ingredient_id"] != olive_oil_id for p in pantry)


def test_commit_pantry_doubled_consumes_double_demand(client, kale_id):
    # Pinned doubled recipe: 0.5 bunch × 2 = 1.0 bunch demand. Buy 1 bunch.
    # Projected carryover = 0 (dropped).
    pinned = _post_recipe(
        client, "kale solo", cuisine="A",
        ingredients=[
            {"ingredient_id": kale_id, "quantity": 0.5, "unit": "bunch"},
        ],
    )
    _post_recipe(client, "f1", cuisine="B")
    _post_recipe(client, "f2", cuisine="C")
    r = _commit(
        client, target_slots=3,
        pins=[{"recipe_id": pinned, "doubled": True}],
    )
    assert r.status_code == 200, r.text
    pantry = client.get("/pantry").json()
    assert all(p["ingredient_id"] != kale_id for p in pantry)


# --- Rollback / atomicity ----------------------------------------------


def test_infeasible_commit_does_not_touch_pantry_or_recipes(
    client, kale_id, session,
):
    from app.models.weekly_plan import WeeklyPlan
    import sqlmodel

    # Seed pantry, then attempt a guaranteed-infeasible commit.
    _post_recipe(client, "lonely", cuisine="A")
    client.put(
        "/pantry",
        json=[{"ingredient_id": kale_id, "quantity": 0.7, "unit": "bunch"}],
    )
    r = _commit(client, target_slots=4)
    assert r.status_code == 422

    plans = session.exec(sqlmodel.select(WeeklyPlan)).all()
    assert plans == []
    pantry = client.get("/pantry").json()
    assert len(pantry) == 1
    assert pantry[0]["ingredient_id"] == kale_id
    assert pantry[0]["quantity"] == pytest.approx(0.7)
