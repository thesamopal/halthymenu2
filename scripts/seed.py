"""
Скрипт загрузки начальных данных в БД.
Запуск: python -m scripts.seed
Идемпотентен — можно запускать несколько раз, дубликаты не создаются.
"""
import json
import sys
from pathlib import Path

# Добавляем корень в путь, чтобы импорты работали
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal, Base, engine
from app.models import Ingredient, Recipe, RecipeIngredient
from app.services.nutrition import update_recipe_nutrition


RECIPE_FILES = [
    "data/seed_recipes_breakfast.json",
    "data/seed_recipes_lunch.json",
    "data/seed_recipes_dinner.json",
    "data/seed_recipes_snacks_desserts.json",
]


def seed_ingredients(db) -> dict[str, int]:
    """Загружает ингредиенты и возвращает маппинг имя -> id."""
    with open("data/seed_ingredients.json", "r", encoding="utf-8") as f:
        ingredients_data = json.load(f)

    name_to_id: dict[str, int] = {}
    added = 0
    for ing_data in ingredients_data:
        existing = db.query(Ingredient).filter(Ingredient.name == ing_data["name"]).first()
        if existing:
            name_to_id[existing.name] = existing.id
            continue
        ing = Ingredient(**ing_data)
        db.add(ing)
        db.flush()
        name_to_id[ing.name] = ing.id
        added += 1
    db.commit()
    print(f"  Ингредиенты: добавлено {added}, всего в маппинге {len(name_to_id)}")
    return name_to_id


def seed_recipes(db, name_to_id: dict[str, int]) -> None:
    """Загружает рецепты из всех файлов."""
    total_added = 0
    total_skipped = 0
    total_missing_ing = 0

    for file_path in RECIPE_FILES:
        if not Path(file_path).exists():
            print(f"  Пропуск: файл {file_path} не найден")
            continue
        with open(file_path, "r", encoding="utf-8") as f:
            recipes = json.load(f)

        for r in recipes:
            # Проверка — не добавлен ли уже такой рецепт (по имени + is_system)
            existing = db.query(Recipe).filter(
                Recipe.name == r["name"], Recipe.is_system == True,  # noqa: E712
            ).first()
            if existing:
                total_skipped += 1
                continue

            # Проверяем, что все ингредиенты есть
            missing = [i["name"] for i in r["ingredients"] if i["name"] not in name_to_id]
            if missing:
                print(f"  ⚠ Пропуск '{r['name']}': нет ингредиентов {missing}")
                total_missing_ing += 1
                continue

            recipe = Recipe(
                name=r["name"],
                description=r.get("description"),
                instructions=r.get("instructions"),
                meal_types=r.get("meal_types", []),
                moods=r.get("moods", []),
                servings=r.get("servings", 1),
                cooking_time_min=r.get("cooking_time_min", 30),
                difficulty=r.get("difficulty", "easy"),
                is_dessert=r.get("is_dessert", False),
                is_system=True,
                created_by_user_id=None,
            )
            db.add(recipe)
            db.flush()

            for ing_item in r["ingredients"]:
                db.add(RecipeIngredient(
                    recipe_id=recipe.id,
                    ingredient_id=name_to_id[ing_item["name"]],
                    amount=ing_item["amount"],
                ))
            db.flush()
            update_recipe_nutrition(db, recipe)
            total_added += 1

    db.commit()
    print(f"  Рецепты: добавлено {total_added}, пропущено существующих {total_skipped}, с missing-ингредиентами {total_missing_ing}")


def main():
    print("== Создание таблиц ==")
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        print("== Загрузка ингредиентов ==")
        name_to_id = seed_ingredients(db)
        print("== Загрузка рецептов ==")
        seed_recipes(db, name_to_id)
        print("\n✓ Seed завершён успешно")
    finally:
        db.close()


if __name__ == "__main__":
    main()
