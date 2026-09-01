from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from iins_client_app.auth import get_current_user
from iins_client_app.db import get_db
from iins_client_app.models import User
from iins_client_app.services import recommender_service

router = APIRouter(prefix="/api/recommender", tags=["recommender"])


class ProfileIn(BaseModel):
    """Профиль клиента: medical / home + travel propensity (agent)."""

    # medical (smoker >> bmi > age > children; region слабый)
    age: int = Field(default=35, ge=18, le=100)
    sex: str = "male"  # для category_recommender
    bmi: float = Field(default=26.0, ge=10, le=60)
    children: int = Field(default=0, ge=0, le=10)
    smoker: bool = False
    region: str = "southeast"
    income: float = Field(default=80000, ge=0)

    # линии продукта
    has_home: bool = False
    has_auto: bool = False
    travels: bool = False

    # home (building_value >> claims > coverage > flood/fire > contents)
    building_value: float = Field(default=400000, ge=0)
    contents_value: float = Field(default=80000, ge=0)
    prior_claims: int = Field(default=0, ge=0, le=20)
    coverage_level: str = "Silver"
    flood_risk: float = Field(default=0.3, ge=0, le=1)
    fire_risk: float = Field(default=0.3, ge=0, le=1)

    # auto (motor premium + claim risk)
    vehicle_type: str = "Automobile"
    vehicle_usage: str = "Private"
    vehicle_value: float = Field(default=280000, ge=0)
    vehicle_age: float = Field(default=8, ge=0, le=40)
    vehicle_seats: int = Field(default=4, ge=1, le=60)
    engine_ccm: float = Field(default=1600, ge=0, le=20000)
    driving_experience: str = "10-19y"
    annual_mileage: float = Field(default=12000, ge=0, le=100000)
    past_accidents: int = Field(default=0, ge=0, le=20)
    speeding_violations: int = Field(default=0, ge=0, le=50)
    credit_score: Optional[float] = Field(default=None, ge=0, le=1)

    # travel propensity (agent 22)
    employment_type: str = "private"
    graduate: bool = True
    family_members: Optional[int] = Field(default=None, ge=1, le=20)
    chronic_diseases: int = Field(default=0, ge=0, le=1)
    frequent_flyer: bool = False
    ever_travelled_abroad: bool = False
    travel_duration: int = Field(default=7, ge=1, le=365)
    travel_distance: float = Field(default=500, ge=0, le=20000)
    travel_reason: str = "vacation"
    travel_mode: str = "plane"

    top_k: int = Field(default=5, ge=1, le=20)
    lang: str = Field(default="ru", description="ru | kk | en")


@router.get("/status")
def rec_status(_: User = Depends(get_current_user)) -> Dict[str, Any]:
    return recommender_service.status()


@router.post("/recommend")
def recommend(
    body: ProfileIn,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        data = body.model_dump()
        lang = data.pop("lang", "ru")
        top_k = data.pop("top_k", 5)
        return recommender_service.recommend_policies(db, data, top_k=top_k, lang=lang)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Ошибка рекомендаций: {exc}") from exc


@router.post("/premiums")
def premiums(body: ProfileIn, _: User = Depends(get_current_user)) -> Dict[str, Any]:
    try:
        return {
            "predicted_premiums": recommender_service.predict_premiums(body.model_dump()),
            "status": recommender_service.status(),
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
