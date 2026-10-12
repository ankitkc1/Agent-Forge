from __future__ import annotations

import os
from collections.abc import Generator, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("AGENTFORGE_ENV", "test")

from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_db

RUNTIME_PYTHON = Path(os.environ.get("AGENTFORGE_SANDBOX_PYTHON", "/opt/agent-runtime/bin/python"))


@pytest.fixture
def session_factory() -> Iterator[sessionmaker[Session]]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def settings_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[pytest.MonkeyPatch]:
    """Isolated settings: artifacts under tmp_path, auth disabled unless a test enables it."""
    monkeypatch.setenv("AGENTFORGE_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("AGENTFORGE_AUTH_MODE", "none")
    monkeypatch.delenv("AGENTFORGE_API_KEYS", raising=False)
    monkeypatch.delenv("AGENTFORGE_SIGNING_KEY", raising=False)
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


@pytest.fixture
def client(
    session_factory: sessionmaker[Session], settings_env: pytest.MonkeyPatch
) -> Generator[TestClient, None, None]:
    from app.api.routes import builds
    from app.main import app

    def override_db() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    settings_env.setattr(builds, "SessionLocal", session_factory)
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
