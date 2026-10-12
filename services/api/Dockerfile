# syntax=docker/dockerfile:1.7
#
# AgentForge control plane: one image for the API, the Celery build worker and Celery beat.
#
# Two virtual environments, deliberately separate:
#   /opt/venv           control plane (FastAPI, Celery, SQLAlchemy, signing keys at runtime)
#   /opt/agent-runtime  the toolchain generated repositories run with in the process sandbox
#                       (LangGraph, pytest, ruff, bandit) — it never sees control-plane packages.
# Both are installed from hash-locked requirement files.

ARG PYTHON_IMAGE=python:3.12-slim-bookworm

FROM ${PYTHON_IMAGE} AS base
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

FROM base AS control-plane
COPY requirements.lock /tmp/requirements.lock
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --require-hashes --no-deps -r /tmp/requirements.lock

FROM base AS agent-runtime
COPY app/generator/runtime/requirements-dev.lock /tmp/runtime.lock
RUN python -m venv /opt/agent-runtime \
    && /opt/agent-runtime/bin/pip install --require-hashes --no-deps -r /tmp/runtime.lock \
    && /opt/agent-runtime/bin/python -c "import langgraph, fastapi, pytest, ruff, bandit, yaml"

FROM base AS runtime
LABEL org.opencontainers.image.title="agentforge-api" \
      org.opencontainers.image.description="AgentForge control plane: requirement compiler, planner, generator and verified build pipeline" \
      org.opencontainers.image.licenses="Proprietary"
ENV PATH="/opt/venv/bin:$PATH" \
    AGENTFORGE_SANDBOX_PYTHON=/opt/agent-runtime/bin/python \
    AGENTFORGE_ARTIFACT_ROOT=/var/lib/agentforge/artifacts
RUN groupadd --system --gid 10001 agentforge \
    && useradd --system --uid 10001 --gid agentforge --home-dir /app --shell /usr/sbin/nologin agentforge \
    && mkdir -p /var/lib/agentforge/artifacts \
    && chown -R agentforge:agentforge /var/lib/agentforge
COPY --from=control-plane /opt/venv /opt/venv
COPY --from=agent-runtime /opt/agent-runtime /opt/agent-runtime
WORKDIR /app
COPY --chown=root:root alembic.ini pyproject.toml README.md ./
COPY --chown=root:root alembic ./alembic
COPY --chown=root:root app ./app
USER agentforge
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2)"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
