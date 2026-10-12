"""Jinja2 environment with context-specific escaping filters.

Templates never interpolate free text without one of these filters:

* ``py``      – a valid Python literal (strings JSON-escaped, long strings split into implicit
  concatenation so the formatter can wrap them);
* ``py_tuple``– a tuple literal of strings;
* ``ident``   – a validated snake_case identifier (raises on anything else);
* ``toml`` / ``json`` – JSON-escaped string literals;
* ``md``      – Markdown-table-safe text (pipes, newlines and HTML neutralised).

``tests/test_generator.py`` scans every template to enforce this rule.
"""

from __future__ import annotations

import json
import re
import textwrap
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

TEMPLATE_ROOT = Path(__file__).parent / "templates" / "agent"
_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")
_IDENT_UPPER = re.compile(r"^[A-Z_][A-Z0-9_]*$")
STRING_WRAP = 72


class TemplateValueError(ValueError):
    pass


def split_exact(value: str, width: int = STRING_WRAP) -> list[str]:
    """Split at spaces into chunks of at most ``width`` chars; ''.join(parts) == value."""
    parts: list[str] = []
    start = 0
    while len(value) - start > width:
        cut = value.rfind(" ", start, start + width)
        cut = start + width if cut <= start else cut + 1
        parts.append(value[start:cut])
        start = cut
    parts.append(value[start:])
    return parts


def py_string(value: str) -> str:
    if len(value) <= STRING_WRAP:
        return json.dumps(value, ensure_ascii=True)
    return "(" + " ".join(json.dumps(part, ensure_ascii=True) for part in split_exact(value)) + ")"


def py_literal(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return repr(value)
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, str):
        return py_string(value)
    if isinstance(value, tuple):
        if not value:
            return "()"
        inner = ", ".join(py_literal(item) for item in value)
        return f"({inner},)" if len(value) == 1 else f"({inner})"
    if isinstance(value, list):
        return "[" + ", ".join(py_literal(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{py_literal(str(k))}: {py_literal(v)}" for k, v in value.items()) + "}"
    raise TemplateValueError(f"cannot render {type(value).__name__} as a Python literal")


def py_tuple(values: Any) -> str:
    return py_literal(tuple(str(value) for value in values))


def ident(value: Any) -> str:
    text = str(value)
    if not _IDENT.fullmatch(text):
        raise TemplateValueError(f"not a safe identifier: {text!r}")
    return text


def ident_upper(value: Any) -> str:
    text = str(value)
    if not _IDENT_UPPER.fullmatch(text):
        raise TemplateValueError(f"not a safe constant name: {text!r}")
    return text


def json_string(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True)


def markdown_cell(value: Any) -> str:
    text = " ".join(str(value).split())
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;")


def docstring_text(value: str, *, indent: int = 0, width: int = 92) -> str:
    """Sanitise text for use inside a triple-quoted docstring."""
    cleaned = " ".join(value.replace("\\", "/").replace('"""', "'''").split()).rstrip('"')
    if not cleaned:
        return ""
    lines = textwrap.wrap(cleaned, width - indent) or [cleaned]
    return ("\n" + " " * indent).join(lines)


def build_environment() -> Environment:
    environment = Environment(
        loader=FileSystemLoader(str(TEMPLATE_ROOT)),
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
        trim_blocks=False,
        lstrip_blocks=False,
    )
    environment.filters.update(
        py=py_literal,
        py_tuple=py_tuple,
        ident=ident,
        ident_upper=ident_upper,
        toml=json_string,
        json=json_string,
        md=markdown_cell,
    )
    return environment
