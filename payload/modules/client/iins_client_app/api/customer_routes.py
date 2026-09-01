from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from iins_client_app.api.helpers import application_out, policy_out, question_out
from iins_client_app.auth import require_customer
from iins_client_app.config import ROOT
from iins_client_app.db import get_db
from iins_client_app.models import (
    Agent,
    Category,
    Claim,
    ClientDocument,
    CustomerPolicy,
    Notification,
    Policy,
    PolicyApplication,
    PremiumPayment,
    Question,
    User,
)
from iins_client_app.schemas import (
    ClaimIn,
    ClaimOut,
    ClientDocumentIn,
    ClientDocumentOut,
    CustomerDashboard,
    CustomerPolicyOut,
    PremiumPaymentOut,
    AgentOut,
    NotificationOut,
    PolicyOut,
    CategoryOut,
    ApplicationOut,
    QuestionIn,
    QuestionOut,
)

router = APIRouter(prefix="/api/customer", tags=["customer"])

DOCS_DIR = ROOT / "data" / "client_docs"


def _cp_out(cp: CustomerPolicy) -> CustomerPolicyOut:
    cat_name = ""
    pol_name = ""
    if cp.catalog_policy:
        pol_name = cp.catalog_policy.name
        if cp.catalog_policy.category:
            cat_name = cp.catalog_policy.category.name
    return CustomerPolicyOut(
        id=cp.id,
        policy_number=cp.policy_number,
        catalog_policy_id=cp.catalog_policy_id,
        catalog_policy_name=pol_name,
        category_name=cat_name,
        customer_id=cp.customer_id,
        application_id=cp.application_id,
        start_date=cp.start_date,
        end_date=cp.end_date,
        premium=cp.premium,
        sum_assurance=cp.sum_assurance,
        status=cp.status,
    )


def _claim_out(c: Claim, policy_number: str = "", customer_name: str = "") -> ClaimOut:
    if not policy_number and c.customer_policy:
        policy_number = c.customer_policy.policy_number
    return ClaimOut(
        id=c.id,
        customer_policy_id=c.customer_policy_id,
        policy_number=policy_number,
        customer_id=c.customer_id,
        customer_name=customer_name,
        claim_type=c.claim_type,
        description=c.description,
        claim_amount=c.claim_amount,
        status=c.status,
        admin_comment=c.admin_comment or "",
        claim_date=c.claim_date,
    )


def _payment_out(p: PremiumPayment, policy_number: str = "") -> PremiumPaymentOut:
    if not policy_number and p.customer_policy:
        policy_number = p.customer_policy.policy_number
    # mark overdue lazily for display
    status = p.status
    if status == "Due" and p.due_date < date.today():
        status = "Overdue"
    return PremiumPaymentOut(
        id=p.id,
        customer_policy_id=p.customer_policy_id,
        policy_number=policy_number,
        amount=p.amount,
        due_date=p.due_date,
        paid_at=p.paid_at,
        status=status,
        method=p.method or "",
    )


@router.get("/dashboard", response_model=CustomerDashboard)
def dashboard(
    db: Session = Depends(get_db),
    user: User = Depends(require_customer),
) -> CustomerDashboard:
    apps = db.query(PolicyApplication).filter(PolicyApplication.customer_id == user.id)
    return CustomerDashboard(
        available_policies=db.query(Policy).count(),
        applied_policies=apps.count(),
        total_categories=db.query(Category).count(),
        total_questions=db.query(Question).filter(Question.customer_id == user.id).count(),
        pending_applications=apps.filter(PolicyApplication.status == "Pending").count(),
        active_policies=db.query(CustomerPolicy)
        .filter(CustomerPolicy.customer_id == user.id, CustomerPolicy.status == "Active")
        .count(),
        open_claims=db.query(Claim)
        .filter(
            Claim.customer_id == user.id,
            Claim.status.in_(["Pending", "InReview"]),
        )
        .count(),
        due_payments=db.query(PremiumPayment)
        .filter(
            PremiumPayment.customer_id == user.id,
            PremiumPayment.status.in_(["Due", "Overdue"]),
        )
        .count(),
        unread_notifications=db.query(Notification)
        .filter(Notification.user_id == user.id, Notification.is_read == 0)
        .count(),
    )


@router.get("/categories", response_model=list[CategoryOut])
def categories(db: Session = Depends(get_db), _: User = Depends(require_customer)) -> list[CategoryOut]:
    return [CategoryOut.model_validate(c) for c in db.query(Category).order_by(Category.id).all()]


@router.get("/policies", response_model=list[PolicyOut])
def policies(db: Session = Depends(get_db), _: User = Depends(require_customer)) -> list[PolicyOut]:
    rows = db.query(Policy).options(joinedload(Policy.category)).order_by(Policy.id).all()
    return [policy_out(p) for p in rows]


