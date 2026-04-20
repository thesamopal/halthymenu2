"""
Десерты: просмотр списка, добавление пользовательских десертов.
Пользовательские десерты учитываются в генераторе как is_dessert=True и принадлежат этому пользователю.
"""
from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from fastapi_csrf_protect import CsrfProtect
from pydantic import ValidationError
import json

from app.database import get_db
from app.models import User, Recipe, RecipeIngredient, Ingredient
from app.schemas import RecipeCreate, RecipeIngredientIn
from app.auth import require_user, log_action, get_client_ip
from app.services.nutrition import update_recipe_nutrition
from app.config import settings


router = APIRouter(tags=["desserts"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/desserts", response_class=HTMLResponse)
def desserts_page(
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
    csrf_protect: CsrfProtect = Depends(),
):
    # Системные десерты + свои
    system_desserts = db.query(Recipe).filter(
        Recipe.is_dessert == True, Recipe.is_system == True,  # noqa: E712
    ).order_by(Recipe.name).all()
    my_desserts = db.query(Recipe).filter(
        Recipe.is_dessert == True, Recipe.created_by_user_id == user.id,  # noqa: E712
    ).order_by(Recipe.name).all()

    all_ingredients = db.query(Ingredient).order_by(Ingredient.name).all()

    csrf_token, signed = csrf_protect.generate_csrf_tokens()
    response = templates.TemplateResponse(
        "desserts.html",
        {
            "request": request,
            "app_name": settings.APP_NAME,
            "active": "desserts",
            "current_user": user,
            "csrf_token": csrf_token,
            "flash_messages": [],
            "system_desserts": system_desserts,
            "my_desserts": my_desserts,
            "all_ingredients": all_ingredients,
        },
    )
    csrf_protect.set_csrf_cookie(signed, response)
    return response


@router.post("/desserts/add")
async def add_dessert(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    instructions: str = Form(""),
    servings: int = Form(1),
    cooking_time_min: int = Form(30),
    ingredients_json: str = Form("[]"),
    csrf_token: str = Form(...),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
    csrf_protect: CsrfProtect = Depends(),
):
    await csrf_protect.validate_csrf(request)

    # Парсим ингредиенты из JSON
    try:
        ing_list = json.loads(ingredients_json)
        if not isinstance(ing_list, list):
            raise ValueError("Ожидается список ингредиентов")
        parsed_ingredients = [RecipeIngredientIn(**item) for item in ing_list]
    except (json.JSONDecodeError, ValueError, ValidationError) as e:
        raise HTTPException(status_code=400, detail=f"Некорректный формат ингредиентов: {e}")

    try:
        data = RecipeCreate(
            name=name, description=description or None, instructions=instructions or None,
            meal_types=["dessert"], moods=["сладкое"],
            servings=servings, cooking_time_min=cooking_time_min, is_dessert=True,
            ingredients=parsed_ingredients,
        )
    except ValidationError as e:
        raise HTTPException(status_code=400, detail="; ".join(err["msg"] for err in e.errors()))

    recipe = Recipe(
        name=data.name,
        description=data.description,
        instructions=data.instructions,
        meal_types=data.meal_types,
        moods=data.moods,
        servings=data.servings,
        cooking_time_min=data.cooking_time_min,
        difficulty=data.difficulty,
        is_dessert=True,
        is_system=False,
        created_by_user_id=user.id,
    )
    db.add(recipe)
    db.flush()

    for ing in data.ingredients:
        # Проверяем, что ингредиент существует
        existing = db.query(Ingredient).filter(Ingredient.id == ing.ingredient_id).first()
        if not existing:
            db.rollback()
            raise HTTPException(status_code=400, detail=f"Ингредиент {ing.ingredient_id} не найден")
        db.add(RecipeIngredient(
            recipe_id=recipe.id,
            ingredient_id=ing.ingredient_id,
            amount=ing.amount,
        ))
    db.commit()

    update_recipe_nutrition(db, recipe)
    log_action(db, "dessert_added", user_id=user.id, ip=get_client_ip(request),
               details=f"recipe_id={recipe.id}")
    return RedirectResponse(url="/desserts", status_code=302)


@router.post("/desserts/{recipe_id}/delete")
async def delete_dessert(
    request: Request,
    recipe_id: int,
    csrf_token: str = Form(...),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
    csrf_protect: CsrfProtect = Depends(),
):
    await csrf_protect.validate_csrf(request)
    # Пользователь может удалять только СВОИ десерты
    recipe = db.query(Recipe).filter(
        Recipe.id == recipe_id,
        Recipe.created_by_user_id == user.id,
        Recipe.is_dessert == True,  # noqa: E712
    ).first()
    if recipe:
        db.delete(recipe)
        db.commit()
    return RedirectResponse(url="/desserts", status_code=302)
