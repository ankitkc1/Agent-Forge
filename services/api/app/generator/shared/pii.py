"""PII detection and redaction for logs, audit trails and long-term memory.

Pattern-based and dependency-free. Card numbers are confirmed with the Luhn checksum to avoid
redacting order numbers; identifiers with letter prefixes such as ``P-1001`` are never matched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("CARD", re.compile(r"(?<![\w-])(?:\d[ -]?){12,18}\d(?![\w-])")),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b")),
    (
        "PHONE",
        re.compile(
            r"(?<![\w-])(?:\+\d{1,3}[ .-]?)?(?:\(\d{1,4}\)[ .-]?)?\d{3,4}[ .-]?\d{3,4}(?:[ .-]?\d{2,4})?(?![\w-])"
        ),
    ),
    ("IP_ADDRESS", re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")),
)


@dataclass(frozen=True)
class PiiFinding:
    kind: str
    start: int
    end: int


def _luhn_valid(candidate: str) -> bool:
    digits = [int(char) for char in candidate if char.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    checksum = 0
    for index, digit in enumerate(reversed(digits)):
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def find_pii(text: str) -> list[PiiFinding]:
    findings: list[PiiFinding] = []
    taken: list[tuple[int, int]] = []
    for kind, pattern in _PATTERNS:
        for match in pattern.finditer(text):
            start, end = match.span()
            if any(start < other_end and end > other_start for other_start, other_end in taken):
                continue
            if kind == "CARD" and not _luhn_valid(match.group(0)):
                continue
            if kind == "PHONE" and sum(char.isdigit() for char in match.group(0)) < 8:
                continue
            findings.append(PiiFinding(kind, start, end))
            taken.append((start, end))
    return sorted(findings, key=lambda finding: finding.start)


def redact(text: str) -> tuple[str, list[str]]:
    """Replace PII with ``[REDACTED_<KIND>]`` markers; returns the text and the kinds found."""
    findings = find_pii(text)
    if not findings:
        return text, []
    parts: list[str] = []
    cursor = 0
    for finding in findings:
        parts.append(text[cursor : finding.start])
        parts.append(f"[REDACTED_{finding.kind}]")
        cursor = finding.end
    parts.append(text[cursor:])
    return "".join(parts), sorted({finding.kind for finding in findings})


def redact_value(value: object) -> object:
    """Recursively redact strings inside JSON-like structures."""
    if isinstance(value, str):
        return redact(value)[0]
    if isinstance(value, dict):
        return {key: redact_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [redact_value(item) for item in value]
    return value
