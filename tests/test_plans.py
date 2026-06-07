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
        _post_recipe(client, f"r{i}", cuisine=f"c{i}")
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
    pinned = _post_recipe(client, "must-have", cuisine="Italian")
    for i in range(5):
        _post_recipe(client, f"filler {i}", cuisine=f"c{i}")
    r = _preview(
        client, target_slots=3, pins=[{"recipe_id": pinned}]
    )
    assert r.status_code == 200, r.text
    ids = [e["recipe_id"] for e in r.json()["plan"]]
    assert pinned in ids
    assert len(ids) == 3


def test_pin_doubled_consumes_two_slots(client):
    pinned = _post_recipe(client, "must-have-twice", cuisine="Italian")
    for i in range(5):
        _post_recipe(client, f"filler {i}", cuisine=f"c{i}")
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
    pinned = _post_recipe(client, "single", cuisine="Italian")
    for i in range(5):
        _post_recipe(client, f"filler {i}", cuisine=f"c{i}")
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


def test_pin_overrides_hard_exclude_with_warning(client):
    # ADR-0003: pin wins over hard exclude; response carries a warning naming
    # the user(s) who excluded the recipe.
    pinned = _post_recipe(client, "dislike-me", cuisine="Italian")
    for i in range(4):
        _post_recipe(client, f"filler {i}", cuisine=f"c{i}")
    client.post(
        "/ratings",
        json={"user_id": 1, "recipe_id": pinned, "value": "dislike"},
    )
    r = _preview(client, target_slots=4, pins=[{"recipe_id": pinned}])
    assert r.status_code == 200, r.text
    body = r.json()
    ids = [e["recipe_id"] for e in body["plan"]]
    assert pinned in ids
    assert len(body["warnings"]) == 1
    w = body["warnings"][0]
    assert w["recipe_id"] == pinned
    assert w["excluding_user_ids"] == [1]
    assert "pin" in w["message"].lower()


def test_pin_overrides_hard_exclude_multiple_users(client):
    pinned = _post_recipe(client, "both-dislike", cuisine="Italian")
    for i in range(4):
        _post_recipe(client, f"filler {i}", cuisine=f"c{i}")
    for uid in (1, 2):
        client.post(
            "/ratings",
            json={"user_id": uid, "recipe_id": pinned, "value": "dislike"},
        )
    r = _preview(client, target_slots=4, pins=[{"recipe_id": pinned}])
    assert r.status_code == 200, r.text
    body = r.json()
    assert pinned in [e["recipe_id"] for e in body["plan"]]
    assert body["warnings"][0]["excluding_user_ids"] == [1, 2]


