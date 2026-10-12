"""Knowledge ingestion: load approved sources, chunk, quarantine injected content, embed, index."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import structlog

from src.guardrails.injection import scan
from src.rag.chunking import Chunk, chunk_document
from src.rag.embeddings import Embedder
from src.rag.store import VectorStore

logger = structlog.get_logger(__name__)
SUPPORTED_SUFFIXES = frozenset({".md", ".markdown", ".txt", ".rst"})
MAX_DOCUMENT_BYTES = 2_000_000


@dataclass
class IngestReport:
    documents: int = 0
    chunks: int = 0
    quarantined: list[dict[str, str]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def load_documents(root: Path, sources: Sequence[str]) -> list[tuple[str, str, str]]:
    """Return (source, relative path, text) for every supported file under ``root/<source>``."""
    documents: list[tuple[str, str, str]] = []
    for source in sources:
        directory = root / source
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            if path.stat().st_size > MAX_DOCUMENT_BYTES:
                logger.warning("knowledge_document_too_large", path=str(path))
                continue
            relative = path.relative_to(root).as_posix()
            documents.append((source, relative, path.read_text(encoding="utf-8", errors="replace")))
    return documents


async def ingest(
    root: Path,
    sources: Sequence[str],
    *,
    embedder: Embedder,
    store: VectorStore,
    chunk_size: int,
    chunk_overlap: int,
    scan_content: bool = True,
) -> IngestReport:
    report = IngestReport()
    accepted: list[Chunk] = []
    for source, relative, text in load_documents(root, sources):
        report.documents += 1
        for chunk in chunk_document(source, relative, text, size=chunk_size, overlap=chunk_overlap):
            verdict = scan(chunk.text, profile="retrieved") if scan_content else None
            if verdict is not None and verdict.suspicious:
                report.quarantined.append({"chunk": chunk.id, "rules": ",".join(verdict.rules)})
                logger.warning("knowledge_chunk_quarantined", chunk=chunk.id, rules=verdict.rules)
                continue
            accepted.append(chunk)
    if accepted:
        vectors = await embedder.embed([chunk.text for chunk in accepted])
        await store.upsert(accepted, vectors)
    report.chunks = len(accepted)
    logger.info(
        "knowledge_ingested",
        documents=report.documents,
        chunks=report.chunks,
        quarantined=len(report.quarantined),
    )
    return report
