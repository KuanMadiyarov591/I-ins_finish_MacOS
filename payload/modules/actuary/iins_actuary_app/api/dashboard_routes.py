from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from iins_actuary_app.auth import require_actuary
from iins_actuary_app.config import get_settings
from iins_actuary_app.db import get_db
from iins_actuary_app.models import CgrDefinition, PremiumCase, TerritoryDefinition, User

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _load_metrics() -> Dict[str, Any]:
    path = get_settings().model_dir / "metrics.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


@router.get("/summary")
def dashboard_summary(
    db: Session = Depends(get_db),
    user: User = Depends(require_actuary),
) -> Dict[str, Any]:
    n_premiums = db.query(PremiumCase).count()
    n_territories = db.query(func.count(func.distinct(PremiumCase.territory))).scalar() or 0
    n_cgr = db.query(func.count(func.distinct(PremiumCase.cgr))).scalar() or 0
    n_cgr_defs = db.query(CgrDefinition).count()
    n_terr_defs = db.query(TerritoryDefinition).count()

    metrics = _load_metrics()
    primary = None
    models = metrics.get("models") or []
    if models:
        primary = models[0]
    elif metrics.get("primary"):
        primary = metrics["primary"]

    mae = None
    r2 = None
    train_rows = None
    model_name = None
    if isinstance(primary, dict):
        mae = primary.get("mae")
        r2 = primary.get("r2")
        train_rows = primary.get("n_rows")
        model_name = primary.get("estimator") or primary.get("name")

    avg_selected = db.query(func.avg(PremiumCase.selected_premium)).scalar() or 0.0
    avg_indicated = db.query(func.avg(PremiumCase.indicated_premium)).scalar() or 0.0

    return {
        "kpis": {
            "n_premiums_sample": n_premiums,
            "mae": mae,
            "r2": r2,
            "territories_count": int(n_territories),
            "cgr_count": int(n_cgr),
            "cgr_definitions": n_cgr_defs,
            "territory_definitions": n_terr_defs,
            "train_rows": train_rows,
            "model_name": model_name,
            "avg_selected_premium": round(float(avg_selected), 2),
            "avg_indicated_premium": round(float(avg_indicated), 2),
        },
        "metrics": metrics,
        "model_ready": Path(get_settings().model_dir / "selected_premium.joblib").is_file(),
        "user": user.username,
    }
