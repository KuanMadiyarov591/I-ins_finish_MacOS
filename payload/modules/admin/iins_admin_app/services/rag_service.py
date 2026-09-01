"""Локальный RAG для Actuary Desk: TF-IDF + extractive или Ollama/Qwen."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from iins_admin_app.config import get_settings
from iins_admin_app.services.vector_rag_store import VectorRagStore

_RAG_SYSTEM = (
    "Ты — цифровой помощник администратора страховой платформы I-ins. "
    "Помогаешь управлять доступом, аудитом, персональными данными, информационной "
    "безопасностью и жизненным циклом ИИ/RAG. "
    "Отвечай строго на основе блока «Контекст из базы знаний». "
    "Если в контексте нет данных — скажи об этом явно. "
    "Не выдумывай суммы, сроки и условия вне контекста. "
    "Давай администратору практичный контрольный шаг и указывай границы его роли. "
    "1–4 коротких абзаца. Подтверждай факты ссылками вида [1], [2] на предоставленные источники."
)

_KK_LETTERS = set("әғқңөұүһіӘҒҚҢӨҰҮҺІ")

# Conservative grounding thresholds. A query without explicit insurance vocabulary
# must have stronger textual evidence before it is allowed to reach the LLM.
_MIN_RELEVANCE_SCORE = 0.18
_MIN_DOMAIN_RELEVANCE_SCORE = 0.10
_DOMAIN_TERMS = {
    "админ", "доступ", "роль", "аудит", "журнал", "инцидент", "персональн",
    "безопас", "защит", "информацион", "ии", "искусственн", "rag", "модел",
    "индекс", "гост", "757", "фтэк", "жизненн", "управлен", "страхов",
}

_ANSWER_LANG = {
    "ru": {
        "empty": (
            "В подключённой базе знаний нет достаточно релевантной информации для достоверного ответа. "
            "Уточните вопрос по доступу, аудиту, защите данных, ИИ или эксплуатации RAG."
        ),
        "intro": "По вопросу администратора «{q}» в базе I-ins найдено:",
        "system_extra": "Отвечай на русском языке как операционный помощник администратора.",
        "translate_to": "русский",
    },
    "kk": {
        "empty": (
            "I-ins әкімшілік білім қорынан сенімді жауап беруге жеткілікті үзінді табылмады. "
            "Қолжетімділік, аудит, деректерді қорғау немесе ИИ туралы сұрақты нақтылаңыз."
        ),
        "intro": "Әкімшінің «{q}» сұрағы бойынша I-ins базасынан табылды:",
        "system_extra": "Жауапты қазақ тілінде әкімшіге арналған әрекет ретінде бер.",
        "translate_to": "қазақ",
    },
    "en": {
        "empty": (
            "No sufficiently relevant administrator knowledge excerpts were found. "
            "Clarify the access, audit, data-protection, AI, or RAG question."
        ),
        "intro": "For the administrator question “{q}”, the I-ins knowledge base found:",
        "system_extra": "Answer in English as a practical administrator control step.",
        "translate_to": "English",
    },
}


def normalize_lang(code: Optional[str]) -> str:
    c = (code or "").lower().strip()
    return c if c in _ANSWER_LANG else ""


def detect_query_lang(text: str, preferred: str = "ru") -> str:
    preferred = normalize_lang(preferred) or "ru"
    s = (text or "").strip()
    if not s:
        return preferred
    if any(ch in _KK_LETTERS for ch in s):
        return "kk"
    letters = [ch for ch in s if ch.isalpha()]
    if not letters:
        return preferred
    latin = sum(1 for ch in letters if ("a" <= ch.lower() <= "z"))
    cyr = sum(1 for ch in letters if "а" <= ch.lower() <= "я" or ch.lower() == "ё")
    if latin >= max(3, int(0.6 * len(letters))) and latin > cyr:
        return "en"
    if cyr >= max(3, int(0.5 * len(letters))):
        return "ru"
    return preferred


def resolve_answer_lang(question: str, requested: Optional[str] = None) -> str:
    pref = normalize_lang(requested) or "ru"
    detected = detect_query_lang(question, preferred=pref)
    if any(ch in _KK_LETTERS for ch in question):
        return "kk"
    letters = [ch for ch in question if ch.isalpha()]
    if letters:
        latin = sum(1 for ch in letters if "a" <= ch.lower() <= "z")
        if latin >= max(3, int(0.6 * len(letters))):
            return "en"
        cyr = sum(1 for ch in letters if "а" <= ch.lower() <= "я" or ch.lower() == "ё")
        if cyr >= max(3, int(0.5 * len(letters))):
            return "ru"
    return detected if detected else pref


def _system_prompt_for(lang: str) -> str:
    pack = _ANSWER_LANG.get(lang, _ANSWER_LANG["ru"])
    return f"{_RAG_SYSTEM} {pack['system_extra']}"


@dataclass
class _Chunk:
    chunk_id: str
    source: str
    title: str
    text: str
    document_id: str = ""
    page_start: Optional[int] = None
    page_end: Optional[int] = None


@dataclass
class _Index:
    chunks: List[_Chunk]
    vectorizer: TfidfVectorizer
    matrix: Any


_INDEX: Optional[_Index] = None
_VECTOR_STORE: Optional[VectorRagStore] = None
_VECTOR_STORE_ERROR: Optional[str] = None


def get_vector_store() -> Optional[VectorRagStore]:
    global _VECTOR_STORE, _VECTOR_STORE_ERROR
    if _VECTOR_STORE is not None:
        return _VECTOR_STORE
    path = get_settings().rag_vector_db_path
    if not path.is_file():
        _VECTOR_STORE_ERROR = f"Файл не найден: {path}"
        return None
    try:
        _VECTOR_STORE = VectorRagStore(path)
        _VECTOR_STORE_ERROR = None
    except Exception as exc:  # noqa: BLE001
        _VECTOR_STORE_ERROR = str(exc)
        return None
    return _VECTOR_STORE


def _corpus_dirs() -> List[Path]:
    settings = get_settings()
    dirs = [settings.corpus_dir, settings.docs_storage_dir]
    return [d for d in dirs if d.is_dir()]


def _split_markdown(text: str, source: str, max_chars: int = 720, overlap: int = 80) -> List[_Chunk]:
    title = source
    m = re.search(r"^#\s+(.+)$", text.strip(), re.MULTILINE)
    if m:
        title = m.group(1).strip()
    sections = re.split(r"\n(?=##\s+)", text.strip())
    raw_parts: List[str] = []
    for sec in sections:
        sec = sec.strip()
        if not sec:
            continue
        if len(sec) <= max_chars:
            raw_parts.append(sec)
            continue
        paras = [p.strip() for p in re.split(r"\n\n+", sec) if p.strip()]
        buf = ""
        for para in paras:
            candidate = (buf + "\n\n" + para).strip() if buf else para
            if len(candidate) <= max_chars:
                buf = candidate
            else:
                if buf:
                    raw_parts.append(buf)
                if len(para) <= max_chars:
                    buf = para
                else:
                    start = 0
                    while start < len(para):
                        end = min(len(para), start + max_chars)
                        raw_parts.append(para[start:end])
                        start = max(start + 1, end - overlap)
                    buf = ""
        if buf:
            raw_parts.append(buf)

    return [
        _Chunk(chunk_id=f"{source}::{i}", source=source, title=title, text=part)
        for i, part in enumerate(raw_parts)
    ]


def _load_chunks() -> List[_Chunk]:
    all_chunks: List[_Chunk] = []
    for root in _corpus_dirs():
        for path in sorted(list(root.glob("*.md")) + list(root.glob("*.txt"))):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            all_chunks.extend(_split_markdown(text, path.name))
    return all_chunks


def _build_index() -> _Index:
    chunks = _load_chunks()
    if not chunks:
        vectorizer = TfidfVectorizer(max_features=5000)
        matrix = vectorizer.fit_transform(["placeholder empty corpus"])
        return _Index(chunks=[], vectorizer=vectorizer, matrix=matrix)
    docs = [c.text for c in chunks]
    vectorizer = TfidfVectorizer(max_features=8000, ngram_range=(1, 2), sublinear_tf=True)
    matrix = vectorizer.fit_transform(docs)
    return _Index(chunks=chunks, vectorizer=vectorizer, matrix=matrix)


def get_index() -> _Index:
    global _INDEX
    if _INDEX is None:
        _INDEX = _build_index()
    return _INDEX


def reload_index() -> _Index:
    global _INDEX, _VECTOR_STORE, _VECTOR_STORE_ERROR
    _VECTOR_STORE = None
    _VECTOR_STORE_ERROR = None
    _INDEX = _build_index()
    get_vector_store()
    return _INDEX


def _excerpt(text: str, limit: int = 220) -> str:
    flat = re.sub(r"\s+", " ", text.strip())
    if len(flat) <= limit:
        return flat
    return flat[: limit - 1].rsplit(" ", 1)[0] + "…"


def _has_domain_signal(query: str) -> bool:
    normalized = query.lower().replace("ё", "е")
    return any(term in normalized for term in _DOMAIN_TERMS)


def _grounded_hits(query: str, hits: List[Tuple[_Chunk, float]]) -> List[Tuple[_Chunk, float]]:
    if not hits:
        return []
    threshold = _MIN_DOMAIN_RELEVANCE_SCORE if _has_domain_signal(query) else _MIN_RELEVANCE_SCORE
    if hits[0][1] < threshold:
        return []
    return [(chunk, score) for chunk, score in hits if score >= threshold * 0.72]


def retrieve(query: str, top_k: int = 4) -> List[Tuple[_Chunk, float]]:
    store = get_vector_store()
    if store is not None:
        candidates = [
            (_Chunk(chunk_id=hit.chunk_id, document_id=hit.document_id,
                    source=hit.source, title=hit.title, text=hit.text,
                    page_start=hit.page_start, page_end=hit.page_end), hit.score)
            for hit in store.search(query, top_k=top_k)
        ]
        return _grounded_hits(query, candidates)
    idx = get_index()
    if not idx.chunks:
        return []
    q = query.strip()
    if not q:
        return []
    q_vec = idx.vectorizer.transform([q])
    scores = cosine_similarity(q_vec, idx.matrix).ravel()
    order = np.argsort(scores)[::-1]
    out: List[Tuple[_Chunk, float]] = []
    for pos in order[:top_k]:
        score = float(scores[pos])
        if score <= 0.01 and out:
            break
        out.append((idx.chunks[int(pos)], score))
    return _grounded_hits(query, out)


def _format_context(hits: List[Tuple[_Chunk, float]]) -> str:
    if not hits:
        return "(Релевантные фрагменты не найдены в корпусе.)"
    lines: List[str] = []
    for i, (chunk, score) in enumerate(hits, start=1):
        lines.append(f"[{i}] Источник: {chunk.source}{_page_label(chunk)} | score={score:.3f}\n{chunk.text}")
    return "\n\n---\n\n".join(lines)


def _extractive_answer(question: str, hits: List[Tuple[_Chunk, float]], lang: str = "ru") -> str:
    pack = _ANSWER_LANG.get(lang, _ANSWER_LANG["ru"])
    if not hits:
        return pack["empty"]
    parts = [pack["intro"].format(q=question.strip()), ""]
    for i, (chunk, _score) in enumerate(hits, start=1):
        parts.append(f"{i}. {_excerpt(chunk.text, 420)}")
        parts.append(f"Источник: {chunk.source}{_page_label(chunk)}")
        parts.append("")
    return "\n".join(parts).strip()


def _rewrite_answer_lang(answer: str, lang: str, question: str) -> Optional[str]:
    if lang == "ru":
        return None
    try:
        from iins_admin_app.services.llm_provider import (
            backend_ready,
            generate_reply,
            resolve_backend,
        )

        backend = resolve_backend()
        if backend == "extractive" or not backend_ready(backend):
            return None
        pack = _ANSWER_LANG[lang]
        prompt = (
            f"Rewrite the insurance administrator answer below into {pack['translate_to']}. "
            "Keep only facts from the text. Do not add new conditions. "
            "Do not mention file names. Keep a helpful advisory tone.\n\n"
            f"User question:\n{question.strip()}\n\n"
            f"Answer to rewrite:\n{answer}"
        )
        out = generate_reply(
            backend,
            prompt,
            max_new_tokens=512,
            temperature=0.2,
            system_prompt=_system_prompt_for(lang),
        ).strip()
        return out or None
    except Exception:  # noqa: BLE001
        return None


def _generate_answer(
    question: str,
    hits: List[Tuple[_Chunk, float]],
    *,
    lang: str,
    mode: str = "auto",
    max_new_tokens: int = 384,
    temperature: float = 0.35,
) -> Tuple[str, str]:
    from iins_admin_app.services.llm_provider import (
        backend_ready,
        generate_reply,
        model_name,
        not_ready_message,
        resolve_backend,
    )

    lang = normalize_lang(lang) or "ru"
    backend = resolve_backend(mode)

    if backend in ("ollama", "gigachat"):
        if not backend_ready(backend):
            raise RuntimeError(not_ready_message(backend))
        context = _format_context(hits)
        user_block = (
            f"Контекст из базы знаний:\n\n{context}\n\n"
            f"Вопрос пользователя:\n{question.strip()}\n\n"
            f"Язык ответа: {lang}"
        )
        answer = generate_reply(
            backend,
            user_block,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            system_prompt=_system_prompt_for(lang),
        )
        return answer, model_name(backend)

    answer = _extractive_answer(question, hits, lang=lang)
    rewritten = _rewrite_answer_lang(answer, lang, question)
    if rewritten:
        return rewritten, "extractive+lm-i18n"
    return answer, "extractive-tfidf"


def status_payload() -> Dict[str, Any]:
    from iins_admin_app.services.llm_provider import providers_status, resolve_backend

    store = get_vector_store()
    idx = get_index() if store is None else None
    sources = store.sources if store is not None else sorted({c.source for c in idx.chunks})
    _providers = providers_status()
    ollama = _providers["ollama"]
    gigachat = _providers["gigachat"]
    effective = resolve_backend()
    ready = bool(store and store.chunk_count) or bool(idx and idx.chunks)

    if ollama.get("model_ready"):
        msg = f"Qwen RAG готов: {ollama.get('model') or 'Ollama'}"
    elif gigachat.get("available"):
        msg = f"GigaChat готов: {gigachat.get('model') or 'API'}"
    elif not ready:
        msg = "Административная база знаний пуста"
    else:
        msg = "Административная PDF-база готова; Ollama недоступна"

    return {
        "corpus_documents": store.document_count if store is not None else len(sources),
        "corpus_chunks": store.chunk_count if store is not None else len(idx.chunks),
        "sources": sources,
        "retrieval_backend": "sqlite-hashed-tfidf" if store is not None else "markdown-tfidf",
        "vector_db_path": str(get_settings().rag_vector_db_path),
        "vector_db_error": _VECTOR_STORE_ERROR,
        "neighbor_expansion": store is not None,
        "relevance_guard": {
            "enabled": True,
            "minimum_score": _MIN_RELEVANCE_SCORE,
            "minimum_domain_score": _MIN_DOMAIN_RELEVANCE_SCORE,
        },
        "lm_backend": get_settings().lm_backend,
        "effective_backend": effective,
        "ollama": ollama,
        "gigachat": gigachat,
        "providers": _providers["providers"],
        "provider_labels": _providers["labels"],
        "ready": ready,
        "modes": _providers["modes"],
        "message_ru": msg,
    }


def rag_query(
    question: str,
    *,
    top_k: int = 4,
    max_new_tokens: int = 384,
    temperature: float = 0.35,
    policy_hint: str = "",
    lang: Optional[str] = None,
    mode: Optional[str] = None,
) -> Dict[str, Any]:
    q = question.strip()
    if len(q) < 2:
        raise ValueError("Вопрос слишком короткий")
    answer_lang = resolve_answer_lang(q, lang)
    q_search = f"{q} {policy_hint.strip()}".strip() if policy_hint.strip() else q

    t0 = time.perf_counter()
    hits = retrieve(q_search, top_k=top_k)
    retrieval_ms = (time.perf_counter() - t0) * 1000.0

    t1 = time.perf_counter()
    if hits:
        answer, model = _generate_answer(
            q,
            hits,
            lang=answer_lang,
            mode=mode or get_settings().lm_backend,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
        )
    else:
        # Never invoke Ollama without grounded context.
        answer = _extractive_answer(q, [], lang=answer_lang)
        model = "retrieval-guard"
    generation_ms = (time.perf_counter() - t1) * 1000.0

    from iins_admin_app.services.llm_provider import resolve_backend

    return {
        "question": q,
        "answer": answer,
        "lang": answer_lang,
        "mode": resolve_backend(mode or get_settings().lm_backend) if hits else "guarded",
        "model": model,
        "backend": get_settings().lm_backend,
        "answered": bool(hits),
        "retrieval_status": "grounded" if hits else "insufficient_context",
        "chunks_used": [
            {
                "chunk_id": chunk.chunk_id,
                "source": chunk.source,
                "title": chunk.title,
                "document_id": chunk.document_id,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "citation": f"{chunk.source}{_page_label(chunk)}",
                "score": round(score, 4),
                "excerpt": _excerpt(chunk.text),
            }
            for chunk, score in hits
        ],
        "retrieval_ms": round(retrieval_ms, 2),
        "generation_ms": round(generation_ms, 2),
    }


def _page_label(chunk: _Chunk) -> str:
    if chunk.page_start is None:
        return ""
    if chunk.page_end is not None and chunk.page_end != chunk.page_start:
        return f", стр. {chunk.page_start}–{chunk.page_end}"
    return f", стр. {chunk.page_start}"
