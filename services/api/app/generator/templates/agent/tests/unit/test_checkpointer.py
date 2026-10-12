"""Checkpoint backends: pending approvals must survive process restarts."""

from __future__ import annotations

from pathlib import Path

import pytest
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.memory import InMemorySaver

from src.config import Settings
from src.memory.checkpointer import _psycopg_dsn, open_checkpointer
from tests.support import run


async def _saver_type(settings: Settings) -> type:
    async with open_checkpointer(settings) as saver:
        return type(saver)


def test_memory_backend(settings: Settings) -> None:
    assert run(_saver_type(settings)) is InMemorySaver


def test_sqlite_checkpoints_survive_reopening(settings: Settings, tmp_path: Path) -> None:
    path = tmp_path / "var" / "checkpoints.sqlite"
    durable = settings.model_copy(update={"checkpoint_backend": "sqlite", "checkpoint_url": str(path)})
    config = {"configurable": {"thread_id": "thread-1", "checkpoint_ns": ""}}

    async def write() -> str:
        async with open_checkpointer(durable) as saver:
            checkpoint = empty_checkpoint()
            stored = await saver.aput(config, checkpoint, {"source": "input", "step": -1}, {})
            return str(stored["configurable"]["checkpoint_id"])

    async def read() -> str | None:
        async with open_checkpointer(durable) as saver:
            restored = await saver.aget_tuple(config)
            return None if restored is None else str(restored.config["configurable"]["checkpoint_id"])

    checkpoint_id = run(write())
    assert path.is_file()
    assert run(read()) == checkpoint_id


def test_unknown_backend_is_rejected(settings: Settings) -> None:
    with pytest.raises(ValueError, match="unsupported checkpoint backend"):
        run(_saver_type(settings.model_copy(update={"checkpoint_backend": "redis"})))


def test_postgres_dsn_drops_the_sqlalchemy_driver() -> None:
    assert _psycopg_dsn("postgresql+psycopg://agent:secret@db:5432/agent") == "postgresql://agent:secret@db:5432/agent"
