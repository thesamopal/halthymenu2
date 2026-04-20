"""
Генератор меню на месяц.

Принципы:
- Случайная выборка из подходящих рецептов (по meal_type и moods пользователя)
- Фильтр по исключениям пользователя (рецепты без запрещённых ингредиентов)
- Стремление уложиться в целевые дневные калории ± допуск
- Минимизация повторений внутри недели (один рецепт не чаще раза в 3-5 дней)
- Десерты — отдельно, X штук в неделю
"""
import random
from datetime import date, timedelta
from calendar import monthrange
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, not_, exists

from app.models import (
    User, Recipe, RecipeIngredient, Exclusion,
    MonthlyPlan, PlanDay, PlanMeal,
)
from app.schemas import PlanSettings


MEAL_ORDER = ["breakfast", "lunch", "snack", "dinner", "late_snack"]
# Примерное распределение калорий по приёмам пищи (в сумме = 1.0 без десертов)
MEAL_CALORIE_SHARE = {
    "breakfast":  0.25,
    "lunch":      0.35,
    "snack":      0.10,
    "dinner":     0.25,
    "late_snack": 0.05,
}
# Допуск по калориям на приём пищи: ±X% от таргета
CALORIE_TOLERANCE = 0.35
# Минимум дней между повторами одного рецепта
MIN_REPEAT_GAP = 4


def _get_excluded_ingredient_ids(db: Session, user_id: int) -> set[int]:
    rows = db.query(Exclusion.ingredient_id).filter(Exclusion.user_id == user_id).all()
    return {r[0] for r in rows}


def _candidate_recipes(
    db: Session,
    meal_type: str,
    excluded_ing_ids: set[int],
    user_id: int,
    is_dessert: bool = False,
) -> list[Recipe]:
    """
    Подбирает рецепты подходящего типа приёма пищи, исключая те,
    в которых есть запрещённые ингредиенты.
    Учитывает как системные, так и пользовательские (собственные) рецепты.
    """
    q = db.query(Recipe).filter(Recipe.is_dessert == is_dessert)

    # Пользователь видит: системные + свои
    q = q.filter((Recipe.is_system == True) | (Recipe.created_by_user_id == user_id))  # noqa: E712

    # Фильтр по типу приёма пищи (JSON-массив содержит строку)
    # В SQLite нет нормального JSON-оператора, поэтому фильтруем в Python
    recipes = q.all()
    filtered = []
    for r in recipes:
        if is_dessert or meal_type in (r.meal_types or []):
            # Проверяем что нет запрещённых ингредиентов
            if excluded_ing_ids:
                has_excluded = db.query(
                    exists().where(and_(
                        RecipeIngredient.recipe_id == r.id,
                        RecipeIngredient.ingredient_id.in_(excluded_ing_ids),
                    ))
                ).scalar()
                if has_excluded:
                    continue
            filtered.append(r)
    return filtered


def _pick_recipe(
    candidates: list[Recipe],
    target_calories: float,
    recent: dict[int, int],   # recipe_id -> day_index последнего использования
    day_idx: int,
    moods: Optional[list[str]] = None,
) -> Optional[Recipe]:
    """
    Выбирает рецепт: сначала фильтрует по калориям и правилу повторов,
    затем взвешенно случайно выбирает с предпочтением подходящего настроения.
    """
    if not candidates:
        return None

    low = target_calories * (1 - CALORIE_TOLERANCE)
    high = target_calories * (1 + CALORIE_TOLERANCE)

    eligible = [
        r for r in candidates
        if low <= r.calories_per_serving <= high
        and (r.id not in recent or day_idx - recent[r.id] >= MIN_REPEAT_GAP)
    ]

    # Если никто не прошёл — ослабляем правило повторов
    if not eligible:
        eligible = [r for r in candidates if low <= r.calories_per_serving <= high]
    # Если всё равно пусто — берём любой подходящий по типу
    if not eligible:
        eligible = candidates

    # Взвешенный выбор по настроению: рецепты с совпадающим настроением весят в 3 раза больше
    weights = []
    for r in eligible:
        w = 1.0
        if moods:
            if set(r.moods or []) & set(moods):
                w = 3.0
        weights.append(w)

    return random.choices(eligible, weights=weights, k=1)[0]


