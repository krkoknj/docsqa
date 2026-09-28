"""Streaming chat endpoint.

Emits Server-Sent Events:
  step    {"node": "retrieve" | "grade" | "rewrite" | "generate" | "check",
           "status": "start" | "end", "detail": str | null}
  sources [{id, document_id, source, page, score, content, relevant?}, ...]
          (sent after retrieval, then again with relevance flags after grading)
  reset   {}  the answer streamed so far is discarded and regenerated
  token   {"text": "..."}
  done    {"answer": "...", "grounded": true | false | null}
  error   {"message": "..."}
"""

import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from langchain_core.messages import AIMessageChunk
from langgraph.graph.state import CompiledStateGraph
from sse_starlette import EventSourceResponse, ServerSentEvent

from app.deps import get_graph
from app.rag.graph import to_messages
from app.schemas import ChatRequest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])


def sse(event: str, data) -> ServerSentEvent:
    return ServerSentEvent(event=event, data=json.dumps(data, ensure_ascii=False))


@router.post("")
async def chat(req: ChatRequest, graph: Annotated[CompiledStateGraph, Depends(get_graph)]):
    inputs = {
        "question": req.question,
        "history": to_messages([m.model_dump() for m in req.history]),
        "document_ids": [str(d) for d in req.document_ids] if req.document_ids else None,
    }

    async def events():
        answer = ""
        grounded = None
        try:
            async for mode, chunk in graph.astream(inputs, stream_mode=["custom", "updates", "messages"]):
                if mode == "custom":
                    if chunk["type"] == "step":
                        yield sse("step", {k: chunk[k] for k in ("node", "status", "detail")})
                    elif chunk["type"] == "reset":
                        answer = ""
                        yield sse("reset", {})
                elif mode == "updates":
                    for node, update in chunk.items():
                        if node in ("retrieve", "grade"):
                            yield sse("sources", update["sources"])
                        elif node == "check":
                            grounded = update["grounded"]
                elif mode == "messages":
                    message, metadata = chunk
                    if metadata.get("langgraph_node") == "generate" and isinstance(message, AIMessageChunk):
                        if text := message.text:
                            answer += text
                            yield sse("token", {"text": text})
            yield sse("done", {"answer": answer, "grounded": grounded})
        except Exception:
            logger.exception("chat stream failed")
            yield sse("error", {"message": "답변 생성 중 오류가 발생했습니다."})

    return EventSourceResponse(events())
