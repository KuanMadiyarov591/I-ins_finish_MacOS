from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from iins_actuary_app.auth import require_actuary
from iins_actuary_app.db import get_db
from iins_actuary_app.models import PremiumCase, User

router = APIRouter(prefix="/api/premiums", tags=["premiums"])


def _serialize(c: PremiumCase) -> Dict[str, Any]:
    return {
        "id": c.id,
        "external_id": c.external_id,
        "case_number": c.external_id,
        "territory": c.territory,
        "gender": c.gender,
        "birthdate": c.birthdate,
        "age": c.age,
        "ypc": c.ypc,
        "indicated_premium": c.indicated_premium,
        "selected_premium": c.selected_premium,
        "fixed_expenses": c.fixed_expenses,
        "cgr": c.cgr,
        "cgr_factor": c.cgr_factor,
        "current_premium": c.current_premium,
        "underlying_premium": c.underlying_premium,
        "gap": round(float(c.selected_premium or 0) - float(c.indicated_premium or 0), 2),
    }


@router.get("")
def list_premiums(
    q: Optional[str] = Query(None),
    territory: Optional[str] = Query(None),
    cgr: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_actuary),
) -> Dict[str, Any]:
    query = db.query(PremiumCase)
    if territory:
        query = query.filter(PremiumCase.territory == territory.strip())
    if cgr:
        query = query.filter(PremiumCase.cgr == cgr.strip())
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            (PremiumCase.external_id.ilike(like))
            | (PremiumCase.territory.ilike(like))
            | (PremiumCase.cgr.ilike(like))
        )
    rows: List[PremiumCase] = query.order_by(PremiumCase.id).limit(limit).all()
    items = [_serialize(c) for c in rows]
    territories = sorted({c.territory for c in rows if c.territory})
    cgrs = sorted({c.cgr for c in rows if c.cgr})
    return {
        "items": items,
        "total": len(items),
        "territories": territories,
        "cgrs": cgrs,
    }


@router.get("/{case_id}")
def get_premium(
    case_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_actuary),
) -> Dict[str, Any]:
    c = db.get(PremiumCase, case_id)
    if not c:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Программа не найдена")
    return _serialize(c)
