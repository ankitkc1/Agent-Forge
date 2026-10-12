from __future__ import annotations

import contextlib
import time
import uuid
from collections.abc import Iterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, Counter, Histogram, generate_latest
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector
from sqlalchemy import func, select
from structlog.contextvars import bind_contextvars, clear_contextvars

from app import __version__
from app.api.routes import builds, health, specs, system
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.models.build import BuildRecord

settings = get_settings()
configure_logging(settings.log_level)
logger = structlog.get_logger(__name__)

REQUESTS = Counter("agentforge_http_requests_total", "HTTP requests", ["method", "path", "status"])
LATENCY = Histogram("agentforge_http_request_duration_seconds", "HTTP request latency", ["method", "path"])


class BuildStatusCollector(Collector):
    """Exports build counts by status at scrape time (cheap aggregate query)."""

    def collect(self) -> Iterator[GaugeMetricFamily]:
        gauge = GaugeMetricFamily("agentforge_builds", "Builds by status", labels=["status"])
        try:
            with SessionLocal() as session:
                rows = session.execute(
                    select(BuildRecord.status, func.count()).group_by(BuildRecord.status)
                ).all()
        except Exception:
            rows = []
        for status_name, count in rows:
            gauge.add_metric([status_name], count)
        yield gauge


with contextlib.suppress(ValueError):  # already registered (module reloaded in tests)
    REGISTRY.register(BuildStatusCollector())


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.artifact_root.mkdir(parents=True, exist_ok=True)
    logger.info("api_started", environment=settings.env, version=__version__, auth_mode=settings.auth_mode)
    yield
    logger.info("api_stopped")


app = FastAPI(
    title="AgentForge API",
    version=__version__,
    description=(
        "Compiles business requirements into validated AgentSpecs and builds tested, "
        "security-checked, signed agent repositories."
    ),
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Request-ID", "X-API-Key", "Authorization", "Idempotency-Key"],
    expose_headers=["X-Request-ID", "X-Artifact-SHA256", "Content-Disposition"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request_id = request_id[:128]
    clear_contextvars()
    bind_contextvars(request_id=request_id, method=request.method, path=request.url.path)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("unhandled_request_error")
        response = JSONResponse(
            status_code=500, content={"detail": "internal server error", "request_id": request_id}
        )
    elapsed = time.perf_counter() - started
    route = request.scope.get("route")
    route_path = getattr(route, "path", "unmatched")
    REQUESTS.labels(request.method, route_path, response.status_code).inc()
    LATENCY.labels(request.method, route_path).observe(elapsed)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    if not request.url.path.endswith("/stream"):
        logger.info("request_complete", status=response.status_code, duration_ms=round(elapsed * 1000, 2))
    clear_contextvars()
    return response


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


app.include_router(health.router)
app.include_router(system.router, prefix="/api/v1")
app.include_router(specs.router, prefix="/api/v1")
app.include_router(builds.router, prefix="/api/v1")
