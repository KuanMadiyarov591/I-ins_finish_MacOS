from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Dict, List, Optional

import joblib
import pandas as pd

from iins_actuary_app.config import get_settings
from iins_actuary_app.models import PremiumCase

FEATURE_COLS = [
    "ypc",
    "fixed_expenses",
    "age",
    "indicated_premium",
    "territory",
    "gender",
    "cgr",
]
TARGET = "selected_premium"
LEAKAGE_COLS = {"current_premium"}


def _f(code: str, **params: Any) -> Dict[str, Any]:
    item: Dict[str, Any] = {"code": code}
    if params:
        item["params"] = params
    return item


def _fmt_num(v: Any) -> str:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return str(v)
    if abs(n - round(n)) < 1e-9:
        return str(int(round(n)))
    return f"{n:.2f}"


@lru_cache(maxsize=1)
def _bundle() -> Optional[dict]:
    path = get_settings().model_dir / "selected_premium.joblib"
    if not path.is_file():
        return None
    try:
        return joblib.load(path)
    except Exception:  # noqa: BLE001
        return None


def reload_model() -> None:
    _bundle.cache_clear()


def status() -> Dict[str, Any]:
    b = _bundle()
    metrics_path = get_settings().model_dir / "metrics.json"
    metrics = {}
    if metrics_path.is_file():
        try:
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            metrics = {}
    return {
        "models_loaded": bool(b),
        "target": TARGET,
        "features": (b or {}).get("features") or FEATURE_COLS,
        "excluded_leakage": sorted(LEAKAGE_COLS),
        "estimator": (b or {}).get("estimator"),
        "metrics": metrics,
    }


