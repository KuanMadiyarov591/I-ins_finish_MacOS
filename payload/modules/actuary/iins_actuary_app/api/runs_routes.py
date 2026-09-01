from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from iins_actuary_app.auth import require_actuary, require_admin
from iins_actuary_app.config import ROOT, get_settings
from iins_actuary_app.models import User

router = APIRouter(prefix="/api/runs", tags=["runs"])


def _metrics_path() -> Path:
    return get_settings().model_dir / "metrics.json"


def _load_metrics() -> Dict[str, Any]:
    path = _metrics_path()
    if not path.is_file():
        return {"models": [], "ready": False}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["ready"] = True
        data["path"] = str(path.relative_to(ROOT)).replace("\\", "/")
        return data
    except Exception as exc:  # noqa: BLE001
        return {"models": [], "ready": False, "error": str(exc)}


@router.get("/status")
def runs_status(_: User = Depends(require_actuary)) -> Dict[str, Any]:
    settings = get_settings()
    model_file = settings.model_dir / "selected_premium.joblib"
    metrics = _load_metrics()
    return {
        "model_ready": model_file.is_file(),
        "model_path": str(model_file.relative_to(ROOT)).replace("\\", "/") if model_file.is_file() else None,
        "metrics": metrics,
        "leaderboard": metrics.get("models") or metrics.get("leaderboard") or [],
    }


@router.post("/retrain")
def retrain(user: User = Depends(require_admin)) -> Dict[str, Any]:
    script = ROOT / "scripts" / "train_actuary_recommender.py"
    if not script.is_file():
        raise HTTPException(status_code=500, detail="Скрипт обучения не найден")
    try:
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail="Обучение превысило лимит времени") from exc
    if proc.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка обучения: {(proc.stderr or proc.stdout or '')[-800:]}",
        )
    return {
        "ok": True,
        "by": user.username,
        "stdout": (proc.stdout or "")[-1200:],
        "status": runs_status(user),
    }
