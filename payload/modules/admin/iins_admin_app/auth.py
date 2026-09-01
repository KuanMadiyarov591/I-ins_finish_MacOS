from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from iins_admin_app.config import get_settings
from iins_admin_app.db import get_db
from iins_admin_app.models import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
TOKEN_TTL_SEC = 60 * 60 * 12


def hash_password(password: str) -> str:
    # bcrypt принимает не более 72 байт
    return pwd_context.hash((password or "")[:72])


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    try:
        return bool(pwd_context.verify((password or "")[:72], password_hash))
    except Exception:  # noqa: BLE001
        return False


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def create_token(user: User) -> str:
    settings = get_settings()
    payload = {
        "sub": user.id,
        "role": user.role,
        "username": user.username,
        "exp": int(time.time()) + TOKEN_TTL_SEC,
    }
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(settings.secret_key.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{_b64url(sig)}"


def decode_token(token: str) -> dict:
    settings = get_settings()
    try:
        body, sig = token.split(".", 1)
        expected = hmac.new(
            settings.secret_key.encode("utf-8"), body.encode("ascii"), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(expected, _b64url_decode(sig)):
            raise HTTPException(status_code=401, detail="Недействительный токен")
        payload = json.loads(_b64url_decode(body))
        if int(payload.get("exp", 0)) < int(time.time()):
            raise HTTPException(status_code=401, detail="Срок действия токена истёк")
        return payload
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=401, detail="Недействительный токен") from exc


def get_token_from_request(request: Request) -> Optional[str]:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return request.cookies.get("access_token")


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = get_token_from_request(request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Требуется вход")
    payload = decode_token(token)
    user = db.get(User, int(payload["sub"]))
    if not user:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Только для администратора")
    return user


def require_customer(user: User = Depends(get_current_user)) -> User:
    if user.role != "customer":
        raise HTTPException(status_code=403, detail="Только для клиента")
    return user
