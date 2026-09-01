from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from iins_underwriter_app.auth import require_underwriter
from iins_underwriter_app.db import get_db
from iins_underwriter_app.models import UnderwritingCase, User
from iins_underwriter_app.services.case_helpers import case_enrich

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary")
def dashboard_summary(
    db: Session = Depends(get_db),
    user: User = Depends(require_underwriter),
) -> Dict[str, Any]:
    rows: List[UnderwritingCase] = db.query(UnderwritingCase).all()
    enriched = [case_enrich(c) for c in rows]

    status_counts: Dict[str, int] = {}
    line_counts: Dict[str, int] = {}
    line_premium: Dict[str, float] = {}
    pending_premium = 0.0
    retained_premium = 0.0
    declined_premium = 0.0
    high_risk = 0
    decline_dnr = 0
    payment_due = 0
    about_to_lapse = 0

    for c, e in zip(rows, enriched):
        st = c.decision_status
        status_counts[st] = status_counts.get(st, 0) + 1
        line_counts[c.line] = line_counts.get(c.line, 0) + 1
        prem = float(e["premium"])
        line_premium[c.line] = line_premium.get(c.line, 0.0) + prem

        if st in {"new", "in_review", "referred"}:
            pending_premium += prem
        elif st == "approved":
            retained_premium += prem
        elif st == "declined":
            declined_premium += prem
            decline_dnr += 1

        if float(c.risk_score or 0) >= 70:
            high_risk += 1

        if c.fraud_signal or (st in {"new", "in_review"} and float(c.risk_score or 0) >= 60):
            payment_due += 1

        # About to lapse: open + renewal within ~14 days (synthetic renewal_date)
        if st in {"new", "in_review", "referred"} and e.get("renewal_date"):
            from datetime import date

            try:
                rd = date.fromisoformat(e["renewal_date"])
                delta = (rd - date.today()).days
                if 0 <= delta <= 14:
                    about_to_lapse += 1
            except ValueError:
                pass

    up_for_renewal = status_counts.get("new", 0) + status_counts.get("in_review", 0)
    open_opportunities = status_counts.get("new", 0) + status_counts.get("referred", 0)
    decided = status_counts.get("approved", 0) + status_counts.get("declined", 0)
    renewal_rate = round(100.0 * status_counts.get("approved", 0) / decided, 1) if decided else 0.0

    # New submissions age table (open cases sorted by days_open desc)
    submissions = sorted(
        [e for e in enriched if e["decision_status"] in {"new", "in_review", "referred"}],
        key=lambda x: x["days_open"],
        reverse=True,
    )[:12]

    workstream = [
        {
            "line": line,
            "count": line_counts.get(line, 0),
            "premium": round(line_premium.get(line, 0.0), 2),
        }
        for line in ("auto", "fraud", "motor")
    ]

    return {
        "action_items": {
            "up_for_renewal": up_for_renewal,
            "about_to_lapse": about_to_lapse,
            "open_opportunities": open_opportunities,
            "payment_due": payment_due,
        },
        "book_of_business": {
            "premium_pending": round(pending_premium, 2),
            "premium_retained": round(retained_premium, 2),
            "premium_declined": round(declined_premium, 2),
            "renewal_rate": renewal_rate,
            "total_cases": len(rows),
        },
        "status_counts": status_counts,
        "line_counts": line_counts,
        "widgets": {
            "pending_vs_retained": {
                "pending": round(pending_premium, 2),
                "retained": round(retained_premium, 2),
            },
            "policy_by_status": status_counts,
            "high_risk_count": high_risk,
            "decline_do_not_renew": decline_dnr,
            "new_submissions": [
                {
                    "id": s["id"],
                    "policy_number": s["policy_number"],
                    "insured_name": s["insured_name"],
                    "line": s["line"],
                    "days_open": s["days_open"],
                    "premium": s["premium"],
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
