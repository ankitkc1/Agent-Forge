"""In-process build execution for single-process development (``AGENTFORGE_BUILD_DISPATCH=inline``).

Deployments use Celery workers: queued builds survive API restarts, workers scale horizontally and
sandboxed execution stays off the API hosts. Inline dispatch exists so the complete workbench runs
with one command and no Redis; settings validation refuses it in production.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import structlog

logger = structlog.get_logger(__name__)
_lock = threading.Lock()
_executor: ThreadPoolExecutor | None = None


def _pool() -> ThreadPoolExecutor:
    global _executor
    with _lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="agentforge-build")
        return _executor


def _run(build_id: str) -> None:
    from app.services.pipeline import execute_build

    try:
        execute_build(build_id)
    except Exception:  # the pipeline records failures itself; this guards the worker thread
        logger.exception("inline_build_crashed", build_id=build_id)


def submit_inline(build_id: str) -> None:
    _pool().submit(_run, build_id)
