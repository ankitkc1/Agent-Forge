"""Packaging: reproducible archives, tamper detection, signatures, SBOM and provenance."""

from __future__ import annotations

import base64
import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.generator.engine import RUNTIME_LOCKS
from app.packaging.archive import build_package, provenance_statement, source_digest, verify_package
from app.packaging.sbom import build_sbom, parse_lock
from app.packaging.signing import SigningKeyError, generate_key, load_signer, verify

RUNTIME_LOCK = (RUNTIME_LOCKS / "requirements-runtime.lock").read_text(encoding="utf-8")
DEV_LOCK = (RUNTIME_LOCKS / "requirements-dev.lock").read_text(encoding="utf-8")
SOURCE = {
    "README.md": b"# Demo agent\n",
    "src/agent/graph.py": b"GRAPH = 1\n",
    "src/agent/state.py": b"STATE = 2\n",
}


def _provenance(digest: str) -> dict:
    statement = provenance_statement(
        package="demo-agent",
        digest=digest,
        build_id="00000000-0000-0000-0000-000000000001",
        spec_hash="a" * 64,
        agent="demo_agent",
        agentforge_version="1.0.0",
        generator="agentforge-generator/1",
        sandbox="scripted",
        lock_digest="b" * 64,
        started_at=datetime(2026, 10, 12, 8, 0, tzinfo=UTC),
        builder_id="https://agentforge.test/builder",
    )
    statement["predicate"]["runDetails"]["metadata"]["finishedOn"] = "2026-10-12T08:05:00+00:00"
    return statement


def _package(tmp_path: Path, name: str, *, signer=None, source=SOURCE) -> Path:  # type: ignore[no-untyped-def]
    destination = tmp_path / name
    build_package(
        destination=destination,
        package="demo-agent",
        source_files=source,
        evidence={"build-report.json": b'{"status": "succeeded"}'},
        signer=signer,
        sbom_inputs={"requirements.lock": RUNTIME_LOCK, "requirements-dev.lock": DEV_LOCK},
        provenance=_provenance(source_digest(source)),
    )
    return destination


def _rewrite(
    archive: Path,
    target: Path,
    *,
    replace: dict[str, bytes] | None = None,
    add: dict[str, bytes] | None = None,
    drop: set[str] = frozenset(),
) -> Path:  # type: ignore[assignment]
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(target, "w") as copy:
        for info in source.infolist():
            if info.filename in drop:
                continue
            data = (replace or {}).get(info.filename, source.read(info.filename))
            copy.writestr(info, data)
        for name, data in (add or {}).items():
            copy.writestr(name, data)
    return target


@pytest.fixture
def signer():  # type: ignore[no-untyped-def]
    seed, _ = generate_key()
    return load_signer(seed)


def test_identical_inputs_produce_identical_bytes(tmp_path: Path, signer) -> None:  # type: ignore[no-untyped-def]
    first = _package(tmp_path, "a.zip", signer=signer)
    second = _package(tmp_path, "b.zip", signer=signer)
    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        infos = archive.infolist()
    assert [info.filename for info in infos] == sorted(info.filename for info in infos)
    assert {info.date_time for info in infos} == {(1980, 1, 1, 0, 0, 0)}
    assert {info.external_attr >> 16 for info in infos} == {0o100644}


def test_archive_layout_and_valid_signature(tmp_path: Path, signer) -> None:  # type: ignore[no-untyped-def]
    archive = _package(tmp_path, "demo.zip", signer=signer)
    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
        manifest = bundle.read("demo-agent/.agentforge/MANIFEST.sha256").decode()
        signature = json.loads(bundle.read("demo-agent/.agentforge/SIGNATURE.json"))
    for expected in (
        "demo-agent/src/agent/graph.py",
        "demo-agent/.agentforge/build-report.json",
        "demo-agent/.agentforge/sbom.cdx.json",
        "demo-agent/.agentforge/provenance.json",
        "demo-agent/.agentforge/MANIFEST.sha256.sig",
        "demo-agent/.agentforge/signing-key.pub",
    ):
        assert expected in names
    assert "src/agent/graph.py" in manifest and ".agentforge/provenance.json" in manifest
    assert signature == {"algorithm": "ed25519", "key_id": signer.key_id, "signed_file": "MANIFEST.sha256"}
    result = verify_package(archive)
    assert result["valid"] is True
    assert result["signature_valid"] is True
    assert result["files_verified"] == len(SOURCE) + 3
    assert result["key_id"] == signer.key_id
    trusted = verify_package(archive, trusted_public_pem=signer.public_pem)
    assert trusted["trusted"] is True and trusted["valid"] is True


def test_unsigned_package_verifies_integrity_only(tmp_path: Path) -> None:
    archive = _package(tmp_path, "unsigned.zip")
    result = verify_package(archive)
    assert result["valid"] is True and result["signature_valid"] is None
    _, other_public = generate_key()
    assert verify_package(archive, trusted_public_pem=other_public)["valid"] is False


