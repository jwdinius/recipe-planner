# ADR-0002: Stack — FastAPI + SQLModel + SQLite + uv

**Status:** Accepted
**Date:** 2026-06-06

## Context

We chose CP-SAT via Google OR-Tools for the plan **optimizer** (see ADR-0003). OR-Tools' Python bindings are by far the most ergonomic; the Java/C++/.NET bindings exist but require materially more boilerplate. That effectively pins the server language to Python.

Within Python, framework, ORM, persistence, and package-manager choices remain. The project is small (one **household**, two users, expected library of ~30–60 recipes), API-shaped (no server-rendered views needed), and operationally self-hosted (home network or VPN).

## Decision

- **Web framework: FastAPI.** Pydantic-based request/response models, automatic OpenAPI docs (serves as a free debugging UI during early development), strong typing throughout.
- **ORM: SQLModel.** A single class doubles as DB schema and API model, eliminating most ORM-vs-Pydantic duplication. Written by the FastAPI author, so the idioms compose cleanly.
- **Database: SQLite.** Single file, no separate process to operate. SQLite's JSON1 extension covers the small semi-structured fields we need (notably `Ingredient.unit_conversions`, see ADR-0005).
- **Package manager: uv.** Fast, modern, sane lockfile semantics. Equivalent in spirit to poetry but materially quicker for everyday workflows.

The standard project layout:

```
recipe-planner/
├── app/
│   ├── main.py            # FastAPI bootstrap
│   ├── db.py              # engine + session
│   ├── models/            # SQLModel classes
│   ├── routes/            # endpoint modules grouped by resource
│   └── optimizer/         # CP-SAT scoring + solving — no FastAPI imports
├── migrations/            # alembic
├── tests/
├── pyproject.toml
└── uv.lock
```

The optimizer module is intentionally HTTP-unaware: a pure function from `(library, pins, carryover, weights, target) → (plan, score_breakdown, grocery_list)`. This keeps it independently testable and reusable from CLI scripts or future workers.

## Consequences

- The full Python ecosystem (OR-Tools, scientific libraries) is available for later enhancements.
- SQLite is backed up with `cp recipe-planner.db recipe-planner.db.bak`. No DBA story to manage.
- FastAPI's `/docs` page becomes a free, always-current API explorer — useful while there's no frontend.
- Migrating to Postgres later changes a connection string and adds an Alembic migration. Application code is unaffected because SQLModel/SQLAlchemy abstracts the dialect.

## Alternatives considered

- **Flask instead of FastAPI.** Functionally equivalent, more boilerplate, no built-in OpenAPI generation. Worth choosing only if you already know Flask deeply and don't want to learn FastAPI's idioms.
- **Django.** Overkill — bundles auth, admin, and a heavy ORM none of which we use. The package size and conceptual surface area both feel wrong for an API server.
- **Plain SQLAlchemy without SQLModel.** Stricter separation between DB and API models, which earns its keep at larger scale. Pointless at v1 scope; SQLModel's class-doubles-as-both is exactly the right ergonomic for a 6-entity domain.
- **Postgres instead of SQLite.** Warranted only if multi-tenant access, full-text search at scale, or high write concurrency arrived. None apply yet. SQLModel makes the migration painless if any do.
- **pip + requirements.txt.** Universal but loses the lockfile discipline that uv (or poetry) brings.
