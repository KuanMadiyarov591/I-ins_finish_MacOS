from __future__ import annotations

from pathlib import Path
from typing import Any

from iins_underwriter_app.config import get_settings

# Optional joblib model (Stage 1: rules are primary)
_MODEL = None
_MODEL_CHECKED = False


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        if v is None:
            return default
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _truthy(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    s = str(v).strip().lower()
    return s in {"1", "1.0", "true", "yes", "y", "t"}


def _clamp(score: float) -> float:
    return round(max(0.0, min(100.0, score)), 1)


def _recommend(score: float, hard_decline: bool = False) -> str:
    if hard_decline or score >= 75:
        return "decline"
    if score >= 45:
        return "refer"
    return "approve"


def _load_optional_model() -> Any:
    global _MODEL, _MODEL_CHECKED
    if _MODEL_CHECKED:
        return _MODEL
    _MODEL_CHECKED = True
    path = get_settings().model_dir / "risk_rules_boost.joblib"
    if not path.is_file():
        return None
    try:
        import joblib

        _MODEL = joblib.load(path)
    except Exception:  # noqa: BLE001
        _MODEL = None
    return _MODEL


def evaluate_auto(features: dict[str, Any]) -> dict[str, Any]:
    score = 18.0
    reasons: list[str] = []

    violations = _safe_int(features.get("SPEEDING_VIOLATIONS") or features.get("speeding_violations"))
    duis = _safe_int(features.get("DUIS") or features.get("duis"))
    accidents = _safe_int(features.get("PAST_ACCIDENTS") or features.get("past_accidents"))
    credit = _safe_float(features.get("CREDIT_SCORE") or features.get("credit_score"), 0.5)
    mileage = _safe_float(features.get("ANNUAL_MILEAGE") or features.get("annual_mileage"), 12000)
    outcome = _safe_float(features.get("OUTCOME") or features.get("outcome"), 0.0)
    age_raw = str(features.get("AGE") or features.get("age") or "")
    vehicle_year = str(features.get("VEHICLE_YEAR") or features.get("vehicle_year") or "")
    ownership = _safe_float(features.get("VEHICLE_OWNERSHIP") or features.get("vehicle_ownership"), 1.0)

    if violations >= 1:
        score += min(28, violations * 9)
        reasons.append(f"Нарушения скорости: {violations}")
    if duis >= 1:
        score += min(35, duis * 22)
        reasons.append(f"Вождение в нетрезвом виде: {duis}")
    if accidents >= 1:
        score += min(30, accidents * 12)
        reasons.append(f"Прошлые ДТП: {accidents}")
    if credit < 0.35:
        score += 18
        reasons.append(f"Низкий кредитный балл ({credit:.2f})")
    elif credit < 0.5:
        score += 8
        reasons.append(f"Умеренный кредитный балл ({credit:.2f})")
    if mileage >= 20000:
        score += 12
        reasons.append(f"Высокий пробег: {int(mileage)}")
    elif mileage >= 15000:
        score += 6
        reasons.append(f"Повышенный пробег: {int(mileage)}")
    if age_raw in {"16-25", "16–25"}:
        score += 14
        reasons.append("Молодой водитель (16–25)")
    if vehicle_year.lower().startswith("before"):
        score += 7
        reasons.append("ТС личного авто до 2015 года")
    if ownership < 0.5:
        score += 5
        reasons.append("Нет владения ТС")
    if outcome >= 1:
        score += 10
        reasons.append("Исторический убыток по исходу")

    hard = duis >= 2 or (duis >= 1 and accidents >= 2)
    score = _clamp(score)
    rec = _recommend(score, hard_decline=hard)
    if not reasons:
        reasons.append("Базовый профиль без явных красных флагов")
    return {
        "risk_score": score,
        "recommendation": rec,
        "reasons": reasons,
        "fraud_signal": False,
        "engine": "rules_auto",
    }


def evaluate_fraud(features: dict[str, Any]) -> dict[str, Any]:
    score = 22.0
    reasons: list[str] = []
    fraud = _truthy(features.get("fraud_reported"))
    severity = str(features.get("incident_severity") or "").lower()
    police = str(features.get("police_report_available") or "").upper()
    property_damage = str(features.get("property_damage") or "").upper()
    witnesses = _safe_int(features.get("witnesses"))
    vehicles = _safe_int(features.get("number_of_vehicles_involved"), 1)
    bodily = _safe_int(features.get("bodily_injuries"))
    umbrella = _safe_float(features.get("umbrella_limit"))
    premium = _safe_float(features.get("policy_annual_premium"), 1000)
    months = _safe_int(features.get("months_as_customer"), 100)
    incident_type = str(features.get("incident_type") or "")

    if fraud:
        score += 40
        reasons.append("Маркер мошенничества в данных")
    if "major" in severity:
        score += 18
        reasons.append(f"Тяжесть инцидента: {severity or 'major'}")
    elif "total" in severity:
        score += 22
        reasons.append(f"Тяжесть инцидента: {severity}")
    if police in {"?", "NO", "N"}:
        score += 12
        reasons.append("Нет / неизвестен отчёт полиции")
    if property_damage in {"?", "YES", "Y"} and police in {"?", "NO", "N"}:
        score += 8
        reasons.append("Повреждение имущества без подтверждённого отчёта")
    if witnesses == 0:
        score += 10
        reasons.append("Нет свидетелей")
    if vehicles >= 3:
        score += 8
        reasons.append(f"Много ТС в инциденте: {vehicles}")
    if bodily >= 2:
        score += 7
        reasons.append(f"Телесные повреждения: {bodily}")
    if months < 12:
        score += 14
        reasons.append(f"Короткий срок клиента: {months} мес.")
    elif months < 36:
        score += 6
        reasons.append(f"Относительно новый клиент: {months} мес.")
    if umbrella >= 5_000_000 and premium < 900:
        score += 9
        reasons.append("Высокий лимит umbrella при низкой премии")
    if "theft" in incident_type.lower():
        score += 6
        reasons.append(f"Тип инцидента: {incident_type}")

    score = _clamp(score)
    hard = fraud and ("major" in severity or witnesses == 0)
    rec = _recommend(score, hard_decline=hard)
    if not reasons:
        reasons.append("Признаков мошенничества не выявлено")
    return {
        "risk_score": score,
        "recommendation": rec,
        "reasons": reasons,
        "fraud_signal": fraud or score >= 60,
        "engine": "rules_fraud",
    }


def evaluate_motor(features: dict[str, Any]) -> dict[str, Any]:
    score = 20.0
    reasons: list[str] = []
    has_claim = _truthy(features.get("has_claim"))
    premium = _safe_float(features.get("PREMIUM") or features.get("premium"))
    insured = _safe_float(features.get("INSURED_VALUE") or features.get("insured_value"), 100000)
    vehicle_age = _safe_float(features.get("vehicle_age"), 5)
    usage = str(features.get("USAGE") or features.get("usage") or "")
    type_vehicle = str(features.get("TYPE_VEHICLE") or features.get("type_vehicle") or "")
    claim_paid = _safe_float(features.get("CLAIM_PAID") or features.get("claim_paid"), 0)
    seats = _safe_float(features.get("SEATS_NUM") or features.get("seats_num"), 4)
    ccm = _safe_float(features.get("CCM_TON") or features.get("ccm_ton"), 0)

    if has_claim:
        score += 28
        reasons.append("Есть история убытка")
    if claim_paid > 0:
        score += min(20, 8 + claim_paid / max(insured, 1) * 40)
        reasons.append(f"Выплата по убытку: {claim_paid:.0f}")
    if vehicle_age >= 15:
        score += 14
        reasons.append(f"Возраст ТС: {vehicle_age:.0f} лет")
    elif vehicle_age >= 10:
        score += 8
        reasons.append(f"Возраст ТС: {vehicle_age:.0f} лет")
    if usage.lower() in {"general cartage", "own goods", "taxi", "hire"}:
        score += 12
        reasons.append(f"Коммерческое использование: {usage}")
    if type_vehicle.lower() in {"truck", "bus"}:
        score += 10
        reasons.append(f"Тип ТС: {type_vehicle}")
    if premium > 0 and insured > 0 and premium / insured > 0.08:
        score += 9
        reasons.append("Высокое отношение премии к страховой сумме")
    if ccm >= 3000:
        score += 7
        reasons.append(f"Высокий объём/тоннаж: {ccm:.0f}")
    if seats >= 8:
        score += 6
        reasons.append(f"Много мест: {seats:.0f}")

    score = _clamp(score)
    hard = has_claim and claim_paid > insured * 0.5 and vehicle_age >= 12
    rec = _recommend(score, hard_decline=hard)
    if not reasons:
        reasons.append("Профиль парка ТС: без существенных отягощений")
    return {
        "risk_score": score,
        "recommendation": rec,
        "reasons": reasons,
        "fraud_signal": False,
        "engine": "rules_motor",
    }


def evaluate(line: str, features: dict[str, Any]) -> dict[str, Any]:
    line_n = (line or "auto").strip().lower()
    if line_n == "fraud":
        result = evaluate_fraud(features)
    elif line_n == "motor":
        result = evaluate_motor(features)
    else:
        result = evaluate_auto(features)

    # Optional light model nudge (±8) if present
    model = _load_optional_model()
    if model is not None:
        try:
            x = [[
                result["risk_score"],
                1.0 if result["fraud_signal"] else 0.0,
                len(result["reasons"]),
            ]]
            pred = float(model.predict_proba(x)[0][1]) * 100.0
            blended = _clamp(0.85 * result["risk_score"] + 0.15 * pred)
            result["risk_score"] = blended
            result["recommendation"] = _recommend(blended, hard_decline=result["recommendation"] == "decline")
            result["engine"] = result["engine"] + "+sklearn"
        except Exception:  # noqa: BLE001
            pass
    return result


def status() -> dict[str, Any]:
    model_path: Path = get_settings().model_dir / "risk_rules_boost.joblib"
    model = _load_optional_model()
    return {
        "ready": True,
        "engine": "deterministic_rules",
        "optional_model": model is not None,
        "model_path": str(model_path) if model_path.is_file() else None,
        "lines": ["auto", "fraud", "motor"],
    }
