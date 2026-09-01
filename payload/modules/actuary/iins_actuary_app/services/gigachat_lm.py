"""Клиент GigaChat: OpenAI-совместимый эндпоинт /v1/chat/completions.

Ключ берётся, в порядке приоритета:
  1) настройка gigachat_api_key (файл .env кабинета);
  2) переменная окружения GIGACHAT_API_KEY или I_INS_GIGACHAT_KEY;
  3) файл gigachat.key рядом с кабинетом, рядом с комплектом или в ~/.i-ins/.
В исходном коде ключ не хранится.

Два разных состояния, которые нельзя путать:
  configured — ключ и адрес заданы. Этого достаточно, чтобы режим GigaChat
               можно было ВЫБРАТЬ в кабинете;
  ready      — пробный запрос к сервису прошёл. Требуется только для режима
               «Авто», который сам решает, к какой модели обратиться.
Если сеть отвечает через прокси или сервис медленный, проба может не пройти —
но пользователь всё равно должен иметь возможность выбрать GigaChat и увидеть
настоящую ошибку запроса, а не серый пункт в списке.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

import httpx

from iins_actuary_app.config import get_settings

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
    candidates = [
        root / "gigachat.key",
        root.parent / "gigachat.key",
        root.parent.parent / "gigachat.key",
        Path.home() / ".i-ins" / "gigachat.key",
    ]
    data_root = os.getenv("IINS_DATA_ROOT")
    if data_root:
        candidates.insert(0, Path(data_root).expanduser() / "gigachat.key")
    return candidates


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


def _client(timeout: float) -> httpx.Client:
    """Клиент, уважающий системные настройки прокси — как это делает curl.

    Раньше здесь стояло trust_env=False, и в сети с прокси проба падала, хотя
    установщик тем же ключом через curl проходил. Расхождение и приводило к
    тому, что режим GigaChat оказывался недоступен.
    """
    return httpx.Client(timeout=timeout, trust_env=True, follow_redirects=True)


def gigachat_configured() -> bool:
    """Ключ и адрес заданы — режим можно выбирать."""
    return bool(base_url()) and bool(api_key())


def _probe_now() -> tuple[bool, Optional[str]]:
    url = base_url()
    key = api_key()
    if not url:
        return False, "не задан адрес сервиса"
    if not key:
        return False, "не задан ключ: GIGACHAT_API_KEY или файл gigachat.key"
    try:
        with _client(min(_timeout(), 15.0)) as client:
            r = client.get(f"{url}/models", headers={"Authorization": f"Bearer {key}"})
    except Exception as exc:  # noqa: BLE001
        return False, f"нет связи с {url}: {type(exc).__name__}: {exc}"
    if r.status_code in (401, 403):
        return False, f"ключ отклонён сервисом (HTTP {r.status_code})"
    if r.status_code >= 500:
        return False, f"сервис отвечает ошибкой {r.status_code}"
    return True, None


def gigachat_is_ready(force: bool = False) -> bool:
    """True, если пробный запрос прошёл. Для выбора режима достаточно configured."""
    now = time.monotonic()
    if force or now - float(_probe.get("ts") or 0.0) > _PROBE_TTL:
        ok, err = _probe_now()
        _probe.update({"ts": now, "ok": ok, "error": err})
    return bool(_probe.get("ok"))


def gigachat_status() -> dict[str, Any]:
    configured = gigachat_configured()
    ready = gigachat_is_ready() if configured else False
    return {
        "base_url": base_url(),
        "model": model_name(),
        "configured": configured,
        "selectable": configured,          # можно выбрать в кабинете
        "reachable": ready,
        "model_ready": ready,
        "available": ready,                # используется режимом «Авто»
        "error": None if ready else (
            _probe.get("error") if configured
            else "ключ не задан: положите его в файл gigachat.key или задайте GIGACHAT_API_KEY"
        ),
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
        with _client(_timeout()) as client:
            r = client.post(f"{url}/chat/completions", json=payload, headers=headers)
    except Exception as exc:  # noqa: BLE001
        _probe.update({"ts": time.monotonic(), "ok": False, "error": str(exc)})
        raise RuntimeError(f"GigaChat недоступен по адресу {url}: {exc}") from exc
    if r.status_code in (401, 403):
        _probe.update({"ts": time.monotonic(), "ok": False, "error": "ключ отклонён"})
        raise RuntimeError(f"GigaChat отклонил ключ доступа (HTTP {r.status_code})")
    if r.status_code >= 400:
        raise RuntimeError(f"GigaChat вернул ошибку {r.status_code}: {r.text[:300]}")
    try:
        data = r.json()
    except ValueError as exc:
        raise RuntimeError(f"GigaChat вернул неразбираемый ответ: {r.text[:200]}") from exc
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
    # некоторые совместимые сервисы отвечают полем output_text
    out = data.get("output_text")
    return out.strip() if isinstance(out, str) else ""
