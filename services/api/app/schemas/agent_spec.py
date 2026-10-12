"""AgentSpec v1 — the only contract allowed to cross into code generation.

The specification is declarative: it states *what* the agent is allowed to do (tools and their
side-effect modes), *how* work flows (typed workflow steps), and *which* controls apply
(guardrails, memory retention, evaluation targets). The planner derives the graph topology from
it and the generator renders source code from it. Free-text fields are treated strictly as data:
they are length-limited here and escaped by the generator for every output context.

Older v1 documents that used a flat list of workflow step names or plain source names are
upgraded transparently by ``_upgrade_legacy_document``.
"""

from __future__ import annotations

import keyword
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

IDENTIFIER = r"^[a-z][a-z0-9_]{1,63}$"
_IDENTIFIER_RE = re.compile(IDENTIFIER)
_HINT_RE = re.compile(r"^[a-z0-9][a-z0-9 '\-]{0,39}$")

StepKind = Literal[
    "classify",
    "assess",
    "retrieve",
    "lookup",
    "analyze",
    "draft",
    "safety_check",
    "verify",
    "human_approval",
    "execute",
    "respond",
]
ToolMode = Literal["read", "draft", "execute"]
ParameterType = Literal["string", "integer", "number", "boolean"]

STEP_KINDS: tuple[str, ...] = (
    "classify",
    "assess",
    "retrieve",
    "lookup",
    "analyze",
    "draft",
    "safety_check",
    "verify",
    "human_approval",
    "execute",
    "respond",
)
DEFAULT_SEVERITY_LEVELS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("low", ("question", "whenever", "minor", "cosmetic", "routine")),
    ("medium", ("soon", "issue", "problem", "broken", "not working")),
    ("high", ("urgent", "asap", "outage", "blocked", "today")),
    ("critical", ("emergency", "danger", "fire", "flood", "injury", "security breach")),
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# Names that would collide with Python keywords or with modules/attributes of the generated code.
RESERVED_TOOL_NAMES = frozenset({"base", "registry", "catalog", "backends"})
RESERVED_STEP_IDS = frozenset({"guard_input", "finalize", "runtime", "start", "end"})
RESERVED_PARAMETER_NAMES = frozenset(
    {"json", "dict", "copy", "schema", "validate", "construct", "fields", "parse_obj", "parse_raw"}
)


def _not_keyword(value: str, what: str) -> str:
    if keyword.iskeyword(value) or keyword.issoftkeyword(value):
        raise ValueError(f"{what} '{value}' is a Python keyword")
    return value


