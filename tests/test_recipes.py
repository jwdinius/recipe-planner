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


def _kale_caesar(kale_id: int, olive_oil_id: int) -> dict:
    return {
        "title": "Kale caesar",
        "cuisine": "Italian",
        "prep_minutes": 15,
        "cook_minutes": 0,
        "instructions": "# Kale caesar\n\nMassage kale with dressing.",
        "source_url": "https://example.com/kale-caesar",
        "dietary_tags": ["vegetarian"],
        "ingredients": [
            {"ingredient_id": kale_id, "quantity": 2.0, "unit": "cup chopped"},
            {"ingredient_id": olive_oil_id, "quantity": 1.5, "unit": "tbsp"},
        ],
    }


def test_create_recipe_with_cup_chopped_kale(client, kale_id):
    r = client.post(
        "/recipes",
        json={
            "title": "Sauteed kale",
            "cuisine": "Italian",
            "prep_minutes": 5,
            "cook_minutes": 10,
            "instructions": "Saute the kale.",
            "dietary_tags": ["vegetarian", "gluten-free"],
            "ingredients": [
                {"ingredient_id": kale_id, "quantity": 4.0, "unit": "cup chopped"},
            ],
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id"] > 0
    assert body["title"] == "Sauteed kale"
    assert body["cuisine"] == "Italian"
    assert body["dietary_tags"] == ["vegetarian", "gluten-free"]
    assert body["last_cooked_at"] is None
    assert body["ingredients"] == [
        {"ingredient_id": kale_id, "quantity": 4.0, "unit": "cup chopped"},
    ]


def test_create_recipe_rejects_undefined_unit(client, kale_id):
    r = client.post(
        "/recipes",
        json={
            "title": "Bad kale",
            "cuisine": "Italian",
            "prep_minutes": 5,
            "cook_minutes": 10,
            "instructions": "...",
            "ingredients": [
                {"ingredient_id": kale_id, "quantity": 2.0, "unit": "kilogram"},
            ],
        },
    )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "kale" in detail
    assert "kilogram" in detail


def test_create_recipe_accepts_purchase_unit_directly(client, kale_id):
    r = client.post(
        "/recipes",
        json={
            "title": "Whole bunch kale",
            "cuisine": "Italian",
            "prep_minutes": 5,
            "cook_minutes": 15,
            "instructions": "...",
            "ingredients": [
                {"ingredient_id": kale_id, "quantity": 1.0, "unit": "bunch"},
            ],
        },
    )
    assert r.status_code == 201, r.text


def test_create_recipe_rejects_unknown_ingredient_id(client):
    r = client.post(
        "/recipes",
        json={
            "title": "Ghost recipe",
            "cuisine": "Italian",
            "prep_minutes": 5,
            "cook_minutes": 10,
            "instructions": "...",
            "ingredients": [
                {"ingredient_id": 9999, "quantity": 1.0, "unit": "bunch"},
            ],
        },
    )
    assert r.status_code == 422
    assert "9999" in r.json()["detail"]


def test_recipe_roundtrip_with_multiple_ingredients(client, kale_id, olive_oil_id):
    payload = _kale_caesar(kale_id, olive_oil_id)
    r = client.post("/recipes", json=payload)
    assert r.status_code == 201, r.text
    created = r.json()

    r = client.get(f"/recipes/{created['id']}")
    assert r.status_code == 200
    assert r.json() == created

    r = client.get("/recipes")
    assert r.status_code == 200
    listing = r.json()
    assert len(listing) == 1
    assert listing[0] == created


def test_patch_recipe_fields(client, kale_id):
    r = client.post(
        "/recipes",
        json={
            "title": "Kale a",
            "cuisine": "Italian",
            "prep_minutes": 5,
            "cook_minutes": 10,
            "instructions": "v1",
            "ingredients": [
                {"ingredient_id": kale_id, "quantity": 1.0, "unit": "bunch"},
            ],
        },
    )
    recipe_id = r.json()["id"]

    r = client.patch(
        f"/recipes/{recipe_id}",
        json={"title": "Kale a (revised)", "instructions": "v2"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Kale a (revised)"
    assert body["instructions"] == "v2"
    assert body["cuisine"] == "Italian"
    assert len(body["ingredients"]) == 1


def test_patch_recipe_replaces_ingredients(client, kale_id, olive_oil_id):
    r = client.post(
        "/recipes",
        json={
            "title": "Recipe",
            "cuisine": "Italian",
            "prep_minutes": 5,
            "cook_minutes": 10,
            "instructions": "...",
            "ingredients": [
                {"ingredient_id": kale_id, "quantity": 1.0, "unit": "bunch"},
            ],
        },
    )
    recipe_id = r.json()["id"]

    r = client.patch(
        f"/recipes/{recipe_id}",
        json={
            "ingredients": [
                {"ingredient_id": kale_id, "quantity": 2.0, "unit": "cup chopped"},
                {"ingredient_id": olive_oil_id, "quantity": 1.0, "unit": "tbsp"},
            ]
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ingredients"] == [
        {"ingredient_id": kale_id, "quantity": 2.0, "unit": "cup chopped"},
        {"ingredient_id": olive_oil_id, "quantity": 1.0, "unit": "tbsp"},
    ]


def test_patch_recipe_validates_new_unit(client, kale_id):
    r = client.post(
        "/recipes",
        json={
            "title": "Recipe",
            "cuisine": "Italian",
            "prep_minutes": 5,
            "cook_minutes": 10,
            "instructions": "...",
            "ingredients": [
                {"ingredient_id": kale_id, "quantity": 1.0, "unit": "bunch"},
            ],
        },
    )
    recipe_id = r.json()["id"]

    r = client.patch(
        f"/recipes/{recipe_id}",
        json={
            "ingredients": [
                {"ingredient_id": kale_id, "quantity": 1.0, "unit": "kilogram"},
            ]
        },
    )
    assert r.status_code == 422


def test_delete_recipe(client, kale_id):
    r = client.post(
        "/recipes",
        json={
            "title": "Recipe",
            "cuisine": "Italian",
            "prep_minutes": 5,
            "cook_minutes": 10,
            "instructions": "...",
            "ingredients": [
                {"ingredient_id": kale_id, "quantity": 1.0, "unit": "bunch"},
            ],
        },
    )
    recipe_id = r.json()["id"]

    r = client.delete(f"/recipes/{recipe_id}")
    assert r.status_code == 204

    r = client.get(f"/recipes/{recipe_id}")
    assert r.status_code == 404


def test_last_cooked_at_is_read_only_via_api(client, kale_id):
    r = client.post(
        "/recipes",
        json={
            "title": "Recipe",
            "cuisine": "Italian",
            "prep_minutes": 5,
            "cook_minutes": 10,
            "instructions": "...",
            "last_cooked_at": "2026-05-01",
            "ingredients": [
                {"ingredient_id": kale_id, "quantity": 1.0, "unit": "bunch"},
            ],
        },
    )
    assert r.status_code == 201
    assert r.json()["last_cooked_at"] is None

    recipe_id = r.json()["id"]
    r = client.patch(
        f"/recipes/{recipe_id}", json={"last_cooked_at": "2026-05-15"}
    )
    assert r.status_code == 200
    assert r.json()["last_cooked_at"] is None


def test_get_missing_recipe_returns_404(client):
    r = client.get("/recipes/9999")
    assert r.status_code == 404


def test_patch_missing_recipe_returns_404(client):
    r = client.patch("/recipes/9999", json={"title": "x"})
    assert r.status_code == 404


def test_delete_missing_recipe_returns_404(client):
    r = client.delete("/recipes/9999")
    assert r.status_code == 404
