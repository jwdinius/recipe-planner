# ADR-0007: Recipes stored as "one household dinner"

**Status:** Accepted
**Date:** 2026-06-06

## Context

Cookbooks, recipe websites, and recipe cards express dishes at varying serving sizes ("serves 4," "serves 6," "feeds a crowd"). The system needs a stable convention for what a stored recipe's ingredient quantities represent, because both the **slot** accounting and the grocery-list math depend on it.

The `doubled` flag on a planned recipe must have an unambiguous meaning. If a stored recipe is "serves 4" from a cookbook, does `doubled: true` mean cook 8 portions (= 4 dinners for a couple), or 4 portions (= 2 dinners)? Without a convention, every recipe is a translation problem.

## Decision

Every recipe is stored with ingredient quantities sized to feed the **household** (Joe + Jessica) for *one* dinner. When importing a recipe from a cookbook or website that yields more portions than that, the user scales it down at entry time.

Consequently:

- `doubled: bool` on a planned recipe means "cook 2× the stored quantities → 2 dinners' worth of food."
- **Slot** math is uniform: each plan entry consumes `1 + (1 if doubled else 0)` slots.
- **Grocery math** is uniform: each plan entry contributes `quantity * (2 if doubled else 1)` of each ingredient.
- No `dinners_per_batch` or `original_servings` field exists on `Recipe`. The unit of measurement is implicit and the same for every row.

## Consequences

- Entry friction is real: a cookbook recipe yielding 4 portions has to be mentally halved during entry. This is a one-time per-recipe cost.
- The math throughout the system has no division or scaling factor — `quantity * (2 if doubled else 1)` is the entire story. Easier to read, easier to test, easier to debug.
- Adjusting household size (e.g., adding a third resident, or hosting) is *not* supported by the data model — it would require either re-entering every recipe at the new scale or introducing a `household_size` setting and per-recipe scaling logic. Hosting is handled instead by setting `doubled: true` or pinning extra recipes. Acceptable for v1.
- Any future "guests for dinner" feature is a real schema change. Flagged here so we don't think it's free.

## Alternatives considered

- **Store as written + add `dinners_per_batch: int`.** Recipes look natural on paper ("serves 4, dinners_per_batch=2"). Rejected because it makes every downstream calculation carry an extra multiplier and every UI surface has to explain the field. The flexibility isn't earned — household size is fixed at 2 in v1.
- **Store as written + `original_servings: int` + `household_size: int` setting.** Maximum generality. Rejected for the same YAGNI reason as `Household` in ADR-0001: we have one household of fixed size; the abstraction has no payoff.
- **No convention at all** (quantities are whatever the user typed, "doubled" multiplies by 2). Forces the user to mentally normalize at recipe-pick time instead of recipe-entry time. The math is the same either way — recipe-entry is the better place to absorb the friction because it happens once per recipe rather than every time the recipe is used.
