"""CycloneDX 1.6 SBOM derived from the generated repository's hash-locked requirements."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;\\]+)")
_HASH = re.compile(r"--hash=sha256:([0-9a-f]{64})")
NAMESPACE = uuid.UUID("6f1c7a52-31a0-4d0e-9c1e-1b6a3a0e5f00")


def parse_lock(content: str) -> dict[str, tuple[str, str | None]]:
    """Return {name: (version, first sha256)} from a pip-compile style lock file."""
    packages: dict[str, tuple[str, str | None]] = {}
    current: str | None = None
    for line in content.splitlines():
        match = _PIN.match(line.strip())
        if match:
            current = match.group(1).lower()
            packages[current] = (match.group(2), None)
            continue
        hash_match = _HASH.search(line)
        if hash_match and current and packages[current][1] is None:
            packages[current] = (packages[current][0], hash_match.group(1))
    return packages


def build_sbom(
    *,
    package: str,
    version: str,
    runtime_lock: str,
    dev_lock: str,
    source_digest: str,
    agentforge_version: str,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Build the SBOM. Pass ``timestamp`` (ISO 8601) to make the document reproducible."""
    runtime = parse_lock(runtime_lock)
    development = parse_lock(dev_lock)
    components = []
    for name in sorted(set(runtime) | set(development)):
        pin_version, digest = runtime.get(name) or development[name]
        purl = f"pkg:pypi/{name}@{pin_version}"
        component: dict[str, Any] = {
            "type": "library",
            "bom-ref": purl,
            "name": name,
            "version": pin_version,
            "purl": purl,
            "scope": "required" if name in runtime else "excluded",
        }
        if digest:
            component["hashes"] = [{"alg": "SHA-256", "content": digest}]
        components.append(component)
    root_ref = f"pkg:generic/{package}@{version}"
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{uuid.uuid5(NAMESPACE, source_digest)}",
        "version": 1,
        "metadata": {
            "timestamp": timestamp or datetime.now(UTC).replace(microsecond=0).isoformat(),
            "tools": {
                "components": [{"type": "application", "name": "agentforge", "version": agentforge_version}]
            },
            "component": {
                "type": "application",
                "bom-ref": root_ref,
                "name": package,
                "version": version,
                "hashes": [{"alg": "SHA-256", "content": source_digest}],
            },
        },
        "components": components,
        "dependencies": [
            {"ref": root_ref, "dependsOn": [c["bom-ref"] for c in components if c["scope"] == "required"]}
        ],
    }
