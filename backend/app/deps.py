"""Shared FastAPI dependencies, as Annotated aliases so routes can declare `db: DbDep`."""

from typing import Annotated

from fastapi import Depends, Request
from langgraph.graph.state import CompiledStateGraph

from app.config import Settings, get_settings
from app.db import Database


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_graph(request: Request) -> CompiledStateGraph:
    return request.app.state.graph


DbDep = Annotated[Database, Depends(get_db)]
GraphDep = Annotated[CompiledStateGraph, Depends(get_graph)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
