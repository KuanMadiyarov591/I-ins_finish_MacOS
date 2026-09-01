from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from iins_actuary_app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(128), default="")
    role: Mapped[str] = mapped_column(String(32), default="actuary")  # actuary | admin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class PremiumCase(Base):
    """Seeded CGR premium row for Programs browse / recommendations."""

    __tablename__ = "premium_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    territory: Mapped[str] = mapped_column(String(32), index=True, default="")
    gender: Mapped[str] = mapped_column(String(8), default="")
    birthdate: Mapped[str] = mapped_column(String(32), default="")
    age: Mapped[float] = mapped_column(Float, default=0.0)
    ypc: Mapped[float] = mapped_column(Float, default=0.0)
    indicated_premium: Mapped[float] = mapped_column(Float, default=0.0)
    selected_premium: Mapped[float] = mapped_column(Float, default=0.0)
    fixed_expenses: Mapped[float] = mapped_column(Float, default=0.0)
    cgr: Mapped[str] = mapped_column(String(32), index=True, default="")
    cgr_factor: Mapped[float] = mapped_column(Float, default=1.0)
    # stored for display only — never used as model feature
    current_premium: Mapped[float] = mapped_column(Float, default=0.0)
    underlying_premium: Mapped[float] = mapped_column(Float, default=0.0)
    raw_features: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class CgrDefinition(Base):
    __tablename__ = "cgr_definitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cgr: Mapped[str] = mapped_column(String(32), index=True, default="")
    aa: Mapped[float] = mapped_column(Float, default=0.0)
    bb: Mapped[float] = mapped_column(Float, default=0.0)
    cc: Mapped[float] = mapped_column(Float, default=0.0)
    va: Mapped[float] = mapped_column(Float, default=0.0)
    dd: Mapped[float] = mapped_column(Float, default=0.0)
    hh: Mapped[float] = mapped_column(Float, default=0.0)
    ss: Mapped[float] = mapped_column(Float, default=0.0)
    payload: Mapped[str] = mapped_column(Text, default="{}")


class TerritoryDefinition(Base):
    __tablename__ = "territory_definitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    county: Mapped[str] = mapped_column(String(128), default="")
    county_code: Mapped[str] = mapped_column(String(32), default="")
    territory: Mapped[str] = mapped_column(String(32), index=True, default="")
    zipcode: Mapped[str] = mapped_column(String(16), default="")
    town: Mapped[str] = mapped_column(String(128), default="")
    area: Mapped[str] = mapped_column(String(64), default="")
    payload: Mapped[str] = mapped_column(Text, default="{}")