@router.post("/applications/{policy_id}", response_model=ApplicationOut)
def apply_policy(
    policy_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_customer),
) -> ApplicationOut:
    policy = db.get(Policy, policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Полис не найден")
    existing = (
        db.query(PolicyApplication)
        .filter(
            PolicyApplication.customer_id == user.id,
            PolicyApplication.policy_id == policy_id,
            PolicyApplication.status == "Pending",
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Заявка на этот полис уже на рассмотрении")

    app = PolicyApplication(customer_id=user.id, policy_id=policy_id, status="Pending")
    db.add(app)

    admins = db.query(User).filter(User.role == "admin").all()
    msg = (
        f"Новая заявка на полис «{policy.name}» от клиента "
        f"{user.first_name} {user.last_name} ({user.username})"
    )
    for admin in admins:
        db.add(Notification(user_id=admin.id, message=msg, is_read=0))

    db.commit()
    app = (
        db.query(PolicyApplication)
        .options(joinedload(PolicyApplication.customer), joinedload(PolicyApplication.policy))
        .filter(PolicyApplication.id == app.id)
        .one()
    )
    return application_out(app)


@router.get("/history", response_model=list[ApplicationOut])
def history(
    db: Session = Depends(get_db),
    user: User = Depends(require_customer),
) -> list[ApplicationOut]:
    rows = (
        db.query(PolicyApplication)
        .options(joinedload(PolicyApplication.customer), joinedload(PolicyApplication.policy))
        .filter(PolicyApplication.customer_id == user.id)
        .order_by(PolicyApplication.id.desc())
        .all()
    )
    return [application_out(a) for a in rows]


@router.post("/questions", response_model=QuestionOut)
def ask_question(
    body: QuestionIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_customer),
) -> QuestionOut:
    q = Question(
        customer_id=user.id,
        description=body.description.strip(),
        admin_comment="Ожидает ответа",
        status="Pending",
    )
    db.add(q)
    for admin in db.query(User).filter(User.role == "admin").all():
        db.add(
            Notification(
                user_id=admin.id,
                message=f"Новый вопрос от {user.username}: {body.description[:80]}",
                is_read=0,
            )
        )
    db.commit()
    q = db.query(Question).options(joinedload(Question.customer)).filter(Question.id == q.id).one()
    return question_out(q)


@router.get("/questions", response_model=list[QuestionOut])
def my_questions(
    db: Session = Depends(get_db),
    user: User = Depends(require_customer),
) -> list[QuestionOut]:
    rows = (
        db.query(Question)
        .options(joinedload(Question.customer))
        .filter(Question.customer_id == user.id)
        .order_by(Question.id.desc())
        .all()
    )
    return [question_out(q) for q in rows]


# --- my policies ---
@router.get("/my-policies", response_model=list[CustomerPolicyOut])
def my_policies(
    db: Session = Depends(get_db),
    user: User = Depends(require_customer),
) -> list[CustomerPolicyOut]:
    rows = (
        db.query(CustomerPolicy)
        .options(joinedload(CustomerPolicy.catalog_policy).joinedload(Policy.category))
        .filter(CustomerPolicy.customer_id == user.id)
        .order_by(CustomerPolicy.id.desc())
        .all()
    )
    return [_cp_out(r) for r in rows]


@router.get("/my-policies/{policy_id}", response_model=CustomerPolicyOut)
def my_policy_detail(
    policy_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_customer),
) -> CustomerPolicyOut:
    cp = (
        db.query(CustomerPolicy)
        .options(joinedload(CustomerPolicy.catalog_policy).joinedload(Policy.category))
        .filter(CustomerPolicy.id == policy_id, CustomerPolicy.customer_id == user.id)
        .first()
    )
    if not cp:
        raise HTTPException(status_code=404, detail="Полис не найден")
    return _cp_out(cp)


# --- claims ---
@router.get("/claims", response_model=list[ClaimOut])
def list_claims(
    db: Session = Depends(get_db),
    user: User = Depends(require_customer),
) -> list[ClaimOut]:
    rows = (
        db.query(Claim)
        .options(joinedload(Claim.customer_policy))
        .filter(Claim.customer_id == user.id)
        .order_by(Claim.id.desc())
        .all()
    )
    return [_claim_out(c) for c in rows]


@router.get("/claims/{claim_id}", response_model=ClaimOut)
def get_claim(
    claim_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_customer),
) -> ClaimOut:
    c = (
        db.query(Claim)
        .options(joinedload(Claim.customer_policy))
        .filter(Claim.id == claim_id, Claim.customer_id == user.id)
        .first()
    )
    if not c:
        raise HTTPException(status_code=404, detail="Убыток не найден")
    return _claim_out(c)


@router.post("/claims", response_model=ClaimOut)
def create_claim(
    body: ClaimIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_customer),
) -> ClaimOut:
    cp = (
        db.query(CustomerPolicy)
        .filter(
            CustomerPolicy.id == body.customer_policy_id,
            CustomerPolicy.customer_id == user.id,
            CustomerPolicy.status == "Active",
        )
        .first()
    )
    if not cp:
        raise HTTPException(status_code=400, detail="Нужен активный полис")

    claim = Claim(
        customer_policy_id=cp.id,
        customer_id=user.id,
        claim_type=body.claim_type,
        description=body.description.strip(),
        claim_amount=body.claim_amount,
        status="Pending",
    )
    db.add(claim)
    for admin in db.query(User).filter(User.role == "admin").all():
        db.add(
            Notification(
                user_id=admin.id,
                message=f"Новый убыток по полису {cp.policy_number} от {user.username}",
                is_read=0,
            )
        )
    db.add(
        Notification(
            user_id=user.id,
            message=f"Убыток по полису {cp.policy_number} принят. Статус: На рассмотрении.",
            is_read=0,
        )
    )
    db.commit()
    claim = (
        db.query(Claim)
        .options(joinedload(Claim.customer_policy))
        .filter(Claim.id == claim.id)
        .one()
    )
    return _claim_out(claim)


