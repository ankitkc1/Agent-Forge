from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from structlog.contextvars import bind_contextvars, clear_contextvars

from app.api.routes import builds, health, specs
from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level)
logger = structlog.get_logger(__name__)

REQUESTS = Counter("agentforge_http_requests_total", "HTTP requests", ["method", "path", "status"])
LATENCY = Histogram(
    "agentforge_http_request_duration_seconds", "HTTP request latency", ["method", "path"]
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    Path(settings.artifact_root).mkdir(parents=True, exist_ok=True)
    logger.info("api_started", environment=settings.env)
    yield
    logger.info("api_stopped")


app = FastAPI(
    title="AgentForge API",
    version="0.2.0",
    description="Deterministic AgentSpec compiler and durable agent build control plane.",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Request-ID"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))[:128]
    clear_contextvars()
    bind_contextvars(request_id=request_id, method=request.method, path=request.url.path)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("unhandled_request_error")
        response = JSONResponse(
            status_code=500,
            content={"detail": "internal server error", "request_id": request_id},
        )
    elapsed = time.perf_counter() - started
    route_path = request.scope.get("route").path if request.scope.get("route") else request.url.path
    REQUESTS.labels(request.method, route_path, response.status_code).inc()
    LATENCY.labels(request.method, route_path).observe(elapsed)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = (
        "no-store" if request.url.path.startswith("/api/") else "no-cache"
    )
    logger.info(
        "request_complete", status=response.status_code, duration_ms=round(elapsed * 1000, 2)
    )
    clear_contextvars()
    return response


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


app.include_router(health.router)
app.include_router(specs.router, prefix="/api/v1")
app.include_router(builds.router, prefix="/api/v1")
