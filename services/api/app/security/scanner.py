"""Static security validation of a generated repository.

Rule families:

* **paths & size** – confinement to the repository root, per-file and total size limits;
* **secrets** – private keys, cloud/SaaS tokens and high-entropy literals assigned to
  secret-looking names;
* **python AST** – dynamic code execution, shell execution, unsafe deserialisation, disabled TLS
  verification, weak hashes;
* **dependencies** – every declared dependency is on the allowlist and pinned with hashes;
* **container & compose** – non-root user, pinned base images, health checks, no privileged
  containers, no Docker socket mounts, no host networking;
* **specification & knowledge** – approval policy for side effects and instruction-like content
  in seed documents.

Critical and high findings block packaging.
"""

from __future__ import annotations

import ast
import math
import re
import tomllib
from collections import Counter
from pathlib import PurePosixPath

import yaml

from app.generator.shared.injection import scan as scan_injection
from app.schemas.report import SecurityFinding, SecurityReport

MAX_FILE_BYTES = 1_000_000
MAX_TOTAL_BYTES = 25_000_000
BLOCKING = {"critical", "high"}
ALLOWED_DEPENDENCIES = frozenset(
    {
        "fastapi",
        "uvicorn",
        "langgraph",
        "langgraph-checkpoint-sqlite",
        "langgraph-checkpoint-postgres",
        "aiosqlite",
        "psycopg",
        "pydantic",
        "pydantic-settings",
        "httpx",
        "sqlalchemy",
        "structlog",
        "pyyaml",
        "prometheus-client",
        "mcp",
        "pytest",
        "pytest-cov",
        "ruff",
        "bandit",
    }
)
SECRET_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "AF-SECRET-001",
        "Private key material",
        re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY"),
    ),
    ("AF-SECRET-002", "AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("AF-SECRET-003", "GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("AF-SECRET-004", "Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("AF-SECRET-005", "API secret key", re.compile(r"\b(?:sk|rk)-(?:live|proj|ant)?[A-Za-z0-9_-]{24,}\b")),
    ("AF-SECRET-006", "Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
)
SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b([a-z_]*(?:secret|token|api_?key|password|passwd|credential)[a-z_]*)\s*[:=]\s*['\"]([^'\"\s]{16,})['\"]"
)
PLACEHOLDER = re.compile(r"(?i)change-?me|example|dummy|placeholder|your-|test-|<.*>|\$\{")
DANGEROUS_CALLS = {
    "eval": ("AF-PY-001", "critical", "Dynamic code evaluation (eval)"),
    "exec": ("AF-PY-001", "critical", "Dynamic code execution (exec)"),
    "compile": ("AF-PY-002", "high", "Runtime compilation of code (compile)"),
    "__import__": ("AF-PY-003", "high", "Dynamic import (__import__)"),
    "os.system": ("AF-PY-004", "critical", "Shell command execution (os.system)"),
    "os.popen": ("AF-PY-004", "critical", "Shell command execution (os.popen)"),
    "os.exec": ("AF-PY-004", "critical", "Process replacement (os.exec*)"),
    "pickle.load": ("AF-PY-005", "high", "Unsafe deserialisation (pickle)"),
    "pickle.loads": ("AF-PY-005", "high", "Unsafe deserialisation (pickle)"),
    "marshal.loads": ("AF-PY-005", "high", "Unsafe deserialisation (marshal)"),
    "shelve.open": ("AF-PY-005", "medium", "Pickle-backed storage (shelve)"),
    "tempfile.mktemp": ("AF-PY-006", "medium", "Insecure temporary file (mktemp)"),
    "hashlib.md5": ("AF-PY-007", "low", "Weak hash function (md5)"),
    "hashlib.sha1": ("AF-PY-007", "low", "Weak hash function (sha1)"),
    "asyncio.create_subprocess_shell": ("AF-PY-004", "critical", "Shell command execution"),
}
SUBPROCESS_FUNCTIONS = {"run", "call", "check_call", "check_output", "Popen", "getoutput", "getstatusoutput"}


def _finding(
    rule_id: str,
    severity: str,
    title: str,
    path: str | None = None,
    line: int | None = None,
    detail: str = "",
) -> SecurityFinding:
    return SecurityFinding(
        rule_id=rule_id,
        severity=severity,  # type: ignore[arg-type]
        title=title,
        path=path,
        line=line,
        detail=detail[:500],
        blocking=severity in BLOCKING,
    )


def _dotted(node: ast.AST) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _shannon(text: str) -> float:
    counts = Counter(text)
    return -sum(count / len(text) * math.log2(count / len(text)) for count in counts.values())


def python_findings(path: str, source: str) -> list[SecurityFinding]:
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        return [_finding("AF-PY-000", "high", "File does not parse", path, exc.lineno, str(exc.msg))]
    findings: list[SecurityFinding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _dotted(node.func) or ""
        rule = DANGEROUS_CALLS.get(name)
        if rule is None and name.startswith("os.exec"):
            rule = DANGEROUS_CALLS["os.exec"]
        if rule is not None:
            findings.append(_finding(rule[0], rule[1], rule[2], path, node.lineno))
        if name.startswith("subprocess.") and name.split(".")[-1] in SUBPROCESS_FUNCTIONS:
            shell = any(
                keyword.arg == "shell"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
                for keyword in node.keywords
            )
            findings.append(
                _finding(
                    "AF-PY-008",
                    "critical" if shell else "high",
                    "Subprocess with shell=True" if shell else "Subprocess execution in agent code",
                    path,
                    node.lineno,
                )
            )
        if name in {"yaml.load", "yaml.load_all"}:
            loader = next((k.value for k in node.keywords if k.arg == "Loader"), None)
            loader_name = _dotted(loader) if loader is not None else None
            if not loader_name or "Safe" not in loader_name:
                findings.append(
                    _finding("AF-PY-009", "high", "yaml.load without SafeLoader", path, node.lineno)
                )
        for keyword in node.keywords:
            if (
                keyword.arg == "verify"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is False
            ):
                findings.append(
                    _finding("AF-PY-010", "high", "TLS certificate verification disabled", path, node.lineno)
                )
    return findings


def _secret_findings(path: str, text: str) -> list[SecurityFinding]:
    findings = []
    for rule_id, title, pattern in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            findings.append(_finding(rule_id, "critical", title, path, line))
    for match in SECRET_ASSIGNMENT.finditer(text):
        value = match.group(2)
        if PLACEHOLDER.search(value) or _shannon(value) < 3.5:
            continue
        line = text.count("\n", 0, match.start()) + 1
        findings.append(
            _finding(
                "AF-SECRET-010", "high", f"High-entropy literal assigned to '{match.group(1)}'", path, line
            )
        )
    return findings


def _dependency_findings(files: dict[str, str]) -> list[SecurityFinding]:
    findings: list[SecurityFinding] = []
    try:
        project = tomllib.loads(files.get("pyproject.toml", ""))["project"]
    except (tomllib.TOMLDecodeError, KeyError):
        return [_finding("AF-DEP-000", "high", "pyproject.toml is missing or invalid", "pyproject.toml")]
    declared = list(project.get("dependencies", []))
    for extra in project.get("optional-dependencies", {}).values():
        declared.extend(extra)
    for requirement in declared:
        name = re.split(r"[\s\[<>=!~;]", requirement, maxsplit=1)[0].lower().replace("_", "-")
        if name not in ALLOWED_DEPENDENCIES:
            findings.append(
                _finding(
                    "AF-DEP-001", "high", f"Dependency '{name}' is not on the allowlist", "pyproject.toml"
                )
            )
    for lock in ("requirements.lock", "requirements-dev.lock"):
        content = files.get(lock)
        if content is None:
            findings.append(_finding("AF-DEP-002", "medium", f"{lock} is missing", lock))
            continue
        pins = re.findall(r"^([a-z0-9][a-z0-9._-]*)==", content, re.MULTILINE | re.IGNORECASE)
        hashes = content.count("--hash=sha256:")
        if not pins:
            findings.append(_finding("AF-DEP-003", "medium", f"{lock} pins no packages", lock))
        elif hashes < len(pins):
            findings.append(_finding("AF-DEP-004", "medium", f"{lock} has packages without hashes", lock))
    return findings


def _dockerfile_findings(text: str) -> list[SecurityFinding]:
    path = "Dockerfile"
    findings = []
    users = re.findall(r"^\s*USER\s+(\S+)", text, re.MULTILINE)
    if not users:
        findings.append(_finding("AF-DOCKER-001", "high", "Container runs as root (no USER)", path))
    elif users[-1] in {"root", "0", "0:0"}:
        findings.append(_finding("AF-DOCKER-001", "high", "Container runs as root", path))
    for image in re.findall(r"^\s*FROM\s+(\S+)", text, re.MULTILINE):
        if image.lower() in {"scratch"}:
            continue
        if ":" not in image.split("/")[-1] and "@sha256:" not in image:
            findings.append(_finding("AF-DOCKER-002", "medium", f"Base image '{image}' is not pinned", path))
        elif image.endswith(":latest"):
            findings.append(_finding("AF-DOCKER-002", "medium", f"Base image '{image}' uses :latest", path))
    if "HEALTHCHECK" not in text:
        findings.append(_finding("AF-DOCKER-003", "low", "No HEALTHCHECK instruction", path))
    if re.search(r"^\s*ADD\s+https?://", text, re.MULTILINE):
        findings.append(_finding("AF-DOCKER-004", "medium", "ADD from a remote URL", path))
    if re.search(
        r"^\s*(ENV|ARG)\s+\S*(SECRET|TOKEN|PASSWORD|API_KEY)\S*\s*=\s*\S+", text, re.MULTILINE | re.IGNORECASE
    ):
        findings.append(_finding("AF-DOCKER-005", "high", "Secret baked into the image", path))
    return findings


def _compose_findings(text: str) -> list[SecurityFinding]:
    path = "docker-compose.yml"
    try:
        document = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        return [_finding("AF-COMPOSE-000", "high", "Compose file does not parse", path, detail=str(exc))]
    findings = []
    for name, service in (document.get("services") or {}).items():
        if not isinstance(service, dict):
            continue
        if service.get("privileged"):
            findings.append(_finding("AF-COMPOSE-001", "critical", f"Service '{name}' is privileged", path))
        if service.get("network_mode") == "host":
            findings.append(
                _finding("AF-COMPOSE-002", "high", f"Service '{name}' uses host networking", path)
            )
        for volume in service.get("volumes", []) or []:
            if "docker.sock" in str(volume):
                findings.append(
                    _finding("AF-COMPOSE-003", "critical", f"Service '{name}' mounts the Docker socket", path)
                )
        image = str(service.get("image", ""))
        if image.endswith(":latest"):
            findings.append(
                _finding("AF-COMPOSE-004", "medium", f"Service '{name}' uses a :latest image", path)
            )
        if "build" in service and "no-new-privileges:true" not in [
            str(item) for item in service.get("security_opt", []) or []
        ]:
            findings.append(
                _finding("AF-COMPOSE-005", "medium", f"Service '{name}' allows privilege escalation", path)
            )
    return findings


def _spec_findings(text: str) -> list[SecurityFinding]:
    try:
        spec = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        return [_finding("AF-SPEC-000", "high", "agent-spec.yaml does not parse", "agent-spec.yaml")]
    findings = []
    for tool in spec.get("tools", []) or []:
        if tool.get("mode") == "execute" and not tool.get("approval_required"):
            findings.append(
                _finding(
                    "AF-SPEC-001",
                    "critical",
                    f"Execute tool '{tool.get('name')}' does not require approval",
                    "agent-spec.yaml",
                )
            )
    if not ((spec.get("guardrails") or {}).get("tool_execution") or {}).get("allowlist_only", False):
        findings.append(_finding("AF-SPEC-002", "critical", "Tool allowlist is disabled", "agent-spec.yaml"))
    return findings


def scan_repository(files: dict[str, str], extra: list[SecurityFinding] | None = None) -> SecurityReport:
    findings: list[SecurityFinding] = []
    total = 0
    for raw_path, content in files.items():
        path = PurePosixPath(raw_path)
        if path.is_absolute() or ".." in path.parts or raw_path.startswith("/"):
            findings.append(_finding("AF-PATH-001", "critical", "Path escapes the repository root", raw_path))
            continue
        size = len(content.encode("utf-8"))
        total += size
        if size > MAX_FILE_BYTES:
            findings.append(
                _finding("AF-SIZE-001", "high", f"File exceeds {MAX_FILE_BYTES // 1000} KB", raw_path)
            )
        if raw_path.endswith(".lock") or raw_path == "evals/dataset.json":
            continue
        findings.extend(_secret_findings(raw_path, content))
        if raw_path.endswith(".py"):
            findings.extend(python_findings(raw_path, content))
        if raw_path.startswith("data/knowledge/") and raw_path.endswith((".md", ".txt", ".rst")):
            verdict = scan_injection(content, profile="retrieved")
            if verdict.suspicious:
                findings.append(
                    _finding(
                        "AF-RAG-001",
                        "high",
                        "Seed document contains instruction-like content",
                        raw_path,
                        detail=", ".join(verdict.rules),
                    )
                )
    if total > MAX_TOTAL_BYTES:
        findings.append(
            _finding("AF-SIZE-002", "high", f"Repository exceeds {MAX_TOTAL_BYTES // 1_000_000} MB")
        )
    findings.extend(_dependency_findings(files))
    if "Dockerfile" in files:
        findings.extend(_dockerfile_findings(files["Dockerfile"]))
    else:
        findings.append(_finding("AF-DOCKER-000", "medium", "No Dockerfile"))
    if "docker-compose.yml" in files:
        findings.extend(_compose_findings(files["docker-compose.yml"]))
    if "agent-spec.yaml" in files:
        findings.extend(_spec_findings(files["agent-spec.yaml"]))
    findings.extend(extra or [])
    findings.sort(
        key=lambda f: (
            ["critical", "high", "medium", "low", "info"].index(f.severity),
            f.path or "",
            f.line or 0,
        )
    )
    summary = {severity: 0 for severity in ("critical", "high", "medium", "low", "info")}
    for finding in findings:
        summary[finding.severity] += 1
    checks = [
        "repository paths confined to the root; size limits enforced",
        "no private keys, cloud tokens or high-entropy secrets in source",
        "no eval/exec, shell execution, unsafe deserialisation or disabled TLS verification",
        "dependencies allowlisted, pinned and hash-locked",
        "container runs as non-root with pinned base image and health check",
        "compose services unprivileged, no Docker socket, no host networking",
        "side-effecting tools require approval; tool allowlist enforced",
        "seed knowledge free of instruction-like content",
    ]
    if extra is not None:
        checks.append("bandit static analysis executed in the sandbox")
    return SecurityReport(
        status="failed" if any(finding.blocking for finding in findings) else "passed",
        summary=summary,
        findings=findings,
        checks=checks,
        files_scanned=len(files),
    )
