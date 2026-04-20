"""
Админ-панель:
- Список пользователей, смена ролей
- CRUD рецептов и ингредиентов
- Просмотр аудит-лога
"""
from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from fastapi_csrf_protect import CsrfProtect
from pydantic import ValidationError
import json

from app.database import get_db
from app.models import User, Recipe, RecipeIngredient, Ingredient, AuditLog
from app.schemas import IngredientCreate, RecipeCreate, RecipeIngredientIn
from app.auth import require_admin, log_action, get_client_ip
from app.services.nutrition import update_recipe_nutrition
from app.config import settings


router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
def admin_dashboard(
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
    csrf_protect: CsrfProtect = Depends(),
):
    users_count = db.query(User).count()
    recipes_count = db.query(Recipe).filter(Recipe.is_system == True).count()  # noqa: E712
    ingredients_count = db.query(Ingredient).count()
    recent_logs = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(30).all()

    csrf_token, signed = csrf_protect.generate_csrf_tokens()
    response = templates.TemplateResponse(
        "admin/dashboard.html",
        {
            "request": request,
            "app_name": settings.APP_NAME,
            "active": "admin",
            "current_user": user,
            "csrf_token": csrf_token,
            "flash_messages": [],
            "users_count": users_count,
            "recipes_count": recipes_count,
            "ingredients_count": ingredients_count,
            "recent_logs": recent_logs,
        },
    )
    csrf_protect.set_csrf_cookie(signed, response)
    return response


@router.get("/users", response_class=HTMLResponse)
def admin_users(
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
    csrf_protect: CsrfProtect = Depends(),
):
    users = db.query(User).order_by(User.created_at.desc()).all()
    csrf_token, signed = csrf_protect.generate_csrf_tokens()
    response = templates.TemplateResponse(
        "admin/users.html",
        {
            "request": request,
            "app_name": settings.APP_NAME,
            "active": "admin",
            "current_user": user,
            "csrf_token": csrf_token,
            "flash_messages": [],
            "users": users,
        },
    )
    csrf_protect.set_csrf_cookie(signed, response)
    return response


@router.post("/users/{user_id}/role")
async def change_role(
    request: Request,
    user_id: int,
    role: str = Form(...),
    csrf_token: str = Form(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
    csrf_protect: CsrfProtect = Depends(),
):
    await csrf_protect.validate_csrf(request)
    if role not in {"admin", "user"}:
        raise HTTPException(status_code=400, detail="Недопустимая роль")
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404)
    # Защита: админ не может понизить себя (минимум один админ должен остаться)
    if target.id == user.id and role != "admin":
        admin_count = db.query(User).filter(User.role == "admin").count()
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="Нельзя понизить единственного администратора")
    old_role = target.role
    target.role = role
    db.commit()
    log_action(db, "role_change", user_id=user.id, ip=get_client_ip(request),
               details=f"target={target.id} {old_role}->{role}")
    return RedirectResponse(url="/admin/users", status_code=302)


@router.post("/users/{user_id}/toggle-active")
async def toggle_active(
    request: Request,
    user_id: int,
    csrf_token: str = Form(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
    csrf_protect: CsrfProtect = Depends(),
):
    await csrf_protect.validate_csrf(request)
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404)
    if target.id == user.id:
        raise HTTPException(status_code=400, detail="Нельзя заблокировать себя")
    target.is_active = not target.is_active
    db.commit()
    log_action(db, "user_active_toggle", user_id=user.id, ip=get_client_ip(request),
               details=f"target={target.id} active={target.is_active}")
    return RedirectResponse(url="/admin/users", status_code=302)


# === Ингредиенты ===

@router.get("/ingredients", response_class=HTMLResponse)
def admin_ingredients(
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
    csrf_protect: CsrfProtect = Depends(),
):
    ingredients = db.query(Ingredient).order_by(Ingredient.name).all()
    csrf_token, signed = csrf_protect.generate_csrf_tokens()
    response = templates.TemplateResponse(
        "admin/ingredients.html",
        {
            "request": request,
            "app_name": settings.APP_NAME,
            "active": "admin",
            "current_user": user,
            "csrf_token": csrf_token,
            "flash_messages": [],
            "ingredients": ingredients,
        },
    )
    csrf_protect.set_csrf_cookie(signed, response)
    return response