# --- payments ---
@router.get("/payments", response_model=list[PremiumPaymentOut])
def list_payments(
    db: Session = Depends(get_db),
    user: User = Depends(require_customer),
) -> list[PremiumPaymentOut]:
    rows = (
        db.query(PremiumPayment)
        .options(joinedload(PremiumPayment.customer_policy))
        .filter(PremiumPayment.customer_id == user.id)
        .order_by(PremiumPayment.due_date.asc())
        .all()
    )
    # persist overdue flag
    changed = False
    for p in rows:
        if p.status == "Due" and p.due_date < date.today():
            p.status = "Overdue"
            changed = True
    if changed:
        db.commit()
    return [_payment_out(p) for p in rows]


@router.post("/payments/{payment_id}/pay", response_model=PremiumPaymentOut)
def pay_premium(
    payment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_customer),
) -> PremiumPaymentOut:
    p = (
        db.query(PremiumPayment)
        .options(joinedload(PremiumPayment.customer_policy))
        .filter(PremiumPayment.id == payment_id, PremiumPayment.customer_id == user.id)
        .first()
    )
    if not p:
        raise HTTPException(status_code=404, detail="Платёж не найден")
    if p.status == "Paid":
        raise HTTPException(status_code=400, detail="Уже оплачено")
    p.status = "Paid"
    p.paid_at = datetime.utcnow()
    p.method = "demo-card"
    db.add(
        Notification(
            user_id=user.id,
            message=f"Оплачена премия {p.amount} ₽ по полису {p.customer_policy.policy_number}",
            is_read=0,
        )
    )
    db.commit()
    db.refresh(p)
    return _payment_out(p)


# --- agent ---
@router.get("/agent", response_model=AgentOut | None)
def my_agent(
    db: Session = Depends(get_db),
    user: User = Depends(require_customer),
) -> AgentOut | None:
    u = db.query(User).options(joinedload(User.agent)).filter(User.id == user.id).one()
    if not u.agent:
        return None
    return AgentOut.model_validate(u.agent)


# --- documents ---
@router.get("/documents", response_model=list[ClientDocumentOut])
def list_documents(
    db: Session = Depends(get_db),
    user: User = Depends(require_customer),
) -> list[ClientDocumentOut]:
    rows = (
        db.query(ClientDocument)
        .filter(ClientDocument.customer_id == user.id)
        .order_by(ClientDocument.id.desc())
        .all()
    )
    return [ClientDocumentOut.model_validate(d) for d in rows]


@router.post("/documents", response_model=ClientDocumentOut)
def add_document(
    body: ClientDocumentIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_customer),
) -> ClientDocumentOut:
    if body.customer_policy_id:
        cp = db.get(CustomerPolicy, body.customer_policy_id)
        if not cp or cp.customer_id != user.id:
            raise HTTPException(status_code=400, detail="Полис не найден")
    if body.claim_id:
        cl = db.get(Claim, body.claim_id)
        if not cl or cl.customer_id != user.id:
            raise HTTPException(status_code=400, detail="Убыток не найден")

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = f"u{user.id}_{int(datetime.utcnow().timestamp())}.txt"
    path = DOCS_DIR / safe_name
    path.write_text(
        f"{body.title}\n{body.kind}\n{body.note}\n",
        encoding="utf-8",
    )
    doc = ClientDocument(
        customer_id=user.id,
        customer_policy_id=body.customer_policy_id,
        claim_id=body.claim_id,
        title=body.title.strip(),
        kind=body.kind,
        file_path=str(path.relative_to(ROOT)).replace("\\", "/"),
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return ClientDocumentOut.model_validate(doc)


# --- notifications ---
@router.get("/notifications", response_model=list[NotificationOut])
def my_notifications(
    db: Session = Depends(get_db),
    user: User = Depends(require_customer),
) -> list[NotificationOut]:
    rows = (
        db.query(Notification)
        .filter(Notification.user_id == user.id)
        .order_by(Notification.id.desc())
        .limit(50)
        .all()
    )
    return [NotificationOut.model_validate(n) for n in rows]


@router.post("/notifications/read-all")
def read_all_notifications(
    db: Session = Depends(get_db),
    user: User = Depends(require_customer),
) -> dict:
    rows = (
        db.query(Notification)
        .filter(Notification.user_id == user.id, Notification.is_read == 0)
        .all()
    )
    for r in rows:
        r.is_read = 1
    db.commit()
    return {"ok": True, "updated": len(rows)}
