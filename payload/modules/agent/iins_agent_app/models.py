from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from iins_agent_app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


client_tags = Table(
    "client_tags",
    Base.metadata,
    Column("client_id", ForeignKey("clients.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(128), default="")
    role: Mapped[str] = mapped_column(String(32), default="agent")  # agent | admin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    profile: Mapped["AgentProfile | None"] = relationship(back_populates="user", uselist=False)


class AgentProfile(Base):
    __tablename__ = "agent_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    display_name: Mapped[str] = mapped_column(String(128), default="")
    phone: Mapped[str] = mapped_column(String(64), default="")
    email: Mapped[str] = mapped_column(String(128), default="")
    # CSV предпочтений: medical,life,auto,travel,home,funeral
    product_prefs: Mapped[str] = mapped_column(String(255), default="medical,travel,auto,home,life,funeral")
    sales_ready: Mapped[bool] = mapped_column(Boolean, default=True)
    compliance_note: Mapped[str] = mapped_column(Text, default="Проверьте разрешения на продажу продуктов перед встречей.")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    user: Mapped[User] = relationship(back_populates="profile")


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    clients: Mapped[list["Client"]] = relationship(secondary=client_tags, back_populates="tags")


class PolicyProduct(Base):
    __tablename__ = "policy_products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    category: Mapped[str] = mapped_column(String(64))  # medical|life|auto|travel|home|funeral
    premium: Mapped[int] = mapped_column(Integer, default=10000)
    sum_assurance: Mapped[int] = mapped_column(Integer, default=500000)
    description: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(128), default="")
    phone: Mapped[str] = mapped_column(String(64), default="")
    email: Mapped[str] = mapped_column(String(128), default="")
    age: Mapped[int] = mapped_column(Integer, default=35)
    employment_type: Mapped[str] = mapped_column(String(64), default="Private Sector/Self Employed")
    graduate: Mapped[str] = mapped_column(String(8), default="Yes")
    annual_income: Mapped[float] = mapped_column(Float, default=500000)
    family_members: Mapped[int] = mapped_column(Integer, default=2)
    chronic_diseases: Mapped[int] = mapped_column(Integer, default=0)
    frequent_flyer: Mapped[str] = mapped_column(String(8), default="No")
    ever_travelled_abroad: Mapped[str] = mapped_column(String(8), default="No")
    # CRM
    status: Mapped[str] = mapped_column(String(32), default="active")  # active|prospect|inactive
    priority: Mapped[int] = mapped_column(Integer, default=3)  # 1..5
    coverage_change: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    # ML signal (secondary)
    buy_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    propensity_tier: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    tags: Mapped[list[Tag]] = relationship(secondary=client_tags, back_populates="clients")
    applications: Mapped[list["Application"]] = relationship(back_populates="client")


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("policy_products.id"))
    status: Mapped[str] = mapped_column(String(32), default="draft")  # draft|checklist|submitted|approved|rejected
    # pre-submit checklist
    chk_contact_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    chk_consent_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    chk_docs_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    chk_prefs_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    quoted_premium: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Лёгкий блок оплаты/комиссии (не полноценный биллинг)
    payment_status: Mapped[str] = mapped_column(String(32), default="unpaid")  # unpaid|pending|paid|overdue
    payment_method: Mapped[str] = mapped_column(String(32), default="")  # card|cash|transfer|installment|""
    next_payment_date: Mapped[str] = mapped_column(String(16), default="")  # YYYY-MM-DD
    commission_pct: Mapped[float] = mapped_column(Float, default=10.0)
    commission_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    client: Mapped[Client] = relationship(back_populates="applications")
    product: Mapped[PolicyProduct] = relationship()
