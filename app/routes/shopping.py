"""
Список покупок:
- GET /shopping — просмотр по неделям/месяцу с чекбоксами
- POST /shopping/toggle/{id} — отметить/снять галочку
- POST /shopping/price/{id} — ввести цену
"""
from datetime import datetime, date
from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from fastapi_csrf_protect import CsrfProtect
from pydantic import ValidationError

from app.database import get_db
from app.models import User, MonthlyPlan, ShoppingItem, Ingredient, PriceHistory
from app.schemas import ShoppingItemUpdate
from app.auth import require_user
from app.config import settings


router = APIRouter(tags=["shopping"])
templates = Jinja2Templates(directory="app/templates")


MONTH_NAMES_RU = [
    "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]


@router.get("/shopping", response_class=HTMLResponse)
def shopping_page(
    request: Request,
    year: int | None = None,
    month: int | None = None,
    view: str = "week",  # 'week' | 'month'
    week: int | None = None,
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

    grouped_by_week: dict[int, list[dict]] = {}
    monthly_items: list[dict] = []
    weeks_available: list[int] = []
    total_spent = 0.0
    total_purchased = 0
    total_items = 0

    if plan:
        # Все позиции, отсортированные
        items = db.query(ShoppingItem).filter(ShoppingItem.plan_id == plan.id).all()
        for si in items:
            ing = db.query(Ingredient).filter(Ingredient.id == si.ingredient_id).first()
            if not ing:
                continue
            row = {
                "id": si.id,
                "ingredient": ing,
                "amount": si.total_amount,
                "week": si.week_number,
                "is_purchased": si.is_purchased,
                "actual_price": si.actual_price,
            }
            if si.week_number is None:
                monthly_items.append(row)
            else:
                grouped_by_week.setdefault(si.week_number, []).append(row)
                total_items += 1
                if si.is_purchased:
                    total_purchased += 1
                if si.actual_price:
                    total_spent += si.actual_price

        # Сортировка по имени внутри групп
        for w in grouped_by_week:
            grouped_by_week[w].sort(key=lambda r: r["ingredient"].name.lower())
        monthly_items.sort(key=lambda r: r["ingredient"].name.lower())
        weeks_available = sorted(grouped_by_week.keys())

    csrf_token, signed = csrf_protect.generate_csrf_tokens()
    response = templates.TemplateResponse(
        "shopping.html",
        {
            "request": request,
            "app_name": settings.APP_NAME,
            "active": "shopping",
            "current_user": user,
            "csrf_token": csrf_token,
            "flash_messages": [],
            "plan": plan,
            "year": year,
            "month": month,
            "month_name": MONTH_NAMES_RU[month],
            "view": view,
            "week": week,
            "weeks_available": weeks_available,
            "grouped_by_week": grouped_by_week,
            "monthly_items": monthly_items,
            "stats": {
                "total_items": total_items,
                "purchased": total_purchased,
                "spent": round(total_spent, 2),
                "progress_pct": round(total_purchased / total_items * 100) if total_items else 0,
            },
        },
    )
    csrf_protect.set_csrf_cookie(signed, response)
    return response


@router.post("/shopping/toggle/{item_id}")
async def toggle_purchased(
    request: Request,
    item_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
    csrf_protect: CsrfProtect = Depends(),
):
    """
    Переключает флажок покупки. Проверяет, что позиция принадлежит
    плану пользователя — защита от IDOR (подмены ID).
    Вызывается из Alpine.js через fetch — тоже с CSRF.
    """
    await csrf_protect.validate_csrf(request)

    si = db.query(ShoppingItem).join(MonthlyPlan).filter(
        ShoppingItem.id == item_id,
        MonthlyPlan.user_id == user.id,
    ).first()
    if not si:
        raise HTTPException(status_code=404, detail="Позиция не найдена")

    si.is_purchased = not si.is_purchased
    si.purchased_at = datetime.utcnow() if si.is_purchased else None
    db.commit()
    return JSONResponse({"ok": True, "is_purchased": si.is_purchased})


@router.post("/shopping/price/{item_id}")
async def set_price(
    request: Request,
    item_id: int,
    actual_price: float = Form(...),
    csrf_token: str = Form(...),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
    csrf_protect: CsrfProtect = Depends(),
):
    await csrf_protect.validate_csrf(request)

    try:
        data = ShoppingItemUpdate(actual_price=actual_price)
    except ValidationError:
        raise HTTPException(status_code=400, detail="Некорректная цена")

    si = db.query(ShoppingItem).join(MonthlyPlan).filter(
        ShoppingItem.id == item_id,
        MonthlyPlan.user_id == user.id,
    ).first()
    if not si:
        raise HTTPException(status_code=404, detail="Позиция не найдена")

    si.actual_price = data.actual_price
    # Записываем в историю цен для прогнозов
    db.add(PriceHistory(
        user_id=user.id,
        ingredient_id=si.ingredient_id,
        price=data.actual_price,
        amount=si.total_amount,
    ))
    db.commit()

    # Возвращаемся на ту же страницу
    back = request.headers.get("referer") or "/shopping"
    return RedirectResponse(url=back, status_code=302)
