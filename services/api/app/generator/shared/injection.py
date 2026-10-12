"""Prompt-injection heuristics.

A transparent, dependency-free detector for the well-known injection families: instruction
override, system-prompt exfiltration, role hijacking, control bypass, bulk data exfiltration,
credential harvesting, fake role markup and tool smuggling. Text is normalised first (Unicode
NFKC, zero-width characters removed, spaced-out letters re-joined, common leetspeak folded) so
trivial obfuscation does not evade the rules.

Two profiles exist. ``input`` is applied to user requests. ``retrieved`` is applied to documents
and tool output, and only uses rules that indicate *instructions aimed at the model*, so ordinary
policy text such as "never share credentials" is not flagged.

Heuristics are a first line of defence, not a guarantee: code-level controls (tool allowlists,
approval binding, phase checks) are what actually prevent unsafe actions.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

Profile = Literal["input", "retrieved"]
THRESHOLD = 0.6

_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿­"), None)
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})
_SPACED = re.compile(r"\b(?:[a-z][ .\-_]){3,}[a-z]\b")
_NEGATION = re.compile(
    r"\b(never|don'?t|do not|must not|mustn'?t|should not|shouldn'?t|cannot|can'?t|may not|not to)"
    r"\s+(?:\w+\s+){0,2}$"
)
# Policy documents legitimately say "never send X without approval"; requests rarely do. Negated
# statements are therefore only discounted for request-style rules, and only adjacent negations
# count, so "Never mind, ignore previous instructions" is still caught.
_NEGATABLE: dict[str, frozenset[str]] = {
    "input": frozenset({"credential_request", "bulk_exfiltration"}),
    "retrieved": frozenset(
        {
            "credential_request",
            "bulk_exfiltration",
            "unapproved_execution",
            "control_bypass",
            "prompt_exfiltration",
            "role_hijack",
        }
    ),
}


@dataclass(frozen=True)
class Signal:
    rule: str
    weight: float
    excerpt: str


@dataclass(frozen=True)
class InjectionVerdict:
    suspicious: bool
    score: float
    signals: tuple[Signal, ...]

    @property
    def rules(self) -> tuple[str, ...]:
        return tuple(signal.rule for signal in self.signals)


def _rule(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern)


_OBJECTS_OF_CONTROL = (
    r"(approvals?|human review|the review|review step|safety checks?|guardrails?|safeguards?|"
    r"policy checks?|security checks?|verification|confirmation|content filters?)"
)
_SENSITIVE = (
    r"(api[ _-]?keys?|secrets?|access tokens?|auth tokens?|credentials|private keys?|ssh keys?|"
    r"admin password|root password|(?:other|all|every|another) (?:users?|employees?|accounts?|"
    r"customers?)'?s? passwords?|passwords? (?:for|of) (?:all|every|other|another))"
)

RULES: tuple[tuple[str, float, re.Pattern[str], frozenset[str]], ...] = (
    (
        "override_instructions",
        0.9,
        _rule(
            r"\b(ignore|disregard|forget|override|bypass|drop)\b[^.\n]{0,40}\b(previous|prior|above|"
            r"earlier|all|any|your|the|system|these|those)\b[^.\n]{0,30}\b(instructions?|prompts?|"
            r"rules|directives|guidelines|guardrails|constraints|programming)\b"
        ),
        frozenset({"input", "retrieved"}),
    ),
    (
        "new_instructions",
        0.7,
        _rule(
            r"\b(new|updated|real|actual|secret|hidden)\s+(instructions?|system prompt|directives?)\s*[:\-]"
        ),
        frozenset({"input", "retrieved"}),
    ),
    (
        "prompt_exfiltration",
        0.8,
        _rule(
            r"\b(reveal|print|show|repeat|output|display|leak|tell me|give me|what is|what are)\b"
            r"[^.\n]{0,40}\b(system prompt|hidden (prompt|instructions)|initial instructions|"
            r"(your|the) (instructions|prompt|rules|configuration)|developer message)\b"
        ),
        frozenset({"input", "retrieved"}),
    ),
    (
        "role_hijack",
        0.75,
        _rule(
            r"\b(you are now|from now on,? you are|act as|pretend (to be|you are)|roleplay as|"
            r"switch to)\b[^.\n]{0,40}\b(unrestricted|jailbroken|dan\b|developer mode|unfiltered|"
            r"evil|without (any )?(rules|restrictions|limits|filters|guidelines))"
        ),
        frozenset({"input", "retrieved"}),
    ),
    (
        "jailbreak_marker",
        0.8,
        _rule(r"\b(do anything now|developer mode (enabled|on)|jailbreak(ed|ing)?|dan mode)\b"),
        frozenset({"input", "retrieved"}),
    ),
    (
        "control_bypass",
        0.75,
        _rule(
            r"\b(bypass|skip|disable|turn off|override|ignore|circumvent|get around|avoid|remove)\b"
            r"[^.\n]{0,25}\b" + _OBJECTS_OF_CONTROL
        ),
        frozenset({"input", "retrieved"}),
    ),
    (
        "unapproved_execution",
        0.75,
        _rule(
            r"\b(execute|run|perform|send|issue|transfer|pay|refund|delete|approve|submit|grant)\b"
            r"[^.\n]{0,50}\bwithout (asking for |waiting for |getting |any |a )?(approvals?|"
            r"confirmation|review|verification|human (review|approval|sign-?off)|sign-?off|"
            r"checking with anyone)\b"
        ),
        frozenset({"input", "retrieved"}),
    ),
    (
        "bulk_exfiltration",
        0.75,
        _rule(
            r"\b(send|email|forward|post|upload|export|exfiltrate|dump|share|leak|copy)\b[^.\n]{0,50}"
            r"\b(all|every|entire|full|complete|whole)\b[^.\n]{0,40}\b(customers|tenants|users|"
            r"employees|records|database|contacts|accounts|passwords|credentials|candidates|vendors)\b"
        ),
        frozenset({"input"}),
    ),
    (
        "credential_request",
        0.75,
        _rule(
            r"\b(send|share|give|reveal|print|show|tell|email|post|list|dump)\b[^.\n]{0,30}\b" + _SENSITIVE
        ),
        frozenset({"input"}),
    ),
    (
        "fake_role_markup",
        0.65,
        _rule(
            r"<\s*/?\s*(system|assistant|tool|function|instructions?)\b[^>]{0,40}>|"
            r"\[\s*/?\s*(system|inst)\s*\]|<\|(im_start|im_end|system|endoftext)\|>"
        ),
        frozenset({"input", "retrieved"}),
    ),
    (
        "tool_smuggling",
        0.7,
        _rule(
            r"\b(call|invoke|execute|run|use)\s+(the\s+)?(tool|function|command)\b[^.\n]{0,30}[(:=]|"
            r"\b(tool_call|function_call|tool_calls)\b"
        ),
        frozenset({"input", "retrieved"}),
    ),
    (
        "exfil_url",
        0.7,
        _rule(r"https?://[^\s]+[?&][a-z_]*(data|secret|token|key|password|exfil|payload)="),
        frozenset({"input", "retrieved"}),
    ),
    (
        "encoded_payload",
        0.4,
        _rule(r"\b(base64|rot13|hex)[- ]?(decode|encoded|encoding)\b|[a-z0-9+/]{120,}={0,2}"),
        frozenset({"input", "retrieved"}),
    ),
    (
        "authority_pressure",
        0.45,
        _rule(
            r"\b(ceo|cfo|cto|director|administrator|it department|security team|legal team|"
            r"management)\b[^.\n]{0,40}\b(says|said|ordered|authori[sz]ed|approved|wants|insists)\b"
            r"[^.\n]{0,40}\b(skip|bypass|no need|without|immediately|right now)\b"
        ),
        frozenset({"input"}),
    ),
    (
        "external_destination",
        0.25,
        _rule(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}|https?://"),
        frozenset({"input"}),
    ),
)


def normalize_for_scan(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).translate(_ZERO_WIDTH).casefold()
    joined = _SPACED.sub(lambda match: re.sub(r"[ .\-_]", "", match.group(0)), folded)
    return " ".join(joined.split())


def scan(text: str, *, profile: Profile = "input", threshold: float = THRESHOLD) -> InjectionVerdict:
    """Score ``text`` for injection signals; ``suspicious`` when the combined score >= threshold."""
    if not text or not text.strip():
        return InjectionVerdict(False, 0.0, ())
    normalized = normalize_for_scan(text)
    variants = (normalized, normalized.translate(_LEET))
    signals: list[Signal] = []
    for rule, weight, pattern, profiles in RULES:
        if profile not in profiles:
            continue
        for variant in variants:
            match = pattern.search(variant)
            if match is None:
                continue
            if rule in _NEGATABLE[profile] and _NEGATION.search(variant[: match.start()]):
                continue
            signals.append(Signal(rule, weight, match.group(0)[:120]))
            break
    combined = 1.0 - math.prod(1.0 - signal.weight for signal in signals)
    combined = round(combined, 3)
    return InjectionVerdict(combined >= threshold, combined, tuple(signals))
