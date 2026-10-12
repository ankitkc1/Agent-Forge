"""Conversation memory: redaction, namespace isolation, retention and erasure."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.memory.store import SqlMemoryStore, memory_turns
from tests.support import run


def make_store(tmp_path: Path, namespace: str = "agent", **kwargs: object) -> SqlMemoryStore:
    options: dict[str, object] = {"retention_days": 30, "window": 10, "redact_pii": True}
    options.update(kwargs)
    return SqlMemoryStore.from_url(f"sqlite:///{tmp_path / 'memory.db'}", namespace=namespace, **options)


def test_history_roundtrip_with_redaction(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    run(store.append("t1", "user", "My email is jo@example.com and the sink leaks."))
    run(store.append("t1", "assistant", "Thanks, we are on it."))
    history = run(store.history("t1"))
    assert [turn["role"] for turn in history] == ["user", "assistant"]
    assert "jo@example.com" not in history[0]["content"]
    assert "[REDACTED_EMAIL]" in history[0]["content"]


def test_namespaces_are_isolated(tmp_path: Path) -> None:
    first, second = make_store(tmp_path, "agent_a"), make_store(tmp_path, "agent_b")
    run(first.append("shared-thread", "user", "hello from a"))
    assert run(second.history("shared-thread")) == []


def test_window_limits_history(tmp_path: Path) -> None:
    store = make_store(tmp_path, window=2)
    for index in range(5):
        run(store.append("t1", "user", f"message {index}"))
    assert [turn["content"] for turn in run(store.history("t1"))] == ["message 3", "message 4"]


def test_expired_records_are_purged(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    past = datetime.now(UTC) - timedelta(days=60)
    with store.engine.begin() as connection:
        connection.execute(
            memory_turns.insert().values(
                namespace="agent", thread_id="old", role="user", content="stale",
                created_at=past, expires_at=past + timedelta(days=30),
            )
        )
    run(store.append("new", "user", "fresh"))
    assert run(store.purge_expired()) == 1
    assert run(store.history("old")) == []
    assert run(store.history("new"))


def test_zero_retention_stores_nothing(tmp_path: Path) -> None:
    store = make_store(tmp_path, retention_days=0)
    run(store.append("t1", "user", "do not keep"))
    assert run(store.history("t1")) == []


def test_forget_erases_a_thread(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    run(store.append("t1", "user", "one"))
    run(store.append("t2", "user", "two"))
    assert run(store.forget("t1")) == 1
    assert run(store.history("t1")) == []
    assert run(store.history("t2"))
