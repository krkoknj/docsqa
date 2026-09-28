from langchain_core.language_models import BaseChatModel

from app.config import Settings
from app.db import Database
from app.rag.rerank import CrossEncoderReranker, LLMReranker, Reranker
from app.rag.retriever import HybridRetriever


def build_reranker(name: str, judge_llm: BaseChatModel, cache_dir: str) -> Reranker | None:
    match name:
        case "none":
            return None
        case "cross-encoder":
            return CrossEncoderReranker(cache_dir=cache_dir)
        case "llm":
            return LLMReranker(judge_llm)
    raise ValueError(f"unknown reranker: {name}")


def build_retriever(
    settings: Settings,
    db: Database,
    judge_llm: BaseChatModel,
    *,
    mode: str | None = None,
    reranker: str | None = None,
) -> HybridRetriever:
    return HybridRetriever(
        db.vector_store,
        db.engine,
        settings.vector_table,
        mode=mode or settings.retrieval_mode,
        reranker=build_reranker(reranker or settings.reranker, judge_llm, settings.reranker_cache_dir),
        candidates=settings.retrieval_candidates,
        rerank_candidates=settings.rerank_candidates,
    )
