"""Rerankers: rescore (query, passage) pairs more precisely than first-stage retrieval.

- LLMReranker: asks the chat model to score all candidates in one structured call.
  Off by default (RERANKER=llm to enable); see eval/results/chunk400_e2e.md.
- CrossEncoderReranker: a small multilingual cross-encoder (FlashRank, ONNX on CPU).
  Kept for comparison only: on Korean it scored below random in eval/run_eval.py
  (Hit@4 29-32% vs 97-100% for the other configs), so it is not used by the app.
  Requires the `eval` dependency group.
"""

import asyncio
from typing import Protocol

from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field


class Reranker(Protocol):
    name: str

    async def rerank(self, query: str, docs: list[Document]) -> list[float]:
        """Return one relevance score per doc (higher is more relevant), in input order."""
        ...


class CrossEncoderReranker:
    name = "cross-encoder"

    def __init__(self, model_name: str = "ms-marco-MultiBERT-L-12", cache_dir: str = ".cache/flashrank"):
        from flashrank import Ranker  # imported lazily: onnxruntime is slow to import

        self._ranker = Ranker(model_name=model_name, cache_dir=cache_dir)

    def _score(self, query: str, docs: list[Document]) -> list[float]:
        from flashrank import RerankRequest

        passages = [{"id": i, "text": d.page_content} for i, d in enumerate(docs)]
        results = self._ranker.rerank(RerankRequest(query=query, passages=passages))
        scores = {r["id"]: float(r["score"]) for r in results}
        return [scores[i] for i in range(len(docs))]

    async def rerank(self, query: str, docs: list[Document]) -> list[float]:
        if not docs:
            return []
        # CPU-bound inference; keep it off the event loop.
        return await asyncio.to_thread(self._score, query, docs)


LLM_RERANK_PROMPT = """당신은 검색 결과를 평가하는 심사관입니다.
각 문서 조각이 질문에 답하는 데 얼마나 유용한지 0~10점으로 매기세요.
- 10: 질문의 답을 직접 담고 있음
- 5: 관련 주제지만 답은 없음
- 0: 무관함
모든 조각에 점수를 매겨야 합니다."""


class _Score(BaseModel):
    id: int
    score: float = Field(ge=0, le=10)


class _Scores(BaseModel):
    scores: list[_Score]


class LLMReranker:
    name = "llm"

    def __init__(self, llm: BaseChatModel):
        self._llm = llm.with_structured_output(_Scores)

    async def rerank(self, query: str, docs: list[Document]) -> list[float]:
        if not docs:
            return []
        numbered = "\n\n".join(f"[{i}]\n{d.page_content}" for i, d in enumerate(docs))
        result: _Scores = await self._llm.ainvoke(
            [SystemMessage(LLM_RERANK_PROMPT), HumanMessage(f"질문: {query}\n\n문서 조각:\n{numbered}")]
        )
        scores = {s.id: s.score for s in result.scores}
        return [scores.get(i, 0.0) for i in range(len(docs))]
