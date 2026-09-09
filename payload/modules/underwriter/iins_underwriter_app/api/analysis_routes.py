"""Маршруты интерактивного анализа кабинета андеррайтера."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from iins_underwriter_app.auth import require_underwriter
from iins_underwriter_app.db import get_db
from iins_underwriter_app.models import User
from iins_underwriter_app.services import analysis_service

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


@router.get("/data")
def analysis_data(
    db: Session = Depends(get_db),
    user: User = Depends(require_underwriter),
) -> Dict[str, Any]:
    """Один пакет на всю вкладку: пороги двигаются без обращений к серверу."""
    data = analysis_service.package(db)
    data["user"] = user.username
    return data
