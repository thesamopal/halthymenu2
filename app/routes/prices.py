"""
Страница анализа цен:
- Итоги потраченного по месяцам
- Средняя цена по каждому ингредиенту
- Прогноз стоимости желаемого набора блюд на будущий месяц
"""
from collections import defaultdict
from datetime import datetime
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from fastapi_csrf_protect import CsrfProtect

from app.database import get_db
from app.models import User, MonthlyPlan, ShoppingItem, Ingredient, PriceHistory
from app.auth import require_user
from app.config import settings


router = APIRouter(tags=["prices"])
templates = Jinja2Templates(directory="app/templates")


MONTH_NAMES_RU = [
    "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]


@router.get("/prices", response_class=HTMLResponse)
def prices_page(
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
    csrf_protect: CsrfProtect = Depends(),
):
    # Сводка по месяцам: для каждого плана — сколько потрачено
    plans = db.query(MonthlyPlan).filter(
        MonthlyPlan.user_id == user.id,
    ).order_by(MonthlyPlan.year.desc(), MonthlyPlan.month.desc()).all()

    month_totals = []
    for plan in plans:
        items = db.query(ShoppingItem).filter(
            ShoppingItem.plan_id == plan.id,
            ShoppingItem.actual_price.isnot(None),
        ).all()
        total = sum((si.actual_price or 0) for si in items)
        purchased = sum(1 for si in items)
        month_totals.append({
            "year": plan.year,
            "month": plan.month,
            "month_name": MONTH_NAMES_RU[plan.month],
            "total": round(total, 2),
            "items": purchased,
        })

    # Средние цены по ингредиентам (по истории последних 180 дней)
    cutoff = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    history = db.query(PriceHistory).filter(PriceHistory.user_id == user.id).all()

    avg_prices: dict[int, dict] = defaultdict(lambda: {"total_price": 0.0, "total_amount": 0.0, "n": 0})
    for h in history:
        if h.amount <= 0:
            continue
        avg_prices[h.ingredient_id]["total_price"] += h.price
        avg_prices[h.ingredient_id]["total_amount"] += h.amount
        avg_prices[h.ingredient_id]["n"] += 1

    price_rows = []
    for ing_id, stats in avg_prices.items():
        ing = db.query(Ingredient).filter(Ingredient.id == ing_id).first()
        if not ing or stats["total_amount"] == 0:
            continue
        price_per_unit = stats["total_price"] / stats["total_amount"]  # цена за 1 единицу
        price_rows.append({
            "ingredient": ing,
            "avg_price_per_100": round(price_per_unit * 100, 2),
            "n_purchases": stats["n"],
        })
    price_rows.sort(key=lambda r: r["ingredient"].name.lower())

    # Прогноз на будущий план (если есть активный план — считаем его стоимость)
    today = datetime.utcnow()
    future_plan = db.query(MonthlyPlan).filter(
        MonthlyPlan.user_id == user.id,
        ((MonthlyPlan.year > today.year) |
         ((MonthlyPlan.year == today.year) & (MonthlyPlan.month >= today.month))),
    ).order_by(MonthlyPlan.year, MonthlyPlan.month).first()

    forecast = None
    if future_plan:
        total_forecast = 0.0
        items_forecast = []
        month_items = db.query(ShoppingItem).filter(
            ShoppingItem.plan_id == future_plan.id,
            ShoppingItem.week_number.is_(None),
        ).all()
        for si in month_items:
            if si.ingredient_id not in avg_prices:
                continue
            stats = avg_prices[si.ingredient_id]
            if stats["total_amount"] == 0:
                continue
            price_per_unit = stats["total_price"] / stats["total_amount"]
            estimated = price_per_unit * si.total_amount
            total_forecast += estimated
            ing = db.query(Ingredient).filter(Ingredient.id == si.ingredient_id).first()
            if ing:
                items_forecast.append({
                    "name": ing.name,
                    "amount": si.total_amount,
                    "unit": ing.unit,
                    "estimated": round(estimated, 2),
                })
        items_forecast.sort(key=lambda r: r["estimated"], reverse=True)
        forecast = {
            "plan": future_plan,
            "month_name": MONTH_NAMES_RU[future_plan.month],
            "total": round(total_forecast, 2),
            "top_items": items_forecast[:15],
            "all_items_count": len(items_forecast),
        }

    csrf_token, signed = csrf_protect.generate_csrf_tokens()
    response = templates.TemplateResponse(
        "prices.html",
        {
            "request": request,
            "app_name": settings.APP_NAME,
            "active": "prices",
            "current_user": user,
            "csrf_token": csrf_token,
            "flash_messages": [],
            "month_totals": month_totals,
            "price_rows": price_rows,
            "forecast": forecast,
        },
    )
    csrf_protect.set_csrf_cookie(signed, response)
    return response