class AgentIdentity(StrictModel):
    name: str = Field(pattern=IDENTIFIER, description="snake_case identifier of the agent")
    domain: str = Field(default="general", pattern=IDENTIFIER)
    objective: str = Field(min_length=10, max_length=300)
    description: str = Field(min_length=10, max_length=1200)
    constraints: tuple[str, ...] = Field(default=(), max_length=8)

    @field_validator("constraints")
    @classmethod
    def bounded_constraints(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(" ".join(item.split()) for item in value)
        for item in cleaned:
            if not 3 <= len(item) <= 240:
                raise ValueError("each constraint must be 3-240 characters")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("constraints must be unique")
        return cleaned


class ModelConfig(StrictModel):
    provider: Literal["local", "openai", "anthropic"]
    model: str = Field(min_length=2, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/\-]*$")
    temperature: float = Field(default=0.1, ge=0.0, le=1.0)
    max_output_tokens: int = Field(default=1024, ge=64, le=32_768)


class ToolParameter(StrictModel):
    name: str = Field(pattern=IDENTIFIER)
    type: ParameterType = "string"
    description: str = Field(default="", max_length=300)
    required: bool = True

    @field_validator("name")
    @classmethod
    def usable_field_name(cls, value: str) -> str:
        if value in RESERVED_PARAMETER_NAMES or value.startswith("model_"):
            raise ValueError(f"input name '{value}' is reserved")
        return _not_keyword(value, "input name")


class ToolSpec(StrictModel):
    name: str = Field(pattern=IDENTIFIER)
    description: str = Field(default="", max_length=400)
    mode: ToolMode
    approval_required: bool = False
    timeout_seconds: int | None = Field(default=None, ge=1, le=300)
    inputs: tuple[ToolParameter, ...] = Field(default=(), max_length=16)

    @field_validator("name")
    @classmethod
    def usable_tool_name(cls, value: str) -> str:
        if value in RESERVED_TOOL_NAMES:
            raise ValueError(f"tool name '{value}' is reserved")
        return _not_keyword(value, "tool name")

    @field_validator("inputs")
    @classmethod
    def unique_inputs(cls, value: tuple[ToolParameter, ...]) -> tuple[ToolParameter, ...]:
        names = [parameter.name for parameter in value]
        if len(names) != len(set(names)):
            raise ValueError("tool input names must be unique")
        return value

    @model_validator(mode="after")
    def execute_tools_require_approval(self) -> ToolSpec:
        if self.mode == "execute" and not self.approval_required:
            raise ValueError(f"tool '{self.name}' has mode 'execute' and must set approval_required: true")
        return self

    @property
    def has_side_effects(self) -> bool:
        return self.mode != "read"


class SourceSpec(StrictModel):
    name: str = Field(pattern=IDENTIFIER)
    description: str = Field(default="", max_length=300)


class RetrievalConfig(StrictModel):
    enabled: bool = True
    sources: tuple[SourceSpec, ...] = Field(default=(), max_length=16)
    top_k: int = Field(default=4, ge=1, le=20)
    min_score: float = Field(default=0.05, ge=0.0, le=1.0)
    citations_required: bool = False
    chunk_size: int = Field(default=800, ge=200, le=4000)
    chunk_overlap: int = Field(default=120, ge=0, le=1000)
    embeddings: Literal["hashing", "openai", "ollama"] = "hashing"
    store: Literal["memory", "pgvector"] = "memory"

    @field_validator("sources", mode="before")
    @classmethod
    def upgrade_plain_sources(cls, value: Any) -> Any:
        if isinstance(value, list | tuple):
            return [{"name": item} if isinstance(item, str) else item for item in value]
        return value

    @field_validator("sources")
    @classmethod
    def unique_sources(cls, value: tuple[SourceSpec, ...]) -> tuple[SourceSpec, ...]:
        names = [source.name for source in value]
        if len(names) != len(set(names)):
            raise ValueError("retrieval sources must be unique")
        return value

    @model_validator(mode="after")
    def coherent(self) -> RetrievalConfig:
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        if self.enabled and not self.sources:
            raise ValueError("retrieval is enabled but no sources are declared")
        if self.citations_required and not self.enabled:
            raise ValueError("citations_required needs retrieval to be enabled")
        return self

    @property
    def source_names(self) -> tuple[str, ...]:
        return tuple(source.name for source in self.sources)


class LabelSpec(StrictModel):
    name: str = Field(pattern=IDENTIFIER)
    description: str = Field(default="", max_length=200)
    hints: tuple[str, ...] = Field(default=(), max_length=24)

    @field_validator("hints")
    @classmethod
    def normalized_hints(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned: list[str] = []
        for hint in value:
            normalized = " ".join(hint.casefold().split())
            if not _HINT_RE.fullmatch(normalized):
                raise ValueError(
                    f"hint '{hint}' must be 1-40 chars of lowercase letters, digits, spaces, "
                    "apostrophes or hyphens"
                )
            if normalized not in cleaned:
                cleaned.append(normalized)
        return tuple(cleaned)


class WorkflowStep(StrictModel):
    id: str = Field(pattern=IDENTIFIER)
    kind: StepKind
    description: str = Field(default="", max_length=300)
    tools: tuple[str, ...] = Field(default=(), max_length=16)
    sources: tuple[str, ...] = Field(default=(), max_length=16)
    labels: tuple[LabelSpec, ...] = Field(default=(), max_length=12)
    dimension: str | None = Field(default=None, pattern=IDENTIFIER)
    review: Literal["when_required", "always"] | None = None

    @field_validator("id")
    @classmethod
    def usable_step_id(cls, value: str) -> str:
        if value in RESERVED_STEP_IDS:
            raise ValueError(f"step id '{value}' is reserved by the runtime")
        return _not_keyword(value, "step id")

    @field_validator("labels", mode="before")
    @classmethod
    def upgrade_plain_labels(cls, value: Any) -> Any:
        if isinstance(value, list | tuple):
            return [{"name": item} if isinstance(item, str) else item for item in value]
        return value

    @model_validator(mode="after")
    def kind_specific_fields(self) -> WorkflowStep:
        names = [label.name for label in self.labels]
        if len(names) != len(set(names)):
            raise ValueError(f"step '{self.id}' has duplicate labels")
        if len(self.tools) != len(set(self.tools)):
            raise ValueError(f"step '{self.id}' lists a tool more than once")
        if self.kind in {"classify", "assess"} and len(self.labels) < 2:
            raise ValueError(f"{self.kind} step '{self.id}' needs at least two labels")
        if self.kind not in {"classify", "assess"} and self.labels:
            raise ValueError(f"labels are only valid on classify/assess steps ('{self.id}')")
        if self.kind not in {"lookup", "draft"} and self.tools:
            raise ValueError(f"tools can only be bound to lookup or draft steps ('{self.id}')")
        if self.kind != "retrieve" and self.sources:
            raise ValueError(f"sources can only be bound to retrieve steps ('{self.id}')")
        if self.kind != "assess" and self.dimension:
            raise ValueError(f"dimension is only valid on assess steps ('{self.id}')")
        if self.kind != "human_approval" and self.review:
            raise ValueError(f"review is only valid on human_approval steps ('{self.id}')")
        return self


class ExternalMessageGuardrail(StrictModel):
    approval_required: bool = True


class ToolExecutionGuardrail(StrictModel):
    allowlist_only: bool = True
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    max_calls_per_run: int = Field(default=12, ge=1, le=100)


class PromptInjectionGuardrail(StrictModel):
    action: Literal["block_and_log", "human_review"] = "block_and_log"
    scan_retrieved_content: bool = True


class PiiGuardrail(StrictModel):
    redact_logs: bool = True
    redact_memory: bool = True


class Guardrails(StrictModel):
    external_messages: ExternalMessageGuardrail = Field(default_factory=ExternalMessageGuardrail)
    tool_execution: ToolExecutionGuardrail = Field(default_factory=ToolExecutionGuardrail)
    prompt_injection: PromptInjectionGuardrail = Field(default_factory=PromptInjectionGuardrail)
    pii: PiiGuardrail = Field(default_factory=PiiGuardrail)


class MemoryConfig(StrictModel):
    type: Literal["postgres", "sqlite", "none"]
    namespace: str = Field(pattern=IDENTIFIER)
    pii_retention_days: int = Field(default=30, ge=0, le=365)
    conversation_window: int = Field(default=10, ge=0, le=100)


class EvaluationConfig(StrictModel):
    task_success_target: float = Field(default=0.9, ge=0.0, le=1.0)
    tool_accuracy_target: float = Field(default=0.95, ge=0.0, le=1.0)
    unsafe_action_target: int = Field(default=0, ge=0, le=10)
    adversarial_cases: int = Field(default=18, ge=1, le=200)


class AgentSpec(StrictModel):
    version: Literal["1.0"] = "1.0"
    agent: AgentIdentity
    model: ModelConfig
    tools: tuple[ToolSpec, ...] = Field(default=(), max_length=32)
    retrieval: RetrievalConfig
    workflow: tuple[WorkflowStep, ...] = Field(min_length=2, max_length=24)
    guardrails: Guardrails = Field(default_factory=Guardrails)
    memory: MemoryConfig
    evaluation: EvaluationConfig = Field(default_factory=EvaluationConfig)

    @model_validator(mode="before")
    @classmethod
    def upgrade_legacy_document(cls, data: Any) -> Any:
        return _upgrade_legacy_document(data)

    @model_validator(mode="after")
    def enforce_invariants(self) -> AgentSpec:
        tool_names = [tool.name for tool in self.tools]
        if len(tool_names) != len(set(tool_names)):
            raise ValueError("tool names must be unique")
        step_ids = [step.id for step in self.workflow]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("workflow step ids must be unique")
        if not self.guardrails.tool_execution.allowlist_only:
            raise ValueError("tool execution must be allowlist-only")

        tools = {tool.name: tool for tool in self.tools}
        sources = set(self.retrieval.source_names)
        kinds = [step.kind for step in self.workflow]
        for index, step in enumerate(self.workflow):
            for tool_name in step.tools:
                tool = tools.get(tool_name)
                if tool is None:
                    raise ValueError(f"step '{step.id}' references undeclared tool '{tool_name}'")
                if step.kind == "lookup" and tool.mode != "read":
                    raise ValueError(
                        f"lookup step '{step.id}' may only use read tools; '{tool_name}' is '{tool.mode}'"
                    )
                if step.kind == "draft" and tool.mode == "read":
                    raise ValueError(
                        f"draft step '{step.id}' proposes side effects; read tool '{tool_name}' "
                        "belongs in a lookup step"
                    )
            if step.kind == "retrieve":
                if not self.retrieval.enabled:
                    raise ValueError(f"retrieve step '{step.id}' requires retrieval.enabled")
                if unknown := set(step.sources) - sources:
                    raise ValueError(
                        f"retrieve step '{step.id}' references undeclared sources {sorted(unknown)}"
                    )
            if step.kind == "execute":
                if "human_approval" not in kinds[:index]:
                    raise ValueError("an execute step must be preceded by a human_approval step")
                if not any(tool.has_side_effects for tool in self.tools):
                    raise ValueError("an execute step needs at least one draft or execute tool")
                if "draft" not in kinds[:index]:
                    raise ValueError("an execute step must come after a draft step")
            if step.kind == "draft":
                bound = step.tools or tuple(t.name for t in self.tools if t.has_side_effects)
                needs_approval = any(self.tool_requires_approval(tools[name]) for name in bound)
                if needs_approval and "human_approval" not in kinds[index + 1 :]:
                    raise ValueError(
                        f"draft step '{step.id}' proposes approval-gated actions but no "
                        "human_approval step follows it"
                    )
        if kinds[0] in {"human_approval", "execute"}:
            raise ValueError("the workflow cannot start with an approval or execute step")
        if self.retrieval.citations_required and "retrieve" not in kinds:
            raise ValueError("citations_required needs at least one retrieve step")
        if self.retrieval.enabled and self.retrieval.store == "pgvector" and (self.memory.type != "postgres"):
            raise ValueError("retrieval.store 'pgvector' requires memory.type 'postgres'")
        if self.memory.namespace and not _IDENTIFIER_RE.fullmatch(self.memory.namespace):
            raise ValueError("memory.namespace must be snake_case")
        if any(tool.mode == "execute" for tool in self.tools) and not (
            self.guardrails.external_messages.approval_required
        ):
            raise ValueError("execute-mode tools require external_messages.approval_required")
        return self

    # ----- derived helpers (not serialized) -----

    def tool_requires_approval(self, tool: ToolSpec) -> bool:
        """Effective approval policy: execute tools always; draft tools when the tool or the
        external-message guardrail demands it."""
        if tool.mode == "read":
            return False
        if tool.mode == "execute":
            return True
        return tool.approval_required or self.guardrails.external_messages.approval_required

    def tool(self, name: str) -> ToolSpec:
        for tool in self.tools:
            if tool.name == name:
                return tool
        raise KeyError(name)

    def steps_of(self, kind: str) -> tuple[WorkflowStep, ...]:
        return tuple(step for step in self.workflow if step.kind == kind)


# ---------------------------------------------------------------------------
# Legacy (pre-typed-workflow) document upgrade
# ---------------------------------------------------------------------------

_LEGACY_KIND_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^(classify|categori[sz]e|triage|route)"), "classify"),
    (re.compile(r"^(assess|prioriti[sz]e|score|rate|evaluate_risk)"), "assess"),
    (re.compile(r"^(retrieve|search|gather_sources|fetch_docs|find_sources)"), "retrieve"),
    (re.compile(r"^(safety_check|policy_check|guard)"), "safety_check"),
    (re.compile(r"^(verify|validate|check_citations)"), "verify"),
    (re.compile(r"^(lookup|look_up|check|identify|get|fetch)"), "lookup"),
    (re.compile(r"^(prepare|draft|compose|write)"), "draft"),
    (re.compile(r"^(human_approval|human_review|approval|review)$"), "human_approval"),
    (re.compile(r"^(execute|send|submit|apply)"), "execute"),
    (re.compile(r"^(respond|reply|answer|publish|report|summari[sz]e)"), "respond"),
)


def legacy_step_kind(step_id: str) -> str:
    for pattern, kind in _LEGACY_KIND_RULES:
        if pattern.search(step_id):
            return kind
    return "analyze"


def _upgrade_legacy_document(data: Any) -> Any:
    if not isinstance(data, dict):
        return data
    workflow = data.get("workflow")
    if not (isinstance(workflow, list | tuple) and workflow and isinstance(workflow[0], str)):
        return data

    upgraded = dict(data)
    tools = [tool for tool in data.get("tools", []) if isinstance(tool, dict)]
    read_tools = [tool["name"] for tool in tools if tool.get("mode") == "read" and "name" in tool]
    action_tools = [tool["name"] for tool in tools if tool.get("mode") in {"draft", "execute"}]
    steps: list[dict[str, Any]] = []
    lookup_bound = False
    draft_bound = False
    for name in workflow:
        kind = legacy_step_kind(str(name))
        step: dict[str, Any] = {"id": name, "kind": kind}
        if kind == "classify":
            step["labels"] = [
                {"name": "request", "hints": ["please", "need", "request"]},
                {"name": "question", "hints": ["how", "what", "why", "question"]},
                {"name": "complaint", "hints": ["unhappy", "complaint", "disappointed"]},
                {"name": "other", "hints": []},
            ]
        elif kind == "assess":
            step["labels"] = [
                {"name": level, "hints": list(hints)} for level, hints in DEFAULT_SEVERITY_LEVELS
            ]
            suffix = str(name).split("_", 1)[1] if "_" in str(name) else "urgency"
            step["dimension"] = suffix if _IDENTIFIER_RE.fullmatch(suffix) else "urgency"
        elif kind == "lookup":
            if read_tools and not lookup_bound:
                step["tools"] = read_tools
                lookup_bound = True
            elif not read_tools:
                step["kind"] = "analyze"
        elif kind == "draft":
            if action_tools and not draft_bound:
                step["tools"] = action_tools
                draft_bound = True
        elif kind == "execute" and not action_tools:
            step["kind"] = "respond"
        steps.append(step)
    if read_tools and not lookup_bound:
        late_kinds = {"draft", "safety_check", "verify", "human_approval", "execute", "respond"}
        insert_at = next((i for i, s in enumerate(steps) if s["kind"] in late_kinds), len(steps))
        steps.insert(insert_at, {"id": "lookup_context", "kind": "lookup", "tools": read_tools})
    if action_tools and not draft_bound:
        insert_at = next(
            (i for i, s in enumerate(steps) if s["kind"] in {"human_approval", "execute"}),
            len(steps),
        )
        steps.insert(insert_at, {"id": "prepare_action", "kind": "draft", "tools": action_tools})
    upgraded["workflow"] = steps
    return upgraded


class CompileOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    engine: Literal["auto", "heuristic", "llm"] = "auto"


class CompileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requirement: str = Field(min_length=24, max_length=12_000)
    options: CompileOptions = Field(default_factory=CompileOptions)


class AnalysisSummary(BaseModel):
    engine: Literal["heuristic", "llm"]
    model: str | None = None
    domain: str
    confidence: float = Field(ge=0, le=1)
    assumptions: list[str] = Field(default_factory=list)
    inferences: list[str] = Field(default_factory=list)
    requirement_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class CompileResponse(BaseModel):
    spec: AgentSpec
    spec_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    warnings: list[str] = Field(default_factory=list)
    analysis: AnalysisSummary | None = None
