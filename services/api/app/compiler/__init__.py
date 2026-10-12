"""Requirement compiler: untrusted natural language in, validated and hashed AgentSpec out."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Literal

import structlog

from app.compiler.analyzer import analyze_requirement
from app.compiler.assemble import assemble_spec
from app.compiler.validation import lint_spec
from app.schemas.agent_spec import AgentSpec, AnalysisSummary

logger = structlog.get_logger(__name__)

Engine = Literal["auto", "heuristic", "llm"]


class CompilationError(ValueError):
    pass


@dataclass
class CompilationResult:
    spec: AgentSpec
    warnings: list[str]
    analysis: AnalysisSummary
    inferences: list[str] = field(default_factory=list)

    @property
    def spec_hash(self) -> str:
        return spec_hash(self.spec)


def canonical_spec(spec: AgentSpec) -> bytes:
    return json.dumps(spec.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()


def spec_hash(spec: AgentSpec) -> str:
    return hashlib.sha256(canonical_spec(spec)).hexdigest()


def requirement_digest(requirement: str) -> str:
    return hashlib.sha256(" ".join(requirement.split()).encode()).hexdigest()


def compile_requirement(
    requirement: str,
    *,
    engine: Engine = "heuristic",
    llm: object | None = None,
) -> CompilationResult:
    """Compile a requirement. ``engine='auto'`` uses the LLM when one is supplied."""
    analysis = analyze_requirement(requirement)
    digest = requirement_digest(requirement)
    warnings: list[str] = []

    if engine in {"auto", "llm"} and llm is not None:
        from app.compiler.llm_analyzer import analyze_with_llm
        from app.llm.client import LLMError

        try:
            spec, llm_warnings = analyze_with_llm(requirement, llm, analysis.pack.key)  # type: ignore[arg-type]
        except (LLMError, ValueError, TypeError, KeyError, AttributeError) as exc:
            # Any defect in model output degrades to the deterministic analyzer, never to a 500.
            logger.warning("llm_compile_fallback", error=str(exc)[:300])
            warnings.append(
                "The LLM analyzer could not produce a valid specification; the deterministic "
                "analyzer was used instead."
            )
        else:
            warnings.extend(llm_warnings)
            warnings.extend(lint_spec(spec))
            return CompilationResult(
                spec=spec,
                warnings=warnings,
                analysis=AnalysisSummary(
                    engine="llm",
                    model=getattr(llm, "model", None),
                    domain=spec.agent.domain,
                    confidence=0.8,
                    assumptions=[],
                    requirement_sha256=digest,
                ),
            )
    elif engine == "llm":
        raise CompilationError("the LLM compiler engine is not configured")

    try:
        spec = assemble_spec(analysis)
    except ValueError as exc:  # pragma: no cover - indicates a domain pack defect
        raise CompilationError(f"compiled specification failed validation: {exc}") from exc
    warnings.extend(analysis.warnings)
    warnings.extend(lint_spec(spec))
    return CompilationResult(
        spec=spec,
        warnings=warnings,
        analysis=AnalysisSummary(
            engine="heuristic",
            domain=analysis.pack.key,
            confidence=analysis.confidence,
            assumptions=analysis.assumptions,
            inferences=analysis.inferences,
            requirement_sha256=digest,
        ),
        inferences=analysis.inferences,
    )


__all__ = [
    "CompilationError",
    "CompilationResult",
    "canonical_spec",
    "compile_requirement",
    "requirement_digest",
    "spec_hash",
]
