from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from iins_client_app.db import Base


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    first_name: Mapped[str] = mapped_column(String(64), default="")
    last_name: Mapped[str] = mapped_column(String(64), default="")
    email: Mapped[str] = mapped_column(String(120), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    specialization: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    customers: Mapped[list[User]] = relationship(back_populates="agent")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    first_name: Mapped[str] = mapped_column(String(64), default="")
    last_name: Mapped[str] = mapped_column(String(64), default="")
    role: Mapped[str] = mapped_column(String(20), default="customer")  # admin | customer
    address: Mapped[str] = mapped_column(String(200), default="")
    mobile: Mapped[str] = mapped_column(String(40), default="")
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    agent: Mapped[Agent | None] = relationship(back_populates="customers")
    applications: Mapped[list[PolicyApplication]] = relationship(back_populates="customer")
    questions: Mapped[list[Question]] = relationship(back_populates="customer")
    customer_policies: Mapped[list[CustomerPolicy]] = relationship(back_populates="customer")
    notifications: Mapped[list[Notification]] = relationship(back_populates="user")


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    creation_date: Mapped[date] = mapped_column(Date, default=date.today)

    policies: Mapped[list[Policy]] = relationship(back_populates="category")


class Policy(Base):
    __tablename__ = "policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    sum_assurance: Mapped[int] = mapped_column(Integer)
    premium: Mapped[int] = mapped_column(Integer)
    tenure: Mapped[int] = mapped_column(Integer)  # years
    description: Mapped[str] = mapped_column(Text, default="")
    creation_date: Mapped[date] = mapped_column(Date, default=date.today)

    category: Mapped[Category] = relationship(back_populates="policies")
    applications: Mapped[list[PolicyApplication]] = relationship(back_populates="policy")
    customer_policies: Mapped[list[CustomerPolicy]] = relationship(back_populates="catalog_policy")


class PolicyApplication(Base):
    __tablename__ = "policy_applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    policy_id: Mapped[int] = mapped_column(ForeignKey("policies.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(40), default="Pending")  # Pending|Approved|Disapproved
    admin_comment: Mapped[str] = mapped_column(String(500), default="")
    creation_date: Mapped[date] = mapped_column(Date, default=date.today)

    customer: Mapped[User] = relationship(back_populates="applications")
    policy: Mapped[Policy] = relationship(back_populates="applications")
    customer_policy: Mapped[CustomerPolicy | None] = relationship(back_populates="application", uselist=False)


class CustomerPolicy(Base):
    """Действующий полис клиента после одобрения заявки."""

    __tablename__ = "customer_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    catalog_policy_id: Mapped[int] = mapped_column(ForeignKey("policies.id", ondelete="CASCADE"))
    application_id: Mapped[int] = mapped_column(
        ForeignKey("policy_applications.id", ondelete="CASCADE"), unique=True
    )
    policy_number: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    start_date: Mapped[date] = mapped_column(Date, default=date.today)
    end_date: Mapped[date] = mapped_column(Date)
    premium: Mapped[int] = mapped_column(Integer)
    sum_assurance: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), default="Active")  # Active|Expired|Cancelled
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    customer: Mapped[User] = relationship(back_populates="customer_policies")
    catalog_policy: Mapped[Policy] = relationship(back_populates="customer_policies")
    application: Mapped[PolicyApplication] = relationship(back_populates="customer_policy")
    claims: Mapped[list[Claim]] = relationship(back_populates="customer_policy")
    payments: Mapped[list[PremiumPayment]] = relationship(back_populates="customer_policy")
    documents: Mapped[list[ClientDocument]] = relationship(back_populates="customer_policy")


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_policy_id: Mapped[int] = mapped_column(ForeignKey("customer_policies.id", ondelete="CASCADE"))
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    claim_type: Mapped[str] = mapped_column(String(40), default="other")  # accident|theft|fire|other
    description: Mapped[str] = mapped_column(String(2000), default="")
    claim_amount: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(40), default="Pending")  # Pending|InReview|Approved|Denied|Paid
    admin_comment: Mapped[str] = mapped_column(String(1000), default="")
    claim_date: Mapped[date] = mapped_column(Date, default=date.today)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    customer_policy: Mapped[CustomerPolicy] = relationship(back_populates="claims")


class PremiumPayment(Base):
    __tablename__ = "premium_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_policy_id: Mapped[int] = mapped_column(ForeignKey("customer_policies.id", ondelete="CASCADE"))
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    amount: Mapped[int] = mapped_column(Integer)
    due_date: Mapped[date] = mapped_column(Date)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="Due")  # Due|Paid|Overdue
    method: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    customer_policy: Mapped[CustomerPolicy] = relationship(back_populates="payments")


class ClientDocument(Base):
    __tablename__ = "client_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    customer_policy_id: Mapped[int | None] = mapped_column(
        ForeignKey("customer_policies.id", ondelete="SET NULL"), nullable=True
    )
    claim_id: Mapped[int | None] = mapped_column(ForeignKey("claims.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(40), default="policy")  # policy|claim|payment|other
    file_path: Mapped[str] = mapped_column(String(500), default="")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    customer_policy: Mapped[CustomerPolicy | None] = relationship(back_populates="documents")


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    description: Mapped[str] = mapped_column(String(1000))
    admin_comment: Mapped[str] = mapped_column(String(1000), default="Ожидает ответа")
    status: Mapped[str] = mapped_column(String(40), default="Pending")  # Pending|Answered
    asked_date: Mapped[date] = mapped_column(Date, default=date.today)

    customer: Mapped[User] = relationship(back_populates="questions")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    message: Mapped[str] = mapped_column(String(500))
    is_read: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped[User] = relationship(back_populates="notifications")
