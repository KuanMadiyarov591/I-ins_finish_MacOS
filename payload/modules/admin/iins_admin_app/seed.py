from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from iins_admin_app.auth import hash_password, verify_password
from iins_admin_app.models import Agent, Category, Policy, User
from iins_admin_app.services.policy_activation import activate_policy_on_approval
from iins_admin_app.models import PolicyApplication

DEMO_ADMIN_USER = "admin"
DEMO_ADMIN_PASS = "admin123"
DEMO_CLIENT_USER = "client"
DEMO_CLIENT_PASS = "client123"


def ensure_demo_credentials(db: Session) -> None:
    """Гарантировать вход demo-учёток admin/admin123 и client/client123."""
    admin = (
        db.query(User)
        .filter(func.lower(User.username) == DEMO_ADMIN_USER)
        .first()
    )
    if not admin:
        admin = User(
            username=DEMO_ADMIN_USER,
            password_hash=hash_password(DEMO_ADMIN_PASS),
            first_name="Админ",
            last_name="Системы",
            role="admin",
            address="офис",
            mobile="+70000000000",
        )
        db.add(admin)
    else:
        admin.username = DEMO_ADMIN_USER
        admin.role = "admin"
        # Не выполняем UPDATE при каждом запуске: это снижает риск проблем
        # с SQLite-журналом после некорректного завершения приложения.
        try:
            password_ok = verify_password(DEMO_ADMIN_PASS, admin.password_hash)
        except Exception:  # повреждённый или несовместимый hash
            password_ok = False
        if not password_ok:
            admin.password_hash = hash_password(DEMO_ADMIN_PASS)

    client = (
        db.query(User)
        .filter(func.lower(User.username) == DEMO_CLIENT_USER)
        .first()
    )
    if not client:
        client = User(
            username=DEMO_CLIENT_USER,
            password_hash=hash_password(DEMO_CLIENT_PASS),
            first_name="Иван",
            last_name="Клиентов",
            role="customer",
            address="г. Москва",
            mobile="+79001112233",
        )
        db.add(client)
    else:
        client.username = DEMO_CLIENT_USER
        if client.role != "customer":
            client.role = "customer"
        try:
            password_ok = verify_password(DEMO_CLIENT_PASS, client.password_hash)
        except Exception:  # повреждённый или несовместимый hash
            password_ok = False
        if not password_ok:
            client.password_hash = hash_password(DEMO_CLIENT_PASS)

    db.commit()


def seed_if_empty(db: Session) -> None:
    ensure_demo_credentials(db)

    if db.query(Category).first():
        ensure_portal_extras(db)
        return

    cats = [
        Category(name="Страхование жизни"),
        Category(name="Медицинское страхование"),
        Category(name="Автострахование"),
        Category(name="Туристическое страхование"),
        Category(name="Имущественное страхование"),
    ]
    db.add_all(cats)
    db.flush()

    policies = [
        Policy(
            category_id=cats[0].id,
            name="Жизнь Плюс",
            sum_assurance=2_000_000,
            premium=12_000,
            tenure=10,
            description="Страхование жизни с выплатой по риску смерти и инвалидности.",
        ),
        Policy(
            category_id=cats[1].id,
            name="МедСтандарт",
            sum_assurance=500_000,
            premium=8_500,
            tenure=1,
            description="ДМС: амбулаторная и стационарная помощь, экстренная госпитализация.",
        ),
        Policy(
            category_id=cats[2].id,
            name="АвтоКомфорт",
            sum_assurance=1_500_000,
            premium=15_000,
            tenure=1,
            description="КАСКО: ущерб, угон, ДТП. Франшиза по согласованию.",
        ),
        Policy(
            category_id=cats[3].id,
            name="Турист Safe",
            sum_assurance=100_000,
            premium=2_500,
            tenure=1,
            description="Медицинские расходы за рубежом, багаж, отмена поездки.",
        ),
        Policy(
            category_id=cats[4].id,
            name="Дом и Квартира",
            sum_assurance=3_000_000,
            premium=9_000,
            tenure=1,
            description="Имущество: пожар, затопление, кража со взломом, стихийные бедствия.",
        ),
    ]
    db.add_all(policies)
    db.commit()
    ensure_portal_extras(db)


def ensure_portal_extras(db: Session) -> None:
    """Демо-агент + привязка к client; активация уже одобренных заявок."""
    # Унификация названия travel-продукта (старые демо-БД)
    for p in db.query(Policy).filter(Policy.name.in_(["Travel Safe", "TravelSafe", "Travel"])).all():
        p.name = "Турист Safe"

    agent = db.query(Agent).first()
    if not agent:
        agent = Agent(
            first_name="Анна",
            last_name="Агентова",
            email="agent@insuradesk.local",
            phone="+79005554433",
            specialization="Жизнь, имущество, авто",
        )
        db.add(agent)
        db.flush()

    client = db.query(User).filter(User.username == "client").first()
    if client and not client.agent_id:
        client.agent_id = agent.id

    # активировать ранее одобренные заявки без CustomerPolicy
    approved = (
        db.query(PolicyApplication)
        .filter(PolicyApplication.status == "Approved")
        .all()
    )
    for app in approved:
        activate_policy_on_approval(db, app)

    db.commit()