def _case_features(c: PremiumCase, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    raw = {}
    try:
        raw = json.loads(c.raw_features or "{}")
    except Exception:  # noqa: BLE001
        raw = {}
    base = {
        "ypc": float(overrides.get("ypc") if overrides and overrides.get("ypc") is not None else c.ypc or 0),
        "fixed_expenses": float(
            overrides.get("fixed_expenses")
            if overrides and overrides.get("fixed_expenses") is not None
            else c.fixed_expenses or 0
        ),
        "age": float(overrides.get("age") if overrides and overrides.get("age") is not None else c.age or 40),
        "indicated_premium": float(
            overrides.get("indicated_premium")
            if overrides and overrides.get("indicated_premium") is not None
            else c.indicated_premium or 0
        ),
        "territory": str(
            overrides.get("territory") if overrides and overrides.get("territory") else c.territory or ""
        ),
        "gender": str(overrides.get("gender") if overrides and overrides.get("gender") else c.gender or "M"),
        "cgr": str(overrides.get("cgr") if overrides and overrides.get("cgr") else c.cgr or ""),
        "selected_premium": float(c.selected_premium or 0),
        "current_premium": float(c.current_premium or 0),
    }
    # merge extra features but strip leakage
    for k, v in (overrides or {}).get("features", {}).items():
        if k in LEAKAGE_COLS:
            continue
        base[k] = v
    for k in LEAKAGE_COLS:
        # keep current_premium only for display, never in model frame
        pass
    raw.update({k: base[k] for k in FEATURE_COLS})
    return base


def _profile_features(payload: Dict[str, Any]) -> Dict[str, Any]:
    feats = dict(payload.get("features") or {})
    out = {
        "ypc": float(payload.get("ypc") if payload.get("ypc") is not None else feats.get("ypc") or 0),
        "fixed_expenses": float(
            payload.get("fixed_expenses")
            if payload.get("fixed_expenses") is not None
            else feats.get("fixed_expenses") or 150
        ),
        "age": float(payload.get("age") if payload.get("age") is not None else feats.get("age") or 40),
        "indicated_premium": float(
            payload.get("indicated_premium")
            if payload.get("indicated_premium") is not None
            else feats.get("indicated_premium") or 800
        ),
        "territory": str(payload.get("territory") or feats.get("territory") or "601"),
        "gender": str(payload.get("gender") or feats.get("gender") or "M"),
        "cgr": str(payload.get("cgr") or feats.get("cgr") or "ZHK"),
    }
    return out


def _predict(features: Dict[str, Any]) -> Dict[str, Any]:
    b = _bundle()
    frame = pd.DataFrame([{c: features.get(c) for c in FEATURE_COLS}])
    # ensure dtypes
    for col in ("ypc", "fixed_expenses", "age", "indicated_premium"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    for col in ("territory", "gender", "cgr"):
        frame[col] = frame[col].astype(str)

    indicated = float(features.get("indicated_premium") or 0)
    if not b:
        # heuristic fallback without leakage
        pred = indicated * (1.0 + 0.01 * (float(features.get("ypc") or 0) - 2.5))
        pred = max(1.0, pred)
        factors = [
            _f("factor_no_model"),
            _f("factor_heuristic"),
            _f("factor_leakage_excluded", name="current_premium"),
            _f("factor_feature", name="territory", value=features.get("territory")),
            _f("factor_feature", name="cgr", value=features.get("cgr")),
            _f("factor_pred_selected", value=_fmt_num(pred)),
            _f("factor_indicated", value=_fmt_num(indicated)),
            _f("factor_gap", value=_fmt_num(pred - indicated)),
        ]
        return {
            "predicted_selected_premium": round(pred, 2),
            "indicated_premium": round(indicated, 2),
            "gap": round(pred - indicated, 2),
            "factors": factors,
            "factors_text": [],
            "decision": "heuristic",
            "model_used": False,
        }

    pipe = b["pipeline"]
    pred = float(pipe.predict(frame)[0])
    gap = pred - indicated
    factors = _explain(features, pred, indicated, b)
    return {
        "predicted_selected_premium": round(pred, 2),
        "indicated_premium": round(indicated, 2),
        "gap": round(gap, 2),
        "factors": factors,
        "factors_text": [],
        "decision": "model",
        "model_used": True,
        "estimator": b.get("estimator"),
    }


def _explain(features: Dict[str, Any], pred: float, indicated: float, bundle: dict) -> List[Dict[str, Any]]:
    gap = pred - indicated
    factors: List[Dict[str, Any]] = []
    est = bundle.get("estimator")
    if est:
        factors.append(_f("factor_estimator", name=est))
    factors.extend(
        [
            _f("factor_pred_selected", value=_fmt_num(pred)),
            _f("factor_indicated", value=_fmt_num(indicated)),
            _f("factor_gap", value=_fmt_num(gap)),
            _f("factor_feature", name="age", value=features.get("age")),
            _f("factor_feature", name="ypc", value=features.get("ypc")),
            _f("factor_feature", name="fixed_expenses", value=features.get("fixed_expenses")),
            _f("factor_feature", name="territory", value=features.get("territory")),
            _f("factor_feature", name="gender", value=features.get("gender")),
            _f("factor_feature", name="cgr", value=features.get("cgr")),
            _f("factor_leakage_excluded", name="current_premium"),
        ]
    )
    return factors


def recommend_for_case(c: PremiumCase, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    feats = _case_features(c, overrides)
    result = _predict(feats)
    priority = None
    if overrides and overrides.get("priority") is not None:
        priority = overrides.get("priority")
    row = {
        "case_id": c.id,
        "external_id": c.external_id,
        "territory": feats["territory"],
        "gender": feats["gender"],
        "cgr": feats["cgr"],
        "age": feats["age"],
        "ypc": feats["ypc"],
        "fixed_expenses": feats["fixed_expenses"],
        "priority": priority,
        "actual_selected_premium": round(float(c.selected_premium or 0), 2),
        **result,
    }
    return {
        "case_id": c.id,
        "rows": [row],
        "results": [row],
        "target": TARGET,
        "features_used": FEATURE_COLS,
    }


def recommend_for_profile(payload: Dict[str, Any]) -> Dict[str, Any]:
    feats = _profile_features(payload)
    result = _predict(feats)
    row = {
        "case_id": None,
        "external_id": "PROFILE",
        "territory": feats["territory"],
        "gender": feats["gender"],
        "cgr": feats["cgr"],
        "age": feats["age"],
        "ypc": feats["ypc"],
        "fixed_expenses": feats["fixed_expenses"],
        "priority": payload.get("priority"),
        "actual_selected_premium": None,
        **result,
    }
    return {
        "case_id": None,
        "rows": [row],
        "results": [row],
        "target": TARGET,
        "features_used": FEATURE_COLS,
    }
