"""
Маршруты авторизации: регистрация, вход, выход, обновление токена.
"""
from datetime import datetime
from fastapi import APIRouter, Depends, Request, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.orm import Session
from fastapi_csrf_protect import CsrfProtect

from app.database import get_db
from app.models import User
from app.schemas import UserRegister, UserLogin
from app.auth import (
    hash_password, verify_password, create_access_token, create_refresh_token,
    is_account_locked, register_failed_login, register_successful_login,
    log_action, get_client_ip, get_current_user,
)
from app.config import settings
from app.ratelimit import limiter


router = APIRouter(prefix="/auth", tags=["auth"])
templates = Jinja2Templates(directory="app/templates")


def _set_auth_cookies(response, user: User) -> None:
    access = create_access_token(user.id, user.role)
    refresh = create_refresh_token(user.id)
    response.set_cookie(
        key="access_token",
        value=access,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600,
        path="/auth",
    )


def _clear_auth_cookies(response) -> None:
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/auth")


# === Регистрация ===

@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request, csrf_protect: CsrfProtect = Depends()):
    csrf_token, signed = csrf_protect.generate_csrf_tokens()
    response = templates.TemplateResponse(
        "auth/register.html",
        {"request": request, "app_name": settings.APP_NAME, "active": "register",
         "current_user": None, "csrf_token": csrf_token, "flash_messages": []},
    )
    csrf_protect.set_csrf_cookie(signed, response)
    return response


@router.post("/register")
@limiter.limit(settings.RATE_LIMIT_REGISTER)
async def register(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
    csrf_protect: CsrfProtect = Depends(),
):
    await csrf_protect.validate_csrf(request)

    # Валидация через Pydantic
    try:
        data = UserRegister(email=email, password=password)
    except ValidationError as e:
        new_csrf, signed = csrf_protect.generate_csrf_tokens()
        response = templates.TemplateResponse(
            "auth/register.html",
            {"request": request, "app_name": settings.APP_NAME, "active": "register",
             "current_user": None, "csrf_token": new_csrf, "email": email,
             "error": "; ".join(err["msg"] for err in e.errors()),
             "flash_messages": []},
            status_code=400,
        )
        csrf_protect.set_csrf_cookie(signed, response)
        return response

    # Уникальность email
    existing = db.query(User).filter(User.email == data.email.lower()).first()
    if existing:
        new_csrf, signed = csrf_protect.generate_csrf_tokens()
        response = templates.TemplateResponse(
            "auth/register.html",
            {"request": request, "app_name": settings.APP_NAME, "active": "register",
             "current_user": None, "csrf_token": new_csrf, "email": email,
             "error": "Пользователь с таким email уже существует",
             "flash_messages": []},
            status_code=400,
        )
        csrf_protect.set_csrf_cookie(signed, response)
        return response

    # Создание пользователя
    role = "admin" if (settings.INITIAL_ADMIN_EMAIL
                        and data.email.lower() == settings.INITIAL_ADMIN_EMAIL.lower()) else "user"
    user = User(
        email=data.email.lower(),
        password_hash=hash_password(data.password),
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    log_action(db, "user_registered", user_id=user.id, ip=get_client_ip(request))

    response = RedirectResponse(url="/planner", status_code=302)
    _set_auth_cookies(response, user)
    return response


# === Вход ===

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, csrf_protect: CsrfProtect = Depends()):
    csrf_token, signed = csrf_protect.generate_csrf_tokens()
    response = templates.TemplateResponse(
        "auth/login.html",
        {"request": request, "app_name": settings.APP_NAME, "active": "login",
         "current_user": None, "csrf_token": csrf_token, "flash_messages": []},
    )
    csrf_protect.set_csrf_cookie(signed, response)
    return response


@router.post("/login")
@limiter.limit(settings.RATE_LIMIT_LOGIN)
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
    csrf_protect: CsrfProtect = Depends(),
):
    await csrf_protect.validate_csrf(request)

    try:
        data = UserLogin(email=email, password=password)
    except ValidationError:
        return _login_error(request, csrf_protect, email, "Неверный формат данных")

    user = db.query(User).filter(User.email == data.email.lower()).first()

    if not user or not user.is_active:
        log_action(db, "login_failed", ip=get_client_ip(request),
                   details=f"unknown_email:{email[:60]}")
        return _login_error(request, csrf_protect, email, "Неверный email или пароль")

    if is_account_locked(user):
        log_action(db, "login_blocked", user_id=user.id, ip=get_client_ip(request))
        return _login_error(request, csrf_protect, email,
                            "Аккаунт временно заблокирован из-за множественных неудачных попыток")

    if not verify_password(data.password, user.password_hash):
        register_failed_login(db, user)
        log_action(db, "login_failed", user_id=user.id, ip=get_client_ip(request))
        return _login_error(request, csrf_protect, email, "Неверный email или пароль")

    register_successful_login(db, user)
    log_action(db, "login_success", user_id=user.id, ip=get_client_ip(request))

    response = RedirectResponse(url="/planner", status_code=302)
    _set_auth_cookies(response, user)
    return response


def _login_error(request, csrf_protect, email, error):
    new_csrf, signed = csrf_protect.generate_csrf_tokens()
    response = templates.TemplateResponse(
        "auth/login.html",
        {"request": request, "app_name": settings.APP_NAME, "active": "login",
         "current_user": None, "csrf_token": new_csrf, "email": email,
         "error": error, "flash_messages": []},
        status_code=401,
    )
    csrf_protect.set_csrf_cookie(signed, response)
    return response


# === Выход ===

@router.post("/logout")
async def logout(
    request: Request,
    csrf_token: str = Form(...),
    csrf_protect: CsrfProtect = Depends(),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await csrf_protect.validate_csrf(request)
    if user:
        log_action(db, "logout", user_id=user.id, ip=get_client_ip(request))
    response = RedirectResponse(url="/", status_code=302)
    _clear_auth_cookies(response)
    return response
