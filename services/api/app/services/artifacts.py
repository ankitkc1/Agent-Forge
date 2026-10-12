"""Read-only access to packaged artifacts (file listing and previews) without extracting them."""

from __future__ import annotations

import zipfile
from pathlib import Path, PurePosixPath

from app.schemas.build import FileContent, FileEntry

MAX_PREVIEW_BYTES = 512_000
LANGUAGES = {
    ".py": "python",
    ".md": "markdown",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".txt": "text",
    ".xml": "xml",
    ".sarif": "json",
    ".lock": "text",
    ".cfg": "ini",
    ".ini": "ini",
    ".sh": "shell",
    ".j2": "jinja",
    ".html": "html",
}
SPECIAL = {"Dockerfile": "dockerfile", "Makefile": "makefile", ".env.example": "dotenv", ".gitignore": "text"}


class ArtifactAccessError(LookupError):
    pass


def resolve_artifact(artifact_root: Path, artifact_path: str | None) -> Path:
    if not artifact_path:
        raise ArtifactAccessError("artifact is not available")
    root = artifact_root.resolve()
    artifact = Path(artifact_path).resolve()
    if not artifact.is_relative_to(root) or not artifact.is_file():
        raise ArtifactAccessError("artifact not found")
    return artifact


def _prefix(archive: zipfile.ZipFile) -> str:
    names = archive.namelist()
    return names[0].split("/", 1)[0] + "/" if names else ""


def _manifest(archive: zipfile.ZipFile, prefix: str) -> dict[str, str]:
    try:
        text = archive.read(f"{prefix}.agentforge/MANIFEST.sha256").decode()
    except KeyError:
        return {}
    digests = {}
    for line in text.splitlines():
        if "  " in line:
            digest, path = line.split("  ", 1)
            digests[path] = digest
    return digests


def list_files(artifact: Path) -> list[FileEntry]:
    with zipfile.ZipFile(artifact) as archive:
        prefix = _prefix(archive)
        digests = _manifest(archive, prefix)
        entries = []
        for info in archive.infolist():
            if info.is_dir() or not info.filename.startswith(prefix):
                continue
            path = info.filename[len(prefix) :]
            entries.append(
                FileEntry(
                    path=path,
                    size=info.file_size,
                    sha256=digests.get(path),
                    evidence=path.startswith(".agentforge/"),
                )
            )
    return sorted(entries, key=lambda entry: (entry.evidence, entry.path))


def read_file(artifact: Path, path: str) -> FileContent:
    pure = PurePosixPath(path)
    if pure.is_absolute() or ".." in pure.parts or not path:
        raise ArtifactAccessError("invalid path")
    with zipfile.ZipFile(artifact) as archive:
        prefix = _prefix(archive)
        try:
            info = archive.getinfo(prefix + path)
        except KeyError as exc:
            raise ArtifactAccessError("file not found") from exc
        with archive.open(info) as handle:
            data = handle.read(MAX_PREVIEW_BYTES + 1)
    truncated = len(data) > MAX_PREVIEW_BYTES
    data = data[:MAX_PREVIEW_BYTES]
    if b"\x00" in data[:8000]:
        raise ArtifactAccessError("binary file")
    name = pure.name
    language = SPECIAL.get(name) or LANGUAGES.get(pure.suffix.lower(), "text")
    return FileContent(
        path=path,
        size=info.file_size,
        content=data.decode("utf-8", errors="replace"),
        language=language,
        truncated=truncated,
    )
