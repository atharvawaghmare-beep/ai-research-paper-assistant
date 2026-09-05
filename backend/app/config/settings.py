from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Full-Stack Starter API"
    api_prefix: str = "/api/v1"
    database_url: str = "postgresql+psycopg://app_user:app_password@localhost:5432/app_db"
    cors_origins: str = "http://localhost:5173"
    jwt_secret_key: str = "change-me-in-development-use-a-long-secret-key"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    paper_upload_dir: str = "uploads/papers"
    max_pdf_upload_size_mb: int = 25
    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    faiss_index_path: str = "storage/faiss/index.faiss"
    reranker_model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"
    llm_request_timeout_seconds: int = 300
    arxiv_api_base_url: str = "https://export.arxiv.org/api/query"
    semantic_scholar_api_base_url: str = "https://api.semanticscholar.org/graph/v1"
    semantic_scholar_api_key: str | None = None
    external_api_timeout_seconds: float = 15.0
    external_api_max_retries: int = 2

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()