"""End-to-end: compile → plan → generate → *real* sandbox gates → scan → signed package.

Runs the generated repository's own lint, tests and evaluation suite with the process sandbox, so
it needs the agent runtime interpreter (``AGENTFORGE_SANDBOX_PYTHON``, built from
``app/generator/runtime/requirements-dev.lock``). Select with ``pytest -m sandbox``.
"""

from __future__ import annotations

import uuid
import zipfile
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.compiler import compile_requirement, spec_hash
from app.compiler.templates import TEMPLATES_BY_ID
from app.core.config import Settings
from app.models.build import BuildRecord
from app.packaging.archive import verify_package
from app.packaging.signing import generate_key
from app.services.pipeline import execute_build, initial_stages
from tests.conftest import RUNTIME_PYTHON

pytestmark = [
    pytest.mark.sandbox,
    pytest.mark.skipif(
        not RUNTIME_PYTHON.exists(), reason=f"agent runtime interpreter not found at {RUNTIME_PYTHON}"
    ),
]


@pytest.mark.parametrize("template", ["maintenance-triage", "research-analyst"])
def test_generated_repository_passes_its_own_gates(
    session_factory: sessionmaker[Session], tmp_path: Path, template: str
) -> None:
    seed, public_pem = generate_key()
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        artifact_root=tmp_path / "artifacts",
        workspace_root=tmp_path / "workspaces",
        sandbox_backend="process",
        sandbox_python=RUNTIME_PYTHON,
        sandbox_timeout_seconds=600,
        run_bandit=True,
        signing_key=seed,
    )
    spec = compile_requirement(TEMPLATES_BY_ID[template].requirement).spec
    with session_factory() as session:
        record = BuildRecord(
            agent_name=spec.agent.name,
            spec_hash=spec_hash(spec),
            spec=spec.model_dump(mode="json"),
            status="queued",
            progress=0.0,
            stages=initial_stages(),
        )
        session.add(record)
        session.commit()
        build_id = str(record.id)

    status = execute_build(build_id, settings=settings, session_factory=session_factory)

    with session_factory() as session:
        record = session.get(BuildRecord, uuid.UUID(build_id))
        assert record is not None
        assert status == "succeeded", f"{record.error}\n{record.report}"
        metrics = record.metrics
        report = record.report
    assert metrics["tests_failed"] == 0 and metrics["tests_passed"] >= 50
    assert metrics["test_coverage"] >= 0.8
    assert metrics["task_success"] >= spec.evaluation.task_success_target
    assert metrics["unsafe_actions"] == 0
    assert report["sandbox"] == "process"
    assert report["security"]["status"] == "passed"
    assert all(gate["status"] == "passed" for gate in report["gates"].values())

    artifact = Path(record.artifact_path)
    verification = verify_package(artifact, trusted_public_pem=public_pem)
    assert verification["valid"] and verification["trusted"], verification
    with zipfile.ZipFile(artifact) as archive:
        names = archive.namelist()
        root = names[0].split("/", 1)[0]
        junit = archive.read(f"{root}/.agentforge/junit.xml")
    assert b"<testsuite" in junit and not any(
        ".agentforge-out" in name or "/.home/" in name for name in names
    )
