# syntax=docker/dockerfile:1.7
# Multi-stage build: dependencies are installed from requirements.lock — the exact versions
# AgentForge tested this repository with — into an isolated virtualenv.
FROM python:3.12-slim AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.lock ./
RUN pip install --require-virtualenv --require-hashes -r requirements.lock

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH="/opt/venv/bin:$PATH"
WORKDIR /app
RUN groupadd --system --gid 10001 agent \
    && useradd --system --uid 10001 --gid agent --home-dir /app --shell /usr/sbin/nologin agent \
    && mkdir -p /app/var \
    && chown agent:agent /app/var
COPY --from=builder /opt/venv /opt/venv
COPY --chown=agent:agent src ./src
COPY --chown=agent:agent mcp ./mcp
COPY --chown=agent:agent evals ./evals
COPY --chown=agent:agent data ./data
COPY --chown=agent:agent agent-spec.yaml ./
USER agent
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"]
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-server-header"]
