from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from app.compiler import compile_requirement, spec_hash
from app.compiler.templates import TEMPLATES, TEMPLATES_BY_ID
from app.generator.engine import generate_repository
from app.generator.render import TEMPLATE_ROOT, TemplateValueError, ident, py_literal, split_exact
from app.generator.shared import textmatch
from app.schemas.agent_spec import AgentSpec

REQUESTED_TREE = (
    "src/agent/graph.py",
    "src/agent/state.py",
    "src/agent/prompts.py",
    "src/tools/registry.py",
    "src/rag/retriever.py",
    "src/memory/store.py",
    "src/api/main.py",
    "mcp/server.py",
    "tests/unit/test_tools.py",
    "tests/integration/test_api.py",
    "tests/agent/test_approval.py",
    "evals/dataset.json",
    "evals/graders.py",
    "Dockerfile",
    "docker-compose.yml",
    "pyproject.toml",
    ".env.example",
    "agent-spec.yaml",
    "architecture.md",
    "README.md",
)
SAFE_FILTERS = ("|py", "|py_tuple", "|ident", "|ident_upper", "|toml", "|json")
SAFE_EXPRESSIONS = {
    "agentforge_version",
    "spec_hash",
    "agent.display_name",
    "agent.package",
    "agent.cli",
    "tool.timeout_seconds",
    "tool.class_name",
    "tool.mode",
    "tool.mode_explanation",
    "tool.docstring",
    "tool.mcp_signature",
    "tool.mcp_arguments",
    "tool.mode|upper",
    "field.annotation",
    "field.default_expr",
    "key",
    "value",
    "step.docstring",
    "model.temperature",
    "model.max_output_tokens",
    "topology_diagram",
    # Literal-only conditional: can only ever render "yes" or "no".
    '"yes" if tool.approval_required else "no"',
}


@pytest.fixture(scope="module")
def maintenance():
    spec = compile_requirement(TEMPLATES_BY_ID["maintenance-triage"].requirement).spec
    return spec, generate_repository(spec)


def test_generated_tree_matches_the_requested_layout(maintenance) -> None:
    _, repository = maintenance
    for path in REQUESTED_TREE:
        assert path in repository.files, path
    assert not any(path.startswith("mcp/__init__") for path in repository.files)


def test_generation_is_deterministic(maintenance) -> None:
    spec, repository = maintenance
    assert generate_repository(spec).files == repository.files


def test_every_python_file_parses(maintenance) -> None:
    _, repository = maintenance
    for path, content in repository.files.items():
        if path.endswith(".py"):
            ast.parse(content, filename=path)


def test_spec_constants_are_embedded(maintenance) -> None:
    spec, repository = maintenance
    assert f'SPEC_SHA256: Final = "{spec_hash(spec)}"' in repository.files["src/agent/blueprint.py"]
    for step in spec.workflow:
        assert f'graph.add_node("{step.id}", nodes.{step.id})' in repository.files["src/agent/graph.py"]
    for tool in spec.tools:
        assert f"src/tools/{tool.name}.py" in repository.files


def test_free_text_is_rendered_as_data_only() -> None:
    base = compile_requirement(TEMPLATES_BY_ID["customer-support"].requirement).spec.model_dump(mode="json")
    payload = 'Evil """ text\\n\nimport os; os.system("rm -rf /")  # {{ 7*7 }} {% raw %}'
    base["agent"]["description"] = payload
    base["agent"]["constraints"] = [payload[:200]]
    base["tools"][0]["description"] = payload[:300]
    base["workflow"][0]["description"] = payload[:300]
    spec = AgentSpec.model_validate(base)
    repository = generate_repository(spec)
    for path, content in repository.files.items():
        if path.endswith(".py"):
            tree = ast.parse(content, filename=path)
            imported = {
                alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
            }
            assert "os" not in imported or path.startswith("src/") is False, path
            assert not any(
                isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "system"
                for node in ast.walk(tree)
            ), path
    assert "49" not in repository.files["README.md"].split("Evil", 1)[-1][:40]


def test_templates_only_interpolate_through_escaping_filters() -> None:
    offenders = []
    for template in TEMPLATE_ROOT.rglob("*.py.j2"):
        for expression in re.findall(r"\{\{\s*(.*?)\s*\}\}", template.read_text(encoding="utf-8")):
            if expression in SAFE_EXPRESSIONS or expression.endswith(SAFE_FILTERS):
                continue
            offenders.append(f"{template.name}: {{{{ {expression} }}}}")
    assert not offenders, offenders


def test_py_literal_round_trips_tricky_strings() -> None:
    for value in ['quote " and \\ backslash', "newline\nand tab\t", "ünïcödé — dash", "x" * 300, ""]:
        assert ast.literal_eval(py_literal(value)) == value
    assert ast.literal_eval(py_literal({"a": (1, 2.5, None, True), "b": ["c"]})) == {
        "a": (1, 2.5, None, True),
        "b": ["c"],
    }
    assert "".join(split_exact("word " * 40, 30)) == "word " * 40
    with pytest.raises(TemplateValueError):
        ident("bad-name; import os")


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda template: template.id)
def test_every_template_generates_a_consistent_dataset(template) -> None:
    spec = compile_requirement(template.requirement).spec
    repository = generate_repository(spec)
    dataset = json.loads(repository.files["evals/dataset.json"])
    categories = {case["category"] for case in dataset["cases"]}
    assert {"functional", "adversarial", "benign"} <= categories
    assert dataset["counts"]["adversarial"] == spec.evaluation.adversarial_cases
    classify = next(step for step in spec.workflow if step.kind == "classify")
    labels = [(label.name, label.hints) for label in classify.labels]
    for case in dataset["cases"]:
        expected = case["expect"].get("classification")
        if expected:
            assert textmatch.classify(case["input"], labels)[0] == expected, case["id"]
    fixtures = json.loads(repository.files["data/fixtures/tools.json"])
    for tool in spec.tools:
        if tool.mode == "read":
            assert tool.name in fixtures["tools"]


def test_generated_repository_carries_hashed_locks(maintenance) -> None:
    _, repository = maintenance
    lock = repository.files["requirements.lock"]
    assert "langgraph==" in lock and "--hash=sha256:" in lock
    assert "pytest==" not in lock
    assert "pytest==" in repository.files["requirements-dev.lock"]


def test_runtime_lock_matches_its_input(tmp_path: Path) -> None:
    runtime_in = (TEMPLATE_ROOT.parents[1] / "runtime" / "requirements-runtime.in").read_text()
    lock = (TEMPLATE_ROOT.parents[1] / "runtime" / "requirements-runtime.lock").read_text().lower()
    for line in runtime_in.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            name = re.split(r"[\[<>=]", line, maxsplit=1)[0].lower()
            assert f"\n{name}==" in "\n" + lock, name
