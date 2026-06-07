from datetime import date, timedelta

import pytest

from app.services.carryover import carryover_fit
from app.services.scoring import (
    preference_value,
    recency_value,
    weeks_since,
)


# --- Ingredient + recipe fixtures ---------------------------------------


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


@pytest.fixture
def kale_id(client) -> int:
    return _post_ingredient(
        client,
        "kale",
        purchase_unit="bunch",
        unit_conversions={"cup chopped": 0.25, "oz": 0.05},
    )


@pytest.fixture
def capers_id(client) -> int:
    return _post_ingredient(
        client,
        "capers",
        tier="semi_perishable",
        purchase_unit="jar",
        unit_conversions={"tbsp": 0.1},
    )


# --- Scoring kernel -----------------------------------------------------


def test_recency_value_none_means_never_cooked():
    assert recency_value(None) == 1.0


@pytest.mark.parametrize(
    "weeks,expected",
    [(0.0, 0.0), (3.0, 0.5), (6.0, 1.0), (12.0, 1.0), (-1.0, 0.0)],
)
def test_recency_value_linear_ramp(weeks, expected):
    assert recency_value(weeks) == pytest.approx(expected)


def test_weeks_since_none_returns_none():
    assert weeks_since(None, date(2026, 6, 7)) is None


def test_weeks_since_two_weeks_ago():
    today = date(2026, 6, 7)
    assert weeks_since(today - timedelta(days=14), today) == pytest.approx(2.0)


def test_preference_value_combines_love_and_like(client, session):
    recipe_id = _post_recipe(client, "kale caesar")
    client.post(
        "/ratings",
        json={"user_id": 1, "recipe_id": recipe_id, "value": "love"},
    )
    client.post(
        "/ratings",
        json={"user_id": 2, "recipe_id": recipe_id, "value": "like"},
    )
    session.expire_all()
    assert preference_value(session, recipe_id) == pytest.approx(3.0)


# --- carryover_fit ------------------------------------------------------


def test_carryover_fit_zero_when_pantry_empty(client, session, kale_id):
    recipe_id = _post_recipe(
        client,
        "kale caesar",
        ingredients=[
            {"ingredient_id": kale_id, "quantity": 0.5, "unit": "bunch"}
        ],
    )
    fit = carryover_fit(session, recipe_id)
    assert fit.value == 0.0
    assert fit.overlap_ingredient_names == ()


def test_carryover_fit_zero_when_no_overlap(
    client, session, kale_id, capers_id
):
    recipe_id = _post_recipe(
        client,
        "kale caesar",
        ingredients=[
            {"ingredient_id": kale_id, "quantity": 0.5, "unit": "bunch"}
        ],
    )
    client.put(
        "/pantry",
        json=[{"ingredient_id": capers_id, "quantity": 0.5, "unit": "jar"}],
    )
    fit = carryover_fit(session, recipe_id)
    assert fit.value == 0.0
    assert fit.overlap_ingredient_names == ()


def test_carryover_fit_partial_consumption(client, session, kale_id):
    # Recipe needs 0.25 bunches; pantry has 0.5 bunch → consumes half.
    recipe_id = _post_recipe(
        client,
        "kale caesar",
        ingredients=[
            {"ingredient_id": kale_id, "quantity": 0.25, "unit": "bunch"}
        ],
    )
    client.put(
        "/pantry",
        json=[{"ingredient_id": kale_id, "quantity": 0.5, "unit": "bunch"}],
    )
    session.expire_all()
    fit = carryover_fit(session, recipe_id)
    assert fit.value == pytest.approx(0.5)
    assert fit.overlap_ingredient_names == ("kale",)


def test_carryover_fit_caps_at_one_when_recipe_exceeds_pantry(
    client, session, kale_id
):
    # Recipe needs 1 bunch; pantry has 0.25 → fit capped at 1.0.
    recipe_id = _post_recipe(
        client,
        "kale caesar",
        ingredients=[
            {"ingredient_id": kale_id, "quantity": 1.0, "unit": "bunch"}
        ],
    )
    client.put(
        "/pantry",
        json=[{"ingredient_id": kale_id, "quantity": 0.25, "unit": "bunch"}],
    )
    session.expire_all()
    fit = carryover_fit(session, recipe_id)
    assert fit.value == pytest.approx(1.0)


