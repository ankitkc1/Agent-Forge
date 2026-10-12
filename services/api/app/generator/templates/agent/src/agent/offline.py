"""Deterministic offline model.

Implements every structured task with transparent heuristics (keyword hints from the
specification, regex argument extraction, template responses). It needs no network and no
API key, which makes the test-suite and the evaluation suite reproducible inside an isolated
sandbox. Offline evaluation therefore measures the agent's *control flow and safety* —
routing, tool selection, approval gating, guardrails — not language quality. Run the same suite
with ``python -m evals.run --live`` to evaluate the configured model.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from src.agent import textmatch
from src.agent.llm import Message

ID_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]{0,5}-\d{2,8}\b")
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
NUMBER_PATTERN = re.compile(r"(?<![\w-])\$?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?(?![\w-])")
TEXT_FIELDS = {
    "query",
    "question",
    "text",
    "description",
    "details",
    "request",
    "notes",
    "reason",
    "issue",
}
BODY_FIELDS = {"body", "message", "content", "reply"}
SUMMARY_FIELDS = {"summary", "title", "headline"}
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def first_sentence(text: str, limit: int = 220) -> str:
    sentence = SENTENCE_END.split(text.strip(), maxsplit=1)[0]
    return sentence if len(sentence) <= limit else sentence[: limit - 1].rstrip() + "…"


def _number(text: str) -> float | None:
    for match in NUMBER_PATTERN.finditer(ID_PATTERN.sub(" ", text)):
        whole = match.group(1).replace(",", "")
        return float(f"{whole}.{match.group(2)}" if match.group(2) else whole)
    return None


def extract_arguments(
    text: str, inputs: Sequence[Mapping[str, Any]], facts: Mapping[str, Any]
) -> dict[str, Any]:
    """Fill tool arguments from the request text and facts gathered by earlier steps."""
    identifiers = ID_PATTERN.findall(text)
    arguments: dict[str, Any] = {}
    for parameter in inputs:
        name = str(parameter["name"])
        kind = str(parameter.get("type", "string"))
        value: Any = None
        if facts.get(name) not in (None, ""):
            value = facts[name]
        elif name.endswith("_id") or name == "id":
            value = identifiers[0] if identifiers else facts.get("entity_id")
        elif kind in {"number", "integer"}:
            value = facts.get(name)
            if value is None:
                value = _number(text)
        elif kind == "boolean":
            value = bool(facts.get(name, False))
        elif "email" in name:
            match = EMAIL_PATTERN.search(text)
            value = match.group(0) if match else None
        elif name in BODY_FIELDS:
            value = facts.get("message") or facts.get("summary") or text[:1000]
        elif name in SUMMARY_FIELDS or name == "subject":
            category = str(facts.get("category", "your request")).replace("_", " ")
            value = f"{category.capitalize()}: {first_sentence(text, 120)}"
        elif name in TEXT_FIELDS:
            value = text[:1000]
        if value is None and parameter.get("required", True):
            value = 0 if kind in {"number", "integer"} else text[:500]
        if value is None:
            continue
        if kind == "integer":
            value = int(float(value))
        elif kind == "number":
            value = float(value)
        elif kind == "string":
            value = str(value)
        arguments[name] = value
    return arguments


class OfflineModel:
    name = "offline"

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        task: str,
        context: Mapping[str, Any],
        schema: dict[str, Any] | None = None,
    ) -> str:
        handler = getattr(self, f"_task_{task}", None)
        if handler is None:
            raise ValueError(f"offline model does not implement task '{task}'")
        return json.dumps(handler(context))

    # -- tasks ---------------------------------------------------------------------------------

    @staticmethod
    def _task_classify(context: Mapping[str, Any]) -> dict[str, Any]:
        labels = [(label["name"], label.get("hints", [])) for label in context["labels"]]
        label, confidence, score = textmatch.classify(str(context["text"]), labels)
        rationale = (
            f"{score} keyword hint(s) matched '{label}'."
            if score
            else "No keyword hints matched; using the fallback label."
        )
        return {"label": label, "confidence": confidence, "rationale": rationale}

    @staticmethod
    def _task_assess(context: Mapping[str, Any]) -> dict[str, Any]:
        levels = [(level["name"], level.get("hints", [])) for level in context["levels"]]
        level, score = textmatch.assess(str(context["text"]), levels)
        rationale = (
            f"{score} severity cue(s) indicate '{level}'."
            if score
            else f"No explicit cues; defaulting to '{level}'."
        )
        return {"level": level, "rationale": rationale}

    @staticmethod
    def _task_tool_arguments(context: Mapping[str, Any]) -> dict[str, Any]:
        tool = context["tool"]
        return {
            "arguments": extract_arguments(
                str(context["text"]), tool.get("inputs", []), context.get("facts", {})
            )
        }

    @staticmethod
    def _task_analyze(context: Mapping[str, Any]) -> dict[str, Any]:
        evidence = list(context.get("evidence", []))
        tool_results = list(context.get("tool_results", []))
        step = context.get("step", {})
        findings = [
            f"{first_sentence(str(item['text']))} [{item['citation']}]" for item in evidence[:3]
        ]
        for result in tool_results[:2]:
            data = result.get("data")
            if isinstance(data, dict) and data.get("found"):
                findings.append(f"{result['tool']} returned a matching record.")
        summary = (
            f"{step.get('description') or step.get('id', 'Analysis')}: reviewed "
            f"{len(evidence)} evidence passage(s) and {len(tool_results)} tool result(s)."
        )
        return {"summary": summary, "findings": findings}

    @staticmethod
    def _task_draft(context: Mapping[str, Any]) -> dict[str, Any]:
        facts = dict(context.get("facts", {}))
        text = str(context["text"])
        evidence = list(context.get("evidence", []))
        category = str(facts.get("category", "your request")).replace("_", " ")
        level_note = ""
        if facts.get("dimension") and facts.get("level"):
            level_note = f" We assessed it as {facts['level']} {facts['dimension']}."
        guidance = ""
        if evidence:
            guidance = (
                f" Relevant guidance [{evidence[0]['citation']}]: "
                f"{first_sentence(str(evidence[0]['text']), 180)}"
            )
        message = (
            f"Thank you for your message about {category}.{level_note}{guidance} "
            "We will confirm the next steps once they are approved."
        ).strip()
        facts.setdefault("message", message)
        facts.setdefault("summary", first_sentence(text, 160))
        actions = []
        for tool in context.get("tools", []):
            actions.append(
                {
                    "tool": tool["name"],
                    "arguments": extract_arguments(text, tool.get("inputs", []), facts),
                    "rationale": f"{tool['name']} supports handling this {category} request.",
                }
            )
        return {
            "summary": f"Prepared {len(actions)} proposed action(s) for {category}.",
            "message": message,
            "actions": actions,
        }

    @staticmethod
    def _task_verify(context: Mapping[str, Any]) -> dict[str, Any]:
        evidence_ids = {item["citation"] for item in context.get("evidence", [])}
        claims = [claim for claim in context.get("claims", []) if claim.strip()]
        issues: list[str] = []
        if context.get("citations_required"):
            if not evidence_ids:
                issues.append("No evidence was retrieved to support the answer.")
            for claim in claims:
                cited = set(re.findall(r"\[(S\d+)\]", claim))
                if not cited:
                    issues.append(f"Uncited claim: {first_sentence(claim, 120)}")
                elif not cited <= evidence_ids:
                    issues.append(f"Citation not found in evidence: {sorted(cited - evidence_ids)}")
        return {"supported": not issues, "issues": issues}

    @staticmethod
    def _task_respond(context: Mapping[str, Any]) -> dict[str, Any]:
        lines: list[str] = []
        classification = context.get("classification") or {}
        if classification.get("label"):
            lines.append(f"Category: {classification['label'].replace('_', ' ')}.")
        for assessment in (context.get("assessments") or {}).values():
            lines.append(f"{str(assessment.get('dimension', 'level')).capitalize()}: {assessment.get('level')}.")
        for result in context.get("tool_results", [])[:3]:
            data = result.get("data")
            if isinstance(data, dict) and data.get("found") and isinstance(data.get("record"), dict):
                record = data["record"]
                preview = ", ".join(f"{k}={v}" for k, v in list(record.items())[:3])
                lines.append(f"{result['tool']}: {preview}.")
        for note in (context.get("notes") or {}).values():
            for finding in note.get("findings", [])[:3]:
                lines.append(finding)
        evidence = context.get("evidence", [])
        if evidence:
            cited = ", ".join(f"[{item['citation']}] {item['title']}" for item in evidence[:3])
            lines.append(f"Sources: {cited}.")
        executed = [a for a in context.get("executed_actions", []) if a.get("status") == "executed"]
        if executed:
            lines.append("Completed actions: " + ", ".join(a["tool"] for a in executed) + ".")
        pending = [
            a for a in context.get("proposed_actions", []) if a.get("requires_approval")
        ]
        if pending and not executed:
            lines.append("Proposed actions: " + ", ".join(a["tool"] for a in pending) + ".")
        if context.get("draft_response"):
            lines.append(str(context["draft_response"]))
        return {"response": "\n".join(lines) or "Request processed."}
