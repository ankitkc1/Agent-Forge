"""Process sandbox: a dedicated interpreter, a scrubbed environment and kernel resource limits.

Used for development and single-host deployments. Isolation layers:

* a separate virtualenv (``AGENTFORGE_SANDBOX_PYTHON``) containing only the generated agent's
  locked dependencies — never the control plane's packages or credentials;
* an environment built from scratch (no inherited secrets, no proxy variables);
* ``setrlimit`` caps on address space, CPU time, file size, open files and processes;
* a new session/process group that is killed as a whole on timeout;
* output written to a size-capped file instead of worker memory.

Network isolation comes from deployment: in the bundled Compose stack the worker only joins the
internal network, which has no route to the internet. For untrusted multi-tenant use, prefer the
Docker backend with gVisor.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from app.sandbox.base import (
    MAX_OUTPUT_BYTES,
    SANDBOX_ENV,
    CommandResult,
    SandboxCancelledError,
    SandboxLimits,
    SandboxUnavailableError,
)

_REQUIRED_MODULES = "import langgraph, fastapi, pydantic, pytest, ruff, yaml"


class ProcessSandbox:
    name = "process"

    def __init__(self, python: Path, limits: SandboxLimits) -> None:
        self.python = python
        self.limits = limits
        self._checked: tuple[bool, str] | None = None

    def check(self) -> tuple[bool, str]:
        if self._checked is not None:
            return self._checked
        if not self.python.exists():
            self._checked = (False, f"sandbox interpreter not found at {self.python}")
            return self._checked
        try:
            probe = subprocess.run(
                [str(self.python), "-c", _REQUIRED_MODULES],
                capture_output=True,
                text=True,
                timeout=60,
                env={"PATH": os.environ.get("PATH", ""), **SANDBOX_ENV},
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            self._checked = (False, f"sandbox interpreter failed to start: {exc}")
            return self._checked
        if probe.returncode != 0:
            self._checked = (False, f"sandbox runtime incomplete: {probe.stderr.strip()[-300:]}")
        else:
            self._checked = (True, f"process sandbox using {self.python}")
        return self._checked

    def _environment(self, workspace: Path) -> dict[str, str]:
        home = workspace / ".home"
        tmp = workspace / ".tmp"
        home.mkdir(exist_ok=True)
        tmp.mkdir(exist_ok=True)
        bin_dir = str(self.python.parent)
        env = {
            **SANDBOX_ENV,
            "PATH": os.pathsep.join([bin_dir, "/usr/local/bin", "/usr/bin", "/bin"]),
            "HOME": str(home),
            "TMPDIR": str(tmp),
            "TEMP": str(tmp),
            "TMP": str(tmp),
            "PYTHONPATH": str(workspace),
        }
        if os.name == "nt":  # pragma: no cover - Windows development only
            env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", r"C:\Windows")
        return env

    def _preexec(self) -> None:  # pragma: no cover - runs in the child process
        import resource

        memory = self.limits.memory_mb * 1024 * 1024
        file_size = self.limits.max_file_mb * 1024 * 1024
        for limit, value in (
            (resource.RLIMIT_AS, memory),
            (resource.RLIMIT_CPU, self.limits.cpu_seconds),
            (resource.RLIMIT_FSIZE, file_size),
            (resource.RLIMIT_NOFILE, 1024),
            (resource.RLIMIT_CORE, 0),
        ):
            # A limit the platform does not support must not prevent the others from applying.
            with contextlib.suppress(ValueError, OSError):
                resource.setrlimit(limit, (value, value))
        if os.geteuid() != 0:
            # RLIMIT_NPROC counts every process of the user; root ignores it.
            with contextlib.suppress(ValueError, OSError):
                resource.setrlimit(
                    resource.RLIMIT_NPROC, (self.limits.max_processes, self.limits.max_processes)
                )

    def run(
        self,
        workspace: Path,
        argv: Sequence[str],
        *,
        timeout: int | None = None,
        collect: Sequence[str] = (),
        should_cancel: Callable[[], bool] | None = None,
    ) -> CommandResult:
        available, detail = self.check()
        if not available:
            raise SandboxUnavailableError(detail)
        command = [str(self.python) if part == "python" else part for part in argv]
        log_path = workspace / ".tmp" / f"command-{time.monotonic_ns()}.log"
        env = self._environment(workspace)
        deadline = timeout or self.limits.timeout_seconds
        started = time.perf_counter()
        timed_out = False
        posix = os.name == "posix"
        with log_path.open("wb") as log:
            process = subprocess.Popen(
                command,
                cwd=workspace,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=posix,
                preexec_fn=self._preexec if posix else None,
            )
            cancelled = False
            exit_code: int | None = None
            while exit_code is None:
                remaining = deadline - (time.perf_counter() - started)
                if remaining <= 0:
                    timed_out = True
                    self._kill(process, posix)
                    exit_code = process.wait(timeout=30)
                    break
                try:
                    exit_code = process.wait(timeout=min(1.0, remaining))
                except subprocess.TimeoutExpired:
                    if should_cancel is not None and should_cancel():
                        cancelled = True
                        self._kill(process, posix)
                        exit_code = process.wait(timeout=30)
        duration = time.perf_counter() - started
        size = log_path.stat().st_size
        with log_path.open("rb") as log:
            if size > MAX_OUTPUT_BYTES:
                log.seek(size - MAX_OUTPUT_BYTES)
            output = log.read().decode("utf-8", errors="replace")
        log_path.unlink(missing_ok=True)
        if cancelled:
            raise SandboxCancelledError("build cancelled while a sandboxed command was running")
        return CommandResult(
            argv=list(argv),
            exit_code=exit_code if not timed_out else -9,
            output=output,
            duration_seconds=duration,
            timed_out=timed_out,
            truncated=size > MAX_OUTPUT_BYTES,
            collected=[path for path in collect if (workspace / path).exists()],
        )

    @staticmethod
    def _kill(process: subprocess.Popen[bytes], posix: bool) -> None:
        try:
            if posix:
                os.killpg(process.pid, signal.SIGKILL)
            else:  # pragma: no cover
                process.kill()
        except ProcessLookupError:
            pass
