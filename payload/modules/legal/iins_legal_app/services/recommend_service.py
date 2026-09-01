"""Рекомендации юриста: PI is_verdict (+ amount hint) и IMR y_overturn."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from iins_legal_app.config import get_settings
from iins_legal_app.services import case_eval as evalsvc
from iins_legal_app.services.case_helpers import extract_amount, parse_json_list, parse_json_obj

LINE_RU = {
    "pi": "Телесный вред · вердикт",
    "imr": "IMR · overturn",
}
LINE_SHORT_RU = {"pi": "Телесный вред", "imr": "IMR"}
REC_RU = {"accept": "Принять", "escalate": "Эскалировать", "decline": "Отклонить"}

RISK_TAXONOMY: Dict[str, Dict[str, Any]] = {
    "pi": {
        "model_key": "pi",
        "target": "is_verdict",
        "line_short": "Телесный вред",
        "line_full": "Телесный вред · вероятность вердикта",
        "risk_question": "Какова вероятность судебного вердикта (is_verdict)?",
        "title_base": "Телесный вред · вердикт",
        "category": "pi_verdict",
        "category_label": "Телесный вред · вердикт",
        "definition": "Вероятность исхода verdict (is_verdict=1) по делу о телесном вреде.",
        "eda_note": "Personal injury verdict propensity",
        "grade": "A",
        "feature_hints": ["сумма / log_amount", "тип травмы", "практика", "штат", "год", "resultType"],
        "feature_keys": (
            "amount", "log_amount", "injuryType", "practiceArea", "state", "year",
            "resultType", "is_verdict", "county", "description",
        ),
    },
    "imr": {
        "model_key": "imr",
        "target": "y_overturn",
        "line_short": "IMR",
        "line_full": "IMR · вероятность overturn",
        "risk_question": "Какова вероятность overturn по апелляции IMR?",
        "title_base": "IMR · overturn",
        "category": "imr_overturn",
        "category_label": "IMR · overturn",
        "definition": "Вероятность отмены отказа страховщика (y_overturn) по IMR-апелляции.",
        "eda_note": "IMR health appeal overturn",
        "grade": "B",
        "feature_hints": ["appeal_type", "длина текста", "decision", "клинические маркеры"],
        "feature_keys": ("appeal_type", "text", "text_len", "decision", "y_overturn"),
    },
}

_MODELS: Dict[str, Any] = {}
_MODELS_CHECKED = False
_METRICS: Dict[str, Any] = {}


def _taxonomy_legend() -> List[Dict[str, Any]]:
    return [
        {
            "id": lid,
            "label": meta["line_full"],
            "label_short": meta["line_short"],
            "target": meta["target"],
            "meaning": meta["definition"],
            "eda_note": meta.get("eda_note", ""),
            "grade": meta.get("grade", ""),
        }
        for lid, meta in RISK_TAXONOMY.items()
    ]


def _model_files() -> Dict[str, Path]:
    d = get_settings().model_dir
    return {
        "pi": d / "pi_verdict.joblib",
        "imr": d / "imr_overturn.joblib",
        "pi_amount": d / "pi_amount.joblib",
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
        "fallback": "case_eval",
    }


def _safe_float(v: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


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
            val = features.get(name)
            if name == "text_len" and val is None:
                val = len(str(features.get("text") or ""))
            if name == "text" and val is not None:
                val = str(val)[:4000]
            row[name] = val
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


def _predict_amount_hint(features: Dict[str, Any]) -> Optional[float]:
    models = _load_models()
    bundle = models.get("pi_amount")
    if not bundle:
        log_a = _safe_float(_feat(features, "log_amount"))
        if log_a is not None and log_a > 0:
            return math.exp(log_a)
        return _safe_float(_feat(features, "amount"))
    pipe = bundle.get("pipeline") if isinstance(bundle, dict) else bundle
    feat_names = bundle.get("features") if isinstance(bundle, dict) else None
    if pipe is None:
        return None
    row = {name: features.get(name) for name in (feat_names or [])}
    try:
        X = pd.DataFrame([row])
        if feat_names:
            X = X.reindex(columns=feat_names)
        pred_log = float(pipe.predict(X)[0])
        return math.exp(max(0.0, pred_log))
    except Exception:  # noqa: BLE001
        log_a = _safe_float(_feat(features, "log_amount"))
        return math.exp(log_a) if log_a else None


def _heuristic_proba(line: str, features: Dict[str, Any], risk_score: float) -> float:
    base = max(0.05, min(0.95, risk_score / 100.0))
    if line == "pi":
        is_v = str(_feat(features, "is_verdict") or "").lower() in {"1", "1.0", "true"}
        amount = _safe_float(_feat(features, "amount"), 0.0) or 0.0
        injury = str(_feat(features, "injuryType") or "").lower()
        bump = 0.2 if is_v else 0.08
        if amount >= 1_000_000:
            bump += 0.15
        if "death" in injury:
            bump += 0.12
        return max(0.05, min(0.95, 0.45 * base + bump))
    # imr
    y = str(_feat(features, "y_overturn") or "").lower() in {"1", "1.0", "true"}
    text_len = _safe_float(_feat(features, "text_len"), len(str(_feat(features, "text") or ""))) or 0
    appeal = str(_feat(features, "appeal_type") or "").lower()
    bump = 0.25 if y else 0.1
    if text_len >= 2000:
        bump += 0.12
    if any(k in appeal for k in ("surgery", "experimental", "transplant")):
        bump += 0.1
    return max(0.05, min(0.95, 0.4 * base + bump))


def _pi_reasons(features: Dict[str, Any]) -> List[str]:
    why: List[str] = []
    for key, label in (
        ("amount", "сумма"),
        ("log_amount", "log_amount"),
        ("injuryType", "травма"),
        ("practiceArea", "практика"),
        ("state", "штат"),
        ("year", "год"),
        ("resultType", "результат"),
        ("is_verdict", "вердикт"),
    ):
        v = _feat(features, key)
        if v is not None:
            if key == "amount":
                why.append(f"{key} = {_fmt_num(float(v))} ({label})")
            else:
                why.append(f"{key} = {v} ({label})")
    return why


def _imr_reasons(features: Dict[str, Any]) -> List[str]:
    why: List[str] = []
    for key, label in (
        ("appeal_type", "тип апелляции"),
        ("decision", "решение"),
        ("y_overturn", "overturn"),
        ("text_len", "длина текста"),
    ):
        v = _feat(features, key)
        if v is None and key == "text_len":
            v = len(str(_feat(features, "text") or ""))
        if v is not None:
            why.append(f"{key} = {v} ({label})")
    return why


def _reasons_for_line(line: str, features: Dict[str, Any]) -> List[str]:
    why = _pi_reasons(features) if line == "pi" else _imr_reasons(features)
    out: List[str] = []
    for r in why:
        if r and r not in out:
            out.append(r)
        if len(out) >= 5:
            break
    return out


def _resolve_proba(line: str, features: Dict[str, Any], risk_score: float) -> Tuple[float, str]:
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
    primary: bool,
    amount_hint: Optional[float] = None,
) -> Dict[str, Any]:
    meta = RISK_TAXONOMY[line]
    pct = max(1, min(99, int(round(proba * 100))))
    reasons = _reasons_for_line(line, features) or [f"Цель EDA: {meta['target']}"]
    if source == "model":
        reasons = [f"Модель по цели «{meta['target']}»"] + reasons
    else:
        reasons = [f"Оценка по признакам (цель «{meta['target']}»)"] + reasons
    if line == "pi" and amount_hint:
        reasons = [f"Оценка суммы (hint): {_fmt_num(amount_hint)}"] + reasons
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
    if amount_hint is not None and line == "pi":
        tile["amount_hint"] = round(amount_hint, 2)
    return tile


def _decision_tile(
    *,
    recommendation: str,
    risk_score: float,
    primary_proba: float,
    primary_line: str,
    feature_reasons: List[str],
) -> Dict[str, Any]:
    lean = recommendation if recommendation in REC_RU else "escalate"
    titles = {
        "accept": "Склоняться к принятию",
        "escalate": "Направить на эскалацию",
        "decline": "Склоняться к отказу",
    }
    if lean == "decline":
        match = int(round(40 + primary_proba * 55))
    elif lean == "accept":
        match = int(round(40 + (1.0 - primary_proba) * 55))
    else:
        match = int(round(50 + (1.0 - abs(primary_proba - 0.5) * 2) * 25))
    match = max(8, min(99, match))
    meta = RISK_TAXONOMY[primary_line]
    why = [
        f"Вероятность «{meta['target']}» ({meta['line_short']}) = {primary_proba * 100:.0f}%",
        f"Приоритет-скор: {risk_score:.0f}",
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
        "target": meta["target"],
    }


def _build_tiles(
    *,
    line: str,
    features: Dict[str, Any],
    risk_score: float,
    recommendation: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, Optional[float]], Optional[float]]:
    line_n = line if line in RISK_TAXONOMY else "pi"
    primary_proba, primary_src = _resolve_proba(line_n, features, risk_score)
    amount_hint = _predict_amount_hint(features) if line_n == "pi" else None
    tiles: List[Dict[str, Any]] = [
        _risk_tile(
            line=line_n,
            proba=primary_proba,
            source=primary_src,
            features=features,
            primary=True,
            amount_hint=amount_hint,
        )
    ]
    # Secondary line only if model available and some feature overlap
    other = "imr" if line_n == "pi" else "pi"
    other_p = _predict_line_proba(other, features)
    if other_p is not None:
        tiles.append(
            _risk_tile(
                line=other,
                proba=other_p,
                source="model",
                features=features,
                primary=False,
            )
        )
    feat_why = _reasons_for_line(line_n, features)
    tiles.append(
        _decision_tile(
            recommendation=recommendation,
            risk_score=risk_score,
            primary_proba=primary_proba,
            primary_line=line_n,
            feature_reasons=feat_why,
        )
    )
    primary = [t for t in tiles if t.get("primary")]
    risks = sorted(
        [t for t in tiles if t.get("category") != "decision" and not t.get("primary")],
        key=lambda t: t["match_pct"],
        reverse=True,
    )
    decisions = [t for t in tiles if t.get("category") == "decision"]
    return primary + risks + decisions, {line_n: primary_proba, other: other_p}, primary_proba


def recommend_from_signals(
    *,
    line: str,
    features: Dict[str, Any],
    risk_score: Optional[float] = None,
    recommendation: Optional[str] = None,
    urgency_signal: Optional[bool] = None,
    reasons: Optional[List[str]] = None,
    amount: Optional[float] = None,
    case_id: Optional[int] = None,
    title: str = "",
) -> Dict[str, Any]:
    line_n = (line or "pi").strip().lower()
    if line_n not in RISK_TAXONOMY:
        line_n = "pi"
    feats = dict(features or {})
    evaluated = evalsvc.evaluate(line_n, feats)
    score = float(risk_score if risk_score is not None else evaluated["risk_score"])
    rec = (recommendation or evaluated["recommendation"] or "escalate").strip().lower()
    # Normalize UW aliases
    if rec == "approve":
        rec = "accept"
    if rec == "refer":
        rec = "escalate"
    urgency = bool(urgency_signal if urgency_signal is not None else evaluated.get("urgency_signal"))
    why = list(reasons or evaluated.get("reasons") or [])

    tiles, probas, primary_proba = _build_tiles(
        line=line_n,
        features=feats,
        risk_score=score,
        recommendation=rec,
    )

    if primary_proba is not None and risk_score is None:
        blended = round(0.55 * score + 0.45 * (primary_proba * 100), 1)
        score = blended
        if blended >= 75:
            rec = "decline"
        elif blended >= 45:
            rec = "escalate"
        else:
            rec = "accept"
        tiles, probas, primary_proba = _build_tiles(
            line=line_n,
            features=feats,
            risk_score=score,
            recommendation=rec,
        )

    meta = RISK_TAXONOMY[line_n]
    if amount is not None:
        amt = amount
    else:
        from math import exp

        raw_amt = _safe_float(feats.get("amount"), 0.0) or 0.0
        log_a = _safe_float(feats.get("log_amount"), 0.0) or 0.0
        if raw_amt > 0:
            amt = raw_amt
        elif log_a > 0:
            amt = exp(log_a)
        else:
            amt = 0.0
    return {
        "case_id": case_id,
        "title": title,
        "line": line_n,
        "line_label": LINE_RU.get(line_n, line_n),
        "line_short": LINE_SHORT_RU.get(line_n, line_n),
        "risk_score": score,
        "recommendation": rec,
        "recommendation_label": REC_RU.get(rec, rec),
        "urgency_signal": urgency,
        "fraud_signal": urgency,
        "amount": amt,
        "ml_proba": round(primary_proba, 4) if primary_proba is not None else None,
        "ml_probas": {k: (round(v, 4) if v is not None else None) for k, v in probas.items()},
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
    amt = extract_amount(case, feats)
    return recommend_from_signals(
        line=getattr(case, "line", "pi") or "pi",
        features=feats,
        risk_score=getattr(case, "risk_score", None),
        recommendation=getattr(case, "recommendation", None),
        urgency_signal=getattr(case, "urgency_signal", None),
        reasons=parse_json_list(getattr(case, "key_factors", "[]")),
        amount=amt,
        case_id=getattr(case, "id", None),
        title=getattr(case, "title", "") or "",
    )


def recommend_for_profile(body: Dict[str, Any]) -> Dict[str, Any]:
    line = str(body.get("line") or "pi").strip().lower()
    feats = dict(body.get("features") or {})
    if body.get("amount") is not None:
        feats.setdefault("amount", body["amount"])
    if body.get("premium") is not None:
        feats.setdefault("amount", body["premium"])
    if body.get("appeal_type"):
        feats.setdefault("appeal_type", body["appeal_type"])
    if body.get("text"):
        feats.setdefault("text", body["text"])
        feats.setdefault("text_len", len(str(body["text"])))
    risk_hint = _safe_float(body.get("risk_hint"))
    return recommend_from_signals(
        line=line,
        features=feats,
        risk_score=risk_hint,
        amount=_safe_float(body.get("amount") or body.get("premium"), 0.0),
        title="Профиль",
    )
