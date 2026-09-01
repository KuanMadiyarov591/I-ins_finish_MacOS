"""Клиент GigaChat: OpenAI-совместимый эндпоинт /v1/chat/completions.

Ключ берётся, в порядке приоритета:
  1) настройка gigachat_api_key (файл .env кабинета);
  2) переменная окружения GIGACHAT_API_KEY или I_INS_GIGACHAT_KEY;
  3) файл gigachat.key рядом с кабинетом, рядом с комплектом или в ~/.i-ins/.
В исходном коде ключ не хранится.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

import httpx

from iins_admin_app.config import get_settings

_log = logging.getLogger(__name__)

_PROBE_TTL = 60.0
_probe: dict[str, Any] = {"ts": 0.0, "ok": False, "error": "не проверено"}

_DEFAULT_SYSTEM = (
    "Ты — деловой помощник информационной системы I-ins. "
    "Отвечай по существу, 1–4 коротких абзаца. "
    "Опирайся только на переданный контекст, ничего не выдумывай. "
    "Не указывай имена файлов и технические источники. "
    "Язык ответа — как у вопроса пользователя."
)


def _key_files() -> list[Path]:
    root = Path(__file__).resolve().parent.parent.parent  # каталог кабинета
    return [
        root / "gigachat.key",
        root.parent / "gigachat.key",
        Path.home() / ".i-ins" / "gigachat.key",
    ]


def api_key() -> str:
    """Ключ доступа к GigaChat или пустая строка, если он не задан."""
    key = (getattr(get_settings(), "gigachat_api_key", "") or "").strip()
    if key:
        return key
    for var in ("GIGACHAT_API_KEY", "I_INS_GIGACHAT_KEY"):
        value = (os.environ.get(var) or "").strip()
        if value:
            return value
    for path in _key_files():
        try:
            if path.is_file():
                value = path.read_text(encoding="utf-8").strip()
                if value:
                    return value
        except OSError:  # noqa: PERF203
            continue
    return ""


def base_url() -> str:
    return (getattr(get_settings(), "gigachat_base_url", "") or "").rstrip("/")


def model_name() -> str:
    return getattr(get_settings(), "gigachat_model", "") or "GigaChat"


def _timeout() -> float:
    try:
        return float(getattr(get_settings(), "gigachat_timeout", 60.0) or 60.0)
    except (TypeError, ValueError):
        return 60.0


def gigachat_configured() -> bool:
    return bool(base_url()) and bool(api_key())


def _probe_now() -> tuple[bool, Optional[str]]:
    url = base_url()
    key = api_key()
    if not url:
        return False, "Не задан адрес GigaChat"
    if not key:
        return False, "Не задан ключ GigaChat: GIGACHAT_API_KEY или файл gigachat.key"
    try:
        with httpx.Client(timeout=min(_timeout(), 10.0), trust_env=False) as client:
            r = client.get(f"{url}/models", headers={"Authorization": f"Bearer {key}"})
    except Exception as exc:  # noqa: BLE001
        return False, f"GigaChat недоступен: {exc}"
    if r.status_code in (401, 403):
        return False, "Ключ GigaChat отклонён сервисом"
    if r.status_code >= 500:
        return False, f"GigaChat отвечает ошибкой {r.status_code}"
    return True, None


def gigachat_is_ready(force: bool = False) -> bool:
    now = time.monotonic()
    if force or now - float(_probe.get("ts") or 0.0) > _PROBE_TTL:
        ok, err = _probe_now()
        _probe.update({"ts": now, "ok": ok, "error": err})
    return bool(_probe.get("ok"))


def gigachat_status() -> dict[str, Any]:
    ready = gigachat_is_ready()
    return {
        "base_url": base_url(),
        "model": model_name(),
        "configured": gigachat_configured(),
        "reachable": ready,
        "model_ready": ready,
        "available": ready,
        "error": None if ready else _probe.get("error"),
    }


def generate_gigachat_reply(
    user_instruction: str,
    *,
    max_new_tokens: int = 384,
    temperature: float = 0.35,
    system_prompt: Optional[str] = None,
) -> str:
    url = base_url()
    key = api_key()
    if not url or not key:
        raise FileNotFoundError(
            "GigaChat не настроен. Задайте переменную GIGACHAT_API_KEY "
            "или положите ключ в файл gigachat.key рядом с комплектом."
        )
    payload = {
        "model": model_name(),
        "messages": [
            {"role": "system", "content": (system_prompt or _DEFAULT_SYSTEM).strip()},
            {"role": "user", "content": user_instruction.strip()},
        ],
        "max_tokens": max(32, min(int(max_new_tokens), 2048)),
        "temperature": max(0.0, min(float(temperature), 1.0)),
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    try:
        with httpx.Client(timeout=_timeout(), trust_env=False) as client:
            r = client.post(f"{url}/chat/completions", json=payload, headers=headers)
    except Exception as exc:  # noqa: BLE001
        _probe.update({"ts": time.monotonic(), "ok": False, "error": str(exc)})
        raise RuntimeError(f"GigaChat недоступен: {exc}") from exc
    if r.status_code in (401, 403):
        _probe.update({"ts": time.monotonic(), "ok": False, "error": "ключ отклонён"})
        raise RuntimeError("GigaChat отклонил ключ доступа")
    if r.status_code >= 400:
        raise RuntimeError(f"GigaChat вернул ошибку {r.status_code}: {r.text[:300]}")
    try:
        data = r.json()
    except ValueError as exc:
        raise RuntimeError("GigaChat вернул неразбираемый ответ") from exc
    text = _extract_text(data)
    if not text:
        raise RuntimeError("GigaChat вернул пустой ответ — повторите запрос.")
    if len(text) > 2800:
        text = text[:2800].rsplit(" ", 1)[0] + "…"
    _probe.update({"ts": time.monotonic(), "ok": True, "error": None})
    return text


def _extract_text(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    choices = data.get("choices") or []
    if choices and isinstance(choices, list):
        first = choices[0] or {}
        message = first.get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):  # части сообщения
            parts = [p.get("text", "") for p in content if isinstance(p, dict)]
            return "".join(parts).strip()
        text = first.get("text")
        if isinstance(text, str):
            return text.strip()
    return ""