def generate_monthly_plan(
    db: Session,
    user: User,
    settings: PlanSettings,
    moods: Optional[list[str]] = None,
) -> MonthlyPlan:
    """
    Основная функция: создаёт (или пересоздаёт) план на месяц.
    Если план на этот месяц уже есть — удаляет его и создаёт заново.
    """
    # Удаляем старый план если есть
    existing = db.query(MonthlyPlan).filter(
        MonthlyPlan.user_id == user.id,
        MonthlyPlan.year == settings.year,
        MonthlyPlan.month == settings.month,
    ).first()
    if existing:
        db.delete(existing)
        db.commit()

    plan = MonthlyPlan(
        user_id=user.id,
        year=settings.year,
        month=settings.month,
        daily_calories=settings.daily_calories,
        servings_breakfast=settings.servings_breakfast,
        servings_lunch=settings.servings_lunch,
        servings_snack=settings.servings_snack,
        servings_dinner=settings.servings_dinner,
        servings_late_snack=settings.servings_late_snack,
        desserts_per_week=settings.desserts_per_week,
    )
    db.add(plan)
    db.flush()  # получаем id не коммитя

    excluded = _get_excluded_ingredient_ids(db, user.id)

    # Подбираем кандидатов по каждому типу приёма пищи один раз — быстрее
    meal_candidates = {
        mt: _candidate_recipes(db, mt, excluded, user.id, is_dessert=False)
        for mt in MEAL_ORDER
    }
    dessert_candidates = _candidate_recipes(db, "dessert", excluded, user.id, is_dessert=True)

    # Дни месяца
    days_in_month = monthrange(settings.year, settings.month)[1]
    first_day = date(settings.year, settings.month, 1)

    recent_by_meal: dict[str, dict[int, int]] = {mt: {} for mt in MEAL_ORDER}

    for day_idx in range(days_in_month):
        current_date = first_day + timedelta(days=day_idx)
        day = PlanDay(plan_id=plan.id, date=current_date)
        db.add(day)
        db.flush()

        # Настройки порций по каждому приёму пищи
        servings_map = {
            "breakfast":  settings.servings_breakfast,
            "lunch":      settings.servings_lunch,
            "snack":      settings.servings_snack,
            "dinner":     settings.servings_dinner,
            "late_snack": settings.servings_late_snack,
        }

        for meal_type in MEAL_ORDER:
            if servings_map[meal_type] <= 0:
                continue
            target_cal = settings.daily_calories * MEAL_CALORIE_SHARE[meal_type] / max(1, servings_map[meal_type])
            recipe = _pick_recipe(
                meal_candidates[meal_type], target_cal,
                recent_by_meal[meal_type], day_idx, moods,
            )
            if recipe is None:
                continue
            db.add(PlanMeal(
                day_id=day.id,
                recipe_id=recipe.id,
                meal_type=meal_type,
                servings=servings_map[meal_type],
            ))
            recent_by_meal[meal_type][recipe.id] = day_idx

    # Десерты: равномерно размещаем по неделям
    if settings.desserts_per_week > 0 and dessert_candidates:
        weeks = _split_month_to_weeks(first_day, days_in_month)
        recent_dessert: dict[int, int] = {}
        for week_days in weeks:
            # Сколько десертов в эту неделю (пропорционально размеру недели)
            n_desserts = max(1, round(settings.desserts_per_week * len(week_days) / 7))
            dessert_days = random.sample(week_days, min(n_desserts, len(week_days)))
            for d in dessert_days:
                day_idx = (d - first_day).days
                # Для десерта таргет калорий: остаток от дневных (небольшой)
                target_cal = settings.daily_calories * 0.10
                recipe = _pick_recipe(
                    dessert_candidates, target_cal,
                    recent_dessert, day_idx, moods,
                )
                if recipe is None:
                    continue
                # Находим PlanDay для этой даты
                plan_day = db.query(PlanDay).filter(
                    PlanDay.plan_id == plan.id, PlanDay.date == d,
                ).first()
                if plan_day:
                    db.add(PlanMeal(
                        day_id=plan_day.id,
                        recipe_id=recipe.id,
                        meal_type="dessert",
                        servings=1,
                    ))
                    recent_dessert[recipe.id] = day_idx

    db.commit()
    db.refresh(plan)
    return plan


def _split_month_to_weeks(first_day: date, days_in_month: int) -> list[list[date]]:
    """Разбивает месяц на ISO-недели (Пн-Вс)."""
    weeks: list[list[date]] = []
    current_week: list[date] = []
    for i in range(days_in_month):
        d = first_day + timedelta(days=i)
        current_week.append(d)
        if d.weekday() == 6:  # воскресенье — закрываем неделю
            weeks.append(current_week)
            current_week = []
    if current_week:
        weeks.append(current_week)
    return weeks
