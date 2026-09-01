from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from iins_underwriter_app.auth import require_underwriter
from iins_underwriter_app.db import get_db
from iins_underwriter_app.models import UnderwritingCase, User
from iins_underwriter_app.services import risk_service as risk
from iins_underwriter_app.services.case_helpers import case_enrich

router = APIRouter(prefix="/api", tags=["cases"])

VALID_STATUS = {"new", "in_review", "referred", "approved", "declined"}
VALID_DECISIONS = {"approve", "refer", "decline"}
STATUS_MAP = {
    "approve": "approved",
    "refer": "referred",
    "decline": "declined",
}


class DecisionIn(BaseModel):
    decision: str = Field(description="approve | refer | decline")
    notes: Optional[str] = ""
    status: Optional[str] = None  # optional explicit status


@router.get("/cases")
def list_cases(
    status: Optional[str] = Query(None),
    line: Optional[str] = Query(None),
    q: Optional[str] = Query(None, description="Search policy / insured / title"),
    renewals_only: bool = Query(False, description="Open renewal-ish cases only"),
    db: Session = Depends(get_db),
    user: User = Depends(require_underwriter),
) -> Dict[str, Any]:
    query = db.query(UnderwritingCase)
    if status:
        query = query.filter(UnderwritingCase.decision_status == status.strip().lower())
    if line:
        query = query.filter(UnderwritingCase.line == line.strip().lower())
    if renewals_only:
        query = query.filter(UnderwritingCase.decision_status.in_(["new", "in_review", "referred"]))

    rows = query.order_by(UnderwritingCase.risk_score.desc(), UnderwritingCase.id.asc()).all()
    items = [case_enrich(c) for c in rows]

    if q:
        needle = q.strip().lower()
        items = [
            e
            for e in items
            if needle in (e.get("policy_number") or "").lower()
            or needle in (e.get("insured_name") or "").lower()
            or needle in (e.get("title") or "").lower()
            or needle in (e.get("external_id") or "").lower()
        ]

    counts: Dict[str, int] = {}
    line_counts: Dict[str, int] = {}
    for c in db.query(UnderwritingCase).all():
        counts[c.decision_status] = counts.get(c.decision_status, 0) + 1
        line_counts[c.line] = line_counts.get(c.line, 0) + 1

    return {
        "items": items,
        "total": len(items),
        "status_counts": counts,
        "line_counts": line_counts,
        "user": user.username,
    }


@router.get("/cases/{case_id}")
def get_case(
    case_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_underwriter),
) -> Dict[str, Any]:
    c = db.get(UnderwritingCase, case_id)
    if not c:
        raise HTTPException(status_code=404, detail="Кейс не найден")
    return case_enrich(c, detail=True)


@router.patch("/cases/{case_id}/decision")
def patch_decision(
    case_id: int,
    body: DecisionIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_underwriter),
) -> Dict[str, Any]:
    c = db.get(UnderwritingCase, case_id)
    if not c:
        raise HTTPException(status_code=404, detail="Кейс не найден")

    decision = (body.decision or "").strip().lower()
    if decision not in VALID_DECISIONS:
        raise HTTPException(status_code=400, detail="decision: approve | refer | decline")

    if body.status:
        st = body.status.strip().lower()
        if st not in VALID_STATUS:
            raise HTTPException(status_code=400, detail=f"status: {', '.join(sorted(VALID_STATUS))}")
        c.decision_status = st
    else:
        c.decision_status = STATUS_MAP[decision]

    c.recommendation = decision
    c.decision_by = user.username
    c.decided_at = datetime.now(timezone.utc)
    if body.notes is not None:
        c.notes = body.notes.strip()
    db.commit()
    db.refresh(c)
    return case_enrich(c, detail=True)


@router.get("/risk/status")
def risk_status(user: User = Depends(require_underwriter)) -> Dict[str, Any]:
    return risk.status()
