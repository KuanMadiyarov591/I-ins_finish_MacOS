"""Lead scoring (как lead-scoring-gcp): buy probability + tiers + reasons."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Dict, List, Tuple

import joblib
import numpy as np
import pandas as pd

from iins_agent_app.config import ROOT

MODELS_DIR = ROOT / "models" / "agent"

# Как в cacaprog/lead-scoring-gcp: Hot / Warm / Nurture / Suppress
# у них score 0-100; у нас — вероятность покупки TravelInsurance
TIER_BY_PROB = (
    ("Hot", 0.60),
    ("Warm", 0.42),
    ("Nurture", 0.25),
    ("Suppress", 0.0),
)

TIER_SLA = {
    "Hot": "Позвонить в ближайшие 2 часа — высокий шанс покупки",
    "Warm": "Позвонить сегодня / завтра",
    "Nurture": "Мягкий follow-up на неделе (письмо / мессенджер)",
    "Suppress": "Не тратить холодный звонок — низкий приоритет",
}

TIER_RU = {
    "Hot": "Горячий",
    "Warm": "Тёплый",
    "Nurture": "Прогрев",
    "Suppress": "Не звонить",
}

FEATURE_LABELS_POS = {
    "AnnualIncome": "Высокий годовой доход",
    "FrequentFlyer": "Частый авиапассажир",
    "EverTravelledAbroad": "Уже бывал за границей",
    "FamilyMembers": "Большая семья (больше покрытие)",
    "GraduateOrNot": "Высшее образование",
    "Employment Type": "Частный сектор / самозанятость",
    "Age": "Возраст в целевом сегменте",
    "ChronicDiseases": "Есть хронические заболевания (мотивация к страховке)",
}

FEATURE_LABELS_NEG = {
    "AnnualIncome": "Низкий доход",
    "FrequentFlyer": "Редко летает",
    "EverTravelledAbroad": "Не был за границей",
    "FamilyMembers": "Маленькая семья",
    "GraduateOrNot": "Без высшего образования",
    "Employment Type": "Госсектор (ниже склонность в датасете)",
    "Age": "Возраст вне типичного покупателя",
    "ChronicDiseases": "Нет хронических заболеваний",
}

# нейтральный профиль для вкладов признаков (как baseline в explain)
BASELINE = {
    "Age": 35.0,
    "AnnualIncome": 500_000.0,
    "FamilyMembers": 3.0,
    "ChronicDiseases": 0.0,
    "Employment Type": "Government Sector",
    "GraduateOrNot": "No",
    "FrequentFlyer": "No",
    "EverTravelledAbroad": "No",
}


def tier_for(buy_probability: float) -> str:
    p = float(buy_probability)
    for name, lo in TIER_BY_PROB:
        if p >= lo:
            return name
    return "Suppress"


def tier_action(tier: str) -> str:
    return TIER_SLA.get(tier, "Оценить вручную")


def score_0_100(buy_probability: float) -> float:
    return round(float(np.clip(buy_probability, 0, 1)) * 100.0, 1)


@lru_cache(maxsize=1)
def _load_bundle() -> Dict[str, Any]:
    bundle: Dict[str, Any] = {"models": {}, "metrics": {}, "load_errors": {}}
    metrics_path = MODELS_DIR / "metrics.json"
    if metrics_path.is_file():
        bundle["metrics"] = json.loads(metrics_path.read_text(encoding="utf-8"))
    search_dirs = [MODELS_DIR]
    # релевантная модель агента также лежит в InsuraDesk recommender (тот же travel_propensity)
    sibling = ROOT.parent / "insurance-rag-system" / "models" / "recommender"
    if sibling.is_dir():
        search_dirs.append(sibling)
    for directory in search_dirs:
        for path in directory.glob("*.joblib"):
            # только propensity для агента — не claim/fraud/premium regressors
            if path.stem != "travel_propensity":
                continue
            if path.stem in bundle["models"]:
                continue
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
    ready = "travel_propensity" in b["models"]
    m = ((b.get("metrics") or {}).get("models") or {}).get("travel_propensity") or {}
    return {
        "ready": ready,
        "models": models,
        "models_dir": str(MODELS_DIR),
        "metrics": b.get("metrics", {}),
        "load_errors": load_errors,
        "what_we_predict_ru": (
            "Вероятность, что клиент КУПИТ туристическую страховку "
            "(класс TravelInsurance=1 в датасете agent 22)."
        ),
        "tiers": {
            "Hot": "≥60% — звонить срочно",
            "Warm": "42–59% — звонить сегодня",
            "Nurture": "25–41% — прогрев",
            "Suppress": "<25% — не холодный звонок",
        },
        "model_auc": m.get("roc_auc"),
        "message_ru": (
            f"Модель готова · AUC={float(m['roc_auc']):.2f}"
            if ready and m.get("roc_auc") is not None
            else (
                "Модель готова"
                if ready
                else "Модель не найдена — scripts/train_agent_models.py"
            )
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


def _employment_type(raw: Any) -> str:
    s = str(raw or "").strip().lower()
    if "gov" in s or "государ" in s:
        return "Government Sector"
    if "priv" in s or "self" in s or "част" in s or "private" in s:
        return "Private Sector/Self Employed"
    if "Government Sector" in str(raw) or "Private Sector" in str(raw):
        return str(raw)
    return "Private Sector/Self Employed"


def profile_from_lead_row(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "Age": int(row.get("age") or row.get("Age") or 35),
        "AnnualIncome": float(row.get("annual_income") or row.get("AnnualIncome") or 500000),
        "FamilyMembers": int(row.get("family_members") or row.get("FamilyMembers") or 2),
        "ChronicDiseases": int(row.get("chronic_diseases") or row.get("ChronicDiseases") or 0),
        "Employment Type": _employment_type(row.get("employment_type") or row.get("Employment Type")),
        "GraduateOrNot": _yes_no(row.get("graduate") if "graduate" in row else row.get("GraduateOrNot"), "Yes"),
        "FrequentFlyer": _yes_no(row.get("frequent_flyer") if "frequent_flyer" in row else row.get("FrequentFlyer"), "No"),
        "EverTravelledAbroad": _yes_no(
            row.get("ever_travelled_abroad") if "ever_travelled_abroad" in row else row.get("EverTravelledAbroad"),
            "No",
        ),
    }


def _normalize(profile: Dict[str, Any]) -> Dict[str, Any]:
    mapped = profile_from_lead_row(profile)
    for k, v in profile.items():
        if k in mapped or k in BASELINE:
            mapped[k] = v
    mapped["Employment Type"] = _employment_type(mapped.get("Employment Type"))
    for k in ("GraduateOrNot", "FrequentFlyer", "EverTravelledAbroad"):
        mapped[k] = _yes_no(mapped.get(k), "No" if k != "GraduateOrNot" else "Yes")
    mapped["Age"] = float(mapped.get("Age") or 35)
    mapped["AnnualIncome"] = float(mapped.get("AnnualIncome") or 500000)
    mapped["FamilyMembers"] = float(mapped.get("FamilyMembers") or 2)
    mapped["ChronicDiseases"] = float(mapped.get("ChronicDiseases") or 0)
    return mapped


def _frame_from_mapped(mapped: Dict[str, Any]) -> pd.DataFrame:
    art = _load_bundle()["models"]["travel_propensity"]
    num_cols: List[str] = art["num_cols"]
    cat_cols: List[str] = art["cat_cols"]
    row: Dict[str, Any] = {}
    for c in num_cols:
        try:
            row[c] = float(mapped.get(c, 0) or 0)
        except (TypeError, ValueError):
            row[c] = 0.0
    for c in cat_cols:
        row[c] = str(mapped.get(c, "unknown"))
    return pd.DataFrame([row])


def _predict_buy_prob(mapped: Dict[str, Any]) -> float:
    art = _load_bundle()["models"]["travel_propensity"]
    X = _frame_from_mapped(mapped)
    proba = art["pipeline"].predict_proba(X)[0]
    classes = list(art["pipeline"].named_steps["model"].classes_)
    if 1 in classes:
        score = float(proba[list(classes).index(1)])
    else:
        score = float(proba[-1])
    return float(np.clip(score, 0.0, 1.0))


def _explanations(mapped: Dict[str, Any], full_score: float) -> Tuple[str, str, str, str]:
    """Вклад признака ≈ насколько падает score, если заменить на baseline (как у GCP reasons)."""
    deltas: List[Tuple[float, str, bool]] = []
    for feat in (
        "AnnualIncome",
        "FrequentFlyer",
        "EverTravelledAbroad",
        "FamilyMembers",
        "GraduateOrNot",
        "Employment Type",
        "Age",
        "ChronicDiseases",
    ):
        if mapped.get(feat) == BASELINE.get(feat):
            continue
        ablated = dict(mapped)
        ablated[feat] = BASELINE[feat]
        drop = full_score - _predict_buy_prob(ablated)
        deltas.append((drop, feat, drop > 0))

    pos = sorted([d for d in deltas if d[0] > 0.01], key=lambda x: -x[0])
    neg = sorted([d for d in deltas if d[0] < -0.01], key=lambda x: x[0])

    reasons: List[str] = []
    for drop, feat, _ in pos[:3]:
        reasons.append(FEATURE_LABELS_POS.get(feat, feat))
    while len(reasons) < 3:
        reasons.append("—")

    top_neg = "—"
    if neg:
        feat = neg[0][1]
        top_neg = FEATURE_LABELS_NEG.get(feat, feat)
    return reasons[0], reasons[1], reasons[2], top_neg


def score_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    b = _load_bundle()
    if "travel_propensity" not in b["models"]:
        raise RuntimeError("Модель travel_propensity не обучена")

    mapped = _normalize(profile)
    buy_p = _predict_buy_prob(mapped)
    will_buy = buy_p >= 0.5
    tier = tier_for(buy_p)
    r1, r2, r3, top_neg = _explanations(mapped, buy_p)
    s100 = score_0_100(buy_p)

    return {
        # явные поля «купит / не купит» (как Conversion Probability в GCP dashboard)
        "target_ru": "Покупка туристической страховки",
        "buy_probability": round(buy_p, 4),
        "will_buy": will_buy,
        "will_buy_label": "Скорее купит" if will_buy else "Скорее не купит",
        "score_0_100": s100,
        "score": round(buy_p, 4),  # alias для совместимости
        "tier": tier,
        "tier_ru": TIER_RU.get(tier, tier),
        "sla": TIER_SLA[tier],
        "action": TIER_SLA[tier],
        "reason_1": r1,
        "reason_2": r2,
        "reason_3": r3,
        "top_negative": top_neg,
        "model": "travel_propensity",
        "auc": ((b.get("metrics") or {}).get("models") or {}).get("travel_propensity", {}).get("roc_auc"),
        "profile_used": mapped,
    }


def score_many(profiles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [score_profile(p) for p in profiles]
