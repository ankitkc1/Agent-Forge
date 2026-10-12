from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath


class QualityGateError(RuntimeError):
    def __init__(self, message: str, logs: list[str]) -> None:
        super().__init__(message)
        self.logs = logs


def write_repository(root: Path, files: dict[str, str]) -> None:
    resolved_root = root.resolve()
    for relative_name, content in files.items():
        relative = PurePosixPath(relative_name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe generated path: {relative_name}")
        target = root.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.resolve().is_relative_to(resolved_root):
            raise ValueError(f"generated path escapes repository root: {relative_name}")
        target.write_text(content, encoding="utf-8", newline="\n")


def _run(command: list[str], root: Path, timeout: int = 90) -> tuple[bool, list[str]]:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": os.pathsep.join(filter(None, [str(root), os.environ.get("PYTHONPATH")])),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "NO_PROXY": "*",
    }
    for key in ("TEMP", "TMP", "TMPDIR", "SYSTEMROOT"):
        if value := os.environ.get(key):
            env[key] = value
    process = subprocess.run(
        command,
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        shell=False,
    )
    output = [line for line in (process.stdout + process.stderr).splitlines() if line.strip()]
    label = " ".join(command[:3])
    return process.returncode == 0, [f"{label}: {line}" for line in output[-40:]]


def run_quality_gates(root: Path, *, repair: bool = False) -> list[str]:
    commands = [
        [sys.executable, "-m", "compileall", "-q", "src", "tests", "evals"],
        [sys.executable, "-m", "ruff", "check", ".", *(["--fix"] if repair else [])],
        [sys.executable, "-m", "pytest", "-q"],
    ]
    logs: list[str] = []
    for command in commands:
        success, command_logs = _run(command, root)
        logs.extend(command_logs)
        if not success:
            raise QualityGateError(f"quality gate failed: {' '.join(command[:3])}", logs)
    return logs


def package_repository(root: Path, destination: Path, repository_name: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    with zipfile.ZipFile(
        temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for file_path in sorted(path for path in root.rglob("*") if path.is_file()):
            if any(
                part in {"__pycache__", ".pytest_cache", ".ruff_cache", ".git"}
                for part in file_path.parts
            ):
                continue
            archive.write(file_path, f"{repository_name}/{file_path.relative_to(root).as_posix()}")
    temporary.replace(destination)
