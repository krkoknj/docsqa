from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = ""
    openai_chat_model: str = "gpt-4.1-mini"
    # Model for relevance grading, query rewriting and grounding checks.
    openai_judge_model: str = "gpt-4.1-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536

    database_url: str = "postgresql+asyncpg://rag:rag@localhost:5432/rag"
    vector_table: str = "chunks"

    cors_origins: list[str] = ["http://localhost:3000"]

    # Auth: a signed JWT in an httpOnly cookie. Set JWT_SECRET in any real deployment.
    jwt_secret: str = "dev-insecure-secret-change-me-in-production"
    jwt_expire_hours: int = 24 * 7
    session_cookie: str = "docsqa_session"
    cookie_secure: bool = False  # true behind HTTPS

    # Indexing queue: run the worker inside the API process (handy for local dev),
    # or as a separate process with `python -m app.worker` (docker-compose does this).
    embedded_worker: bool = True
    worker_poll_seconds: float = 1.0
    max_index_attempts: int = 3
    stale_job_minutes: int = 10

    # Number of previous messages sent to the LLM as conversation history.
    history_messages: int = 10

    # Tuned with eval/run_eval.py: 400/80 beat 1000/150 on Hit@1 (see eval/results).
    chunk_size: int = 400
    chunk_overlap: int = 80
    retrieval_k: int = 4
    # "vector" | "keyword" | "hybrid"
    retrieval_mode: str = "hybrid"
    # "none" | "llm" | "cross-encoder" (eval only: needs the `eval` dependency group).
    # "none" by default: in eval, the LLM reranker made retrieval Hit@1 perfect but gave no
    # end-to-end gain (the grade node already filters chunks) while adding ~1.5s per answer.
    reranker: str = "none"
    retrieval_candidates: int = 20
    rerank_candidates: int = 12
    reranker_cache_dir: str = ".cache/flashrank"
    max_query_rewrites: int = 1
    max_generations: int = 2
    max_upload_mb: int = 10


@lru_cache
def get_settings() -> Settings:
    return Settings()
