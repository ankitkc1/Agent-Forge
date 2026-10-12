from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.compiler import CompilationError, compile_requirement, spec_hash
from app.compiler.domains import ALL_PACKS
from app.compiler.templates import TEMPLATES
from app.compiler.validation import validate_document
from app.core.config import get_settings
from app.core.security import CurrentPrincipal
from app.llm.client import LLMError, build_llm
from app.planner.architecture import plan_architecture
from app.schemas.agent_spec import AgentSpec, CompileRequest, CompileResponse
from app.schemas.plan import ArchitecturePlan

router = APIRouter(prefix="/specs", tags=["specs"])


class ValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document: str | None = Field(default=None, max_length=256_000, description="YAML or JSON text")
    spec: dict[str, Any] | None = None


class SpecIssueModel(BaseModel):
    loc: str
    message: str


class ValidateResponse(BaseModel):
    valid: bool
    spec: AgentSpec | None = None
    spec_hash: str | None = None
    errors: list[SpecIssueModel] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    plan: ArchitecturePlan | None = None


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spec: AgentSpec


@router.post("/compile", response_model=CompileResponse)
def compile_spec(payload: CompileRequest, principal: CurrentPrincipal) -> CompileResponse:
    settings = get_settings()
    if len(payload.requirement) > settings.max_requirement_chars:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "requirement too long")
    engine = payload.options.engine
    llm = None
    if engine in {"auto", "llm"} and settings.llm_provider != "none":
        try:
            llm = build_llm(settings)
        except LLMError as exc:
            if engine == "llm":
                raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    if engine == "llm" and llm is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "the LLM compiler is not configured on this server")
    try:
        result = compile_requirement(payload.requirement, engine=engine, llm=llm)
    except CompilationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return CompileResponse(
        spec=result.spec, spec_hash=result.spec_hash, warnings=result.warnings, analysis=result.analysis
    )


@router.post("/validate", response_model=ValidateResponse)
def validate_spec(payload: ValidateRequest, principal: CurrentPrincipal) -> ValidateResponse:
    if (payload.document is None) == (payload.spec is None):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "provide exactly one of 'document' or 'spec'")
    outcome = validate_document(payload.document if payload.document is not None else payload.spec)
    if not outcome.valid or outcome.spec is None:
        return ValidateResponse(
            valid=False, errors=[SpecIssueModel(**issue.as_dict()) for issue in outcome.errors]
        )
    plan = plan_architecture(outcome.spec)
    return ValidateResponse(
        valid=True,
        spec=outcome.spec,
        spec_hash=spec_hash(outcome.spec),
        warnings=outcome.warnings,
        plan=plan,
    )


@router.post("/plan", response_model=ArchitecturePlan)
def plan_spec(payload: PlanRequest, principal: CurrentPrincipal) -> ArchitecturePlan:
    return plan_architecture(payload.spec)


@router.get("/templates")
def list_templates(principal: CurrentPrincipal) -> list[dict[str, str]]:
    return [template.as_dict() for template in TEMPLATES]


@router.get("/domains")
def list_domains(principal: CurrentPrincipal) -> list[dict[str, Any]]:
    return [
        {
            "key": pack.key,
            "title": pack.title,
            "labels": [label.name for label in pack.labels],
            "tools": [{"name": tool.name, "mode": tool.mode} for tool in pack.tools],
            "sources": [source.name for source in pack.sources],
        }
        for pack in ALL_PACKS
    ]


@router.get("/schema")
def spec_schema() -> dict[str, Any]:
    return AgentSpec.model_json_schema()
