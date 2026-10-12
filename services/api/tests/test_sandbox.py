"""Sandbox runners: process isolation (real subprocesses) and the Docker Engine API contract."""

from __future__ import annotations

import io
import json
import os
import sys
import tarfile
import time
from pathlib import Path

import httpx
import pytest

from app.sandbox import process as process_module
from app.sandbox.base import MAX_OUTPUT_BYTES, SandboxCancelledError, SandboxLimits, SandboxUnavailableError
from app.sandbox.docker import SANDBOX_UID, DockerSandbox, build_workspace_tar, demux_logs
from app.sandbox.process import ProcessSandbox

pytestmark = pytest.mark.skipif(os.name != "posix", reason="sandbox isolation relies on POSIX process groups")


@pytest.fixture
def sandbox(monkeypatch: pytest.MonkeyPatch) -> ProcessSandbox:
    # The control-plane interpreter lacks the agent runtime; probe only for the standard library.
    monkeypatch.setattr(process_module, "_REQUIRED_MODULES", "import json")
    return ProcessSandbox(
        Path(sys.executable), SandboxLimits(timeout_seconds=30, memory_mb=1024, cpu_seconds=30)
    )


def _script(workspace: Path, name: str, body: str) -> str:
    (workspace / name).write_text(body, encoding="utf-8")
    return name


def test_environment_is_scrubbed(
    sandbox: ProcessSandbox, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENTFORGE_SIGNING_KEY", "control-plane-secret")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.internal:3128")
    monkeypatch.setenv("DATABASE_URL", "postgresql://agentforge:secret@db/agentforge")
    script = _script(tmp_path, "env_probe.py", "import json, os\nprint(json.dumps(dict(os.environ)))\n")
    result = sandbox.run(tmp_path, ["python", script])
    assert result.ok, result.output
    env = json.loads(result.output.strip().splitlines()[-1])
    for leaked in ("AGENTFORGE_SIGNING_KEY", "HTTPS_PROXY", "DATABASE_URL"):
        assert leaked not in env
    assert env["MODEL_PROVIDER"] == "offline" and env["TOOL_BACKEND"] == "fixture"
    assert env["HOME"] == str(tmp_path / ".home") and env["TMPDIR"] == str(tmp_path / ".tmp")
    assert env["NO_PROXY"] == "*" and env["PYTHONHASHSEED"] == "0"


def test_exit_code_output_and_collection(sandbox: ProcessSandbox, tmp_path: Path) -> None:
    script = _script(
        tmp_path,
        "writer.py",
        "import pathlib, sys\n"
        "out = pathlib.Path('.agentforge-out'); out.mkdir(exist_ok=True)\n"
        "(out / 'report.json').write_text('{}')\n"
        "print('wrote report'); sys.exit(3)\n",
    )
    result = sandbox.run(
        tmp_path, ["python", script], collect=(".agentforge-out/report.json", ".agentforge-out/absent.json")
    )
    assert result.exit_code == 3 and not result.ok and not result.timed_out
    assert "wrote report" in result.output
    assert result.collected == [".agentforge-out/report.json"]
    assert result.as_dict()["command"] == "python writer.py"


def test_timeout_kills_the_whole_process_group(sandbox: ProcessSandbox, tmp_path: Path) -> None:
    script = _script(
        tmp_path,
        "spawner.py",
        "import pathlib, subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "pathlib.Path('child.pid').write_text(str(child.pid))\n"
        "time.sleep(60)\n",
    )
    started = time.monotonic()
    result = sandbox.run(tmp_path, ["python", script], timeout=2)
    assert result.timed_out and result.exit_code == -9 and not result.ok
    assert time.monotonic() - started < 15
    pid = int((tmp_path / "child.pid").read_text())
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        status = Path(f"/proc/{pid}/status")
        if not status.exists() or "\nState:\tZ" in status.read_text():
            break
        time.sleep(0.1)
    else:
        pytest.fail("grandchild process survived the sandbox timeout")


def test_cancellation_interrupts_a_running_command(sandbox: ProcessSandbox, tmp_path: Path) -> None:
    script = _script(tmp_path, "sleeper.py", "import time\ntime.sleep(60)\n")
    calls = {"n": 0}

    def should_cancel() -> bool:
        calls["n"] += 1
        return calls["n"] >= 2

    started = time.monotonic()
    with pytest.raises(SandboxCancelledError):
        sandbox.run(tmp_path, ["python", script], should_cancel=should_cancel)
    assert time.monotonic() - started < 10


