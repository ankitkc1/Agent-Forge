"""Vector stores: in-process (default) and PostgreSQL + pgvector."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import create_engine, text

from src.rag.chunking import Chunk


@dataclass(frozen=True)
class ScoredChunk:
    chunk: Chunk
    score: float


class VectorStore(Protocol):
    async def upsert(self, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]) -> None: ...

    async def search(
        self, vector: Sequence[float], *, top_k: int, sources: Sequence[str]
    ) -> list[ScoredChunk]: ...

    async def count(self) -> int: ...


class InMemoryVectorStore:
    """Exact cosine search over normalised vectors; fine for tens of thousands of chunks."""

    def __init__(self) -> None:
        self._rows: dict[str, tuple[Chunk, tuple[float, ...]]] = {}

    async def upsert(self, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]) -> None:
        for chunk, vector in zip(chunks, vectors, strict=True):
            self._rows[chunk.id] = (chunk, tuple(vector))

    async def search(
        self, vector: Sequence[float], *, top_k: int, sources: Sequence[str]
    ) -> list[ScoredChunk]:
        allowed = set(sources)
        scored = [
            ScoredChunk(chunk, sum(a * b for a, b in zip(vector, stored, strict=False)))
            for chunk, stored in self._rows.values()
            if chunk.source in allowed
        ]
        scored.sort(key=lambda item: (-item.score, item.chunk.id))
        return scored[:top_k]

    async def count(self) -> int:
        return len(self._rows)


class PgVectorStore:
    """pgvector-backed store. Requires the ``vector`` extension (pgvector/pgvector image)."""

    def __init__(self, database_url: str, *, dim: int, table: str = "rag_chunks") -> None:
        if not table.isidentifier():
            raise ValueError("table name must be an identifier")
        self.engine = create_engine(database_url, pool_pre_ping=True)
        self.dim = dim
        self.table = table
        self._ready = False

    def _ensure_schema(self) -> None:
        if self._ready:
            return
        with self.engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            connection.execute(
                text(
                    f"CREATE TABLE IF NOT EXISTS {self.table} ("
                    "id TEXT PRIMARY KEY, source TEXT NOT NULL, document TEXT NOT NULL, "
                    "title TEXT NOT NULL, chunk_index INTEGER NOT NULL, body TEXT NOT NULL, "
                    f"embedding vector({self.dim}) NOT NULL)"
                )
            )
            connection.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS {self.table}_embedding_idx ON {self.table} "
                    "USING hnsw (embedding vector_cosine_ops)"
                )
            )
        self._ready = True

    @staticmethod
    def _literal(vector: Sequence[float]) -> str:
        return "[" + ",".join(f"{value:.7f}" for value in vector) + "]"

    async def upsert(self, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]) -> None:
        def _write() -> None:
            self._ensure_schema()
            # The table name is validated as an identifier in __init__; values are bound parameters.
            statement = text(
                f"INSERT INTO {self.table} (id, source, document, title, chunk_index, body, embedding) "  # nosec B608
                "VALUES (:id, :source, :document, :title, :chunk_index, :body, CAST(:embedding AS vector)) "
                "ON CONFLICT (id) DO UPDATE SET body = EXCLUDED.body, embedding = EXCLUDED.embedding, "
                "title = EXCLUDED.title"
            )
            with self.engine.begin() as connection:
                connection.execute(
                    statement,
                    [
                        {
                            "id": chunk.id,
                            "source": chunk.source,
                            "document": chunk.document,
                            "title": chunk.title,
                            "chunk_index": chunk.index,
                            "body": chunk.text,
                            "embedding": self._literal(vector),
                        }
                        for chunk, vector in zip(chunks, vectors, strict=True)
                    ],
                )

        await asyncio.to_thread(_write)

    async def search(
        self, vector: Sequence[float], *, top_k: int, sources: Sequence[str]
    ) -> list[ScoredChunk]:
        def _query() -> list[ScoredChunk]:
            self._ensure_schema()
            # The table name is validated as an identifier in __init__; values are bound parameters.
            statement = text(
                f"SELECT id, source, document, title, chunk_index, body, "  # nosec B608
                f"1 - (embedding <=> CAST(:q AS vector)) AS score FROM {self.table} "
                "WHERE source = ANY(:sources) ORDER BY embedding <=> CAST(:q AS vector) LIMIT :k"
            )
            with self.engine.connect() as connection:
                rows = connection.execute(
                    statement, {"q": self._literal(vector), "sources": list(sources), "k": top_k}
                ).all()
            return [
                ScoredChunk(Chunk(row.id, row.source, row.document, row.title, row.body, row.chunk_index), float(row.score))
                for row in rows
            ]

        return await asyncio.to_thread(_query)

    async def count(self) -> int:
        def _count() -> int:
            self._ensure_schema()
            with self.engine.connect() as connection:
                query = text(f"SELECT count(*) FROM {self.table}")  # nosec B608
                return int(connection.execute(query).scalar_one())

        return await asyncio.to_thread(_count)
