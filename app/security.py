"""
Middleware для заголовков безопасности + настройка CSRF.
"""
from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from fastapi_csrf_protect import CsrfProtect
from pydantic_settings import BaseSettings
from app.config import settings


class CsrfSettings(BaseSettings):
    secret_key: str = settings.CSRF_SECRET_KEY
    # lax вместо strict — strict блокирует cookie при переходах по внешним ссылкам
    # и в некоторых сценариях редиректов. Для CSRF защиты lax достаточно.
    cookie_samesite: str = "lax"
    cookie_secure: bool = settings.COOKIE_SECURE
    # Важно: указываем, что токен приходит в теле формы (а не в заголовке),
    # и имя поля формы совпадает с тем, что в HTML-шаблонах (`csrf_token`).
    token_location: str = "body"
    token_key: str = "csrf_token"


@CsrfProtect.load_config
def get_csrf_config():
    return CsrfSettings()


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Добавляет заголовки безопасности ко всем ответам."""
    async def dispatch(self, request: Request, call_next) -> Response:
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        # CSP: разрешаем свои скрипты + Alpine.js с jsdelivr.
        # 'unsafe-eval' нужен Alpine.js для выполнения директив x-data/x-show/@click;
        # 'unsafe-inline' нужен для <script> блоков в шаблонах (shopping.html, admin/recipes.html).
        # XSS через user-input всё равно блокируется Jinja2 autoescape на уровне шаблонов.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none';"
        )
        if settings.COOKIE_SECURE:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


def setup_security(app: FastAPI) -> None:
    app.add_middleware(SecurityHeadersMiddleware)
