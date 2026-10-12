FROM python:3.12-slim AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --upgrade pip && pip install ".[dev]"

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"
WORKDIR /app
RUN groupadd --system --gid 10001 agentforge \
    && useradd --system --uid 10001 --gid agentforge --home-dir /app agentforge \
    && mkdir -p /var/lib/agentforge/artifacts \
    && chown -R agentforge:agentforge /app /var/lib/agentforge
COPY --from=builder /opt/venv /opt/venv
COPY --chown=agentforge:agentforge app ./app
COPY --chown=agentforge:agentforge alembic ./alembic
COPY --chown=agentforge:agentforge alembic.ini pyproject.toml ./
USER agentforge
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

