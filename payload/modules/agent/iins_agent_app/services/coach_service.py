"""CRM-aware coach actions (inspired by Moneta ins-crm / advisor tools).

Actions for insurance agents: call prep, email draft, objection handling, follow-up.
Uses existing RAG + optional Ollama; no Azure Foundry/Cosmos.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session, joinedload

from iins_agent_app.models import Application, Client
from iins_agent_app.services import rag_service
from iins_agent_app.services.priority_service import PRIORITY_LABELS, PRIORITY_SHORT

ACTIONS = ("call_prep", "email_draft", "objection", "follow_up", "client_brief")


def _crm_blob(client: Client, open_apps: int) -> str:
    tags = ", ".join(t.name for t in (client.tags or [])) or "—"
    return (
        f"Клиент: {client.full_name} ({client.external_id})\n"
        f"Приоритет: {PRIORITY_LABELS.get(client.priority, client.priority)}\n"
        f"Статус CRM: {client.status}; телефон: {client.phone or '—'}; email: {client.email or '—'}\n"
        f"Возраст: {client.age}; доход: {client.annual_income}; семья: {client.family_members}\n"
        f"FrequentFlyer={client.frequent_flyer}; Abroad={client.ever_travelled_abroad}; "
        f"Chronic={client.chronic_diseases}; coverage_change={client.coverage_change}\n"
        f"Теги: [{tags}]; открытых заявок: {open_apps}\n"
        f"Travel propensity: {client.buy_probability}; tier: {client.propensity_tier}\n"
        f"Заметки: {client.notes or '—'}"
    )


def _question_for(action: str, client: Client, objection: str, lang: str) -> str:
    name = client.full_name
    prio = PRIORITY_SHORT.get(client.priority, str(client.priority))
    if action == "call_prep":
        return (
            f"Подготовь страхового агента к звонку клиенту {name} ({prio}). "
            f"Дай: цель звонка, 4 discovery-вопроса, предлагаемый продукт, "
            f"opening script на 30 секунд, next step. Язык: {lang}."
        )
    if action == "email_draft":
        return (
            f"Напиши короткий деловой email-черновик клиенту {name} от страхового агента. "
            f"Тема + тело (приветствие, ценность, CTA follow-up). Без выдуманных сумм. Язык: {lang}."
        )
    if action == "objection":
        obj = objection.strip() or "дорого"
        return (
            f"Клиент {name} возражает: «{obj}». "
            f"Дай скрипт ответа агента + 2 уточняющих вопроса + мягкий closing. Язык: {lang}."
        )
    if action == "follow_up":
        return (
            f"Составь план follow-up для клиента {name} ({prio}): "
            f"когда связаться, канал (звонок/сообщение), текст касания, что проверить в CRM. Язык: {lang}."
        )
    # client_brief — Moneta-style CRM specialist summary
    return (
        f"Сделай краткий CRM-brief по клиенту {name} для страхового агента: "
        f"профиль, риски/возможности, приоритет действий на сегодня, "
        f"какой продукт обсудить первым. Язык: {lang}."
    )


def run_coach(
    db: Session,
    *,
    action: str,
    client_id: int,
    objection: str = "",
    lang: str = "ru",
    mode: str = "auto",
) -> Dict[str, Any]:
    if action not in ACTIONS:
        raise ValueError(f"Неизвестное действие: {action}")

    client = (
        db.query(Client)
        .options(joinedload(Client.tags))
        .filter(Client.id == client_id)
        .first()
    )
    if not client:
        raise LookupError("Клиент не найден")

    open_apps = (
        db.query(Application)
        .filter(
            Application.client_id == client_id,
            Application.status.in_(["draft", "checklist", "submitted"]),
        )
        .count()
    )
    crm = _crm_blob(client, open_apps)
    question = _question_for(action, client, objection, lang)
    hint = f"CRM-профиль для агента:\n{crm}"

    result = rag_service.rag_query(
        question,
        top_k=5,
        policy_hint=hint,
        lang=lang,
        mode=mode,
    )
    result["action"] = action
    result["client_id"] = client.id
    result["client_name"] = client.full_name
    result["priority_short"] = PRIORITY_SHORT.get(client.priority, str(client.priority))
    return result
