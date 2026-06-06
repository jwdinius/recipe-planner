KALE = {
    "name": "kale",
    "tier": "perishable",
    "purchase_unit": "bunch",
    "unit_conversions": {"cup chopped": 0.25, "oz": 0.05},
    "notes": None,
}


def test_create_and_get_kale_roundtrip(client):
    r = client.post("/ingredients", json=KALE)
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["id"] > 0
    assert created["name"] == "kale"
    assert created["tier"] == "perishable"
    assert created["purchase_unit"] == "bunch"
    assert created["unit_conversions"] == {"cup chopped": 0.25, "oz": 0.05}
    assert created["notes"] is None

    r = client.get(f"/ingredients/{created['id']}")
    assert r.status_code == 200
    assert r.json() == created


def test_list_ingredients(client):
    client.post("/ingredients", json=KALE)
    client.post(
        "/ingredients",
        json={
            "name": "olive oil",
            "tier": "staple",
            "purchase_unit": "bottle",
            "unit_conversions": {"tbsp": 0.02},
        },
    )

    r = client.get("/ingredients")
    assert r.status_code == 200
    names = [i["name"] for i in r.json()]
    assert names == ["kale", "olive oil"]


def test_create_duplicate_name_returns_409(client):
    r = client.post("/ingredients", json=KALE)
    assert r.status_code == 201
    r = client.post("/ingredients", json=KALE)
    assert r.status_code == 409


def test_invalid_tier_rejected(client):
    bad = {**KALE, "tier": "spicy"}
    r = client.post("/ingredients", json=bad)
    assert r.status_code == 422


def test_patch_merges_unit_conversions(client):
    r = client.post("/ingredients", json=KALE)
    ingredient_id = r.json()["id"]

    r = client.patch(
        f"/ingredients/{ingredient_id}",
        json={"unit_conversions": {"cup chopped": 0.3, "g": 0.002}, "notes": "from farmers market"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["unit_conversions"] == {
        "cup chopped": 0.3,
        "oz": 0.05,
        "g": 0.002,
    }
    assert body["notes"] == "from farmers market"
    assert body["tier"] == "perishable"
    assert body["purchase_unit"] == "bunch"


def test_patch_other_fields(client):
    r = client.post("/ingredients", json=KALE)
    ingredient_id = r.json()["id"]

    r = client.patch(
        f"/ingredients/{ingredient_id}",
        json={"tier": "semi_perishable", "purchase_unit": "head"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["tier"] == "semi_perishable"
    assert body["purchase_unit"] == "head"
    assert body["unit_conversions"] == {"cup chopped": 0.25, "oz": 0.05}


def test_delete_ingredient(client):
    r = client.post("/ingredients", json=KALE)
    ingredient_id = r.json()["id"]

    r = client.delete(f"/ingredients/{ingredient_id}")
    assert r.status_code == 204

    r = client.get(f"/ingredients/{ingredient_id}")
    assert r.status_code == 404


def test_get_missing_returns_404(client):
    r = client.get("/ingredients/9999")
    assert r.status_code == 404


def test_patch_missing_returns_404(client):
    r = client.patch("/ingredients/9999", json={"notes": "x"})
    assert r.status_code == 404


def test_delete_missing_returns_404(client):
    r = client.delete("/ingredients/9999")
    assert r.status_code == 404
