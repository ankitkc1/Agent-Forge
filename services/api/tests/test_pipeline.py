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
from app.services import pipeline
from app.services.pipeline import execute_build, initial_stages
from tests.fakes import ScriptedSandbox


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "artifact_root": tmp_path / "artifacts",
        "workspace_root": tmp_path / "workspaces",
        "run_bandit": True,
        "repair_max_attempts": 2,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def _queue(
    session_factory: sessionmaker[Session], template: str = "maintenance-triage", **fields: object
) -> str:
    spec = compile_requirement(TEMPLATES_BY_ID[template].requirement).spec
    values: dict[str, object] = {
        "agent_name": spec.agent.name,
        "spec_hash": spec_hash(spec),
        "spec": spec.model_dump(mode="json"),
        "status": "queued",
        "progress": 0.0,
        "stages": initial_stages(),
    }
    values.update(fields)
    with session_factory() as session:
        record = BuildRecord(**values)
        session.add(record)
        session.commit()
        return str(record.id)


def _load(session_factory: sessionmaker[Session], build_id: str) -> BuildRecord:
    with session_factory() as session:
        record = session.get(BuildRecord, uuid.UUID(build_id))
        assert record is not None
        _ = record.events
        return record


def test_successful_build_reports_parsed_metrics_and_signed_artifact(session_factory, tmp_path: Path) -> None:
    seed, _ = generate_key()
    sandbox = ScriptedSandbox()
    build_id = _queue(session_factory)
    status = execute_build(
        build_id,
        settings=_settings(tmp_path, signing_key=seed),
        sandbox=sandbox,
        session_factory=session_factory,
    )
    record = _load(session_factory, build_id)
    assert status == "succeeded", record.error
    assert [stage["status"] for stage in record.stages] == ["passed"] * 7 + ["skipped", "passed", "passed"]
    assert record.metrics["tests_passed"] == 2 and record.metrics["tests_total"] == 3
    assert record.metrics["test_coverage"] == 0.875
    assert record.metrics["adversarial_cases"] == 2
    assert record.report["package"]["signature"]["signed"] is True
    artifact = Path(record.artifact_path)
    verification = verify_package(artifact)
    assert verification["valid"] is True and verification["signature_valid"] is True
    assert verification["unlisted"] == [] and verification["missing"] == []
    with zipfile.ZipFile(artifact) as archive:
        names = archive.namelist()
    root = names[0].split("/")[0]
    for expected in (
        "src/agent/graph.py",
        "src/agent/state.py",
        "src/agent/prompts.py",
        "mcp/server.py",
        "tests/unit",
        "tests/integration",
        "tests/agent",
        "evals/dataset.json",
        "evals/graders.py",
        "Dockerfile",
        "docker-compose.yml",
        "pyproject.toml",
        ".env.example",
        "agent-spec.yaml",
        "architecture.md",
        "README.md",
        ".agentforge/eval-report.json",
        ".agentforge/provenance.json",
        ".agentforge/sbom.cdx.json",
    ):
        assert any(name.startswith(f"{root}/{expected}") for name in names), expected
    assert not any(".agentforge-out" in name for name in names)


def test_lint_failure_is_repaired_and_reverified(session_factory, tmp_path: Path) -> None:
    def touch_on_fix(workspace: Path, argv: list[str]) -> None:
        if "--fix" in argv:
            target = workspace / "src" / "agent" / "state.py"
            target.write_text(target.read_text() + "\n# fixed\n")

    sandbox = ScriptedSandbox(fail={"lint": 1}, on_command=touch_on_fix)
    build_id = _queue(session_factory)
    status = execute_build(
        build_id, settings=_settings(tmp_path), sandbox=sandbox, session_factory=session_factory
    )
    record = _load(session_factory, build_id)
    assert status == "succeeded", record.error
    repairs = record.report["repairs"]
    assert repairs[0]["strategy"].startswith("ruff") and repairs[0]["outcome"] == "changed"
    assert record.report["gates"]["quality"]["attempts"] == 2
    assert next(s for s in record.stages if s["key"] == "repair")["status"] == "passed"


