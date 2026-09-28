"""Streaming chat endpoint.

Conversations are stored server-side: the client sends only the new question and a
conversation_id, and history is loaded from the database (never trusted from the client).
Retrieval is always scoped to the current user's own, fully indexed documents.

Emits Server-Sent Events:
  conversation {"id": "...", "title": "..."}  first event; the conversation this turn belongs to
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
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from sse_starlette import EventSourceResponse, ServerSentEvent

from app.auth import CurrentUser
from app.config import Settings, get_settings
from app.db import Database
from app.deps import get_db, get_graph
from app.rag.graph import to_messages
from app.rag.stream import stream_events
from app.schemas import ChatRequest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])

TITLE_MAX = 40


def sse(event: str, data) -> ServerSentEvent:
    return ServerSentEvent(event=event, data=json.dumps(data, ensure_ascii=False))


async def searchable_document_ids(conn: AsyncConnection, user_id: UUID, requested: list[UUID] | None) -> list[str]:
    """The user's ready documents, optionally narrowed to `requested`. Never None: an empty
    list means "search nothing", so one user's query can't reach another user's chunks."""
    sql = "SELECT id FROM documents WHERE owner_id = :uid AND status = 'ready'"
    params: dict = {"uid": user_id}
    if requested:
        sql += " AND id = ANY(:ids)"
        params["ids"] = list(requested)
    return [str(i) for i in (await conn.execute(text(sql), params)).scalars()]


async def load_or_create_conversation(
    conn: AsyncConnection, user_id: UUID, conversation_id: UUID | None, question: str, history_limit: int
) -> tuple[UUID, str, list[dict]]:
    if conversation_id is None:
        title = question.strip().replace("\n", " ")
        title = title if len(title) <= TITLE_MAX else title[: TITLE_MAX - 1] + "…"
        new_id = uuid4()
        await conn.execute(
            text("INSERT INTO conversations (id, user_id, title) VALUES (:id, :uid, :title)"),
            {"id": new_id, "uid": user_id, "title": title},
        )
        return new_id, title, []

    title = await conn.scalar(
        text("SELECT title FROM conversations WHERE id = :id AND user_id = :uid"),
        {"id": conversation_id, "uid": user_id},
    )
    if title is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "대화를 찾을 수 없습니다.")
    rows = await conn.execute(
        text(
            "SELECT role, content FROM (SELECT id, role, content FROM messages WHERE conversation_id = :id "
            "ORDER BY id DESC LIMIT :n) recent ORDER BY id"
        ),
        {"id": conversation_id, "n": history_limit},
    )
    return conversation_id, title, [dict(r._mapping) for r in rows]


async def save_message(db: Database, conversation_id: UUID, role: str, content: str, sources=None, grounded=None):
    async with db.engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO messages (conversation_id, role, content, sources, grounded) "
                "VALUES (:cid, :role, :content, CAST(:sources AS jsonb), :grounded)"
            ),
            {
                "cid": conversation_id,
                "role": role,
                "content": content,
                "sources": json.dumps(sources, ensure_ascii=False) if sources is not None else None,
                "grounded": grounded,
            },
        )
        await conn.execute(text("UPDATE conversations SET updated_at = now() WHERE id = :id"), {"id": conversation_id})


@router.post("")
async def chat(
    req: ChatRequest,
    user: CurrentUser,
    db: Annotated[Database, Depends(get_db)],
    graph: Annotated[CompiledStateGraph, Depends(get_graph)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    async with db.engine.begin() as conn:
        document_ids = await searchable_document_ids(conn, user.id, req.document_ids)
        conversation_id, title, history = await load_or_create_conversation(
            conn, user.id, req.conversation_id, req.question, settings.history_messages
        )
    await save_message(db, conversation_id, "user", req.question)

    inputs = {"question": req.question, "history": to_messages(history), "document_ids": document_ids}

    async def events():
        yield sse("conversation", {"id": str(conversation_id), "title": title})
        sources: list = []
        try:
            async for event, data in stream_events(graph, inputs):
                if event == "sources":
                    sources = data
                elif event == "done":
                    await save_message(db, conversation_id, "assistant", data["answer"], sources, data["grounded"])
                yield sse(event, data)
        except Exception:
            logger.exception("chat stream failed")
            yield sse("error", {"message": "답변 생성 중 오류가 발생했습니다."})

    return EventSourceResponse(events())
