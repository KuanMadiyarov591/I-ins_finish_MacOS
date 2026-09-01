from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from iins_actuary_app.config import get_settings

_log = logging.getLogger(__name__)

_DEFAULT_SYSTEM = (
    "Ты — помощник актуария в Actuary Desk. "
    "Помогаешь с тарификацией, CGR, территориями и leakage, "
    "прогнозом selected_premium и рейтинговыми допущениями. "
    "Отвечай по существу, 1–4 коротких абзаца, деловой актуарный стиль. "
    "Не выдумывай суммы, сроки и условия вне контекста. "
    "Не указывай имена файлов и технические источники. "
    "Язык ответа — как у вопроса пользователя."
)


def _base_url() -> str:
    return get_settings().ollama_base_url.rstrip("/")


def _model() -> str:
    return get_settings().ollama_model


def ollama_list_models(timeout: float = 4.0) -> list[str]:
    try:
        with httpx.Client(timeout=timeout, trust_env=False) as client:
            r = client.get(f"{_base_url()}/api/tags")
            r.raise_for_status()
            data = r.json()
    except Exception as exc:  # noqa: BLE001
        _log.debug("ollama tags failed: %s", exc)
        return []
    names: list[str] = []
    for item in data.get("models") or []:
        name = item.get("name")
        if isinstance(name, str) and name:
            names.append(name)
    return names


def _model_present(model: str, available: list[str]) -> bool:
    if not available:
        return False
    base = model.split(":", 1)[0]
    for name in available:
        if name == model or name.startswith(f"{base}:") or name.startswith(f"{model}:"):
            return True
    return False


def _ping_root() -> bool:
    try:
        with httpx.Client(timeout=2.0, trust_env=False) as client:
            r = client.get(_base_url())
            return r.status_code < 500
    except Exception:  # noqa: BLE001
        return False


def ollama_is_ready() -> bool:
    models = ollama_list_models()
    return _model_present(_model(), models)


def ollama_status() -> dict[str, Any]:
    models = ollama_list_models()
    target = _model()
    ready = _model_present(target, models)
    return {
        "base_url": _base_url(),
        "model": target,
        "reachable": bool(models) or _ping_root(),
        "model_ready": ready,
        "available": ready,
        "available_models": models[:16],
        "error": None if ready else (
            f"Модель {target} не найдена. Запустите: .\\scripts\\setup_qwen_ollama.ps1"
            if _ping_root() or models
            else "Ollama недоступна на " + _base_url()
        ),
    }


def resolve_lm_backend(requested: Optional[str] = None) -> str:
    """extractive | ollama — итоговый движок ответа."""
    mode = (requested or get_settings().lm_backend or "auto").strip().lower()
    if mode in {"extractive", "rag"}:
        return "extractive"
    if mode == "ollama":
        return "ollama"
    return "ollama" if ollama_is_ready() else "extractive"


def generate_ollama_reply(
    user_instruction: str,
    *,
    max_new_tokens: int = 384,
    temperature: float = 0.35,
    system_prompt: Optional[str] = None,
) -> str:
    if not ollama_is_ready():
        raise FileNotFoundError(
            f"Локальная модель Qwen (Ollama) не готова. "
            f"Запустите Ollama и выполните: ollama pull {_model()} "
            f"или .\\scripts\\setup_qwen_ollama.ps1"
        )
    payload = {
        "model": _model(),
        "messages": [
            {"role": "system", "content": (system_prompt or _DEFAULT_SYSTEM).strip()},
            {"role": "user", "content": user_instruction.strip()},
        ],
        "stream": False,
        "options": {
            "num_predict": max(32, min(max_new_tokens, 1024)),
            "temperature": max(0.0, min(temperature, 1.0)),
        },
    }
    with httpx.Client(timeout=180.0, trust_env=False) as client:
        r = client.post(f"{_base_url()}/api/chat", json=payload)
        r.raise_for_status()
        data = r.json()
    message = data.get("message") or {}
    text = (message.get("content") or "").strip()
    if not text:
        raise RuntimeError("Ollama вернула пустой ответ — повторите запрос.")
    if len(text) > 2800:
        text = text[:2800].rsplit(" ", 1)[0] + "…"
    return text
