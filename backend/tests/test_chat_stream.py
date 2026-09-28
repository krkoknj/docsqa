import json

from fastapi.testclient import TestClient
from langchain_core.documents import Document
from langchain_core.language_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from app.main import create_app
from app.rag.graph import build_graph
from app.rag.judges import GroundingResult
from app.rag.retriever import Candidate, RetrievalResult


class FakeRetriever:
    def __init__(self):
        self.queries: list[str] = []
        self.last_document_ids = None

    async def search(self, query, k, document_ids=None):
        self.queries.append(query)
        self.last_document_ids = document_ids
        docs = [
            Document(
                id="c1",
                page_content="Next.js는 React 프레임워크다.",
                metadata={"document_id": "d1", "source": "next.md", "page": None},
            ),
            Document(
                id="c2",
                page_content="점심 식대는 1만 2천 원이다.",
                metadata={"document_id": "d1", "source": "next.md", "page": None},
            ),
        ]
        return RetrievalResult(candidates=[Candidate(doc=d, vector_rank=i + 1) for i, d in enumerate(docs)])


class FakeJudges:
    """Scripted judge: each call pops the next scripted result."""

    def __init__(self, grades=None, groundings=None, rewrite_to="개선된 검색어"):
        self.grades = list(grades or [{1}])
        self.groundings = list(groundings or [True])
        self.rewrite_to = rewrite_to
        self.rewrite_calls = 0

    async def grade(self, question, sources):
        return self.grades.pop(0)

    async def rewrite(self, question, previous_query, history):
        self.rewrite_calls += 1
        return self.rewrite_to

    async def check_grounding(self, answer, sources):
        return GroundingResult(grounded=self.groundings.pop(0), reason="테스트 판정")


def parse_sse(body: str) -> list[tuple[str, object]]:
    events = []
    for block in body.replace("\r\n", "\n").strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.split("\n") if ": " in line)
        if "event" in fields:
            events.append((fields["event"], json.loads(fields["data"])))
    return events


def make_client(store=None, judges=None, answers=("Next.js는 React 프레임워크입니다 [1]",)) -> TestClient:
    app = create_app()  # lifespan is not run without the context manager, so no DB is needed
    llm = GenericFakeChatModel(messages=iter([AIMessage(a) for a in answers]))
    app.state.graph = build_graph(store or FakeRetriever(), llm, judges or FakeJudges(), k=4)
    return TestClient(app)


def chat(client: TestClient, **body) -> list[tuple[str, object]]:
    res = client.post("/api/chat", json={"question": "Next.js가 뭐야?", **body})
    assert res.status_code == 200
    return parse_sse(res.text)


def steps(events) -> list[tuple[str, str]]:
    return [(d["node"], d["status"]) for e, d in events if e == "step"]


def test_happy_path_streams_graded_sources_tokens_and_grounded_done():
    events = chat(make_client())

    assert [n for n, s in steps(events) if s == "start"] == ["retrieve", "grade", "generate", "check"]

    sources_events = [d for e, d in events if e == "sources"]
    assert len(sources_events) == 2  # raw retrieval, then graded
    graded = sources_events[-1]
    assert [s["relevant"] for s in graded] == [True, False]

    streamed = "".join(d["text"] for e, d in events if e == "token")
    assert events[-1] == ("done", {"answer": streamed, "grounded": True})
    assert streamed == "Next.js는 React 프레임워크입니다 [1]"


def test_no_relevant_docs_rewrites_query_and_retrieves_again():
    store = FakeRetriever()
    judges = FakeJudges(grades=[set(), {1}])

    events = chat(make_client(store, judges))

    assert judges.rewrite_calls == 1
    assert store.queries == ["Next.js가 뭐야?", "개선된 검색어"]
    assert [n for n, s in steps(events) if s == "start"] == [
        "retrieve",
        "grade",
        "rewrite",
        "retrieve",
        "grade",
        "generate",
        "check",
    ]
    rewrite_end = next(
        d for e, d in events if e == "step" and d["node"] == "rewrite" and d["status"] == "end"
    )
    assert rewrite_end["detail"] == "개선된 검색어"


def test_gives_up_rewriting_after_limit_and_skips_grounding_check():
    judges = FakeJudges(grades=[set(), set()])

    events = chat(make_client(judges=judges, answers=["문서에서 찾을 수 없습니다."]))

    assert judges.rewrite_calls == 1  # max_rewrites defaults to 1
    assert ("check", "start") not in steps(events)
    assert events[-1] == ("done", {"answer": "문서에서 찾을 수 없습니다.", "grounded": None})


def test_ungrounded_answer_is_reset_and_regenerated():
    judges = FakeJudges(groundings=[False, True])
    answers = ["지어낸 답변", "근거 있는 답변 [1]"]

    events = chat(make_client(judges=judges, answers=answers))

    names = [e for e, _ in events]
    assert names.count("reset") == 1
    after_reset = names.index("reset")
    streamed_after = "".join(d["text"] for e, d in events[after_reset:] if e == "token")
    assert streamed_after == "근거 있는 답변 [1]"
    assert events[-1] == ("done", {"answer": "근거 있는 답변 [1]", "grounded": True})


def test_stops_regenerating_after_max_generations():
    judges = FakeJudges(groundings=[False, False])

    events = chat(make_client(judges=judges, answers=["첫 답변", "두 번째 답변"]))

    assert [n for n, s in steps(events) if s == "start"].count("generate") == 2
    assert events[-1] == ("done", {"answer": "두 번째 답변", "grounded": False})


def test_chat_passes_document_filter_to_retriever():
    store = FakeRetriever()
    doc_id = "7c9e6679-7425-40de-944b-e07fc1f90ae7"

    chat(make_client(store), document_ids=[doc_id])

    assert store.last_document_ids == [doc_id]


def test_chat_rejects_empty_question():
    res = make_client().post("/api/chat", json={"question": ""})
    assert res.status_code == 422
