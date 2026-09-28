from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class UserOut(BaseModel):
    id: UUID
    email: str
    created_at: datetime


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


DocumentStatus = Literal["pending", "processing", "ready", "failed"]


class DocumentOut(BaseModel):
    id: UUID
    filename: str
    content_type: str
    size_bytes: int
    chunk_count: int
    status: DocumentStatus
    error: str | None
    created_at: datetime


class ConversationOut(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    id: int
    role: Literal["user", "assistant"]
    content: str
    sources: list[dict[str, Any]] | None
    grounded: bool | None
    created_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    # Omit to start a new conversation; history is loaded from the server, not trusted from the client.
    conversation_id: UUID | None = None
    # Restrict retrieval to these documents (must belong to the user). Omit to search all of them.
    document_ids: list[UUID] | None = None
