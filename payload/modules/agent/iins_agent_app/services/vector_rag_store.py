"""Read-only adapter for the external actuarial SQLite vector store."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import struct
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


TOKEN_RE = re.compile(r"(?u)\b[\w-]{2,}\b")


@dataclass(frozen=True)
class VectorHit:
    chunk_id: str
    document_id: str
    source: str
    title: str
    page_start: int
    page_end: int
    chunk_index: int
    text: str
    score: float


@dataclass(frozen=True)
class _StoredChunk:
    chunk_id: str
    document_id: str
    source: str
    title: str
    page_start: int
    page_end: int
    chunk_index: int
    text: str
    indices: tuple[int, ...]
    values: tuple[float, ...]


def _unpack_ints(blob: bytes) -> tuple[int, ...]:
    return struct.unpack(f"<{len(blob) // 4}I", blob) if blob else ()


def _unpack_floats(blob: bytes) -> tuple[float, ...]:
    return struct.unpack(f"<{len(blob) // 4}f", blob) if blob else ()


def _terms(text: str) -> list[str]:
    tokens = [token.lower().replace("ё", "е") for token in TOKEN_RE.findall(text)]
    terms = tokens + [f"word2:{a}__{b}" for a, b in zip(tokens, tokens[1:])]
    for token in tokens:
        if len(token) < 5:
            continue
        padded = f"^{token}$"
        for width in (3, 4, 5):
            terms.extend(f"char{width}:{padded[i:i + width]}" for i in range(len(padded) - width + 1))
    return terms


def _feature_index(term: str, dimension: int) -> int:
    digest = hashlib.blake2b(term.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "little") % dimension


def _tfidf(
    text: str,
    *,
    dimension: int,
    document_frequency: Counter[int],
    document_count: int,
) -> tuple[list[int], list[float]]:
    counts = Counter(_feature_index(term, dimension) for term in _terms(text))
    weighted: list[tuple[int, float]] = []
    for index, count in counts.items():
        tf = 1.0 + math.log(count)
        idf = math.log((1.0 + document_count) / (1.0 + document_frequency[index])) + 1.0
        weighted.append((index, tf * idf))
    norm = math.sqrt(sum(value * value for _, value in weighted)) or 1.0
    weighted.sort()
    return [index for index, _ in weighted], [value / norm for _, value in weighted]


def _dot(
    indices_a: Sequence[int],
    values_a: Sequence[float],
    indices_b: Sequence[int],
    values_b: Sequence[float],
) -> float:
    i = j = 0
    score = 0.0
    while i < len(indices_a) and j < len(indices_b):
        if indices_a[i] == indices_b[j]:
            score += values_a[i] * values_b[j]
            i += 1
            j += 1
        elif indices_a[i] < indices_b[j]:
            i += 1
        else:
            j += 1
    return score


def _merge_overlapping(parts: Sequence[str], max_chars: int = 3600) -> str:
    merged = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if not merged:
            merged = part
            continue
        overlap = 0
        max_overlap = min(300, len(merged), len(part))
        for size in range(max_overlap, 39, -1):
            if merged[-size:] == part[:size]:
                overlap = size
                break
        merged = f"{merged}\n\n{part[overlap:].lstrip()}".strip()
        if len(merged) >= max_chars:
            return merged[:max_chars].rsplit(" ", 1)[0]
    return merged


class VectorRagStore:
    def __init__(self, path: Path):
        self.path = path
        if not path.is_file():
            raise FileNotFoundError(path)
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
        if integrity != "ok":
            connection.close()
            raise RuntimeError(f"Повреждена векторная база: {integrity}")
        self.meta = dict(connection.execute("SELECT key, value FROM meta"))
        if self.meta.get("schema_version") != "1":
            connection.close()
            raise RuntimeError("Неподдерживаемая версия векторной базы")
        self.dimension = int(self.meta["vector_dimension"])
        self.document_frequency = Counter(
            {int(key): int(value) for key, value in json.loads(self.meta["document_frequency"]).items()}
        )
        self.document_count = int(self.meta["document_count"])
        self.chunk_count = int(self.meta["chunk_count"])
        self.sources = [row[0] for row in connection.execute("SELECT source FROM documents ORDER BY source")]
        self.chunks = [
            _StoredChunk(
                chunk_id=row["chunk_id"],
                document_id=row["document_id"],
                source=row["source"],
                title=row["title"],
                page_start=row["page_start"],
                page_end=row["page_end"],
                chunk_index=row["chunk_index"],
                text=row["text"],
                indices=_unpack_ints(row["indices"]),
                values=_unpack_floats(row["values_blob"]),
            )
            for row in connection.execute(
                """
                SELECT c.*, e.indices, e.values_blob
                FROM chunks c JOIN embeddings e ON e.chunk_id = c.chunk_id
                ORDER BY c.document_id, c.chunk_index
                """
            )
        ]
        connection.close()
        self._positions = {chunk.chunk_id: position for position, chunk in enumerate(self.chunks)}

    def _neighbor_context(self, hit: _StoredChunk) -> tuple[str, int, int]:
        position = self._positions[hit.chunk_id]
        neighbors = [hit]
        for candidate_position in (position - 1, position + 1):
            if 0 <= candidate_position < len(self.chunks):
                candidate = self.chunks[candidate_position]
                if candidate.document_id == hit.document_id and abs(candidate.page_start - hit.page_start) <= 1:
                    neighbors.append(candidate)
        neighbors.sort(key=lambda chunk: chunk.chunk_index)
        return (
            _merge_overlapping([chunk.text for chunk in neighbors]),
            min(chunk.page_start for chunk in neighbors),
            max(chunk.page_end for chunk in neighbors),
        )

    def search(self, query: str, top_k: int = 4) -> list[VectorHit]:
        query_indices, query_values = _tfidf(
            query,
            dimension=self.dimension,
            document_frequency=self.document_frequency,
            document_count=self.chunk_count,
        )
        scored: list[tuple[float, _StoredChunk]] = []
        for chunk in self.chunks:
            score = _dot(query_indices, query_values, chunk.indices, chunk.values)
            lowered = chunk.text.lower()
            if "оглавление" in lowered or len(re.findall(r"\.{8,}", chunk.text)) >= 2:
                score *= 0.45
            if score > 0:
                scored.append((score, chunk))
        scored.sort(key=lambda item: item[0], reverse=True)

        results: list[VectorHit] = []
        seen_documents_pages: set[tuple[str, int]] = set()
        for score, chunk in scored:
            key = (chunk.document_id, chunk.page_start)
            if key in seen_documents_pages:
                continue
            seen_documents_pages.add(key)
            text, page_start, page_end = self._neighbor_context(chunk)
            results.append(
                VectorHit(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    source=chunk.source,
                    title=chunk.title,
                    page_start=page_start,
                    page_end=page_end,
                    chunk_index=chunk.chunk_index,
                    text=text,
                    score=score,
                )
            )
            if len(results) >= top_k:
                break
        return results
