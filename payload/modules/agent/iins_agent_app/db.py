from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from iins_agent_app.config import get_settings

settings = get_settings()
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def migrate_schema() -> None:
    """Добавить колонки оплаты/комиссии в существующую SQLite без пересоздания БД."""
    if not settings.database_url.startswith("sqlite"):
        return
    insp = inspect(engine)
    if "applications" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("applications")}
    alters = [
        ("payment_status", "VARCHAR(32) DEFAULT 'unpaid'"),
        ("payment_method", "VARCHAR(32) DEFAULT ''"),
        ("next_payment_date", "VARCHAR(16) DEFAULT ''"),
        ("commission_pct", "FLOAT DEFAULT 10.0"),
        ("commission_amount", "INTEGER"),
    ]
    with engine.begin() as conn:
        for name, ddl in alters:
            if name not in cols:
                conn.execute(text(f"ALTER TABLE applications ADD COLUMN {name} {ddl}"))