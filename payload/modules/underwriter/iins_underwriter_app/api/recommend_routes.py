from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from iins_underwriter_app.auth import require_underwriter
from iins_underwriter_app.db import get_db
from iins_underwriter_app.models import UnderwritingCase, User
from iins_underwriter_app.services import recommend_service

router = APIRouter(prefix="/api/recommend", tags=["recommend"])


class ProfileIn(BaseModel):
    line: str = Field(default="auto", description="auto | fraud | motor")
    premium: Optional[float] = None
    risk_hint: Optional[float] = Field(default=None, ge=0, le=100)
    features: Dict[str, Any] = Field(default_factory=dict)


@router.get("/status")
def recommend_status(_: User = Depends(require_underwriter)) -> Dict[str, Any]:
    return recommend_service.status()


@router.get("/case/{case_id}")
def recommend_case_get(
    case_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_underwriter),
) -> Dict[str, Any]:
    c = db.get(UnderwritingCase, case_id)
    if not c:
        raise HTTPException(status_code=404, detail="Кейс не найден")
    return recommend_service.recommend_for_case(c)


@router.post("/case/{case_id}")
def recommend_case_post(
    case_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_underwriter),
) -> Dict[str, Any]:
    c = db.get(UnderwritingCase, case_id)
    if not c:
        raise HTTPException(status_code=404, detail="Кейс не найден")
    return recommend_service.recommend_for_case(c)


@router.post("/profile")
def recommend_profile(
    body: ProfileIn,
    _: User = Depends(require_underwriter),
) -> Dict[str, Any]:
    line = (body.line or "auto").strip().lower()
    if line not in {"auto", "fraud", "motor"}:
        raise HTTPException(status_code=400, detail="line: auto | fraud | motor")
    return recommend_service.recommend_for_profile(body.model_dump())
