from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session, SQLModel

from app.db import get_session
from app.models.user import User
from app.services.recommendations import Recommendation, recommend

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


class ScoreBreakdownRead(SQLModel):
    preference: float
    recency: float
    carryover_fit: float


class RecommendationRead(SQLModel):
    recipe_id: int
    score: float
    breakdown: ScoreBreakdownRead
    badges: list[str]


def _to_read(item: Recommendation) -> RecommendationRead:
    return RecommendationRead(
        recipe_id=item.recipe_id,
        score=item.score,
        breakdown=ScoreBreakdownRead(
            preference=item.breakdown.preference,
            recency=item.breakdown.recency,
            carryover_fit=item.breakdown.carryover_fit,
        ),
        badges=list(item.badges),
    )


@router.get("", response_model=list[RecommendationRead])
def list_recommendations(
    user_id: int = Query(...),
    limit: int = Query(10, ge=1, le=100),
    session: Session = Depends(get_session),
) -> list[RecommendationRead]:
    if session.get(User, user_id) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"unknown user_id: {user_id}",
        )
    return [_to_read(item) for item in recommend(session, limit=limit)]
