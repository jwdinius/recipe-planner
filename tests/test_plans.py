import time

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


def _preview(client, **body):
    body.setdefault("user_id", 1)
    return client.post("/plans/preview", json=body)


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


@pytest.fixture
def capers_id(client) -> int:
    return _post_ingredient(
        client, "capers", tier="semi_perishable", purchase_unit="jar",
        unit_conversions={"tbsp": 0.1},
    )


# --- Validation ---------------------------------------------------------


def test_unknown_user_id_returns_422(client):
    r = _preview(client, user_id=999, target_slots=4)
    assert r.status_code == 422
    assert "unknown user_id" in r.json()["detail"]


def test_target_slots_below_range_rejected(client):
    r = _preview(client, target_slots=2)
    assert r.status_code == 422


def test_target_slots_above_range_rejected(client):
    r = _preview(client, target_slots=7)
    assert r.status_code == 422


def test_target_slots_defaults_to_four(client):
    for i in range(5):
        _post_recipe(client, f"r{i}")
    r = _preview(client)
    assert r.status_code == 200, r.text
    assert len(r.json()["plan"]) == 4


def test_unknown_pin_recipe_returns_422(client):
    _post_recipe(client, "r0")
    r = _preview(client, target_slots=3, pins=[{"recipe_id": 999}])
    assert r.status_code == 422
    assert "unknown recipe_id in pins" in r.json()["detail"]


def test_duplicate_pin_returns_422(client):
    rid = _post_recipe(client, "r0")
    r = _preview(
        client,
        target_slots=3,
        pins=[{"recipe_id": rid}, {"recipe_id": rid}],
    )
    assert r.status_code == 422


def test_no_feasible_plan_returns_422(client):
    # target_slots=4 but only 2 recipes available → infeasible (each
    # recipe can fill at most 2 slots when doubled, but we have 2 vars
    # of 2 slots each = 4. Hmm actually that's feasible. Let me drop
    # to only 1 recipe.)
    _post_recipe(client, "only")
    r = _preview(client, target_slots=4)
    assert r.status_code == 422


# --- Pins ---------------------------------------------------------------


def test_pin_forces_recipe_into_plan(client):
    pinned = _post_recipe(client, "must-have")
    for i in range(5):
        _post_recipe(client, f"filler {i}")
    r = _preview(
        client, target_slots=3, pins=[{"recipe_id": pinned}]
    )
    assert r.status_code == 200, r.text
    ids = [e["recipe_id"] for e in r.json()["plan"]]
    assert pinned in ids
    assert len(ids) == 3


