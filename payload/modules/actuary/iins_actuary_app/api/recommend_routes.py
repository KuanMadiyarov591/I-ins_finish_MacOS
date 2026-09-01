from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from iins_actuary_app.auth import require_actuary
from iins_actuary_app.db import get_db
from iins_actuary_app.models import PremiumCase, User
from iins_actuary_app.services import recommend_service

router = APIRouter(prefix="/api/recommend", tags=["recommend"])


class ProfileIn(BaseModel):
    territory: Optional[str] = None
    gender: Optional[str] = None
    cgr: Optional[str] = None
    age: Optional[float] = Field(default=None, ge=16, le=100)
    ypc: Optional[float] = Field(default=None, ge=0, le=20)
    indicated_premium: Optional[float] = Field(default=None, ge=0)
    fixed_expenses: Optional[float] = Field(default=None, ge=0)
    priority: Optional[float] = Field(default=None, ge=0, le=100, description="stub priority")
    case_id: Optional[int] = None
    features: Dict[str, Any] = Field(default_factory=dict)


@router.get("/status")
def recommend_status(_: User = Depends(require_actuary)) -> Dict[str, Any]:
    return recommend_service.status()


@router.get("/options")
def recommend_options(
    db: Session = Depends(get_db),
    _: User = Depends(require_actuary),
) -> Dict[str, Any]:
    rows = db.query(PremiumCase).all()
    territories = sorted({r.territory for r in rows if r.territory})
    genders = sorted({r.gender for r in rows if r.gender})
    cgrs = sorted({r.cgr for r in rows if r.cgr})
    return {
        "territories": territories[:80],
        "genders": genders or ["M", "F"],
        "cgrs": cgrs[:80],
        "cases": [
            {
                "id": r.id,
                "label": f"{r.external_id} · T{r.territory} · {r.cgr}",
                "territory": r.territory,
                "gender": r.gender,
                "cgr": r.cgr,
                "age": r.age,
                "ypc": r.ypc,
                "indicated_premium": r.indicated_premium,
                "fixed_expenses": r.fixed_expenses,
            }
            for r in rows[:120]
        ],
    }


@router.post("/profile")
def recommend_profile(
    body: ProfileIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_actuary),
) -> Dict[str, Any]:
    payload = body.model_dump()
    if body.case_id:
        c = db.get(PremiumCase, body.case_id)
        if not c:
            raise HTTPException(status_code=404, detail="Программа не найдена")
        return recommend_service.recommend_for_case(c, overrides=payload)
    return recommend_service.recommend_for_profile(payload)


@router.get("/case/{case_id}")
def recommend_case(
    case_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_actuary),
) -> Dict[str, Any]:
    c = db.get(PremiumCase, case_id)
    if not c:
        raise HTTPException(status_code=404, detail="Программа не найдена")
    return recommend_service.recommend_for_case(c)
