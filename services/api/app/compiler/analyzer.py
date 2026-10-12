"""Deterministic requirement analysis.

Turns untrusted natural language into a structured :class:`RequirementAnalysis`. The analysis is
an intermediate representation only — it never reaches the generator. ``assemble.py`` converts it
into an AgentSpec, which is then validated like any user-authored specification.

The analyzer is intentionally conservative: every default it applies is recorded as an
assumption and every inferred capability is recorded with the phrase that triggered it, so the
reviewer can see exactly why the specification looks the way it does.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.compiler.domains import (
    ALL_PACKS,
    GENERAL_PACK,
    DomainPack,
    LabelTemplate,
    SourceTemplate,
    ToolTemplate,
)

_SNAKE_INVALID = re.compile(r"[^a-z0-9]+")
_FILLER_WORDS = {
    "a",
    "an",
    "the",
    "ai",
    "smart",
    "simple",
    "intelligent",
    "autonomous",
    "llm",
    "governed",
    "new",
    "our",
    "my",
    "production",
    "ready",
    "production-ready",
    "agentic",
}
_ROLE_NOUNS = ("agent", "assistant", "analyst", "coordinator", "bot", "copilot", "processor")


def snake(text: str, *, max_words: int = 5) -> str:
    joined = re.sub(r"(?<=[a-z0-9])-(?=[a-z0-9])", "", text.casefold())
    words = [w for w in _SNAKE_INVALID.sub(" ", joined).split() if w not in _FILLER_WORDS]
    value = "_".join(words[:max_words])
    if not value or not value[0].isalpha():
        value = f"x_{value}" if value else ""
    return value[:63]


def singular(word: str) -> str:
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith(("sses", "shes", "ches")):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


@dataclass
class ToolDraft:
    name: str
    mode: str
    description: str
    inputs: tuple[tuple[str, str, str, bool], ...]
    origin: str
    evidence: str = ""


@dataclass
class SourceDraft:
    name: str
    description: str
    origin: str
    template: SourceTemplate | None = None


@dataclass
class RequirementAnalysis:
    text: str
    pack: DomainPack
    domain_score: float
    agent_name: str
    objective: str
    description: str
    provider: str
    model: str
    memory: str
    task_success_target: float
    tool_accuracy_target: float
    unsafe_action_target: int
    tools: list[ToolDraft]
    sources: list[SourceDraft]
    labels: tuple[LabelTemplate, ...]
    wants_assess: bool
    dimension: str | None
    levels: tuple[LabelTemplate, ...]
    retrieval_enabled: bool
    citations: bool
    approval_explicit: bool
    review_always: bool
    store: str
    embeddings: str
    constraints: list[str]
    assumptions: list[str] = field(default_factory=list)
    inferences: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def confidence(self) -> float:
        if self.pack is GENERAL_PACK:
            return 0.35
        domain_confidence = min(1.0, self.domain_score / 8)
        explicit = sum(1 for tool in self.tools if tool.origin != "default")
        coverage = min(1.0, explicit / 3)
        return round(0.4 + 0.4 * domain_confidence + 0.2 * coverage, 2)


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------


def detect_domain(text: str) -> tuple[DomainPack, float]:
    lower = text.casefold()
    best: tuple[DomainPack, float] = (GENERAL_PACK, 0.0)
    for pack in ALL_PACKS:
        pack_score = 0.0
        for pattern, weight in pack.detect:
            if re.search(pattern, lower):
                pack_score += weight
        if pack_score > best[1]:
            best = (pack, pack_score)
    if best[1] < 3:
        return GENERAL_PACK, best[1]
    return best


_LOCAL_RE = re.compile(
    r"\b(local|on-?prem(ise)?s?|self-?hosted|ollama|qwen|llama|mistral|gemma|deepseek|phi-?\d)\b"
)
_ANTHROPIC_RE = re.compile(r"\b(anthropic|claude)\b")
_OPENAI_RE = re.compile(r"\b(openai|gpt|chatgpt|azure openai)\b")


def detect_model(lower: str) -> tuple[str, str, str | None]:
    """Return (provider, model, assumption)."""
    if _LOCAL_RE.search(lower):
        if match := re.search(r"\b(qwen[\d.]*(?::\d+b)?)\b", lower):
            model = match.group(1)
            if model == "qwen" or ":" not in model:
                model = "qwen2.5:14b"
        elif "llama" in lower:
            model = "llama3.1:8b"
        elif "mistral" in lower:
            model = "mistral:7b"
        elif "gemma" in lower:
            model = "gemma3:12b"
        elif "deepseek" in lower:
            model = "deepseek-r1:14b"
        else:
            model = "qwen2.5:14b"
        return "local", model, None
    if _ANTHROPIC_RE.search(lower):
        match = re.search(r"\b(claude-[a-z0-9][a-z0-9.\-]*)\b", lower)
        return "anthropic", match.group(1) if match else "claude-sonnet-5-5", None
    if _OPENAI_RE.search(lower):
        match = re.search(r"\b(gpt-[a-z0-9][a-z0-9.\-]*)\b", lower)
        return "openai", match.group(1) if match else "gpt-5-mini", None
    return "openai", "gpt-5-mini", "No model provider was named; defaulted to OpenAI gpt-5-mini."


def detect_memory(lower: str) -> tuple[str, str | None]:
    if re.search(r"\bpostgres(ql)?\b|\bpgvector\b", lower):
        return "postgres", None
    if re.search(r"\bsqlite\b", lower):
        return "sqlite", None
    if re.search(r"\b(no|without) (long[- ]term )?memory\b|\bstateless\b", lower):
        return "none", None
    return "sqlite", "No memory backend was named; defaulted to SQLite conversation memory."


def _percent(value: str) -> float:
    return max(0.0, min(1.0, int(value) / 100))


def detect_targets(lower: str) -> tuple[float, float, int, list[str]]:
    notes: list[str] = []
    task = None
    for pattern in (
        r"(\d{2,3})\s*%\s*(?:task[- ]success|success(?: rate)?|factual accuracy|accuracy|resolution)",
        r"(?:task[- ]success|success rate|factual accuracy|accuracy)\D{0,30}?(\d{2,3})\s*%",
        r"\btarget(?:ing)?\s+(?:at least\s+|of\s+)?(\d{2,3})\s*%",
        r"\bat least\s+(\d{2,3})\s*%",
    ):
        if match := re.search(pattern, lower):
            task = _percent(match.group(1))
            break
    if task is None:
        task = 0.9
        notes.append("No task-success target was stated; defaulted to 90%.")
    tool = 0.95
    if match := re.search(r"tool[- ](?:selection )?accuracy\D{0,20}?(\d{2,3})\s*%", lower):
        tool = _percent(match.group(1))
    unsafe = 0
    if match := re.search(r"(?:at most|no more than|max(?:imum)?)\s+(\d)\s+unsafe", lower):
        unsafe = int(match.group(1))
    return task, tool, unsafe, notes


_LIST_STOP_WORDS = {
    "look",
    "looks",
    "search",
    "searches",
    "create",
    "creates",
    "draft",
    "drafts",
    "can",
    "will",
    "should",
    "must",
    "may",
    "then",
    "check",
    "checks",
    "send",
    "sends",
    "escalate",
    "escalates",
    "prepare",
    "prepares",
    "retrieve",
    "retrieves",
    "identify",
    "identifies",
    "assess",
    "assesses",
    "use",
    "uses",
    "route",
    "routes",
    "it",
    "flag",
    "flags",
    "require",
    "requires",
    "answer",
    "answers",
    "reply",
    "replies",
    "update",
    "updates",
    "schedule",
    "schedules",
}


def _split_list(fragment: str) -> list[str]:
    fragment = re.split(r"[.;:()]|\bthen\b|\bwith\b|\bbased\b|\bbefore\b|\busing\b", fragment)[0]
    parts: list[str] = []
    for raw in re.split(r",|\bor\b|\band\b|/", fragment):
        part = raw.strip()
        if not part:
            continue
        if part.split()[0] in _LIST_STOP_WORDS:
            break
        parts.append(part)
    return parts


def detect_explicit_labels(lower: str) -> list[str]:
    match = re.search(
        r"\b(?:classif(?:y|ies|ying)|categori[sz]e[sd]?|sort|triage|route)\b[^.]{0,60}?\b(?:into|as|by)\b\s+(?:categories\s+(?:such as|like)\s+)?([^.;]{3,200})",
        lower,
    )
    if not match:
        return []
    labels: list[str] = []
    for part in _split_list(match.group(1)):
        words = part.split()
        if not words or len(words) > 3:
            continue
        name = snake(" ".join(w for w in words if w not in {"issues", "requests", "tickets"}))
        if name and name not in labels and 2 <= len(name) <= 40:
            labels.append(name)
    return labels if 2 <= len(labels) <= 12 else []


_DIMENSIONS = {
    "urgency": r"\burgen(t|cy)\b",
    "severity": r"\bseverity\b|\bsev ?[1-4]\b",
    "priority": r"\bprioriti[sz](e|ation)|\bpriority\b",
    "risk": r"\brisk\b",
    "fit": r"\b(lead score|fit score|qualif)",
    "impact": r"\bimpact\b",
}


def detect_dimension(lower: str) -> str | None:
    for dimension, pattern in _DIMENSIONS.items():
        if re.search(pattern, lower):
            return dimension
    return None


_CONSTRAINT_RE = re.compile(
    r"([^.!?\n]*\b(?:never|must not|mustn't|do not|don't|should not|shouldn't|may not|cannot|can't|"
    r"only after|only with)\b[^.!?\n]*)[.!?]?",
    re.IGNORECASE,
)


def detect_constraints(text: str) -> list[str]:
    constraints: list[str] = []
    for match in _CONSTRAINT_RE.finditer(text):
        sentence = " ".join(match.group(1).split()).strip(" ,;-")
        if not 8 <= len(sentence) <= 240:
            continue
        sentence = sentence[0].upper() + sentence[1:]
        if not sentence.endswith("."):
            sentence += "."
        if sentence not in constraints:
            constraints.append(sentence)
    return constraints[:6]


# ---------------------------------------------------------------------------
# Capability extraction
# ---------------------------------------------------------------------------

_READ_RE = re.compile(
    r"\b(?:look(?:s|ing)?\s+up|lookups?|check(?:s|ing)?|fetch(?:es|ing)?|quer(?:y|ies|ying)|"
    r"retriev(?:e|es|ing)|get(?:s|ting)?|verif(?:y|ies|ying))\s+(?:the\s+|their\s+|a\s+|an\s+|its\s+)?"
    r"(?:([a-z]+)\s+)?([a-z]+)\s+(details|status|history|records?|information|info|data|availability|"
    r"balance|profile|inventory)\b"
)
_DRAFT_RE = re.compile(
    r"\b(?:draft(?:s|ing)?|prepar(?:e|es|ing)|writ(?:e|es|ing)|compos(?:e|es|ing))\s+"
    r"(?:a\s+|an\s+|the\s+)?(?:([a-z]+)\s+)?(emails?|repl(?:y|ies)|responses?|messages?|work orders?|"
    r"tickets?|reports?|status updates?|updates?|notes?|letters?|quotes?|proposals?|summar(?:y|ies))\b"
    r"(?!\s+(?:plans?|strateg(?:y|ies)|outlines?|analys[ie]s|approach(?:es)?))"
)
_EXECUTE_RE = re.compile(
    r"\b(send|create|open|update|close|issue|escalate|assign|schedule|book|submit)(?:s|ing|e)?\s+"
    r"(?:a\s+|an\s+|the\s+|any\s+|new\s+)?(?:([a-z]+)\s+)?(emails?|messages?|notifications?|replies|"
    r"tickets?|work orders?|tasks?|records?|refunds?|credits?|meetings?|appointments?|visits?|"
    r"payments?|interviews?|cases?|issues?|invoices?)\b"
)
_DOC_RE = re.compile(
    r"\b(?:search(?:es|ing)?|consult(?:s|ing)?|referenc(?:e|es|ing)|us(?:e|es|ing)|check(?:s|ing)?|"
    r"retriev(?:e|es|ing)(?:\s+from)?|read(?:s|ing)?|look(?:s|ing)?\s+up)\s+(?:the\s+|our\s+|their\s+|"
    r"approved\s+|internal\s+|relevant\s+)?(?:([a-z]+)\s+)?(documentation|docs|knowledge base|policies|"
    r"policy|runbooks?|manuals?|wiki|articles|faqs?|handbook|guidelines|playbooks?|procedures|contracts)\b"
)
_STOP_QUALIFIERS = {"any", "all", "relevant", "approved", "internal", "external", "the", "our", "and"}


def _matches_any(patterns: tuple[str, ...], lower: str) -> str | None:
    for pattern in patterns:
        if match := re.search(pattern, lower):
            return match.group(0)
    return None


def _entity_inputs(pack: DomainPack) -> tuple[tuple[str, str, str, bool], ...]:
    entity = pack.entity
    example = f"{entity.id_prefix}-1001"
    return ((entity.id_param, "string", f"{entity.noun.title()} identifier, for example {example}.", True),)


def extract_tools(lower: str, pack: DomainPack) -> tuple[list[ToolDraft], list[str], list[str]]:
    tools: list[ToolDraft] = []
    inferences: list[str] = []
    assumptions: list[str] = []
    seen: set[str] = set()

    def add(draft: ToolDraft) -> None:
        if draft.name in seen or len(tools) >= 12:
            return
        seen.add(draft.name)
        tools.append(draft)

    for template in pack.tools:
        if evidence := _matches_any(template.triggers, lower):
            add(_from_template(template, "matched", evidence))

    covered_words = {part for tool in tools for part in tool.name.split("_")}
    entity_inputs = _entity_inputs(pack)

    for match in _READ_RE.finditer(lower):
        noun = singular(match.group(2))
        qualifier = singular(match.group(1)) if match.group(1) else None
        if noun in {"the", "their", "its", "a"} or noun in covered_words:
            continue
        if qualifier and qualifier in covered_words:
            continue
        name = snake(f"{noun} lookup", max_words=3)
        if name in seen:
            continue
        add(
            ToolDraft(
                name,
                "read",
                f"Look up {noun} {match.group(3)}.",
                entity_inputs,
                "inferred",
                match.group(0),
            )
        )
        inferences.append(f"Inferred read tool '{name}' from \"{match.group(0)}\".")

    for match in _DRAFT_RE.finditer(lower):
        obj = singular(match.group(2))
        qualifier = match.group(1) if match.group(1) not in _STOP_QUALIFIERS else None
        if any(word in covered_words for word in obj.split()):
            continue
        name = snake(f"draft {qualifier or ''} {obj}", max_words=4)
        if name in seen:
            continue
        add(
            ToolDraft(
                name,
                "draft",
                f"Draft a {' '.join(filter(None, [qualifier, obj]))} for human review.",
                (
                    *entity_inputs,
                    ("subject", "string", "Subject or title.", True),
                    ("body", "string", "Draft content.", True),
                ),
                "inferred",
                match.group(0),
            )
        )
        inferences.append(f"Inferred draft tool '{name}' from \"{match.group(0)}\".")

    for match in _EXECUTE_RE.finditer(lower):
        verb, qualifier, obj = match.group(1), match.group(2), singular(match.group(3))
        if qualifier in _STOP_QUALIFIERS:
            qualifier = None
        if any(word in covered_words for word in obj.split()):
            continue
        name = snake(f"{verb} {qualifier or ''} {obj}", max_words=4)
        if name in seen:
            continue
        add(
            ToolDraft(
                name,
                "execute",
                f"{verb.title()} a {' '.join(filter(None, [qualifier, obj]))} in the system of record.",
                (*entity_inputs, ("details", "string", "What should be done.", True)),
                "inferred",
                match.group(0),
            )
        )
        inferences.append(f"Inferred execute tool '{name}' from \"{match.group(0)}\".")

    core_pack = pack is not GENERAL_PACK
    has_read = any(tool.mode == "read" for tool in tools)
    has_action = any(tool.mode != "read" for tool in tools)
    for template in pack.tools:
        if not template.default or template.name in seen:
            continue
        if (
            core_pack
            or (template.mode == "read" and not has_read)
            or (template.mode != "read" and not has_action)
        ):
            add(_from_template(template, "default"))
            assumptions.append(
                f"Added the {pack.title} pack's default {template.mode} tool '{template.name}'."
            )
    order = {template.name: index for index, template in enumerate(pack.tools)}
    tools.sort(key=lambda tool: order.get(tool.name, len(order)))
    return tools, inferences, assumptions


def _from_template(template: ToolTemplate, origin: str, evidence: str = "") -> ToolDraft:
    return ToolDraft(template.name, template.mode, template.description, template.inputs, origin, evidence)


def extract_sources(lower: str, pack: DomainPack) -> tuple[list[SourceDraft], list[str]]:
    sources: list[SourceDraft] = []
    inferences: list[str] = []
    seen: set[str] = set()
    for template in pack.sources:
        if _matches_any(template.triggers, lower):
            sources.append(SourceDraft(template.name, template.description, "matched", template))
            seen.add(template.name)
    covered = {word for source in sources for word in source.name.split("_")}
    for match in _DOC_RE.finditer(lower):
        qualifier = match.group(1) if match.group(1) not in _STOP_QUALIFIERS else None
        doc = match.group(2).replace("docs", "documentation")
        doc_word = doc.split()[-1]
        if singular(doc_word) in {singular(word) for word in covered}:
            continue
        name = snake(f"{qualifier or ''} {doc}", max_words=3)
        if not name or name in seen:
            continue
        seen.add(name)
        sources.append(
            SourceDraft(name, f"Approved {(qualifier + ' ') if qualifier else ''}{doc}.", "inferred")
        )
        inferences.append(f"Inferred retrieval source '{name}' from \"{match.group(0)}\".")
    return sources, inferences


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

_NAME_RE = re.compile(
    r"\b(?:build|create|make|design|develop|need|want|generate)\s+(?:me\s+)?(?:an?|the|our)\s+"
    r"([a-z0-9][a-z0-9 \-]{2,60}?)\s+(" + "|".join(_ROLE_NOUNS) + r")\b"
)


def detect_agent_name(lower: str, pack: DomainPack) -> tuple[str, str | None]:
    if match := _NAME_RE.search(lower):
        phrase, role = match.group(1), match.group(2)
        words = [w for w in _SNAKE_INVALID.sub(" ", phrase).split() if w not in _FILLER_WORDS]
        if 1 <= len(words) <= 4:
            if role not in {"agent", "assistant", "bot"}:
                words.append(role)
            name = snake(" ".join(words))
            if re.fullmatch(r"[a-z][a-z0-9_]{1,63}", name):
                return name, None
    return pack.agent_name, f"Agent name defaulted to '{pack.agent_name}'."


def analyze_requirement(requirement: str) -> RequirementAnalysis:
    text = " ".join(requirement.split())
    lower = text.casefold()
    pack, domain_score = detect_domain(text)
    assumptions: list[str] = []
    if pack is GENERAL_PACK:
        assumptions.append(
            "No domain matched with high confidence; the general operations pack supplied defaults."
        )

    agent_name, name_note = detect_agent_name(lower, pack)
    if name_note:
        assumptions.append(name_note)
    provider, model, model_note = detect_model(lower)
    if model_note:
        assumptions.append(model_note)
    memory, memory_note = detect_memory(lower)
    if memory_note:
        assumptions.append(memory_note)
    task_target, tool_target, unsafe_target, target_notes = detect_targets(lower)
    assumptions.extend(target_notes)

    tools, tool_inferences, tool_assumptions = extract_tools(lower, pack)
    assumptions.extend(tool_assumptions)

    no_retrieval = bool(re.search(r"\b(no|without) (retrieval|rag|knowledge base)\b", lower))
    sources, source_inferences = extract_sources(lower, pack)
    retrieval_mentioned = bool(
        sources
        or re.search(
            r"\b(rag|retriev\w*|knowledge base|documentation|docs|polic(y|ies)|runbooks?|manuals?|"
            r"vector|sources?|citations?)\b",
            lower,
        )
    )
    retrieval_enabled = not no_retrieval
    if retrieval_enabled:
        present = {source.name for source in sources}
        defaults = [
            SourceDraft(t.name, t.description, "default", t)
            for t in pack.sources
            if t.default and t.name not in present
        ]
        if defaults:
            sources = [*sources, *defaults]
            note = "Added the domain pack's curated sources: " + ", ".join(s.name for s in defaults)
            assumptions.append(note if retrieval_mentioned else note + " (retrieval was not mentioned).")

    explicit_labels = detect_explicit_labels(lower)
    if explicit_labels:
        labels = tuple(pack.label(name) or LabelTemplate(name, "", ()) for name in explicit_labels)
    else:
        labels = pack.labels
        assumptions.append(
            f"Classification labels came from the {pack.title} pack: "
            + ", ".join(label.name for label in labels)
        )

    dimension = detect_dimension(lower)
    wants_assess = bool(dimension) or pack.assess_step is not None
    levels = pack.levels
    if wants_assess and not levels:
        levels = GENERAL_PACK.levels
    if wants_assess and dimension is None:
        dimension = pack.dimension or "urgency"

    citations = pack.citations or bool(
        re.search(r"\bcit(e|es|ed|ing|ation|ations)\b|\breferences? (every|each|all)\b", lower)
    )
    if citations and not retrieval_enabled:
        citations = False
    approval_explicit = bool(
        re.search(r"\b(approv\w*|sign-?off|human (review|in the loop)|manual review)\b", lower)
    )
    review_always = pack.review_always or bool(
        re.search(r"\b(human|manual|editor) review (before|of every|of all|for every)\b", lower)
    )
    store = (
        "pgvector"
        if re.search(r"\bpgvector\b", lower)
        or (memory == "postgres" and re.search(r"\bvector (store|database|db|search)\b", lower))
        else "memory"
    )
    embeddings = "hashing"
    if re.search(r"\bopenai embeddings?\b|\btext-embedding", lower):
        embeddings = "openai"
    elif re.search(r"\b(ollama|local) embeddings?\b|\bnomic-embed", lower):
        embeddings = "ollama"

    constraints = detect_constraints(text)
    for note in pack.safety_notes:
        if note not in constraints:
            constraints.append(note)

    objective = pack.objective
    description = pack.description
    if pack is GENERAL_PACK:
        capability_words = sorted({tool.name.replace("_", " ") for tool in tools})[:4]
        if capability_words:
            description = f"{pack.description} Capabilities: {', '.join(capability_words)}."

    analysis = RequirementAnalysis(
        text=text,
        pack=pack,
        domain_score=domain_score,
        agent_name=agent_name,
        objective=objective,
        description=description,
        provider=provider,
        model=model,
        memory=memory,
        task_success_target=task_target,
        tool_accuracy_target=tool_target,
        unsafe_action_target=unsafe_target,
        tools=tools,
        sources=sources if retrieval_enabled else [],
        labels=labels,
        wants_assess=wants_assess,
        dimension=dimension,
        levels=levels,
        retrieval_enabled=retrieval_enabled and bool(sources),
        citations=citations,
        approval_explicit=approval_explicit,
        review_always=review_always,
        store=store,
        embeddings=embeddings,
        constraints=constraints[:8],
        assumptions=assumptions,
        inferences=[*tool_inferences, *source_inferences],
    )
    if explicit_labels and any(not label.hints for label in labels):
        analysis.warnings.append(
            "Some classification labels have no keyword hints; add hints in the spec so the offline "
            "evaluation model can recognise them."
        )
    return analysis