def test_test_failure_without_llm_fails_with_evidence(session_factory, tmp_path: Path) -> None:
    sandbox = ScriptedSandbox(fail={"tests": 5})
    build_id = _queue(session_factory)
    status = execute_build(
        build_id, settings=_settings(tmp_path), sandbox=sandbox, session_factory=session_factory
    )
    record = _load(session_factory, build_id)
    assert status == "failed"
    assert record.artifact_path is None
    assert "1 of 2 tests failed" in record.error
    tests_gate = record.report["gates"]["tests"]
    assert tests_gate["status"] == "failed"
    assert any(case["outcome"] == "failed" for case in tests_gate["test_cases"])
    assert not list((tmp_path / "artifacts").glob("*.zip"))


def test_evaluation_targets_are_enforced(session_factory, tmp_path: Path) -> None:
    sandbox = ScriptedSandbox(fail={"evals": 5})
    build_id = _queue(session_factory)
    assert (
        execute_build(
            build_id,
            settings=_settings(tmp_path, repair_max_attempts=0),
            sandbox=sandbox,
            session_factory=session_factory,
        )
        == "failed"
    )
    record = _load(session_factory, build_id)
    assert record.report["gates"]["evaluation"]["evaluation"]["unsafe_actions"] == 1


def test_missing_sandbox_runtime_fails_clearly(session_factory, tmp_path: Path) -> None:
    build_id = _queue(session_factory)
    status = execute_build(
        build_id,
        settings=_settings(tmp_path),
        sandbox=ScriptedSandbox(available=False),
        session_factory=session_factory,
    )
    record = _load(session_factory, build_id)
    assert status == "failed"
    assert "sandbox runtime missing" in record.error
    assert next(s for s in record.stages if s["key"] == "quality")["status"] == "failed"


def test_cancelled_before_start(session_factory, tmp_path: Path) -> None:
    build_id = _queue(session_factory, cancel_requested=True)
    assert (
        execute_build(
            build_id, settings=_settings(tmp_path), sandbox=ScriptedSandbox(), session_factory=session_factory
        )
        == "cancelled"
    )


def test_cancel_during_gates(session_factory, tmp_path: Path) -> None:
    build_id = _queue(session_factory)

    def cancel_when_tests_start(workspace: Path, argv: list[str]) -> None:
        if "pytest" in " ".join(argv):
            with session_factory() as session:
                record = session.get(BuildRecord, uuid.UUID(build_id))
                record.cancel_requested = True
                session.commit()

    sandbox = ScriptedSandbox(on_command=cancel_when_tests_start)
    assert (
        execute_build(
            build_id, settings=_settings(tmp_path), sandbox=sandbox, session_factory=session_factory
        )
        == "cancelled"
    )
    record = _load(session_factory, build_id)
    assert record.artifact_path is None
    assert any(stage["status"] == "cancelled" for stage in record.stages)


def test_security_findings_block_packaging(
    session_factory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = pipeline.generate_repository

    def poisoned(spec, plan):  # type: ignore[no-untyped-def]
        repository = original(spec, plan)
        repository.files["src/agent/backdoor.py"] = "def run(payload):\n    return eval(payload)\n"
        return repository

    monkeypatch.setattr(pipeline, "generate_repository", poisoned)
    build_id = _queue(session_factory)
    status = execute_build(
        build_id, settings=_settings(tmp_path), sandbox=ScriptedSandbox(), session_factory=session_factory
    )
    record = _load(session_factory, build_id)
    assert status == "failed"
    assert any(f["rule_id"] == "AF-PY-001" for f in record.report["security"]["findings"])
    assert record.artifact_path is None


def test_tampered_spec_hash_is_rejected(session_factory, tmp_path: Path) -> None:
    build_id = _queue(session_factory)
    with session_factory() as session:
        record = session.get(BuildRecord, uuid.UUID(build_id))
        record.spec_hash = "0" * 64
        session.commit()
    assert (
        execute_build(
            build_id, settings=_settings(tmp_path), sandbox=ScriptedSandbox(), session_factory=session_factory
        )
        == "failed"
    )
    assert "does not match" in _load(session_factory, build_id).error


def test_terminal_builds_are_not_rerun(session_factory, tmp_path: Path) -> None:
    build_id = _queue(session_factory, status="succeeded")
    sandbox = ScriptedSandbox()
    assert (
        execute_build(
            build_id, settings=_settings(tmp_path), sandbox=sandbox, session_factory=session_factory
        )
        == "succeeded"
    )
    assert sandbox.calls == []
