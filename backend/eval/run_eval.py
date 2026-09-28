"""Evaluate retrieval and end-to-end answer quality over the sample corpus.

Usage (from backend/):
    uv run --group eval python -m eval.run_eval                        # retrieval metrics only (cheap)
    uv run --group eval python -m eval.run_eval --e2e                  # + full graph with RAGAS metrics
    uv run --group eval python -m eval.run_eval --chunk-size 400 --configs hybrid+cross-encoder

Samples in ../samples are indexed into a separate table (eval_chunks_<size>), so the
app's own documents are never touched.

Retrieval metrics (answerable questions only; a hit = a retrieved chunk contains the
question's evidence string):
    Hit@1, Hit@k (recall), MRR@k
End-to-end metrics (RAGAS, LLM-judged):
    faithfulness       - are the answer's claims supported by the retrieved context?
    answer_correctness - does the answer match the reference answer?
    context_recall     - does the retrieved context contain what the reference needs?
    abstention         - for unanswerable questions, did the system decline to answer?
"""

import argparse
import asyncio
import json
import statistics
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from langchain_openai import ChatOpenAI
from sqlalchemy import text

from app.config import get_settings
from app.db import Database
from app.rag.factory import build_retriever
from app.rag.graph import build_graph, relevant_sources
from app.rag.ingest import load_pages, split_into_chunks
from app.rag.judges import LLMJudges
from eval import _compat  # noqa: F401  (patches ragas imports; ragas is imported lazily below)

ROOT = Path(__file__).parent
SAMPLES = ROOT.parent.parent / "samples"
DEFAULT_CONFIGS = "vector,keyword,hybrid,hybrid+cross-encoder,hybrid+llm"
ABSTAIN_MARKERS = ("없습니다", "찾을 수 없", "모르", "알 수 없", "포함되어 있지 않", "나와 있지 않")


@dataclass
class ConfigResult:
    name: str
    hit1: float = 0.0
    hitk: float = 0.0
    mrr: float = 0.0
    by_type: dict[str, float] = field(default_factory=dict)
    retrieval_ms: float = 0.0
    misses: list[str] = field(default_factory=list)
    e2e: dict[str, float] | None = None


def parse_config(config: str) -> tuple[str, str]:
    mode, _, reranker = config.partition("+")
    return mode, reranker or "none"


async def ensure_index(db: Database, table: str, chunk_size: int, chunk_overlap: int) -> int:
    async with db.engine.connect() as conn:
        count = await conn.scalar(text(f'SELECT count(*) FROM "{table}"'))
    if count:
        return count
    chunks = []
    for path in sorted(SAMPLES.glob("*.md")):
        pages = load_pages(path.name, path.read_bytes())
        chunks += split_into_chunks(uuid.uuid4(), path.name, pages, chunk_size, chunk_overlap)
    await db.vector_store.aadd_documents(chunks)
    return len(chunks)


def first_hit_rank(contents: list[str], evidence: str) -> int | None:
    return next((i + 1 for i, c in enumerate(contents) if evidence in c), None)


async def eval_retrieval(retriever, questions: list[dict], k: int) -> ConfigResult:
    result = ConfigResult(name=retriever.name)
    ranks: list[int | None] = []
    latencies: list[float] = []
    type_hits: dict[str, list[bool]] = {}
    for q in questions:
        start = time.perf_counter()
        found = await retriever.search(q["question"], k)
        latencies.append((time.perf_counter() - start) * 1000)
        rank = first_hit_rank([c.doc.page_content for c in found.candidates], q["evidence"])
        ranks.append(rank)
        type_hits.setdefault(q["type"], []).append(rank is not None)
        if rank is None:
            result.misses.append(q["id"])

    n = len(questions)
    result.hit1 = sum(r == 1 for r in ranks) / n
    result.hitk = sum(r is not None for r in ranks) / n
    result.mrr = sum(1 / r for r in ranks if r) / n
    result.by_type = {t: sum(h) / len(h) for t, h in type_hits.items()}
    result.retrieval_ms = statistics.median(latencies)
    return result


async def eval_e2e(graph, questions: list[dict], ragas_llm, concurrency: int) -> dict[str, float]:
    from ragas.metrics.collections import AnswerCorrectness, ContextRecall, Faithfulness

    faithfulness = Faithfulness(llm=ragas_llm)
    correctness = AnswerCorrectness(llm=ragas_llm, weights=[1.0, 0.0])  # factual overlap only
    recall = ContextRecall(llm=ragas_llm)
    sem = asyncio.Semaphore(concurrency)

    async def run(q: dict) -> dict:
        async with sem:
            start = time.perf_counter()
            state = await graph.ainvoke({"question": q["question"], "history": []})
            latency = time.perf_counter() - start
            answer = state["answer"]
            contexts = [s["content"] for s in relevant_sources(state)] or [""]
            row = {"latency": latency, "rewrites": state.get("rewrites", 0)}
            if q["evidence"] is None:
                row["abstained"] = any(m in answer for m in ABSTAIN_MARKERS)
                return row
            row["faithfulness"] = (await faithfulness.ascore(q["question"], answer, contexts)).value
            row["correctness"] = (await correctness.ascore(q["question"], answer, q["reference"])).value
            row["context_recall"] = (await recall.ascore(q["question"], contexts, q["reference"])).value
            return row

    rows = await asyncio.gather(*(run(q) for q in questions))
    answerable = [r for r in rows if "abstained" not in r]
    unanswerable = [r for r in rows if "abstained" in r]

    def mean(key: str, items: list[dict]) -> float:
        values = [r[key] for r in items if r.get(key) is not None]
        return statistics.fmean(values) if values else float("nan")

    return {
        "faithfulness": mean("faithfulness", answerable),
        "answer_correctness": mean("correctness", answerable),
        "context_recall": mean("context_recall", answerable),
        "abstention": sum(r["abstained"] for r in unanswerable) / max(len(unanswerable), 1),
        "latency_s": statistics.median(r["latency"] for r in rows),
        "rewrite_rate": sum(r["rewrites"] > 0 for r in rows) / len(rows),
    }


