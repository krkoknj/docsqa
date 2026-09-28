from fastapi import Request

from app.db import Database


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_graph(request: Request):
    return request.app.state.graph
