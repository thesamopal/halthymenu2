"""
Конфигурация приложения. Все секреты — только из переменных окружения.
Никаких хардкод-ключей.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
import secrets


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Основное
    APP_NAME: str = "Мятный Планер"
    DEBUG: bool = False

    # БД — на Render смонтируем persistent disk в /data
    DATABASE_URL: str = "sqlite:///./data/planner.db"

    # Безопасность
    # SECRET_KEY ОБЯЗАТЕЛЬНО задавать в env на проде.
    # Локально — автогенерится случайный, чтобы не хардкодить.
    SECRET_KEY: str = secrets.token_urlsafe(64)
    CSRF_SECRET_KEY: str = secrets.token_urlsafe(64)

    # JWT
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    JWT_ALGORITHM: str = "HS256"

    # Админ-bootstrap
    # Email первого админа. При регистрации с этим email автоматом выдаётся роль admin.
    INITIAL_ADMIN_EMAIL: str = ""

    # Rate limiting
    LOGIN_ATTEMPTS_LIMIT: int = 10          # попыток до блокировки
    LOGIN_BLOCK_MINUTES: int = 15           # на сколько блокировать аккаунт
    RATE_LIMIT_LOGIN: str = "5/minute"      # на IP
    RATE_LIMIT_REGISTER: str = "3/minute"   # на IP

    # Куки
    COOKIE_SECURE: bool = True              # False только для локальной разработки
    COOKIE_SAMESITE: str = "strict"

    # Пути
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    DATA_DIR: Path = BASE_DIR / "data"


settings = Settings()

# Гарантируем, что папка data существует
settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
