"""Docker sandbox: one throw-away container per command, driven through the Engine HTTP API.

Each command runs in a fresh container created from the sandbox image (the generated agent's
locked toolchain) with:

* no network (``NetworkMode=none``), all Linux capabilities dropped, ``no-new-privileges``;
* an unprivileged user (65534), memory/CPU/PID limits and a size-limited ``/tmp`` tmpfs;
* an optional hardened OCI runtime such as gVisor (``AGENTFORGE_SANDBOX_DOCKER_RUNTIME=runsc``).

Point ``AGENTFORGE_SANDBOX_DOCKER_HOST`` at a *dedicated* sandbox daemon (``tcp://host:2376`` with
TLS client certificates). Never give the worker the host's Docker socket: that is equivalent to
root on the host.
"""

from __future__ import annotations

import io
import tarfile
import time
from collections.abc import Callable, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

import httpx

from app.sandbox.base import (
    MAX_OUTPUT_BYTES,
    OUTPUT_DIR,
    SANDBOX_ENV,
    CommandResult,
    SandboxCancelledError,
    SandboxError,
    SandboxLimits,
    SandboxUnavailableError,
)

API_VERSION = "v1.44"
SANDBOX_UID = 65534
EXCLUDED_PARTS = {".home", ".tmp", "__pycache__", ".pytest_cache", ".ruff_cache"}


def build_workspace_tar(workspace: Path) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for path in sorted(workspace.rglob("*")):
            relative = path.relative_to(workspace)
            if any(part in EXCLUDED_PARTS for part in relative.parts):
                continue
            info = archive.gettarinfo(str(path), arcname=relative.as_posix())
            info.uid = info.gid = SANDBOX_UID
            info.uname = info.gname = "nobody"
            info.mode = 0o755 if path.is_dir() else 0o644
            if path.is_file():
                with path.open("rb") as handle:
                    archive.addfile(info, handle)
            elif path.is_dir():
                archive.addfile(info)
    return buffer.getvalue()


def demux_logs(payload: bytes) -> str:
    """Decode Docker's multiplexed stdout/stderr stream (8-byte frame headers)."""
    chunks: list[bytes] = []
    offset = 0
    while offset + 8 <= len(payload):
        size = int.from_bytes(payload[offset + 4 : offset + 8], "big")
        chunks.append(payload[offset + 8 : offset + 8 + size])
        offset += 8 + size
    if offset == 0 and payload:
        chunks.append(payload)  # TTY or raw stream
    return b"".join(chunks).decode("utf-8", errors="replace")


