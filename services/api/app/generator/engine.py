"""Repository generator: renders a validated AgentSpec + verified plan into a source tree.

Generation is a pure function of (spec, AgentForge version): the same specification always yields
byte-identical files, which makes builds reproducible and diffs reviewable.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import yaml

from app import __version__
from app.compiler import spec_hash as compute_spec_hash
from app.generator.context import build_context
from app.generator.render import TEMPLATE_ROOT, build_environment
from app.generator.samples import build_samples
from app.planner.architecture import plan_architecture
from app.schemas.agent_spec import AgentSpec
from app.schemas.plan import ArchitecturePlan

GENERATOR_SCHEMA = "agentforge.generator/v1"
SHARED_ROOT = Path(__file__).parent / "shared"
RUNTIME_LOCKS = Path(__file__).parent / "runtime"
SHARED_MODULES = {
    "textmatch.py": "src/agent/textmatch.py",
    "injection.py": "src/guardrails/injection.py",
    "pii.py": "src/guardrails/pii.py",
}
PER_TOOL_TEMPLATE = "src/tools/_tool.py.j2"
DEFERRED = {"README.md.j2"}


@dataclass
class GeneratedRepository:
    files: dict[str, str]
    notes: list[str] = field(default_factory=list)
    formatted: bool = False

    @property
    def total_bytes(self) -> int:
        return sum(len(content.encode("utf-8")) for content in self.files.values())


def _output_path(template_path: str) -> str:
    parts = [
        "." + part[4:] if part.startswith("dot-") else part for part in PurePosixPath(template_path).parts
    ]
    path = "/".join(parts)
    return path.removesuffix(".j2")


def _tree(paths: list[str]) -> str:
    top_level: dict[str, set[str]] = {}
    for path in sorted(paths):
        parts = path.split("/")
        if len(parts) == 1:
            top_level.setdefault(parts[0], set())
        else:
            top_level.setdefault(parts[0] + "/", set()).add(parts[1] + ("/" if len(parts) > 2 else ""))
    lines: list[str] = []
    for name in sorted(top_level, key=lambda item: (not item.endswith("/"), item)):
        lines.append(name)
        children = sorted(top_level[name], key=lambda item: (not item.endswith("/"), item))
        for index, child in enumerate(children[:12]):
            lines.append(("└── " if index == len(children[:12]) - 1 else "├── ") + child)
    return "\n".join(lines) + "\n"


def format_python(files: dict[str, str]) -> bool:
    """Normalise Python formatting with ruff (does not change semantics). Returns success."""
    python_files = {path: content for path, content in files.items() if path.endswith(".py")}
    with tempfile.TemporaryDirectory(prefix="agentforge-fmt-") as directory:
        root = Path(directory)
        (root / "pyproject.toml").write_text(files.get("pyproject.toml", ""), encoding="utf-8")
        for path, content in python_files.items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        ruff = shutil.which("ruff")
        command = [ruff] if ruff else [sys.executable, "-m", "ruff"]
        try:
            result = subprocess.run(
                [*command, "format", "--quiet", "."],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        if result.returncode != 0:
            return False
        for path in python_files:
            files[path] = (root / path).read_text(encoding="utf-8")
    return True


def generate_repository(spec: AgentSpec, plan: ArchitecturePlan | None = None) -> GeneratedRepository:
    plan = plan or plan_architecture(spec)
    if not plan.passed:
        raise ValueError("refusing to generate from a plan that failed verification")
    digest = compute_spec_hash(spec)
    samples = build_samples(spec, plan)
    context = build_context(spec, plan, samples, spec_hash=digest, version=__version__)
    environment = build_environment()
    files: dict[str, str] = {}

    for template in sorted(TEMPLATE_ROOT.rglob("*")):
        if not template.is_file() or "__pycache__" in template.parts:
            continue
        relative = template.relative_to(TEMPLATE_ROOT).as_posix()
        if relative == PER_TOOL_TEMPLATE or relative in DEFERRED:
            continue
        output = _output_path(relative)
        if relative.endswith(".j2"):
            files[output] = environment.get_template(relative).render(**context)
        else:
            files[output] = template.read_text(encoding="utf-8")

    tool_template = environment.get_template(PER_TOOL_TEMPLATE)
    for tool in context["tools"]:
        files[f"src/tools/{tool['name']}.py"] = tool_template.render(**context, tool=tool)
    for source, target in SHARED_MODULES.items():
        files[target] = (SHARED_ROOT / source).read_text(encoding="utf-8")

    spec_document = spec.model_dump(mode="json")
    header = (
        f"# AgentSpec v{spec.version} — compiled by AgentForge {__version__}\n"
        f"# SHA-256 of the canonical JSON form: {digest}\n"
        "# Edit, then regenerate with AgentForge; tests/unit/test_spec.py detects drift.\n"
    )
    files["agent-spec.yaml"] = header + yaml.safe_dump(
        spec_document, sort_keys=False, allow_unicode=False, width=100
    )
    files["data/fixtures/tools.json"] = json.dumps(samples.fixtures, indent=2) + "\n"
    files["evals/dataset.json"] = json.dumps(samples.dataset, indent=2, ensure_ascii=False) + "\n"
    files.update(samples.knowledge)
    files["requirements.lock"] = (RUNTIME_LOCKS / "requirements-runtime.lock").read_text(encoding="utf-8")
    files["requirements-dev.lock"] = (RUNTIME_LOCKS / "requirements-dev.lock").read_text(encoding="utf-8")

    formatted = format_python(files)
    context["tree"] = _tree([*files, "README.md"])
    files["README.md"] = environment.get_template("README.md.j2").render(**context)

    for path in files:
        pure = PurePosixPath(path)
        if pure.is_absolute() or ".." in pure.parts:
            raise ValueError(f"unsafe generated path: {path}")
    notes = list(samples.notes)
    if not formatted:
        notes.append("ruff was unavailable during generation; Python files were not pre-formatted.")
    return GeneratedRepository(files=dict(sorted(files.items())), notes=notes, formatted=formatted)
