"""Command-line interface.

    python -m src.cli run "The kitchen sink is leaking at P-1001"
    python -m src.cli run "..." --approve --reviewer "Dana"
    python -m src.cli ingest            # (re)index data/knowledge into the configured vector store
    python -m src.cli purge-memory      # enforce the PII retention policy
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from src.agent.contracts import ApprovalDecision
from src.agent.graph import build_graph
from src.agent.runtime import AgentRuntime
from src.agent.service import AgentService
from src.config import get_settings
from src.memory.checkpointer import open_checkpointer
from src.observability import configure_logging


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    async with open_checkpointer(settings) as checkpointer:
        runtime = await AgentRuntime.create(settings)
        service = AgentService(runtime, build_graph(runtime, checkpointer))
        view = await service.start(args.message, thread_id=args.thread)
        if view.status == "awaiting_approval" and (args.approve or args.reject):
            decision = ApprovalDecision(approved=bool(args.approve), reviewer=args.reviewer)
            view = await service.resume(view.run_id, decision)
        print(json.dumps(view.model_dump(mode="json"), indent=2))
    return 0


async def _ingest() -> int:
    from src.agent import blueprint
    from src.rag.embeddings import build_embedder
    from src.rag.ingest import ingest
    from src.rag.store import InMemoryVectorStore, PgVectorStore

    settings = get_settings()
    if not blueprint.RETRIEVAL["enabled"]:
        print("Retrieval is disabled for this agent.")
        return 0
    embedder = build_embedder(settings)
    store = (
        PgVectorStore(settings.database_url, dim=embedder.dim)
        if settings.vector_store == "pgvector"
        else InMemoryVectorStore()
    )
    report = await ingest(
        settings.knowledge_dir,
        list(blueprint.RETRIEVAL["sources"]),
        embedder=embedder,
        store=store,
        chunk_size=blueprint.RETRIEVAL["chunk_size"],
        chunk_overlap=blueprint.RETRIEVAL["chunk_overlap"],
        scan_content=blueprint.GUARDRAILS["scan_retrieved_content"],
    )
    print(json.dumps({"documents": report.documents, "chunks": report.chunks, "quarantined": report.quarantined}, indent=2))
    return 0


async def _purge() -> int:
    from src.memory.store import build_memory

    deleted = await build_memory(get_settings()).purge_expired()
    print(json.dumps({"purged": deleted}))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="process one request")
    run.add_argument("message")
    run.add_argument("--thread", default=None)
    decision = run.add_mutually_exclusive_group()
    decision.add_argument("--approve", action="store_true")
    decision.add_argument("--reject", action="store_true")
    run.add_argument("--reviewer", default="cli-operator")
    commands.add_parser("ingest", help="index data/knowledge into the vector store")
    commands.add_parser("purge-memory", help="delete memory past its retention period")
    args = parser.parse_args(argv)
    configure_logging(get_settings().log_level)
    if args.command == "run":
        return asyncio.run(_run(args))
    if args.command == "ingest":
        return asyncio.run(_ingest())
    return asyncio.run(_purge())


if __name__ == "__main__":
    sys.exit(main())
