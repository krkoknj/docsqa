"""LLM-based judges used by the corrective RAG graph.

Kept behind a small Protocol so the graph can be tested with deterministic fakes.
"""

from typing import Protocol

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.rag.types import Source

GRADE_PROMPT = """당신은 검색 결과의 관련성을 평가하는 심사관입니다.
사용자 질문에 답하는 데 필요한 정보를 담고 있는 문서 조각의 번호만 고르세요.
키워드만 겹치고 실제로 답에 도움이 되지 않는 조각은 제외하세요."""

REWRITE_PROMPT = """당신은 검색어를 개선하는 도우미입니다.
이전 검색에서 관련 문서를 찾지 못했습니다. 문서 검색이 잘 되도록 질문을 다시 작성하세요.
- 대화 맥락이 있다면 대명사("그거", "거기")를 구체적인 대상으로 바꾸세요.
- 핵심 개념과 동의어를 포함하세요.
- 이전 검색어와는 다른 표현을 사용하세요.
- 질문에 없는 정보(연도, 날짜, 수치, 고유명사)를 추측해서 추가하지 마세요.
- "작년", "최근" 같은 상대적인 시간 표현은 특정 연도로 바꾸지 말고 그대로 두세요."""

GROUNDING_PROMPT = """당신은 답변의 사실 근거를 검증하는 심사관입니다.
답변의 모든 사실 주장이 제공된 문서 조각에 의해 뒷받침되는지 판단하세요.
- 문서에 없는 수치, 이름, 규칙이 하나라도 있으면 grounded=false 입니다.
- "문서에서 찾을 수 없다"는 식의 답변은 grounded=true 입니다.
- reason에는 판단 근거를 한국어 한 문장으로 적으세요."""


class GradeResult(BaseModel):
    relevant_ids: list[int] = Field(description="질문에 답하는 데 도움이 되는 문서 조각 번호 목록")


class RewriteResult(BaseModel):
    query: str = Field(description="개선된 검색어")


class GroundingResult(BaseModel):
    grounded: bool = Field(description="답변이 문서 조각에 의해 완전히 뒷받침되는지")
    reason: str = Field(description="판단 근거 한 문장")


class Judges(Protocol):
    async def grade(self, question: str, sources: list[Source]) -> set[int]: ...

    async def rewrite(self, question: str, previous_query: str, history: list[BaseMessage]) -> str: ...

    async def check_grounding(self, answer: str, sources: list[Source]) -> GroundingResult: ...


def _numbered(sources: list[Source]) -> str:
    return "\n\n".join(f"[{s['id']}]\n{s['content']}" for s in sources)


def _history_text(history: list[BaseMessage]) -> str:
    return "\n".join(f"{m.type}: {m.text}" for m in history[-6:]) or "(없음)"


class LLMJudges:
    def __init__(self, llm: BaseChatModel):
        self._grader = llm.with_structured_output(GradeResult)
        self._rewriter = llm.with_structured_output(RewriteResult)
        self._checker = llm.with_structured_output(GroundingResult)

    async def grade(self, question: str, sources: list[Source]) -> set[int]:
        if not sources:
            return set()
        result: GradeResult = await self._grader.ainvoke(
            [
                SystemMessage(GRADE_PROMPT),
                HumanMessage(f"질문: {question}\n\n문서 조각:\n{_numbered(sources)}"),
            ]
        )
        valid = {s["id"] for s in sources}
        return set(result.relevant_ids) & valid

    async def rewrite(self, question: str, previous_query: str, history: list[BaseMessage]) -> str:
        result: RewriteResult = await self._rewriter.ainvoke(
            [
                SystemMessage(REWRITE_PROMPT),
                HumanMessage(
                    f"대화 맥락:\n{_history_text(history)}\n\n원래 질문: {question}\n이전 검색어: {previous_query}"
                ),
            ]
        )
        return result.query.strip() or question

    async def check_grounding(self, answer: str, sources: list[Source]) -> GroundingResult:
        return await self._checker.ainvoke(
            [
                SystemMessage(GROUNDING_PROMPT),
                HumanMessage(f"문서 조각:\n{_numbered(sources)}\n\n답변:\n{answer}"),
            ]
        )
