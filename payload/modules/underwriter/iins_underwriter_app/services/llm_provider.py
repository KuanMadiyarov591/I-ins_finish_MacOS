"""Единый выбор языковой модели для всех кабинетов I-ins.

Два режима ответа:
  extractive — ответ строится только из найденных фрагментов базы знаний;
  ollama     — Qwen RAG: локальная модель Qwen через Ollama, контекст из базы знаний.

В режиме ollama модель получает только тот контекст, который вернул поиск:
без найденных фрагментов генерация не запускается.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

_log = logging.getLogger(__name__)

BACKENDS = ("extractive", "ollama")

LABELS = {
    "extractive": "RAG по базе знаний",
    "ollama": "Qwen RAG (локально)",
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
            from iins_underwriter_app.services.ollama_lm import ollama_is_ready

            return bool(ollama_is_ready())
        except Exception as exc:  # noqa: BLE001
            _log.debug("ollama readiness failed: %s", exc)
            return False
    return False


def resolve_backend(requested: Optional[str] = None) -> str:
    """extractive | ollama — движок, которым будет дан ответ."""
    mode = normalize(requested)
    if mode == "auto":
        try:
            from iins_underwriter_app.config import get_settings

            mode = normalize(getattr(get_settings(), "lm_backend", "auto"))
        except Exception:  # noqa: BLE001
            mode = "auto"
    if mode == "auto":
        return "ollama" if backend_ready("ollama") else "extractive"
    return mode


def model_name(backend: str) -> str:
    """Имя модели для подписи ответа — то, которым отвечали на самом деле."""
    if backend == "ollama":
        try:
            from iins_underwriter_app.services.ollama_lm import active_model

            chosen = active_model()
            if chosen:
                return chosen
        except Exception as exc:  # noqa: BLE001
            _log.debug("active model lookup failed: %s", exc)
        try:
            from iins_underwriter_app.config import get_settings

            return getattr(get_settings(), "ollama_model", "qwen") or "qwen"
        except Exception:  # noqa: BLE001
            return "qwen"
    return "extractive-tfidf"


def not_ready_message(backend: str) -> str:
    if backend == "ollama":
        return (
            "Выбран режим Qwen RAG, но локальная модель не готова. "
            "Запустите Ollama и выполните: ollama pull qwen2.5:1.5b"
        )
    return "Языковая модель недоступна."


def generate_reply(
    backend: str,
    user_instruction: str,
    *,
    max_new_tokens: int = 384,
    temperature: float = 0.35,
    system_prompt: Optional[str] = None,
) -> str:
    from iins_underwriter_app.services.ollama_lm import generate_ollama_reply

    return generate_ollama_reply(
        user_instruction,
        max_new_tokens=max_new_tokens,
        temperature=temperature,
        system_prompt=system_prompt,
    )


def providers_status() -> dict[str, Any]:
    """Состояние всех движков ответа — для строки состояния и переключателя."""
    try:
        from iins_underwriter_app.services.ollama_lm import ollama_status

        ollama = ollama_status()
    except Exception as exc:  # noqa: BLE001
        ollama = {"model": "", "model_ready": False, "available": False, "error": str(exc)}
    return {
        "modes": ["auto", *BACKENDS],
        "labels": dict(LABELS),
        "ollama": ollama,
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
        },
    }
