"""
Подключение к SQLite через SQLAlchemy.
Только параметризованные запросы через ORM — защита от SQL-инъекций.
"""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from sqlalchemy.engine import Engine
from app.config import settings


# check_same_thread=False нужен для SQLite+FastAPI (разные потоки)
# Но это безопасно потому что мы используем per-request сессии
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {},
    echo=settings.DEBUG,
)


# Включаем foreign keys в SQLite (по умолчанию выключены)
# и WAL-режим для лучшего конкурентного доступа
@event.listens_for(Engine, "connect")
def _sqlite_on_connect(dbapi_connection, connection_record):
    if settings.DATABASE_URL.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db() -> Session:
    """Dependency для FastAPI: открывает сессию на запрос, гарантированно закрывает."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
