from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AgentIdentity(StrictModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    objective: str = Field(min_length=10, max_length=300)
    description: str = Field(min_length=10, max_length=800)


class ModelConfig(StrictModel):
    provider: Literal["local", "openai", "anthropic"]
    model: str = Field(min_length=2, max_length=100)
    temperature: float = Field(default=0.1, ge=0.0, le=1.0)


class ToolSpec(StrictModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    mode: Literal["read", "draft", "execute"]
    approval_required: bool = False


class RetrievalConfig(StrictModel):
    enabled: bool = True
    sources: tuple[str, ...] = ()
    citations_required: bool = False

    @field_validator("sources")
    @classmethod
    def unique_sources(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("retrieval sources must be unique")
        return value


class ExternalMessageGuardrail(StrictModel):
    approval_required: bool = True


class ToolExecutionGuardrail(StrictModel):
    allowlist_only: bool = True
    timeout_seconds: int = Field(default=30, ge=1, le=300)


class PromptInjectionGuardrail(StrictModel):
    action: Literal["block_and_log", "human_review"] = "block_and_log"


class Guardrails(StrictModel):
    external_messages: ExternalMessageGuardrail
    tool_execution: ToolExecutionGuardrail
    prompt_injection: PromptInjectionGuardrail


class MemoryConfig(StrictModel):
    type: Literal["postgres", "sqlite", "none"]
    namespace: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    pii_retention_days: int = Field(default=30, ge=0, le=365)


class EvaluationConfig(StrictModel):
    task_success_target: float = Field(default=0.9, ge=0.0, le=1.0)
    tool_accuracy_target: float = Field(default=0.95, ge=0.0, le=1.0)
    unsafe_action_target: int = Field(default=0, ge=0)
    adversarial_cases: int = Field(default=18, ge=1, le=500)


class AgentSpec(StrictModel):
    version: Literal["1.0"] = "1.0"
    agent: AgentIdentity
    model: ModelConfig
    tools: tuple[ToolSpec, ...] = Field(min_length=1, max_length=32)
    retrieval: RetrievalConfig
    workflow: tuple[str, ...] = Field(min_length=2, max_length=32)
    guardrails: Guardrails
    memory: MemoryConfig
    evaluation: EvaluationConfig

    @model_validator(mode="after")
    def enforce_safety_invariants(self) -> AgentSpec:
        if len(self.workflow) != len(set(self.workflow)):
            raise ValueError("workflow steps must be unique")
        if "execute" in self.workflow:
            if "human_approval" not in self.workflow:
                raise ValueError("executable workflows require a human_approval step")
            if self.workflow.index("human_approval") > self.workflow.index("execute"):
                raise ValueError("human_approval must occur before execute")
        if (
            any(tool.mode == "execute" for tool in self.tools)
            and not self.guardrails.external_messages.approval_required
        ):
            raise ValueError("executable tools require approval for external messages")
        if not self.guardrails.tool_execution.allowlist_only:
            raise ValueError("tool execution must be allowlist-only")
        return self


class CompileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requirement: str = Field(min_length=24, max_length=12_000)


class CompileResponse(BaseModel):
    spec: AgentSpec
    spec_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    warnings: list[str] = Field(default_factory=list)
