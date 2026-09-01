from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    username: str
    user_id: int
    full_name: str


class SignupIn(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=4, max_length=128)
    first_name: str = ""
    last_name: str = ""
    address: str = ""
    mobile: str = ""


class LoginIn(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: int
    username: str
    first_name: str
    last_name: str
    role: str
    address: str
    mobile: str
    created_at: datetime

    model_config = {"from_attributes": True}


class UserUpdateIn(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    address: Optional[str] = None
    mobile: Optional[str] = None
    password: Optional[str] = None


class CategoryIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)


class CategoryOut(BaseModel):
    id: int
    name: str
    creation_date: date

    model_config = {"from_attributes": True}


class PolicyIn(BaseModel):
    category_id: int
    name: str
    sum_assurance: int = Field(ge=0)
    premium: int = Field(ge=0)
    tenure: int = Field(ge=1)
    description: str = ""


class PolicyOut(BaseModel):
    id: int
    category_id: int
    category_name: str = ""
    name: str
    sum_assurance: int
    premium: int
    tenure: int
    description: str
    creation_date: date

    model_config = {"from_attributes": True}


class ApplicationOut(BaseModel):
    id: int
    customer_id: int
    customer_name: str = ""
    policy_id: int
    policy_name: str = ""
    status: str
    admin_comment: str
    creation_date: date


class ApplicationDecisionIn(BaseModel):
    status: str  # Approved | Disapproved
    admin_comment: str = ""


class QuestionIn(BaseModel):
    description: str = Field(min_length=3, max_length=1000)


class QuestionAnswerIn(BaseModel):
    admin_comment: str = Field(min_length=1, max_length=1000)


class QuestionOut(BaseModel):
    id: int
    customer_id: int
    customer_name: str = ""
    description: str
    admin_comment: str
    status: str
    asked_date: date


class DashboardStats(BaseModel):
    total_customers: int
    total_policies: int
    total_categories: int
    total_questions: int
    total_applications: int
    approved_applications: int
    disapproved_applications: int
    pending_applications: int
    unread_notifications: int = 0


class CustomerDashboard(BaseModel):
    available_policies: int
    applied_policies: int
    total_categories: int
    total_questions: int
    pending_applications: int
    active_policies: int = 0
    open_claims: int = 0
    due_payments: int = 0
    unread_notifications: int = 0


class NotificationOut(BaseModel):
    id: int
    message: str
    is_read: int
    created_at: datetime

    model_config = {"from_attributes": True}


class AgentOut(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: str
    phone: str
    specialization: str

    model_config = {"from_attributes": True}


class AgentIn(BaseModel):
    first_name: str = Field(min_length=1, max_length=64)
    last_name: str = ""
    email: str = ""
    phone: str = ""
    specialization: str = ""


class AssignAgentIn(BaseModel):
    customer_id: int
    agent_id: int


class CustomerPolicyOut(BaseModel):
    id: int
    policy_number: str
    catalog_policy_id: int
    catalog_policy_name: str = ""
    category_name: str = ""
    customer_id: int
    application_id: int
    start_date: date
    end_date: date
    premium: int
    sum_assurance: int
    status: str


class ClaimIn(BaseModel):
    customer_policy_id: int
    claim_type: str = Field(default="accident", pattern="^(accident|theft|fire|other)$")
    description: str = Field(min_length=5, max_length=2000)
    claim_amount: int = Field(ge=0, default=0)


class ClaimDecisionIn(BaseModel):
    status: str  # InReview|Approved|Denied|Paid
    admin_comment: str = ""


class ClaimOut(BaseModel):
    id: int
    customer_policy_id: int
    policy_number: str = ""
    customer_id: int
    customer_name: str = ""
    claim_type: str
    description: str
    claim_amount: int
    status: str
    admin_comment: str
    claim_date: date


class PremiumPaymentOut(BaseModel):
    id: int
    customer_policy_id: int
    policy_number: str = ""
    amount: int
    due_date: date
    paid_at: datetime | None = None
    status: str
    method: str


class ClientDocumentOut(BaseModel):
    id: int
    title: str
    kind: str
    file_path: str
    customer_policy_id: int | None = None
    claim_id: int | None = None
    uploaded_at: datetime

    model_config = {"from_attributes": True}


class ClientDocumentIn(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    kind: str = Field(default="other", pattern="^(policy|claim|payment|other)$")
    customer_policy_id: int | None = None
    claim_id: int | None = None
    note: str = ""


class RagAskIn(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    top_k: int = Field(default=4, ge=1, le=8)
    policy_hint: str = ""
    lang: str = Field(default="ru", description="Preferred UI language: ru | kk | en")
    mode: str = Field(
        default="auto",
        description="Answer engine: auto | extractive | ollama (Qwen RAG) | gigachat",
    )


class RagChunkOut(BaseModel):
    chunk_id: str
    source: str
    title: str
    document_id: str = ""
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    citation: str = ""
    score: float
    excerpt: str


class RagAskOut(BaseModel):
    question: str
    answer: str
    model: str
    chunks_used: List[RagChunkOut]
    retrieval_ms: float
    generation_ms: float
    backend: str
    lang: str = "ru"
    mode: str = "extractive"
    answered: bool = True
    retrieval_status: str = "grounded"


class RagStatusOut(BaseModel):
    corpus_documents: int
    corpus_chunks: int
    sources: List[str]
    lm_backend: str
    ready: bool
    message_ru: str
    ollama: dict = {}
    gigachat: dict = {}
    providers: dict = {}
    provider_labels: dict = {}
    effective_backend: str = "extractive"
    modes: list[str] = ["auto", "extractive", "ollama", "gigachat"]
    retrieval_backend: str = "markdown-tfidf"
    vector_db_path: str = ""
    vector_db_error: Optional[str] = None
    neighbor_expansion: bool = False
    relevance_guard: dict = {}
