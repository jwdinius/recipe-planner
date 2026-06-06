# Recipe Planner — Context

## Mission

A backend that lets two specific people (Joe and Jessica) plan weekly dinners and generate an optimized grocery list that minimizes the waste of perishable ingredients. Replaces the curation-and-portioning value of a Green Chef subscription while letting the household shop themselves.

## System narrative

Each week, Joe and Jessica open the app to plan 3–6 dinners. They browse a **recommendation** list of recipes the system thinks they'd like this week — ranked by their **ratings**, how recently each was cooked, and how well it uses up their current **carryover**. They **pin** any they're committed to (with optional **double-up**), set a target dinner count, and hit "build plan."

The **optimizer** picks the remaining recipes from their **library**, using **CP-SAT** to minimize a weighted linear objective combining ingredient **waste**, ratings, recency, and **cuisine variety**. It can also propose **doubling** non-pinned recipes when that finishes off a **perishable** package cleanly. The result is a **weekly plan** plus a **grocery list** with **projected waste** annotations.

Committing the plan updates the **carryover** to its projected post-cook state.

## Glossary

**Carryover** — Items left in the kitchen at the start of a planning week, typically partially-used perishables (½ bunch kale, ¾ jar capers). Acts as bonus inventory the optimizer subtracts from required purchases. Only **perishable** and **semi-perishable** items live here; **staples** are never tracked. Optionally tagged with an `as_of` date for at-a-glance freshness checks.

**Conversion factor** — On each `Ingredient`, the multiplier from a recipe-friendly unit (e.g., "cup chopped") to the **purchase unit** (e.g., "bunch"). Stored as a JSON dict `{unit_name: factor}` on the ingredient. The **purchase unit** is the implicit row with factor `1.0`.

**Cuisine** — A free-form string attribute on `Recipe` (e.g., "Italian", "Mexican", "Baja"). Used as the **variety** axis. Not canonicalized in v1.

**Diversification** — Greedy step in the **recommendation** algorithm that penalizes each candidate by its cuisine and ingredient overlap with already-picked recommendations, producing a varied lineup rather than top-K-by-score.

**Doubled (Double-up)** — A flag on a planned recipe meaning "cook 2× the ingredients to yield 2 dinners' worth." Consumes 2 **slots**. The **optimizer** may set this on non-pinned recipes when it reduces waste; pinned recipes' double flag is user-set and immutable to the optimizer.

**Fill** — Optimization mode where the user pins some recipes and the optimizer fills the remaining **slots**.

**Grocery list** — Computed output of a committed plan: per ingredient, the rounded-up purchase quantity needed to satisfy total recipe demand minus current **carryover**. Includes a per-ingredient **projected waste** estimate.

**Hard exclude** — A 👎 rating from either user permanently excludes a recipe from system-driven selection (recommendations and optimizer fill). An explicit **pin** overrides the exclude with a warning attached to the plan response.

**Household** — In v1, the single household of two users. Not modeled as a first-class entity; the entire system is implicitly scoped to this one household.

**Ingredient** — A canonical entry in the ingredient catalog. Has a `name`, a **tier**, a **purchase unit**, a JSON map of **conversion factors**, and free-form notes.

**Library** — The household's collection of recipes. Hand-entered via API in v1.

**Pin** — A user-locked recipe in a plan request. Cannot be removed or un-doubled by the optimizer. Pins override the **hard exclude** rule.

**Plan (Weekly plan)** — An unordered bag of selected recipes for the upcoming week. Each entry is `{recipe_id, doubled: bool}`. Day-of-week assignment is not modeled.

**Preview** — A non-persistent invocation of the optimizer returning a candidate plan, its **score breakdown**, and the resulting **grocery list**. Used by the frontend to recompute as the user tweaks pins, target count, or **weights**.

**Projected waste** — Per-ingredient estimate of the unused fraction of purchased packages, weighted by **tier**. Reported on every plan preview and commit.

**Purchase unit** — The unit each ingredient is sold in (e.g., "bunch" for kale, "bottle" for olive oil, "can" for beans). Implicit on the ingredient as the **conversion factor** of value `1.0`.

**Rating** — A per-`(user, recipe)` value of `love` (+2), `like` (+1), or `dislike` (hard exclude). At most one rating per pair. Missing rating = neutral (0).

