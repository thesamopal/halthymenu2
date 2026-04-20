"""
Маршруты планировщика:
- /planner — главная страница с настройками и календарём
- /planner/generate — создание нового плана на месяц
"""
from datetime import date
from calendar import monthrange, month_name
from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from fastapi_csrf_protect import CsrfProtect
from pydantic import ValidationError

from app.database import get_db
from app.models import User, MonthlyPlan, PlanDay, PlanMeal, Recipe
from app.schemas import PlanSettings
from app.auth import require_user, log_action, get_client_ip
from app.services.menu_generator import generate_monthly_plan
from app.services.shopping_list import build_shopping_list
from app.config import settings


router = APIRouter(tags=["planner"])
templates = Jinja2Templates(directory="app/templates")


MONTH_NAMES_RU = [
    "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]
MOOD_OPTIONS = [
    ("уютное",    "Уютное"),
    ("бодрящее",  "Бодрящее"),
    ("лёгкое",    "Лёгкое"),
    ("сытное",    "Сытное"),
    ("острое",    "Острое"),
    ("сладкое",   "Сладкое"),
    ("праздничное", "Праздничное"),
]


@router.get("/planner", response_class=HTMLResponse)
def planner_page(
    request: Request,
    year: int | None = None,
    month: int | None = None,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
    csrf_protect: CsrfProtect = Depends(),
):
    today = date.today()
    year = year or today.year
    month = month or today.month

    plan = db.query(MonthlyPlan).filter(
        MonthlyPlan.user_id == user.id,
        MonthlyPlan.year == year,
        MonthlyPlan.month == month,
    ).first()

    days_grid = []
    total_stats = {"calories": 0.0, "protein": 0.0, "fat": 0.0, "carbs": 0.0, "meals": 0}
    if plan:
        days = db.query(PlanDay).filter(PlanDay.plan_id == plan.id).order_by(PlanDay.date).all()
        for d in days:
            meals = db.query(PlanMeal).filter(PlanMeal.day_id == d.id).all()
            meal_items = []
            for m in meals:
                r = db.query(Recipe).filter(Recipe.id == m.recipe_id).first()
                if not r:
                    continue
                meal_items.append({
                    "type": m.meal_type,
                    "name": r.name,
                    "servings": m.servings,
                    "calories": round(r.calories_per_serving * m.servings, 1),
                })
                total_stats["calories"] += r.calories_per_serving * m.servings
                total_stats["protein"]  += r.protein_per_serving * m.servings
                total_stats["fat"]      += r.fat_per_serving * m.servings
                total_stats["carbs"]    += r.carbs_per_serving * m.servings
                total_stats["meals"]    += 1
            days_grid.append({"date": d.date, "meals": meal_items})

    # Сетка с "пустыми" ячейками в начале (чтобы 1 число встало на свой день недели)
    days_in_month = monthrange(year, month)[1]
    first_weekday = date(year, month, 1).weekday()

    # Список лет/месяцев для переключателя
    year_options = [today.year - 1, today.year, today.year + 1]

    csrf_token, signed = csrf_protect.generate_csrf_tokens()
    response = templates.TemplateResponse(
        "planner.html",
        {
            "request": request,
            "app_name": settings.APP_NAME,
            "active": "planner",
            "current_user": user,
            "csrf_token": csrf_token,
            "flash_messages": [],
            "plan": plan,
            "days_grid": days_grid,
            "first_weekday": first_weekday,
            "days_in_month": days_in_month,
            "year": year,
            "month": month,
            "month_name": MONTH_NAMES_RU[month],
            "year_options": year_options,
            "month_options": [(i, MONTH_NAMES_RU[i]) for i in range(1, 13)],
            "mood_options": MOOD_OPTIONS,
            "total_stats": {k: round(v, 1) if isinstance(v, float) else v for k, v in total_stats.items()},
            "user_targets": {
                "calories": user.daily_calories * days_in_month,
                "protein": user.target_protein * days_in_month,
                "fat": user.target_fat * days_in_month,
                "carbs": user.target_carbs * days_in_month,
            },
        },
    )
    csrf_protect.set_csrf_cookie(signed, response)
    return response


@router.post("/planner/generate")
async def planner_generate(
    request: Request,
    year: int = Form(...),
    month: int = Form(...),
    daily_calories: int = Form(...),
    servings_breakfast: int = Form(1),
    servings_lunch: int = Form(1),
    servings_snack: int = Form(0),
    servings_dinner: int = Form(1),
    servings_late_snack: int = Form(0),
    desserts_per_week: int = Form(2),
    csrf_token: str = Form(...),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
    csrf_protect: CsrfProtect = Depends(),
):
    await csrf_protect.validate_csrf(request)

    # Настроения — приходят множественным select'ом
    form = await request.form()
    moods = form.getlist("moods") if hasattr(form, "getlist") else form.get("moods", [])
    if isinstance(moods, str):
        moods = [moods]

    try:
        plan_settings = PlanSettings(
            year=year, month=month, daily_calories=daily_calories,
            servings_breakfast=servings_breakfast, servings_lunch=servings_lunch,
            servings_snack=servings_snack, servings_dinner=servings_dinner,
            servings_late_snack=servings_late_snack, desserts_per_week=desserts_per_week,
        )
    except ValidationError as e:
        raise HTTPException(status_code=400, detail="Некорректные параметры плана")

    plan = generate_monthly_plan(db, user, plan_settings, moods=list(moods) if moods else None)

    # Сразу пересобираем список покупок
    build_shopping_list(db, plan)

    log_action(db, "plan_generated", user_id=user.id, ip=get_client_ip(request),
               details=f"{year}-{month:02d}")

    return RedirectResponse(url=f"/planner?year={year}&month={month}", status_code=302)


@router.post("/planner/delete")
async def planner_delete(
    request: Request,
    year: int = Form(...),
    month: int = Form(...),
    csrf_token: str = Form(...),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
    csrf_protect: CsrfProtect = Depends(),
):
    await csrf_protect.validate_csrf(request)
    plan = db.query(MonthlyPlan).filter(
        MonthlyPlan.user_id == user.id,
        MonthlyPlan.year == year,
        MonthlyPlan.month == month,
    ).first()
    if plan:
        db.delete(plan)
        db.commit()
        log_action(db, "plan_deleted", user_id=user.id, ip=get_client_ip(request),
                   details=f"{year}-{month:02d}")
    return RedirectResponse(url=f"/planner?year={year}&month={month}", status_code=302)
