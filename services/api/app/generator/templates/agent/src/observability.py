"""Structured logging and Prometheus metrics."""

from __future__ import annotations

import logging
import sys

import structlog
from prometheus_client import Counter, Histogram

RUNS = Counter("agent_runs_total", "Agent runs by terminal status", ["status"])
NODE_LATENCY = Histogram(
    "agent_node_duration_seconds",
    "Graph node latency",
    ["node"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
)
TOOL_CALLS = Counter("agent_tool_calls_total", "Tool invocations", ["tool", "phase", "outcome"])
TOOL_LATENCY = Histogram("agent_tool_duration_seconds", "Tool latency", ["phase"])
APPROVALS = Counter("agent_approval_decisions_total", "Human approval decisions", ["decision"])
GUARDRAIL_EVENTS = Counter("agent_guardrail_events_total", "Guardrail interventions", ["kind"])
HTTP_REQUESTS = Counter("agent_http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_LATENCY = Histogram("agent_http_request_duration_seconds", "HTTP latency", ["method", "route"])


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper(), force=True)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        cache_logger_on_first_use=True,
    )
