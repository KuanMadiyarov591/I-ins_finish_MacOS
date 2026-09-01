from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from iins_client_app.api.helpers import user_out
from iins_client_app.auth import create_token, get_current_user, hash_password, verify_password
from iins_client_app.config import get_settings
from iins_client_app.db import get_db
from iins_client_app.models import User
from iins_client_app.schemas import LoginIn, SignupIn, TokenOut, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _surface() -> str:
    s = (get_settings().app_surface or "client").strip().lower()
    return s if s in ("client", "admin") else "client"


@router.post("/signup", response_model=TokenOut)
def signup(body: SignupIn, db: Session = Depends(get_db)) -> TokenOut:
    if _surface() != "client":
        raise HTTPException(
            status_code=403,
            detail=f"Регистрация клиентов только на порту {get_settings().client_port}",
        )
    username = body.username.strip()
    if db.query(User).filter(func.lower(User.username) == username.lower()).first():
        raise HTTPException(status_code=400, detail="Имя пользователя уже занято")
    user = User(
        username=username,
        password_hash=hash_password(body.password),
        first_name=body.first_name.strip(),
        last_name=body.last_name.strip(),
        role="customer",
        address=body.address.strip(),
        mobile=body.mobile.strip(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_token(user)
    return TokenOut(
        access_token=token,
        role=user.role,
        username=user.username,
        user_id=user.id,
        full_name=f"{user.first_name} {user.last_name}".strip() or user.username,
    )


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)) -> TokenOut:
    username = (body.username or "").strip()
    password = body.password or ""
    user = (
        db.query(User)
        .filter(func.lower(User.username) == username.lower())
        .first()
    )
    ok = False
    if user:
        try:
            ok = verify_password(password, user.password_hash)
        except Exception:  # noqa: BLE001 — битый hash / несовместимый bcrypt
            ok = False
    if not user or not ok:
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")

    surface = _surface()
    settings = get_settings()
    if surface == "admin" and user.role != "admin":
        raise HTTPException(
            status_code=403,
            detail=f"Кабинет компании только для админа. Клиент: http://127.0.0.1:{settings.client_port}/",
        )
    if surface == "client" and user.role == "admin":
        raise HTTPException(
            status_code=403,
            detail=f"Админ-вход на http://127.0.0.1:{settings.admin_port}/",
        )

    token = create_token(user)
    return TokenOut(
        access_token=token,
        role=user.role,
        username=user.username,
        user_id=user.id,
        full_name=f"{user.first_name} {user.last_name}".strip() or user.username,
    )

@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return user_out(user)
