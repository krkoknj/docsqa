"""First-stage retrieval: vector search, keyword search, and their fusion.

    query ─┬─ vector search  (pgvector cosine distance, top N) ─┐
           └─ keyword search (tsvector + Hangul bigrams, top N) ─┴─ RRF fusion ─ [rerank] ─ top k

Reciprocal Rank Fusion scores a chunk by sum(1 / (60 + rank)) over the lists it
appears in, so it needs no score normalization between the two very different
ranking functions.
"""

import time
from dataclasses import dataclass, field
from typing import Literal

from langchain_core.documents import Document
from langchain_postgres import PGVectorStore
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.rag.rerank import Reranker
from app.rag.tokenize import to_tsquery

RetrievalMode = Literal["vector", "keyword", "hybrid"]
RRF_K = 60


@dataclass
class Candidate:
    doc: Document
    vector_rank: int | None = None
    keyword_rank: int | None = None
    fused_score: float = 0.0
    rerank_score: float | None = None

    @property
    def score(self) -> float:
        return self.rerank_score if self.rerank_score is not None else self.fused_score


@dataclass
class RetrievalResult:
    candidates: list[Candidate]
    timings_ms: dict[str, float] = field(default_factory=dict)


class HybridRetriever:
    def __init__(
        self,
        vector_store: PGVectorStore,
        engine: AsyncEngine,
        table: str,
        *,
        mode: RetrievalMode = "hybrid",
        reranker: Reranker | None = None,
        candidates: int = 20,
        rerank_candidates: int = 12,
    ):
        self.vector_store = vector_store
        self.engine = engine
        self.table = table
        self.mode = mode
        self.reranker = reranker
        self.candidates = candidates
        self.rerank_candidates = rerank_candidates

    @property
    def name(self) -> str:
        return self.mode + (f"+{self.reranker.name}" if self.reranker else "")

    async def search(self, query: str, k: int, document_ids: list[str] | None = None) -> RetrievalResult:
        timings: dict[str, float] = {}
        vector_docs: list[Document] = []
        keyword_docs: list[Document] = []

        start = time.perf_counter()
        if self.mode in ("vector", "hybrid"):
            filter_ = {"document_id": {"$in": document_ids}} if document_ids else None
            results = await self.vector_store.asimilarity_search_with_score(
                query, k=self.candidates, filter=filter_
            )
            vector_docs = [doc for doc, _ in results]
            timings["vector"] = (time.perf_counter() - start) * 1000

        start = time.perf_counter()
        if self.mode in ("keyword", "hybrid"):
            keyword_docs = await self.keyword_search(query, self.candidates, document_ids)
            timings["keyword"] = (time.perf_counter() - start) * 1000

        fused = fuse(vector_docs, keyword_docs)

        if self.reranker and fused:
            start = time.perf_counter()
            pool = fused[: self.rerank_candidates]
            scores = await self.reranker.rerank(query, [c.doc for c in pool])
            for candidate, score in zip(pool, scores, strict=True):
                candidate.rerank_score = score
            fused = sorted(pool, key=lambda c: c.rerank_score, reverse=True)
            timings["rerank"] = (time.perf_counter() - start) * 1000

        return RetrievalResult(candidates=fused[:k], timings_ms=timings)

    async def keyword_search(self, query: str, limit: int, document_ids: list[str] | None) -> list[Document]:
        tsquery = to_tsquery(query)
        if not tsquery:
            return []
        doc_filter = "AND document_id = ANY(CAST(:ids AS uuid[]))" if document_ids else ""
        sql = text(
            f"""
            SELECT langchain_id, content, document_id, source, page, chunk_index,
                   ts_rank(search_tsv, q, 1) AS rank
            FROM "{self.table}", to_tsquery('simple', :q) AS q
            WHERE search_tsv @@ q {doc_filter}
            ORDER BY rank DESC
            LIMIT :limit
            """
        )
        params = {"q": tsquery, "limit": limit}
        if document_ids:
            params["ids"] = document_ids
        async with self.engine.connect() as conn:
            rows = (await conn.execute(sql, params)).all()
        return [
            Document(
                id=str(r.langchain_id),
                page_content=r.content,
                metadata={
                    "document_id": str(r.document_id),
                    "source": r.source,
                    "page": r.page,
                    "chunk_index": r.chunk_index,
                },
            )
            for r in rows
        ]


def fuse(vector_docs: list[Document], keyword_docs: list[Document]) -> list[Candidate]:
    """Reciprocal Rank Fusion of two ranked lists, keyed by chunk id."""
    by_id: dict[str, Candidate] = {}
    for rank, doc in enumerate(vector_docs, start=1):
        c = by_id.setdefault(doc.id, Candidate(doc=doc))
        c.vector_rank = rank
        c.fused_score += 1 / (RRF_K + rank)
    for rank, doc in enumerate(keyword_docs, start=1):
        c = by_id.setdefault(doc.id, Candidate(doc=doc))
        c.keyword_rank = rank
        c.fused_score += 1 / (RRF_K + rank)
    return sorted(by_id.values(), key=lambda c: c.fused_score, reverse=True)
