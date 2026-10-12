"""LangGraph checkpointer factory.

Checkpoints make human-approval interrupts durable: a run paused for approval survives process
restarts and can be resumed by any replica that shares the checkpoint store.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.engine import make_url

from src.config import Settings


def _psycopg_dsn(url: str) -> str:
    parsed = make_url(url)
    return parsed.set(drivername="postgresql").render_as_string(hide_password=False)


@asynccontextmanager
async def open_checkpointer(settings: Settings) -> AsyncIterator[BaseCheckpointSaver]:
    backend = settings.checkpoint_backend
    if backend == "memory":
        yield InMemorySaver()
        return
    if backend == "sqlite":
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        path = settings.checkpoint_url or "var/checkpoints.sqlite"
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        async with AsyncSqliteSaver.from_conn_string(path) as saver:
            await saver.setup()
            yield saver
        return
    if backend == "postgres":
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        dsn = settings.checkpoint_url or _psycopg_dsn(settings.database_url)
        async with AsyncPostgresSaver.from_conn_string(dsn) as saver:
            await saver.setup()
            yield saver
        return
    raise ValueError(f"unsupported checkpoint backend: {backend}")
