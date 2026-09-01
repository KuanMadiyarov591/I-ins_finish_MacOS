from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from iins_agent_app.auth import require_agent
from iins_agent_app.db import get_db
from iins_agent_app.models import Application, Client, PolicyProduct, User
from iins_agent_app.services import finance_service as finance
from iins_agent_app.services import priority_service as prio

router = APIRouter(prefix="/api/applications", tags=["applications"])


class ApplicationCreateIn(BaseModel):
    client_id: int
    product_id: int
    notes: str = ""


class ChecklistIn(BaseModel):
    chk_contact_ok: bool = False
    chk_consent_ok: bool = False
    chk_docs_ok: bool = False
    chk_prefs_ok: bool = False
    notes: Optional[str] = None


class FinanceIn(BaseModel):
    payment_status: Optional[str] = Field(default=None, pattern="^(unpaid|pending|paid|overdue)$")
    payment_method: Optional[str] = Field(default=None, pattern="^(|card|cash|transfer|installment)$")
    next_payment_date: Optional[str] = Field(default=None, max_length=16)
    commission_pct: Optional[float] = Field(default=None, ge=0, le=50)


def _ensure_commission(a: Application) -> None:
    p = a.product
    prem = a.quoted_premium if a.quoted_premium is not None else (p.premium if p else 0)
    if a.commission_pct is None or float(a.commission_pct) <= 0:
        a.commission_pct = finance.default_commission_pct(p.category if p else None)
    a.commission_amount = finance.calc_commission(prem, float(a.commission_pct))


def _app_out(a: Application) -> Dict[str, Any]:
    p = a.product
    c = a.client
    checklist = {
        "chk_contact_ok": a.chk_contact_ok,
        "chk_consent_ok": a.chk_consent_ok,
        "chk_docs_ok": a.chk_docs_ok,
        "chk_prefs_ok": a.chk_prefs_ok,
    }
    ready = all(checklist.values())
    prem = a.quoted_premium if a.quoted_premium is not None else (p.premium if p else None)
    pct = float(a.commission_pct) if a.commission_pct is not None else finance.default_commission_pct(
        p.category if p else None
    )
    commission = a.commission_amount
    if commission is None:
        commission = finance.calc_commission(prem, pct)
    return {
        "id": a.id,
        "client_id": a.client_id,
        "client_name": c.full_name if c else None,
        "product_id": a.product_id,
        "product_name": p.name if p else None,
        "product_category": p.category if p else None,
        "status": a.status,
        "quoted_premium": prem,
        "payment_status": a.payment_status or "unpaid",
        "payment_method": a.payment_method or "",
        "next_payment_date": a.next_payment_date or "",
        "commission_pct": pct,
        "commission_amount": commission,
        "checklist": checklist,
        "checklist_ready": ready,
        "notes": a.notes,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


def _bump_client_priority(db: Session, client_id: int) -> None:
    client = db.get(Client, client_id)
    if not client:
        return
    open_apps = (
        db.query(Application)
        .filter(
            Application.client_id == client_id,
            Application.status.in_(["draft", "checklist", "submitted"]),
        )
        .count()
    )
    client.priority = prio.compute_priority(
        coverage_change=bool(client.coverage_change),
        has_open_application=open_apps > 0,
        buy_probability=client.buy_probability,
        propensity_tier=client.propensity_tier,
    )
    client.updated_at = datetime.now(timezone.utc)


@router.get("")
def list_applications(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_agent),
) -> Dict[str, Any]:
    q = db.query(Application).options(joinedload(Application.product), joinedload(Application.client))
    if status:
        q = q.filter(Application.status == status)
    rows = q.order_by(Application.id.desc()).limit(200).all()
    counts = {"draft": 0, "checklist": 0, "submitted": 0}
    for a in db.query(Application).all():
        st = a.status or ""
        if st in counts:
            counts[st] += 1
    return {"applications": [_app_out(a) for a in rows], "status_counts": counts, "total": len(rows)}


@router.post("")
def create_application(
    body: ApplicationCreateIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_agent),
) -> Dict[str, Any]:
    client = db.get(Client, body.client_id)
    product = db.get(PolicyProduct, body.product_id)
    if not client or not product:
        raise HTTPException(404, "Клиент или продукт не найден")
    pct = finance.default_commission_pct(product.category)
    app = Application(
        client_id=client.id,
        product_id=product.id,
        status="draft",
        quoted_premium=product.premium,
        payment_status="unpaid",
        commission_pct=pct,
        commission_amount=finance.calc_commission(product.premium, pct),
        notes=body.notes,
    )
    db.add(app)
    db.flush()
    _bump_client_priority(db, client.id)
    db.commit()
    db.refresh(app)
    app = (
        db.query(Application)
        .options(joinedload(Application.product), joinedload(Application.client))
        .filter(Application.id == app.id)
        .first()
    )
    return _app_out(app)


@router.patch("/{app_id}/checklist")
def update_checklist(
    app_id: int,
    body: ChecklistIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_agent),
) -> Dict[str, Any]:
    app = (
        db.query(Application)
        .options(joinedload(Application.product), joinedload(Application.client))
        .filter(Application.id == app_id)
        .first()
    )
    if not app:
        raise HTTPException(404, "Заявка не найдена")
    if app.status not in ("draft", "checklist"):
        raise HTTPException(400, "Чеклист только для draft/checklist")
    for k, v in body.model_dump(exclude_unset=True).items():
        if k == "notes" and v is not None:
            app.notes = v
        elif k.startswith("chk_"):
            setattr(app, k, v)
    ready = all([app.chk_contact_ok, app.chk_consent_ok, app.chk_docs_ok, app.chk_prefs_ok])
    app.status = "checklist" if ready else "draft"
    app.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(app)
    return _app_out(app)


@router.patch("/{app_id}/finance")
def update_finance(
    app_id: int,
    body: FinanceIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_agent),
) -> Dict[str, Any]:
    app = (
        db.query(Application)
        .options(joinedload(Application.product), joinedload(Application.client))
        .filter(Application.id == app_id)
        .first()
    )
    if not app:
        raise HTTPException(404, "Заявка не найдена")
    data = body.model_dump(exclude_unset=True)
    if "payment_status" in data and data["payment_status"] is not None:
        app.payment_status = data["payment_status"]
    if "payment_method" in data and data["payment_method"] is not None:
        app.payment_method = data["payment_method"]
    if "next_payment_date" in data and data["next_payment_date"] is not None:
        app.next_payment_date = (data["next_payment_date"] or "").strip()
    if "commission_pct" in data and data["commission_pct"] is not None:
        app.commission_pct = float(data["commission_pct"])
    _ensure_commission(app)
    app.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(app)
    return _app_out(app)


@router.post("/{app_id}/submit")
def submit_application(
    app_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_agent),
) -> Dict[str, Any]:
    app = (
        db.query(Application)
        .options(joinedload(Application.product), joinedload(Application.client))
        .filter(Application.id == app_id)
        .first()
    )
    if not app:
        raise HTTPException(404, "Заявка не найдена")
    if not all([app.chk_contact_ok, app.chk_consent_ok, app.chk_docs_ok, app.chk_prefs_ok]):
        raise HTTPException(400, "Сначала завершите pre-submit checklist")
    app.status = "submitted"
    if (app.payment_status or "unpaid") == "unpaid":
        app.payment_status = "pending"
    _ensure_commission(app)
    app.updated_at = datetime.now(timezone.utc)
    _bump_client_priority(db, app.client_id)
    db.commit()
    db.refresh(app)
    return _app_out(app)
