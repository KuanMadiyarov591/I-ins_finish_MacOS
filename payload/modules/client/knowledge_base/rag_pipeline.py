"""Build and query the local client-facing I-ins PDF RAG corpus.

The store is intentionally dependency-light: PDF text is extracted with pypdf,
chunks and metadata are persisted as JSONL, and sparse TF-IDF vectors are kept
in SQLite.  This makes the first-stage corpus portable into ActuaryDesk later.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sqlite3
import struct
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parent
STORE_DIR = ROOT / "rag_store"
TEXT_DIR = STORE_DIR / "extracted_text"
CHUNKS_PATH = STORE_DIR / "chunks.jsonl"
DOCUMENTS_PATH = STORE_DIR / "documents.jsonl"
REPORT_PATH = STORE_DIR / "build_report.json"
RETRIEVAL_QA_PATH = STORE_DIR / "retrieval_qa.json"
DB_PATH = STORE_DIR / "vectors.sqlite3"

PDF_PATTERN = "*.pdf"
MAX_CHARS = 1400
OVERLAP_CHARS = 180
VECTOR_DIM = 32768
TOKEN_RE = re.compile(r"(?u)\b[\w-]{2,}\b")


@dataclass(frozen=True)
class DocumentRecord:
    document_id: str
    source: str
    title: str
    sha256: str
    pages: int
    extracted_chars: int
    empty_pages: list[int]


@dataclass(frozen=True)
class ChunkRecord:
    chunk_id: str
    document_id: str
    source: str
    title: str
    page_start: int
    page_end: int
    chunk_index: int
    text: str
    char_count: int
    sha256: str


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _title_from_filename(path: Path) -> str:
    value = re.sub(
        r"^(?:01_\d+_client_and_02_insurance_agent_and_04_admin_|01_client_internal_\d+_\d+_)",
        "",
        path.stem,
        flags=re.IGNORECASE,
    )
    value = value.replace("_", " ")
    return re.sub(r"\s+", " ", value).strip() or path.stem


def _normalize_page_text(text: str) -> str:
    text = (text or "").replace("\u00ad", "").replace("\xa0", " ")
    text = text.translate(str.maketrans({"\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-"}))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Join words broken by PDF line wrapping while preserving paragraph breaks.
    text = re.sub(r"(?<=\w)-[ \t]*\n[ \t]*(?=[а-яА-ЯёЁa-zA-Z])", "", text)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    paragraphs: list[str] = []
    buffer: list[str] = []
    for line in lines:
        if line:
            buffer.append(line)
        elif buffer:
            paragraphs.append(" ".join(buffer))
            buffer = []
    if buffer:
        paragraphs.append(" ".join(buffer))
    normalized = "\n\n".join(p for p in paragraphs if p).strip()
    boilerplate = (
        "Сайт использует cookies, аналитику и рекламу.",
        "Политика обработки данных",
        "Принять и продолжить",
    )
    for phrase in boilerplate:
        normalized = normalized.replace(phrase, " ")
    return re.sub(r"[ \t]+", " ", normalized).strip()


def _split_long_text(text: str, max_chars: int, overlap: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    parts: list[str] = []
    start = 0
    while start < len(text):
        hard_end = min(len(text), start + max_chars)
        end = hard_end
        if hard_end < len(text):
            candidates = [text.rfind(mark, start + max_chars // 2, hard_end) for mark in (". ", "; ", ": ", " ")]
            end = max(candidates)
            if end <= start:
                end = hard_end
            elif text[end : end + 2] == ". ":
                end += 1
        part = text[start:end].strip()
        if part:
            parts.append(part)
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return parts


def _chunk_page(text: str, max_chars: int = MAX_CHARS, overlap: int = OVERLAP_CHARS) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\n+", text) if p.strip()]
    chunks: list[str] = []
    buffer = ""
    for paragraph in paragraphs:
        candidate = f"{buffer}\n\n{paragraph}".strip() if buffer else paragraph
        if len(candidate) <= max_chars:
            buffer = candidate
            continue
        if buffer:
            chunks.append(buffer)
            tail = buffer[-overlap:].lstrip()
            buffer = f"{tail}\n\n{paragraph}".strip()
        else:
            chunks.extend(_split_long_text(paragraph, max_chars, overlap))
            buffer = ""
        if len(buffer) > max_chars:
            pieces = _split_long_text(buffer, max_chars, overlap)
            chunks.extend(pieces[:-1])
            buffer = pieces[-1] if pieces else ""
    if buffer:
        chunks.append(buffer)
    return [chunk for chunk in chunks if len(chunk) >= 80]


def extract_documents(pdf_paths: Sequence[Path]) -> tuple[list[DocumentRecord], list[ChunkRecord], int]:
    documents: list[DocumentRecord] = []
    chunks: list[ChunkRecord] = []
    seen_chunk_hashes: set[str] = set()
    duplicate_chunks = 0
    TEXT_DIR.mkdir(parents=True, exist_ok=True)

    for pdf_path in pdf_paths:
        file_hash = _sha256_file(pdf_path)
        document_id = file_hash[:16]
        title = _title_from_filename(pdf_path)
        reader = PdfReader(str(pdf_path))
        page_texts: list[str] = []
        empty_pages: list[int] = []
        chunk_index = 0

        for page_number, page in enumerate(reader.pages, start=1):
            normalized = _normalize_page_text(page.extract_text() or "")
            page_texts.append(normalized)
            if len(normalized) < 80:
                empty_pages.append(page_number)
            for piece in _chunk_page(normalized):
                chunk_hash = _sha256_bytes(piece.encode("utf-8"))
                if chunk_hash in seen_chunk_hashes:
                    duplicate_chunks += 1
                    continue
                seen_chunk_hashes.add(chunk_hash)
                chunks.append(
                    ChunkRecord(
                        chunk_id=f"{document_id}:p{page_number}:c{chunk_index}",
                        document_id=document_id,
                        source=pdf_path.name,
                        title=title,
                        page_start=page_number,
                        page_end=page_number,
                        chunk_index=chunk_index,
                        text=piece,
                        char_count=len(piece),
                        sha256=chunk_hash,
                    )
                )
                chunk_index += 1

        joined = "\n\n".join(f"--- PAGE {i} ---\n{text}" for i, text in enumerate(page_texts, start=1))
        (TEXT_DIR / f"{pdf_path.stem}.txt").write_text(joined, encoding="utf-8")
        documents.append(
            DocumentRecord(
                document_id=document_id,
                source=pdf_path.name,
                title=title,
                sha256=file_hash,
                pages=len(reader.pages),
                extracted_chars=sum(len(text) for text in page_texts),
                empty_pages=empty_pages,
            )
        )
        print(f"EXTRACT {pdf_path.name}: pages={len(reader.pages)} chunks={chunk_index}")
    return documents, chunks, duplicate_chunks


def _terms(text: str) -> list[str]:
    tokens = [token.lower().replace("ё", "е") for token in TOKEN_RE.findall(text)]
    terms = tokens + [f"word2:{a}__{b}" for a, b in zip(tokens, tokens[1:])]
    # Character n-grams make lexical retrieval robust to Russian inflection
    # (for example, "устойчивость" vs. "устойчивости") without a language model.
    for token in tokens:
        if len(token) < 5:
            continue
        padded = f"^{token}$"
        for width in (3, 4, 5):
            terms.extend(f"char{width}:{padded[i:i + width]}" for i in range(len(padded) - width + 1))
    return terms


def _feature_index(term: str) -> int:
    digest = hashlib.blake2b(term.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "little") % VECTOR_DIM


def _pack_ints(values: Sequence[int]) -> bytes:
    return struct.pack(f"<{len(values)}I", *values) if values else b""


def _pack_floats(values: Sequence[float]) -> bytes:
    return struct.pack(f"<{len(values)}f", *values) if values else b""


def _unpack_ints(blob: bytes) -> tuple[int, ...]:
    return struct.unpack(f"<{len(blob) // 4}I", blob) if blob else ()


def _unpack_floats(blob: bytes) -> tuple[float, ...]:
    return struct.unpack(f"<{len(blob) // 4}f", blob) if blob else ()


def _vector_counts(text: str) -> Counter[int]:
    return Counter(_feature_index(term) for term in _terms(text))


def _tfidf(counts: Counter[int], document_frequency: Counter[int], n_docs: int) -> tuple[list[int], list[float]]:
    weighted: list[tuple[int, float]] = []
    for index, count in counts.items():
        tf = 1.0 + math.log(count)
        idf = math.log((1.0 + n_docs) / (1.0 + document_frequency[index])) + 1.0
        weighted.append((index, tf * idf))
    norm = math.sqrt(sum(value * value for _, value in weighted)) or 1.0
    weighted.sort()
    return [index for index, _ in weighted], [value / norm for _, value in weighted]


def build_sqlite(documents: Sequence[DocumentRecord], chunks: Sequence[ChunkRecord]) -> None:
    counts_by_chunk = [_vector_counts(chunk.text) for chunk in chunks]
    document_frequency: Counter[int] = Counter()
    for counts in counts_by_chunk:
        document_frequency.update(counts.keys())

    temp_path = DB_PATH.with_suffix(".sqlite3.tmp")
    if temp_path.exists():
        temp_path.unlink()
    connection = sqlite3.connect(temp_path)
    connection.executescript(
        """
        PRAGMA journal_mode=WAL;
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE documents (
            document_id TEXT PRIMARY KEY, source TEXT NOT NULL, title TEXT NOT NULL,
            sha256 TEXT NOT NULL, pages INTEGER NOT NULL, extracted_chars INTEGER NOT NULL,
            empty_pages_json TEXT NOT NULL
        );
        CREATE TABLE chunks (
            chunk_id TEXT PRIMARY KEY, document_id TEXT NOT NULL, source TEXT NOT NULL,
            title TEXT NOT NULL, page_start INTEGER NOT NULL, page_end INTEGER NOT NULL,
            chunk_index INTEGER NOT NULL, text TEXT NOT NULL, char_count INTEGER NOT NULL,
            sha256 TEXT NOT NULL, FOREIGN KEY(document_id) REFERENCES documents(document_id)
        );
        CREATE TABLE embeddings (
            chunk_id TEXT PRIMARY KEY, indices BLOB NOT NULL, values_blob BLOB NOT NULL,
            FOREIGN KEY(chunk_id) REFERENCES chunks(chunk_id)
        );
        CREATE INDEX idx_chunks_document ON chunks(document_id, page_start, chunk_index);
        CREATE INDEX idx_chunks_source ON chunks(source);
        """
    )
    connection.executemany(
        "INSERT INTO meta(key, value) VALUES (?, ?)",
        [
            ("schema_version", "1"),
            ("vectorizer", "hashed_tfidf_word_bigram_char_3_5"),
            ("vector_dimension", str(VECTOR_DIM)),
            ("chunk_count", str(len(chunks))),
            ("document_count", str(len(documents))),
            ("built_at_unix", str(int(time.time()))),
            ("document_frequency", json.dumps(document_frequency, separators=(",", ":"))),
        ],
    )
    connection.executemany(
        "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (
                doc.document_id,
                doc.source,
                doc.title,
                doc.sha256,
                doc.pages,
                doc.extracted_chars,
                json.dumps(doc.empty_pages),
            )
            for doc in documents
        ],
    )
    connection.executemany(
        "INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                chunk.chunk_id,
                chunk.document_id,
                chunk.source,
                chunk.title,
                chunk.page_start,
                chunk.page_end,
                chunk.chunk_index,
                chunk.text,
                chunk.char_count,
                chunk.sha256,
            )
            for chunk in chunks
        ],
    )
    embedding_rows = []
    for chunk, counts in zip(chunks, counts_by_chunk):
        indices, values = _tfidf(counts, document_frequency, len(chunks))
        embedding_rows.append((chunk.chunk_id, _pack_ints(indices), _pack_floats(values)))
    connection.executemany("INSERT INTO embeddings VALUES (?, ?, ?)", embedding_rows)
    connection.commit()
    connection.close()
    if DB_PATH.exists():
        DB_PATH.unlink()
    temp_path.replace(DB_PATH)


def _write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def build() -> None:
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    pdf_paths = sorted(ROOT.glob(PDF_PATTERN))
    if not pdf_paths:
        raise FileNotFoundError(f"No PDFs match {PDF_PATTERN} in {ROOT}")
    documents, chunks, duplicate_chunks = extract_documents(pdf_paths)
    if not chunks:
        raise RuntimeError("No chunks were extracted")
    _write_jsonl(DOCUMENTS_PATH, (asdict(doc) for doc in documents))
    _write_jsonl(CHUNKS_PATH, (asdict(chunk) for chunk in chunks))
    build_sqlite(documents, chunks)

    low_text = [doc.source for doc in documents if doc.extracted_chars < 500]
    report = {
        "schema_version": 1,
        "pdf_pattern": PDF_PATTERN,
        "documents": len(documents),
        "pages": sum(doc.pages for doc in documents),
        "chunks": len(chunks),
        "characters": sum(doc.extracted_chars for doc in documents),
        "duplicate_chunks_removed": duplicate_chunks,
        "documents_with_low_text": low_text,
        "pages_with_low_text": sum(len(doc.empty_pages) for doc in documents),
        "chunk_chars": {
            "min": min(chunk.char_count for chunk in chunks),
            "max": max(chunk.char_count for chunk in chunks),
            "average": round(sum(chunk.char_count for chunk in chunks) / len(chunks), 2),
        },
        "artifacts": {
            "documents": DOCUMENTS_PATH.name,
            "chunks": CHUNKS_PATH.name,
            "vectors": DB_PATH.name,
            "extracted_text_dir": TEXT_DIR.name,
        },
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


def _dot(indices_a: Sequence[int], values_a: Sequence[float], indices_b: Sequence[int], values_b: Sequence[float]) -> float:
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


def search(query: str, top_k: int = 5) -> list[dict]:
    if not DB_PATH.is_file():
        raise FileNotFoundError(f"Build the store first: {DB_PATH}")
    connection = sqlite3.connect(DB_PATH)
    meta = dict(connection.execute("SELECT key, value FROM meta"))
    document_frequency = Counter({int(k): int(v) for k, v in json.loads(meta["document_frequency"]).items()})
    n_docs = int(meta["chunk_count"])
    query_indices, query_values = _tfidf(_vector_counts(query), document_frequency, n_docs)
    hits: list[tuple[float, sqlite3.Row]] = []
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT c.*, e.indices, e.values_blob
        FROM chunks c JOIN embeddings e ON e.chunk_id = c.chunk_id
        """
    )
    for row in rows:
        score = _dot(query_indices, query_values, _unpack_ints(row["indices"]), _unpack_floats(row["values_blob"]))
        lowered = row["text"].lower()
        if "оглавление" in lowered or len(re.findall(r"\.{8,}", row["text"])) >= 2:
            score *= 0.45
        if score > 0:
            hits.append((score, row))
    connection.close()
    hits.sort(key=lambda item: item[0], reverse=True)
    return [
        {
            "score": round(score, 6),
            "chunk_id": row["chunk_id"],
            "source": row["source"],
            "title": row["title"],
            "page": row["page_start"],
            "text": row["text"],
        }
        for score, row in hits[:top_k]
    ]


