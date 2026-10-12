"""Shared fixtures: a hermetic runtime (offline model, fixture tools, in-memory checkpoints)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.agent.graph import build_graph
from src.agent.runtime import AgentRuntime
from src.agent.service import AgentService
from src.config import Settings
from src.tools.backends import FixtureBackend
from tests.support import ROOT, load_dataset, run


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        env="test",
        model_provider="offline",
        tool_backend="fixture",
        checkpoint_backend="memory",
        database_url=f"sqlite:///{tmp_path / 'agent.db'}",
        api_keys="test-caller-key",
        approver_api_keys="test-approver-key",
        embeddings="hashing",
        vector_store="memory",
        knowledge_dir=ROOT / "data" / "knowledge",
        fixtures_path=ROOT / "data" / "fixtures" / "tools.json",
    )


@pytest.fixture
def backend(settings: Settings) -> FixtureBackend:
    return FixtureBackend(settings.fixtures_path)


@pytest.fixture
def runtime(settings: Settings, backend: FixtureBackend) -> AgentRuntime:
    return run(AgentRuntime.create(settings, backend=backend))


@pytest.fixture
def service(runtime: AgentRuntime) -> AgentService:
    return AgentService(runtime, build_graph(runtime))


@pytest.fixture(scope="session")
def dataset() -> dict[str, Any]:
    return load_dataset()
