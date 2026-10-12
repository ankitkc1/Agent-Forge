import py_compile
from pathlib import Path

from app.services.compiler import compile_requirement
from app.services.generator import generate_repository
from app.services.repository import write_repository
from app.services.security import validate_repository


def test_generated_repository_is_safe_and_python_compiles(tmp_path: Path) -> None:
    spec, _ = compile_requirement(
        "Build a customer support agent with documentation retrieval, human approval, "
        "and zero unsafe actions."
    )
    files = generate_repository(spec)
    assert len(files) >= 25
    assert "agent-spec.yaml" in files
    assert "src/agent/graph.py" in files
    assert "tests/agent/test_safety.py" in files
    assert validate_repository(files)
    write_repository(tmp_path, files)
    for source in (tmp_path / "src").rglob("*.py"):
        py_compile.compile(str(source), doraise=True)


def test_values_are_escaped_before_code_generation(tmp_path: Path) -> None:
    spec, _ = compile_requirement(
        "Build a market research analyst that cites sources and requires human review "
        "before publishing."
    )
    files = generate_repository(spec)
    write_repository(tmp_path, files)
    py_compile.compile(str(tmp_path / "src" / "agent" / "prompts.py"), doraise=True)