def test_pin_doubled_consumes_two_slots(client):
    pinned = _post_recipe(client, "must-have-twice")
    for i in range(5):
        _post_recipe(client, f"filler {i}")
    r = _preview(
        client,
        target_slots=4,
        pins=[{"recipe_id": pinned, "doubled": True}],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    pinned_entry = next(e for e in body["plan"] if e["recipe_id"] == pinned)
    assert pinned_entry["doubled"] is True
    # 1 pinned (doubled, 2 slots) + 2 others (1 slot each) = 4
    assert len(body["plan"]) == 3


def test_pin_doubled_false_consumes_one_slot(client):
    pinned = _post_recipe(client, "single")
    for i in range(5):
        _post_recipe(client, f"filler {i}")
    r = _preview(
        client,
        target_slots=4,
        pins=[{"recipe_id": pinned, "doubled": False}],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    pinned_entry = next(e for e in body["plan"] if e["recipe_id"] == pinned)
    assert pinned_entry["doubled"] is False
    assert len(body["plan"]) == 4


# --- Hard exclude -------------------------------------------------------


def test_hard_excluded_recipe_never_appears(client):
    drop = _post_recipe(client, "dislike-me")
    for i in range(4):
        _post_recipe(client, f"filler {i}")
    client.post(
        "/ratings",
        json={"user_id": 1, "recipe_id": drop, "value": "dislike"},
    )
    r = _preview(client, target_slots=4)
    assert r.status_code == 200, r.text
    ids = [e["recipe_id"] for e in r.json()["plan"]]
    assert drop not in ids


def test_hard_excluded_pin_dropped_silently(client):
    # Per #7: pinning a hard-excluded recipe drops the pin (warnings #8).
    drop = _post_recipe(client, "dislike-me")
    for i in range(4):
        _post_recipe(client, f"filler {i}")
    client.post(
        "/ratings",
        json={"user_id": 1, "recipe_id": drop, "value": "dislike"},
    )
    r = _preview(client, target_slots=4, pins=[{"recipe_id": drop}])
    assert r.status_code == 200, r.text
    ids = [e["recipe_id"] for e in r.json()["plan"]]
    assert drop not in ids
    assert len(ids) == 4


# --- Kale interaction (the central case) -------------------------------


def test_kale_interaction_two_half_recipes_buy_one_bunch_zero_waste(
    client, kale_id
):
    # Two recipes each using 0.5 bunch of kale. With target_slots=2, the
    # solver should select both → demand=1 bunch → buy 1, waste 0.
    a = _post_recipe(
        client, "kale a", ingredients=[
            {"ingredient_id": kale_id, "quantity": 0.5, "unit": "bunch"},
        ],
    )
    b = _post_recipe(
        client, "kale b", ingredients=[
            {"ingredient_id": kale_id, "quantity": 0.5, "unit": "bunch"},
        ],
    )
    # Pad the library so target_slots=3 is feasible if needed.
    _post_recipe(client, "filler")
    r = _preview(client, target_slots=3, pins=[
        {"recipe_id": a}, {"recipe_id": b},
    ])
    assert r.status_code == 200, r.text
    body = r.json()
    kale = next(g for g in body["grocery_list"] if g["ingredient_id"] == kale_id)
    assert kale["quantity"] == 1
    assert kale["projected_waste"] == pytest.approx(0.0)


def test_one_kale_recipe_alone_buys_one_bunch_half_waste(client, kale_id):
    only_kale = _post_recipe(
        client, "kale solo", ingredients=[
            {"ingredient_id": kale_id, "quantity": 0.5, "unit": "bunch"},
        ],
    )
    _post_recipe(client, "filler 1")
    _post_recipe(client, "filler 2")
    r = _preview(client, target_slots=3, pins=[{"recipe_id": only_kale}])
    assert r.status_code == 200, r.text
    body = r.json()
    kale = next(g for g in body["grocery_list"] if g["ingredient_id"] == kale_id)
    assert kale["quantity"] == 1
    assert kale["projected_waste"] == pytest.approx(0.5)


def test_carryover_reduces_purchases(client, kale_id):
    only_kale = _post_recipe(
        client, "kale solo", ingredients=[
            {"ingredient_id": kale_id, "quantity": 0.5, "unit": "bunch"},
        ],
    )
    _post_recipe(client, "filler 1")
    _post_recipe(client, "filler 2")
    # Pantry already has the half-bunch we need.
    client.put(
        "/pantry",
        json=[{"ingredient_id": kale_id, "quantity": 0.5, "unit": "bunch"}],
    )
    r = _preview(client, target_slots=3, pins=[{"recipe_id": only_kale}])
    assert r.status_code == 200, r.text
    body = r.json()
    # Carryover covers demand → no purchase needed → not in grocery list.
    assert all(g["ingredient_id"] != kale_id for g in body["grocery_list"])


# --- Grocery list / staples --------------------------------------------


def test_staples_never_in_grocery_list(client, kale_id, olive_oil_id):
    # Pad with non-kale recipes so we can fill all 3 slots without forcing
    # the kale recipe in.
    pinned = _post_recipe(
        client, "kale+oil", ingredients=[
            {"ingredient_id": kale_id, "quantity": 0.5, "unit": "bunch"},
            {"ingredient_id": olive_oil_id, "quantity": 2.0, "unit": "tbsp"},
        ],
    )
    _post_recipe(client, "filler 1")
    _post_recipe(client, "filler 2")
    r = _preview(client, target_slots=3, pins=[{"recipe_id": pinned}])
    assert r.status_code == 200, r.text
    grocery = r.json()["grocery_list"]
    ids = [g["ingredient_id"] for g in grocery]
    assert olive_oil_id not in ids
    assert kale_id in ids


def test_grocery_item_has_required_fields(client, kale_id):
    pinned = _post_recipe(
        client, "kale", ingredients=[
            {"ingredient_id": kale_id, "quantity": 0.5, "unit": "bunch"},
        ],
    )
    _post_recipe(client, "filler 1")
    _post_recipe(client, "filler 2")
    r = _preview(client, target_slots=3, pins=[{"recipe_id": pinned}])
    assert r.status_code == 200, r.text
    item = r.json()["grocery_list"][0]
    assert set(item.keys()) == {
        "ingredient_id", "name", "purchase_unit", "quantity",
        "projected_waste",
    }
    assert item["purchase_unit"] == "bunch"
    assert item["name"] == "kale"


# --- Score breakdown ----------------------------------------------------


def test_score_breakdown_shape(client):
    for i in range(5):
        _post_recipe(client, f"r{i}")
    r = _preview(client)
    assert r.status_code == 200, r.text
    breakdown = r.json()["score_breakdown"]
    assert set(breakdown.keys()) == {"waste", "preference", "total"}
    assert breakdown["total"] == pytest.approx(
        breakdown["waste"] + breakdown["preference"]
    )


def test_preference_term_uses_negative_weight(client):
    # A loved+liked recipe (3 points) should produce preference = -3 * 3 = -9
    # for each such selected recipe. Set up: one recipe rated love+like, plus
    # 4 unrated fillers, pin the rated one to force it into the plan.
    rated = _post_recipe(client, "fan favorite")
    for i in range(4):
        _post_recipe(client, f"filler {i}")
    client.post(
        "/ratings",
        json={"user_id": 1, "recipe_id": rated, "value": "love"},
    )
    client.post(
        "/ratings",
        json={"user_id": 2, "recipe_id": rated, "value": "like"},
    )
    r = _preview(client, target_slots=3, pins=[{"recipe_id": rated}])
    assert r.status_code == 200, r.text
    pref = r.json()["score_breakdown"]["preference"]
    # The other 2 selected recipes have 0 preference points.
    assert pref == pytest.approx(-9.0)


def test_kale_waste_score_uses_perishable_multiplier(client, kale_id):
    # 1 kale recipe alone → 0.5 bunch waste, perishable tier mult = 3,
    # waste weight = 10 → 10 * 3 * 0.5 = 15.
    only_kale = _post_recipe(
        client, "kale solo", ingredients=[
            {"ingredient_id": kale_id, "quantity": 0.5, "unit": "bunch"},
        ],
    )
    _post_recipe(client, "filler 1")
    _post_recipe(client, "filler 2")
    r = _preview(client, target_slots=3, pins=[{"recipe_id": only_kale}])
    assert r.status_code == 200, r.text
    waste = r.json()["score_breakdown"]["waste"]
    assert waste == pytest.approx(15.0)


# --- Performance --------------------------------------------------------


def test_solver_sub_second_on_thirty_recipe_fixture(client, kale_id, capers_id):
    # 30 recipes, each using a varying amount of kale and/or capers, plus
    # one staple-free filler ingredient. Asserts the solver returns under
    # a second on a small library.
    other_id = _post_ingredient(
        client, "tomato", purchase_unit="lb",
        unit_conversions={"oz": 0.0625},
    )
    for i in range(30):
        ings: list[dict] = []
        if i % 3 == 0:
            ings.append(
                {"ingredient_id": kale_id, "quantity": 0.25 + (i % 4) * 0.1,
                 "unit": "bunch"}
            )
        if i % 4 == 0:
            ings.append(
                {"ingredient_id": capers_id, "quantity": 0.1 + (i % 3) * 0.05,
                 "unit": "jar"}
            )
        if i % 2 == 0:
            ings.append(
                {"ingredient_id": other_id, "quantity": 0.5,
                 "unit": "lb"}
            )
        _post_recipe(
            client, f"recipe {i}",
            cuisine="Italian" if i % 2 else "American",
            ingredients=ings,
        )
    t0 = time.monotonic()
    r = _preview(client, target_slots=4)
    elapsed = time.monotonic() - t0
    assert r.status_code == 200, r.text
    assert elapsed < 1.0, f"solver took {elapsed:.2f}s"
    assert len(r.json()["plan"]) > 0
