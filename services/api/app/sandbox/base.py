"""Sandbox contracts shared by the process and Docker runners."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

OUTPUT_DIR = ".agentforge-out"
MAX_OUTPUT_BYTES = 256_000

# Environment every sandboxed command receives. Generated code runs hermetically: offline model,
# fixture tools, in-memory checkpoints and no proxy configuration.
SANDBOX_ENV = {
    "ENV": "test",
    "MODEL_PROVIDER": "offline",
    "TOOL_BACKEND": "fixture",
    "CHECKPOINT_BACKEND": "memory",
    "EMBEDDINGS": "hashing",
    "VECTOR_STORE": "memory",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONUNBUFFERED": "1",
    "PYTHONHASHSEED": "0",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "NO_PROXY": "*",
    "no_proxy": "*",
}


class SandboxError(RuntimeError):
    """The sandbox itself failed (not the command it ran)."""


class SandboxUnavailableError(SandboxError):
    pass


class SandboxCancelledError(SandboxError):
    """The build was cancelled while a sandboxed command was running."""


@dataclass(frozen=True)
class SandboxLimits:
    timeout_seconds: int = 300
    memory_mb: int = 2048
    cpu_seconds: int = 300
    max_processes: int = 512
    max_file_mb: int = 256
    cpus: float = 1.5


@dataclass
class CommandResult:
    argv: list[str]
    exit_code: int
    output: str
    duration_seconds: float
    timed_out: bool = False
    truncated: bool = False
    collected: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def tail(self, lines: int = 60) -> str:
        return "\n".join(self.output.splitlines()[-lines:])

    def as_dict(self, *, lines: int = 60) -> dict[str, object]:
        return {
            "command": " ".join(self.argv),
            "exit_code": self.exit_code,
            "duration_seconds": round(self.duration_seconds, 3),
            "timed_out": self.timed_out,
            "output_tail": self.tail(lines),
        }


class SandboxRunner(Protocol):
    name: str

    def check(self) -> tuple[bool, str]:
        """Return (available, detail) without running generated code."""
        ...

    def run(
        self,
        workspace: Path,
        argv: Sequence[str],
        *,
        timeout: int | None = None,
        collect: Sequence[str] = (),
        should_cancel: Callable[[], bool] | None = None,
    ) -> CommandResult:
        """Run ``argv`` (``python ...``) inside the sandbox with ``workspace`` as the cwd.

        Files listed in ``collect`` (relative paths) must exist in the local workspace afterwards.
        """
        ...
