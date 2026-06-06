# ADR-0003: CP-SAT for plan optimization with a weighted linear objective

**Status:** Accepted
**Date:** 2026-06-06

## Context

The plan **optimizer** must select a subset of recipes from the **library** (and decide which to **double**) to fill the user's requested **slot** count, while minimizing an objective that combines:

- ingredient **waste** (the central problem — finishing perishable packages cleanly),
- per-user **rating** preferences,
- **recency** (variety over time),
- **cuisine variety** (variety within the week).

The decision space is naturally integer/boolean: each recipe is selected or not, each selected recipe is doubled or not, and for each perishable ingredient the number of packages purchased is a non-negative integer. The waste term involves a `ceiling(demand / package_size)` calculation that benefits from native integer variables.

The user asked us to plan for scale rather than choose the simplest thing that works today.

## Decision

Use Google OR-Tools' **CP-SAT** solver for the planner. Encode the problem as:

- **Decision variables**
  - `selected[r] ∈ {0,1}` for each candidate recipe.
  - `doubled[r] ∈ {0,1}` for each candidate recipe.
  - `packages[i] ∈ ℕ` for each perishable / semi-perishable ingredient.

- **Hard constraints**
  - Pinned recipes have `selected[r] = 1` (and `doubled[r]` fixed to the user-set value).
  - Recipes with a 👎 from either user have `selected[r] = 0`, *unless* explicitly pinned (in which case the pin wins and a warning is attached to the response).
  - `doubled[r] ≤ selected[r]` — can't double something you haven't selected.
  - Slot constraint: `Σ (selected[r] + doubled[r]) = target_count`.
  - Demand constraint per perishable / semi-perishable ingredient: `packages[i] * package_size_i ≥ Σ recipe_demand[r][i] * (selected[r] + doubled[r])`.

- **Objective (minimize)**

  ```
  + w_waste      · Σ tier_multiplier[i] · (packages[i] · package_size_i − total_demand[i])
  − w_preference · Σ preference_score[r] · selected[r]
  − w_recency    · Σ recency_value[r]    · selected[r]
  + w_variety    · Σ max(0, cuisine_count[c] − 2)
  ```

  Combined as a weighted linear sum. Defaults for weights and curves live in `CONTEXT.md`.

- **Integer scaling.** CP-SAT is integer-only. All fractional quantities (recipe demands, conversion factors, recency curve values) are multiplied by `SCALE = 1000` and rounded to int before entering the model. Strictly mechanical bookkeeping; well-commented in the optimizer module.

The optimizer is a pure function with no FastAPI imports. The boundary `(library, pins, carryover, weights, target) → (plan, score_breakdown, grocery_list)` is the durable contract.

## Consequences

- **Sub-second solves** at v1 scale and substantial headroom as the library grows or constraints are added (dietary filters, multi-week, ingredient compatibility).
- **Set-level reasoning is built in.** The optimizer handles the kale problem natively: a kale recipe's score depends on whether other selections finish the bunch, and CP-SAT explores those interactions.
- **Hard-exclude via 👎 is a real constraint, not a soft penalty** — no risk of "the system served you the casserole you hate because the math worked out." Pins can override with explicit warnings, surfacing the conflict rather than hiding it.
- **Debugging is harder than a brute-force loop.** Mitigation: log the per-term contribution of every preview's winning plan; consider exposing a "second-best plan" option later via a no-good cut.
- **Recommendations do not use this solver** — they have a different shape (rank individuals, not pick a set) and use a simpler scoring + greedy diversification (see ADR-0006). The per-recipe scoring components are factored into a shared helper.

## Alternatives considered

- **Brute-force enumeration in plain Python.** Viable at v1 scale (~200K candidate plans), trivially debuggable. Rejected because the user explicitly asked to plan for scaling now, and the optimizer's external interface is identical either way — so the choice was between "build the long-term version now" and "build the throwaway version twice."
- **MILP via PuLP + CBC (or OR-Tools' MILP frontend).** Equivalent expressive power; slightly more verbose for the doubling implication constraints than CP-SAT. Either would work; CP-SAT's API is the smaller barrier.
- **Greedy / beam search heuristic.** Fast and simple but exactly wrong for this problem. The kale interaction is non-local: a kale recipe is worth picking only if other picks finish the bunch. Greedy will routinely produce sub-optimal grocery lists.
- **Lexicographic objective** (waste strictly dominates preference, which strictly dominates recency, etc.). Rejected because it makes the system rigid: a 0.01-unit waste improvement always beats arbitrary preference loss. Real-world tradeoffs are smoother than that.
- **Pareto front / "give me 3 candidate plans."** Deferred. Layer onto the existing solver later if "show me alternatives" becomes desirable.
