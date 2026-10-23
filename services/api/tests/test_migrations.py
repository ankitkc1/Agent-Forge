from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from alembic import command
from app.core.config import get_settings
from app.models.build import BuildRecord

API_ROOT = Path(__file__).resolve().parents[1]


def _config() -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    return config


def test_scoped_idempotency_migration_round_trip_with_duplicate_keys(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    database = tmp_path / "migration.db"
    url = f"sqlite:///{database.as_posix()}"
    monkeypatch.setenv("AGENTFORGE_DATABASE_URL", url)
    get_settings.cache_clear()
    config = _config()
    command.upgrade(config, "head")

    engine = create_engine(url)
    with Session(engine) as session:
        for owner in ("dana@example.com", "lee@example.com"):
            session.add(
                BuildRecord(
                    agent_name="demo",
                    spec_hash="0" * 64,
                    spec={},
                    status="queued",
                    progress=0,
                    stages=[],
                    requested_by=owner,
                    idempotency_key="shared-key",
                )
            )
        session.commit()
    engine.dispose()

    command.downgrade(config, "20261012_0002")
    engine = create_engine(url)
    with engine.connect() as connection:
        keys = (
            connection.execute(text("SELECT idempotency_key FROM builds ORDER BY created_at, id"))
            .scalars()
            .all()
        )
    engine.dispose()
    assert keys.count("shared-key") == 1
    assert keys.count(None) == 1

    command.upgrade(config, "head")
    get_settings.cache_clear()
