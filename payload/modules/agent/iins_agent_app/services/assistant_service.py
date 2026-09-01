"""Цифровой помощник (lite): сводка + рекомендации продуктов."""

from __future__ import annotations

from typing import Any, Dict, List

from iins_agent_app.models import Application, Client, PolicyProduct
from iins_agent_app.services import recommend_service
from iins_agent_app.services.priority_service import PRIORITY_LABELS, PRIORITY_SHORT


def client_summary(
    client: Client,
    applications: List[Application],
    products: List[PolicyProduct],
    *,
    lang: str = "ru",
) -> Dict[str, Any]:
    open_apps = [a for a in applications if a.status in ("draft", "checklist", "submitted")]
    prod_by_id = {p.id: p for p in products}
    reco = recommend_service.recommend_for_client(client, products, top_k=3, lang=lang)
    top = (reco.get("recommendations") or [{}])[0]
    rec_name = top.get("policy_name") or "—"

    lines = [
        f"{client.full_name} ({client.external_id})",
        f"{PRIORITY_LABELS.get(client.priority, client.priority)}",
        f"{client.phone or '—'} / {client.email or '—'}",
        f"Открытых заявок: {len(open_apps)}",
    ]
    ml = reco.get("ml") or {}
    if ml.get("buy_probability") is not None:
        lines.append(
            f"Travel propensity: {float(ml['buy_probability']):.0%} · {ml.get('propensity_tier') or '—'}"
        )
    if client.coverage_change:
        lines.append("Флаг: изменение покрытия")
    lines.append(f"Топ-рекомендация: {rec_name}")

    app_brief = []
    for a in open_apps[:5]:
        p = prod_by_id.get(a.product_id)
        app_brief.append(
            {
                "id": a.id,
                "product": p.name if p else str(a.product_id),
                "status": a.status,
                "checklist_ready": all(
                    [a.chk_contact_ok, a.chk_consent_ok, a.chk_docs_ok, a.chk_prefs_ok]
                ),
            }
        )

    return {
        "client_id": client.id,
        "headline": f"{client.full_name} · {PRIORITY_SHORT.get(client.priority, client.priority)}",
        "summary_text": "\n".join(lines),
        "recommended_product": rec_name,
        "recommendations": reco.get("recommendations") or [],
        "ml": ml,
        "open_applications": app_brief,
        "priority_label": PRIORITY_LABELS.get(client.priority, str(client.priority)),
        "priority_short": PRIORITY_SHORT.get(client.priority, str(client.priority)),
        "tags": [t.name for t in (client.tags or [])],
    }