def test_output_is_capped(sandbox: ProcessSandbox, tmp_path: Path) -> None:
    script = _script(tmp_path, "noisy.py", "import sys\nsys.stdout.write('x' * 400_000 + '\\nEND\\n')\n")
    result = sandbox.run(tmp_path, ["python", script])
    assert result.ok and result.truncated
    assert len(result.output) <= MAX_OUTPUT_BYTES and result.output.endswith("END\n")


def test_memory_limit_is_enforced(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(process_module, "_REQUIRED_MODULES", "import json")
    small = ProcessSandbox(Path(sys.executable), SandboxLimits(timeout_seconds=30, memory_mb=256))
    script = _script(tmp_path, "hog.py", "block = bytearray(1024 * 1024 * 1024)\nprint('allocated')\n")
    result = small.run(tmp_path, ["python", script])
    assert not result.ok and "allocated" not in result.output
    assert "MemoryError" in result.output


def test_missing_interpreter_is_reported(tmp_path: Path) -> None:
    missing = ProcessSandbox(tmp_path / "no-python", SandboxLimits())
    available, detail = missing.check()
    assert not available and "not found" in detail
    with pytest.raises(SandboxUnavailableError):
        missing.run(tmp_path, ["python", "-c", "pass"])


# --------------------------------------------------------------------------------------------
# Docker backend: exercised against a fake Engine API so the security contract is verifiable
# without a daemon.
# --------------------------------------------------------------------------------------------


def _frame(stream: int, payload: bytes) -> bytes:
    return bytes([stream, 0, 0, 0]) + len(payload).to_bytes(4, "big") + payload


def _tar_with(name: str, payload: bytes) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        info = tarfile.TarInfo(name)
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


class FakeDocker:
    def __init__(self, *, image_present: bool = True, wait: str = "exit", exit_code: int = 0) -> None:
        self.image_present = image_present
        self.wait = wait
        self.exit_code = exit_code
        self.requests: list[tuple[str, str]] = []
        self.created: dict | None = None
        self.uploaded: bytes = b""

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append((request.method, path))
        if path == "/_ping":
            return httpx.Response(200, text="OK")
        if path.startswith("/v1.44/images/"):
            return httpx.Response(200 if self.image_present else 404, json={})
        if path == "/v1.44/containers/create":
            self.created = json.loads(request.content)
            return httpx.Response(201, json={"Id": "c0ffee"})
        if path == "/v1.44/containers/c0ffee/archive" and request.method == "PUT":
            self.uploaded = request.content
            return httpx.Response(200)
        if path == "/v1.44/containers/c0ffee/start":
            return httpx.Response(204)
        if path == "/v1.44/containers/c0ffee/wait":
            if self.wait == "hang":
                time.sleep(0.02)
                raise httpx.ReadTimeout("still running", request=request)
            return httpx.Response(200, json={"StatusCode": self.exit_code})
        if path == "/v1.44/containers/c0ffee/logs":
            return httpx.Response(200, content=_frame(1, b"3 passed\n") + _frame(2, b"warning: slow\n"))
        if path == "/v1.44/containers/c0ffee/archive" and request.method == "GET":
            wanted = request.url.params["path"]
            if wanted.endswith("junit.xml"):
                return httpx.Response(200, content=_tar_with("junit.xml", b"<testsuite/>"))
            return httpx.Response(404, json={"message": "not found"})
        if path in {"/v1.44/containers/c0ffee/kill", "/v1.44/containers/c0ffee"}:
            return httpx.Response(204)
        return httpx.Response(500, json={"message": f"unexpected {request.method} {path}"})


def _docker(fake: FakeDocker, **limits) -> DockerSandbox:  # type: ignore[no-untyped-def]
    return DockerSandbox(
        host="tcp://sandbox-daemon:2376",
        image="agentforge/sandbox-runtime:1.0.0",
        limits=SandboxLimits(**{"timeout_seconds": 30, **limits}),
        runtime="runsc",
        transport=httpx.MockTransport(fake),
        poll_seconds=0.05,
    )


def _workspace(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hi')\n")
    for excluded in (".home", ".tmp", "src/__pycache__"):
        (tmp_path / excluded).mkdir(parents=True, exist_ok=True)
        (tmp_path / excluded / "junk").write_text("x")
    return tmp_path


def test_docker_container_is_locked_down(tmp_path: Path) -> None:
    fake = FakeDocker()
    result = _docker(fake).run(
        _workspace(tmp_path),
        ["python", "-m", "pytest"],
        collect=(".agentforge-out/junit.xml", ".agentforge-out/cov.json"),
    )
    assert result.ok and result.output == "3 passed\nwarning: slow\n"
    assert result.collected == [".agentforge-out/junit.xml"]
    assert (tmp_path / ".agentforge-out" / "junit.xml").read_bytes() == b"<testsuite/>"
    spec = fake.created
    assert spec is not None
    host = spec["HostConfig"]
    assert spec["User"] == f"{SANDBOX_UID}:{SANDBOX_UID}" and spec["NetworkDisabled"] is True
    assert host["NetworkMode"] == "none" and host["CapDrop"] == ["ALL"]
    assert host["SecurityOpt"] == ["no-new-privileges"] and host["Runtime"] == "runsc"
    assert host["Memory"] == host["MemorySwap"] == 2048 * 1024 * 1024
    assert host["PidsLimit"] == 512 and "Binds" not in host and "Privileged" not in host
    assert "MODEL_PROVIDER=offline" in spec["Env"]
    assert not any(variable.startswith(("HTTP_PROXY", "HTTPS_PROXY")) for variable in spec["Env"])
    assert ("DELETE", "/v1.44/containers/c0ffee") in fake.requests
    with tarfile.open(fileobj=io.BytesIO(fake.uploaded)) as archive:
        members = {member.name: member for member in archive.getmembers()}
    assert "src/app.py" in members and members["src/app.py"].uid == SANDBOX_UID
    assert not any(name.startswith((".home", ".tmp")) or "__pycache__" in name for name in members)


def test_docker_nonzero_exit_is_reported(tmp_path: Path) -> None:
    result = _docker(FakeDocker(exit_code=1)).run(
        _workspace(tmp_path), ["python", "-m", "ruff", "check", "."]
    )
    assert result.exit_code == 1 and not result.ok and not result.timed_out


def test_docker_timeout_kills_and_removes_the_container(tmp_path: Path) -> None:
    fake = FakeDocker(wait="hang")
    result = _docker(fake, timeout_seconds=1).run(_workspace(tmp_path), ["python", "-c", "while True: pass"])
    assert result.timed_out and result.exit_code == -9
    assert ("POST", "/v1.44/containers/c0ffee/kill") in fake.requests
    assert fake.requests[-1] == ("DELETE", "/v1.44/containers/c0ffee")


def test_docker_cancellation_kills_and_removes_the_container(tmp_path: Path) -> None:
    fake = FakeDocker(wait="hang")
    answers = iter([False, False, True])
    with pytest.raises(SandboxCancelledError):
        _docker(fake).run(
            _workspace(tmp_path), ["python", "-m", "pytest"], should_cancel=lambda: next(answers, True)
        )
    assert ("POST", "/v1.44/containers/c0ffee/kill") in fake.requests
    assert fake.requests[-1] == ("DELETE", "/v1.44/containers/c0ffee")


def test_docker_unavailable_image(tmp_path: Path) -> None:
    sandbox = _docker(FakeDocker(image_present=False))
    available, detail = sandbox.check()
    assert not available and "not found" in detail
    with pytest.raises(SandboxUnavailableError):
        sandbox.run(_workspace(tmp_path), ["python", "-c", "pass"])


def test_docker_refuses_unsafe_collect_paths(tmp_path: Path) -> None:
    from app.sandbox.base import SandboxError

    with pytest.raises(SandboxError):
        _docker(FakeDocker()).run(
            _workspace(tmp_path), ["python", "-c", "pass"], collect=("../../etc/passwd",)
        )


def test_docker_host_validation() -> None:
    from app.sandbox.base import SandboxError

    with pytest.raises(SandboxError, match="unsupported"):
        DockerSandbox(host="ssh://root@host", image="x:1", limits=SandboxLimits())
    with pytest.raises(SandboxError, match="CERT_PATH"):
        DockerSandbox(host="tcp://host:2376", image="x:1", limits=SandboxLimits(), tls_verify=True)


def test_demux_and_workspace_tar(tmp_path: Path) -> None:
    assert demux_logs(_frame(1, b"out ") + _frame(2, b"err")) == "out err"
    assert demux_logs(b"raw tty") == "raw tty"
    assert demux_logs(b"") == ""
    workspace = _workspace(tmp_path)
    first = build_workspace_tar(workspace)
    assert first == build_workspace_tar(workspace)


def test_docker_backend_requires_a_dedicated_daemon() -> None:
    from app.core.config import Settings
    from app.sandbox import build_sandbox

    with pytest.raises(ValueError, match="SANDBOX_DOCKER_HOST"):
        Settings(_env_file=None, sandbox_backend="docker")  # type: ignore[call-arg]
    settings = Settings(_env_file=None, sandbox_backend="docker", sandbox_docker_host="tcp://sandbox:2375")  # type: ignore[call-arg]
    sandbox = build_sandbox(settings)
    assert isinstance(sandbox, DockerSandbox) and sandbox.image == "agentforge/sandbox-runtime:1.0.0"
