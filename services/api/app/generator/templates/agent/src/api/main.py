"""FastAPI application factory."""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from structlog.contextvars import bind_contextvars, clear_contextvars

from src.agent import blueprint
from src.agent.graph import build_graph
from src.agent.runtime import AgentRuntime
from src.agent.service import AgentService
from src.api.routes import router
from src.config import Settings, get_settings
from src.memory.checkpointer import open_checkpointer
from src.observability import HTTP_LATENCY, HTTP_REQUESTS, configure_logging

logger = structlog.get_logger(__name__)


def create_app(settings: Settings | None = None, *, runtime: AgentRuntime | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.validate_for_production()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with open_checkpointer(settings) as checkpointer:
            agent_runtime = runtime or await AgentRuntime.create(settings)
            app.state.service = AgentService(agent_runtime, build_graph(agent_runtime, checkpointer))
            purged = await agent_runtime.memory.purge_expired()
            logger.info(
                "agent_started",
                agent=blueprint.AGENT_NAME,
                model=agent_runtime.model.name,
                checkpoint_backend=settings.checkpoint_backend,
                purged_memory=purged,
            )
            yield
        logger.info("agent_stopped")

    app = FastAPI(
        title=blueprint.DISPLAY_NAME,
        description=blueprint.OBJECTIVE,
        version=blueprint.AGENTFORGE_VERSION,
        lifespan=lifespan,
    )
    app.state.settings = settings

    @app.middleware("http")
    async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.state.request_id = request_id[:128]
        clear_contextvars()
        bind_contextvars(request_id=request.state.request_id, path=request.url.path)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("unhandled_error")
            response = JSONResponse(
                {"detail": "internal error", "request_id": request.state.request_id}, status_code=500
            )
        route = request.scope.get("route")
        path = getattr(route, "path", "unmatched")
        elapsed = time.perf_counter() - started
        HTTP_REQUESTS.labels(request.method, path, response.status_code).inc()
        HTTP_LATENCY.labels(request.method, path).observe(elapsed)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        logger.info("request", status=response.status_code, duration_ms=round(elapsed * 1000, 1))
        return response

    app.include_router(router)
    return app


def __getattr__(name: str) -> FastAPI:
    """Lazily build the ASGI app so importing this module has no side effects."""
    if name == "app":
        application = create_app()
        globals()["app"] = application
        return application
    raise AttributeError(name)