@pytest.mark.parametrize("attack", ["modify", "add", "remove", "manifest", "resign"])
def test_tampering_is_detected(tmp_path: Path, signer, attack: str) -> None:  # type: ignore[no-untyped-def]
    original = _package(tmp_path, "original.zip", signer=signer)
    target = tmp_path / f"{attack}.zip"
    with zipfile.ZipFile(original) as bundle:
        manifest = bundle.read("demo-agent/.agentforge/MANIFEST.sha256")
    if attack == "modify":
        _rewrite(original, target, replace={"demo-agent/src/agent/graph.py": b"import os\nos.system('id')\n"})
        assert verify_package(target)["mismatches"] == ["src/agent/graph.py"]
    elif attack == "add":
        _rewrite(original, target, add={"demo-agent/src/agent/backdoor.py": b"x = 1\n"})
        assert verify_package(target)["unlisted"] == ["src/agent/backdoor.py"]
    elif attack == "remove":
        _rewrite(original, target, drop={"demo-agent/src/agent/state.py"})
        assert verify_package(target)["missing"] == ["src/agent/state.py"]
    elif attack == "manifest":
        forged = manifest.replace(b"README.md", b"README.MD")
        _rewrite(original, target, replace={"demo-agent/.agentforge/MANIFEST.sha256": forged})
        assert verify_package(target)["signature_valid"] is False
    else:  # attacker rewrites a file, regenerates the manifest and signs it with their own key
        attacker = load_signer(generate_key()[0])
        payload = b"STATE = 'pwned'\n"
        from app.packaging.archive import sha256_bytes

        lines = []
        for line in manifest.decode().splitlines():
            digest, path = line.split("  ", 1)
            lines.append(f"{sha256_bytes(payload) if path == 'src/agent/state.py' else digest}  {path}")
        forged = ("\n".join(lines) + "\n").encode()
        _rewrite(
            original,
            target,
            replace={
                "demo-agent/src/agent/state.py": payload,
                "demo-agent/.agentforge/MANIFEST.sha256": forged,
                "demo-agent/.agentforge/MANIFEST.sha256.sig": (attacker.sign(forged) + "\n").encode(),
                "demo-agent/.agentforge/signing-key.pub": attacker.public_pem.encode(),
            },
        )
        # Integrity holds against the embedded key — only the trusted key reveals the forgery.
        assert verify_package(target)["valid"] is True
        trusted = verify_package(target, trusted_public_pem=signer.public_pem)
        assert trusted["valid"] is False and trusted["signature_valid"] is False
        return
    assert verify_package(target)["valid"] is False


def test_verify_rejects_garbage(tmp_path: Path) -> None:
    junk = tmp_path / "junk.zip"
    junk.write_bytes(b"not a zip")
    result = verify_package(junk)
    assert result["valid"] is False and "BadZipFile" in result["error"]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("a/readme.md", "x")
        bundle.writestr("b/readme.md", "y")
    two_roots = tmp_path / "two.zip"
    two_roots.write_bytes(buffer.getvalue())
    assert verify_package(two_roots)["error"].startswith("ValueError")


def test_unsafe_paths_are_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsafe archive path"):
        _package(tmp_path, "bad.zip", source={**SOURCE, "../evil.py": b"x"})


def test_signing_keys(tmp_path: Path) -> None:
    seed, public_pem = generate_key()
    signer = load_signer(seed)
    assert signer is not None and signer.public_pem == public_pem
    assert signer.key_id.startswith("ed25519:") and len(signer.key_id) == len("ed25519:") + 16
    signature = signer.sign(b"payload")
    assert verify(public_pem, b"payload", signature)
    assert not verify(public_pem, b"payload!", signature)
    assert not verify("not a pem", b"payload", signature)
    pem = (
        Ed25519PrivateKey.from_private_bytes(base64.b64decode(seed))
        .private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
        .decode()
    )
    assert load_signer(pem).key_id == signer.key_id  # type: ignore[union-attr]
    assert load_signer(seed, key_id="custom").key_id == "custom"  # type: ignore[union-attr]
    assert load_signer(None) is None and load_signer("") is None
    with pytest.raises(SigningKeyError):
        load_signer("definitely-not-base64!")
    with pytest.raises(SigningKeyError):
        load_signer(base64.b64encode(b"short").decode())


def test_sbom_from_real_lock_files() -> None:
    runtime = parse_lock(RUNTIME_LOCK)
    development = parse_lock(DEV_LOCK)
    assert {"langgraph", "fastapi", "pydantic"} <= set(runtime)
    assert {"pytest", "ruff"} <= set(development) - set(runtime)
    assert all(digest and len(digest) == 64 for _, digest in runtime.values())
    sbom = build_sbom(
        package="demo-agent",
        version="0.1.0",
        runtime_lock=RUNTIME_LOCK,
        dev_lock=DEV_LOCK,
        source_digest="c" * 64,
        agentforge_version="1.0.0",
        timestamp="2026-10-12T08:05:00+00:00",
    )
    assert sbom["bomFormat"] == "CycloneDX" and sbom["specVersion"] == "1.6"
    assert sbom["metadata"]["timestamp"] == "2026-10-12T08:05:00+00:00"
    by_name = {component["name"]: component for component in sbom["components"]}
    assert by_name["langgraph"]["scope"] == "required"
    assert by_name["pytest"]["scope"] == "excluded"
    assert by_name["fastapi"]["purl"] == f"pkg:pypi/fastapi@{runtime['fastapi'][0]}"
    required = sbom["dependencies"][0]["dependsOn"]
    assert len(required) == len(runtime)
    # deterministic serial number for the same source
    again = build_sbom(
        package="demo-agent",
        version="0.1.0",
        runtime_lock="",
        dev_lock="",
        source_digest="c" * 64,
        agentforge_version="1.0.0",
    )
    assert again["serialNumber"] == sbom["serialNumber"]


def test_provenance_statement_shape() -> None:
    statement = _provenance("d" * 64)
    assert statement["_type"] == "https://in-toto.io/Statement/v1"
    assert statement["predicateType"] == "https://slsa.dev/provenance/v1"
    assert statement["subject"] == [{"name": "demo-agent/source", "digest": {"sha256": "d" * 64}}]
    definition = statement["predicate"]["buildDefinition"]
    assert definition["externalParameters"]["agentSpec"]["sha256"] == "a" * 64
    assert statement["predicate"]["runDetails"]["metadata"]["startedOn"] == "2026-10-12T08:00:00+00:00"
