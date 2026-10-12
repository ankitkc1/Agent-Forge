"""Build pipeline orchestrator.

Stages (persisted after every transition so the workbench can follow progress):

  analysis -> architecture -> risk -> codegen -> quality -> tests -> evaluation -> repair
           -> security -> package

The verification gates run in the sandbox. When one fails, the repair agent gets a bounded number
of attempts; every gate is then re-run from the start so a fix cannot regress an earlier gate.
Nothing in this module invents a number: metrics come from the sandbox's JUnit, coverage and
evaluation reports, and the artifact is only written after every blocking gate has passed.
"""

from __future__ import annotations

import json
import shutil
import socket
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app import __version__
from app.compiler import spec_hash
from app.compiler.validation import lint_spec
from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.generator.engine import GENERATOR_SCHEMA, RUNTIME_LOCKS, generate_repository
from app.llm.client import LLMError, build_llm
from app.models.build import BuildEvent, BuildRecord
from app.packaging.archive import build_package, provenance_statement, sha256_bytes, source_digest
from app.packaging.signing import load_signer
from app.planner.architecture import plan_architecture
from app.sandbox import (
    OUTPUT_DIR,
    SandboxCancelledError,
    SandboxError,
    SandboxRunner,
    SandboxUnavailableError,
    build_sandbox,
)
from app.schemas.agent_spec import AgentSpec
from app.schemas.report import BuildReport, GateResult, GenerationReport, PackageReport, SignatureInfo
from app.security.sarif import to_sarif
from app.security.scanner import scan_repository
from app.verification.gates import (
    BANDIT_REPORT,
    COVERAGE,
    EVAL_REPORT,
    JUNIT,
    run_bandit,
    run_evaluation_gate,
    run_quality_gate,
    run_test_gate,
)
from app.verification.repair import RepairAgent

logger = structlog.get_logger(__name__)

STAGE_DEFINITIONS: tuple[tuple[str, str], ...] = (
    ("analysis", "Spec analysis"),
    ("architecture", "Architecture planner"),
    ("risk", "Risk analysis"),
    ("codegen", "Code generation"),
    ("quality", "Static checks"),
    ("tests", "Sandbox tests"),
    ("evaluation", "Evaluation suite"),
    ("repair", "Repair agent"),
    ("security", "Security validation"),
    ("package", "Signed packaging"),
)
STAGE_INDEX = {key: index for index, (key, _) in enumerate(STAGE_DEFINITIONS)}
GATE_STAGES = ("quality", "tests", "evaluation")
SKIP_PARTS = {OUTPUT_DIR, ".home", ".tmp", "__pycache__", ".pytest_cache", ".ruff_cache", "var"}
SKIP_FILES = {".coverage", "coverage.json", "junit.xml", "eval-report.json"}


class BuildCancelledError(Exception):
    pass


class PipelineFailure(Exception):
    def __init__(self, stage: str, message: str) -> None:
        super().__init__(message)
        self.stage = stage


def initial_stages() -> list[dict[str, Any]]:
    return [
        {
            "key": key,
            "name": name,
            "status": "pending",
            "progress": 0.0,
            "started_at": None,
            "finished_at": None,
            "summary": None,
            "attempts": 0,
        }
        for key, name in STAGE_DEFINITIONS
    ]


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class BuildRecorder:
    """Persists stage transitions, events and the report; checks for cancellation."""

    session: Session
    record: BuildRecord

    def _commit(self) -> None:
        self.session.add(self.record)
        self.session.commit()

    def event(self, message: str, *, level: str = "info", stage: str | None = None) -> None:
        self.session.add(
            BuildEvent(build_id=self.record.id, level=level, stage=stage, message=message[:4000])
        )
        self.session.commit()

    def stage(self, key: str, status: str, summary: str | None = None) -> None:
        stages = [dict(stage) for stage in self.record.stages]
        stage = stages[STAGE_INDEX[key]]
        stage["status"] = status
        if status == "running":
            stage["started_at"] = _now().isoformat()
            stage["finished_at"] = None
            stage["attempts"] = int(stage.get("attempts", 0)) + 1
            stage["progress"] = 25.0
            self.record.current_stage = str(stage["name"])
        else:
            stage["finished_at"] = _now().isoformat()
            stage["progress"] = 100.0 if status != "pending" else 0.0
        if summary is not None:
            stage["summary"] = summary[:500]
        self.record.stages = stages
        done = sum(item["status"] in {"passed", "skipped"} for item in stages)
        self.record.progress = round(done / len(stages) * 100, 1)
        self._commit()
        if status in {"passed", "failed", "skipped"}:
            level = {"passed": "success", "failed": "error", "skipped": "info"}[status]
            self.event(f"{stage['name']}: {summary or status}", level=level, stage=key)

    def reset_stage(self, key: str) -> None:
        stages = [dict(stage) for stage in self.record.stages]
        stages[STAGE_INDEX[key]].update(status="pending", progress=0.0, finished_at=None)
        self.record.stages = stages
        self._commit()

    def cancelled(self) -> bool:
        self.session.refresh(self.record, attribute_names=["cancel_requested"])
        return bool(self.record.cancel_requested)

    def check_cancel(self) -> None:
        if self.cancelled():
            raise BuildCancelledError()

    def save_report(self, report: BuildReport) -> None:
        self.record.report = json.loads(report.model_dump_json())
        self._commit()


