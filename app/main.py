"""
Главный файл FastAPI приложения.
Собирает все роутеры, middleware, обработчики ошибок.
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.exceptions import HTTPException
from sqlalchemy.orm import Session
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from fastapi_csrf_protect.exceptions import CsrfProtectError
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.config import settings
from app.database import Base, engine, get_db
from app.models import User
from app.security import setup_security
from app.ratelimit import limiter
from app.auth import get_current_user
from app.routes import auth, planner, exclusions, shopping, desserts, prices, admin


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup: создаём таблицы, если их нет.
    На проде для сложных миграций использовать Alembic; для SQLite create_all достаточно.
    """
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title=settings.APP_NAME,
    description="Рандомный планер питания по настроению",
    version="1.0.0",
    # Выключаем docs на проде — лишняя атакоповерхность
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url=None,
    lifespan=lifespan,
)

# Middleware: заголовки безопасности, CSP, HSTS
setup_security(app)

# ProxyHeadersMiddleware — Render стоит за прокси (Cloudflare).
# Этот middleware заставляет Starlette доверять заголовкам X-Forwarded-For и X-Forwarded-Proto,
# чтобы request.url.scheme был "https", а не "http". Без него Secure cookies не работают.
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

# Rate limiting
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)


# === Обработчики ошибок ===

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return HTMLResponse(
        "<h1>Слишком много запросов</h1><p>Попробуй через минуту.</p>",
        status_code=429,
    )


@app.exception_handler(CsrfProtectError)
async def csrf_error_handler(request: Request, exc: CsrfProtectError):
    """При ошибке CSRF — показываем детали, чтобы было видно причину в браузере."""
    import logging
    logging.error(f"CSRF error on {request.method} {request.url.path}: {exc.message}")
    return HTMLResponse(
        f"<h1>CSRF ошибка (403)</h1>"
        f"<p><b>Путь:</b> {request.method} {request.url.path}</p>"
        f"<p><b>Причина:</b> {exc.message}</p>"
        f"<p><a href='/'>На главную</a></p>",
        status_code=403,
    )


@app.exception_handler(404)
async def not_found_handler(request: Request, exc: HTTPException):
    user = None
    try:
        # Пытаемся получить юзера, чтобы показать навигацию корректно
        from app.auth import decode_token
        token = request.cookies.get("access_token")
        if token:
            payload = decode_token(token, "access")
            if payload:
                from app.database import SessionLocal
                db = SessionLocal()
                try:
                    user = db.query(User).filter(User.id == int(payload["sub"])).first()
                finally:
                    db.close()
    except Exception:
        pass
    tpl = Jinja2Templates(directory="app/templates")
    return tpl.TemplateResponse(
        "error.html",
        {
            "request": request,
            "app_name": settings.APP_NAME,
            "active": None,
            "current_user": user,
            "csrf_token": "",
            "flash_messages": [],
            "error_code": 404,
            "error_message": "Страница не найдена",
        },
        status_code=404,
    )


# === Статика ===

app.mount("/static", StaticFiles(directory="app/static"), name="static")


# === Главная страница ===

templates = Jinja2Templates(directory="app/templates")


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    user: User | None = Depends(get_current_user),
):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "app_name": settings.APP_NAME,
            "active": "home",
            "current_user": user,
            "csrf_token": "",
            "flash_messages": [],
        },
    )


@app.get("/healthz")
def healthz():
    """Health check для Render."""
    return {"status": "ok"}


# === Подключаем роутеры ===

app.include_router(auth.router)
app.include_router(planner.router)
app.include_router(exclusions.router)
app.include_router(shopping.router)
app.include_router(desserts.router)
app.include_router(prices.router)
app.include_router(admin.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=settings.DEBUG)
