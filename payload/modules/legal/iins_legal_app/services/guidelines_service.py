from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from iins_legal_app.config import get_settings


def _load_docs() -> list[dict[str, str]]:
    corpus = get_settings().corpus_dir
    docs: list[dict[str, str]] = []
    if not corpus.is_dir():
        return docs
    for path in sorted(corpus.glob("*.md")):
        text = path.read_text(encoding="utf-8", errors="ignore").strip()
        if text:
            docs.append({"id": path.stem, "title": path.stem.replace("_", " "), "text": text, "path": path.name})
    return docs


@lru_cache(maxsize=1)
def _index() -> tuple[list[dict[str, str]], Any, Any]:
    docs = _load_docs()
    if not docs:
        return [], None, None
    vectorizer = TfidfVectorizer(max_features=4000, ngram_range=(1, 2))
    matrix = vectorizer.fit_transform([d["text"] for d in docs])
    return docs, vectorizer, matrix


def search(query: str, top_k: int = 3) -> list[dict[str, Any]]:
    q = (query or "").strip()
    docs, vectorizer, matrix = _index()
    if not docs or vectorizer is None or not q:
        return [{"title": d["title"], "path": d["path"], "snippet": d["text"][:400], "score": 0.0} for d in docs[:top_k]]
    q_vec = vectorizer.transform([q])
    sims = cosine_similarity(q_vec, matrix).ravel()
    order = sims.argsort()[::-1][:top_k]
    out: list[dict[str, Any]] = []
    for i in order:
        d = docs[int(i)]
        snippet = d["text"][:500]
        out.append({"title": d["title"], "path": d["path"], "snippet": snippet, "score": float(sims[int(i)])})
    return out


def list_guidelines() -> list[dict[str, str]]:
    docs, _, _ = _index()
    return [{"id": d["id"], "title": d["title"], "path": d["path"], "chars": str(len(d["text"]))} for d in docs]


def get_guideline(doc_id: str) -> dict[str, str] | None:
    docs, _, _ = _index()
    for d in docs:
        if d["id"] == doc_id or d["path"] == doc_id:
            return d
    return None


def status() -> dict[str, Any]:
    docs, vectorizer, _ = _index()
    return {
        "ready": bool(docs),
        "docs": len(docs),
        "engine": "tfidf" if vectorizer is not None else "none",
        "corpus_dir": str(get_settings().corpus_dir),
    }
