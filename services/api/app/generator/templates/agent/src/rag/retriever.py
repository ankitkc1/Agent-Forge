"""Retriever: approved-source allowlist, relevance threshold, injection quarantine, citations."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from src.agent import blueprint
from src.config import Settings
from src.guardrails.injection import scan
from src.rag.embeddings import Embedder, build_embedder
from src.rag.ingest import ingest
from src.rag.store import InMemoryVectorStore, PgVectorStore, VectorStore


@dataclass(frozen=True)
class Evidence:
    citation: str
    source: str
    document: str
    title: str
    text: str
    score: float
    chunk_id: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RetrievalResult:
    evidence: list[Evidence] = field(default_factory=list)
    quarantined: list[dict[str, Any]] = field(default_factory=list)


class Retriever:
    def __init__(
        self,
        embedder: Embedder,
        store: VectorStore,
        *,
        approved_sources: Sequence[str],
        top_k: int,
        min_score: float,
        scan_content: bool = True,
    ) -> None:
        self.embedder = embedder
        self.store = store
        self.approved_sources = tuple(approved_sources)
        self.top_k = top_k
        self.min_score = min_score
        self.scan_content = scan_content

    def validate_sources(self, sources: Sequence[str] | None) -> tuple[str, ...]:
        if not sources:
            return self.approved_sources
        unapproved = sorted(set(sources) - set(self.approved_sources))
        if unapproved:
            raise PermissionError(f"Unapproved retrieval source(s): {unapproved}")
        return tuple(sources)

    async def search(
        self,
        query: str,
        *,
        sources: Sequence[str] | None = None,
        top_k: int | None = None,
        citation_offset: int = 0,
    ) -> RetrievalResult:
        allowed = self.validate_sources(sources)
        [vector] = await self.embedder.embed([query])
        hits = await self.store.search(vector, top_k=top_k or self.top_k, sources=allowed)
        result = RetrievalResult()
        for hit in hits:
            if hit.score < self.min_score:
                continue
            if self.scan_content:
                verdict = scan(hit.chunk.text, profile="retrieved")
                if verdict.suspicious:
                    result.quarantined.append({"chunk": hit.chunk.id, "rules": list(verdict.rules)})
                    continue
            result.evidence.append(
                Evidence(
                    citation=f"S{citation_offset + len(result.evidence) + 1}",
                    source=hit.chunk.source,
                    document=hit.chunk.document,
                    title=hit.chunk.title,
                    text=hit.chunk.text,
                    score=round(hit.score, 4),
                    chunk_id=hit.chunk.id,
                )
            )
        return result


async def build_retriever(settings: Settings, *, embedder: Embedder | None = None) -> Retriever | None:
    config = blueprint.RETRIEVAL
    if not config["enabled"]:
        return None
    embedder = embedder or build_embedder(settings)
    store: VectorStore
    if settings.vector_store == "pgvector":
        store = PgVectorStore(settings.database_url, dim=embedder.dim)
    else:
        store = InMemoryVectorStore()
        await ingest(
            settings.knowledge_dir,
            list(config["sources"]),
            embedder=embedder,
            store=store,
            chunk_size=config["chunk_size"],
            chunk_overlap=config["chunk_overlap"],
            scan_content=blueprint.GUARDRAILS["scan_retrieved_content"],
        )
    return Retriever(
        embedder,
        store,
        approved_sources=list(config["sources"]),
        top_k=config["top_k"],
        min_score=config["min_score"],
        scan_content=blueprint.GUARDRAILS["scan_retrieved_content"],
    )
