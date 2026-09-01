from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_host: str = "127.0.0.1"
    app_port: int = 8003
    # client | admin — какой кабинет обслуживает этот процесс
    app_surface: str = "admin"
    client_port: int = 8000
    admin_port: int = 8003
    secret_key: str = "insurance-rag-demo-secret"
    database_url: str = f"sqlite:///{(ROOT / 'data' / 'insurance.db').as_posix()}"
    ollama_base_url: str = "http://127.0.0.1:11434"
    # Как в FIPS2: лёгкая Qwen для локального демо (~16 ГБ RAM)
    ollama_model: str = "qwen2.5:1.5b"
    # auto = Ollama/Qwen если готова, иначе extractive RAG; ollama | extractive
    lm_backend: str = "auto"
    gigachat_base_url: str = "https://gigachat-students.nsk.21-school.ru/v1"
    gigachat_model: str = "Gigashlep/GigaChat-2-Max"
    gigachat_api_key: str = ""
    gigachat_timeout: float = 60.0
    corpus_dir: Path = ROOT / "iins_admin_app" / "data" / "admin_rag_corpus"
    docs_storage_dir: Path = ROOT / "data" / "policy_docs"
    rag_vector_db_path: Path = ROOT / "knowledge_base" / "rag_store" / "vectors.sqlite3"


@lru_cache
def get_settings() -> Settings:
    return Settings()
