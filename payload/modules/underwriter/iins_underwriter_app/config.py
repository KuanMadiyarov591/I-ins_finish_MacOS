from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent
SHARED_DATASETS = ROOT.parent / "recommender_datasets"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_host: str = "127.0.0.1"
    app_port: int = 8004
    secret_key: str = "insurance-underwriter-desk-demo-secret"
    database_url: str = f"sqlite:///{(ROOT / 'data' / 'underwriter.db').as_posix()}"
    corpus_dir: Path = ROOT / "iins_underwriter_app" / "data" / "uw_guidelines"
    docs_storage_dir: Path = ROOT / "data" / "policy_docs"
    rag_vector_db_path: Path = ROOT / "knowledge_base" / "rag_store" / "vectors.sqlite3"
    model_dir: Path = ROOT / "models" / "underwriter"

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:1.5b"
    lm_backend: str = "auto"
    gigachat_base_url: str = "https://gigachat-students.nsk.21-school.ru/v1"
    gigachat_model: str = "Gigashlep/GigaChat-2-Max"
    gigachat_api_key: str = ""
    gigachat_timeout: float = 60.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
