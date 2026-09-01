from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from iins_legal_app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(128), default="")
    role: Mapped[str] = mapped_column(String(32), default="lawyer")  # lawyer | admin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class LegalCase(Base):
    __tablename__ = "legal_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    line: Mapped[str] = mapped_column(String(32), index=True)  # pi | imr
    title: Mapped[str] = mapped_column(String(255), default="")
    applicant_summary: Mapped[str] = mapped_column(Text, default="")
    risk_score: Mapped[float] = mapped_column(Float, default=50.0)  # 0..100 priority/complexity
    recommendation: Mapped[str] = mapped_column(String(32), default="escalate")  # accept|escalate|decline
    decision_status: Mapped[str] = mapped_column(
        String(32), default="new", index=True
    )  # new|in_review|escalated|accepted|declined
    urgency_signal: Mapped[bool] = mapped_column(Boolean, default=False)
    key_factors: Mapped[str] = mapped_column(Text, default="[]")
    raw_features: Mapped[str] = mapped_column(Text, default="{}")
    notes: Mapped[str] = mapped_column(Text, default="")
    decision_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
