"""Helpers to enrich underwriting cases for Kiwi/Fortimize-style UI (no schema migration)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from iins_underwriter_app.models import UnderwritingCase

STAGE_MAP = {
    "new": "not_analyzed",
    "in_review": "in_analysis",
    "referred": "refer_escalate",
    "approved": "approved",
    "declined": "declined_closed",
}

STAGE_LABEL_RU = {
    "not_analyzed": "Не разобран",
    "in_analysis": "В анализе",
    "refer_escalate": "На эскалации",
    "approved": "Одобрено",
    "declined_closed": "Отклонено",
}

STAGE_ORDER = [
    "not_analyzed",
    "in_analysis",
    "refer_escalate",
    "approved",
    "declined_closed",
]


def parse_json_list(raw: str) -> List[str]:
    try:
        data = json.loads(raw or "[]")
        if isinstance(data, list):
            return [str(x) for x in data]
    except Exception:  # noqa: BLE001
        pass
    return [raw] if raw else []


def parse_json_obj(raw: str) -> Dict[str, Any]:
    try:
        data = json.loads(raw or "{}")
        if isinstance(data, dict):
            return data
    except Exception:  # noqa: BLE001
        pass
    return {}


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def extract_insured_name(c: UnderwritingCase) -> str:
    title = c.title or ""
    summary = c.applicant_summary or ""
    if c.line != "motor" and " · " in title:
        return title.split(" · ", 1)[1].strip()
    m = re.search(r"Заявитель:\s*([^·]+)", summary)
    if m:
        return m.group(1).strip()
    # Fallback: strip line prefixes
    for prefix in (
        "Авто · ",
        "Fraud review · ",
        "Мотор · ",
        "Ком. мотор · ",
        "Парк ТС · ",
        "Личное авто · ",
        "Мошенничество · ",
    ):
        if title.startswith(prefix):
            return title[len(prefix):].strip() or title
    return title or c.external_id


def extract_premium(c: UnderwritingCase, features: Optional[Dict[str, Any]] = None) -> float:
    feats = features if features is not None else parse_json_obj(c.raw_features)
    for key in (
        "policy_annual_premium",
        "PREMIUM",
        "premium",
        "annual_premium",
        "POLICY_ANNUAL_PREMIUM",
    ):
        if key in feats:
            val = _safe_float(feats.get(key), 0.0)
            if val > 0:
                return round(val, 2)
    # Synthetic book premium for auto rows without premium column
    base = {"auto": 920.0, "fraud": 1250.0, "motor": 3400.0}.get(c.line, 1000.0)
    return round(base + float(c.risk_score or 0) * 11.5 + (c.id or 0) % 17 * 7, 2)


def days_open(c: UnderwritingCase, now: Optional[datetime] = None) -> int:
    now = now or datetime.now(timezone.utc)
    created = c.created_at
    if not created:
        return 0
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    delta = now - created
    # Demo: spread ages using id so dashboard table looks realistic
    synthetic = (c.id or 0) % 21
    return max(0, int(delta.total_seconds() // 86400) + synthetic)


def renewal_date_iso(c: UnderwritingCase) -> Optional[str]:
    """Synthetic renewal horizon for demo Fortimize renewals table."""
    created = c.created_at or datetime.now(timezone.utc)
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    # Open cases nearer; closed further / past
    offset_days = 7 + ((c.id or 0) % 45)
    if c.decision_status in {"approved", "declined"}:
        offset_days = -3 - ((c.id or 0) % 20)
    from datetime import timedelta

    return (created + timedelta(days=offset_days)).date().isoformat()


def case_enrich(c: UnderwritingCase, detail: bool = False) -> Dict[str, Any]:
    features = parse_json_obj(c.raw_features)
    premium = extract_premium(c, features)
    stage = STAGE_MAP.get(c.decision_status, "not_analyzed")
    out: Dict[str, Any] = {
        "id": c.id,
        "external_id": c.external_id,
        "policy_number": c.external_id,
        "insured_name": extract_insured_name(c),
        "line": c.line,
        "title": c.title,
        "applicant_summary": c.applicant_summary,
        "premium": premium,
        "risk_score": c.risk_score,
        "recommendation": c.recommendation,
        "decision_status": c.decision_status,
        "stage": stage,
        "stage_label": STAGE_LABEL_RU.get(stage, stage),
        "fraud_signal": c.fraud_signal,
        "key_factors": parse_json_list(c.key_factors),
        "notes": c.notes,
        "decision_by": c.decision_by,
        "days_open": days_open(c),
        "renewal_date": renewal_date_iso(c),
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        "decided_at": c.decided_at.isoformat() if c.decided_at else None,
    }
    if detail:
        out["raw_features"] = features
        out["stages"] = [
            {
                "id": s,
                "label": STAGE_LABEL_RU[s],
                "active": s == stage,
                "done": STAGE_ORDER.index(s) <= STAGE_ORDER.index(stage)
                if stage in STAGE_ORDER and s in STAGE_ORDER
                else False,
            }
            for s in STAGE_ORDER
        ]
    return out
