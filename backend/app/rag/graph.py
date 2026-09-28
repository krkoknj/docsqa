"""Corrective RAG pipeline as a LangGraph state graph.

    START → retrieve → grade ─(relevant docs)──────────────▶ generate → check ─(grounded)──▶ END
               ▲          └─(none, retries left)→ rewrite ┐     ▲          │
               └──────────────────────────────────────────┘     └─(not grounded, retries left)

- grade:   an LLM judge drops retrieved chunks that don't help answer the question.
- rewrite: if nothing relevant was found, rephrase the query and search again.
- check:   an LLM judge verifies the answer is supported by the sources; if not,
           the answer is regenerated once with the judge's feedback.
"""

from typing import Literal, Protocol, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from app.rag.judges import Judges
from app.rag.retriever import Candidate, RetrievalResult
from app.rag.types import Source

SYSTEM_PROMPT = """당신은 사용자가 업로드한 문서를 근거로 답변하는 어시스턴트입니다.

규칙:
- 아래 <context>에 있는 내용만 근거로 답하세요. 추측하지 마세요.
- 근거로 사용한 문장 뒤에 [1], [2]처럼 출처 번호를 붙이세요.
- 컨텍스트에서 답을 찾을 수 없으면 모른다고 솔직히 말하세요.
- 사용자의 질문 언어로 답하세요. 마크다운을 사용해도 됩니다.

<context>
{context}
</context>"""

RETRY_NOTE = """

주의: 직전 답변에 문서로 뒷받침되지 않는 내용이 있었습니다.
검증 의견: {feedback}
context에 명시된 내용만 사용해 다시 답하세요."""


class RAGState(TypedDict, total=False):
    question: str
    history: list[BaseMessage]
    document_ids: list[str] | None
    search_query: str
    rewrites: int
    sources: list[Source]
    answer: str
    generations: int
    grounded: bool | None
    feedback: str | None


def format_context(sources: list[Source]) -> str:
    if not sources:
        return "(검색된 문서 없음)"
    blocks = []
    for s in sources:
        location = f"{s['source']}" + (f" p.{s['page']}" if s["page"] else "")
        blocks.append(f"[{s['id']}] ({location})\n{s['content']}")
    return "\n\n".join(blocks)


class Retriever(Protocol):
    async def search(self, query: str, k: int, document_ids: list[str] | None = None) -> RetrievalResult: ...


def to_sources(candidates: list[Candidate]) -> list[Source]:
    return [
        Source(
            id=i + 1,
            document_id=str(c.doc.metadata.get("document_id")),
            source=c.doc.metadata.get("source", ""),
            page=c.doc.metadata.get("page"),
            score=round(c.score, 4),
            vector_rank=c.vector_rank,
            keyword_rank=c.keyword_rank,
            rerank_score=c.rerank_score,
            content=c.doc.page_content,
        )
        for i, c in enumerate(candidates)
    ]


def relevant_sources(state: RAGState) -> list[Source]:
    return [s for s in state.get("sources", []) if s.get("relevant")]


def build_graph(
    retriever: Retriever,
    llm: BaseChatModel,
    judges: Judges,
    *,
    k: int,
    max_rewrites: int = 1,
    max_generations: int = 2,
):
    def step(node: str, status: str, detail: str | None = None) -> None:
        get_stream_writer()({"type": "step", "node": node, "status": status, "detail": detail})

    async def retrieve(state: RAGState) -> RAGState:
        query = state.get("search_query") or state["question"]
        step("retrieve", "start", query)
        result = await retriever.search(query, k, state.get("document_ids"))
        step("retrieve", "end", f"{len(result.candidates)}개 검색")
        return {"sources": to_sources(result.candidates), "search_query": query}

    async def grade(state: RAGState) -> RAGState:
        step("grade", "start")
        sources = state["sources"]
        relevant_ids = await judges.grade(state["question"], sources)
        graded = [{**s, "relevant": s["id"] in relevant_ids} for s in sources]
        step("grade", "end", f"{len(sources)}개 중 {len(relevant_ids)}개 관련")
        return {"sources": graded}

    async def rewrite(state: RAGState) -> RAGState:
        step("rewrite", "start")
        query = await judges.rewrite(state["question"], state["search_query"], state.get("history", []))
        step("rewrite", "end", query)
        return {"search_query": query, "rewrites": state.get("rewrites", 0) + 1}

    async def generate(state: RAGState) -> RAGState:
        attempt = state.get("generations", 0)
        if attempt > 0:
            # Tell the client to discard the answer it has streamed so far.
            get_stream_writer()({"type": "reset"})
        step("generate", "start", "다시 생성" if attempt else None)

        prompt = SYSTEM_PROMPT.format(context=format_context(relevant_sources(state)))
        if attempt and state.get("feedback"):
            prompt += RETRY_NOTE.format(feedback=state["feedback"])
        messages = [SystemMessage(prompt), *state.get("history", []), HumanMessage(state["question"])]
        response = await llm.ainvoke(messages)

        step("generate", "end")
        return {"answer": response.text, "generations": attempt + 1}

    async def check(state: RAGState) -> RAGState:
        sources = relevant_sources(state)
        if not sources:
            # Nothing to verify against; the prompt already forces an "I don't know" answer.
            step("check", "end", "검증 생략 (관련 문서 없음)")
            return {"grounded": None, "feedback": None}
        step("check", "start")
        result = await judges.check_grounding(state["answer"], sources)
        step("check", "end", "근거 확인" if result.grounded else f"근거 부족: {result.reason}")
        return {"grounded": result.grounded, "feedback": result.reason}

    def route_after_grade(state: RAGState) -> Literal["generate", "rewrite"]:
        if relevant_sources(state) or state.get("rewrites", 0) >= max_rewrites:
            return "generate"
        return "rewrite"

    def route_after_check(state: RAGState) -> Literal["generate", "__end__"]:
        if state.get("grounded") is False and state.get("generations", 0) < max_generations:
            return "generate"
        return END

    graph = StateGraph(RAGState)
    graph.add_node("retrieve", retrieve)
    graph.add_node("grade", grade)
    graph.add_node("rewrite", rewrite)
    graph.add_node("generate", generate)
    graph.add_node("check", check)

    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "grade")
    graph.add_conditional_edges("grade", route_after_grade)
    graph.add_edge("rewrite", "retrieve")
    graph.add_edge("generate", "check")
    graph.add_conditional_edges("check", route_after_check)
    return graph.compile()


def to_messages(history: list[dict]) -> list[BaseMessage]:
    return [HumanMessage(m["content"]) if m["role"] == "user" else AIMessage(m["content"]) for m in history]
