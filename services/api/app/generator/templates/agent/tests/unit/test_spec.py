"""The generated code must stay consistent with agent-spec.yaml."""

from __future__ import annotations

import hashlib
import json

import yaml

from src.agent import blueprint
from src.tools.catalog import DEFINITIONS, ToolName
from tests.support import ROOT


def load_spec() -> dict:
    return yaml.safe_load((ROOT / "agent-spec.yaml").read_text(encoding="utf-8"))


def test_spec_hash_matches_generated_code() -> None:
    canonical = json.dumps(load_spec(), sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(canonical).hexdigest() == blueprint.SPEC_SHA256, (
        "agent-spec.yaml changed without regenerating the code"
    )


def test_workflow_matches_spec() -> None:
    assert [step["id"] for step in load_spec()["workflow"]] == list(blueprint.WORKFLOW)
    for step in load_spec()["workflow"]:
        config = blueprint.STEPS[step["id"]]
        assert config.kind == step["kind"]


def test_tool_allowlist_matches_spec() -> None:
    declared = {tool["name"] for tool in load_spec()["tools"]}
    assert declared == {tool.value for tool in ToolName}
    assert declared == {definition.name for definition in DEFINITIONS}


def test_side_effect_tools_require_approval() -> None:
    for definition in DEFINITIONS:
        if definition.mode == "execute":
            assert definition.approval_required, definition.name


def test_guardrails_are_enabled() -> None:
    spec = load_spec()
    assert spec["guardrails"]["tool_execution"]["allowlist_only"] is True
    assert blueprint.GUARDRAILS["max_tool_calls"] >= 1
