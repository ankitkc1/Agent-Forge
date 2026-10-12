"""Conversation memory: namespaced, retention-bounded and PII-redacted.

Backed by SQLAlchemy Core so the same code serves SQLite (development) and PostgreSQL
(production). Long-term memory stores only what is needed for conversational continuity; every
record carries an ``expires_at`` timestamp and ``purge_expired`` enforces the retention policy.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete,
    select,
)
from sqlalchemy.engine import Engine, make_url

from src.config import Settings
from src.guardrails.pii import redact

metadata = MetaData()
memory_turns = Table(
    "agent_memory_turns",
    metadata,
    Column("id", BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
    Column("namespace", String(64), nullable=False),
    Column("thread_id", String(128), nullable=False),
    Column("role", String(16), nullable=False),
    Column("content", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Index("ix_agent_memory_thread", "namespace", "thread_id", "id"),
    Index("ix_agent_memory_expiry", "expires_at"),
)


class MemoryStore(Protocol):
    async def append(self, thread_id: str, role: str, content: str) -> None: ...

    async def history(self, thread_id: str, limit: int | None = None) -> list[dict[str, str]]: ...

    async def purge_expired(self) -> int: ...

    async def forget(self, thread_id: str) -> int: ...


class NullMemoryStore:
    async def append(self, thread_id: str, role: str, content: str) -> None:
        return None

    async def history(self, thread_id: str, limit: int | None = None) -> list[dict[str, str]]:
        return []

    async def purge_expired(self) -> int:
        return 0

    async def forget(self, thread_id: str) -> int:
        return 0


class SqlMemoryStore:
    def __init__(
        self,
        engine: Engine,
        *,
        namespace: str,
        retention_days: int,
        window: int,
        redact_pii: bool = True,
        max_chars: int = 4000,
    ) -> None:
        self.engine = engine
        self.namespace = namespace
        self.retention = timedelta(days=retention_days)
        self.window = window
        self.redact_pii = redact_pii
        self.max_chars = max_chars
        metadata.create_all(engine)

    @classmethod
    def from_url(cls, url: str, **kwargs: object) -> SqlMemoryStore:
        parsed = make_url(url)
        if parsed.get_backend_name() == "sqlite" and parsed.database not in (None, "", ":memory:"):
            Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url, pool_pre_ping=True)
        return cls(engine, **kwargs)  # type: ignore[arg-type]

    async def append(self, thread_id: str, role: str, content: str) -> None:
        if self.retention <= timedelta(0):
            return
        text = redact(content)[0] if self.redact_pii else content
        now = datetime.now(UTC)

        def _write() -> None:
            with self.engine.begin() as connection:
                connection.execute(
                    memory_turns.insert().values(
                        namespace=self.namespace,
                        thread_id=thread_id,
                        role=role,
                        content=text[: self.max_chars],
                        created_at=now,
                        expires_at=now + self.retention,
                    )
                )

        await asyncio.to_thread(_write)

    async def history(self, thread_id: str, limit: int | None = None) -> list[dict[str, str]]:
        window = self.window if limit is None else limit
        if window <= 0:
            return []
        now = datetime.now(UTC)

        def _read() -> list[dict[str, str]]:
            statement = (
                select(memory_turns.c.role, memory_turns.c.content)
                .where(
                    memory_turns.c.namespace == self.namespace,
                    memory_turns.c.thread_id == thread_id,
                    memory_turns.c.expires_at > now,
                )
                .order_by(memory_turns.c.id.desc())
                .limit(window)
            )
            with self.engine.connect() as connection:
                rows = connection.execute(statement).all()
            return [{"role": row.role, "content": row.content} for row in reversed(rows)]

        return await asyncio.to_thread(_read)

    async def purge_expired(self) -> int:
        now = datetime.now(UTC)

        def _purge() -> int:
            with self.engine.begin() as connection:
                result = connection.execute(delete(memory_turns).where(memory_turns.c.expires_at <= now))
            return int(result.rowcount or 0)

        return await asyncio.to_thread(_purge)

    async def forget(self, thread_id: str) -> int:
        def _forget() -> int:
            with self.engine.begin() as connection:
                result = connection.execute(
                    delete(memory_turns).where(
                        memory_turns.c.namespace == self.namespace,
                        memory_turns.c.thread_id == thread_id,
                    )
                )
            return int(result.rowcount or 0)

        return await asyncio.to_thread(_forget)


def build_memory(settings: Settings) -> MemoryStore:
    from src.agent import blueprint

    config = blueprint.MEMORY
    if not settings.memory_enabled or config["type"] == "none":
        return NullMemoryStore()
    return SqlMemoryStore.from_url(
        settings.database_url,
        namespace=config["namespace"],
        retention_days=config["pii_retention_days"],
        window=config["conversation_window"],
        redact_pii=blueprint.GUARDRAILS["redact_memory"],
    )
