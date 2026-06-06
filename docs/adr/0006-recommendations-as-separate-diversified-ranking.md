# ADR-0006: Recommendations as a separate diversified ranking surface

**Status:** Accepted
**Date:** 2026-06-06

## Context

A Green-Chef-style experience surfaces a *list* of recommended recipes when the user opens the app, distinct from the act of building a weekly plan. The user browses, pins one or two they're craving, then triggers plan optimization to fill the remaining **slots**.

Superficially, "recommendations" looks like a thin wrapper over the plan **optimizer** — run the solver, return the picks. But on closer inspection these are different problem shapes:

- The optimizer reasons about an *interacting set*: kale recipe A's value depends on whether other selections finish the bunch. The objective is global.
- Recommendations reason about *individual recipes* surfaced for browsing. There are no interactions between displayed items — the user picks 0–2 of them by hand.

If we conflate them, the homepage list commits the user to interactions they haven't asked for, and the optimizer is constrained to produce a presentable individual ranking that isn't its purpose.

## Decision

Implement recommendations as a **separate endpoint** (`GET /recommendations`) using a **separate algorithm**:

1. **Per-recipe scoring.** Apply the hard-exclude rule (👎 from either user filters the recipe out entirely). Then compute:

   ```
   score(r) = w_preference   · (joe_rating_points  + jessica_rating_points)
            + w_recency      · recency_curve(weeks_since_last_cooked)
            + w_carryover    · carryover_fit(r)
   ```

   where `carryover_fit` rewards recipes whose ingredients overlap with the current **carryover** list, weighted by how much of the carryover they'd consume.

2. **Greedy diversification.** Take the top-scoring recipe, then iteratively pick the next recipe maximizing `score(r) − α · similarity(r, already_chosen)`. Similarity penalizes cuisine overlap and ingredient overlap with the already-chosen recommendations. Continue until `limit` items are chosen.

3. **Return structure.** A ranked list, each item carrying its score breakdown and any badges (e.g., "uses your kale carryover").

**Shared scoring kernel.** The per-recipe scoring components (preference, recency) are factored into a helper module imported by both the recommendation algorithm and the plan optimizer. The recommendation algorithm adds carryover-fit; the plan optimizer adds the set-level **waste** and **variety** terms.

## Consequences

- Two simple algorithms, one shared scoring kernel. Each is small enough to read end-to-end.
- The recommendation list never commits the user to anything; they pin from it, then call `POST /plans/preview`.
- Carryover-fit is an explicit term, which means we can surface "uses your kale" badges directly from the score breakdown — no special-case code in the frontend.
- The diversification step is greedy, not provably optimal. For typical `limit = 10` from a pool of ~30, the gap to optimum is negligible and the code stays linear.

## Alternatives considered

- **Use the plan optimizer to produce recommendations** (e.g., return the top-N picks from the first-best plan, or return the union of the top-K plans). Couples browsing to set-level interactions the user hasn't asked for. The set-level optimization also implicitly *commits* the user — picking from "the optimizer's set" is psychologically different from picking from a ranked list. Wrong workflow shape.
- **Pure top-K by score, no diversification.** Tends to clump same-cuisine recipes at the top of the list — kale-and-quinoa, kale-and-farro, kale-and-chickpea — losing the Green-Chef-style "varied lineup" feel.
- **Stochastic sampling** (weight by score, sample without replacement). Avoids the staleness of pure top-K but loses determinism. "Why did *this* show up today?" becomes unanswerable, which hurts trust and tuning.
- **Collaborative filtering** (learn what you'll like from rating patterns). Useful at scale; meaningless with two users and ~30 recipes. Premature.
