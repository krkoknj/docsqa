from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text

from app.auth import CurrentUser
from app.deps import DbDep
from app.schemas import ConversationDetail, ConversationOut

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationOut])
async def list_conversations(user: CurrentUser, db: DbDep):
    async with db.engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT id, title, created_at, updated_at FROM conversations "
                "WHERE user_id = :uid ORDER BY updated_at DESC LIMIT 100"
            ),
            {"uid": user.id},
        )
        return [dict(r._mapping) for r in rows]


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: UUID, user: CurrentUser, db: DbDep):
    async with db.engine.connect() as conn:
        conv = (
            await conn.execute(
                text("SELECT id, title, created_at, updated_at FROM conversations WHERE id = :id AND user_id = :uid"),
                {"id": conversation_id, "uid": user.id},
            )
        ).one_or_none()
        if conv is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "대화를 찾을 수 없습니다.")
        messages = await conn.execute(
            text(
                "SELECT id, role, content, sources, grounded, created_at FROM messages "
                "WHERE conversation_id = :id ORDER BY id"
            ),
            {"id": conversation_id},
        )
        return {**conv._mapping, "messages": [dict(m._mapping) for m in messages]}


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(conversation_id: UUID, user: CurrentUser, db: DbDep):
    async with db.engine.begin() as conn:
        result = await conn.execute(
            text("DELETE FROM conversations WHERE id = :id AND user_id = :uid"),
            {"id": conversation_id, "uid": user.id},
        )
    if result.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "대화를 찾을 수 없습니다.")
