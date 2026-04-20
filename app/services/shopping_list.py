"""
Построение списка покупок из плана.

Собирает все PlanMeal плана, суммирует ингредиенты с учётом порций
(Recipe хранит БЖУ и ингредиенты на свои servings, мы умножаем на запрошенные).

Поддерживает два режима:
- На весь месяц (week_number = None)
- По неделям (week_number = 1..5 по ISO-дате)
"""
from collections import defaultdict
from datetime import date, timedelta
from sqlalchemy.orm import Session
from app.models import MonthlyPlan, PlanDay, PlanMeal, Recipe, RecipeIngredient, ShoppingItem


def build_shopping_list(db: Session, plan: MonthlyPlan) -> None:
    """
    Пересобирает список покупок для плана.
    ВАЖНО: не удаляет уже купленные позиции с ценами — обновляет количество.
    """
    # Собираем: (ingredient_id, week_number) -> total_amount
    aggregated: dict[tuple[int, int | None], float] = defaultdict(float)

    # Берём все дни плана с блюдами
    days = db.query(PlanDay).filter(PlanDay.plan_id == plan.id).all()
    for day in days:
        week_num = _iso_week_in_month(day.date)
        meals = db.query(PlanMeal).filter(PlanMeal.day_id == day.id).all()
        for meal in meals:
            recipe = db.query(Recipe).filter(Recipe.id == meal.recipe_id).first()
            if not recipe:
                continue
            # Сколько порций нужно и сколько рецепт даёт
            need_servings = meal.servings
            recipe_servings = max(1, recipe.servings)
            multiplier = need_servings / recipe_servings

            ris = db.query(RecipeIngredient).filter(RecipeIngredient.recipe_id == recipe.id).all()
            for ri in ris:
                aggregated[(ri.ingredient_id, week_num)] += ri.amount * multiplier
                # Также месячный агрегат (для "на весь месяц")
                aggregated[(ri.ingredient_id, None)] += ri.amount * multiplier

    # Загружаем существующие позиции чтобы сохранить чекбоксы и цены
    existing = {
        (si.ingredient_id, si.week_number): si
        for si in db.query(ShoppingItem).filter(ShoppingItem.plan_id == plan.id).all()
    }

    # Удаляем те, которых больше нет
    current_keys = set(aggregated.keys())
    for key, item in existing.items():
        if key not in current_keys:
            db.delete(item)

    # Обновляем/создаём
    for (ing_id, week_num), amount in aggregated.items():
        if (ing_id, week_num) in existing:
            existing[(ing_id, week_num)].total_amount = round(amount, 1)
        else:
            db.add(ShoppingItem(
                plan_id=plan.id,
                ingredient_id=ing_id,
                week_number=week_num,
                total_amount=round(amount, 1),
            ))
    db.commit()


def _iso_week_in_month(d: date) -> int:
    """
    Возвращает порядковый номер недели внутри месяца (1..5).
    Считаем по понедельнику первого дня месяца.
    """
    first = date(d.year, d.month, 1)
    # Сколько дней до понедельника первой недели
    offset = first.weekday()  # 0 = Пн
    return ((d.day + offset - 1) // 7) + 1
