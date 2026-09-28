from langchain_openai import OpenAIEmbeddings
from langchain_postgres import Column, PGEngine, PGVectorStore
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import Settings
from app.rag.tokenize import to_search_text

# Metadata stored as real columns so they can be filtered in SQL.
METADATA_COLUMNS = [
    Column("document_id", "UUID", nullable=False),
    Column("source", "TEXT", nullable=False),
    Column("page", "INTEGER"),
    Column("chunk_index", "INTEGER", nullable=False),
    # Pre-tokenized text for keyword search (see app/rag/tokenize.py).
    Column("search_tokens", "TEXT"),
]

CREATE_DOCUMENTS_TABLE = """
CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY,
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


class Database:
    """Owns the SQLAlchemy engine and the pgvector-backed vector store."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.engine: AsyncEngine = create_async_engine(settings.database_url, pool_pre_ping=True)
        self.pg_engine = PGEngine.from_engine(self.engine)
        self.vector_store: PGVectorStore | None = None

    async def init(self) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.execute(text(CREATE_DOCUMENTS_TABLE))
            exists = await conn.scalar(
                text("SELECT to_regclass(:name) IS NOT NULL"),
                {"name": self.settings.vector_table},
            )

        if not exists:
            await self.pg_engine.ainit_vectorstore_table(
                table_name=self.settings.vector_table,
                vector_size=self.settings.embedding_dim,
                metadata_columns=METADATA_COLUMNS,
            )

        await self._migrate_keyword_search()

        embeddings = OpenAIEmbeddings(
            model=self.settings.openai_embedding_model,
            api_key=self.settings.openai_api_key,
        )
        self.vector_store = await PGVectorStore.create(
            engine=self.pg_engine,
            embedding_service=embeddings,
            table_name=self.settings.vector_table,
            metadata_columns=[c.name for c in METADATA_COLUMNS],
            k=self.settings.retrieval_k,
        )

    async def _migrate_keyword_search(self) -> None:
        """Add the full-text search column + GIN index, and backfill rows indexed before it existed."""
        table = f'"{self.settings.vector_table}"'
        async with self.engine.begin() as conn:
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS search_tokens TEXT"))
            await conn.execute(
                text(
                    f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS search_tsv tsvector "
                    "GENERATED ALWAYS AS (to_tsvector('simple', coalesce(search_tokens, ''))) STORED"
                )
            )
            await conn.execute(
                text(
                    f'CREATE INDEX IF NOT EXISTS "{self.settings.vector_table}_search_tsv_idx" '
                    f"ON {table} USING GIN (search_tsv)"
                )
            )
            rows = (
                await conn.execute(
                    text(f"SELECT langchain_id, content FROM {table} WHERE search_tokens IS NULL")
                )
            ).all()
            for row in rows:
                await conn.execute(
                    text(f"UPDATE {table} SET search_tokens = :tokens WHERE langchain_id = :id"),
                    {"tokens": to_search_text(row.content), "id": row.langchain_id},
                )

    async def close(self) -> None:
        await self.engine.dispose()
