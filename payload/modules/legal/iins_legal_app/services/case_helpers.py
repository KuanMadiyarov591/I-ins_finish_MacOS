"""Helpers to enrich legal cases for UI."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from iins_legal_app.models import LegalCase

STAGE_MAP = {
    "new": "intake",
    "in_review": "review",
    "escalated": "escalate",
    "accepted": "accepted",
    "declined": "closed",
}

STAGE_LABEL_RU = {
    "intake": "Поступление",
    "review": "В работе",
    "escalate": "Эскалация",
    "accepted": "Принято",
    "closed": "Отказ",
}

STAGE_ORDER = ["intake", "review", "escalate", "accepted", "closed"]

MOCK_DOCS = {
    "pi": [
        {"name": "Жалоба / исковое заявление.pdf", "type": "complaint", "synced": True},
        {"name": "Медзаключение.pdf", "type": "medical", "synced": True},
        {"name": "Отчёт эксперта.docx", "type": "expert", "synced": False},
        {"name": "Переписка со страховой.pdf", "type": "correspondence", "synced": True},
    ],
    "imr": [
        {"name": "Апелляция IMR.pdf", "type": "appeal", "synced": True},
        {"name": "Отказ страховщика.pdf", "type": "denial", "synced": True},
        {"name": "Клиническая выписка.pdf", "type": "clinical", "synced": True},
        {"name": "Протокол IMR.docx", "type": "protocol", "synced": False},
    ],
}


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


def extract_party_name(c: LegalCase) -> str:
    title = c.title or ""
    summary = c.applicant_summary or ""
    if " · " in title:
        return title.split(" · ", 1)[1].strip()
    m = re.search(r"Клиент:\s*([^·]+)", summary)
    if m:
        return m.group(1).strip()
    for prefix in ("PI · ", "IMR · ", "Телесный вред · ", "Апелляция IMR · "):
        if title.startswith(prefix):
            return title[len(prefix) :].strip() or title
    return title or c.external_id


def extract_amount(c: LegalCase, features: Optional[Dict[str, Any]] = None) -> float:
    feats = features if features is not None else parse_json_obj(c.raw_features)
    for key in ("amount", "claim_amount", "estimated_amount"):
        if key in feats:
            val = _safe_float(feats.get(key), 0.0)
            if val > 0:
                return round(val, 2)
    log_a = _safe_float(feats.get("log_amount"), 0.0)
    if log_a > 0:
        import math

        return round(math.exp(log_a), 2)
    base = {"pi": 250_000.0, "imr": 45_000.0}.get(c.line, 100_000.0)
    return round(base + float(c.risk_score or 0) * 1200 + (c.id or 0) % 17 * 900, 2)


def days_open(c: LegalCase, now: Optional[datetime] = None) -> int:
    now = now or datetime.now(timezone.utc)
    created = c.created_at
    if not created:
        return 0
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    delta = now - created
    synthetic = (c.id or 0) % 21
    return max(0, int(delta.total_seconds() // 86400) + synthetic)


def hearing_date_iso(c: LegalCase) -> Optional[str]:
    created = c.created_at or datetime.now(timezone.utc)
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    offset_days = 10 + ((c.id or 0) % 40)
    if c.decision_status in {"accepted", "declined"}:
        offset_days = -5 - ((c.id or 0) % 15)
    return (created + timedelta(days=offset_days)).date().isoformat()


def mock_documents(c: LegalCase) -> List[Dict[str, Any]]:
    docs = list(MOCK_DOCS.get(c.line, MOCK_DOCS["pi"]))
    # Slight variation by case id
    out = []
    for i, d in enumerate(docs):
        item = dict(d)
        item["id"] = f"doc-{c.id}-{i}"
        item["synced"] = bool(d["synced"]) if (c.id or 0) % 5 != i else not d["synced"]
        out.append(item)
    return out


def case_enrich(c: LegalCase, detail: bool = False) -> Dict[str, Any]:
    features = parse_json_obj(c.raw_features)
    amount = extract_amount(c, features)
    stage = STAGE_MAP.get(c.decision_status, "intake")
    out: Dict[str, Any] = {
        "id": c.id,
        "external_id": c.external_id,
        "case_number": c.external_id,
        "policy_number": c.external_id,  # UW-compat for shared UI patterns
        "insured_name": extract_party_name(c),
        "party_name": extract_party_name(c),
        "line": c.line,
        "title": c.title,
        "applicant_summary": c.applicant_summary,
        "amount": amount,
        "premium": amount,  # UW-compat for dashboard widgets
        "risk_score": c.risk_score,
        "recommendation": c.recommendation,
        "decision_status": c.decision_status,
        "stage": stage,
        "stage_label": STAGE_LABEL_RU.get(stage, stage),
        "urgency_signal": c.urgency_signal,
        "fraud_signal": c.urgency_signal,  # UW-compat
        "key_factors": parse_json_list(c.key_factors),
        "notes": c.notes,
        "decision_by": c.decision_by,
        "days_open": days_open(c),
        "hearing_date": hearing_date_iso(c),
        "renewal_date": hearing_date_iso(c),
        "sharepoint_synced": True,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        "decided_at": c.decided_at.isoformat() if c.decided_at else None,
    }
    if detail:
        out["raw_features"] = features
        out["documents"] = mock_documents(c)
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
