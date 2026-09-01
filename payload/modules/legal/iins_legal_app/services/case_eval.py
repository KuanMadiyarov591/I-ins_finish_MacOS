"""Rule-based priority scoring for PI / IMR legal cases."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from iins_legal_app.config import get_settings


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
    return str(v).strip().lower() in {"1", "1.0", "true", "yes", "y", "t"}


def _clamp(score: float) -> float:
    return round(max(0.0, min(100.0, score)), 1)


def _recommend(score: float, hard_decline: bool = False) -> str:
    """Map priority score to accept | escalate | decline."""
    if hard_decline or score >= 78:
        return "decline"
    if score >= 48:
        return "escalate"
    return "accept"


def evaluate_pi(features: dict[str, Any]) -> dict[str, Any]:
    score = 20.0
    reasons: list[str] = []
    amount = _safe_float(features.get("amount"), 0.0)
    log_amount = _safe_float(features.get("log_amount"), 0.0)
    is_verdict = _truthy(features.get("is_verdict"))
    result_type = str(features.get("resultType") or features.get("result_type") or "")
    injury = str(features.get("injuryType") or features.get("injury_type") or "")
    practice = str(features.get("practiceArea") or features.get("practice_area") or "")
    year = _safe_int(features.get("year"), 2020)
    text_len = len(str(features.get("description") or ""))

    if is_verdict:
        score += 18
        reasons.append("Исход — вердикт суда (is_verdict)")
    if amount >= 5_000_000:
        score += 28
        reasons.append(f"Крупная сумма: {amount:,.0f}")
    elif amount >= 1_000_000:
        score += 18
        reasons.append(f"Существенная сумма: {amount:,.0f}")
    elif amount >= 250_000:
        score += 10
        reasons.append(f"Средняя сумма: {amount:,.0f}")
    if log_amount >= 15:
        score += 8
        reasons.append(f"log_amount={log_amount:.2f}")
    if "death" in injury.lower() or "wrongful" in injury.lower():
        score += 16
        reasons.append(f"Тяжёлая травма: {injury}")
    elif injury:
        score += 6
        reasons.append(f"Тип травмы: {injury}")
    if "malpractice" in practice.lower():
        score += 10
        reasons.append(f"Практика: {practice}")
    if result_type.lower() == "verdict":
        score += 6
        reasons.append("Тип результата: verdict")
    if year >= 2024:
        score += 4
        reasons.append(f"Свежий год: {year}")
    if text_len > 400:
        score += 4
        reasons.append("Развёрнутое описание дела")

    score = _clamp(score)
    hard = is_verdict and amount >= 50_000_000
    rec = _recommend(score, hard_decline=hard)
    if not reasons:
        reasons.append("Базовый PI-профиль без явных красных флагов")
    return {
        "risk_score": score,
        "recommendation": rec,
        "reasons": reasons,
        "urgency_signal": score >= 65 or amount >= 5_000_000,
        "fraud_signal": score >= 65,
        "engine": "rules_pi",
    }


def evaluate_imr(features: dict[str, Any]) -> dict[str, Any]:
    score = 22.0
    reasons: list[str] = []
    y_overturn = _truthy(features.get("y_overturn"))
    decision = str(features.get("decision") or "").lower()
    appeal_type = str(features.get("appeal_type") or "")
    text = str(features.get("text") or "")
    text_len = len(text)

    if y_overturn:
        score += 30
        reasons.append("Исторический overturn (y_overturn=1)")
    if "overturn" in decision:
        score += 18
        reasons.append(f"Решение: {decision}")
    elif "uphold" in decision or "deny" in decision:
        score += 8
        reasons.append(f"Решение: {decision}")
    if appeal_type:
        score += 6
        reasons.append(f"Тип апелляции: {appeal_type}")
        if any(k in appeal_type.lower() for k in ("experimental", "surgery", "transplant", "chemo")):
            score += 12
            reasons.append("Сложный клинический тип апелляции")
    if text_len >= 2500:
        score += 14
        reasons.append(f"Длинный текст апелляции ({text_len} симв.)")
    elif text_len >= 1200:
        score += 8
        reasons.append(f"Средний объём текста ({text_len} симв.)")
    if any(w in text.lower() for w in ("urgent", "emergency", "life-threatening", "срочно", "экстрен")):
        score += 10
        reasons.append("Маркеры срочности в тексте")

    score = _clamp(score)
    hard = y_overturn and text_len >= 3000
    rec = _recommend(score, hard_decline=hard)
    if not reasons:
        reasons.append("IMR-профиль без существенных отягощений")
    return {
        "risk_score": score,
        "recommendation": rec,
        "reasons": reasons,
        "urgency_signal": score >= 60 or y_overturn,
        "fraud_signal": score >= 60,
        "engine": "rules_imr",
    }


def evaluate(line: str, features: dict[str, Any]) -> dict[str, Any]:
    line_n = (line or "pi").strip().lower()
    if line_n == "imr":
        return evaluate_imr(features)
    return evaluate_pi(features)


def status() -> dict[str, Any]:
    model_dir: Path = get_settings().model_dir
    return {
        "ready": True,
        "engine": "deterministic_rules",
        "model_dir": str(model_dir),
        "lines": ["pi", "imr"],
    }