@router.post("/ingredients/add")
async def admin_add_ingredient(
    request: Request,
    name: str = Form(...),
    unit: str = Form("г"),
    calories_per_100: float = Form(0),
    protein_per_100: float = Form(0),
    fat_per_100: float = Form(0),
    carbs_per_100: float = Form(0),
    category: str = Form(""),
    csrf_token: str = Form(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
    csrf_protect: CsrfProtect = Depends(),
):
    await csrf_protect.validate_csrf(request)
    try:
        data = IngredientCreate(
            name=name, unit=unit,
            calories_per_100=calories_per_100, protein_per_100=protein_per_100,
            fat_per_100=fat_per_100, carbs_per_100=carbs_per_100,
            category=category or None,
        )
    except ValidationError as e:
        raise HTTPException(status_code=400, detail="; ".join(err["msg"] for err in e.errors()))

    # Проверка уникальности
    existing = db.query(Ingredient).filter(Ingredient.name == data.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Ингредиент с таким названием уже существует")

    ing = Ingredient(**data.model_dump())
    db.add(ing)
    db.commit()
    log_action(db, "ingredient_added", user_id=user.id, ip=get_client_ip(request),
               details=f"name={data.name}")
    return RedirectResponse(url="/admin/ingredients", status_code=302)


# === Рецепты ===

@router.get("/recipes", response_class=HTMLResponse)
def admin_recipes(
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
    csrf_protect: CsrfProtect = Depends(),
):
    recipes = db.query(Recipe).filter(Recipe.is_system == True).order_by(Recipe.name).all()  # noqa: E712
    ingredients = db.query(Ingredient).order_by(Ingredient.name).all()
    csrf_token, signed = csrf_protect.generate_csrf_tokens()
    response = templates.TemplateResponse(
        "admin/recipes.html",
        {
            "request": request,
            "app_name": settings.APP_NAME,
            "active": "admin",
            "current_user": user,
            "csrf_token": csrf_token,
            "flash_messages": [],
            "recipes": recipes,
            "all_ingredients": ingredients,
        },
    )
    csrf_protect.set_csrf_cookie(signed, response)
    return response


@router.post("/recipes/add")
async def admin_add_recipe(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    instructions: str = Form(""),
    servings: int = Form(4),
    cooking_time_min: int = Form(30),
    difficulty: str = Form("easy"),
    is_dessert: bool = Form(False),
    meal_types_json: str = Form("[]"),
    moods_json: str = Form("[]"),
    ingredients_json: str = Form("[]"),
    csrf_token: str = Form(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
    csrf_protect: CsrfProtect = Depends(),
):
    await csrf_protect.validate_csrf(request)

    try:
        meal_types = json.loads(meal_types_json)
        moods = json.loads(moods_json)
        ing_list = json.loads(ingredients_json)
        parsed_ingredients = [RecipeIngredientIn(**item) for item in ing_list]
    except (json.JSONDecodeError, ValueError, ValidationError) as e:
        raise HTTPException(status_code=400, detail=f"Некорректный формат данных: {e}")

    try:
        data = RecipeCreate(
            name=name, description=description or None, instructions=instructions or None,
            meal_types=meal_types, moods=moods,
            servings=servings, cooking_time_min=cooking_time_min, difficulty=difficulty,
            is_dessert=is_dessert, ingredients=parsed_ingredients,
        )
    except ValidationError as e:
        raise HTTPException(status_code=400, detail="; ".join(err["msg"] for err in e.errors()))

    recipe = Recipe(
        name=data.name, description=data.description, instructions=data.instructions,
        meal_types=data.meal_types, moods=data.moods,
        servings=data.servings, cooking_time_min=data.cooking_time_min,
        difficulty=data.difficulty, is_dessert=data.is_dessert,
        is_system=True, created_by_user_id=None,
    )
    db.add(recipe)
    db.flush()

    for ing in data.ingredients:
        existing = db.query(Ingredient).filter(Ingredient.id == ing.ingredient_id).first()
        if not existing:
            db.rollback()
            raise HTTPException(status_code=400, detail=f"Ингредиент {ing.ingredient_id} не найден")
        db.add(RecipeIngredient(recipe_id=recipe.id, ingredient_id=ing.ingredient_id, amount=ing.amount))
    db.commit()

    update_recipe_nutrition(db, recipe)
    log_action(db, "recipe_added", user_id=user.id, ip=get_client_ip(request),
               details=f"recipe_id={recipe.id}")
    return RedirectResponse(url="/admin/recipes", status_code=302)


@router.post("/recipes/{recipe_id}/delete")
async def admin_delete_recipe(
    request: Request,
    recipe_id: int,
    csrf_token: str = Form(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
    csrf_protect: CsrfProtect = Depends(),
):
    await csrf_protect.validate_csrf(request)
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id, Recipe.is_system == True).first()  # noqa: E712
    if recipe:
        db.delete(recipe)
        db.commit()
        log_action(db, "recipe_deleted", user_id=user.id, ip=get_client_ip(request),
                   details=f"recipe_id={recipe_id}")
    return RedirectResponse(url="/admin/recipes", status_code=302)
