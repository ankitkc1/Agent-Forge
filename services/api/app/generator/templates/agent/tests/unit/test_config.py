"""Configuration: production refuses to start with development defaults."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from src.config import Settings


def test_production_rejects_development_defaults(settings: Settings) -> None:
    unsafe = settings.model_copy(
        update={
            "env": "production",
            "api_keys": SecretStr("change-me-dev-key"),
            "approver_api_keys": SecretStr(""),
            "model_provider": "offline",
            "tool_backend": "fixture",
            "checkpoint_backend": "memory",
            "database_url": "postgresql+psycopg://agent:change-me@db/agent",
        }
    )
    with pytest.raises(RuntimeError) as excinfo:
        unsafe.validate_for_production()
    message = str(excinfo.value)
    for problem in ("API_KEYS", "APPROVER_API_KEYS", "MODEL_PROVIDER=offline", "TOOL_BACKEND=fixture", "CHECKPOINT_BACKEND=memory", "DATABASE_URL"):
        assert problem in message


def test_hardened_production_configuration_starts(settings: Settings) -> None:
    hardened = settings.model_copy(
        update={
            "env": "production",
            "api_keys": SecretStr("caller-" + "k" * 24),
            "approver_api_keys": SecretStr("approver-" + "k" * 24),
            "model_provider": "openai",
            "tool_backend": "http",
            "tool_backend_url": "https://tools.internal",
            "checkpoint_backend": "postgres",
            "database_url": "postgresql+psycopg://agent:strong-password@db/agent",
        }
    )
    hardened.validate_for_production()


def test_guard_only_applies_to_production(settings: Settings) -> None:
    settings.validate_for_production()


def test_key_lists_are_split_and_trimmed(settings: Settings) -> None:
    configured = settings.model_copy(update={"api_keys": SecretStr(" alpha , beta ,, "), "approver_api_keys": SecretStr("gamma")})
    assert configured.api_key_set() == {"alpha", "beta"}
    assert configured.approver_key_set() == {"gamma"}
