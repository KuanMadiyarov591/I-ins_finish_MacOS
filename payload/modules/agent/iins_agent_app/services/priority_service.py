"""Приоритет клиента 1..5: правила CRM + ML propensity как сигнал."""

from __future__ import annotations

from typing import Any, Dict, Optional

from iins_agent_app.services import lead_scoring_service as scoring

PRIORITY_SHORT = {
    1: "Приоритет 1",
    2: "Приоритет 2",
    3: "Приоритет 3",
    4: "Приоритет 4",
    5: "Приоритет 5",
}

PRIORITY_LABELS = {
    1: "Приоритет 1 — срочно (изменение покрытия / активная заявка)",
    2: "Приоритет 2 — высокий (горячий propensity / котировка)",
    3: "Приоритет 3 — средний (тёплый / follow-up)",
    4: "Приоритет 4 — прогрев",
    5: "Приоритет 5 — низкий",
}

PRIORITY_SHORT_I18N = {
    "ru": PRIORITY_SHORT,
    "kk": {
        1: "Басымдық 1",
        2: "Басымдық 2",
        3: "Басымдық 3",
        4: "Басымдық 4",
        5: "Басымдық 5",
    },
    "en": {
        1: "Priority 1",
        2: "Priority 2",
        3: "Priority 3",
        4: "Priority 4",
        5: "Priority 5",
    },
}


def compute_priority(
    *,
    coverage_change: bool = False,
    has_open_application: bool = False,
    buy_probability: Optional[float] = None,
    propensity_tier: Optional[str] = None,
) -> int:
    tier = propensity_tier
    if buy_probability is not None and not tier:
        tier = scoring.tier_for(float(buy_probability))

    if coverage_change or has_open_application:
        return 1
    if tier == "Hot" or (buy_probability is not None and buy_probability >= 0.60):
        return 2
    if tier == "Warm" or (buy_probability is not None and buy_probability >= 0.42):
        return 3
    if tier == "Nurture" or (buy_probability is not None and buy_probability >= 0.25):
        return 4
    return 5


def enrich_client_ml(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Вторичный ML-сигнал: вероятность покупки travel (не главный UX)."""
    if not scoring.status()["ready"]:
        return {"buy_probability": None, "propensity_tier": None}
    try:
        out = scoring.score_profile(profile)
        return {
            "buy_probability": out.get("buy_probability"),
            "propensity_tier": out.get("tier"),
            "will_buy_label": out.get("will_buy_label"),
            "reason_1": out.get("reason_1"),
        }
    except Exception:  # noqa: BLE001
        return {"buy_probability": None, "propensity_tier": None}
