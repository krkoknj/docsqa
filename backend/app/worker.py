"""Background indexing worker backed by a Postgres job queue.

The `documents` table is the queue: uploads insert rows with status='pending'.
Workers claim one job at a time with `FOR UPDATE SKIP LOCKED`, so any number of
worker processes can run concurrently without taking the same job, and no extra
broker (Redis, RabbitMQ) is needed.

    pending ──claim──▶ processing ──ok──▶ ready
       ▲                    │
       └──retry (< max)─────┤
                            └──attempts exhausted──▶ failed

Jobs stuck in 'processing' (worker crashed mid-job) are returned to 'pending'
after `stale_job_minutes`.

Run standalone:  python -m app.worker
"""

import asyncio
import logging
import signal
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text

from app.config import Settings, get_settings
from app.db import Database
from app.rag.ingest import load_pages, split_into_chunks

logger = logging.getLogger("app.worker")

CLAIM_JOB = text(
    """
    UPDATE documents
    SET status = 'processing', attempts = attempts + 1, updated_at = now()
    WHERE id = (
        SELECT id FROM documents
        WHERE status = 'pending'
        ORDER BY created_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    RETURNING id, filename, attempts
    """
)

REQUEUE_STALE = text(
    """
    UPDATE documents SET status = 'pending', updated_at = now()
    WHERE status = 'processing' AND updated_at < now() - make_interval(mins => :minutes)
    """
)


@dataclass
class Job:
    id: UUID
    filename: str
    attempts: int


class IndexingError(Exception):
    """A failure that retrying won't fix (bad file, no text)."""


class IndexWorker:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        logger.info("indexing worker started")
        await self.requeue_stale()
        while not self._stop.is_set():
            try:
                processed = await self.run_once()
            except Exception:
                logger.exception("worker loop error")
                processed = False
            if not processed:
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self.settings.worker_poll_seconds)
                except TimeoutError:
                    pass
        logger.info("indexing worker stopped")

    async def requeue_stale(self) -> None:
        async with self.db.engine.begin() as conn:
            result = await conn.execute(REQUEUE_STALE, {"minutes": self.settings.stale_job_minutes})
        if result.rowcount:
            logger.warning("requeued %d stale jobs", result.rowcount)

    async def run_once(self) -> bool:
        """Claim and process one job. Returns False when the queue is empty."""
        async with self.db.engine.begin() as conn:
            row = (await conn.execute(CLAIM_JOB)).one_or_none()
        if row is None:
            return False
        job = Job(id=row.id, filename=row.filename, attempts=row.attempts)
        logger.info("indexing %s (%s), attempt %d", job.filename, job.id, job.attempts)

        try:
            chunk_count = await self.index(job)
        except IndexingError as e:
            await self.fail(job, str(e), retry=False)
        except Exception as e:
            logger.exception("indexing %s failed", job.id)
            await self.fail(job, f"색인 중 오류가 발생했습니다: {type(e).__name__}", retry=True)
        else:
            await self.finish(job, chunk_count)
        return True

    async def index(self, job: Job) -> int:
        async with self.db.engine.connect() as conn:
            data = await conn.scalar(text("SELECT data FROM document_files WHERE document_id = :id"), {"id": job.id})
        if data is None:  # deleted while queued
            raise IndexingError("원본 파일을 찾을 수 없습니다.")

        try:
            pages = await asyncio.to_thread(load_pages, job.filename, data)
        except Exception as e:
            raise IndexingError("파일을 읽을 수 없습니다. 손상되었거나 지원하지 않는 형식입니다.") from e
        chunks = split_into_chunks(job.id, job.filename, pages, self.settings.chunk_size, self.settings.chunk_overlap)
        if not chunks:
            raise IndexingError("문서에서 텍스트를 추출하지 못했습니다. (스캔한 이미지 PDF일 수 있습니다)")

        # Make retries idempotent: drop chunks a previous failed attempt may have written.
        table = f'"{self.settings.vector_table}"'
        async with self.db.engine.begin() as conn:
            await conn.execute(text(f"DELETE FROM {table} WHERE document_id = :id"), {"id": job.id})
        await self.db.vector_store.aadd_documents(chunks)
        return len(chunks)

    async def finish(self, job: Job, chunk_count: int) -> None:
        async with self.db.engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE documents SET status = 'ready', chunk_count = :n, error = NULL, updated_at = now() "
                    "WHERE id = :id"
                ),
                {"id": job.id, "n": chunk_count},
            )
        logger.info("indexed %s: %d chunks", job.id, chunk_count)

    async def fail(self, job: Job, message: str, *, retry: bool) -> None:
        give_up = not retry or job.attempts >= self.settings.max_index_attempts
        async with self.db.engine.begin() as conn:
            await conn.execute(
                text("UPDATE documents SET status = :status, error = :error, updated_at = now() WHERE id = :id"),
                {"id": job.id, "status": "failed" if give_up else "pending", "error": message},
            )
        logger.warning("indexing %s %s: %s", job.id, "failed" if give_up else "will retry", message)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    db = Database(settings)
    await db.init()
    worker = IndexWorker(db, settings)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, worker.stop)
        except NotImplementedError:  # Windows
            pass
    try:
        await worker.run()
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
