from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from iins_underwriter_app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(128), default="")
    role: Mapped[str] = mapped_column(String(32), default="underwriter")  # underwriter | admin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class UnderwritingCase(Base):
    __tablename__ = "underwriting_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    line: Mapped[str] = mapped_column(String(32), index=True)  # auto | fraud | motor
    title: Mapped[str] = mapped_column(String(255), default="")
    applicant_summary: Mapped[str] = mapped_column(Text, default="")
    risk_score: Mapped[float] = mapped_column(Float, default=50.0)  # 0..100
    recommendation: Mapped[str] = mapped_column(String(32), default="refer")  # approve|refer|decline
    decision_status: Mapped[str] = mapped_column(
        String(32), default="new", index=True
    )  # new|in_review|referred|approved|declined
    fraud_signal: Mapped[bool] = mapped_column(Boolean, default=False)
    key_factors: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of reason strings
    raw_features: Mapped[str] = mapped_column(Text, default="{}")  # JSON snippet of source columns
    notes: Mapped[str] = mapped_column(Text, default="")
    decision_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
