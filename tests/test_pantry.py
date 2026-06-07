import pytest


@pytest.fixture
def kale_id(client) -> int:
    r = client.post(
        "/ingredients",
        json={
            "name": "kale",
            "tier": "perishable",
            "purchase_unit": "bunch",
            "unit_conversions": {"cup chopped": 0.25, "oz": 0.05},
        },
    )
    return r.json()["id"]


@pytest.fixture
def capers_id(client) -> int:
    r = client.post(
        "/ingredients",
        json={
            "name": "capers",
            "tier": "semi_perishable",
            "purchase_unit": "jar",
            "unit_conversions": {"tbsp": 0.1},
        },
    )
    return r.json()["id"]


@pytest.fixture
def olive_oil_id(client) -> int:
    r = client.post(
        "/ingredients",
        json={
            "name": "olive oil",
            "tier": "staple",
            "purchase_unit": "bottle",
            "unit_conversions": {"tbsp": 0.02},
        },
    )
    return r.json()["id"]


def test_get_empty_pantry(client):
    r = client.get("/pantry")
    assert r.status_code == 200
    assert r.json() == []


def test_put_replaces_entire_pantry(client, kale_id, capers_id):
    r = client.put(
        "/pantry",
        json=[
            {"ingredient_id": kale_id, "quantity": 0.5, "unit": "bunch", "as_of": "2026-06-01"},
            {"ingredient_id": capers_id, "quantity": 0.75, "unit": "jar"},
        ],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 2
    by_name = {e["ingredient"]["name"]: e for e in body}
    assert by_name["kale"]["quantity"] == 0.5
    assert by_name["kale"]["unit"] == "bunch"
    assert by_name["kale"]["as_of"] == "2026-06-01"
    assert by_name["kale"]["ingredient"]["tier"] == "perishable"
    assert by_name["kale"]["ingredient"]["purchase_unit"] == "bunch"
    assert by_name["capers"]["quantity"] == 0.75
    assert by_name["capers"]["as_of"] is None

    # Replace with a different shape — previous entries gone.
    r = client.put(
        "/pantry",
        json=[
            {"ingredient_id": kale_id, "quantity": 1.0, "unit": "bunch"},
        ],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 1
    assert body[0]["ingredient_id"] == kale_id
    assert body[0]["quantity"] == 1.0

    # And GET agrees.
    r = client.get("/pantry")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_put_empty_clears_pantry(client, kale_id):
    client.put(
        "/pantry",
        json=[{"ingredient_id": kale_id, "quantity": 0.5, "unit": "bunch"}],
    )
    r = client.put("/pantry", json=[])
    assert r.status_code == 200
    assert r.json() == []


def test_put_rejects_staple(client, olive_oil_id):
    r = client.put(
        "/pantry",
        json=[{"ingredient_id": olive_oil_id, "quantity": 0.5, "unit": "bottle"}],
    )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "staple" in detail
    assert "olive oil" in detail


def test_put_rejects_unknown_ingredient(client):
    r = client.put(
        "/pantry",
        json=[{"ingredient_id": 9999, "quantity": 0.5, "unit": "bunch"}],
    )
    assert r.status_code == 422
    assert "9999" in r.json()["detail"]


def test_put_rejects_undefined_unit(client, kale_id):
    r = client.put(
        "/pantry",
        json=[{"ingredient_id": kale_id, "quantity": 0.5, "unit": "kilogram"}],
    )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "kale" in detail
    assert "kilogram" in detail


def test_put_rejects_duplicate_ingredient_ids(client, kale_id):
    r = client.put(
        "/pantry",
        json=[
            {"ingredient_id": kale_id, "quantity": 0.5, "unit": "bunch"},
            {"ingredient_id": kale_id, "quantity": 0.25, "unit": "bunch"},
        ],
    )
    assert r.status_code == 422
    assert "duplicate" in r.json()["detail"]


def test_patch_adds_new_entry(client, kale_id):
    r = client.patch(
        "/pantry",
        json=[{"ingredient_id": kale_id, "quantity_delta": 0.5, "unit": "bunch"}],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 1
    assert body[0]["ingredient_id"] == kale_id
    assert body[0]["quantity"] == 0.5
    assert body[0]["unit"] == "bunch"
    assert body[0]["as_of"] is None


def test_patch_skips_new_entry_with_nonpositive_delta(client, kale_id):
    r = client.patch(
        "/pantry",
        json=[{"ingredient_id": kale_id, "quantity_delta": -0.5, "unit": "bunch"}],
    )
    assert r.status_code == 200
    assert r.json() == []


def test_patch_increments_existing_entry_preserving_as_of(client, kale_id):
    client.put(
        "/pantry",
        json=[
            {
                "ingredient_id": kale_id,
                "quantity": 0.5,
                "unit": "bunch",
                "as_of": "2026-06-01",
            }
        ],
    )
    r = client.patch(
        "/pantry",
        json=[{"ingredient_id": kale_id, "quantity_delta": 0.25, "unit": "bunch"}],
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["quantity"] == 0.75
    assert body[0]["as_of"] == "2026-06-01"


def test_patch_subtract_to_zero_deletes_row(client, kale_id, capers_id):
    client.put(
        "/pantry",
        json=[
            {"ingredient_id": kale_id, "quantity": 0.5, "unit": "bunch"},
            {"ingredient_id": capers_id, "quantity": 0.75, "unit": "jar"},
        ],
    )
    r = client.patch(
        "/pantry",
        json=[
            {"ingredient_id": kale_id, "quantity_delta": -0.5, "unit": "bunch"},
        ],
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["ingredient_id"] == capers_id


def test_patch_subtract_below_zero_deletes_row(client, kale_id):
    client.put(
        "/pantry",
        json=[{"ingredient_id": kale_id, "quantity": 0.3, "unit": "bunch"}],
    )
    r = client.patch(
        "/pantry",
        json=[{"ingredient_id": kale_id, "quantity_delta": -1.0, "unit": "bunch"}],
    )
    assert r.status_code == 200
    assert r.json() == []


def test_patch_rejects_staple(client, olive_oil_id):
    r = client.patch(
        "/pantry",
        json=[
            {"ingredient_id": olive_oil_id, "quantity_delta": 0.5, "unit": "bottle"}
        ],
    )
    assert r.status_code == 422
    assert "staple" in r.json()["detail"]


def test_patch_rejects_unit_mismatch_against_existing(client, kale_id):
    client.put(
        "/pantry",
        json=[{"ingredient_id": kale_id, "quantity": 0.5, "unit": "bunch"}],
    )
    r = client.patch(
        "/pantry",
        json=[
            {
                "ingredient_id": kale_id,
                "quantity_delta": 0.5,
                "unit": "cup chopped",
            }
        ],
    )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "bunch" in detail
    assert "cup chopped" in detail


def test_patch_rejects_unknown_ingredient(client):
    r = client.patch(
        "/pantry",
        json=[{"ingredient_id": 9999, "quantity_delta": 0.5, "unit": "bunch"}],
    )
    assert r.status_code == 422
    assert "9999" in r.json()["detail"]


def test_patch_rejects_undefined_unit_for_new_entry(client, kale_id):
    r = client.patch(
        "/pantry",
        json=[
            {"ingredient_id": kale_id, "quantity_delta": 0.5, "unit": "kilogram"}
        ],
    )
    assert r.status_code == 422
    assert "kilogram" in r.json()["detail"]


def test_patch_rejects_duplicate_ingredient_ids(client, kale_id):
    r = client.patch(
        "/pantry",
        json=[
            {"ingredient_id": kale_id, "quantity_delta": 0.5, "unit": "bunch"},
            {"ingredient_id": kale_id, "quantity_delta": 0.25, "unit": "bunch"},
        ],
    )
    assert r.status_code == 422
    assert "duplicate" in r.json()["detail"]


def test_put_leaves_no_staples_in_a_mixed_batch(client, kale_id, olive_oil_id):
    r = client.put(
        "/pantry",
        json=[
            {"ingredient_id": kale_id, "quantity": 0.5, "unit": "bunch"},
            {"ingredient_id": olive_oil_id, "quantity": 0.1, "unit": "bottle"},
        ],
    )
    assert r.status_code == 422
    # And nothing was persisted.
    r = client.get("/pantry")
    assert r.json() == []
