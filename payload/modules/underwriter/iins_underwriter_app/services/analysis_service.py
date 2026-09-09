"""Данные для вкладки «Анализ» в кабинете андеррайтера.

Здесь важно не готовое число, а возможность подвигать порог и сразу
увидеть цену решения: сколько дел уходит на ручной разбор, сколько
премии остаётся в портфеле и какая доля сигналов мошенничества
попадает под отказ. Поэтому сервер отдаёт разобранные дела одним
пакетом, а пересчёт при движении ползунка идёт на странице.
"""

from __future__ import annotations

import math
import statistics
from typing import Any, Dict, List, Sequence

from sqlalchemy.orm import Session

from iins_underwriter_app.models import UnderwritingCase
from iins_underwriter_app.services.case_helpers import (
    STAGE_LABEL_RU,
    case_enrich,
)

LINE_LABEL = {
    "auto": "Авто",
    "fraud": "Мошенничество",
    "motor": "Мотор",
}

STATUS_LABEL = {
    "new": "Новые",
    "in_review": "В работе",
    "referred": "На эскалации",
    "approved": "Одобрены",
    "declined": "Отклонены",
}


def _summary(values: Sequence[float]) -> Dict[str, Any]:
    clean = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    n = len(clean)
    if n < 2:
        return {"n": n}
    ordered = sorted(clean)
    return {
        "n": n,
        "mean": round(statistics.fmean(clean), 2),
        "sd": round(statistics.pstdev(clean), 2),
        "min": round(ordered[0], 2),
        "median": round(ordered[n // 2], 2),
        "max": round(ordered[-1], 2),
    }


def _factor_stats(cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    acc: Dict[str, Dict[str, float]] = {}
    for c in cases:
        for raw in c.get("factors") or []:
            name = str(raw).strip()
            if not name:
                continue
            # Формулировки причин длинные: для сводки берём начало фразы.
            key = name.split(":")[0].split("(")[0].strip()[:48] or name[:48]
            a = acc.setdefault(key, {"n": 0.0, "risk": 0.0, "premium": 0.0, "fraud": 0.0})
            a["n"] += 1
            a["risk"] += float(c["risk"] or 0.0)
            a["premium"] += float(c["premium"] or 0.0)
            a["fraud"] += 1.0 if c["fraud"] else 0.0
    out = []
    for key, a in acc.items():
        n = a["n"] or 1.0
        out.append({
            "label": key,
            "n": int(a["n"]),
            "avg_risk": round(a["risk"] / n, 1),
            "avg_premium": round(a["premium"] / n, 2),
            "fraud_share": round(a["fraud"] / n, 4),
        })
    out.sort(key=lambda x: x["n"], reverse=True)
    return out[:18]


def _group(cases: List[Dict[str, Any]], key: str, labels: Dict[str, str]) -> List[Dict[str, Any]]:
    acc: Dict[str, Dict[str, float]] = {}
    for c in cases:
        k = str(c.get(key) or "—")
        a = acc.setdefault(k, {"n": 0.0, "premium": 0.0, "risk": 0.0, "fraud": 0.0})
        a["n"] += 1
        a["premium"] += float(c["premium"] or 0.0)
        a["risk"] += float(c["risk"] or 0.0)
        a["fraud"] += 1.0 if c["fraud"] else 0.0
    out = []
    for k, a in acc.items():
        n = a["n"] or 1.0
        out.append({
            "key": k,
            "label": labels.get(k, k),
            "n": int(a["n"]),
            "premium": round(a["premium"], 2),
            "avg_risk": round(a["risk"] / n, 1),
            "fraud": int(a["fraud"]),
        })
    out.sort(key=lambda x: x["n"], reverse=True)
    return out


def package(db: Session) -> Dict[str, Any]:
    rows: List[UnderwritingCase] = db.query(UnderwritingCase).all()
    cases: List[Dict[str, Any]] = []
    for c in rows:
        e = case_enrich(c)
        cases.append({
            "id": e["id"],
            "policy": e["policy_number"],
            "insured": e["insured_name"],
            "line": e["line"],
            "line_label": LINE_LABEL.get(e["line"], e["line"]),
            "status": e["decision_status"],
            "status_label": STATUS_LABEL.get(e["decision_status"], e["decision_status"]),
            "stage_label": STAGE_LABEL_RU.get(e["stage"], e["stage"]),
            "risk": round(float(e["risk_score"] or 0.0), 1),
            "premium": float(e["premium"] or 0.0),
            "fraud": bool(e["fraud_signal"]),
            "days_open": int(e["days_open"] or 0),
            "recommendation": e["recommendation"],
            "factors": e["key_factors"],
        })

    risks = [c["risk"] for c in cases]
    premiums = [c["premium"] for c in cases]
    fraud_n = sum(1 for c in cases if c["fraud"])

    return {
        "cases": cases,
        "totals": {
            "n": len(cases),
            "premium": round(sum(premiums), 2),
            "fraud": fraud_n,
            "fraud_share": round(fraud_n / len(cases), 4) if cases else 0.0,
            "open": sum(1 for c in cases if c["status"] in {"new", "in_review", "referred"}),
        },
        "risk_summary": _summary(risks),
        "premium_summary": _summary(premiums),
        "by_line": _group(cases, "line", LINE_LABEL),
        "by_status": _group(cases, "status", STATUS_LABEL),
        "factors": _factor_stats(cases),
    }
