import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langchain_openai import ChatOpenAI

from app.api import chat, documents
from app.config import get_settings
from app.db import Database
from app.rag.factory import build_retriever
from app.rag.graph import build_graph
from app.rag.judges import LLMJudges

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    db = Database(settings)
    await db.init()
    llm = ChatOpenAI(model=settings.openai_chat_model, api_key=settings.openai_api_key)
    judge_llm = ChatOpenAI(model=settings.openai_judge_model, api_key=settings.openai_api_key)

    app.state.db = db
    app.state.graph = build_graph(
        build_retriever(settings, db, judge_llm),
        llm,
        LLMJudges(judge_llm),
        k=settings.retrieval_k,
        max_rewrites=settings.max_query_rewrites,
        max_generations=settings.max_generations,
    )
    yield
    await db.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="DocsQA API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(documents.router)
    app.include_router(chat.router)

    @app.get("/health", tags=["health"])
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
