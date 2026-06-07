from sqlmodel import Session, select

from app.models.rating import Rating

DISLIKE = "dislike"
POINTS: dict[str, int] = {"love": 2, "like": 1, "dislike": 0}
ALLOWED_VALUES: tuple[str, ...] = tuple(POINTS.keys())


def is_hard_excluded(session: Session, recipe_id: int) -> bool:
    row = session.exec(
        select(Rating.id).where(
            Rating.recipe_id == recipe_id,
            Rating.value == DISLIKE,
        )
    ).first()
    return row is not None


def hard_exclude_user_ids(session: Session, recipe_id: int) -> list[int]:
    rows = session.exec(
        select(Rating.user_id).where(
            Rating.recipe_id == recipe_id,
            Rating.value == DISLIKE,
        )
    ).all()
    return sorted(rows)


def preference_points(session: Session, recipe_id: int) -> int:
    ratings = session.exec(
        select(Rating).where(Rating.recipe_id == recipe_id)
    ).all()
    return sum(POINTS[r.value] for r in ratings)
