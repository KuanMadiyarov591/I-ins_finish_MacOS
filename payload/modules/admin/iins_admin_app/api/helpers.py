from __future__ import annotations

from iins_admin_app.models import Policy, PolicyApplication, Question, User
from iins_admin_app.schemas import ApplicationOut, PolicyOut, QuestionOut, UserOut


def user_out(u: User) -> UserOut:
    return UserOut.model_validate(u)


def policy_out(p: Policy) -> PolicyOut:
    return PolicyOut(
        id=p.id,
        category_id=p.category_id,
        category_name=p.category.name if p.category else "",
        name=p.name,
        sum_assurance=p.sum_assurance,
        premium=p.premium,
        tenure=p.tenure,
        description=p.description or "",
        creation_date=p.creation_date,
    )


def application_out(a: PolicyApplication) -> ApplicationOut:
    return ApplicationOut(
        id=a.id,
        customer_id=a.customer_id,
        customer_name=f"{a.customer.first_name} {a.customer.last_name}".strip()
        if a.customer
        else "",
        policy_id=a.policy_id,
        policy_name=a.policy.name if a.policy else "",
        status=a.status,
        admin_comment=a.admin_comment or "",
        creation_date=a.creation_date,
    )


def question_out(q: Question) -> QuestionOut:
    return QuestionOut(
        id=q.id,
        customer_id=q.customer_id,
        customer_name=f"{q.customer.first_name} {q.customer.last_name}".strip()
        if q.customer
        else "",
        description=q.description,
        admin_comment=q.admin_comment or "",
        status=q.status,
        asked_date=q.asked_date,
    )
