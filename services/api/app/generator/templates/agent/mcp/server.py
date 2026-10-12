"""Launcher for the agent's MCP server (keeps the repository root importable).

This directory intentionally has no ``__init__.py`` so it never shadows the ``mcp`` SDK package.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.mcp_server import main  # noqa: E402

if __name__ == "__main__":
    main()
