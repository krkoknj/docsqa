from typing import NotRequired, TypedDict


class Source(TypedDict):
    id: int
    document_id: str
    source: str
    page: int | None
    # Final ranking score, higher is better: reranker score if reranked, else RRF score.
    score: float
    vector_rank: int | None
    keyword_rank: int | None
    rerank_score: float | None
    content: str
    relevant: NotRequired[bool]
