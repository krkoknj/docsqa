from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy import text

from app.config import Settings, get_settings
from app.db import Database
from app.deps import get_db
from app.rag.ingest import UnsupportedFileError, load_pages, split_into_chunks
from app.schemas import DocumentOut

router = APIRouter(prefix="/api/documents", tags=["documents"])

DbDep = Annotated[Database, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.get("", response_model=list[DocumentOut])
async def list_documents(db: DbDep):
    async with db.engine.connect() as conn:
        rows = await conn.execute(text("SELECT * FROM documents ORDER BY created_at DESC"))
        return [dict(r._mapping) for r in rows]


@router.post("", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(file: UploadFile, db: DbDep, settings: SettingsDep):
    filename = file.filename or "untitled"
    data = await file.read()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"파일은 {settings.max_upload_mb}MB 이하만 업로드할 수 있습니다.",
        )

    try:
        pages = load_pages(filename, data)
    except UnsupportedFileError as e:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(e)) from e

    document_id = uuid4()
    chunks = split_into_chunks(document_id, filename, pages, settings.chunk_size, settings.chunk_overlap)
    if not chunks:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "문서에서 텍스트를 추출하지 못했습니다.")

    # TODO(stage 4): move embedding to a background job queue for large files.
    await db.vector_store.aadd_documents(chunks)

    async with db.engine.begin() as conn:
        row = await conn.execute(
            text(
                """
                INSERT INTO documents (id, filename, content_type, size_bytes, chunk_count)
                VALUES (:id, :filename, :content_type, :size_bytes, :chunk_count)
                RETURNING *
                """
            ),
            {
                "id": document_id,
                "filename": filename,
                "content_type": file.content_type or "application/octet-stream",
                "size_bytes": len(data),
                "chunk_count": len(chunks),
            },
        )
        return dict(row.one()._mapping)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: UUID, db: DbDep):
    async with db.engine.begin() as conn:
        result = await conn.execute(text("DELETE FROM documents WHERE id = :id"), {"id": document_id})
    if result.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "문서를 찾을 수 없습니다.")
    await db.vector_store.adelete(filter={"document_id": {"$eq": str(document_id)}})
