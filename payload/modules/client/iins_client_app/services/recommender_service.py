"""Рекомендации полисов InsuraDesk: medical / home / travel / auto."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import joblib
import numpy as np
import pandas as pd
from sqlalchemy.orm import Session, joinedload

from iins_client_app.config import ROOT
from iins_client_app.models import Policy

MODELS_DIR = ROOT / "models" / "recommender"

MIN_REGRESSOR_R2 = 0.2
MIN_CATEGORY_PROB = 0.05
HIGH_INCOME_THRESHOLD = 80000.0
# agent dataset AnnualIncome ~3e5..1.8e6; UI часто даёт западный масштаб
PROPENSITY_INCOME_SCALE_BELOW = 200_000.0
PROPENSITY_INCOME_MULTIPLIER = 10.0
SOFT_TRAVEL_BASE_PREMIUM = 12000.0

CATEGORY_TO_LINE = {
    "Страхование жизни": "medical_premium",
    "Медицинское страхование": "medical_premium",
    "Имущественное страхование": "home_premium",
    "Туристическое страхование": "travel_premium",
    "Автострахование": "auto_premium",
}

# пусто: все клиентские линии активны (авто включён)
EXCLUDED_CATEGORIES: set[str] = set()

CATEGORY_I18N = {
    "Страхование жизни": {
        "ru": "Страхование жизни",
        "kk": "Өмірді сақтандыру",
        "en": "Life insurance",
    },
    "Медицинское страхование": {
        "ru": "Медицинское страхование",
        "kk": "Медициналық сақтандыру",
        "en": "Medical insurance",
    },
    "Имущественное страхование": {
        "ru": "Имущественное страхование",
        "kk": "Мүліктік сақтандыру",
        "en": "Property insurance",
    },
    "Туристическое страхование": {
        "ru": "Туристическое страхование",
        "kk": "Туристік сақтандыру",
        "en": "Travel insurance",
    },
    "Автострахование": {
        "ru": "Автострахование",
        "kk": "Автосақтандыру",
        "en": "Auto insurance",
    },
}

LINE_I18N = {
    "medical_premium": {"ru": "мед.", "kk": "мед.", "en": "medical"},
    "home_premium": {"ru": "имущество", "kk": "мүлік", "en": "home"},
    "travel_premium": {"ru": "туризм", "kk": "туризм", "en": "travel"},
    "auto_premium": {"ru": "авто", "kk": "авто", "en": "auto"},
    "catalog": {"ru": "каталог", "kk": "каталог", "en": "catalog"},
}


def _lang(code: Optional[str]) -> str:
    c = (code or "ru").lower().strip()
    return c if c in ("ru", "kk", "en") else "ru"


def translate_category(name: str, lang: str) -> str:
    pack = CATEGORY_I18N.get(name)
    if not pack:
        return name
    return pack.get(_lang(lang), pack["ru"])


def _fmt_money(n: float, lang: str) -> str:
    lang = _lang(lang)
    if lang == "en":
        return f"{n:,.0f} ₽"
    return f"{n:,.0f} ₽".replace(",", " ")


def _reason_texts(
    *,
    lang: str,
    cat_name: str,
    cat_score: float,
    line: str,
    pred: float,
    catalog_premium: int,
    budget: float,
    travel_p: Optional[float] = None,
    auto_risk: Optional[float] = None,
) -> List[str]:
    lang = _lang(lang)
    cat_l = translate_category(cat_name, lang)
    if cat_name == "Страхование жизни":
        line_l = {"ru": "жизнь/мед.", "kk": "өмір/мед.", "en": "life/medical"}.get(lang, "life")
    else:
        line_l = LINE_I18N.get(line, {}).get(lang, line)
    if lang == "kk":
        texts = [
            f"«{cat_l}» санатының сәйкестігі: {cat_score:.0%}",
            f"Күтілетін сыйақы ({line_l}): {_fmt_money(float(pred), lang)}; каталогта: {_fmt_money(float(catalog_premium), lang)}",
        ]
        if travel_p is not None and cat_name == "Туристическое страхование":
            texts.append(f"Саяхат сатып алу ықтималдығы: {travel_p:.0%}")
        if auto_risk is not None and cat_name == "Автострахование":
            texts.append(f"Автозақым қаупі: {auto_risk:.0%}")
        return texts
    if lang == "en":
        texts = [
            f"Category match “{cat_l}”: {cat_score:.0%}",
            f"Expected premium ({line_l}): {_fmt_money(float(pred), lang)}; catalog: {_fmt_money(float(catalog_premium), lang)}",
        ]
        if travel_p is not None and cat_name == "Туристическое страхование":
            texts.append(f"Travel purchase propensity: {travel_p:.0%}")
        if auto_risk is not None and cat_name == "Автострахование":
            texts.append(f"Auto claim risk: {auto_risk:.0%}")
        return texts
    texts = [
        f"Совпадение категории «{cat_l}»: {cat_score:.0%}",
        f"Ожидаемая премия ({line_l}): {_fmt_money(float(pred), lang)}; в каталоге: {_fmt_money(float(catalog_premium), lang)}",
    ]
    if travel_p is not None and cat_name == "Туристическое страхование":
        texts.append(f"Склонность купить туристическое: {travel_p:.0%}")
    if auto_risk is not None and cat_name == "Автострахование":
        texts.append(f"Риск автоубытка: {auto_risk:.0%}")
    return texts


def _blend_profile_priors(probs: Dict[str, float], profile: Dict[str, Any]) -> Dict[str, float]:
    if not probs:
        return probs
    p = {k: float(v) for k, v in probs.items() if k not in EXCLUDED_CATEGORIES}
    if not p:
        return probs

    def add(cat: str, w: float) -> None:
        if cat in EXCLUDED_CATEGORIES:
            return
        p[cat] = p.get(cat, 0.0) + w

    if profile.get("smoker"):
        add("Страхование жизни", 0.45)
        add("Медицинское страхование", 0.10)
    else:
        add("Медицинское страхование", 0.25)
        add("Страхование жизни", 0.05)

    if profile.get("has_home"):
        add("Имущественное страхование", 0.40)
    if profile.get("has_auto"):
        add("Автострахование", 0.50)
    if profile.get("travels"):
        add("Туристическое страхование", 0.50)

    if float(profile.get("children", 0) or 0) > 0:
        add("Страхование жизни", 0.08)
        add("Медицинское страхование", 0.05)

    if float(profile.get("high_income", 0) or 0) >= 0.5 or profile.get("high_income") is True:
        add("Имущественное страхование", 0.12)
        add("Страхование жизни", 0.08)
        add("Автострахование", 0.06)

    total = sum(p.values()) or 1.0
    return {k: v / total for k, v in p.items()}


def _score_policy(
    *,
    p: Policy,
    cat_name: str,
    cat_score: float,
    premiums: Dict[str, Any],
    income: float,
    budget: float,
    lang: str,
    travel_p: Optional[float] = None,
    auto_risk: Optional[float] = None,
) -> Dict[str, Any]:
    line = CATEGORY_TO_LINE.get(cat_name, "catalog")
    pred = premiums.get(line, {}).get("predicted_premium")
    if pred is None:
        pred = float(p.premium)
    premium_fit = 1.0 - min(1.0, abs(float(p.premium) - float(pred)) / max(float(pred), 1.0))
    budget_fit = 1.0 if p.premium <= budget else max(0.0, 1.0 - (p.premium - budget) / budget)
    coverage_fit = min(1.0, float(p.sum_assurance) / max(income * 2, 1.0))
    score = 0.55 * cat_score + 0.20 * premium_fit + 0.15 * budget_fit + 0.10 * coverage_fit
    return {
        "policy_id": p.id,
        "policy_name": p.name,
        "category": translate_category(cat_name, lang),
        "category_key": cat_name,
        "premium": p.premium,
        "sum_assurance": p.sum_assurance,
        "tenure": p.tenure,
        "score": round(float(score), 4),
        "predicted_line_premium": round(float(pred), 2),
        "category_score": round(cat_score, 4),
        "reasons": _reason_texts(
            lang=lang,
            cat_name=cat_name,
            cat_score=cat_score,
            line=line if line in premiums else "catalog",
            pred=float(pred),
            catalog_premium=int(p.premium),
            budget=float(budget),
            travel_p=travel_p,
            auto_risk=auto_risk,
        ),
    }


@lru_cache(maxsize=1)
def _load_bundle() -> Dict[str, Any]:
    bundle: Dict[str, Any] = {"models": {}, "metrics": {}, "load_errors": {}}
    metrics_path = MODELS_DIR / "metrics.json"
    if metrics_path.is_file():
        import json

        bundle["metrics"] = json.loads(metrics_path.read_text(encoding="utf-8"))
    for path in MODELS_DIR.glob("*.joblib"):
        try:
            bundle["models"][path.stem] = joblib.load(path)
        except Exception as exc:  # noqa: BLE001
            bundle["load_errors"][path.stem] = str(exc)
    return bundle


def reload_models() -> Dict[str, Any]:
    _load_bundle.cache_clear()
    return status()


def status() -> Dict[str, Any]:
    b = _load_bundle()
    models = sorted(b["models"].keys())
    load_errors = b.get("load_errors") or {}
    return {
        "ready": "category_recommender" in b["models"] and len(models) >= 2,
        "models": models,
        "models_dir": str(MODELS_DIR),
        "metrics": b.get("metrics", {}),
        "load_errors": load_errors,
        "message_ru": (
            f"Загружено моделей: {len(models)}"
            + (f"; ошибки загрузки: {len(load_errors)}" if load_errors else "")
            if models or load_errors
            else "Модели не найдены — выполните scripts/train_recommender.py"
        ),
    }


def _yes_no(val: Any, default: str = "No") -> str:
    if val is None:
        return default
    if isinstance(val, bool):
        return "Yes" if val else "No"
    s = str(val).strip().lower()
    if s in ("1", "yes", "y", "true", "да"):
        return "Yes"
    if s in ("0", "no", "n", "false", "нет"):
        return "No"
    if str(val) in ("Yes", "No"):
        return str(val)
    return default


def _employment_type(profile: Dict[str, Any]) -> str:
    raw = profile.get("employment_type") or profile.get("Employment Type") or ""
    s = str(raw).strip().lower()
    if "gov" in s or "государ" in s:
        return "Government Sector"
    if "priv" in s or "self" in s or "част" in s:
        return "Private Sector/Self Employed"
    return "Private Sector/Self Employed"


def _annual_income_for_propensity(income: float) -> float:
    x = float(income or 0)
    if 0 < x < PROPENSITY_INCOME_SCALE_BELOW:
        return x * PROPENSITY_INCOME_MULTIPLIER
    return x


def _family_members(profile: Dict[str, Any]) -> float:
    if profile.get("family_members") is not None:
        try:
            return float(profile.get("family_members"))
        except (TypeError, ValueError):
            pass
    children = float(profile.get("children", 0) or 0)
    return max(1.0, children + 1.0)


def _age_bin(age: Any) -> str:
    try:
        a = int(float(age))
    except (TypeError, ValueError):
        return "26-39"
    if a < 26:
        return "16-25"
    if a < 40:
        return "26-39"
    if a < 65:
        return "40-64"
    return "65+"


def _driving_experience(profile: Dict[str, Any]) -> str:
    raw = str(profile.get("driving_experience") or "").strip().lower()
    mapping = {
        "0-9y": "0-9y",
        "0-9": "0-9y",
        "10-19y": "10-19y",
        "10-19": "10-19y",
        "20-29y": "20-29y",
        "20-29": "20-29y",
        "30y+": "30y+",
        "30+": "30y+",
    }
    if raw in mapping:
        return mapping[raw]
    # оценка по возрасту: стаж ≈ age - 18
    try:
        years = max(0, int(float(profile.get("age", 35))) - 18)
    except (TypeError, ValueError):
        years = 10
    if years < 10:
        return "0-9y"
    if years < 20:
        return "10-19y"
    if years < 30:
        return "20-29y"
    return "30y+"


def _vehicle_year_label(profile: Dict[str, Any]) -> str:
    raw = str(profile.get("vehicle_year_label") or "").strip().lower()
    if "after" in raw or "после" in raw or raw == "new":
        return "after 2015"
    if "before" in raw or "до" in raw or raw == "old":
        return "before 2015"
    try:
        age = float(profile.get("vehicle_age", 8) or 8)
    except (TypeError, ValueError):
        age = 8.0
    # текущий год условно 2026
    return "after 2015" if age <= 11 else "before 2015"


def _claim_vehicle_type(profile: Dict[str, Any]) -> str:
    vt = str(profile.get("vehicle_type") or "Automobile").strip().lower()
    if "sport" in vt:
        return "sports car"
    return "sedan"


def _motor_vehicle_type(profile: Dict[str, Any]) -> str:
    vt = str(profile.get("vehicle_type") or "Automobile").strip()
    allowed = {"Automobile", "Station Wagones", "Pick-up", "Motor-cycle"}
    if vt in allowed:
        return vt
    low = vt.lower()
    if "pick" in low or "suv" in low:
        return "Pick-up"
    if "moto" in low or "bike" in low:
        return "Motor-cycle"
    if "station" in low or "wagon" in low:
        return "Station Wagones"
    return "Automobile"


def _motor_usage(profile: Dict[str, Any]) -> str:
    u = str(profile.get("vehicle_usage") or "Private").strip()
    if u in ("Private", "Own Goods"):
        return u
    low = u.lower()
    if "goods" in low or "груз" in low:
        return "Own Goods"
    return "Private"


def _credit_score(profile: Dict[str, Any]) -> float:
    if profile.get("credit_score") is not None:
        try:
            return float(np.clip(float(profile.get("credit_score")), 0.0, 1.0))
        except (TypeError, ValueError):
            pass
    # soft prior от дохода (замена census affordability)
    income = float(profile.get("income", 60000) or 60000)
    return float(np.clip(0.35 + income / 250000.0, 0.2, 0.85))


def _frame_for(model_name: str, profile: Dict[str, Any]) -> pd.DataFrame:
    art = _load_bundle()["models"][model_name]
    num_cols: List[str] = art["num_cols"]
    cat_cols: List[str] = art["cat_cols"]
    row: Dict[str, Any] = {}

    income = float(profile.get("income", 60000) or 60000)
    sex = str(profile.get("sex", "male")).lower()
    aliases = {
        "age": profile.get("age"),
        "Age": profile.get("age"),
        "bmi": profile.get("bmi", 25),
        "children": profile.get("children", 0),
        "sex": profile.get("sex", "unknown"),
        "smoker": "yes" if profile.get("smoker") else "no",
        "region": profile.get("region", "southeast"),
        "income": income,
        "AnnualIncome": _annual_income_for_propensity(income),
        "FamilyMembers": _family_members(profile),
        "ChronicDiseases": float(profile.get("chronic_diseases", 0) or 0),
        "Employment Type": _employment_type(profile),
        "GraduateOrNot": _yes_no(profile.get("graduate", True), "Yes"),
        "FrequentFlyer": _yes_no(profile.get("frequent_flyer", False), "No"),
        "EverTravelledAbroad": _yes_no(
            profile.get("ever_travelled_abroad", profile.get("travels", False)),
            "No",
        ),
        "Duration": profile.get("travel_duration", 7),
        "Distance": profile.get("travel_distance", 500),
        "Reason": profile.get("travel_reason", "vacation"),
        "Mode": profile.get("travel_mode", "plane"),
        "building_value": profile.get("building_value", 400000),
        "contents_value": profile.get("contents_value", 80000),
        "flood_risk_score": profile.get("flood_risk", 0.3),
        "fire_risk_score": profile.get("fire_risk", 0.3),
        "previous_claims_count": profile.get("prior_claims", 0),
        "coverage_level": profile.get("coverage_level", "Silver"),
        # auto premium (motor FE)
        "INSURED_VALUE": profile.get("vehicle_value", profile.get("insured_value", 280000)),
        "vehicle_age": profile.get("vehicle_age", 8),
        "SEATS_NUM": profile.get("vehicle_seats", 4),
        "CCM_TON": profile.get("engine_ccm", 1600),
        "SEX": 1.0 if sex in ("male", "m") else 0.0,
        "TYPE_VEHICLE": _motor_vehicle_type(profile),
        "USAGE": _motor_usage(profile),
        # auto claim risk
        "CREDIT_SCORE": _credit_score(profile),
        "ANNUAL_MILEAGE": profile.get("annual_mileage", 12000),
        "SPEEDING_VIOLATIONS": profile.get("speeding_violations", 0),
        "DUIS": profile.get("duis", 0),
        "PAST_ACCIDENTS": profile.get("past_accidents", 0),
        "VEHICLE_OWNERSHIP": float(profile.get("vehicle_ownership", 1) or 1),
        "AGE": _age_bin(profile.get("age", 35)),
        "GENDER": "male" if sex in ("male", "m") else "female",
        "DRIVING_EXPERIENCE": _driving_experience(profile),
        "VEHICLE_YEAR": _vehicle_year_label(profile),
        "VEHICLE_TYPE": _claim_vehicle_type(profile),
    }

    for c in num_cols:
        val = aliases.get(c, 0)
        try:
            row[c] = float(val if val is not None else 0)
        except (TypeError, ValueError):
            row[c] = 0.0
    for c in cat_cols:
        val = aliases.get(c, "unknown")
        row[c] = str(val if val is not None else "unknown")
    return pd.DataFrame([row])


def _predict_proba_positive(art: Dict[str, Any], X: pd.DataFrame) -> float:
    proba = art["pipeline"].predict_proba(X)[0]
    classes = list(art["pipeline"].named_steps["model"].classes_)
    if 1 in classes:
        return float(proba[list(classes).index(1)])
    return float(proba[-1])


def travel_propensity(profile: Dict[str, Any]) -> Optional[float]:
    b = _load_bundle()
    if "travel_propensity" not in b["models"]:
        return None
    art = b["models"]["travel_propensity"]
    try:
        return float(np.clip(_predict_proba_positive(art, _frame_for("travel_propensity", profile)), 0, 1))
    except Exception:  # noqa: BLE001
        return None


def auto_claim_risk(profile: Dict[str, Any]) -> Optional[float]:
    b = _load_bundle()
    if "auto_claim_risk" not in b["models"]:
        return None
    art = b["models"]["auto_claim_risk"]
    try:
        return float(np.clip(_predict_proba_positive(art, _frame_for("auto_claim_risk", profile)), 0, 1))
    except Exception:  # noqa: BLE001
        return None


def predict_premiums(profile: Dict[str, Any]) -> Dict[str, Any]:
    b = _load_bundle()
    out: Dict[str, Any] = {}
    for name in ("medical_premium", "home_premium", "travel_premium", "auto_premium"):
        if name not in b["models"]:
            continue
        art = b["models"][name]
        r2 = art.get("metrics", {}).get("r2")
        if r2 is not None and float(r2) < MIN_REGRESSOR_R2:
            continue
        X = _frame_for(name, profile)
        pred = float(art["pipeline"].predict(X)[0])
        out[name] = {
            "predicted_premium": round(max(0.0, pred), 2),
            "mae": art.get("metrics", {}).get("mae"),
            "r2": r2,
        }

    # мягкая оценка travel-премии из propensity, если нет сильного регрессора
    if "travel_premium" not in out and (profile.get("travels") or "travel_propensity" in b["models"]):
        tp = travel_propensity(profile)
        if tp is not None:
            duration = float(profile.get("travel_duration", 7) or 7)
            soft = SOFT_TRAVEL_BASE_PREMIUM * (0.55 + 0.9 * tp) * max(0.5, duration / 7.0)
            out["travel_premium"] = {
                "predicted_premium": round(max(0.0, soft), 2),
                "mae": None,
                "r2": None,
                "source": "soft_from_travel_propensity",
                "travel_propensity": round(tp, 4),
            }
    return out


def _income_prior(profile: Dict[str, Any]) -> float:
    """Платёжеспособность по заявленному доходу (+ soft credit_score)."""
    b = _load_bundle()
    if "income_affinity" in b["models"]:
        art = b["models"]["income_affinity"]
        try:
            return float(np.clip(_predict_proba_positive(art, _frame_for("income_affinity", profile)), 0, 1))
        except Exception:  # noqa: BLE001
            pass
    income = float(profile.get("income", 0) or 0)
    if income <= 0:
        return 0.0
    base = float(np.clip((income - HIGH_INCOME_THRESHOLD * 0.5) / HIGH_INCOME_THRESHOLD, 0.0, 1.0))
    credit = _credit_score(profile)
    return float(np.clip(0.7 * base + 0.3 * credit, 0.0, 1.0))


def _category_probs(
    profile: Dict[str, Any],
) -> tuple[Dict[str, float], float, Optional[float], Optional[float]]:
    b = _load_bundle()
    income_p = _income_prior(profile)
    profile = dict(profile)
    profile["high_income"] = income_p
    travel_p = travel_propensity(profile)
    auto_risk = auto_claim_risk(profile)

    base_fallback = {
        "Медицинское страхование": 0.25,
        "Страхование жизни": 0.20,
        "Имущественное страхование": 0.20,
        "Туристическое страхование": 0.15,
        "Автострахование": 0.20,
    }
    if "category_recommender" not in b["models"]:
        return _blend_profile_priors(base_fallback, profile), income_p, travel_p, auto_risk

    art = b["models"]["category_recommender"]
    feat_num = list(art.get("num_cols") or [])
    feat_cat = list(art.get("cat_cols") or [])
    raw = {
        "age": float(profile.get("age", 35)),
        "bmi": float(profile.get("bmi", 25)),
        "children": float(profile.get("children", 0)),
        "smoker": 1.0 if profile.get("smoker") else 0.0,
        "income": float(profile.get("income", 60000)),
        "has_home": 1.0 if profile.get("has_home") else 0.0,
        "has_auto": 1.0 if profile.get("has_auto") else 0.0,
        "travels": 1.0 if profile.get("travels") else 0.0,
        "high_income": float(income_p),
        "prior_claims": float(profile.get("prior_claims", profile.get("past_accidents", 0)) or 0),
        "sex": str(profile.get("sex", "unknown")),
    }
    row = {c: raw.get(c, 0.0) for c in feat_num}
    row.update({c: raw.get(c, "unknown") for c in feat_cat})
    X = pd.DataFrame([row])
    try:
        proba = art["pipeline"].predict_proba(X)[0]
        classes = list(art["pipeline"].named_steps["model"].classes_)
        probs = {str(c): float(p) for c, p in zip(classes, proba)}
    except Exception:  # noqa: BLE001
        probs = dict(base_fallback)

    if income_p > 0.55:
        if "Имущественное страхование" in probs:
            probs["Имущественное страхование"] += 0.08 * income_p
        if "Страхование жизни" in probs:
            probs["Страхование жизни"] += 0.05 * income_p

    if travel_p is not None:
        boost = 0.35 * float(travel_p)
        if profile.get("travels"):
            boost += 0.25 * float(travel_p)
        probs["Туристическое страхование"] = probs.get("Туристическое страхование", 0.0) + boost

    # UW claim risk → буст авто (как travel propensity)
    if auto_risk is not None:
        boost = 0.30 * float(auto_risk)
        if profile.get("has_auto"):
            boost += 0.28 * float(auto_risk)
        probs["Автострахование"] = probs.get("Автострахование", 0.0) + boost

    probs = _blend_profile_priors(probs, profile)
    return probs, income_p, travel_p, auto_risk


def recommend_policies(
    db: Session,
    profile: Dict[str, Any],
    *,
    top_k: int = 5,
    lang: str = "ru",
) -> Dict[str, Any]:
    if not status()["ready"]:
        raise RuntimeError("Модели рекомендаций не обучены")

    lang = _lang(lang)
    premiums = predict_premiums(profile)
    cat_probs, income_p, travel_p, auto_risk = _category_probs(profile)
    policies = (
        db.query(Policy).options(joinedload(Policy.category)).order_by(Policy.id).all()
    )
    income = float(profile.get("income", 60000) or 60000)
    budget = income * 0.08

    scored: list[dict] = []
    by_cat: dict[str, list[dict]] = {}
    for p in policies:
        cat_name = p.category.name if p.category else ""
        if cat_name in EXCLUDED_CATEGORIES:
            continue
        cat_score = float(cat_probs.get(cat_name, 0.0))
        item = _score_policy(
            p=p,
            cat_name=cat_name,
            cat_score=cat_score,
            premiums=premiums,
            income=income,
            budget=budget,
            lang=lang,
            travel_p=travel_p,
            auto_risk=auto_risk,
        )
        by_cat.setdefault(cat_name, []).append(item)
        if cat_score >= MIN_CATEGORY_PROB:
            scored.append(item)

    for items in by_cat.values():
        items.sort(key=lambda x: x["score"], reverse=True)

    must_cats: list[str] = []
    if profile.get("travels") or (travel_p is not None and travel_p >= 0.55):
        must_cats.append("Туристическое страхование")
    if profile.get("has_home"):
        must_cats.append("Имущественное страхование")
    if profile.get("has_auto") or (auto_risk is not None and auto_risk >= 0.55):
        must_cats.append("Автострахование")
    if profile.get("smoker"):
        must_cats.append("Страхование жизни")
    else:
        must_cats.append("Медицинское страхование")

    picked: dict[int, dict] = {}
    for cat in must_cats:
        items = by_cat.get(cat) or []
        if items:
            best = dict(items[0])
            best["score"] = round(max(best["score"], 0.35 + 0.5 * float(cat_probs.get(cat, 0))), 4)
            picked[best["policy_id"]] = best

    scored.sort(key=lambda x: x["score"], reverse=True)
    for item in scored:
        if len(picked) >= top_k:
            break
        picked.setdefault(item["policy_id"], item)

    top = sorted(picked.values(), key=lambda x: x["score"], reverse=True)[:top_k]
    top_cat = max(cat_probs, key=cat_probs.get) if cat_probs else None
    metrics = _load_bundle().get("metrics", {})
    cat_m = (metrics.get("models") or {}).get("category_recommender") or {}
    tp_m = (metrics.get("models") or {}).get("travel_propensity") or {}
    ap_m = (metrics.get("models") or {}).get("auto_premium") or {}
    ar_m = (metrics.get("models") or {}).get("auto_claim_risk") or {}
    active_premiums = sorted(premiums.keys())
    models_in_use = set(active_premiums)
    if cat_probs:
        models_in_use.add("category_recommender")
    if travel_p is not None:
        models_in_use.add("travel_propensity")
    if auto_risk is not None:
        models_in_use.add("auto_claim_risk")
    return {
        "profile": profile,
        "category_probabilities": {
            translate_category(k, lang): round(v, 4)
            for k, v in sorted(cat_probs.items(), key=lambda kv: -kv[1])
            if k not in EXCLUDED_CATEGORIES
        },
        "top_category": translate_category(top_cat, lang) if top_cat else None,
        "predicted_premiums": premiums,
        "travel_propensity": round(float(travel_p), 4) if travel_p is not None else None,
        "auto_claim_risk": round(float(auto_risk), 4) if auto_risk is not None else None,
        "budget_estimate": round(budget, 2),
        "recommendations": top,
        "lang": lang,
        "model_status": status()["message_ru"],
        "enrichment": {
            "external_sources": metrics.get("external_sources") or {},
            "datasets": metrics.get("datasets") or [],
            "models_in_use": sorted(models_in_use),
            "category_train_rows": cat_m.get("n_rows"),
            "category_accuracy": cat_m.get("accuracy"),
            "travel_propensity_auc": tp_m.get("roc_auc"),
            "auto_premium_r2": ap_m.get("r2"),
            "auto_claim_risk_auc": ar_m.get("roc_auc"),
            "income_prior": round(float(income_p), 4),
            "min_regressor_r2": MIN_REGRESSOR_R2,
            "profile_priors": True,
            "effect_ru": (
                "ML: medical/home/auto premiums + travel propensity + auto claim risk. "
                "Правила профиля: жильё / авто / поездки / курение. "
                f"Активные премии: {', '.join(active_premiums) or 'каталог'}."
            ),
        },
    }
