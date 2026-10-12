# syntax=docker/dockerfile:1.7
#
# Sandbox image for AGENTFORGE_SANDBOX_BACKEND=docker.
#
# Every gate command (ruff, pytest, the evaluation suite, bandit) runs in a fresh container created
# from this image on a *dedicated* sandbox daemon: no network, all capabilities dropped,
# no-new-privileges, user 65534, memory/CPU/PID limits and optionally gVisor (runsc).
# It contains only the generated agent's hash-locked toolchain.
#
#   docker build -f services/api/sandbox.Dockerfile -t agentforge/sandbox-runtime:1.0.0 services/api

ARG PYTHON_IMAGE=python:3.12-slim-bookworm
FROM ${PYTHON_IMAGE}
LABEL org.opencontainers.image.title="agentforge-sandbox-runtime" \
      org.opencontainers.image.description="Isolated toolchain for verifying AgentForge-generated repositories"
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
COPY app/generator/runtime/requirements-dev.lock /tmp/runtime.lock
RUN python -m venv /opt/agent-runtime \
    && /opt/agent-runtime/bin/pip install --require-hashes --no-deps -r /tmp/runtime.lock \
    && /opt/agent-runtime/bin/python -c "import langgraph, fastapi, pytest, ruff, bandit, yaml" \
    && rm /tmp/runtime.lock \
    && mkdir /workspace \
    && chown 65534:65534 /workspace
ENV PATH="/opt/agent-runtime/bin:$PATH"
WORKDIR /workspace
USER 65534:65534
CMD ["python", "--version"]
