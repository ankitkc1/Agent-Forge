"""Build report contracts: every number shown in the workbench comes from one of these."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.plan import ArchitecturePlan

GateStatus = Literal["passed", "failed", "error", "skipped", "warning"]
Severity = Literal["info", "low", "medium", "high", "critical"]


class CommandSummary(BaseModel):
    command: str
    exit_code: int
    duration_seconds: float
    timed_out: bool = False
    output_tail: str = ""


class TestCaseResult(BaseModel):
    id: str
    outcome: Literal["passed", "failed", "skipped", "error"]
    duration_seconds: float = 0.0
    message: str | None = None


class TestSummary(BaseModel):
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    duration_seconds: float = 0.0


class CoverageFile(BaseModel):
    path: str
    percent: float
    missing_lines: int


class CoverageSummary(BaseModel):
    percent: float = Field(ge=0, le=100)
    covered_lines: int
    total_lines: int
    files: list[CoverageFile] = Field(default_factory=list)


class EvalCaseResult(BaseModel):
    id: str
    category: str
    passed: bool
    details: list[str] = Field(default_factory=list)


class EvalSummary(BaseModel):
    mode: str
    model: str
    passed: bool
    task_success: float
    tool_accuracy: float
    unsafe_actions: int
    cases: int
    passed_cases: int
    thresholds: dict[str, float]
    by_category: dict[str, dict[str, int]] = Field(default_factory=dict)
    case_results: list[EvalCaseResult] = Field(default_factory=list)


class GateResult(BaseModel):
    name: str
    status: GateStatus
    attempts: int = 1
    duration_seconds: float = 0.0
    summary: str = ""
    commands: list[CommandSummary] = Field(default_factory=list)
    tests: TestSummary | None = None
    test_cases: list[TestCaseResult] = Field(default_factory=list)
    coverage: CoverageSummary | None = None
    evaluation: EvalSummary | None = None

    @property
    def ok(self) -> bool:
        return self.status in {"passed", "warning", "skipped"}


class RepairAttemptReport(BaseModel):
    number: int
    gate: str
    strategy: str
    outcome: Literal["changed", "unchanged", "rejected", "error"]
    changed_files: list[str] = Field(default_factory=list)
    detail: str = ""


class SecurityFinding(BaseModel):
    rule_id: str
    severity: Severity
    title: str
    path: str | None = None
    line: int | None = None
    detail: str = ""
    source: Literal["agentforge", "bandit"] = "agentforge"
    blocking: bool = False


class SecurityReport(BaseModel):
    status: Literal["passed", "failed"]
    summary: dict[str, int]
    findings: list[SecurityFinding]
    checks: list[str]
    files_scanned: int


class SignatureInfo(BaseModel):
    algorithm: str
    key_id: str
    signed: bool


class PackageReport(BaseModel):
    archive_sha256: str
    size_bytes: int
    files: int
    source_digest: str
    signature: SignatureInfo | None = None
    sbom_components: int = 0


class GenerationReport(BaseModel):
    files: int
    bytes: int
    formatted: bool
    notes: list[str] = Field(default_factory=list)


class BuildReport(BaseModel):
    schema_version: Literal["agentforge.build-report/v1"] = "agentforge.build-report/v1"
    build_id: str
    agent: str
    spec_hash: str
    agentforge_version: str
    sandbox: str | None = None
    plan: ArchitecturePlan | None = None
    generation: GenerationReport | None = None
    gates: dict[str, GateResult] = Field(default_factory=dict)
    repairs: list[RepairAttemptReport] = Field(default_factory=list)
    security: SecurityReport | None = None
    package: PackageReport | None = None
    timings: dict[str, float] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
