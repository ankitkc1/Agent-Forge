"""Deterministic packaging with a signed manifest, SBOM and SLSA-style provenance.

Archive layout::

    <package>/...                       generated source (byte-identical for the same spec)
    <package>/.agentforge/
        build-report.json               pipeline summary (plan, gates, repairs, security)
        junit.xml, coverage.json        raw test evidence from the sandbox
        eval-report.json                evaluation results per case
        security-report.json / .sarif   static security findings
        sbom.cdx.json                   CycloneDX SBOM of the locked dependencies
        provenance.json                 in-toto statement with SLSA v1 provenance predicate
        MANIFEST.sha256                 sha256 of every file above (and all source files)
        MANIFEST.sha256.sig             Ed25519 signature of the manifest (when a key is set)
        signing-key.pub                 public key to verify the signature

ZIP entries are sorted, timestamped 1980-01-01 and stored with fixed permissions, and the SBOM
timestamp is taken from the provenance statement, so identical inputs produce identical archive
bytes. Across builds of the same specification the *source* digest is stable; only the evidence
(timings, provenance timestamps) differs.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from app.packaging.sbom import build_sbom
from app.packaging.signing import ALGORITHM, Signer

FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
EVIDENCE_DIR = ".agentforge"


@dataclass(frozen=True)
class PackageResult:
    path: Path
    sha256: str
    size_bytes: int
    files: int
    source_digest: str
    signed: bool
    key_id: str | None
    sbom_components: int


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_digest(files: Mapping[str, bytes]) -> str:
    """Digest over sorted (path, sha256) pairs of the generated source (evidence excluded)."""
    hasher = hashlib.sha256()
    for path in sorted(files):
        hasher.update(path.encode() + b"\0" + sha256_bytes(files[path]).encode() + b"\n")
    return hasher.hexdigest()


def provenance_statement(
    *,
    package: str,
    digest: str,
    build_id: str,
    spec_hash: str,
    agent: str,
    agentforge_version: str,
    generator: str,
    sandbox: str,
    lock_digest: str,
    started_at: datetime,
    builder_id: str,
) -> dict[str, Any]:
    return {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [{"name": f"{package}/source", "digest": {"sha256": digest}}],
        "predicateType": "https://slsa.dev/provenance/v1",
        "predicate": {
            "buildDefinition": {
                "buildType": "https://agentforge.dev/build-types/agent-repository/v1",
                "externalParameters": {"agentSpec": {"sha256": spec_hash, "agent": agent}},
                "internalParameters": {
                    "agentforgeVersion": agentforge_version,
                    "generator": generator,
                    "sandbox": sandbox,
                    "evaluationMode": "offline",
                },
                "resolvedDependencies": [
                    {
                        "uri": "agentforge:generator/runtime/requirements-dev.lock",
                        "digest": {"sha256": lock_digest},
                    }
                ],
            },
            "runDetails": {
                "builder": {"id": builder_id, "version": {"agentforge": agentforge_version}},
                "metadata": {
                    "invocationId": build_id,
                    "startedOn": started_at.replace(microsecond=0).isoformat(),
                    "finishedOn": datetime.now(UTC).replace(microsecond=0).isoformat(),
                },
            },
        },
    }


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=FIXED_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def build_package(
    *,
    destination: Path,
    package: str,
    source_files: Mapping[str, bytes],
    evidence: Mapping[str, bytes],
    signer: Signer | None,
    sbom_inputs: Mapping[str, str],
    provenance: Mapping[str, Any],
) -> PackageResult:
    for path in [*source_files, *evidence]:
        pure = PurePosixPath(path)
        if pure.is_absolute() or ".." in pure.parts:
            raise ValueError(f"unsafe archive path: {path}")
    digest = source_digest(source_files)
    predicate = provenance["predicate"]
    sbom = build_sbom(
        package=package,
        version="0.1.0",
        runtime_lock=sbom_inputs.get("requirements.lock", ""),
        dev_lock=sbom_inputs.get("requirements-dev.lock", ""),
        source_digest=digest,
        agentforge_version=str(predicate["buildDefinition"]["internalParameters"]["agentforgeVersion"]),
        timestamp=str(predicate["runDetails"]["metadata"]["finishedOn"]),
    )
    all_evidence: dict[str, bytes] = {f"{EVIDENCE_DIR}/{name}": content for name, content in evidence.items()}
    all_evidence[f"{EVIDENCE_DIR}/sbom.cdx.json"] = json.dumps(sbom, indent=2).encode()
    all_evidence[f"{EVIDENCE_DIR}/provenance.json"] = json.dumps(provenance, indent=2).encode()
    manifest_lines = [
        f"{sha256_bytes(content)}  {path}"
        for path, content in sorted({**source_files, **all_evidence}.items())
    ]
    manifest = ("\n".join(manifest_lines) + "\n").encode()
    all_evidence[f"{EVIDENCE_DIR}/MANIFEST.sha256"] = manifest
    if signer is not None:
        all_evidence[f"{EVIDENCE_DIR}/MANIFEST.sha256.sig"] = (signer.sign(manifest) + "\n").encode()
        all_evidence[f"{EVIDENCE_DIR}/signing-key.pub"] = signer.public_pem.encode()
        all_evidence[f"{EVIDENCE_DIR}/SIGNATURE.json"] = json.dumps(
            {"algorithm": ALGORITHM, "key_id": signer.key_id, "signed_file": "MANIFEST.sha256"}, indent=2
        ).encode()

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".partial")
    entries = {**source_files, **all_evidence}
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(entries):
            archive.writestr(_zip_info(f"{package}/{path}"), entries[path])
    temporary.replace(destination)
    data = destination.read_bytes()
    return PackageResult(
        path=destination,
        sha256=sha256_bytes(data),
        size_bytes=len(data),
        files=len(entries),
        source_digest=digest,
        signed=signer is not None,
        key_id=signer.key_id if signer else None,
        sbom_components=len(sbom["components"]),
    )


SIGNATURE_FILES = frozenset(
    f"{EVIDENCE_DIR}/{name}"
    for name in ("MANIFEST.sha256", "MANIFEST.sha256.sig", "signing-key.pub", "SIGNATURE.json")
)


def verify_package(archive_path: Path, *, trusted_public_pem: str | None = None) -> dict[str, Any]:
    """Verify a packaged artifact without extracting it.

    Checks that every manifest entry exists with the recorded digest, that the archive contains no
    file the manifest does not list, and — when present — the Ed25519 signature over the manifest.
    The embedded public key only proves *integrity*; pass ``trusted_public_pem`` (published at
    ``GET /api/v1/system/signing-key``) to also prove *origin*.
    """
    from app.packaging.signing import key_id_for_pem, verify

    result: dict[str, Any] = {
        "valid": False,
        "files_verified": 0,
        "mismatches": [],
        "missing": [],
        "unlisted": [],
        "signature_valid": None,
        "key_id": None,
        "trusted": None,
        "error": None,
    }
    try:
        with zipfile.ZipFile(archive_path) as archive:
            names = [name for name in archive.namelist() if not name.endswith("/")]
            roots = {name.split("/", 1)[0] for name in names}
            if len(roots) != 1:
                raise ValueError("archive must contain exactly one top-level directory")
            root = roots.pop()
            members = {name.split("/", 1)[1] for name in names if "/" in name}
            manifest = archive.read(f"{root}/{EVIDENCE_DIR}/MANIFEST.sha256")
            listed: set[str] = set()
            for line in manifest.decode().splitlines():
                expected, path = line.split("  ", 1)
                listed.add(path)
                if path not in members:
                    result["missing"].append(path)
                elif sha256_bytes(archive.read(f"{root}/{path}")) != expected:
                    result["mismatches"].append(path)
            result["files_verified"] = len(listed)
            result["unlisted"] = sorted(members - listed - SIGNATURE_FILES)
            signature_name = f"{EVIDENCE_DIR}/MANIFEST.sha256.sig"
            if signature_name in members:
                embedded_pem = archive.read(f"{root}/{EVIDENCE_DIR}/signing-key.pub").decode()
                public_pem = trusted_public_pem or embedded_pem
                result["signature_valid"] = verify(
                    public_pem, manifest, archive.read(f"{root}/{signature_name}").decode().strip()
                )
                result["key_id"] = key_id_for_pem(public_pem)
                if trusted_public_pem is not None:
                    result["trusted"] = (
                        bool(result["signature_valid"]) and key_id_for_pem(embedded_pem) == result["key_id"]
                    )
            elif trusted_public_pem is not None:
                result["trusted"] = False
    except (KeyError, ValueError, zipfile.BadZipFile, UnicodeDecodeError) as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"[:300]
        return result
    result["valid"] = (
        not result["mismatches"]
        and not result["missing"]
        and not result["unlisted"]
        and result["signature_valid"] is not False
        and result["trusted"] is not False
    )
    return result
