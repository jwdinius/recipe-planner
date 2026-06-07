from dataclasses import dataclass
from datetime import date

from sqlmodel import Session, select

from app.models.recipe import Recipe, RecipeIngredient
from app.services.carryover import carryover_fit
from app.services.ratings import is_hard_excluded
from app.services.scoring import preference_value, recency_value, weeks_since

# Sign convention for /recommendations: positive = better, sort descending.
# This inverts the optimizer's negative-weight reward convention from
# CONTEXT.md so the API surfaces higher-is-better scores.
RECOMMENDATION_WEIGHTS: dict[str, float] = {
    "preference": 3.0,
    "recency": 2.0,
    "carryover": 1.0,
}

DIVERSIFICATION_ALPHA = 0.5


@dataclass(frozen=True)
class ScoreBreakdown:
    preference: float
    recency: float
    carryover_fit: float


@dataclass(frozen=True)
class Recommendation:
    recipe_id: int
    score: float
    breakdown: ScoreBreakdown
    badges: tuple[str, ...]


@dataclass(frozen=True)
class _Candidate:
    recipe: Recipe
    score: float
    breakdown: ScoreBreakdown
    badges: tuple[str, ...]
    cuisine: str
    ingredient_ids: frozenset[int]


def _weighted_score(breakdown: ScoreBreakdown) -> float:
    w = RECOMMENDATION_WEIGHTS
    return (
        w["preference"] * breakdown.preference
        + w["recency"] * breakdown.recency
        + w["carryover"] * breakdown.carryover_fit
    )


def _pairwise_similarity(a: _Candidate, b: _Candidate) -> float:
    cuisine_match = 1.0 if a.cuisine == b.cuisine else 0.0
    if not a.ingredient_ids or not b.ingredient_ids:
        jaccard = 0.0
    else:
        intersection = a.ingredient_ids & b.ingredient_ids
        union = a.ingredient_ids | b.ingredient_ids
        jaccard = len(intersection) / len(union)
    return cuisine_match + jaccard


def _build_candidate(session: Session, recipe: Recipe, today: date) -> _Candidate:
    fit = carryover_fit(session, recipe.id)
    breakdown = ScoreBreakdown(
        preference=preference_value(session, recipe.id),
        recency=recency_value(weeks_since(recipe.last_cooked_at, today)),
        carryover_fit=fit.value,
    )
    badges = tuple(
        f"uses your {name} carryover" for name in fit.overlap_ingredient_names
    )
    ingredient_ids = frozenset(
        ri.ingredient_id
        for ri in session.exec(
            select(RecipeIngredient).where(
                RecipeIngredient.recipe_id == recipe.id
            )
        ).all()
    )
    return _Candidate(
        recipe=recipe,
        score=_weighted_score(breakdown),
        breakdown=breakdown,
        badges=badges,
        cuisine=recipe.cuisine,
        ingredient_ids=ingredient_ids,
    )


def _to_recommendation(candidate: _Candidate) -> Recommendation:
    return Recommendation(
        recipe_id=candidate.recipe.id,
        score=candidate.score,
        breakdown=candidate.breakdown,
        badges=candidate.badges,
    )


def recommend(
    session: Session,
    limit: int,
    today: date | None = None,
) -> list[Recommendation]:
    if limit <= 0:
        return []
    today = today or date.today()

    recipes = session.exec(select(Recipe).order_by(Recipe.id)).all()
    eligible = [r for r in recipes if not is_hard_excluded(session, r.id)]
    if not eligible:
        return []

    candidates = [_build_candidate(session, r, today) for r in eligible]

    chosen: list[_Candidate] = []
    remaining = list(candidates)
    while remaining and len(chosen) < limit:
        if not chosen:
            remaining.sort(key=lambda c: (-c.score, c.recipe.id))
            chosen.append(remaining.pop(0))
            continue

        def adjusted(c: _Candidate) -> float:
            penalty = sum(_pairwise_similarity(c, x) for x in chosen)
            return c.score - DIVERSIFICATION_ALPHA * penalty

        remaining.sort(key=lambda c: (-adjusted(c), c.recipe.id))
        chosen.append(remaining.pop(0))

    return [_to_recommendation(c) for c in chosen]
