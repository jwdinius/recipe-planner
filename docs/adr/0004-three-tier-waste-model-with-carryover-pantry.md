# ADR-0004: Three-tier waste model with carryover-only pantry

**Status:** Accepted
**Date:** 2026-06-06

## Context

The central problem this app solves is *ingredient waste from misaligned package sizes* — a recipe wants ½ bunch of kale, kale is sold in whole bunches, and a typical week leaves half a bunch wilting in the fridge. Solving it requires the **optimizer** to know which ingredients trigger that pressure.

But "every ingredient should be fully consumed" is wrong: flour, oil, salt, and common spices are sold in quantities far exceeding a week's recipes — you just keep them stocked. Modeling them as waste-sensitive would either over-constrain the optimizer (no feasible plans) or force the household to track inventory levels they don't think about.

Between perishables and staples, there's a middle band: items like sundried tomatoes and marinated artichokes that survive open in the fridge for several weeks. They're worth optimizing softly — finishing the jar is a win but not urgent.

Separately: the optimizer needs to know about partial leftovers from prior weeks (a half-used jar, a third of a bunch) so it doesn't make the household buy redundant inventory.

## Decision

**Three ingredient tiers.** Every `Ingredient` carries a `tier` field of `perishable`, `semi_perishable`, or `staple`. The **waste** term in the objective uses tier multipliers:

| Tier | Multiplier |
| --- | --- |
| perishable | 3.0 |
| semi_perishable | 1.0 |
| staple | 0.0 |

Staples are never on a **grocery list** and never appear in **carryover** — they're considered always-available. The household replenishes them off-app.

**Carryover-only pantry.** The pantry model tracks only partially-used perishable and semi-perishable items the household currently has on hand. It is *not* an inventory of everything in the kitchen. A typical carryover list has perhaps 0–6 entries at the start of a planning week.

A pantry entry is `{ingredient_id, quantity, unit, as_of: date | null}`. The `as_of` field is optional and informational only — no automatic expiry. At-a-glance, the user can spot "this kale has been here 9 days" and edit it out manually.

**Update mechanism.** Auto-deduct on plan commit, with manual override always available. When a plan is committed, the system computes projected post-cook state (carryover + grocery list − planned recipe demand) and sets the pantry to that. The user can edit the pantry at any time via `PUT /pantry` (replace) or `PATCH /pantry` (incremental) to correct for divergences from the plan (cooked something different, recipe didn't use all the kale, etc.).

## Consequences

- The household maintains staples off-app. The system isn't a kitchen inventory tracker; it's a planner that respects the difference between waste-sensitive and abundant ingredients.
- The optimizer has crisp constraints: only perishable and semi-perishable ingredients contribute to waste cost or appear in grocery list calculations.
- Pantry state can drift from reality if the household doesn't cook exactly what was planned. The drift is bounded by a single weekly manual edit during the next planning session.
- Sundried tomatoes and similar items still pressure the optimizer (just less than fresh greens). This matches the household's actual preference: finishing the jar is good, but not at the cost of a great Monday-night recipe.

## Alternatives considered

- **Two-tier `perishable: bool` only.** Too coarse — sundried tomatoes and marinated artichokes don't fit either bucket cleanly, and forcing them into "staple" loses real waste signal.
- **Continuous shelf-life days per ingredient.** Maximally precise (kale = 7 days, capers = 60 days, flour = 365). The waste penalty becomes a function of shelf life. Rejected because per-ingredient data-entry cost is real and the gains over three discrete tiers are marginal for a two-person household.
- **Full kitchen inventory pantry.** Tracks everything you own. Morphs the app toward a separate problem (household inventory management) with its own daily maintenance burden. Scope creep.
- **Pure manual pantry** (user types every edit, no automation). Simpler but the pantry drifts to staleness fast. Manual + auto-deduct hybrid gives the best of both.
- **Per-meal cook-confirmation deduction.** More accurate ground truth, but adds a daily check-in. Rejected to preserve the "open the app once a week" UX that's central to the Green-Chef-style appeal.
