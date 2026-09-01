"""Маршруты аналитических отчётов кабинета актуария."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from iins_actuary_app.auth import require_actuary
from iins_actuary_app.db import get_db
from iins_actuary_app.models import User
from iins_actuary_app.services import report_service

router = APIRouter(prefix="/api/report", tags=["report"])


class BuildIn(BaseModel):
    kind: str = Field(min_length=2, max_length=32)
    mode: str = Field(default="auto", pattern="^(auto|extractive|ollama|qwen|gigachat)$")


@router.get("/kinds")
def report_kinds(_: User = Depends(require_actuary)) -> Dict[str, Any]:
    return {"kinds": report_service.available_kinds(), "recent": report_service.recent()}


@router.post("/build")
def report_build(
    body: BuildIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_actuary),
) -> Dict[str, Any]:
    try:
        return report_service.build(body.kind, db, mode=body.mode, author=user.username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Ошибка построения отчёта: {exc}") from exc


@router.get("/recent")
def report_recent(_: User = Depends(require_actuary)) -> Dict[str, List[Dict[str, Any]]]:
    return {"recent": report_service.recent()}


@router.get("/{report_id}.pdf")
def report_pdf(report_id: str, _: User = Depends(require_actuary)) -> FileResponse:
    try:
        path = report_service.report_path(report_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=f"{report_id}.pdf",
        content_disposition_type="inline",
    )
