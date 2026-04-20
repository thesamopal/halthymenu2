"""
Страница исключений продуктов. Пользователь добавляет ингредиенты,
которые не хочет видеть в плане (аллергии / не любит).
"""
from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from fastapi_csrf_protect import CsrfProtect
from pydantic import ValidationError

from app.database import get_db
from app.models import User, Exclusion, Ingredient
from app.schemas import ExclusionCreate
from app.auth import require_user, log_action, get_client_ip
from app.config import settings


router = APIRouter(tags=["exclusions"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/exclusions", response_class=HTMLResponse)
def exclusions_page(
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
    csrf_protect: CsrfProtect = Depends(),
):
    exclusions = db.query(Exclusion).filter(Exclusion.user_id == user.id).all()
    excl_with_ing = []
    for e in exclusions:
        ing = db.query(Ingredient).filter(Ingredient.id == e.ingredient_id).first()
        if ing:
            excl_with_ing.append({"id": e.id, "ingredient": ing, "reason": e.reason})

    all_ingredients = db.query(Ingredient).order_by(Ingredient.name).all()
    excluded_ids = {e["ingredient"].id for e in excl_with_ing}
    available = [i for i in all_ingredients if i.id not in excluded_ids]

    csrf_token, signed = csrf_protect.generate_csrf_tokens()
    response = templates.TemplateResponse(
        "exclusions.html",
        {
            "request": request,
            "app_name": settings.APP_NAME,
            "active": "exclusions",
            "current_user": user,
            "csrf_token": csrf_token,
            "flash_messages": [],
            "exclusions": excl_with_ing,
            "available_ingredients": available,
        },
    )
    csrf_protect.set_csrf_cookie(signed, response)
    return response


@router.post("/exclusions/add")
async def add_exclusion(
    request: Request,
    ingredient_id: int = Form(...),
    reason: str = Form(""),
    csrf_token: str = Form(...),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
    csrf_protect: CsrfProtect = Depends(),
):
    await csrf_protect.validate_csrf(request)

    try:
        data = ExclusionCreate(ingredient_id=ingredient_id, reason=reason or None)
    except ValidationError:
        raise HTTPException(status_code=400, detail="Некорректные данные")

    # Проверяем, что ингредиент существует
    ing = db.query(Ingredient).filter(Ingredient.id == data.ingredient_id).first()
    if not ing:
        raise HTTPException(status_code=404, detail="Ингредиент не найден")

    # Уникальность: user_id + ingredient_id
    existing = db.query(Exclusion).filter(
        Exclusion.user_id == user.id,
        Exclusion.ingredient_id == data.ingredient_id,
    ).first()
    if existing:
        return RedirectResponse(url="/exclusions", status_code=302)

    excl = Exclusion(user_id=user.id, ingredient_id=data.ingredient_id, reason=data.reason)
    db.add(excl)
    db.commit()
    log_action(db, "exclusion_added", user_id=user.id, ip=get_client_ip(request),
               details=f"ingredient_id={data.ingredient_id}")
    return RedirectResponse(url="/exclusions", status_code=302)


@router.post("/exclusions/{excl_id}/delete")
async def delete_exclusion(
    request: Request,
    excl_id: int,
    csrf_token: str = Form(...),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
    csrf_protect: CsrfProtect = Depends(),
):
    await csrf_protect.validate_csrf(request)
    # ВАЖНО: фильтр по user_id — пользователь может удалять только СВОИ исключения
    excl = db.query(Exclusion).filter(
        Exclusion.id == excl_id,
        Exclusion.user_id == user.id,
    ).first()
    if excl:
        db.delete(excl)
        db.commit()
    return RedirectResponse(url="/exclusions", status_code=302)
