"""Sandboxed execution of generated repositories."""

from __future__ import annotations

from app.core.config import Settings
from app.sandbox.base import (
    OUTPUT_DIR,
    CommandResult,
    SandboxCancelledError,
    SandboxError,
    SandboxLimits,
    SandboxRunner,
    SandboxUnavailableError,
)


def limits_from(settings: Settings) -> SandboxLimits:
    return SandboxLimits(
        timeout_seconds=settings.sandbox_timeout_seconds,
        memory_mb=settings.sandbox_memory_mb,
        cpu_seconds=settings.sandbox_cpu_seconds,
        max_processes=settings.sandbox_max_processes,
    )


def build_sandbox(settings: Settings) -> SandboxRunner:
    if settings.sandbox_backend == "docker":
        from app.sandbox.docker import DockerSandbox

        assert settings.sandbox_docker_host  # enforced by settings validation
        return DockerSandbox(
            host=settings.sandbox_docker_host,
            image=settings.sandbox_image,
            limits=limits_from(settings),
            runtime=settings.sandbox_docker_runtime,
            tls_verify=settings.sandbox_docker_tls_verify,
            cert_path=settings.sandbox_docker_cert_path,
        )
    from app.sandbox.process import ProcessSandbox

    return ProcessSandbox(settings.sandbox_python, limits_from(settings))


__all__ = [
    "OUTPUT_DIR",
    "CommandResult",
    "SandboxCancelledError",
    "SandboxError",
    "SandboxLimits",
    "SandboxRunner",
    "SandboxUnavailableError",
    "build_sandbox",
    "limits_from",
]
