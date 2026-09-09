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


def _family(model: str) -> str:
    """qwen2.5:1.5b -> qwen2.5"""
    return (model or "").split(":", 1)[0].strip().lower()


def pick_model(available: list[str], target: str | None = None) -> str:
    """Какую модель звать: точный тег, иначе тот же qwen, иначе любой qwen.

    Пользователь часто скачивает не тот тег, что записан в настройках
    (qwen2.5:3b вместо qwen2.5:1.5b, qwen3:4b вместо qwen2.5). Раньше кабинет
    в таком случае считал, что Qwen недоступен, хотя модель на машине была.
    """
    target = target or _model()
    if not available:
        return ""
    if target in available:
        return target
    base = _family(target)
    same = [n for n in available if _family(n) == base]
    if same:
        return sorted(same)[0]
    any_qwen = [n for n in available if _family(n).startswith("qwen")]
    if any_qwen:
        return sorted(any_qwen)[0]
    return ""


def _ping_root() -> bool:
    try:
        with httpx.Client(timeout=2.0, trust_env=False) as client:
            r = client.get(_base_url())
            return r.status_code < 500
    except Exception:  # noqa: BLE001
        return False


def active_model() -> str:
    """Модель, которой кабинет ответит прямо сейчас; пусто — Qwen недоступен."""
    return pick_model(ollama_list_models())


def ollama_is_ready() -> bool:
    return bool(active_model())


def ollama_status() -> dict[str, Any]:
    models = ollama_list_models()
    target = _model()
    chosen = pick_model(models, target)
    reachable = bool(models) or _ping_root()

    if chosen:
        error = None
    elif reachable:
        error = (
            f"Ollama отвечает на {_base_url()}, но модели Qwen нет. "
            f"Выполните: ollama pull {target}"
        )
    else:
        error = (
            f"Ollama недоступна на {_base_url()}. "
            "Запустите её командой: ollama serve"
        )

    return {
        "base_url": _base_url(),
        "model": chosen or target,
        "configured_model": target,
        "substituted": bool(chosen) and chosen != target,
        "reachable": reachable,
        "model_ready": bool(chosen),
        "available": bool(chosen),
        "available_models": models[:16],
        "error": error,
    }


def resolve_lm_backend(requested: Optional[str] = None) -> str:
    """extractive | ollama — итоговый движок ответа."""
    mode = (requested or get_settings().lm_backend or "auto").strip().lower()
    if mode in {"extractive", "rag"}:
        return "extractive"
    if mode == "ollama":
        return "ollama"
    return "ollama" if ollama_is_ready() else "extractive"


def _explain_http_error(response: Any, model: str) -> str:
    """Причина отказа словами: Ollama кладёт её в тело ответа, а не в статус.

    Раньше наружу уходило «Server error \'500 Internal Server Error\'» — по такому
    сообщению понять ничего нельзя. Тело почти всегда объясняет: модель не
    скачалась до конца, не хватило памяти, тег не найден.
    """
    detail = ""
    try:
        body = response.json()
        detail = str(body.get("error") or "").strip()
    except Exception:  # noqa: BLE001
        try:
            detail = (response.text or "").strip()[:300]
        except Exception:  # noqa: BLE001
            detail = ""

    low = detail.lower()
    if response.status_code == 404 or "not found" in low:
        return (
            f"Ollama не нашла модель {model}. Скачайте её заново: "
            f"ollama pull {model}" + (f" ({detail})" if detail else "")
        )
    if "memory" in low or "out of memory" in low or "insufficient" in low:
        return (
            f"Ollama не смогла загрузить {model}: не хватает памяти. "
            "Закройте тяжёлые программы или возьмите модель поменьше, "
            "например qwen2.5:0.5b." + (f" ({detail})" if detail else "")
        )
    if "no such file" in low or "unable to load" in low or "digest" in low:
        return (
            f"Файлы модели {model} неполные — загрузка оборвалась. "
            f"Скачайте заново: ollama pull {model}" + (f" ({detail})" if detail else "")
        )
    if detail:
        return f"Ollama ответила ошибкой на модели {model}: {detail}"
    return (
        f"Ollama ответила кодом {response.status_code} на модели {model}. "
        f"Проверьте её: ollama run {model} \"привет\""
    )


def generate_ollama_reply(
    user_instruction: str,
    *,
    max_new_tokens: int = 384,
    temperature: float = 0.35,
    system_prompt: Optional[str] = None,
) -> str:
    chosen = active_model()
    if not chosen:
        raise FileNotFoundError(ollama_status()["error"] or "Локальная модель Qwen не готова.")
    payload = {
        "model": chosen,
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
        if r.status_code >= 400:
            raise RuntimeError(_explain_http_error(r, chosen))
        data = r.json()
    message = data.get("message") or {}
    text = (message.get("content") or "").strip()
    if not text:
        raise RuntimeError("Ollama вернула пустой ответ — повторите запрос.")
    if len(text) > 2800:
        text = text[:2800].rsplit(" ", 1)[0] + "…"
    return text