**Recency** — Number of weeks since a recipe's `last_cooked_at`. Translated to a reward via a linear ramp `min(1.0, weeks / 6)`. "Never cooked" = `weeks = ∞ → 1.0`.

**Recipe** — Title, cuisine, prep/cook minutes, instructions (markdown), optional source URL, dietary tags, and a list of `(ingredient, quantity, unit)` entries. The ingredient quantities are sized to feed the **household** for one dinner (see ADR-0007).

**Recommendation** — A ranked, **diversified** list of individual recipes surfaced before plan generation. Separate from the **optimizer**: ranks per-recipe rather than as a set. Same per-recipe scoring components, plus a **carryover-fit** bonus.

**Score breakdown** — The per-term contribution of each objective component (waste, preference, recency, variety) to the total. Returned with every **preview** for tunability and debug.

**Slot** — A unit of "one dinner this week." A non-doubled recipe consumes 1 slot; a doubled one consumes 2. Target slot count is user-set per plan (3–6, default 4).

**Staple** — A **tier** for ingredients kept stocked at all times (oil, flour, salt, common spices). Excluded from waste optimization and grocery lists by convention. The household keeps these stocked outside the system.

**Tier** — One of `perishable` (full waste-penalty multiplier), `semi_perishable` (lower multiplier), or `staple` (zero). Determines how much the **optimizer** cares about leftover packages of this ingredient.

**Variety** — Penalty applied to a plan when too many recipes share a **cuisine**. Computed as `sum_c max(0, count[c] - 2)`. First two same-cuisine recipes are free; each beyond costs one unit.

**Waste** — Sum over **perishable** and **semi-perishable** ingredients of `(purchased_packages * package_size − total_demand) * tier_multiplier`. Multiplied by the `waste` weight to enter the objective.

**Weight** — Tunable scalar coefficient on an objective term (waste, preference, recency, variety). Defaults live server-side; per-request overrides allowed via the **preview** body for what-if exploration.

## Key invariants

- A `Rating` row exists per `(user, recipe)` at most once. Missing = neutral.
- Every `RecipeIngredient.unit` is either the ingredient's **purchase unit** or appears as a key in its `unit_conversions` dict.
- A `WeeklyPlan` entry's `doubled` flag is mutable by the **optimizer** for system-picked recipes; immutable for **pinned** recipes.
- **Staple** ingredients never appear in **carryover** and never appear on a **grocery list**.
- All fractional quantities are multiplied by `SCALE = 1000` and rounded to int before entering the CP-SAT model.
- A 👎 **rating** from *either* user hard-excludes a recipe from system-driven selection unless that recipe is explicitly **pinned**.

## Default optimizer parameters

These live in a server-side config module and are overridable per-request via `/plans/preview`.

```python
DEFAULT_WEIGHTS = {
    "waste":      10.0,   # per fractional purchase unit, after tier multipliers
    "preference": -3.0,   # per rating point summed across users (negative = reward)
    "recency":    -2.0,   # per selected recipe, times recency-curve value
    "variety":     5.0,   # per cuisine-overrun unit (count beyond 2 of same cuisine)
}
TIER_MULTIPLIERS = {"perishable": 3.0, "semi_perishable": 1.0, "staple": 0.0}
RECENCY_CURVE = lambda weeks: min(1.0, weeks / 6)  # 0 at "cooked this week", 1.0 at "6+ weeks ago"
RECOMMENDATION_DIVERSIFICATION_ALPHA = 0.5         # cuisine/ingredient overlap penalty
DEFAULT_TARGET_DINNERS = 4
TARGET_DINNER_RANGE = (3, 6)
```

## Out of scope (v1)

- Authentication, sessions, multi-household support.
- Breakfast and lunch planning (recipes are dinner-only; `meal_type` reserved as a future field on `Recipe`).
- Photos, calorie info, equipment lists, ingredient substitutions, per-cooking notes.
- Auto-deduct on per-meal cook-confirmation (auto-deduct happens at plan commit only).
- Multi-week optimization (each week solved independently with current carryover as input).
- A separate cookbook entity for tracking page references (stored in `instructions` as plain text).
- Frontend / mobile clients (this repo is the backend only).