def test_no_warnings_when_no_pin_conflicts(client):
    for i in range(4):
        _post_recipe(client, f"r{i}", cuisine=f"c{i}")
    r = _preview(client, target_slots=4)
    assert r.status_code == 200, r.text
    assert r.json()["warnings"] == []


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
        _post_recipe(client, f"r{i}", cuisine=f"c{i}")
    r = _preview(client)
    assert r.status_code == 200, r.text
    breakdown = r.json()["score_breakdown"]
    assert set(breakdown.keys()) == {
        "waste", "preference", "recency", "variety", "total",
    }
    assert breakdown["total"] == pytest.approx(
        breakdown["waste"]
        + breakdown["preference"]
        + breakdown["recency"]
        + breakdown["variety"]
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


# --- Recency ------------------------------------------------------------


def test_never_cooked_recipe_earns_full_recency_reward(client):
    # Never-cooked recipes have recency_value = 1.0 → reward = -2 per recipe.
    # 3 pinned slots (none cooked) → recency contribution = -6.0.
    pins = []
    for i in range(3):
        rid = _post_recipe(client, f"never{i}", cuisine=f"c{i}")
        pins.append({"recipe_id": rid})
    _post_recipe(client, "filler", cuisine="filler")
    r = _preview(client, target_slots=3, pins=pins)
    assert r.status_code == 200, r.text
    recency = r.json()["score_breakdown"]["recency"]
    assert recency == pytest.approx(-6.0)


def test_recently_cooked_recipe_earns_zero_recency(client, session):
    # A recipe with last_cooked_at = today has weeks_since = 0 → value = 0 →
    # contributes nothing to recency. Compare with the never-cooked control.
    import datetime as _dt
    from app.models.recipe import Recipe

    rid = _post_recipe(client, "fresh", cuisine="solo")
    recipe = session.get(Recipe, rid)
    recipe.last_cooked_at = _dt.date.today()
    session.add(recipe)
    session.commit()

    _post_recipe(client, "p1", cuisine="x")
    _post_recipe(client, "p2", cuisine="y")
    r = _preview(client, target_slots=3, pins=[{"recipe_id": rid}])
    assert r.status_code == 200, r.text
    # 'fresh' contributes 0; the other 2 selected (never-cooked) contribute
    # -2 each → recency total = -4.
    recency = r.json()["score_breakdown"]["recency"]
    assert recency == pytest.approx(-4.0)


# --- Variety ------------------------------------------------------------


def test_three_same_cuisine_recipes_incur_variety_penalty_one(client):
    pins = []
    for i in range(3):
        rid = _post_recipe(client, f"italian{i}", cuisine="Italian")
        pins.append({"recipe_id": rid})
    _post_recipe(client, "spacer", cuisine="other")
    r = _preview(client, target_slots=3, pins=pins)
    assert r.status_code == 200, r.text
    variety = r.json()["score_breakdown"]["variety"]
    # excess = 3 - 2 = 1; w_variety = 5 → 5.0.
    assert variety == pytest.approx(5.0)


def test_four_same_cuisine_recipes_incur_variety_penalty_two(client):
    pins = []
    for i in range(4):
        rid = _post_recipe(client, f"italian{i}", cuisine="Italian")
        pins.append({"recipe_id": rid})
    _post_recipe(client, "spacer", cuisine="other")
    r = _preview(client, target_slots=4, pins=pins)
    assert r.status_code == 200, r.text
    variety = r.json()["score_breakdown"]["variety"]
    # excess = 4 - 2 = 2; w_variety = 5 → 10.0.
    assert variety == pytest.approx(10.0)


def test_two_same_cuisine_recipes_no_variety_penalty(client):
    pins = []
    for i in range(2):
        rid = _post_recipe(client, f"italian{i}", cuisine="Italian")
        pins.append({"recipe_id": rid})
    _post_recipe(client, "spacer", cuisine="other")
    r = _preview(client, target_slots=3, pins=pins)
    assert r.status_code == 200, r.text
    assert r.json()["score_breakdown"]["variety"] == pytest.approx(0.0)


# --- Per-request weight overrides ---------------------------------------


def test_weights_unknown_key_returns_422(client):
    _post_recipe(client, "r")
    r = _preview(client, target_slots=3, weights={"nope": 1.0})
    assert r.status_code == 422
    assert "unknown weight" in r.json()["detail"].lower()


def test_weights_partial_override_merges_with_defaults(client):
    # Verify a partial override keeps the other terms at their defaults by
    # spot-checking the preference contribution.
    rated = _post_recipe(client, "loved", cuisine="A")
    client.post(
        "/ratings",
        json={"user_id": 1, "recipe_id": rated, "value": "love"},
    )
    _post_recipe(client, "f1", cuisine="B")
    _post_recipe(client, "f2", cuisine="C")
    # Override only waste; preference should still be -3 * 2 = -6 for the
    # loved recipe.
    r = _preview(
        client, target_slots=3, pins=[{"recipe_id": rated}],
        weights={"waste": 0.0},
    )
    assert r.status_code == 200, r.text
    assert r.json()["score_breakdown"]["preference"] == pytest.approx(-6.0)


def test_weight_override_waste_zero_ignores_waste(client, kale_id):
    # A heavily-loved recipe wastes 0.5 bunch of kale. With waste=10
    # (default), the solver avoids it; with waste=0, the solver picks it for
    # its preference reward.
    # 1.1 bunches: neither single (0.9 waste) nor doubled (0.8 waste) fits
    # cleanly, so doubling can't sneak the recipe in past the waste term.
    high_waste_loved = _post_recipe(
        client, "loved-but-wasteful", cuisine="A",
        ingredients=[
            {"ingredient_id": kale_id, "quantity": 1.1, "unit": "bunch"},
        ],
    )
    for uid in (1, 2):
        client.post(
            "/ratings",
            json={"user_id": uid, "recipe_id": high_waste_loved,
                  "value": "love"},
        )
    clean_loved = _post_recipe(client, "clean-loved", cuisine="B")
    client.post(
        "/ratings",
        json={"user_id": 1, "recipe_id": clean_loved, "value": "love"},
    )
    _post_recipe(client, "filler1", cuisine="C")
    _post_recipe(client, "filler2", cuisine="D")

    # Default weights: high_waste excluded.
    r_default = _preview(client, target_slots=3)
    assert r_default.status_code == 200, r_default.text
    default_ids = [e["recipe_id"] for e in r_default.json()["plan"]]
    assert high_waste_loved not in default_ids

    # waste=0 override: high_waste in plan (preference wins).
    r_override = _preview(
        client, target_slots=3, weights={"waste": 0.0},
    )
    assert r_override.status_code == 200, r_override.text
    override_ids = [e["recipe_id"] for e in r_override.json()["plan"]]
    assert high_waste_loved in override_ids


def test_weight_override_variety_forces_cuisine_spread(client):
    # Three Italian + three Mexican recipes, all equally likable. With
    # variety=1000, target_slots=4, no more than 2 of either cuisine can
    # appear (excess penalty would dominate any other reward).
    italians = [
        _post_recipe(client, f"italian{i}", cuisine="Italian")
        for i in range(3)
    ]
    mexicans = [
        _post_recipe(client, f"mexican{i}", cuisine="Mexican")
        for i in range(3)
    ]
    r = _preview(
        client, target_slots=4, weights={"variety": 1000.0},
    )
    assert r.status_code == 200, r.text
    ids = [e["recipe_id"] for e in r.json()["plan"]]
    n_italian = sum(1 for rid in ids if rid in italians)
    n_mexican = sum(1 for rid in ids if rid in mexicans)
    assert n_italian <= 2
    assert n_mexican <= 2


def test_weight_override_does_not_mutate_defaults(client):
    # An override request must not leak into the next request's defaults.
    for i in range(5):
        _post_recipe(client, f"r{i}", cuisine=f"c{i}")
    client.post(
        "/plans/preview",
        json={"user_id": 1, "target_slots": 3, "weights": {"variety": 999.0}},
    )
    r = _preview(client, target_slots=3)
    assert r.status_code == 200, r.text
    # If defaults had been mutated, the variety term would still be inflated.
    # With 3 distinct cuisines selected from the 5 distinct-cuisine library,
    # variety should be 0.
    assert r.json()["score_breakdown"]["variety"] == pytest.approx(0.0)


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
