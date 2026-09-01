from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from iins_legal_app.auth import require_lawyer
from iins_legal_app.db import get_db
from iins_legal_app.models import LegalCase, User
from iins_legal_app.services.case_helpers import case_enrich

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary")
def dashboard_summary(
    db: Session = Depends(get_db),
    user: User = Depends(require_lawyer),
) -> Dict[str, Any]:
    rows: List[LegalCase] = db.query(LegalCase).all()
    enriched = [case_enrich(c) for c in rows]

    status_counts: Dict[str, int] = {}
    line_counts: Dict[str, int] = {}
    line_amount: Dict[str, float] = {}
    pending_amount = 0.0
    accepted_amount = 0.0
    declined_amount = 0.0
    high_priority = 0
    declined_n = 0
    urgent = 0
    upcoming_hearings = 0

    for c, e in zip(rows, enriched):
        st = c.decision_status
        status_counts[st] = status_counts.get(st, 0) + 1
        line_counts[c.line] = line_counts.get(c.line, 0) + 1
        amt = float(e["amount"])
        line_amount[c.line] = line_amount.get(c.line, 0.0) + amt

        if st in {"new", "in_review", "escalated"}:
            pending_amount += amt
        elif st == "accepted":
            accepted_amount += amt
        elif st == "declined":
            declined_amount += amt
            declined_n += 1

        if float(c.risk_score or 0) >= 70:
            high_priority += 1

        if c.urgency_signal or (st in {"new", "in_review"} and float(c.risk_score or 0) >= 60):
            urgent += 1

        if st in {"new", "in_review", "escalated"} and e.get("hearing_date"):
            from datetime import date

            try:
                hd = date.fromisoformat(e["hearing_date"])
                delta = (hd - date.today()).days
                if 0 <= delta <= 14:
                    upcoming_hearings += 1
            except ValueError:
                pass

    open_queue = status_counts.get("new", 0) + status_counts.get("in_review", 0)
    open_opportunities = status_counts.get("new", 0) + status_counts.get("escalated", 0)
    decided = status_counts.get("accepted", 0) + status_counts.get("declined", 0)
    accept_rate = round(100.0 * status_counts.get("accepted", 0) / decided, 1) if decided else 0.0

    submissions = sorted(
        [e for e in enriched if e["decision_status"] in {"new", "in_review", "escalated"}],
        key=lambda x: x["days_open"],
        reverse=True,
    )[:12]

    workstream = [
        {
            "line": line,
            "count": line_counts.get(line, 0),
            "premium": round(line_amount.get(line, 0.0), 2),
            "amount": round(line_amount.get(line, 0.0), 2),
        }
        for line in ("pi", "imr")
    ]

    return {
        "action_items": {
            "up_for_renewal": open_queue,
            "open_queue": open_queue,
            "about_to_lapse": upcoming_hearings,
            "upcoming_hearings": upcoming_hearings,
            "open_opportunities": open_opportunities,
            "payment_due": urgent,
            "urgent": urgent,
        },
        "book_of_business": {
            "premium_pending": round(pending_amount, 2),
            "premium_retained": round(accepted_amount, 2),
            "premium_declined": round(declined_amount, 2),
            "amount_pending": round(pending_amount, 2),
            "amount_accepted": round(accepted_amount, 2),
            "amount_declined": round(declined_amount, 2),
            "renewal_rate": accept_rate,
            "accept_rate": accept_rate,
            "total_cases": len(rows),
        },
        "status_counts": status_counts,
        "line_counts": line_counts,
        "widgets": {
            "pending_vs_retained": {
                "pending": round(pending_amount, 2),
                "retained": round(accepted_amount, 2),
            },
            "policy_by_status": status_counts,
            "high_risk_count": high_priority,
            "decline_do_not_renew": declined_n,
            "new_submissions": [
                {
                    "id": s["id"],
                    "policy_number": s["case_number"],
                    "case_number": s["case_number"],
                    "insured_name": s["party_name"],
                    "party_name": s["party_name"],
                    "line": s["line"],
                    "days_open": s["days_open"],
                    "premium": s["amount"],
                    "amount": s["amount"],
                    "risk_score": s["risk_score"],
                    "status": s["decision_status"],
                    "recommendation": s["recommendation"],
                }
                for s in submissions
            ],
            "workstream": workstream,
        },
        "user": user.username,
    }
