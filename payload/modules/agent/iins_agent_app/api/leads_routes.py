from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from iins_agent_app.auth import require_agent
from iins_agent_app.db import get_db
from iins_agent_app.models import Lead, User
from iins_agent_app.services import lead_scoring_service as scoring

router = APIRouter(prefix="/api", tags=["leads"])

STATUS_RU = {
    "new": "В очереди",
    "contacted": "Позвонили",
    "won": "Купил",
    "lost": "Отказ",
}


class LeadProfileIn(BaseModel):
    age: int = Field(default=35, ge=16, le=100)
    employment_type: str = "private"
    graduate: bool = True
    annual_income: float = Field(default=500000, ge=0)
    family_members: int = Field(default=2, ge=1, le=20)
    chronic_diseases: int = Field(default=0, ge=0, le=1)
    frequent_flyer: bool = False
    ever_travelled_abroad: bool = False


class LeadStatusIn(BaseModel):
    status: str = Field(pattern="^(new|contacted|won|lost)$")
    notes: Optional[str] = None


def _profile_from_lead(lead: Lead) -> Dict[str, Any]:
    return {
        "age": lead.age,
        "employment_type": lead.employment_type,
        "graduate": lead.graduate,
        "annual_income": lead.annual_income,
        "family_members": lead.family_members,
        "chronic_diseases": lead.chronic_diseases,
        "frequent_flyer": lead.frequent_flyer,
        "ever_travelled_abroad": lead.ever_travelled_abroad,
    }


def _lead_out(lead: Lead, scored: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out = {
        "id": lead.id,
        "external_id": lead.external_id,
        "age": lead.age,
        "employment_type": lead.employment_type,
        "graduate": lead.graduate,
        "annual_income": lead.annual_income,
        "family_members": lead.family_members,
        "chronic_diseases": lead.chronic_diseases,
        "frequent_flyer": lead.frequent_flyer,
        "ever_travelled_abroad": lead.ever_travelled_abroad,
        "buy_probability": lead.score,
        "score": lead.score,
        "score_0_100": round(float(lead.score) * 100, 1) if lead.score is not None else None,
        "will_buy": (lead.score is not None and float(lead.score) >= 0.5),
        "will_buy_label": (
            "Скорее купит"
            if lead.score is not None and float(lead.score) >= 0.5
            else ("Скорее не купит" if lead.score is not None else None)
        ),
        "tier": lead.tier,
        "tier_ru": scoring.TIER_RU.get(lead.tier or "", lead.tier),
        "sla": scoring.tier_action(lead.tier) if lead.tier else None,
        "status": lead.status,
        "status_ru": STATUS_RU.get(lead.status, lead.status),
        "notes": lead.notes,
        "reason_1": None,
        "reason_2": None,
        "reason_3": None,
        "top_negative": None,
    }
    if scored:
        for k in (
            "buy_probability",
            "score_0_100",
            "will_buy",
            "will_buy_label",
            "tier",
            "tier_ru",
            "sla",
            "reason_1",
            "reason_2",
            "reason_3",
            "top_negative",
        ):
            if k in scored:
                out[k] = scored[k]
        out["score"] = scored.get("buy_probability", out["score"])
    return out


@router.get("/scoring/status")
def scoring_status(_: User = Depends(require_agent)) -> Dict[str, Any]:
    return scoring.status()


@router.post("/leads/score")
def score_one(body: LeadProfileIn, _: User = Depends(require_agent)) -> Dict[str, Any]:
    try:
        return scoring.score_profile(body.model_dump())
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/leads")
def list_leads(
    tier: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    explain: bool = Query(default=True, description="Добавить reasons (медленнее)"),
    limit: int = Query(default=80, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_agent),
) -> Dict[str, Any]:
    q = db.query(Lead)
    if tier:
        q = q.filter(Lead.tier == tier)
    if status:
        q = q.filter(Lead.status == status)
    rows = q.order_by(Lead.score.is_(None), Lead.score.desc(), Lead.id.asc()).limit(limit).all()

    counts = {"Hot": 0, "Warm": 0, "Nurture": 0, "Suppress": 0, "unscored": 0}
    # migrate old Cold -> Nurture display count
    for r in db.query(Lead).all():
        t = r.tier
        if t == "Cold":
            t = "Nurture"
        if t in counts:
            counts[t] += 1
        else:
            counts["unscored"] += 1

    leads_out = []
    ready = scoring.status()["ready"]
    for lead in rows:
        scored = None
        if explain and ready:
            try:
                scored = scoring.score_profile(_profile_from_lead(lead))
            except Exception:  # noqa: BLE001
                scored = None
        item = _lead_out(lead, scored)
        # normalize legacy Cold
        if item.get("tier") == "Cold":
            item["tier"] = "Nurture"
            item["tier_ru"] = scoring.TIER_RU["Nurture"]
        leads_out.append(item)

    return {
        "what_we_predict_ru": scoring.status()["what_we_predict_ru"],
        "leads": leads_out,
        "counts": counts,
        "total": len(leads_out),
    }


@router.post("/leads/rescore")
def rescore_all(db: Session = Depends(get_db), _: User = Depends(require_agent)) -> Dict[str, Any]:
    if not scoring.status()["ready"]:
        raise HTTPException(status_code=503, detail="Модель не обучена")
    leads = db.query(Lead).all()
    updated = 0
    for lead in leads:
        out = scoring.score_profile(_profile_from_lead(lead))
        lead.score = out["buy_probability"]
        lead.tier = out["tier"]
        lead.updated_at = datetime.now(timezone.utc)
        updated += 1
    db.commit()
    return {"updated": updated, "status": scoring.status()}


@router.patch("/leads/{lead_id}")
def update_lead(
    lead_id: int,
    body: LeadStatusIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_agent),
) -> Dict[str, Any]:
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Лид не найден")
    lead.status = body.status
    if body.notes is not None:
        lead.notes = body.notes
    lead.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(lead)
    scored = None
    if scoring.status()["ready"]:
        try:
            scored = scoring.score_profile(_profile_from_lead(lead))
        except Exception:  # noqa: BLE001
            scored = None
    return _lead_out(lead, scored)
