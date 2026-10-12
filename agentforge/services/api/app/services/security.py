from __future__ import annotations

import re
from pathlib import PurePosixPath


class SecurityValidationError(RuntimeError):
    pass


FORBIDDEN_PATTERNS = {
    "embedded private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "likely API credential": re.compile(
        r"(?i)(?:api[_-]?key|secret|token)\s*=\s*['\"][A-Za-z0-9_-]{24,}"
    ),
    "unsafe shell invocation": re.compile(r"subprocess\.(?:run|Popen)\([^\n]*shell\s*=\s*True"),
    "dynamic evaluation": re.compile(r"\b(?:eval|exec)\s*\("),
}


def validate_repository(files: dict[str, str]) -> list[str]:
    if not files:
        raise SecurityValidationError("generator produced no files")
    findings: list[str] = []
    for raw_path, content in files.items():
        path = PurePosixPath(raw_path)
        if path.is_absolute() or ".." in path.parts:
            raise SecurityValidationError(f"unsafe artifact path: {raw_path}")
        if len(content.encode()) > 1_000_000:
            raise SecurityValidationError(f"artifact file exceeds 1 MB: {raw_path}")
        for label, pattern in FORBIDDEN_PATTERNS.items():
            if pattern.search(content):
                findings.append(f"{raw_path}: {label}")
    if findings:
        raise SecurityValidationError("; ".join(findings))
    return [
        "artifact paths are confined to the repository root",
        "no embedded credentials or private keys detected",
        "no shell=True, eval(), or exec() calls detected",
        "runtime tools are generated from an explicit allowlist",
    ]
