"""
Аутентификация и авторизация.
- bcrypt для паролей (cost=12)
- JWT access + refresh tokens
- Роли: admin / user
- Блокировка аккаунта после N неудачных попыток
- Аудит-логирование всех попыток входа
"""
from datetime import datetime, timedelta
from typing import Optional
import bcrypt
from jose import jwt, JWTError
from fastapi import Depends, HTTPException, Request, status, Cookie
from sqlalchemy.orm import Session
from app.config import settings
from app.database import get_db
from app.models import User, AuditLog


# === Пароли (bcrypt) ===

def hash_password(password: str) -> str:
    # cost=12 — хороший баланс скорости/безопасности в 2026 году
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


# === JWT ===

def create_access_token(user_id: int, role: str) -> str:
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "exp": datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "type": "refresh",
        "exp": datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str, expected_type: str = "access") -> Optional[dict]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") != expected_type:
            return None
        return payload
    except JWTError:
        return None


# === Аудит ===

def log_action(db: Session, action: str, user_id: Optional[int] = None,
               ip: Optional[str] = None, details: Optional[str] = None) -> None:
    entry = AuditLog(user_id=user_id, action=action, ip_address=ip, details=details)
    db.add(entry)
    db.commit()


def get_client_ip(request: Request) -> str:
    # На Render стоит прокси — берём из X-Forwarded-For
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# === Dependency: текущий пользователь ===

def get_current_user(
    request: Request,
    access_token: Optional[str] = Cookie(default=None),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """
    Возвращает текущего пользователя или None, если не залогинен.
    Токен читаем из httpOnly cookie.
    """
    if not access_token:
        return None
    payload = decode_token(access_token, expected_type="access")
    if not payload:
        return None
    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError):
        return None
    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()  # noqa: E712
    return user


def require_user(user: Optional[User] = Depends(get_current_user)) -> User:
    """Требует авторизации. Кидает 401."""
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Нужна авторизация")
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    """Требует роль admin. Кидает 403."""
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Только для администраторов")
    return user


# === Блокировка аккаунта ===

def is_account_locked(user: User) -> bool:
    if user.locked_until and user.locked_until > datetime.utcnow():
        return True
    return False


def register_failed_login(db: Session, user: User) -> None:
    user.failed_login_attempts += 1
    if user.failed_login_attempts >= settings.LOGIN_ATTEMPTS_LIMIT:
        user.locked_until = datetime.utcnow() + timedelta(minutes=settings.LOGIN_BLOCK_MINUTES)
        user.failed_login_attempts = 0
    db.commit()


def register_successful_login(db: Session, user: User) -> None:
    user.failed_login_attempts = 0
    user.locked_until = None
    db.commit()
