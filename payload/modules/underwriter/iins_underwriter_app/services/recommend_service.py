"""Рекомендации андеррайтера: классы риска из EDA (OUTCOME / fraud_reported / has_claim)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from iins_underwriter_app.config import get_settings
from iins_underwriter_app.services import risk_service as risk
from iins_underwriter_app.services.case_helpers import extract_premium, parse_json_list, parse_json_obj

LINE_RU = {
    "auto": "Личное авто · риск убытка",
    "fraud": "Мошенничество по убытку",
    "motor": "Парк ТС · страховой случай",
}
LINE_SHORT_RU = {
    "auto": "Личное авто",
    "fraud": "Мошенничество",
    "motor": "Парк ТС",
}
REC_RU = {"approve": "Одобрить", "refer": "На эскалацию", "decline": "Отклонить"}

# Таксономия из EDA 02_underwriter_* (внутренние id: auto / fraud / motor)
RISK_TAXONOMY: Dict[str, Dict[str, Any]] = {
    "auto": {
        "model_key": "auto",
        "target": "OUTCOME",
        "line_short": "Личное авто",
        "line_full": "Личное авто · риск убытка",
        "risk_question": "Какова вероятность убытка по личному авто?",
        "title_base": "Личное авто · риск убытка",
        "category": "auto_risk",
        "category_label": "Личное авто · убыток",
        "definition": "Склонность водителя личного авто к убытку / претензии (OUTCOME).",
        "eda_note": "Personal driver claim/loss propensity",
        "grade": "A",
        "feature_hints": [
            "кредитный балл",
            "годовой пробег",
            "DUIS / нетрезвое",
            "прошлые ДТП",
            "нарушения скорости",
            "опыт вождения",
        ],
        "feature_keys": (
            "CREDIT_SCORE",
            "ANNUAL_MILEAGE",
            "VEHICLE_OWNERSHIP",
            "SPEEDING_VIOLATIONS",
            "DUIS",
            "PAST_ACCIDENTS",
            "AGE",
            "GENDER",
            "DRIVING_EXPERIENCE",
            "VEHICLE_YEAR",
            "VEHICLE_TYPE",
            "INCOME",
            "MARRIED",
            "CHILDREN",
            "RACE",
            "EDUCATION",
        ),
    },
    "fraud": {
        "model_key": "fraud",
        "target": "fraud_reported",
        "line_short": "Мошенничество",
        "line_full": "Мошенничество по убытку",
        "risk_question": "Есть ли сигнал мошенничества по убытку?",
        "title_base": "Мошенничество по убытку",
        "category": "fraud",
        "category_label": "Мошенничество по убытку",
        "definition": "Сигнал мошенничества по заявленному убытку (fraud_reported).",
        "eda_note": "Fraud signal on claim",
        "grade": "B",
        "feature_hints": [
            "тяжесть инцидента",
            "отчёт полиции",
            "свидетели",
            "срок клиента",
            "тип инцидента",
            "повреждение имущества",
        ],
        "feature_keys": (
            "months_as_customer",
            "age",
            "policy_deductable",
            "policy_annual_premium",
            "umbrella_limit",
            "number_of_vehicles_involved",
            "bodily_injuries",
            "witnesses",
            "incident_severity",
            "police_report_available",
            "property_damage",
            "incident_type",
            "collision_type",
            "insured_sex",
            "authorities_contacted",
            "capital-gains",
            "capital-loss",
            "incident_hour_of_the_day",
            "auto_year",
            "policy_state",
            "auto_make",
        ),
    },
    "motor": {
        "model_key": "motor",
        "target": "has_claim",
        "line_short": "Парк ТС",
        "line_full": "Парк ТС · страховой случай",
        "risk_question": "Какова вероятность страхового случая по парку ТС?",
        "title_base": "Парк ТС · страховой случай",
        "category": "motor_risk",
        "category_label": "Парк ТС · страховой случай",
        "definition": (
            "Вероятность страхового случая по парку ТС (has_claim). "
            "Единица — ТС/полис смешанного портфеля (TYPE_VEHICLE, USAGE, PREMIUM, INSURED_VALUE)."
        ),
        "eda_note": "Vehicle portfolio claim event (mixed private+commercial; unit=vehicle/policy)",
        "grade": "C",
        "confidence_note": (
            "Модель has_claim слабее линейки личного авто — трактуйте вероятность осторожнее."
        ),
        "feature_hints": [
            "премия / страховая сумма",
            "возраст ТС",
            "использование (USAGE)",
            "тип ТС (TYPE_VEHICLE)",
            "число мест",
            "марка",
        ],
        "feature_keys": (
            "PREMIUM",
            "INSURED_VALUE",
            "vehicle_age",
            "SEATS_NUM",
            "CCM_TON",
            "CARRYING_CAPACITY",
            "SEX",
            "TYPE_VEHICLE",
            "USAGE",
            "MAKE",
            "value_per_seat",
            "log_insured",
        ),
    },
}


def _taxonomy_legend() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for lid, meta in RISK_TAXONOMY.items():
        out.append(
            {
                "id": lid,
                "label": meta["line_full"],
                "label_short": meta["line_short"],
                "target": meta["target"],
                "meaning": meta["definition"],
                "eda_note": meta.get("eda_note", ""),
                "grade": meta.get("grade", ""),
            }
        )
    return out

_MODELS: Dict[str, Any] = {}
_MODELS_CHECKED = False
_METRICS: Dict[str, Any] = {}


def _model_files() -> Dict[str, Path]:
    d = get_settings().model_dir
    return {
        "auto": d / "auto_outcome.joblib",
        "fraud": d / "fraud_flag.joblib",
        "motor": d / "motor_claim.joblib",
    }


def _load_models() -> Dict[str, Any]:
    global _MODELS, _MODELS_CHECKED, _METRICS
    if _MODELS_CHECKED:
        return _MODELS
    _MODELS_CHECKED = True
    try:
        import joblib
    except Exception:  # noqa: BLE001
        return _MODELS

    for key, path in _model_files().items():
        if not path.is_file():
            continue
        try:
            _MODELS[key] = joblib.load(path)
        except Exception:  # noqa: BLE001
            pass

    metrics_path = get_settings().model_dir / "metrics.json"
    if metrics_path.is_file():
        try:
            _METRICS = json.loads(metrics_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            _METRICS = {}
    return _MODELS


def status() -> Dict[str, Any]:
    models = _load_models()
    return {
        "ready": True,
        "models_loaded": sorted(models.keys()),
        "metrics": _METRICS,
        "taxonomy": {
            k: {
                "target": v["target"],
                "title_base": v["title_base"],
                "line_short": v["line_short"],
                "line_full": v["line_full"],
                "risk_question": v["risk_question"],
                "grade": v.get("grade"),
                "eda_note": v.get("eda_note"),
            }
            for k, v in RISK_TAXONOMY.items()
        },
        "taxonomy_legend": _taxonomy_legend(),
        "fallback": "risk_service",
    }


def _safe_float(v: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        if v is None or v == "":
            return default
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _truthy(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    return str(v).strip().lower() in {"1", "1.0", "true", "yes", "y", "t"}


def _feat(features: Dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in features and features[k] is not None and features[k] != "":
            return features[k]
    return None


def _fmt_num(v: float, digits: int = 0) -> str:
    if digits == 0:
        return f"{v:,.0f}".replace(",", " ")
    return f"{v:,.{digits}f}".replace(",", " ")


def _predict_line_proba(line: str, features: Dict[str, Any]) -> Optional[float]:
    models = _load_models()
    bundle = models.get(line)
    if not bundle:
        return None
    pipe = bundle.get("pipeline") if isinstance(bundle, dict) else bundle
    feat_names = bundle.get("features") if isinstance(bundle, dict) else None
    if pipe is None:
        return None
    row: Dict[str, Any] = {}
    if feat_names:
        for name in feat_names:
            row[name] = features.get(name)
    else:
        row = dict(features)
    try:
        X = pd.DataFrame([row])
        if feat_names:
            X = X.reindex(columns=feat_names)
        proba = float(pipe.predict_proba(X)[0][1])
        return max(0.0, min(1.0, proba))
    except Exception:  # noqa: BLE001
        return None


def _feature_coverage(line: str, features: Dict[str, Any]) -> float:
    keys = RISK_TAXONOMY.get(line, {}).get("feature_keys") or ()
    if not keys:
        return 0.0
    hit = sum(1 for k in keys if _feat(features, k) is not None)
    return hit / float(len(keys))


def _heuristic_proba(line: str, features: Dict[str, Any], risk_score: float) -> float:
    """Запасной сигнал, если модель недоступна — всё равно по признакам кейса."""
    base = max(0.05, min(0.95, risk_score / 100.0))
    if line == "auto":
        duis = _safe_int(_feat(features, "DUIS", "duis"))
        accidents = _safe_int(_feat(features, "PAST_ACCIDENTS", "past_accidents"))
        violations = _safe_int(_feat(features, "SPEEDING_VIOLATIONS", "speeding_violations"))
        credit = _safe_float(_feat(features, "CREDIT_SCORE", "credit_score"), 0.5) or 0.5
        bump = min(0.45, duis * 0.18 + accidents * 0.1 + max(0, violations - 1) * 0.05)
        if credit < 0.4:
            bump += 0.08
        return max(0.05, min(0.95, 0.55 * base + 0.45 * (0.2 + bump)))
    if line == "fraud":
        severity = str(_feat(features, "incident_severity") or "").lower()
        police = str(_feat(features, "police_report_available") or "").strip().upper()
        witnesses = _safe_int(_feat(features, "witnesses"))
        bump = 0.15
        if "major" in severity or "total" in severity:
            bump += 0.25
        if police in {"NO", "N", "?"}:
            bump += 0.12
        if witnesses == 0:
            bump += 0.08
        if _truthy(_feat(features, "fraud_reported")):
            bump = 0.85
        return max(0.05, min(0.95, 0.4 * base + bump))
    # motor
    prem = _safe_float(_feat(features, "PREMIUM", "premium"), 0.0) or 0.0
    insured = _safe_float(_feat(features, "INSURED_VALUE", "insured_value"), 0.0) or 0.0
    age = _safe_float(_feat(features, "vehicle_age"), 0.0) or 0.0
    bump = 0.12
    if prem > 0 and insured > 0:
        ratio = prem / insured
        if ratio >= 0.08:
            bump += 0.18
        elif ratio <= 0.01 and insured >= 200_000:
            bump += 0.1
    if age >= 12:
        bump += 0.1
    if _truthy(_feat(features, "has_claim")):
        bump += 0.25
    return max(0.05, min(0.95, 0.45 * base + bump))


def _auto_reasons(features: Dict[str, Any]) -> List[str]:
    why: List[str] = []
    credit = _safe_float(_feat(features, "CREDIT_SCORE", "credit_score"))
    mileage = _safe_float(_feat(features, "ANNUAL_MILEAGE", "annual_mileage"))
    ownership = _feat(features, "VEHICLE_OWNERSHIP", "vehicle_ownership")
    violations = _safe_int(_feat(features, "SPEEDING_VIOLATIONS", "speeding_violations"))
    duis = _safe_int(_feat(features, "DUIS", "duis"))
    accidents = _safe_int(_feat(features, "PAST_ACCIDENTS", "past_accidents"))
    age = _feat(features, "AGE", "age")
    exp = _feat(features, "DRIVING_EXPERIENCE", "driving_experience")
    vyear = _feat(features, "VEHICLE_YEAR", "vehicle_year")
    vtype = _feat(features, "VEHICLE_TYPE", "vehicle_type")
    income = _feat(features, "INCOME", "income")

    if duis:
        why.append(f"DUIS = {duis} (вождение в нетрезвом виде)")
    if accidents:
        why.append(f"PAST_ACCIDENTS = {accidents} (прошлые ДТП)")
    if violations:
        why.append(f"SPEEDING_VIOLATIONS = {violations} (нарушения скорости)")
    if credit is not None:
        why.append(f"CREDIT_SCORE = {credit:.2f} (кредитный балл)")
    if mileage is not None:
        why.append(f"ANNUAL_MILEAGE = {_fmt_num(mileage)} (годовой пробег)")
    if ownership is not None:
        why.append(f"VEHICLE_OWNERSHIP = {ownership} (владение ТС)")
    if age is not None:
        why.append(f"AGE = {age} (возраст)")
    if exp is not None:
        why.append(f"DRIVING_EXPERIENCE = {exp} (опыт вождения)")
    if vyear is not None:
        why.append(f"VEHICLE_YEAR = {vyear} (год ТС)")
    if vtype is not None:
        why.append(f"VEHICLE_TYPE = {vtype} (тип ТС)")
    if income is not None:
        why.append(f"INCOME = {income} (доход)")
    return why


def _fraud_reasons(features: Dict[str, Any]) -> List[str]:
    why: List[str] = []
    severity = _feat(features, "incident_severity")
    police = _feat(features, "police_report_available")
    witnesses = _feat(features, "witnesses")
    itype = _feat(features, "incident_type")
    collision = _feat(features, "collision_type")
    damage = _feat(features, "property_damage")
    authorities = _feat(features, "authorities_contacted")
    nveh = _feat(features, "number_of_vehicles_involved")
    injuries = _feat(features, "bodily_injuries")
    months = _feat(features, "months_as_customer")
    premium = _safe_float(_feat(features, "policy_annual_premium"))

    if severity is not None:
        why.append(f"incident_severity = {severity} (тяжесть)")
    if police is not None:
        why.append(f"police_report_available = {police} (отчёт полиции)")
    if witnesses is not None:
        why.append(f"witnesses = {witnesses} (свидетели)")
    if itype is not None:
        why.append(f"incident_type = {itype} (тип инцидента)")
    if collision is not None and str(collision) != "?":
        why.append(f"collision_type = {collision} (тип столкновения)")
    if damage is not None:
        why.append(f"property_damage = {damage} (повреждение имущества)")
    if authorities is not None:
        why.append(f"authorities_contacted = {authorities} (обращение в органы)")
    if nveh is not None:
        why.append(f"number_of_vehicles_involved = {nveh} (число ТС)")
    if injuries is not None:
        why.append(f"bodily_injuries = {injuries} (телесные повреждения)")
    if months is not None:
        why.append(f"months_as_customer = {months} (месяцев клиентом)")
    if premium is not None:
        why.append(f"policy_annual_premium = {_fmt_num(premium, 2)} (годовая премия)")
    return why


def _motor_reasons(features: Dict[str, Any], premium: float) -> List[str]:
    why: List[str] = []
    prem = premium or (_safe_float(_feat(features, "PREMIUM", "premium"), 0.0) or 0.0)
    insured = _safe_float(_feat(features, "INSURED_VALUE", "insured_value"), 0.0) or 0.0
    vage = _safe_float(_feat(features, "vehicle_age"))
    seats = _feat(features, "SEATS_NUM")
    usage = _feat(features, "USAGE", "usage")
    make = _feat(features, "MAKE", "make")
    tveh = _feat(features, "TYPE_VEHICLE")
    vps = _safe_float(_feat(features, "value_per_seat"))
    ccm = _feat(features, "CCM_TON")

    if prem > 0 and insured > 0:
        ratio = prem / insured
        why.append(
            f"PREMIUM/INSURED_VALUE = {ratio * 100:.2f}% "
            f"({_fmt_num(prem)} / {_fmt_num(insured)}) (премия к сумме)"
        )
    elif prem > 0:
        why.append(f"PREMIUM = {_fmt_num(prem)} (премия)")
    if insured > 0 and not (prem > 0):
        why.append(f"INSURED_VALUE = {_fmt_num(insured)} (страховая сумма)")
    if vage is not None:
        why.append(f"vehicle_age = {vage:.0f} (возраст ТС)")
    if vps is not None:
        why.append(f"value_per_seat = {_fmt_num(vps)} (стоимость на место)")
    if seats is not None:
        why.append(f"SEATS_NUM = {seats} (число мест)")
    if usage is not None:
        why.append(f"USAGE = {usage} (использование)")
    if make is not None:
        why.append(f"MAKE = {make} (марка)")
    if tveh is not None:
        why.append(f"TYPE_VEHICLE = {tveh} (тип ТС, парк ТС)")
    if ccm is not None:
        why.append(f"CCM_TON = {ccm} (объём/тоннаж)")
    return why


def _reasons_for_line(line: str, features: Dict[str, Any], premium: float) -> List[str]:
    if line == "auto":
        why = _auto_reasons(features)
    elif line == "fraud":
        why = _fraud_reasons(features)
    else:
        why = _motor_reasons(features, premium)
    seen: set[str] = set()
    out: List[str] = []
    for r in why:
        if r and r not in seen:
            seen.add(r)
            out.append(r)
        if len(out) >= 5:
            break
    return out


def _resolve_proba(
    line: str,
    features: Dict[str, Any],
    risk_score: float,
) -> Tuple[float, str]:
    ml = _predict_line_proba(line, features)
    if ml is not None:
        return ml, "model"
    return _heuristic_proba(line, features, risk_score), "heuristic"


def _risk_tile(
    *,
    line: str,
    proba: float,
    source: str,
    features: Dict[str, Any],
    premium: float,
    primary: bool,
) -> Dict[str, Any]:
    meta = RISK_TAXONOMY[line]
    pct = int(round(proba * 100))
    pct = max(1, min(99, pct))
    reasons = _reasons_for_line(line, features, premium)
    if not reasons:
        reasons = [f"Цель EDA: {meta['target']}"]
    if source == "model":
        reasons = [f"Модель по цели «{meta['target']}»"] + reasons
    else:
        reasons = [f"Оценка по признакам (цель «{meta['target']}»)"] + reasons
    tile: Dict[str, Any] = {
        "id": f"risk_{line}",
        "title": f"{meta['title_base']}: {pct}%",
        "category": meta["category"],
        "category_label": meta["category_label"],
        "match_pct": pct,
        "match_kind": "probability",
        "match_label": "вероятность",
        "line": line,
        "line_label": meta["line_full"],
        "line_short": meta["line_short"],
        "risk_question": meta["risk_question"],
        "target": meta["target"],
        "definition": meta["definition"],
        "feature_hints": list(meta.get("feature_hints") or []),
        "proba": round(proba, 4),
        "primary": primary,
        "grade": meta.get("grade"),
        "reasons": reasons[:5],
    }
    note = meta.get("confidence_note")
    if note and line == "motor":
        tile["confidence_note"] = note
    return tile


def _decision_tile(
    *,
    recommendation: str,
    risk_score: float,
    primary_proba: float,
    primary_line: str,
    feature_reasons: List[str],
) -> Dict[str, Any]:
    lean = recommendation if recommendation in REC_RU else "refer"
    titles = {
        "approve": "Склоняться к одобрению",
        "refer": "Направить на эскалацию",
        "decline": "Склоняться к отказу",
    }
    # match_pct отражает уверенность lean, привязанную к вероятности риска
    if lean == "decline":
        match = int(round(40 + primary_proba * 55))
    elif lean == "approve":
        match = int(round(40 + (1.0 - primary_proba) * 55))
    else:
        match = int(round(50 + (1.0 - abs(primary_proba - 0.5) * 2) * 25))
    match = max(8, min(99, match))

    meta = RISK_TAXONOMY[primary_line]
    target = meta["target"]
    why = [
        f"Вероятность «{target}» ({meta['line_short']}) = {primary_proba * 100:.0f}%",
        f"Интегральный риск-скор: {risk_score:.0f}",
    ]
    for r in feature_reasons:
        if r not in why:
            why.append(r)
        if len(why) >= 4:
            break
    return {
        "id": f"decision_{lean}",
        "title": titles[lean],
        "category": "decision",
        "category_label": "Решение",
        "match_pct": match,
        "match_kind": "confidence",
        "match_label": "уверенность",
        "reasons": why[:4],
        "action": lean,
        "line": primary_line,
        "line_label": meta["line_full"],
        "target": target,
    }


def _build_tiles(
    *,
    line: str,
    features: Dict[str, Any],
    risk_score: float,
    recommendation: str,
    premium: float,
) -> Tuple[List[Dict[str, Any]], Dict[str, Optional[float]], Optional[float]]:
    line_n = line if line in RISK_TAXONOMY else "auto"
    probas: Dict[str, Optional[float]] = {"auto": None, "fraud": None, "motor": None}
    sources: Dict[str, str] = {}

    primary_proba, primary_src = _resolve_proba(line_n, features, risk_score)
    probas[line_n] = primary_proba
    sources[line_n] = primary_src

    # Доп. классы — только если в кейсе достаточно признаков этой линейки
    for other in ("auto", "fraud", "motor"):
        if other == line_n:
            continue
        if _feature_coverage(other, features) < 0.35:
            continue
        p, src = _resolve_proba(other, features, risk_score)
        # Не раздувать UI слабыми эвристиками по чужой линейке
        if src != "model":
            continue
        probas[other] = p
        sources[other] = src

    tiles: List[Dict[str, Any]] = []
    tiles.append(
        _risk_tile(
            line=line_n,
            proba=primary_proba,
            source=primary_src,
            features=features,
            premium=premium,
            primary=True,
        )
    )
    for other in ("auto", "fraud", "motor"):
        if other == line_n or probas[other] is None:
            continue
        tiles.append(
            _risk_tile(
                line=other,
                proba=float(probas[other]),
                source=sources[other],
                features=features,
                premium=premium,
                primary=False,
            )
        )

    feat_why = _reasons_for_line(line_n, features, premium)
    tiles.append(
        _decision_tile(
            recommendation=recommendation,
            risk_score=risk_score,
            primary_proba=primary_proba,
            primary_line=line_n,
            feature_reasons=feat_why,
        )
    )

    # Сортировка: первичный риск → остальные риски по вероятности → решение в конце
    primary = [t for t in tiles if t.get("primary")]
    risks = sorted(
        [t for t in tiles if t.get("category") != "decision" and not t.get("primary")],
        key=lambda t: t["match_pct"],
        reverse=True,
    )
    decisions = [t for t in tiles if t.get("category") == "decision"]
    ordered = primary + risks + decisions
    return ordered, probas, primary_proba


def recommend_from_signals(
    *,
    line: str,
    features: Dict[str, Any],
    risk_score: Optional[float] = None,
    recommendation: Optional[str] = None,
    fraud_signal: Optional[bool] = None,
    reasons: Optional[List[str]] = None,
    premium: Optional[float] = None,
    case_id: Optional[int] = None,
    title: str = "",
) -> Dict[str, Any]:
    line_n = (line or "auto").strip().lower()
    if line_n not in RISK_TAXONOMY:
        line_n = "auto"
    feats = dict(features or {})
    evaluated = risk.evaluate(line_n, feats)
    score = float(risk_score if risk_score is not None else evaluated["risk_score"])
    rec = (recommendation or evaluated["recommendation"] or "refer").strip().lower()
    fraud = bool(fraud_signal if fraud_signal is not None else evaluated.get("fraud_signal"))
    why = list(reasons or evaluated.get("reasons") or [])
    prem = float(premium if premium is not None else _safe_float(feats.get("premium"), 0) or 0)

    tiles, probas, primary_proba = _build_tiles(
        line=line_n,
        features=feats,
        risk_score=score,
        recommendation=rec,
        premium=prem,
    )

    # Решение привязываем к вероятности целевого класса EDA, если score не задан снаружи
    if primary_proba is not None and risk_score is None:
        blended = round(0.55 * score + 0.45 * (primary_proba * 100), 1)
        score = blended
        if blended >= 75:
            rec = "decline"
        elif blended >= 45:
            rec = "refer"
        else:
            rec = "approve"
        # Пересобрать decision-tile с обновлённым lean
        tiles, probas, primary_proba = _build_tiles(
            line=line_n,
            features=feats,
            risk_score=score,
            recommendation=rec,
            premium=prem,
        )

    meta = RISK_TAXONOMY[line_n]
    return {
        "case_id": case_id,
        "title": title,
        "line": line_n,
        "line_label": LINE_RU.get(line_n, line_n),
        "line_short": LINE_SHORT_RU.get(line_n, line_n),
        "risk_score": score,
        "recommendation": rec,
        "recommendation_label": REC_RU.get(rec, rec),
        "fraud_signal": fraud,
        "ml_proba": round(primary_proba, 4) if primary_proba is not None else None,
        "ml_probas": {
            k: (round(v, 4) if v is not None else None) for k, v in probas.items()
        },
        "engine": "ml+eda" if any(probas.values()) else evaluated.get("engine", "rules"),
        "key_factors": why,
        "recommendations": tiles,
        "taxonomy_legend": _taxonomy_legend(),
        "primary_risk": {
            "line": line_n,
            "target": meta["target"],
            "proba": round(primary_proba, 4) if primary_proba is not None else None,
            "label": meta["line_full"],
            "risk_question": meta["risk_question"],
        },
    }


def recommend_for_case(case: Any) -> Dict[str, Any]:
    feats = parse_json_obj(getattr(case, "raw_features", "{}"))
    prem = extract_premium(case, feats)
    return recommend_from_signals(
        line=getattr(case, "line", "auto") or "auto",
        features=feats,
        risk_score=getattr(case, "risk_score", None),
        recommendation=getattr(case, "recommendation", None),
        fraud_signal=getattr(case, "fraud_signal", None),
        reasons=parse_json_list(getattr(case, "key_factors", "[]")),
        premium=prem,
        case_id=getattr(case, "id", None),
        title=getattr(case, "title", "") or "",
    )


def recommend_for_profile(body: Dict[str, Any]) -> Dict[str, Any]:
    line = str(body.get("line") or "auto").strip().lower()
    feats = dict(body.get("features") or {})
    if body.get("premium") is not None:
        feats.setdefault("premium", body["premium"])
        feats.setdefault("PREMIUM", body["premium"])
        feats.setdefault("policy_annual_premium", body["premium"])
    risk_hint = _safe_float(body.get("risk_hint"))
    out = recommend_from_signals(
        line=line,
        features=feats,
        risk_score=risk_hint,
        premium=_safe_float(body.get("premium"), 0.0),
        title="Профиль",
    )
    return out
