"""Integration tests against a real Postgres + pgvector.

They create a throwaway database (default: rag_test on the docker-compose server) and
run the full app with fake models, so no OpenAI key is needed. Skipped if Postgres is
unreachable. Override the server with TEST_DATABASE_URL.
"""

import asyncio
import itertools
import os
import time

import asyncpg
import pytest
from fastapi.testclient import TestClient
from langchain_core.embeddings import DeterministicFakeEmbedding
from langchain_core.language_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from app.config import Settings
from app.main import create_app
from app.rag.judges import GroundingResult

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://rag:rag@localhost:5432/rag_test")


class AlwaysRelevantJudges:
    async def grade(self, question, sources):
        return {s["id"] for s in sources}

    async def rewrite(self, question, previous_query, history):
        return question

    async def check_grounding(self, answer, sources):
        return GroundingResult(grounded=True, reason="test")


async def _recreate_database(url: str) -> None:
    dsn = url.replace("postgresql+asyncpg://", "postgresql://")
    admin_dsn, _, db_name = dsn.rpartition("/")
    conn = await asyncpg.connect(f"{admin_dsn}/postgres", timeout=3)
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def client():
    try:
        asyncio.run(_recreate_database(TEST_DATABASE_URL))
    except (OSError, asyncpg.PostgresError, TimeoutError) as e:
        pytest.skip(f"Postgres not available for integration tests: {e}")

    settings = Settings(
        _env_file=None,
        database_url=TEST_DATABASE_URL,
        openai_api_key="test-not-used",
        jwt_secret="test-secret-that-is-at-least-32-bytes-long",
        reranker="none",
        embedded_worker=True,
        worker_poll_seconds=0.05,
    )
    app = create_app(
        settings,
        embeddings=DeterministicFakeEmbedding(size=settings.embedding_dim),
        chat_llm=GenericFakeChatModel(messages=itertools.cycle([AIMessage("문서에 따르면 그렇습니다 [1]")])),
        judges=AlwaysRelevantJudges(),
    )
    with TestClient(app) as c:
        yield c


_counter = itertools.count()


class UserSession:
    """One logged-in user. All users share the app's single TestClient (its event loop owns the
    DB pool), so the session cookie is sent explicitly instead of living in the shared cookie jar."""

    def __init__(self, client: TestClient, token: str, email: str):
        self.client, self.token, self.email = client, token, email

    def request(self, method: str, url: str, **kwargs):
        self.client.cookies.clear()
        headers = {**kwargs.pop("headers", {}), "Cookie": f"docsqa_session={self.token}"}
        return self.client.request(method, url, headers=headers, **kwargs)

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)

    def delete(self, url, **kw):
        return self.request("DELETE", url, **kw)


def signup(client: TestClient, email: str | None = None, password: str = "password123"):
    email = email or f"user{next(_counter)}-{time.time_ns()}@example.com"
    client.cookies.clear()
    return client.post("/api/auth/signup", json={"email": email, "password": password}), email


@pytest.fixture
def new_user(client):
    """Factory: signs up a fresh user and returns their session."""

    def make() -> UserSession:
        res, email = signup(client)
        assert res.status_code == 201, res.text
        return UserSession(client, res.cookies["docsqa_session"], email)

    return make


def wait_until_indexed(session: UserSession, document_id: str, timeout: float = 10) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        doc = next(d for d in session.get("/api/documents").json() if d["id"] == document_id)
        if doc["status"] in ("ready", "failed"):
            return doc
        time.sleep(0.05)
    raise AssertionError(f"document {document_id} was not indexed in {timeout}s")