def render_report(args, chunk_count: int, n_answerable: int, results: list[ConfigResult]) -> str:
    types = sorted({t for r in results for t in r.by_type})
    lines = [
        f"# RAG 평가 결과 — {datetime.now():%Y-%m-%d %H:%M}",
        "",
        f"- 코퍼스: `samples/*.md` → 청크 {chunk_count}개 (chunk_size={args.chunk_size}, overlap={args.chunk_overlap})",
        f"- 질문: 답이 있는 질문 {n_answerable}개로 검색 평가, k={args.k}",
        "",
        "## 검색 품질",
        "",
        "| 구성 | Hit@1 | Hit@k | MRR | " + " | ".join(f"Hit@k ({t})" for t in types) + " | 검색 지연 (중앙값) |",
        "|---|---|---|---|" + "---|" * len(types) + "---|",
    ]
    for r in results:
        per_type = " | ".join(f"{r.by_type.get(t, 0):.0%}" for t in types)
        lines.append(
            f"| `{r.name}` | {r.hit1:.0%} | {r.hitk:.0%} | {r.mrr:.3f} | {per_type} | {r.retrieval_ms:.0f} ms |"
        )
    lines += ["", "놓친 질문:", ""]
    lines += [f"- `{r.name}`: {', '.join(r.misses) or '없음'}" for r in results]

    e2e = [r for r in results if r.e2e]
    if e2e:
        lines += [
            "",
            "## 전체 파이프라인 (RAGAS)",
            "",
            "| 구성 | Faithfulness | Answer correctness | Context recall | 답변 거부 정확도 | 재검색 비율 | 응답 시간 (중앙값) |",
            "|---|---|---|---|---|---|---|",
        ]
        for r in e2e:
            m = r.e2e
            lines.append(
                f"| `{r.name}` | {m['faithfulness']:.3f} | {m['answer_correctness']:.3f} | "
                f"{m['context_recall']:.3f} | {m['abstention']:.0%} | {m['rewrite_rate']:.0%} | "
                f"{m['latency_s']:.1f} s |"
            )
    return "\n".join(lines) + "\n"


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--configs", default=DEFAULT_CONFIGS)
    parser.add_argument("--chunk-size", type=int, default=400)
    parser.add_argument("--chunk-overlap", type=int, default=80)
    parser.add_argument("--k", type=int, default=4)
    parser.add_argument("--e2e", action="store_true", help="also run the full graph and RAGAS metrics")
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()

    base = get_settings()
    settings = base.model_copy(update={"vector_table": f"eval_chunks_{args.chunk_size}_{args.chunk_overlap}"})
    db = Database(settings, link_documents=False)  # eval chunks have no document rows
    await db.init()
    chunk_count = await ensure_index(db, settings.vector_table, args.chunk_size, args.chunk_overlap)

    questions = json.loads((ROOT / "dataset.json").read_text(encoding="utf-8"))
    answerable = [q for q in questions if q["evidence"]]

    judge_llm = ChatOpenAI(model=settings.openai_judge_model, api_key=settings.openai_api_key)
    chat_llm = ChatOpenAI(model=settings.openai_chat_model, api_key=settings.openai_api_key)
    ragas_llm = None
    if args.e2e:
        from openai import AsyncOpenAI
        from ragas.llms import llm_factory

        ragas_llm = llm_factory(settings.openai_judge_model, client=AsyncOpenAI(api_key=settings.openai_api_key))

    results = []
    for config in args.configs.split(","):
        mode, reranker = parse_config(config.strip())
        retriever = build_retriever(settings, db, judge_llm, mode=mode, reranker=reranker)
        print(f"[retrieval] {retriever.name} ...", flush=True)
        result = await eval_retrieval(retriever, answerable, args.k)
        if args.e2e:
            print(f"[e2e] {retriever.name} ...", flush=True)
            graph = build_graph(retriever, chat_llm, LLMJudges(judge_llm), k=args.k)
            result.e2e = await eval_e2e(graph, questions, ragas_llm, args.concurrency)
        results.append(result)

    report = render_report(args, chunk_count, len(answerable), results)
    out_dir = ROOT / "results"
    out_dir.mkdir(exist_ok=True)
    name = f"chunk{args.chunk_size}" + ("_e2e" if args.e2e else "")
    (out_dir / f"{name}.md").write_text(report, encoding="utf-8")
    print("\n" + report)
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