def _write_files(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        target = root.joinpath(*relative.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.resolve().is_relative_to(root.resolve()):
            raise PipelineFailure("codegen", f"generated path escapes the workspace: {relative}")
        target.write_text(content, encoding="utf-8", newline="\n")


def _collect_source(root: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in SKIP_PARTS for part in relative.parts) or path.name in SKIP_FILES:
            continue
        files[relative.as_posix()] = path.read_bytes()
    return files


def _metrics(report: BuildReport, files: int) -> dict[str, Any]:
    tests = report.gates["tests"]
    evaluation = report.gates["evaluation"].evaluation
    assert tests.tests is not None and evaluation is not None
    adversarial = evaluation.by_category.get("adversarial", {}).get("cases", 0)
    security = report.security
    return {
        "task_success": evaluation.task_success,
        "tool_accuracy": evaluation.tool_accuracy,
        "unsafe_actions": evaluation.unsafe_actions,
        "test_coverage": round((tests.coverage.percent if tests.coverage else 0.0) / 100, 4),
        "tests_passed": tests.tests.passed,
        "tests_total": tests.tests.total,
        "tests_failed": tests.tests.failed + tests.tests.errors,
        "eval_cases": evaluation.cases,
        "adversarial_cases": adversarial,
        "security_findings": sum(
            count for severity, count in (security.summary if security else {}).items() if severity != "info"
        ),
        "repair_attempts": len(report.repairs),
        "files": files,
        "eval_mode": evaluation.mode,
    }


def execute_build(
    build_id: str,
    *,
    settings: Settings | None = None,
    sandbox: SandboxRunner | None = None,
    session_factory: sessionmaker[Session] | Callable[[], Session] = SessionLocal,
) -> str:
    """Run the pipeline for ``build_id``; returns the terminal status."""
    settings = settings or get_settings()
    parsed_id = uuid.UUID(build_id)
    with session_factory() as session:
        record = session.scalar(select(BuildRecord).where(BuildRecord.id == parsed_id))
        if record is None:
            raise LookupError(f"build not found: {build_id}")
        if record.terminal:
            return record.status
        recorder = BuildRecorder(session, record)
        if record.cancel_requested:
            return _finish(recorder, "cancelled", "Build cancelled before it started.")
        if record.status == "running":
            recorder.event("Worker restarted this build after an interruption.", level="warning")
            record.stages = initial_stages()
        record.status = "running"
        record.attempt = int(record.attempt or 0) + 1
        record.started_at = record.started_at or _now()
        record.error = None
        record.agentforge_version = __version__
        session.commit()
        recorder.event(f"Build started by AgentForge {__version__} (attempt {record.attempt}).")
        workspace = settings.workspace_dir / str(record.id)
        try:
            status = _run(recorder, record, settings, sandbox, workspace)
        except OperationalError:
            session.rollback()
            raise
        finally:
            shutil.rmtree(workspace, ignore_errors=True)
        return status


def _finish(recorder: BuildRecorder, status: str, message: str, *, level: str = "info") -> str:
    record = recorder.record
    record.status = status
    record.finished_at = _now()
    record.current_stage = {"succeeded": "Complete", "cancelled": "Cancelled"}.get(
        status, record.current_stage
    )
    if status == "succeeded":
        record.progress = 100.0
    if status == "cancelled":
        record.stages = [
            {**stage, "status": "cancelled"} if stage["status"] in {"pending", "running"} else stage
            for stage in record.stages
        ]
    recorder.session.add(record)
    recorder.session.commit()
    recorder.event(message, level=level)
    logger.info("build_finished", build_id=str(record.id), status=status)
    return status


def _run(
    recorder: BuildRecorder,
    record: BuildRecord,
    settings: Settings,
    sandbox: SandboxRunner | None,
    workspace: Path,
) -> str:
    report = BuildReport(
        build_id=str(record.id),
        agent=record.agent_name,
        spec_hash=record.spec_hash,
        agentforge_version=__version__,
    )
    current = "analysis"
    timings: dict[str, float] = {}

    def timed(stage: str) -> Callable[[], None]:
        started = _now()

        def stop() -> None:
            timings[stage] = round((_now() - started).total_seconds(), 3)
            report.timings = dict(timings)

        return stop

    try:
        # -- analysis --------------------------------------------------------------------------
        recorder.stage("analysis", "running")
        stop = timed("analysis")
        spec = AgentSpec.model_validate(record.spec)
        if spec_hash(spec) != record.spec_hash:
            raise PipelineFailure("analysis", "stored specification does not match its SHA-256 hash")
        warnings = lint_spec(spec)
        for warning in warnings:
            recorder.event(warning, level="warning", stage="analysis")
        stop()
        recorder.stage("analysis", "passed", f"AgentSpec v{spec.version} valid · {len(warnings)} warning(s)")
        recorder.check_cancel()

        # -- architecture ------------------------------------------------------------------------
        current = "architecture"
        recorder.stage("architecture", "running")
        stop = timed("architecture")
        plan = plan_architecture(spec)
        report.plan = plan
        failed_checks = [check for check in plan.checks if not check.passed]
        for check in plan.checks:
            recorder.event(
                f"{'✓' if check.passed else '✗'} {check.title}: {check.detail}",
                stage="architecture",
                level="info" if check.passed else "error",
            )
        stop()
        if failed_checks:
            raise PipelineFailure("architecture", f"{len(failed_checks)} topology check(s) failed")
        recorder.stage(
            "architecture",
            "passed",
            f"{len(plan.nodes)} nodes · {len(plan.edges)} edges · {len(plan.checks)} properties verified",
        )
        recorder.save_report(report)

        # -- risk ---------------------------------------------------------------------------------
        current = "risk"
        recorder.stage("risk", "running")
        stop = timed("risk")
        for finding in plan.risk.findings:
            if finding.status != "mitigated":
                recorder.event(
                    f"[{finding.severity}] {finding.title} — {finding.mitigation}",
                    stage="risk",
                    level="warning",
                )
        stop()
        if plan.risk.blocking:
            raise PipelineFailure("risk", "blocking risk findings must be resolved in the specification")
        mitigated = sum(1 for finding in plan.risk.findings if finding.status == "mitigated")
        recorder.stage(
            "risk",
            "passed",
            f"risk level {plan.risk.level} · {mitigated}/{len(plan.risk.findings)} findings mitigated",
        )
        recorder.check_cancel()

        # -- codegen ------------------------------------------------------------------------------
        current = "codegen"
        recorder.stage("codegen", "running")
        stop = timed("codegen")
        generated = generate_repository(spec, plan)
        repo = workspace / "repo"
        if workspace.exists():
            shutil.rmtree(workspace)
        repo.mkdir(parents=True)
        _write_files(repo, generated.files)
        report.generation = GenerationReport(
            files=len(generated.files),
            bytes=generated.total_bytes,
            formatted=generated.formatted,
            notes=generated.notes,
        )
        for note in generated.notes:
            recorder.event(note, level="warning", stage="codegen")
        stop()
        recorder.stage(
            "codegen", "passed", f"{len(generated.files)} files · {generated.total_bytes // 1024} KB rendered"
        )
        recorder.save_report(report)
        recorder.check_cancel()

        # -- sandbox gates with bounded repair ----------------------------------------------------
        runner = sandbox or build_sandbox(settings)
        available, detail = runner.check()
        report.sandbox = runner.name
        if not available:
            current = "quality"
            raise SandboxUnavailableError(detail)
        recorder.event(detail, stage="quality")
        llm = None
        if settings.repair_use_llm:
            try:
                llm = build_llm(settings)
            except LLMError as exc:
                recorder.event(f"LLM repair disabled: {exc}", level="warning", stage="repair")
        repair_agent = RepairAgent(runner, llm)
        attempt = 0
        cancel_check = recorder.cancelled
        while True:
            failure: GateResult | None = None
            for gate in GATE_STAGES:
                current = gate
                recorder.stage(gate, "running")
                stop = timed(gate)
                if gate == "quality":
                    result = run_quality_gate(runner, repo, should_cancel=cancel_check)
                elif gate == "tests":
                    result = run_test_gate(runner, repo, should_cancel=cancel_check)
                else:
                    result = run_evaluation_gate(
                        runner, repo, enforce=settings.enforce_eval_targets, should_cancel=cancel_check
                    )
                stop()
                result.attempts = attempt + 1
                report.gates[gate] = result
                recorder.save_report(report)
                if result.ok:
                    recorder.stage(gate, "passed", result.summary)
                    if result.status == "warning":
                        recorder.event(result.summary, level="warning", stage=gate)
                    continue
                recorder.stage(gate, "failed", result.summary)
                tail = result.commands[-1].output_tail if result.commands else ""
                if tail:
                    recorder.event(tail[-1500:], level="error", stage=gate)
                failure = result
                break
            if failure is None:
                break
            if attempt >= settings.repair_max_attempts:
                raise PipelineFailure(failure.name, f"{failure.summary} (after {attempt} repair attempt(s))")
            attempt += 1
            current = "repair"
            recorder.stage("repair", "running")
            stop = timed("repair")
            repair = repair_agent.repair(repo, failure, attempt)
            stop()
            report.repairs.append(repair)
            recorder.save_report(report)
            recorder.event(
                f"Repair attempt {attempt} ({repair.strategy}): {repair.outcome} — {', '.join(repair.changed_files) or 'no files changed'}",
                level="warning" if repair.outcome == "changed" else "error",
                stage="repair",
            )
            if repair.outcome != "changed":
                raise PipelineFailure(failure.name, f"{failure.summary}; repair could not make progress")
            for gate in GATE_STAGES:
                recorder.reset_stage(gate)
            recorder.check_cancel()
        if report.repairs:
            recorder.stage("repair", "passed", f"{len(report.repairs)} repair(s) applied and re-verified")
        else:
            recorder.stage("repair", "skipped", "No repairs required")
        recorder.check_cancel()

        # -- security -----------------------------------------------------------------------------
        current = "security"
        recorder.stage("security", "running")
        stop = timed("security")
        bandit_findings = None
        if settings.run_bandit:
            bandit_findings, _ = run_bandit(runner, repo, should_cancel=cancel_check)
        source = _collect_source(repo)
        text_files = {path: content.decode("utf-8", errors="replace") for path, content in source.items()}
        security = scan_repository(text_files, extra=bandit_findings)
        report.security = security
        stop()
        recorder.save_report(report)
        blocking = [finding for finding in security.findings if finding.blocking]
        for finding in security.findings[:25]:
            location = f" ({finding.path}:{finding.line})" if finding.path and finding.line else ""
            recorder.event(
                f"[{finding.severity}] {finding.rule_id} {finding.title}{location}",
                level="error" if finding.blocking else "warning",
                stage="security",
            )
        if blocking:
            raise PipelineFailure("security", f"{len(blocking)} blocking security finding(s)")
        counts = (
            ", ".join(f"{count} {severity}" for severity, count in security.summary.items() if count)
            or "no findings"
        )
        recorder.stage("security", "passed", f"{security.files_scanned} files scanned · {counts}")
        recorder.check_cancel()

        # -- package ------------------------------------------------------------------------------
        current = "package"
        recorder.stage("package", "running")
        stop = timed("package")
        signer = load_signer(
            settings.signing_key.get_secret_value() if settings.signing_key else None, settings.signing_key_id
        )
        if signer is None:
            recorder.event(
                "No AGENTFORGE_SIGNING_KEY configured; the manifest is hashed but unsigned.",
                level="warning",
                stage="package",
            )
        evidence: dict[str, bytes] = {}
        for name, path in (
            ("junit.xml", JUNIT),
            ("coverage.json", COVERAGE),
            ("eval-report.json", EVAL_REPORT),
            ("bandit.json", BANDIT_REPORT),
        ):
            artefact = repo / path
            if artefact.is_file():
                evidence[name] = artefact.read_bytes()
        evidence["security-report.json"] = security.model_dump_json(indent=2).encode()
        evidence["security-report.sarif"] = json.dumps(
            to_sarif(security, tool_version=__version__), indent=2
        ).encode()
        package_name = generated.files["pyproject.toml"].split('name = "', 1)[1].split('"', 1)[0]
        lock_digest = sha256_bytes((RUNTIME_LOCKS / "requirements-dev.lock").read_bytes())
        report_snapshot = report.model_copy(deep=True)
        evidence["build-report.json"] = report_snapshot.model_dump_json(indent=2).encode()
        provenance = provenance_statement(
            package=package_name,
            digest=source_digest(source),
            build_id=str(record.id),
            spec_hash=record.spec_hash,
            agent=record.agent_name,
            agentforge_version=__version__,
            generator=GENERATOR_SCHEMA,
            sandbox=runner.name,
            lock_digest=lock_digest,
            started_at=record.started_at or _now(),
            builder_id=f"agentforge://{socket.gethostname()}",
        )
        destination = settings.artifact_root / f"{record.id}.zip"
        packaged = build_package(
            destination=destination,
            package=package_name,
            source_files=source,
            evidence=evidence,
            signer=signer,
            sbom_inputs={
                "requirements.lock": source["requirements.lock"].decode(),
                "requirements-dev.lock": source["requirements-dev.lock"].decode(),
            },
            provenance=provenance,
        )
        report.package = PackageReport(
            archive_sha256=packaged.sha256,
            size_bytes=packaged.size_bytes,
            files=packaged.files,
            source_digest=packaged.source_digest,
            signature=SignatureInfo(algorithm="ed25519", key_id=packaged.key_id or "", signed=packaged.signed)
            if packaged.signed
            else None,
            sbom_components=packaged.sbom_components,
        )
        stop()
        record.artifact_path = str(destination)
        record.artifact_sha256 = packaged.sha256
        record.artifact_size = packaged.size_bytes
        record.metrics = _metrics(report, len(source))
        recorder.save_report(report)
        recorder.stage(
            "package",
            "passed",
            f"{packaged.files} files · {packaged.size_bytes // 1024} KB · sha256 {packaged.sha256[:12]}"
            + (" · signed" if packaged.signed else " · unsigned"),
        )
        return _finish(recorder, "succeeded", "Build complete: every blocking gate passed.", level="success")
    except BuildCancelledError:
        recorder.save_report(report)
        return _finish(recorder, "cancelled", "Build cancelled by request.", level="warning")
    except SandboxCancelledError:
        recorder.save_report(report)
        return _finish(
            recorder, "cancelled", "Build cancelled while the sandbox was running.", level="warning"
        )
    except (PipelineFailure, SandboxUnavailableError, SandboxError, ValueError) as exc:
        stage = getattr(exc, "stage", current)
        recorder.stage(stage, "failed", str(exc)[:500])
        record.error = str(exc)[:2000]
        recorder.save_report(report)
        logger.warning("build_failed", build_id=str(record.id), stage=stage, error=str(exc)[:500])
        return _finish(recorder, "failed", f"Build failed at {stage}: {exc}", level="error")
    except OperationalError:
        raise
    except Exception as exc:
        logger.exception("build_crashed", build_id=str(record.id))
        recorder.session.rollback()
        record.error = f"internal error during {current}: {type(exc).__name__}"
        try:
            recorder.stage(current, "failed", record.error)
            recorder.save_report(report)
        except Exception:  # pragma: no cover - best effort while failing
            recorder.session.rollback()
        return _finish(
            recorder,
            "failed",
            f"Build failed unexpectedly at {current} ({type(exc).__name__}).",
            level="error",
        )
