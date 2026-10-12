"""Deterministic keyword matching.

This module is the single source of truth for hint matching. AgentForge uses it to compute the
expected outcomes of generated evaluation cases, and the generator copies this exact file into
every generated repository (``src/agent/textmatch.py``) where the offline model uses it. Keeping
one implementation guarantees that offline evaluations measure the agent's control flow rather
than disagreements between two matchers. Standard library only.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence

_NON_WORD = re.compile(r"[^a-z0-9]+")
_SUFFIXES = frozenset({"", "s", "es", "ed", "d", "ing", "er", "ers", "y"})
FALLBACK_LABEL_NAMES = ("other", "general", "unknown", "uncategorized", "uncategorised")


def normalize(text: str) -> str:
    """Casefold, strip accents/punctuation and collapse whitespace."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(_NON_WORD.sub(" ", folded).split())


def tokens(text: str) -> list[str]:
    return normalize(text).split()


def _word_matches(word: str, hint: str) -> bool:
    return word.startswith(hint) and word[len(hint) :] in _SUFFIXES


def count_hint(text_tokens: Sequence[str], hint: str) -> int:
    """Count occurrences of a (possibly multi-word) hint with light suffix tolerance."""
    hint_tokens = normalize(hint).split()
    if not hint_tokens:
        return 0
    width = len(hint_tokens)
    total = 0
    for start in range(len(text_tokens) - width + 1):
        window = text_tokens[start : start + width]
        if window[:-1] == hint_tokens[:-1] and _word_matches(window[-1], hint_tokens[-1]):
            total += 1
    return total


def score(text: str, hints: Iterable[str]) -> int:
    text_tokens = tokens(text)
    return sum(count_hint(text_tokens, hint) for hint in hints)


def label_hints(name: str, hints: Sequence[str]) -> tuple[str, ...]:
    """A label always matches its own name ("general_repair" -> "general repair")."""
    implicit = name.replace("_", " ")
    return (implicit, *[hint for hint in hints if hint != implicit])


def fallback_label(names: Sequence[str]) -> str:
    for name in names:
        if name in FALLBACK_LABEL_NAMES or name.startswith("general"):
            return name
    return names[0]


def classify(text: str, labels: Sequence[tuple[str, Sequence[str]]]) -> tuple[str, float, int]:
    """Return ``(label, confidence, score)`` using hint counts; ties keep declaration order."""
    if not labels:
        raise ValueError("at least one label is required")
    scored = [(name, score(text, label_hints(name, hints))) for name, hints in labels]
    ranked = sorted(scored, key=lambda item: -item[1])
    best_name, best_score = ranked[0]
    if best_score == 0:
        return fallback_label([name for name, _ in labels]), 0.0, 0
    runner_up = ranked[1][1] if len(ranked) > 1 else 0
    confidence = round(best_score / (best_score + runner_up + 1), 3)
    return best_name, confidence, best_score


def assess(text: str, levels: Sequence[tuple[str, Sequence[str]]]) -> tuple[str, int]:
    """Pick the level with most hint matches; ties escalate; no signal picks the middle level."""
    if len(levels) < 2:
        raise ValueError("at least two levels are required")
    best_index = (len(levels) - 1) // 2
    best_score = 0
    for index, (name, hints) in enumerate(levels):
        level_score = score(text, label_hints(name, hints))
        if level_score and level_score >= best_score:
            best_index, best_score = index, level_score
    return levels[best_index][0], best_score
