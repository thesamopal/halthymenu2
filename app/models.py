"""
Модели БД. Используем ORM — никакого сырого SQL из пользовательского ввода.
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, ForeignKey,
    Text, Date, UniqueConstraint, Index, JSON
)
from sqlalchemy.orm import relationship
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)   # bcrypt
    role = Column(String(20), nullable=False, default="user")  # 'user' | 'admin'
    is_active = Column(Boolean, default=True, nullable=False)

    # Для защиты от brute-force
    failed_login_attempts = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime, nullable=True)

    # Цели пользователя
    daily_calories = Column(Integer, default=2000, nullable=False)
    target_protein = Column(Float, default=100.0, nullable=False)  # грамм/сут
    target_fat = Column(Float, default=70.0, nullable=False)
    target_carbs = Column(Float, default=250.0, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Связи
    exclusions = relationship("Exclusion", back_populates="user", cascade="all, delete-orphan")
    plans = relationship("MonthlyPlan", back_populates="user", cascade="all, delete-orphan")
    custom_desserts = relationship("Recipe", back_populates="created_by_user",
                                    foreign_keys="Recipe.created_by_user_id")


class Ingredient(Base):
    """Справочник ингредиентов с БЖУ на 100г."""
    __tablename__ = "ingredients"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), unique=True, nullable=False, index=True)
    unit = Column(String(20), default="г", nullable=False)  # 'г', 'мл', 'шт'

    # БЖУ на 100г (или 100мл, или 1шт для штучных)
    calories_per_100 = Column(Float, default=0.0, nullable=False)
    protein_per_100 = Column(Float, default=0.0, nullable=False)
    fat_per_100 = Column(Float, default=0.0, nullable=False)
    carbs_per_100 = Column(Float, default=0.0, nullable=False)

    category = Column(String(50), nullable=True)  # 'мясо', 'овощи' и т.д. для группировки в закупках


class Recipe(Base):
    __tablename__ = "recipes"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(300), nullable=False, index=True)
    description = Column(Text, nullable=True)
    instructions = Column(Text, nullable=True)

    # Типы приёмов пищи (JSON-массив: ['breakfast', 'lunch', 'dinner', 'snack', 'late_snack', 'dessert'])
    meal_types = Column(JSON, nullable=False, default=list)

    # Настроение (теги: 'уютное', 'бодрящее', 'лёгкое', 'сытное', 'острое', 'сладкое' ...)
    moods = Column(JSON, nullable=False, default=list)

    # Порций в рецепте (БЖУ хранится в пересчёте на 1 порцию)
    servings = Column(Integer, default=1, nullable=False)

    # БЖУ на порцию — кэшированный пересчёт для быстрой выборки
    calories_per_serving = Column(Float, default=0.0, nullable=False)
    protein_per_serving = Column(Float, default=0.0, nullable=False)
    fat_per_serving = Column(Float, default=0.0, nullable=False)
    carbs_per_serving = Column(Float, default=0.0, nullable=False)

    cooking_time_min = Column(Integer, default=30, nullable=False)
    difficulty = Column(String(20), default="easy", nullable=False)  # easy/medium/hard
    is_dessert = Column(Boolean, default=False, nullable=False)

    # Для пользовательских рецептов (десертов)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    is_system = Column(Boolean, default=True, nullable=False)  # системные vs пользовательские

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    ingredients = relationship("RecipeIngredient", back_populates="recipe", cascade="all, delete-orphan")
    created_by_user = relationship("User", back_populates="custom_desserts",
                                    foreign_keys=[created_by_user_id])

    __table_args__ = (
        Index("ix_recipes_meal_dessert", "is_dessert"),
    )


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredients"

    id = Column(Integer, primary_key=True, index=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False, index=True)
    ingredient_id = Column(Integer, ForeignKey("ingredients.id", ondelete="RESTRICT"), nullable=False)
    amount = Column(Float, nullable=False)   # в единицах ингредиента на весь рецепт (не на порцию)

    recipe = relationship("Recipe", back_populates="ingredients")
    ingredient = relationship("Ingredient")


class Exclusion(Base):
    """Исключения продуктов пользователя (аллергии, не люблю)."""
    __tablename__ = "exclusions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    ingredient_id = Column(Integer, ForeignKey("ingredients.id", ondelete="CASCADE"), nullable=False)
    reason = Column(String(200), nullable=True)  # 'аллергия', 'не люблю', ...

    user = relationship("User", back_populates="exclusions")
    ingredient = relationship("Ingredient")

    __table_args__ = (
        UniqueConstraint("user_id", "ingredient_id", name="uq_user_ingredient_exclusion"),
    )


class MonthlyPlan(Base):
    """План на месяц. Один план = один месяц для одного пользователя."""
    __tablename__ = "monthly_plans"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)    # 1..12

    # Сохраняем настройки, с которыми был сгенерирован план
    daily_calories = Column(Integer, nullable=False)

    # Порций на каждый приём пищи на день (настраивается перед генерацией)
    servings_breakfast = Column(Integer, default=1, nullable=False)
    servings_lunch = Column(Integer, default=1, nullable=False)
    servings_snack = Column(Integer, default=1, nullable=False)
    servings_dinner = Column(Integer, default=1, nullable=False)
    servings_late_snack = Column(Integer, default=1, nullable=False)
    desserts_per_week = Column(Integer, default=2, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="plans")
    days = relationship("PlanDay", back_populates="plan", cascade="all, delete-orphan")
    shopping_items = relationship("ShoppingItem", back_populates="plan", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("user_id", "year", "month", name="uq_user_year_month"),
    )


class PlanDay(Base):
    """Меню на конкретный день."""
    __tablename__ = "plan_days"

    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(Integer, ForeignKey("monthly_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    date = Column(Date, nullable=False)

    plan = relationship("MonthlyPlan", back_populates="days")
    meals = relationship("PlanMeal", back_populates="day", cascade="all, delete-orphan")


class PlanMeal(Base):
    """Конкретное блюдо в конкретный приём пищи в конкретный день."""
    __tablename__ = "plan_meals"

    id = Column(Integer, primary_key=True, index=True)
    day_id = Column(Integer, ForeignKey("plan_days.id", ondelete="CASCADE"), nullable=False, index=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id", ondelete="RESTRICT"), nullable=False)
    meal_type = Column(String(20), nullable=False)   # 'breakfast' | 'lunch' | ... | 'dessert'
    servings = Column(Integer, default=1, nullable=False)

    day = relationship("PlanDay", back_populates="meals")
    recipe = relationship("Recipe")


class ShoppingItem(Base):
    """Строка в списке покупок (агрегат ингредиентов на весь план)."""
    __tablename__ = "shopping_items"

    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(Integer, ForeignKey("monthly_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    ingredient_id = Column(Integer, ForeignKey("ingredients.id", ondelete="RESTRICT"), nullable=False)
    total_amount = Column(Float, nullable=False)   # суммарное количество по всему плану
    week_number = Column(Integer, nullable=True)   # 1..5, null = на весь месяц

    is_purchased = Column(Boolean, default=False, nullable=False)
    actual_price = Column(Float, nullable=True)     # заполняется после покупки
    purchased_at = Column(DateTime, nullable=True)

    plan = relationship("MonthlyPlan", back_populates="shopping_items")
    ingredient = relationship("Ingredient")


class PriceHistory(Base):
    """История цен — для прогнозов."""
    __tablename__ = "price_history"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    ingredient_id = Column(Integer, ForeignKey("ingredients.id", ondelete="CASCADE"), nullable=False)
    price = Column(Float, nullable=False)           # цена за единицу ингредиента
    amount = Column(Float, nullable=False)          # сколько купили
    recorded_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AuditLog(Base):
    """Аудит-лог: входы, админ-действия, изменения ролей."""
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    action = Column(String(100), nullable=False)    # 'login_success', 'login_failed', 'role_change', ...
    ip_address = Column(String(45), nullable=True)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
