import pytest

from app.services.ratings import is_hard_excluded, preference_points


def _make_recipe(client, title: str = "kale caesar") -> int:
    r = client.post(
        "/recipes",
        json={
            "title": title,
            "cuisine": "American",
            "prep_minutes": 10,
            "cook_minutes": 15,
            "instructions": "toss",
            "dietary_tags": [],
            "ingredients": [],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture
def recipe_id(client) -> int:
    return _make_recipe(client)


@pytest.fixture
def other_recipe_id(client) -> int:
    return _make_recipe(client, title="chana masala")


# --- POST upsert ---------------------------------------------------------


def test_post_creates_rating(client, recipe_id):
    r = client.post(
        "/ratings",
        json={"user_id": 1, "recipe_id": recipe_id, "value": "love"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user_id"] == 1
    assert body["recipe_id"] == recipe_id
    assert body["value"] == "love"
    assert isinstance(body["id"], int)


def test_post_upserts_keeps_one_row_per_pair(client, recipe_id):
    first = client.post(
        "/ratings",
        json={"user_id": 1, "recipe_id": recipe_id, "value": "like"},
    ).json()
    second = client.post(
        "/ratings",
        json={"user_id": 1, "recipe_id": recipe_id, "value": "love"},
    )
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["id"] == first["id"]
    assert body["value"] == "love"

    listed = client.get("/ratings", params={"user_id": 1}).json()
    assert len(listed) == 1
    assert listed[0]["value"] == "love"


def test_post_rejects_invalid_value(client, recipe_id):
    r = client.post(
        "/ratings",
        json={"user_id": 1, "recipe_id": recipe_id, "value": "meh"},
    )
    assert r.status_code == 422


def test_post_rejects_unknown_user(client, recipe_id):
    r = client.post(
        "/ratings",
        json={"user_id": 999, "recipe_id": recipe_id, "value": "love"},
    )
    assert r.status_code == 422
    assert "unknown user_id" in r.json()["detail"]


def test_post_rejects_unknown_recipe(client):
    r = client.post(
        "/ratings",
        json={"user_id": 1, "recipe_id": 999, "value": "love"},
    )
    assert r.status_code == 422
    assert "unknown recipe_id" in r.json()["detail"]


# --- GET -----------------------------------------------------------------


def test_get_by_user_lists_only_that_users_ratings(
    client, recipe_id, other_recipe_id
):
    client.post(
        "/ratings", json={"user_id": 1, "recipe_id": recipe_id, "value": "love"}
    )
    client.post(
        "/ratings",
        json={"user_id": 1, "recipe_id": other_recipe_id, "value": "like"},
    )
    client.post(
        "/ratings",
        json={"user_id": 2, "recipe_id": recipe_id, "value": "dislike"},
    )

    r = client.get("/ratings", params={"user_id": 1})
    assert r.status_code == 200
    body = r.json()
    assert {row["recipe_id"] for row in body} == {recipe_id, other_recipe_id}
    assert all(row["user_id"] == 1 for row in body)


def test_get_by_recipe_lists_every_users_rating(client, recipe_id):
    client.post(
        "/ratings", json={"user_id": 1, "recipe_id": recipe_id, "value": "love"}
    )
    client.post(
        "/ratings",
        json={"user_id": 2, "recipe_id": recipe_id, "value": "dislike"},
    )

    r = client.get("/ratings", params={"recipe_id": recipe_id})
    assert r.status_code == 200
    body = r.json()
    assert {row["user_id"]: row["value"] for row in body} == {
        1: "love",
        2: "dislike",
    }


def test_get_requires_exactly_one_filter(client, recipe_id):
    assert client.get("/ratings").status_code == 422
    assert (
        client.get(
            "/ratings", params={"user_id": 1, "recipe_id": recipe_id}
        ).status_code
        == 422
    )


# --- DELETE --------------------------------------------------------------


def test_delete_removes_rating(client, recipe_id):
    client.post(
        "/ratings", json={"user_id": 1, "recipe_id": recipe_id, "value": "love"}
    )
    r = client.delete(
        "/ratings", params={"user_id": 1, "recipe_id": recipe_id}
    )
    assert r.status_code == 204

    listed = client.get("/ratings", params={"user_id": 1}).json()
    assert listed == []


def test_delete_missing_returns_404(client, recipe_id):
    r = client.delete(
        "/ratings", params={"user_id": 1, "recipe_id": recipe_id}
    )
    assert r.status_code == 404


# --- Helpers -------------------------------------------------------------


def test_is_hard_excluded_false_when_no_ratings(session, recipe_id):
    assert is_hard_excluded(session, recipe_id) is False


def test_is_hard_excluded_false_when_only_positive_ratings(
    client, session, recipe_id
):
    client.post(
        "/ratings", json={"user_id": 1, "recipe_id": recipe_id, "value": "love"}
    )
    client.post(
        "/ratings", json={"user_id": 2, "recipe_id": recipe_id, "value": "like"}
    )
    assert is_hard_excluded(session, recipe_id) is False


def test_is_hard_excluded_true_when_joe_dislikes(client, session, recipe_id):
    client.post(
        "/ratings",
        json={"user_id": 1, "recipe_id": recipe_id, "value": "dislike"},
    )
    assert is_hard_excluded(session, recipe_id) is True


def test_is_hard_excluded_true_when_jessica_dislikes(
    client, session, recipe_id
):
    client.post(
        "/ratings",
        json={"user_id": 2, "recipe_id": recipe_id, "value": "dislike"},
    )
    assert is_hard_excluded(session, recipe_id) is True


def test_is_hard_excluded_scoped_to_recipe(
    client, session, recipe_id, other_recipe_id
):
    client.post(
        "/ratings",
        json={"user_id": 1, "recipe_id": recipe_id, "value": "dislike"},
    )
    assert is_hard_excluded(session, recipe_id) is True
    assert is_hard_excluded(session, other_recipe_id) is False


def test_preference_points_zero_when_no_ratings(session, recipe_id):
    assert preference_points(session, recipe_id) == 0


def test_preference_points_both_love_equals_4(client, session, recipe_id):
    client.post(
        "/ratings", json={"user_id": 1, "recipe_id": recipe_id, "value": "love"}
    )
    client.post(
        "/ratings", json={"user_id": 2, "recipe_id": recipe_id, "value": "love"}
    )
    assert preference_points(session, recipe_id) == 4


def test_preference_points_love_plus_like_equals_3(client, session, recipe_id):
    client.post(
        "/ratings", json={"user_id": 1, "recipe_id": recipe_id, "value": "love"}
    )
    client.post(
        "/ratings", json={"user_id": 2, "recipe_id": recipe_id, "value": "like"}
    )
    assert preference_points(session, recipe_id) == 3


def test_preference_points_dislike_contributes_zero(
    client, session, recipe_id
):
    client.post(
        "/ratings", json={"user_id": 1, "recipe_id": recipe_id, "value": "love"}
    )
    client.post(
        "/ratings",
        json={"user_id": 2, "recipe_id": recipe_id, "value": "dislike"},
    )
    assert preference_points(session, recipe_id) == 2