def test_carryover_fit_unit_conversion(client, session, kale_id):
    # Recipe needs 4 cups chopped = 1 bunch. Pantry has 0.5 bunch.
    # → fit = min(1.0, 1 / 0.5) = 1.0.
    recipe_id = _post_recipe(
        client,
        "kale caesar",
        ingredients=[
            {"ingredient_id": kale_id, "quantity": 4.0, "unit": "cup chopped"}
        ],
    )
    client.put(
        "/pantry",
        json=[{"ingredient_id": kale_id, "quantity": 0.5, "unit": "bunch"}],
    )
    session.expire_all()
    fit = carryover_fit(session, recipe_id)
    assert fit.value == pytest.approx(1.0)
    assert fit.overlap_ingredient_names == ("kale",)


# --- Route --------------------------------------------------------------


def test_route_requires_user_id(client):
    assert client.get("/recommendations").status_code == 422


def test_route_rejects_unknown_user(client):
    r = client.get("/recommendations", params={"user_id": 999})
    assert r.status_code == 422
    assert "unknown user_id" in r.json()["detail"]


def test_route_returns_empty_when_no_recipes(client):
    r = client.get("/recommendations", params={"user_id": 1})
    assert r.status_code == 200
    assert r.json() == []


def test_route_respects_limit(client):
    for i in range(5):
        _post_recipe(client, f"recipe {i}")
    r = client.get("/recommendations", params={"user_id": 1, "limit": 3})
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 3


def test_route_returns_fewer_when_pool_smaller_than_limit(client):
    _post_recipe(client, "only one")
    r = client.get("/recommendations", params={"user_id": 1, "limit": 10})
    assert len(r.json()) == 1


def test_hard_excluded_recipe_never_appears(client):
    keep_id = _post_recipe(client, "keep")
    drop_id = _post_recipe(client, "drop")
    client.post(
        "/ratings",
        json={"user_id": 1, "recipe_id": drop_id, "value": "dislike"},
    )
    r = client.get("/recommendations", params={"user_id": 1, "limit": 10})
    ids = [item["recipe_id"] for item in r.json()]
    assert keep_id in ids
    assert drop_id not in ids


def test_carryover_badge_surfaces(client, kale_id):
    recipe_id = _post_recipe(
        client,
        "kale caesar",
        ingredients=[
            {"ingredient_id": kale_id, "quantity": 0.25, "unit": "bunch"}
        ],
    )
    client.put(
        "/pantry",
        json=[{"ingredient_id": kale_id, "quantity": 0.5, "unit": "bunch"}],
    )
    r = client.get("/recommendations", params={"user_id": 1, "limit": 10})
    item = next(x for x in r.json() if x["recipe_id"] == recipe_id)
    assert item["badges"] == ["uses your kale carryover"]
    assert item["breakdown"]["carryover_fit"] == pytest.approx(0.5)


def test_breakdown_populated_for_each_item(client):
    recipe_id = _post_recipe(client, "plain")
    r = client.get("/recommendations", params={"user_id": 1, "limit": 10})
    item = next(x for x in r.json() if x["recipe_id"] == recipe_id)
    assert set(item["breakdown"].keys()) == {
        "preference",
        "recency",
        "carryover_fit",
    }


# --- Diversification ----------------------------------------------------


def test_diversification_alternates_cuisines_under_tied_scores(client):
    # Four recipes, two of each cuisine, no ratings → all preference=0, all
    # recency=1.0 (never cooked), carryover=0. Raw scores tied.
    # Diversification should not place both Italians back-to-back at top.
    italian_a = _post_recipe(client, "pasta a", cuisine="Italian")
    italian_b = _post_recipe(client, "pasta b", cuisine="Italian")
    american_a = _post_recipe(client, "burger a", cuisine="American")
    american_b = _post_recipe(client, "burger b", cuisine="American")

    r = client.get("/recommendations", params={"user_id": 1, "limit": 4})
    body = r.json()
    assert len(body) == 4

    # Map recipe_id back to cuisine for the assertion.
    cuisines = {
        italian_a: "Italian",
        italian_b: "Italian",
        american_a: "American",
        american_b: "American",
    }
    order = [cuisines[item["recipe_id"]] for item in body]
    # Greedy: first pick by score+id tiebreak, then diversify. The second
    # pick must be the other cuisine because same-cuisine carries the
    # similarity penalty.
    assert order[0] != order[1]
    # Third pick reverts to the original first cuisine (the only remaining
    # of the other cuisine has the highest penalty).
    assert order[2] != order[1]


def test_response_is_deterministic_for_same_db_state(client):
    for i in range(4):
        _post_recipe(client, f"r{i}", cuisine="American" if i % 2 else "Italian")
    a = client.get("/recommendations", params={"user_id": 1, "limit": 4}).json()
    b = client.get("/recommendations", params={"user_id": 1, "limit": 4}).json()
    assert [x["recipe_id"] for x in a] == [x["recipe_id"] for x in b]
