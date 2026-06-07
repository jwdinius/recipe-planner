from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, SQLModel, select

from app.db import get_session
from app.models.rating import Rating
from app.models.recipe import Recipe
from app.models.user import User

router = APIRouter(prefix="/ratings", tags=["ratings"])

RatingValue = Literal["love", "like", "dislike"]


class RatingIn(SQLModel):
    user_id: int
    recipe_id: int
    value: RatingValue


class RatingRead(SQLModel):
    id: int
    user_id: int
    recipe_id: int
    value: str


def _to_read(rating: Rating) -> RatingRead:
    return RatingRead(
        id=rating.id,
        user_id=rating.user_id,
        recipe_id=rating.recipe_id,
        value=rating.value,
    )


def _get_existing(
    session: Session, user_id: int, recipe_id: int
) -> Rating | None:
    return session.exec(
        select(Rating).where(
            Rating.user_id == user_id,
            Rating.recipe_id == recipe_id,
        )
    ).first()


@router.post("", response_model=RatingRead)
def upsert_rating(
    payload: RatingIn, session: Session = Depends(get_session)
) -> RatingRead:
    if session.get(User, payload.user_id) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"unknown user_id: {payload.user_id}",
        )
    if session.get(Recipe, payload.recipe_id) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"unknown recipe_id: {payload.recipe_id}",
        )

    existing = _get_existing(session, payload.user_id, payload.recipe_id)
    if existing is None:
        existing = Rating(
            user_id=payload.user_id,
            recipe_id=payload.recipe_id,
            value=payload.value,
        )
    else:
        existing.value = payload.value
    session.add(existing)
    session.commit()
    session.refresh(existing)
    return _to_read(existing)


@router.get("", response_model=list[RatingRead])
def list_ratings(
    user_id: int | None = None,
    recipe_id: int | None = None,
    session: Session = Depends(get_session),
) -> list[RatingRead]:
    if (user_id is None) == (recipe_id is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="exactly one of user_id or recipe_id must be provided",
        )

    stmt = select(Rating)
    if user_id is not None:
        stmt = stmt.where(Rating.user_id == user_id)
    else:
        stmt = stmt.where(Rating.recipe_id == recipe_id)
    rows = session.exec(stmt.order_by(Rating.id)).all()
    return [_to_read(r) for r in rows]


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_rating(
    user_id: int,
    recipe_id: int,
    session: Session = Depends(get_session),
) -> None:
    existing = _get_existing(session, user_id, recipe_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="not found"
        )
    session.delete(existing)
    session.commit()
