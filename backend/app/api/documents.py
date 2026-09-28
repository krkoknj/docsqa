"""Document upload is asynchronous: the API stores the file and enqueues it; the
indexing worker (app/worker.py) parses, chunks, and embeds it. Clients poll the
list endpoint for status (pending -> processing -> ready | failed)."""

from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, UploadFile, status
from sqlalchemy import text

from app.auth import CurrentUser
from app.deps import DbDep, SettingsDep
from app.rag.ingest import UnsupportedFileError, check_extension
from app.schemas import DocumentOut

router = APIRouter(prefix="/api/documents", tags=["documents"])

DOCUMENT_COLUMNS = "id, filename, content_type, size_bytes, chunk_count, status, error, created_at"


@router.get("", response_model=list[DocumentOut])
async def list_documents(user: CurrentUser, db: DbDep):
    async with db.engine.connect() as conn:
        rows = await conn.execute(
            text(f"SELECT {DOCUMENT_COLUMNS} FROM documents WHERE owner_id = :uid ORDER BY created_at DESC"),
            {"uid": user.id},
        )
        return [dict(r._mapping) for r in rows]


@router.post("", response_model=DocumentOut, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(file: UploadFile, user: CurrentUser, db: DbDep, settings: SettingsDep):
    filename = file.filename or "untitled"
    try:
        check_extension(filename)
    except UnsupportedFileError as e:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(e)) from None
    data = await file.read()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"파일은 {settings.max_upload_mb}MB 이하만 업로드할 수 있습니다.",
        )
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "빈 파일입니다.")

    document_id = uuid4()
    async with db.engine.begin() as conn:
        row = (
            await conn.execute(
                text(
                    f"""
                    INSERT INTO documents (id, owner_id, filename, content_type, size_bytes, status)
                    VALUES (:id, :owner, :filename, :content_type, :size, 'pending')
                    RETURNING {DOCUMENT_COLUMNS}
                    """
                ),
                {
                    "id": document_id,
                    "owner": user.id,
                    "filename": filename,
                    "content_type": file.content_type or "application/octet-stream",
                    "size": len(data),
                },
            )
        ).one()
        await conn.execute(
            text("INSERT INTO document_files (document_id, data) VALUES (:id, :data)"),
            {"id": document_id, "data": data},
        )
    return dict(row._mapping)


@router.post("/{document_id}/retry", response_model=DocumentOut)
async def retry_document(document_id: UUID, user: CurrentUser, db: DbDep):
    async with db.engine.begin() as conn:
        row = (
            await conn.execute(
                text(
                    f"""
                    UPDATE documents SET status = 'pending', error = NULL, attempts = 0, updated_at = now()
                    WHERE id = :id AND owner_id = :uid AND status = 'failed'
                    RETURNING {DOCUMENT_COLUMNS}
                    """
                ),
                {"id": document_id, "uid": user.id},
            )
        ).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "재시도할 수 있는 문서가 없습니다.")
    return dict(row._mapping)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: UUID, user: CurrentUser, db: DbDep):
    # Chunks and the stored file are removed by ON DELETE CASCADE.
    async with db.engine.begin() as conn:
        result = await conn.execute(
            text("DELETE FROM documents WHERE id = :id AND owner_id = :uid"),
            {"id": document_id, "uid": user.id},
        )
    if result.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "문서를 찾을 수 없습니다.")
