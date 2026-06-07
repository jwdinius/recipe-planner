"""Plain-data IO types for the CP-SAT plan optimizer.

These dataclasses are framework-free by design: no SQLModel, no FastAPI.
The route layer translates database rows into these types before calling
solve_plan() (see ADR-0003).
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class IngredientInfo:
    id: int
    name: str
    tier: str  # "perishable" | "semi_perishable" | "staple"
    purchase_unit: str


@dataclass(frozen=True)
class RecipeDemand:
    ingredient_id: int
    quantity_purchase_units: float


@dataclass(frozen=True)
class RecipeCandidate:
    id: int
    preference_points: int
    hard_excluded: bool
    demands: tuple[RecipeDemand, ...]
    recency_value: float = 0.0
    cuisine: str = ""
    excluded_by_user_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class Pin:
    recipe_id: int
    doubled: bool = False


@dataclass(frozen=True)
class PantryQty:
    ingredient_id: int
    quantity_purchase_units: float


@dataclass(frozen=True)
class PlanEntry:
    recipe_id: int
    doubled: bool


@dataclass(frozen=True)
class ScoreBreakdown:
    waste: float
    preference: float
    recency: float
    variety: float
    total: float


@dataclass(frozen=True)
class GroceryItem:
    ingredient_id: int
    name: str
    purchase_unit: str
    quantity: int
    projected_waste: float


@dataclass(frozen=True)
class PlanWarning:
    recipe_id: int
    message: str
    excluding_user_ids: tuple[int, ...]


@dataclass(frozen=True)
class PlanResult:
    plan: tuple[PlanEntry, ...]
    score_breakdown: ScoreBreakdown
    grocery_list: tuple[GroceryItem, ...]
    warnings: tuple[PlanWarning, ...] = ()