class DockerSandbox:
    name = "docker"

    def __init__(
        self,
        *,
        host: str,
        image: str,
        limits: SandboxLimits,
        runtime: str | None = None,
        tls_verify: bool = False,
        cert_path: Path | None = None,
        transport: httpx.BaseTransport | None = None,
        poll_seconds: float = 2.0,
    ) -> None:
        self.image = image
        self.limits = limits
        self.runtime = runtime
        self.poll_seconds = poll_seconds
        timeout = httpx.Timeout(30.0, read=limits.timeout_seconds + 30)
        if transport is not None:
            self.client = httpx.Client(transport=transport, base_url="http://docker", timeout=timeout)
        elif host.startswith("unix://"):
            self.client = httpx.Client(
                transport=httpx.HTTPTransport(uds=host.removeprefix("unix://")),
                base_url="http://docker",
                timeout=timeout,
            )
        elif host.startswith("tcp://"):
            address = host.removeprefix("tcp://")
            if tls_verify:
                if cert_path is None:
                    raise SandboxError("AGENTFORGE_SANDBOX_DOCKER_CERT_PATH is required for TLS")
                self.client = httpx.Client(
                    base_url=f"https://{address}",
                    verify=str(cert_path / "ca.pem"),
                    cert=(str(cert_path / "cert.pem"), str(cert_path / "key.pem")),
                    timeout=timeout,
                )
            else:
                self.client = httpx.Client(base_url=f"http://{address}", timeout=timeout)
        else:
            raise SandboxError(f"unsupported Docker host: {host}")

    def _url(self, path: str) -> str:
        return f"/{API_VERSION}{path}"

    def check(self) -> tuple[bool, str]:
        try:
            ping = self.client.get("/_ping")
            image = self.client.get(self._url(f"/images/{self.image}/json"))
        except httpx.HTTPError as exc:
            return False, f"Docker sandbox daemon unreachable: {exc}"
        if ping.status_code != 200:
            return False, f"Docker daemon ping failed: HTTP {ping.status_code}"
        if image.status_code != 200:
            return False, f"sandbox image {self.image} not found on the sandbox daemon"
        return True, f"docker sandbox using {self.image}" + (
            f" (runtime {self.runtime})" if self.runtime else ""
        )

    def _container_spec(self, argv: Sequence[str]) -> dict[str, Any]:
        memory = self.limits.memory_mb * 1024 * 1024
        env = {**SANDBOX_ENV, "HOME": "/tmp", "TMPDIR": "/tmp", "PYTHONPATH": "/workspace"}
        host_config: dict[str, Any] = {
            "NetworkMode": "none",
            "Memory": memory,
            "MemorySwap": memory,
            "NanoCpus": int(self.limits.cpus * 1_000_000_000),
            "PidsLimit": self.limits.max_processes,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges"],
            "Tmpfs": {"/tmp": "rw,nosuid,nodev,size=268435456"},
            "Ulimits": [
                {
                    "Name": "fsize",
                    "Soft": self.limits.max_file_mb * 1048576,
                    "Hard": self.limits.max_file_mb * 1048576,
                },
                {"Name": "nofile", "Soft": 1024, "Hard": 1024},
            ],
        }
        if self.runtime:
            host_config["Runtime"] = self.runtime
        return {
            "Image": self.image,
            "Cmd": list(argv),
            "WorkingDir": "/workspace",
            "User": f"{SANDBOX_UID}:{SANDBOX_UID}",
            "Env": [f"{key}={value}" for key, value in env.items()],
            "NetworkDisabled": True,
            "AttachStdout": False,
            "AttachStderr": False,
            "Tty": False,
            "Labels": {"io.agentforge.sandbox": "true"},
            "HostConfig": host_config,
        }

    def _collect(self, container: str, workspace: Path, relative: str) -> bool:
        target = PurePosixPath(relative)
        if target.is_absolute() or ".." in target.parts:
            raise SandboxError(f"refusing to collect unsafe path {relative}")
        response = self.client.get(
            self._url(f"/containers/{container}/archive"), params={"path": f"/workspace/{relative}"}
        )
        if response.status_code != 200:
            return False
        with tarfile.open(fileobj=io.BytesIO(response.content)) as archive:
            for member in archive.getmembers():
                if not member.isfile() or member.size > 64 * 1024 * 1024:
                    continue
                extracted = archive.extractfile(member)
                if extracted is None:
                    continue
                destination = workspace / target
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(extracted.read())
                return True
        return False

    def run(
        self,
        workspace: Path,
        argv: Sequence[str],
        *,
        timeout: int | None = None,
        collect: Sequence[str] = (),
        should_cancel: Callable[[], bool] | None = None,
    ) -> CommandResult:
        if should_cancel is not None and should_cancel():
            raise SandboxCancelledError("build cancelled before the sandboxed command started")
        available, detail = self.check()
        if not available:
            raise SandboxUnavailableError(detail)
        (workspace / OUTPUT_DIR).mkdir(exist_ok=True)
        created = self.client.post(self._url("/containers/create"), json=self._container_spec(argv))
        if created.status_code >= 300:
            raise SandboxError(f"container create failed: HTTP {created.status_code} {created.text[:200]}")
        container = created.json()["Id"]
        started = time.perf_counter()
        timed_out = False
        exit_code = -1
        try:
            upload = self.client.put(
                self._url(f"/containers/{container}/archive"),
                params={"path": "/workspace"},
                content=build_workspace_tar(workspace),
                headers={"Content-Type": "application/x-tar"},
            )
            if upload.status_code >= 300:
                raise SandboxError(f"workspace upload failed: HTTP {upload.status_code}")
            start = self.client.post(self._url(f"/containers/{container}/start"))
            if start.status_code >= 300:
                raise SandboxError(f"container start failed: HTTP {start.status_code}")
            deadline = float(timeout or self.limits.timeout_seconds)
            while True:
                remaining = deadline - (time.perf_counter() - started)
                if remaining <= 0:
                    timed_out = True
                    self.client.post(self._url(f"/containers/{container}/kill"))
                    break
                if should_cancel is not None and should_cancel():
                    self.client.post(self._url(f"/containers/{container}/kill"))
                    raise SandboxCancelledError("build cancelled while a sandboxed command was running")
                try:
                    # Short waits keep cancellation responsive; the daemon returns as soon as the
                    # container stops, so a finished command costs a single round trip.
                    waited = self.client.post(
                        self._url(f"/containers/{container}/wait"),
                        timeout=httpx.Timeout(30.0, read=min(self.poll_seconds, remaining)),
                    )
                except httpx.ReadTimeout:
                    continue
                exit_code = int(waited.json().get("StatusCode", -1))
                break
            logs = self.client.get(
                self._url(f"/containers/{container}/logs"), params={"stdout": 1, "stderr": 1}
            )
            output = demux_logs(logs.content)
            truncated = len(output) > MAX_OUTPUT_BYTES
            output = output[-MAX_OUTPUT_BYTES:]
            collected = [path for path in collect if self._collect(container, workspace, path)]
        finally:
            self.client.delete(self._url(f"/containers/{container}"), params={"force": 1, "v": 1})
        return CommandResult(
            argv=list(argv),
            exit_code=-9 if timed_out else exit_code,
            output=output,
            duration_seconds=time.perf_counter() - started,
            timed_out=timed_out,
            truncated=truncated,
            collected=collected,
        )
