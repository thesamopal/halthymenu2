"""
Расчёт БЖУ рецепта на основе ингредиентов.
Единый источник правды — вызывается при создании/обновлении рецепта
и кэширует значения в Recipe.calories_per_serving и т.д.
"""
from sqlalchemy.orm import Session
from app.models import Recipe, RecipeIngredient, Ingredient


def calculate_recipe_nutrition(db: Session, recipe: Recipe) -> dict:
    """
    Считает суммарные БЖУ по всем ингредиентам и делит на число порций.
    Все ингредиенты хранят БЖУ на 100 единиц (г/мл/шт).
    """
    total = {"calories": 0.0, "protein": 0.0, "fat": 0.0, "carbs": 0.0}

    items = db.query(RecipeIngredient).filter(RecipeIngredient.recipe_id == recipe.id).all()
    for ri in items:
        ing = db.query(Ingredient).filter(Ingredient.id == ri.ingredient_id).first()
        if not ing:
            continue
        factor = ri.amount / 100.0
        total["calories"] += ing.calories_per_100 * factor
        total["protein"]  += ing.protein_per_100 * factor
        total["fat"]      += ing.fat_per_100 * factor
        total["carbs"]    += ing.carbs_per_100 * factor

    servings = max(1, recipe.servings)
    return {
        "calories_per_serving": round(total["calories"] / servings, 1),
        "protein_per_serving":  round(total["protein"]  / servings, 1),
        "fat_per_serving":      round(total["fat"]      / servings, 1),
        "carbs_per_serving":    round(total["carbs"]    / servings, 1),
    }


def update_recipe_nutrition(db: Session, recipe: Recipe) -> None:
    """Пересчитывает и сохраняет БЖУ в рецепте."""
    nutr = calculate_recipe_nutrition(db, recipe)
    recipe.calories_per_serving = nutr["calories_per_serving"]
    recipe.protein_per_serving = nutr["protein_per_serving"]
    recipe.fat_per_serving = nutr["fat_per_serving"]
    recipe.carbs_per_serving = nutr["carbs_per_serving"]
    db.commit()
