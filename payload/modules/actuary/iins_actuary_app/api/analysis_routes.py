"""Маршруты интерактивного анализа кабинета актуария."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from iins_actuary_app.auth import require_actuary
from iins_actuary_app.db import get_db
from iins_actuary_app.models import User
from iins_actuary_app.services import analysis_service

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


@router.get("/data")
def analysis_data(
    db: Session = Depends(get_db),
    user: User = Depends(require_actuary),
) -> Dict[str, Any]:
    """Один пакет на всю вкладку: дальше страница считает сама."""
    data = analysis_service.package(db)
    data["user"] = user.username
    return data
