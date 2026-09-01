from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from iins_legal_app.auth import require_lawyer
from iins_legal_app.db import get_db
from iins_legal_app.models import LegalCase, User
from iins_legal_app.services import case_eval as evalsvc
from iins_legal_app.services.case_helpers import case_enrich

router = APIRouter(prefix="/api", tags=["cases"])

VALID_STATUS = {"new", "in_review", "escalated", "accepted", "declined"}
# accept/escalate/decline (+ UW aliases approve/refer)
VALID_DECISIONS = {"accept", "escalate", "decline", "approve", "refer"}
DECISION_NORMALIZE = {
    "approve": "accept",
    "refer": "escalate",
    "accept": "accept",
    "escalate": "escalate",
    "decline": "decline",
}
STATUS_MAP = {
    "accept": "accepted",
    "escalate": "escalated",
    "decline": "declined",
}


class DecisionIn(BaseModel):
    decision: str = Field(description="accept | escalate | decline")
    notes: Optional[str] = ""
    status: Optional[str] = None


@router.get("/cases")
def list_cases(
    status: Optional[str] = Query(None),
    line: Optional[str] = Query(None),
    q: Optional[str] = Query(None, description="Search case / party / title"),
    open_only: bool = Query(False, description="Open requests only"),
    renewals_only: bool = Query(False, description="Alias for open_only (UW compat)"),
    db: Session = Depends(get_db),
    user: User = Depends(require_lawyer),
) -> Dict[str, Any]:
    query = db.query(LegalCase)
    if status:
        query = query.filter(LegalCase.decision_status == status.strip().lower())
    if line:
        query = query.filter(LegalCase.line == line.strip().lower())
    if open_only or renewals_only:
        query = query.filter(LegalCase.decision_status.in_(["new", "in_review", "escalated"]))

    rows = query.order_by(LegalCase.risk_score.desc(), LegalCase.id.asc()).all()
    items = [case_enrich(c) for c in rows]

    if q:
        needle = q.strip().lower()
        items = [
            e
            for e in items
            if needle in (e.get("case_number") or "").lower()
            or needle in (e.get("party_name") or "").lower()
            or needle in (e.get("title") or "").lower()
            or needle in (e.get("external_id") or "").lower()
        ]

    counts: Dict[str, int] = {}
    line_counts: Dict[str, int] = {}
    for c in db.query(LegalCase).all():
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
    user: User = Depends(require_lawyer),
) -> Dict[str, Any]:
    c = db.get(LegalCase, case_id)
    if not c:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    return case_enrich(c, detail=True)


@router.patch("/cases/{case_id}/decision")
def patch_decision(
    case_id: int,
    body: DecisionIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_lawyer),
) -> Dict[str, Any]:
    c = db.get(LegalCase, case_id)
    if not c:
        raise HTTPException(status_code=404, detail="Дело не найдено")

    raw = (body.decision or "").strip().lower()
    if raw not in VALID_DECISIONS:
        raise HTTPException(status_code=400, detail="decision: accept | escalate | decline")
    decision = DECISION_NORMALIZE[raw]

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
def risk_status(user: User = Depends(require_lawyer)) -> Dict[str, Any]:
    return evalsvc.status()
