# ADR-0001: Single-tenant identity model

**Status:** Accepted
**Date:** 2026-06-06

## Context

The recipe planner is being built for one specific two-person household — Joe and Jessica. We need per-user **ratings** (so that a 👎 from either user hard-excludes a recipe, and so the system can balance both of their preferences when scoring a plan). That requires user identity to be present in the data model.

Beyond that requirement, the design space ranges from "two seeded rows in a `users` table, no auth" to "first-class `Household` entity, multi-tenant from day one."

## Decision

Single-tenant deployment. The database holds two `User` rows seeded once via migration. No login flow, no sessions, no `household_id` column anywhere. The API takes a `user_id` (query param or header) to identify which user is acting; this is used by rating endpoints and by recommendations that ask "for whom."

The app runs on a home network or behind a personal VPN (e.g., Tailscale). It is not intended to be exposed to the open internet in v1.

## Consequences

- No authorization logic to write, test, or maintain.
- Schema is simpler — no tenant-scoping joins on every query.
- The deployment story is trivial: one process, one SQLite file, one trusted network.
- A future move to multi-tenancy is a real migration: add `household_id` to every scopeable table, backfill, rewrite queries, add login. Cost is real but bounded, and we'd only pay it if a concrete demand appeared.

## Alternatives considered

- **Same data model with real auth (password / magic-link).** Mechanical to bolt on later by adding `users.password_hash` and a session middleware. Not worth the work today — VPN access solves 95% of the access problem with 0% of the code.
- **Multi-tenant `Household` entity from day one.** Future-proofs for friends or family adopting the system, but pays the tenant-scoping tax on every query for zero current value. Classic YAGNI.