def validate_retrieval() -> dict:
    cases = [
        {
            "query": "срок выплаты по полису Жизнь Плюс",
            "expected_sources": ["01_client_internal_01_"],
        },
        {
            "query": "случайное повреждение остекления лимит",
            "expected_sources": ["01_client_internal_02_"],
        },
        {
            "query": "куда обратиться потребителю страховых услуг с претензией",
            "expected_sources": ["01_04_", "01_05_", "01_06_"],
        },
        {
            "query": "право страхователя отказаться от договора страхования",
            "expected_sources": ["01_01_", "01_02_", "01_03_", "01_04_"],
        },
        {
            "query": "обработка персональных данных клиента страховой компании",
            "expected_sources": ["01_07_"],
        },
    ]
    results = []
    for case in cases:
        hits = search(case["query"], top_k=5)
        passed = any(
            any(hit["source"].startswith(prefix) for prefix in case["expected_sources"])
            for hit in hits
        )
        results.append(
            {
                **case,
                "passed": passed,
                "hits": [
                    {
                        "rank": rank,
                        "score": hit["score"],
                        "source": hit["source"],
                        "page": hit["page"],
                        "chunk_id": hit["chunk_id"],
                    }
                    for rank, hit in enumerate(hits, start=1)
                ],
            }
        )
    payload = {
        "passed": sum(1 for result in results if result["passed"]),
        "total": len(results),
        "cases": results,
    }
    RETRIEVAL_QA_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Build and query the client I-ins PDF RAG store")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build", help="Extract PDF text, make chunks, and build vectors.sqlite3")
    sub.add_parser("validate", help="Run saved retrieval quality checks")
    query_parser = sub.add_parser("search", help="Search the local vector store")
    query_parser.add_argument("query")
    query_parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    if args.command == "build":
        build()
    elif args.command == "search":
        print(json.dumps(search(args.query, args.top_k), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(validate_retrieval(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
