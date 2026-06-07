from fastapi import FastAPI

from app.routes import (
    health,
    ingredients,
    pantry,
    plans,
    ratings,
    recipes,
    recommendations,
)

app = FastAPI(title="recipe-planner", version="0.1.0")
app.include_router(health.router)
app.include_router(ingredients.router)
app.include_router(recipes.router)
app.include_router(pantry.router)
app.include_router(ratings.router)
app.include_router(recommendations.router)
app.include_router(plans.router)
