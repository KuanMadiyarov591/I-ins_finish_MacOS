from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from iins_agent_app.auth import get_current_user, require_agent
from iins_agent_app.db import get_db
from iins_agent_app.models import Application, Client, PolicyProduct, Tag, User
from iins_agent_app.services import priority_service as prio

router = APIRouter(prefix="/api", tags=["crm"])


class ClientUpdateIn(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    status: Optional[str] = Field(default=None, pattern="^(active|prospect|inactive)$")
    notes: Optional[str] = None
    coverage_change: Optional[bool] = None
    tags: Optional[List[str]] = None
    priority: Optional[int] = Field(default=None, ge=1, le=5)


class AgentProfileIn(BaseModel):
    display_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    product_prefs: Optional[str] = None
    sales_ready: Optional[bool] = None


def _client_out(c: Client) -> Dict[str, Any]:
    return {
        "id": c.id,
        "external_id": c.external_id,
        "full_name": c.full_name,
        "phone": c.phone,
        "email": c.email,
        "age": c.age,
        "annual_income": c.annual_income,
        "family_members": c.family_members,
        "employment_type": c.employment_type,
        "graduate": c.graduate,
        "chronic_diseases": c.chronic_diseases,
        "frequent_flyer": c.frequent_flyer,
        "ever_travelled_abroad": c.ever_travelled_abroad,
        "status": c.status,
        "priority": c.priority,
        "priority_label": prio.PRIORITY_LABELS.get(c.priority, str(c.priority)),
        "priority_short": prio.PRIORITY_SHORT.get(c.priority, str(c.priority)),
        "coverage_change": c.coverage_change,
        "notes": c.notes,
        "buy_probability": c.buy_probability,
        "propensity_tier": c.propensity_tier,
        "tags": [t.name for t in (c.tags or [])],
        "applications_count": len(c.applications or []),
    }


def _recalc_priority(db: Session, client: Client) -> None:
    open_apps = (
        db.query(Application)
        .filter(
            Application.client_id == client.id,
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


@router.get("/products")
def list_products(db: Session = Depends(get_db), _: User = Depends(require_agent)) -> Dict[str, Any]:
    rows = db.query(PolicyProduct).filter(PolicyProduct.is_active.is_(True)).order_by(PolicyProduct.id).all()
    return {
        "products": [
            {
                "id": p.id,
                "code": p.code,
                "name": p.name,
                "category": p.category,
                "premium": p.premium,
                "sum_assurance": p.sum_assurance,
                "description": p.description,
            }
            for p in rows
        ]
    }


@router.get("/tags")
def list_tags(db: Session = Depends(get_db), _: User = Depends(require_agent)) -> Dict[str, Any]:
    return {"tags": [t.name for t in db.query(Tag).order_by(Tag.name).all()]}


@router.get("/clients")
def list_clients(
    priority: Optional[int] = Query(default=None, ge=1, le=5),
    tag: Optional[str] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_agent),
) -> Dict[str, Any]:
    query = db.query(Client).options(joinedload(Client.tags), joinedload(Client.applications))
    if priority is not None:
        query = query.filter(Client.priority == priority)
    if status:
        query = query.filter(Client.status == status)
    if tag:
        query = query.join(Client.tags).filter(Tag.name == tag)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            (Client.full_name.ilike(like))
            | (Client.external_id.ilike(like))
            | (Client.phone.ilike(like))
            | (Client.email.ilike(like))
        )
    rows = query.order_by(Client.priority.asc(), Client.id.asc()).limit(limit).all()
    counts = {i: 0 for i in range(1, 6)}
    for c in db.query(Client).all():
        counts[int(c.priority)] = counts.get(int(c.priority), 0) + 1
    return {"clients": [_client_out(c) for c in rows], "priority_counts": counts, "total": len(rows)}


@router.get("/clients/{client_id}")
def get_client(client_id: int, db: Session = Depends(get_db), _: User = Depends(require_agent)) -> Dict[str, Any]:
    c = (
        db.query(Client)
        .options(joinedload(Client.tags), joinedload(Client.applications))
        .filter(Client.id == client_id)
        .first()
    )
    if not c:
        raise HTTPException(404, "Клиент не найден")
    out = _client_out(c)
    out["applications"] = [
        {
            "id": a.id,
            "product_id": a.product_id,
            "status": a.status,
            "quoted_premium": a.quoted_premium,
        }
        for a in (c.applications or [])
    ]
    return out


@router.patch("/clients/{client_id}")
def update_client(
    client_id: int,
    body: ClientUpdateIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_agent),
) -> Dict[str, Any]:
    c = db.query(Client).options(joinedload(Client.tags)).filter(Client.id == client_id).first()
    if not c:
        raise HTTPException(404, "Клиент не найден")
    data = body.model_dump(exclude_unset=True)
    tags = data.pop("tags", None)
    for k, v in data.items():
        setattr(c, k, v)
    if tags is not None:
        tag_objs = []
        for name in tags:
            t = db.query(Tag).filter(Tag.name == name).first()
            if not t:
                t = Tag(name=name)
                db.add(t)
                db.flush()
            tag_objs.append(t)
        c.tags = tag_objs
    if body.priority is None:
        _recalc_priority(db, c)
    c.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(c)
    return _client_out(c)


@router.post("/clients/{client_id}/refresh-priority")
def refresh_priority(client_id: int, db: Session = Depends(get_db), _: User = Depends(require_agent)) -> Dict[str, Any]:
    c = db.get(Client, client_id)
    if not c:
        raise HTTPException(404, "Клиент не найден")
    ml = prio.enrich_client_ml(
        {
            "age": c.age,
            "annual_income": c.annual_income,
            "family_members": c.family_members,
            "employment_type": c.employment_type,
            "graduate": c.graduate,
            "chronic_diseases": c.chronic_diseases,
            "frequent_flyer": c.frequent_flyer,
            "ever_travelled_abroad": c.ever_travelled_abroad,
        }
    )
    c.buy_probability = ml.get("buy_probability")
    c.propensity_tier = ml.get("propensity_tier")
    _recalc_priority(db, c)
    c.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(c)
    return _client_out(c)


@router.get("/agent/profile")
def get_agent_profile(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Dict[str, Any]:
    from iins_agent_app.models import AgentProfile

    prof = db.query(AgentProfile).filter(AgentProfile.user_id == user.id).first()
    if not prof:
        return {
            "user_id": user.id,
            "username": user.username,
            "display_name": user.full_name,
            "phone": "",
            "email": "",
            "product_prefs": "medical,travel,auto,home,life,funeral",
            "sales_ready": True,
            "compliance_note": "",
        }
    return {
        "user_id": user.id,
        "username": user.username,
        "display_name": prof.display_name,
        "phone": prof.phone,
        "email": prof.email,
        "product_prefs": prof.product_prefs,
        "sales_ready": prof.sales_ready,
        "compliance_note": prof.compliance_note,
    }


@router.patch("/agent/profile")
def patch_agent_profile(
    body: AgentProfileIn,
    user: User = Depends(require_agent),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    from iins_agent_app.models import AgentProfile

    prof = db.query(AgentProfile).filter(AgentProfile.user_id == user.id).first()
    if not prof:
        prof = AgentProfile(user_id=user.id, display_name=user.full_name or user.username)
        db.add(prof)
        db.flush()
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(prof, k, v)
    prof.updated_at = datetime.now(timezone.utc)
    db.commit()
    return get_agent_profile(user, db)
