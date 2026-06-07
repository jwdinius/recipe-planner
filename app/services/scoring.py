from datetime import date

from sqlmodel import Session

from app.services.ratings import preference_points

RECENCY_WEEKS_FULL = 6.0


def preference_value(session: Session, recipe_id: int) -> float:
    return float(preference_points(session, recipe_id))


def recency_value(weeks_since_last_cooked: float | None) -> float:
    if weeks_since_last_cooked is None:
        return 1.0
    return min(1.0, max(0.0, weeks_since_last_cooked) / RECENCY_WEEKS_FULL)


def weeks_since(last_cooked_at: date | None, today: date) -> float | None:
    if last_cooked_at is None:
        return None
    return (today - last_cooked_at).days / 7.0
