"""Рекомендации продуктов для агента: propensity + профиль клиента (без UW/fraud)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from iins_agent_app.models import Client, PolicyProduct
from iins_agent_app.services import lead_scoring_service as scoring
from iins_agent_app.services.priority_service import PRIORITY_LABELS, PRIORITY_SHORT

CATEGORY_RU = {
    "medical": "Медицина",
    "life": "Жизнь",
    "auto": "Авто",
    "travel": "Туризм",
    "home": "Имущество",
    "funeral": "Похоронное",
}

CATEGORY_KK = {
    "medical": "Медицина",
    "life": "Өмір",
    "auto": "Авто",
    "travel": "Саяхат",
    "home": "Мүлік",
    "funeral": "Жерлеу",
}

CATEGORY_EN = {
    "medical": "Medical",
    "life": "Life",
    "auto": "Auto",
    "travel": "Travel",
    "home": "Home",
    "funeral": "Funeral",
}


def _cat_label(cat: str, lang: str) -> str:
    pack = {"ru": CATEGORY_RU, "kk": CATEGORY_KK, "en": CATEGORY_EN}.get(lang, CATEGORY_RU)
    return pack.get(cat, cat)


def _ml_signal(client: Client) -> Dict[str, Any]:
    if client.buy_probability is not None:
        return {
            "buy_probability": float(client.buy_probability),
            "propensity_tier": client.propensity_tier,
            "reason_1": None,
            "ready": True,
        }
    profile = {
        "Age": client.age,
        "AnnualIncome": client.annual_income,
        "FamilyMembers": client.family_members,
        "ChronicDiseases": client.chronic_diseases,
        "Employment Type": client.employment_type,
        "GraduateOrNot": client.graduate,
        "FrequentFlyer": client.frequent_flyer,
        "EverTravelledAbroad": client.ever_travelled_abroad,
    }
    if not scoring.status()["ready"]:
        return {"buy_probability": None, "propensity_tier": None, "reason_1": None, "ready": False}
    try:
        out = scoring.score_profile(profile)
        return {
            "buy_probability": out.get("buy_probability"),
            "propensity_tier": out.get("tier"),
            "reason_1": out.get("reason_1"),
            "ready": True,
            "will_buy_label": out.get("will_buy_label"),
            "action": out.get("action") or scoring.tier_action(out.get("tier") or ""),
        }
    except Exception:  # noqa: BLE001
        return {"buy_probability": None, "propensity_tier": None, "reason_1": None, "ready": False}


def _category_affinity(client: Client, travel_p: Optional[float]) -> Dict[str, float]:
    """Скоринг категорий только по сигналам продаж (не claim/fraud)."""
    age = int(client.age or 35)
    income = float(client.annual_income or 0)
    family = int(client.family_members or 1)
    chronic = int(client.chronic_diseases or 0)
    flyer = (client.frequent_flyer or "").lower() == "yes"
    abroad = (client.ever_travelled_abroad or "").lower() == "yes"
    tp = float(travel_p) if travel_p is not None else (0.55 if flyer or abroad else 0.25)

    return {
        "travel": min(0.98, 0.25 + 0.55 * tp + (0.12 if flyer else 0) + (0.08 if abroad else 0)),
        "medical": min(0.95, 0.28 + 0.18 * chronic + (0.12 if age >= 45 else 0) + (0.08 if family >= 3 else 0)),
        "life": min(0.95, 0.22 + (0.25 if income >= 700_000 else 0.08) + (0.12 if family >= 3 else 0)),
        "home": min(0.92, 0.20 + (0.35 if client.coverage_change else 0) + (0.12 if income >= 500_000 else 0)),
        "auto": min(0.90, 0.24 + (0.15 if income >= 400_000 else 0) + (0.08 if age <= 55 else 0)),
        "funeral": min(0.90, 0.12 + (0.45 if age >= 55 else 0) + (0.12 if age >= 65 else 0)),
    }


def _reasons(
    cat: str,
    client: Client,
    travel_p: Optional[float],
    lang: str,
) -> List[str]:
    ru = lang == "ru"
    kk = lang == "kk"
    reasons: List[str] = []
    if cat == "travel":
        if travel_p is not None:
            pct = f"{travel_p * 100:.0f}%"
            if ru:
                reasons.append(f"Склонность к туристической страховке {pct}")
            elif kk:
                reasons.append(f"Туристік сақтандыруға бейімділік {pct}")
            else:
                reasons.append(f"Travel insurance propensity {pct}")
        if (client.frequent_flyer or "").lower() == "yes":
            reasons.append("Частый авиапассажир" if ru else ("Жиі ұшады" if kk else "Frequent flyer"))
        if (client.ever_travelled_abroad or "").lower() == "yes":
            reasons.append(
                "Опыт зарубежных поездок" if ru else ("Шетел тәжірибесі" if kk else "Travelled abroad")
            )
    elif cat == "medical":
        if int(client.chronic_diseases or 0):
            reasons.append("Есть хронические заболевания" if ru else ("Созылмалы ауру бар" if kk else "Chronic conditions"))
        if int(client.age or 0) >= 45:
            reasons.append("Возраст в зоне мед. риска" if ru else ("Жасы мед. тәуекелде" if kk else "Age in medical risk band"))
    elif cat == "life":
        if float(client.annual_income or 0) >= 700_000:
            reasons.append("Высокий доход — защита семьи" if ru else ("Жоғары табыс" if kk else "Higher income — family protection"))
        if int(client.family_members or 0) >= 3:
            reasons.append("Семья из нескольких человек" if ru else ("Отбасы үлкен" if kk else "Larger family"))
    elif cat == "home":
        if client.coverage_change:
            reasons.append("Флаг: изменение покрытия" if ru else ("Қамту өзгеруі" if kk else "Coverage change flag"))
        else:
            reasons.append("Имущественная защита по профилю" if ru else ("Мүлікті қорғау" if kk else "Home protection fit"))
    elif cat == "auto":
        reasons.append("Профиль подходит для авто-линейки" if ru else ("Авто өніміне сай" if kk else "Fit for auto line"))
    elif cat == "funeral":
        reasons.append("Возраст 55+ — похоронное покрытие" if ru else ("55+ жерлеу өнімі" if kk else "Age 55+ funeral fit"))
    if not reasons:
        reasons.append("Совпадение с каталогом агента" if ru else ("Каталогпен сәйкес" if kk else "Catalog fit"))
    return reasons


def recommend_for_client(
    client: Client,
    products: List[PolicyProduct],
    *,
    top_k: int = 5,
    lang: str = "ru",
) -> Dict[str, Any]:
    ml = _ml_signal(client)
    travel_p = ml.get("buy_probability")
    affinity = _category_affinity(client, travel_p)

    ranked: List[Dict[str, Any]] = []
    for p in products:
        if not p.is_active:
            continue
        cat = (p.category or "").lower()
        base = affinity.get(cat, 0.15)
        # лёгкий буст премии в «доступном» диапазоне для дохода
        income = float(client.annual_income or 500_000)
        prem = float(p.premium or 0)
        afford = 1.0
        if income > 0 and prem > 0:
            share = prem / income
            afford = 1.0 if share <= 0.04 else max(0.55, 1.0 - (share - 0.04) * 4)
        score = min(0.99, base * 0.85 + afford * 0.15)
        ranked.append(
            {
                "product_id": p.id,
                "code": p.code,
                "policy_name": p.name,
                "category": cat,
                "category_label": _cat_label(cat, lang),
                "premium": prem,
                "coverage_limit": float(getattr(p, "sum_assurance", None) or getattr(p, "coverage_limit", None) or 0),
                "score": round(score, 4),
                "match_pct": int(round(score * 100)),
                "reasons": _reasons(cat, client, travel_p, lang),
                "description": p.description or "",
            }
        )

    ranked.sort(key=lambda x: x["score"], reverse=True)
    top = ranked[: max(1, min(top_k, len(ranked)))]

    return {
        "client_id": client.id,
        "client_name": client.full_name,
        "priority": client.priority,
        "priority_label": PRIORITY_LABELS.get(client.priority, str(client.priority)),
        "priority_short": PRIORITY_SHORT.get(client.priority, str(client.priority)),
        "ml": {
            "model": "travel_propensity",
            "ready": bool(ml.get("ready")),
            "buy_probability": ml.get("buy_probability"),
            "propensity_tier": ml.get("propensity_tier"),
            "reason_1": ml.get("reason_1"),
            "action": ml.get("action"),
        },
        "category_scores": {k: round(v, 3) for k, v in affinity.items()},
        "recommendations": top,
    }
