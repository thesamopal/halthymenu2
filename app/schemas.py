"""
Pydantic-схемы для валидации ВСЕГО пользовательского ввода.
Без них данные из форм и JSON не попадают в БД.
"""
from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional, List
from datetime import date, datetime


# === Пользователь ===

class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not any(c.isdigit() for c in v):
            raise ValueError("Пароль должен содержать хотя бы одну цифру")
        if not any(c.isalpha() for c in v):
            raise ValueError("Пароль должен содержать хотя бы одну букву")
        return v


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserGoals(BaseModel):
    daily_calories: int = Field(ge=800, le=6000)
    target_protein: float = Field(ge=10, le=400)
    target_fat: float = Field(ge=10, le=300)
    target_carbs: float = Field(ge=10, le=800)


# === Рецепты ===

class RecipeIngredientIn(BaseModel):
    ingredient_id: int = Field(ge=1)
    amount: float = Field(gt=0, le=100000)


class RecipeCreate(BaseModel):
    name: str = Field(min_length=2, max_length=300)
    description: Optional[str] = Field(default=None, max_length=2000)
    instructions: Optional[str] = Field(default=None, max_length=10000)
    meal_types: List[str] = Field(default_factory=list)
    moods: List[str] = Field(default_factory=list)
    servings: int = Field(default=1, ge=1, le=50)
    cooking_time_min: int = Field(default=30, ge=1, le=1440)
    difficulty: str = Field(default="easy")
    is_dessert: bool = False
    ingredients: List[RecipeIngredientIn] = Field(default_factory=list)

    @field_validator("meal_types")
    @classmethod
    def validate_meal_types(cls, v: List[str]) -> List[str]:
        allowed = {"breakfast", "lunch", "snack", "dinner", "late_snack", "dessert"}
        for m in v:
            if m not in allowed:
                raise ValueError(f"Недопустимый приём пищи: {m}")
        return v

    @field_validator("difficulty")
    @classmethod
    def validate_difficulty(cls, v: str) -> str:
        if v not in {"easy", "medium", "hard"}:
            raise ValueError("Сложность: easy/medium/hard")
        return v


# === Исключения ===

class ExclusionCreate(BaseModel):
    ingredient_id: int = Field(ge=1)
    reason: Optional[str] = Field(default=None, max_length=200)


# === План ===

class PlanSettings(BaseModel):
    year: int = Field(ge=2024, le=2100)
    month: int = Field(ge=1, le=12)
    daily_calories: int = Field(ge=800, le=6000)
    servings_breakfast: int = Field(default=1, ge=0, le=20)
    servings_lunch: int = Field(default=1, ge=0, le=20)
    servings_snack: int = Field(default=1, ge=0, le=20)
    servings_dinner: int = Field(default=1, ge=0, le=20)
    servings_late_snack: int = Field(default=0, ge=0, le=20)
    desserts_per_week: int = Field(default=2, ge=0, le=14)


# === Покупки ===

class ShoppingItemUpdate(BaseModel):
    is_purchased: Optional[bool] = None
    actual_price: Optional[float] = Field(default=None, ge=0, le=1000000)


# === Ингредиенты (для админки) ===

class IngredientCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    unit: str = Field(default="г", max_length=20)
    calories_per_100: float = Field(ge=0, le=2000)
    protein_per_100: float = Field(ge=0, le=200)
    fat_per_100: float = Field(ge=0, le=200)
    carbs_per_100: float = Field(ge=0, le=200)
    category: Optional[str] = Field(default=None, max_length=50)
