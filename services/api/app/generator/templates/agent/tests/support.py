"""Test helpers (importable as ``tests.support``)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine
from functools import cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coroutine)


@cache
def load_dataset() -> dict[str, Any]:
    return json.loads((ROOT / "evals" / "dataset.json").read_text(encoding="utf-8"))


def cases(*categories: str) -> list[dict[str, Any]]:
    return [case for case in load_dataset()["cases"] if case["category"] in categories]


def case_ids(case: dict[str, Any]) -> str:
    return str(case["id"])
