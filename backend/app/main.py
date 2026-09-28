import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.api import auth, chat, conversations, documents
from app.config import Settings, get_settings
from app.db import Database
from app.rag.factory import build_retriever
from app.rag.graph import build_graph
from app.rag.judges import Judges, LLMJudges
from app.worker import IndexWorker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    embeddings: Embeddings | None = None,
    chat_llm: BaseChatModel | None = None,
    judges: Judges | None = None,
) -> FastAPI:
    """Settings and model overrides exist for tests; by default everything comes from the environment."""
    custom_settings = settings is not None
    settings = settings or get_settings()
    if settings.jwt_secret == Settings.model_fields["jwt_secret"].default:
        logger.warning("JWT_SECRET is not set; using an insecure development secret")
    elif len(settings.jwt_secret.encode()) < 32:
        logger.warning("JWT_SECRET is shorter than 32 bytes; use a longer random secret")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = Database(settings, embeddings=embeddings)
        await db.init()
        judge_llm = ChatOpenAI(model=settings.openai_judge_model, api_key=settings.openai_api_key)
        llm = chat_llm or ChatOpenAI(model=settings.openai_chat_model, api_key=settings.openai_api_key)

        app.state.db = db
        app.state.graph = build_graph(
            build_retriever(settings, db, judge_llm),
            llm,
            judges or LLMJudges(judge_llm),
            k=settings.retrieval_k,
            max_rewrites=settings.max_query_rewrites,
            max_generations=settings.max_generations,
        )

        worker = IndexWorker(db, settings) if settings.embedded_worker else None
        worker_task = asyncio.create_task(worker.run()) if worker else None
        app.state.worker = worker
        try:
            yield
        finally:
            if worker:
                worker.stop()
                await worker_task
            await db.close()

    app = FastAPI(title="DocsQA API", version="0.2.0", lifespan=lifespan)
    if custom_settings:
        app.dependency_overrides[get_settings] = lambda: settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for module in (auth, documents, conversations, chat):
        app.include_router(module.router)

    @app.get("/health", tags=["health"])
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
