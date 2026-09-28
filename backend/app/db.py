from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings
from langchain_postgres import Column, PGEngine, PGVectorStore
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import Settings
from app.migrations import run_migrations
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


class Database:
    """Owns the SQLAlchemy engine, schema migrations, and the pgvector-backed vector store."""

    def __init__(self, settings: Settings, *, embeddings: Embeddings | None = None, link_documents: bool = True):
        """
        embeddings: override the OpenAI embedding model (tests use a deterministic fake).
        link_documents: add a FK from chunks to documents (ON DELETE CASCADE). The eval
            harness indexes chunks without document rows, so it turns this off.
        """
        self.settings = settings
        self.engine: AsyncEngine = create_async_engine(settings.database_url, pool_pre_ping=True)
        self.pg_engine = PGEngine.from_engine(self.engine)
        self.embeddings = embeddings or OpenAIEmbeddings(
            model=settings.openai_embedding_model, api_key=settings.openai_api_key
        )
        self.link_documents = link_documents
        self.vector_store: PGVectorStore | None = None

    async def init(self) -> None:
        async with self.engine.begin() as conn:
            await run_migrations(conn)
            exists = await conn.scalar(
                text("SELECT to_regclass(:name) IS NOT NULL"), {"name": self.settings.vector_table}
            )

        if not exists:
            await self.pg_engine.ainit_vectorstore_table(
                table_name=self.settings.vector_table,
                vector_size=self.settings.embedding_dim,
                metadata_columns=METADATA_COLUMNS,
            )

        await self._migrate_vector_table()

        self.vector_store = await PGVectorStore.create(
            engine=self.pg_engine,
            embedding_service=self.embeddings,
            table_name=self.settings.vector_table,
            metadata_columns=[c.name for c in METADATA_COLUMNS],
            k=self.settings.retrieval_k,
        )

    async def _migrate_vector_table(self) -> None:
        """Idempotent patches to the langchain-managed vector table."""
        name = self.settings.vector_table
        table = f'"{name}"'
        async with self.engine.begin() as conn:
            await conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:t))"), {"t": name})

            # Keyword search: tokenized text + generated tsvector + GIN index.
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS search_tokens TEXT"))
            await conn.execute(
                text(
                    f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS search_tsv tsvector "
                    "GENERATED ALWAYS AS (to_tsvector('simple', coalesce(search_tokens, ''))) STORED"
                )
            )
            await conn.execute(
                text(f'CREATE INDEX IF NOT EXISTS "{name}_search_tsv_idx" ON {table} USING GIN (search_tsv)')
            )
            rows = (
                await conn.execute(text(f"SELECT langchain_id, content FROM {table} WHERE search_tokens IS NULL"))
            ).all()
            for row in rows:
                await conn.execute(
                    text(f"UPDATE {table} SET search_tokens = :tokens WHERE langchain_id = :id"),
                    {"tokens": to_search_text(row.content), "id": row.langchain_id},
                )

            await conn.execute(text(f'CREATE INDEX IF NOT EXISTS "{name}_document_idx" ON {table} (document_id)'))

            if self.link_documents:
                has_fk = await conn.scalar(
                    text("SELECT 1 FROM pg_constraint WHERE conname = :c"), {"c": f"{name}_document_fk"}
                )
                if not has_fk:
                    # Chunks of documents deleted before this FK existed are unreachable; drop them.
                    await conn.execute(text(f"DELETE FROM {table} WHERE document_id NOT IN (SELECT id FROM documents)"))
                    await conn.execute(
                        text(
                            f'ALTER TABLE {table} ADD CONSTRAINT "{name}_document_fk" FOREIGN KEY (document_id) '
                            "REFERENCES documents (id) ON DELETE CASCADE"
                        )
                    )

    async def close(self) -> None:
        await self.engine.dispose()
