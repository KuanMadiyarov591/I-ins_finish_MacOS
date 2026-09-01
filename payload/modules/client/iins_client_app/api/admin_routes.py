from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from iins_client_app.api.helpers import application_out, policy_out, question_out, user_out
from iins_client_app.auth import hash_password, require_admin
from iins_client_app.db import get_db
from iins_client_app.models import (
    Agent,
    Category,
    Claim,
    Notification,
    Policy,
    PolicyApplication,
    Question,
    User,
)
from iins_client_app.schemas import (
    AgentIn,
    AgentOut,
    ApplicationDecisionIn,
    ApplicationOut,
    AssignAgentIn,
    CategoryIn,
    CategoryOut,
    ClaimDecisionIn,
    ClaimOut,
    DashboardStats,
    NotificationOut,
    PolicyIn,
    PolicyOut,
    QuestionAnswerIn,
    QuestionOut,
    SignupIn,
    UserOut,
    UserUpdateIn,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/dashboard", response_model=DashboardStats)
def dashboard(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> DashboardStats:
    apps = db.query(PolicyApplication)
    unread = (
        db.query(Notification)
        .filter(Notification.user_id == admin.id, Notification.is_read == 0)
        .count()
    )
    return DashboardStats(
        total_customers=db.query(User).filter(User.role == "customer").count(),
        total_policies=db.query(Policy).count(),
        total_categories=db.query(Category).count(),
        total_questions=db.query(Question).count(),
        total_applications=apps.count(),
        approved_applications=apps.filter(PolicyApplication.status == "Approved").count(),
        disapproved_applications=apps.filter(PolicyApplication.status == "Disapproved").count(),
        pending_applications=apps.filter(PolicyApplication.status == "Pending").count(),
        unread_notifications=unread,
    )


@router.get("/notifications", response_model=list[NotificationOut])
def notifications(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> list[NotificationOut]:
    rows = (
        db.query(Notification)
        .filter(Notification.user_id == admin.id)
        .order_by(Notification.id.desc())
        .limit(50)
        .all()
    )
    return [NotificationOut.model_validate(r) for r in rows]


@router.post("/notifications/read-all")
def read_all_notifications(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    rows = (
        db.query(Notification)
        .filter(Notification.user_id == admin.id, Notification.is_read == 0)
        .all()
    )
    for r in rows:
        r.is_read = 1
    db.commit()
    return {"ok": True, "updated": len(rows)}


# --- customers ---
@router.get("/customers", response_model=list[UserOut])
def list_customers(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> list[UserOut]:
    rows = db.query(User).filter(User.role == "customer").order_by(User.id).all()
    return [user_out(u) for u in rows]


@router.post("/customers", response_model=UserOut)
def create_customer(
    body: SignupIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> UserOut:
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(status_code=400, detail="Имя пользователя уже занято")
    user = User(
        username=body.username.strip(),
        password_hash=hash_password(body.password),
        first_name=body.first_name.strip(),
        last_name=body.last_name.strip(),
        role="customer",
        address=body.address.strip(),
        mobile=body.mobile.strip(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user_out(user)


@router.put("/customers/{customer_id}", response_model=UserOut)
def update_customer(
    customer_id: int,
    body: UserUpdateIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> UserOut:
    user = db.get(User, customer_id)
    if not user or user.role != "customer":
        raise HTTPException(status_code=404, detail="Клиент не найден")
    if body.first_name is not None:
        user.first_name = body.first_name
    if body.last_name is not None:
        user.last_name = body.last_name
    if body.address is not None:
        user.address = body.address
    if body.mobile is not None:
        user.mobile = body.mobile
    if body.password:
        user.password_hash = hash_password(body.password)
    db.commit()
    db.refresh(user)
    return user_out(user)


@router.delete("/customers/{customer_id}")
def delete_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    user = db.get(User, customer_id)
    if not user or user.role != "customer":
        raise HTTPException(status_code=404, detail="Клиент не найден")
    db.delete(user)
    db.commit()
    return {"ok": True}


# --- categories ---
@router.get("/categories", response_model=list[CategoryOut])
def list_categories(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> list[CategoryOut]:
    return [CategoryOut.model_validate(c) for c in db.query(Category).order_by(Category.id).all()]


@router.post("/categories", response_model=CategoryOut)
def add_category(
    body: CategoryIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> CategoryOut:
    if db.query(Category).filter(Category.name == body.name.strip()).first():
        raise HTTPException(status_code=400, detail="Категория уже существует")
    cat = Category(name=body.name.strip())
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return CategoryOut.model_validate(cat)


@router.put("/categories/{category_id}", response_model=CategoryOut)
def update_category(
    category_id: int,
    body: CategoryIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> CategoryOut:
    cat = db.get(Category, category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Категория не найдена")
    cat.name = body.name.strip()
    db.commit()
    db.refresh(cat)
    return CategoryOut.model_validate(cat)


@router.delete("/categories/{category_id}")
def delete_category(
    category_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    cat = db.get(Category, category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Категория не найдена")
    db.delete(cat)
    db.commit()
    return {"ok": True}


# --- policies ---
@router.get("/policies", response_model=list[PolicyOut])
def list_policies(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> list[PolicyOut]:
    rows = db.query(Policy).options(joinedload(Policy.category)).order_by(Policy.id).all()
    return [policy_out(p) for p in rows]


@router.post("/policies", response_model=PolicyOut)
def add_policy(
    body: PolicyIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> PolicyOut:
    if not db.get(Category, body.category_id):
        raise HTTPException(status_code=400, detail="Категория не найдена")
    p = Policy(
        category_id=body.category_id,
        name=body.name.strip(),
        sum_assurance=body.sum_assurance,
        premium=body.premium,
        tenure=body.tenure,
        description=body.description.strip(),
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    p = db.query(Policy).options(joinedload(Policy.category)).filter(Policy.id == p.id).one()
    return policy_out(p)


@router.put("/policies/{policy_id}", response_model=PolicyOut)
def update_policy(
    policy_id: int,
    body: PolicyIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> PolicyOut:
    p = db.get(Policy, policy_id)
    if not p:
        raise HTTPException(status_code=404, detail="Полис не найден")
    if not db.get(Category, body.category_id):
        raise HTTPException(status_code=400, detail="Категория не найдена")
    p.category_id = body.category_id
    p.name = body.name.strip()
    p.sum_assurance = body.sum_assurance
    p.premium = body.premium
    p.tenure = body.tenure
    p.description = body.description.strip()
    db.commit()
    p = db.query(Policy).options(joinedload(Policy.category)).filter(Policy.id == p.id).one()
    return policy_out(p)


@router.delete("/policies/{policy_id}")
def delete_policy(
    policy_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    p = db.get(Policy, policy_id)
    if not p:
        raise HTTPException(status_code=404, detail="Полис не найден")
    db.delete(p)
    db.commit()
    return {"ok": True}


# --- applications ---
@router.get("/applications", response_model=list[ApplicationOut])
def list_applications(
    status: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[ApplicationOut]:
    q = db.query(PolicyApplication).options(
        joinedload(PolicyApplication.customer),
        joinedload(PolicyApplication.policy),
    )
    if status:
        q = q.filter(PolicyApplication.status == status)
    return [application_out(a) for a in q.order_by(PolicyApplication.id.desc()).all()]


@router.post("/applications/{app_id}/decide", response_model=ApplicationOut)
def decide_application(
    app_id: int,
    body: ApplicationDecisionIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> ApplicationOut:
    from iins_client_app.services.policy_activation import activate_policy_on_approval

    if body.status not in ("Approved", "Disapproved"):
        raise HTTPException(status_code=400, detail="status: Approved или Disapproved")
    a = db.get(PolicyApplication, app_id)
    if not a:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    a.status = body.status
    a.admin_comment = body.admin_comment.strip()
    if body.status == "Approved":
        activate_policy_on_approval(db, a)
    elif body.status == "Disapproved":
        db.add(
            Notification(
                user_id=a.customer_id,
                message="Заявка на полис отклонена. " + (body.admin_comment or ""),
                is_read=0,
            )
        )
    db.commit()
    a = (
        db.query(PolicyApplication)
        .options(joinedload(PolicyApplication.customer), joinedload(PolicyApplication.policy))
        .filter(PolicyApplication.id == app_id)
        .one()
    )
    return application_out(a)


# --- claims (admin) ---
@router.get("/claims", response_model=list[ClaimOut])
def admin_list_claims(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[ClaimOut]:
    rows = (
        db.query(Claim)
        .options(joinedload(Claim.customer_policy))
        .order_by(Claim.id.desc())
        .all()
    )
    out: list[ClaimOut] = []
    for c in rows:
        cust = db.get(User, c.customer_id)
        name = f"{cust.first_name} {cust.last_name}".strip() if cust else ""
        out.append(
            ClaimOut(
                id=c.id,
                customer_policy_id=c.customer_policy_id,
                policy_number=c.customer_policy.policy_number if c.customer_policy else "",
                customer_id=c.customer_id,
                customer_name=name,
                claim_type=c.claim_type,
                description=c.description,
                claim_amount=c.claim_amount,
                status=c.status,
                admin_comment=c.admin_comment or "",
                claim_date=c.claim_date,
            )
        )
    return out


@router.post("/claims/{claim_id}/decide", response_model=ClaimOut)
def decide_claim(
    claim_id: int,
    body: ClaimDecisionIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> ClaimOut:
    if body.status not in ("InReview", "Approved", "Denied", "Paid"):
        raise HTTPException(status_code=400, detail="Недопустимый статус")
    c = db.get(Claim, claim_id)
    if not c:
        raise HTTPException(status_code=404, detail="Убыток не найден")
    c.status = body.status
    c.admin_comment = body.admin_comment.strip()
    c.updated_at = datetime.utcnow()
    db.add(
        Notification(
            user_id=c.customer_id,
            message=f"Статус убытка #{c.id}: {body.status}. {body.admin_comment}".strip(),
            is_read=0,
        )
    )
    db.commit()
    c = db.query(Claim).options(joinedload(Claim.customer_policy)).filter(Claim.id == claim_id).one()
    cust = db.get(User, c.customer_id)
    return ClaimOut(
        id=c.id,
        customer_policy_id=c.customer_policy_id,
        policy_number=c.customer_policy.policy_number if c.customer_policy else "",
        customer_id=c.customer_id,
        customer_name=f"{cust.first_name} {cust.last_name}".strip() if cust else "",
        claim_type=c.claim_type,
        description=c.description,
        claim_amount=c.claim_amount,
        status=c.status,
        admin_comment=c.admin_comment or "",
        claim_date=c.claim_date,
    )


# --- agents ---
@router.get("/agents", response_model=list[AgentOut])
def list_agents(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> list[AgentOut]:
    return [AgentOut.model_validate(a) for a in db.query(Agent).order_by(Agent.id).all()]


@router.post("/agents", response_model=AgentOut)
def create_agent(
    body: AgentIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> AgentOut:
    agent = Agent(
        first_name=body.first_name.strip(),
        last_name=body.last_name.strip(),
        email=body.email.strip(),
        phone=body.phone.strip(),
        specialization=body.specialization.strip(),
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return AgentOut.model_validate(agent)


@router.post("/agents/assign")
def assign_agent(
    body: AssignAgentIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    customer = db.get(User, body.customer_id)
    agent = db.get(Agent, body.agent_id)
    if not customer or customer.role != "customer":
        raise HTTPException(status_code=404, detail="Клиент не найден")
    if not agent:
        raise HTTPException(status_code=404, detail="Агент не найден")
    customer.agent_id = agent.id
    db.add(
        Notification(
            user_id=customer.id,
            message=f"Вам назначен агент {agent.first_name} {agent.last_name} ({agent.phone})",
            is_read=0,
        )
    )
    db.commit()
    return {"ok": True, "customer_id": customer.id, "agent_id": agent.id}


# --- questions ---
@router.get("/questions", response_model=list[QuestionOut])
def list_questions(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> list[QuestionOut]:
    rows = (
        db.query(Question)
        .options(joinedload(Question.customer))
        .order_by(Question.id.desc())
        .all()
    )
    return [question_out(q) for q in rows]


@router.put("/questions/{question_id}", response_model=QuestionOut)
def answer_question(
    question_id: int,
    body: QuestionAnswerIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> QuestionOut:
    q = db.get(Question, question_id)
    if not q:
        raise HTTPException(status_code=404, detail="Вопрос не найден")
    q.admin_comment = body.admin_comment.strip()
    q.status = "Answered"
    db.add(
        Notification(
            user_id=q.customer_id,
            message=f"Ответ администратора на ваш вопрос: {body.admin_comment[:120]}",
            is_read=0,
        )
    )
    db.commit()
    q = db.query(Question).options(joinedload(Question.customer)).filter(Question.id == question_id).one()
    return question_out(q)
