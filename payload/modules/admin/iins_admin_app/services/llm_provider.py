"""Единый выбор языковой модели для всех кабинетов I-ins.

Три режима ответа:
  extractive — ответ строится только из найденных фрагментов базы знаний;
  ollama     — Qwen RAG: локальная модель Qwen через Ollama, контекст из базы знаний;
  gigachat   — GigaChat: облачная модель по API, контекст из базы знаний.

Во всех режимах, кроме extractive, модель получает только тот контекст,
который вернул поиск: без найденных фрагментов генерация не запускается.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

_log = logging.getLogger(__name__)

BACKENDS = ("extractive", "ollama", "gigachat")

LABELS = {
    "extractive": "RAG по базе знаний",
    "ollama": "Qwen RAG (локально)",
    "gigachat": "GigaChat (по API)",
}

_ALIASES = {
    "extractive": "extractive",
    "rag": "extractive",
    "corpus": "extractive",
    "ollama": "ollama",
    "qwen": "ollama",
    "qwen-rag": "ollama",
    "qwen_rag": "ollama",
    "local": "ollama",
    "gigachat": "gigachat",
    "giga": "gigachat",
    "gigachat-2-max": "gigachat",
}


def normalize(requested: Optional[str]) -> str:
    """Приводит запрошенный режим к каноническому виду или к 'auto'."""
    mode = (requested or "").strip().lower()
    if not mode or mode == "auto":
        return "auto"
    return _ALIASES.get(mode, "auto")


def backend_ready(backend: str) -> bool:
    if backend == "extractive":
        return True
    if backend == "ollama":
        try:
            from iins_admin_app.services.ollama_lm import ollama_is_ready

            return bool(ollama_is_ready())
        except Exception as exc:  # noqa: BLE001
            _log.debug("ollama readiness failed: %s", exc)
            return False
    if backend == "gigachat":
        try:
            from iins_admin_app.services.gigachat_lm import gigachat_is_ready

            return bool(gigachat_is_ready())
        except Exception as exc:  # noqa: BLE001
            _log.debug("gigachat readiness failed: %s", exc)
            return False
    return False


def resolve_backend(requested: Optional[str] = None) -> str:
    """extractive | ollama | gigachat — движок, которым будет дан ответ."""
    mode = normalize(requested)
    if mode == "auto":
        try:
            from iins_admin_app.config import get_settings

            mode = normalize(getattr(get_settings(), "lm_backend", "auto"))
        except Exception:  # noqa: BLE001
            mode = "auto"
    if mode == "auto":
        for candidate in ("ollama", "gigachat"):
            if backend_ready(candidate):
                return candidate
        return "extractive"
    return mode


def model_name(backend: str) -> str:
    try:
        from iins_admin_app.config import get_settings

        settings = get_settings()
    except Exception:  # noqa: BLE001
        settings = None
    if backend == "ollama":
        return getattr(settings, "ollama_model", "qwen") or "qwen"
    if backend == "gigachat":
        return getattr(settings, "gigachat_model", "gigachat") or "gigachat"
    return "extractive-tfidf"


def not_ready_message(backend: str) -> str:
    if backend == "ollama":
        return (
            "Выбран режим Qwen RAG, но локальная модель не готова. "
            "Запустите Ollama и выполните: ollama pull qwen2.5:1.5b"
        )
    if backend == "gigachat":
        try:
            from iins_admin_app.services.gigachat_lm import gigachat_status

            err = gigachat_status().get("error")
        except Exception:  # noqa: BLE001
            err = None
        return "Выбран режим GigaChat, но сервис недоступен." + (f" {err}" if err else "")
    return "Языковая модель недоступна."


def generate_reply(
    backend: str,
    user_instruction: str,
    *,
    max_new_tokens: int = 384,
    temperature: float = 0.35,
    system_prompt: Optional[str] = None,
) -> str:
    if backend == "gigachat":
        from iins_admin_app.services.gigachat_lm import generate_gigachat_reply

        return generate_gigachat_reply(
            user_instruction,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            system_prompt=system_prompt,
        )
    from iins_admin_app.services.ollama_lm import generate_ollama_reply

    return generate_ollama_reply(
        user_instruction,
        max_new_tokens=max_new_tokens,
        temperature=temperature,
        system_prompt=system_prompt,
    )


def providers_status() -> dict[str, Any]:
    """Состояние всех движков ответа — для строки состояния и переключателя."""
    try:
        from iins_admin_app.services.ollama_lm import ollama_status

        ollama = ollama_status()
    except Exception as exc:  # noqa: BLE001
        ollama = {"model": "", "model_ready": False, "available": False, "error": str(exc)}
    try:
        from iins_admin_app.services.gigachat_lm import gigachat_status

        gigachat = gigachat_status()
    except Exception as exc:  # noqa: BLE001
        gigachat = {"model": "", "model_ready": False, "available": False, "error": str(exc)}
    return {
        "modes": ["auto", *BACKENDS],
        "labels": dict(LABELS),
        "ollama": ollama,
        "gigachat": gigachat,
        "providers": {
            "extractive": {
                "id": "extractive",
                "label": LABELS["extractive"],
                "ready": True,
                "model": "tf-idf",
                "error": None,
            },
            "ollama": {
                "id": "ollama",
                "label": LABELS["ollama"],
                "ready": bool(ollama.get("model_ready")),
                "model": ollama.get("model") or "",
                "error": ollama.get("error"),
            },
            "gigachat": {
                "id": "gigachat",
                "label": LABELS["gigachat"],
                "ready": bool(gigachat.get("available")),
                "model": gigachat.get("model") or "",
                "error": gigachat.get("error"),
            },
        },
    }
