"""Versioned schema migrations for the app's own tables.

Each migration runs once, in order, inside a transaction, and is recorded in
schema_migrations. A Postgres advisory lock serializes concurrent startups (the
API and the indexing worker boot at the same time).

The vector table is created by langchain-postgres and patched in Database.init,
because its name is configurable (the eval harness uses separate tables).
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

MIGRATION_LOCK_ID = 7_210_001

MIGRATIONS: list[tuple[int, str, list[str]]] = [
    (
        1,
        "documents",
        [
            "CREATE EXTENSION IF NOT EXISTS vector",
            """
            CREATE TABLE IF NOT EXISTS documents (
                id UUID PRIMARY KEY,
                filename TEXT NOT NULL,
                content_type TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                chunk_count INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """,
        ],
    ),
    (
        2,
        "users",
        [
            """
            CREATE TABLE users (
                id UUID PRIMARY KEY,
                email TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """,
            "CREATE UNIQUE INDEX users_email_key ON users (lower(email))",
        ],
    ),
    (
        3,
        "document ownership and indexing queue",
        [
            # Documents uploaded before accounts existed have no owner and are hidden.
            "ALTER TABLE documents ADD COLUMN owner_id UUID REFERENCES users (id) ON DELETE CASCADE",
            "ALTER TABLE documents ADD COLUMN status TEXT NOT NULL DEFAULT 'ready'",
            "ALTER TABLE documents ADD COLUMN error TEXT",
            "ALTER TABLE documents ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE documents ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT now()",
            """
            ALTER TABLE documents ADD CONSTRAINT documents_status_check
                CHECK (status IN ('pending', 'processing', 'ready', 'failed'))
            """,
            "CREATE INDEX documents_owner_idx ON documents (owner_id, created_at DESC)",
            # Partial index: the worker only ever scans for pending jobs.
            "CREATE INDEX documents_pending_idx ON documents (created_at) WHERE status = 'pending'",
            """
            CREATE TABLE document_files (
                document_id UUID PRIMARY KEY REFERENCES documents (id) ON DELETE CASCADE,
                data BYTEA NOT NULL
            )
            """,
        ],
    ),
    (
        4,
        "conversations",
        [
            """
            CREATE TABLE conversations (
                id UUID PRIMARY KEY,
                user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """,
            "CREATE INDEX conversations_user_idx ON conversations (user_id, updated_at DESC)",
            """
            CREATE TABLE messages (
                id BIGSERIAL PRIMARY KEY,
                conversation_id UUID NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                sources JSONB,
                grounded BOOLEAN,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """,
            "CREATE INDEX messages_conversation_idx ON messages (conversation_id, id)",
        ],
    ),
]


async def run_migrations(conn: AsyncConnection) -> list[int]:
    """Apply pending migrations. Must be called inside a transaction (engine.begin())."""
    await conn.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": MIGRATION_LOCK_ID})
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    )
    applied = set((await conn.execute(text("SELECT version FROM schema_migrations"))).scalars())
    newly_applied = []
    for version, name, statements in MIGRATIONS:
        if version in applied:
            continue
        for statement in statements:
            await conn.execute(text(statement))
        await conn.execute(
            text("INSERT INTO schema_migrations (version, name) VALUES (:v, :n)"), {"v": version, "n": name}
        )
        newly_applied.append(version)
    return newly_applied
