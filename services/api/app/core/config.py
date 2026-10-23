from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENTFORGE_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- runtime -----------------------------------------------------------------------------
    env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    database_url: str = "sqlite:///./agentforge.db"
    redis_url: str = "redis://localhost:6379/0"
    artifact_root: Path = Path("./artifacts")
    workspace_root: Path | None = None
    allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://localhost:8080"]
    )
    build_retention_days: int = Field(default=30, ge=1, le=365)
    max_requirement_chars: int = Field(default=12_000, ge=500, le=100_000)
    max_active_builds: int = Field(default=20, ge=1, le=1000)
    # "celery" queues builds for workers; "inline" runs them in the API process (development only).
    build_dispatch: Literal["celery", "inline"] = "celery"

    # --- authentication ------------------------------------------------------------------------
    auth_mode: Literal["none", "api_key", "trusted_header"] = "none"
    api_keys: SecretStr = SecretStr("")
    trusted_user_header: str = "X-Forwarded-Email"

    # --- optional LLM features -----------------------------------------------------------------
    llm_provider: Literal["none", "openai", "anthropic", "ollama"] = "none"
    llm_model: str | None = None
    llm_api_key: SecretStr | None = None
    llm_base_url: str | None = None
    llm_timeout_seconds: int = Field(default=60, ge=5, le=600)

    # --- sandbox -------------------------------------------------------------------------------
    sandbox_backend: Literal["process", "docker"] = "process"
    sandbox_python: Path = Path("/opt/agent-runtime/bin/python")
    sandbox_timeout_seconds: int = Field(default=300, ge=10, le=3600)
    sandbox_memory_mb: int = Field(default=2048, ge=256, le=65_536)
    sandbox_cpu_seconds: int = Field(default=300, ge=10, le=7200)
    sandbox_max_processes: int = Field(default=512, ge=16, le=8192)
    # A *dedicated* sandbox daemon (tcp://host:2376 with TLS, or a rootless socket). Never the host socket.
    sandbox_docker_host: str | None = None
    sandbox_docker_tls_verify: bool = False
    sandbox_docker_cert_path: Path | None = None
    sandbox_image: str = "agentforge/sandbox-runtime:1.0.0"
    sandbox_docker_runtime: str | None = None

    # --- pipeline ------------------------------------------------------------------------------
    repair_max_attempts: int = Field(default=2, ge=0, le=5)
    repair_use_llm: bool = False
    enforce_eval_targets: bool = True
    run_bandit: bool = True

    # --- signing -------------------------------------------------------------------------------
    signing_key: SecretStr | None = None
    signing_key_id: str | None = None

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        return value.upper()

    @model_validator(mode="after")
    def production_guards(self) -> Settings:
        if self.sandbox_backend == "docker" and not self.sandbox_docker_host:
            raise ValueError(
                "AGENTFORGE_SANDBOX_DOCKER_HOST is required for the docker sandbox backend; "
                "point it at a dedicated sandbox daemon"
            )
        if self.env == "production":
            if self.auth_mode == "none":
                raise ValueError("AGENTFORGE_AUTH_MODE must not be 'none' in production")
            if self.auth_mode == "api_key" and not self.api_key_digests:
                raise ValueError("AGENTFORGE_API_KEYS must be set when auth_mode is api_key")
            if "agentforge:agentforge@" in self.database_url:
                raise ValueError("replace the development database credentials in production")
            if self.build_dispatch == "inline":
                raise ValueError(
                    "AGENTFORGE_BUILD_DISPATCH=inline is for development; run Celery workers in production"
                )
            signing_secret = self.signing_key.get_secret_value().strip() if self.signing_key else ""
            if not signing_secret:
                raise ValueError("AGENTFORGE_SIGNING_KEY is required in production")
            from app.packaging.signing import SigningKeyError, load_signer

            try:
                load_signer(signing_secret, self.signing_key_id)
            except SigningKeyError as exc:
                raise ValueError("AGENTFORGE_SIGNING_KEY is invalid") from exc
        return self

    @property
    def api_key_digests(self) -> frozenset[str]:
        """API keys are compared by SHA-256 digest; entries may be raw keys or 'sha256:<hex>'."""
        digests: set[str] = set()
        for raw in self.api_keys.get_secret_value().split(","):
            item = raw.strip()
            if not item:
                continue
            if item.startswith("sha256:"):
                digests.add(item.removeprefix("sha256:").lower())
            else:
                digests.add(hashlib.sha256(item.encode()).hexdigest())
        return frozenset(digests)

    @property
    def workspace_dir(self) -> Path:
        return self.workspace_root or (self.artifact_root / ".workspaces")


@lru_cache
def get_settings() -> Settings:
    return Settings()
