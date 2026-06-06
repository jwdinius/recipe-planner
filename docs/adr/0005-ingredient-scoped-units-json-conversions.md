# ADR-0005: Ingredient-scoped units with a JSON conversion table

**Status:** Accepted
**Date:** 2026-06-06

## Context

Recipes are written in cooking units ("2 cups chopped kale," "½ tbsp olive oil") while groceries are bought in **purchase units** ("1 bunch kale," "1 bottle olive oil"). The **optimizer** needs to convert between them to compute total demand in purchase-unit terms and decide how many packages to buy.

Conversions are genuinely ingredient-specific. "1 cup chopped" of kale weighs and occupies wildly different amounts than "1 cup chopped" of garlic. The same unit *name* carries different *semantics* per ingredient.

The user accepted that fuzzy conversion factors are fine ("1 bunch kale ≈ 4 cups chopped") — cooking is approximate, and the optimizer's waste math doesn't require gram-perfect accuracy.

## Decision

Each `Ingredient` carries its own unit conversion table as a JSON column:

```python
class Ingredient(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    tier: Literal["perishable", "semi_perishable", "staple"]
    purchase_unit: str                     # display label: "bunch", "bottle", "can"
    unit_conversions: dict[str, float] = Field(
        default_factory=dict, sa_column=Column(JSON)
    )
    notes: str | None = None
```

`unit_conversions` maps recipe-friendly unit names to fractions of one purchase unit. For kale:

```python
{"cup chopped": 0.25, "oz": 0.05}
```

The **purchase unit** itself is implicit at factor `1.0` — entries with that factor in the dict are redundant but harmless. `purchase_unit` lives as a separate string field for display purposes (grocery-list rendering says "buy 2 bunches of kale").

A `RecipeIngredient` row references its ingredient and stores `(quantity, unit)`. At optimization time, the system multiplies by the conversion factor (or `1.0` if `unit == ingredient.purchase_unit`) to obtain demand in purchase units.

**Author convention:** when entering a recipe with a not-yet-defined unit, the API surfaces an error or the frontend prompts inline for the conversion factor and patches the ingredient. After ~20 recipes, common ingredients carry their common units and entry is friction-free.

## Consequences

- New ingredients require defining only the units actually used. Minimal upfront setup; ~30 ingredients × 30 seconds ≈ 15 minutes one-time effort across the whole library.
- No global `Unit` registry to maintain. "Cup" doesn't exist as a portable concept — only "cup for kale" and "cup for garlic" as separate per-ingredient entries.
- JSON column is not query-friendly, but we never query *into* the conversion dict — we read it together with the ingredient as a whole. The structure is read-mostly, dict-sized.
- The convention "purchase unit has implicit factor 1.0" means there's one less normalization step in the data model and one more thing to remember in code. Worth it for the smaller schema.

## Alternatives considered

- **Global `Unit` table + per-ingredient `IngredientUnit` rows.** Relationally cleaner, more queryable. Rejected because it implies a misleading abstraction: "cup" as a global unit suggests portability that doesn't hold. Every ingredient would still need its own row in `IngredientUnit` to declare its semantics, so the gain is only on querying-by-unit-name, which we never do.
- **Canonical mass (grams) for everything with global cup/tbsp/piece conversion tables (USDA-style).** Maximally consistent. Rejected because we'd be building food-science infrastructure for a household app, produce conversions are notoriously sloppy in practice ("1 medium onion" is a range), and we agreed fuzzy units are acceptable.
- **Free-text units with no conversion** (just store "2 cups chopped" as a string). Makes the optimizer impossible — can't reconcile "2 cups chopped" in recipe A with "½ bunch" in recipe B without a conversion structure.
