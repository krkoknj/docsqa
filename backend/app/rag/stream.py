"""Translate a LangGraph run into the chat SSE event protocol (see app/api/chat.py).

Kept free of HTTP and database concerns so every graph branch can be unit-tested.
"""

from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import AIMessageChunk
from langgraph.graph.state import CompiledStateGraph


async def stream_events(graph: CompiledStateGraph, inputs: dict) -> AsyncIterator[tuple[str, Any]]:
    answer = ""
    grounded = None
    async for mode, chunk in graph.astream(inputs, stream_mode=["custom", "updates", "messages"]):
        if mode == "custom":
            if chunk["type"] == "step":
                yield "step", {k: chunk[k] for k in ("node", "status", "detail")}
            elif chunk["type"] == "reset":
                answer = ""
                yield "reset", {}
        elif mode == "updates":
            for node, update in chunk.items():
                if node in ("retrieve", "grade"):
                    yield "sources", update["sources"]
                elif node == "check":
                    grounded = update["grounded"]
        elif mode == "messages":
            message, metadata = chunk
            if metadata.get("langgraph_node") == "generate" and isinstance(message, AIMessageChunk):
                if piece := message.text:
                    answer += piece
                    yield "token", {"text": piece}
    yield "done", {"answer": answer, "grounded": grounded}
