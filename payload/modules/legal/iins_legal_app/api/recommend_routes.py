from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from iins_legal_app.auth import require_lawyer
from iins_legal_app.db import get_db
from iins_legal_app.models import LegalCase, User
from iins_legal_app.services import recommend_service

router = APIRouter(prefix="/api/recommend", tags=["recommend"])


class ProfileIn(BaseModel):
    line: str = Field(default="pi", description="pi | imr")
    amount: Optional[float] = None
    premium: Optional[float] = None  # UW-compat alias for amount
    risk_hint: Optional[float] = Field(default=None, ge=0, le=100)
    appeal_type: Optional[str] = None
    text: Optional[str] = None
    features: Dict[str, Any] = Field(default_factory=dict)


@router.get("/status")
def recommend_status(_: User = Depends(require_lawyer)) -> Dict[str, Any]:
    return recommend_service.status()


@router.get("/case/{case_id}")
def recommend_case_get(
    case_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_lawyer),
) -> Dict[str, Any]:
    c = db.get(LegalCase, case_id)
    if not c:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    return recommend_service.recommend_for_case(c)


@router.post("/case/{case_id}")
def recommend_case_post(
    case_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_lawyer),
) -> Dict[str, Any]:
    c = db.get(LegalCase, case_id)
    if not c:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    return recommend_service.recommend_for_case(c)


@router.post("/profile")
def recommend_profile(
    body: ProfileIn,
    _: User = Depends(require_lawyer),
) -> Dict[str, Any]:
    line = (body.line or "pi").strip().lower()
    if line not in {"pi", "imr"}:
        raise HTTPException(status_code=400, detail="line: pi | imr")
    return recommend_service.recommend_for_profile(body.model_dump())
