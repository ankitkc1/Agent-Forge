#!/usr/bin/env python3
"""Generate every curated template's repository and run *its own* quality gates.

This is the same verification the build pipeline performs in the sandbox, run directly against a
local agent runtime so generator changes can be checked in one command (and in CI):

    python scripts/verify_templates.py --runtime .venv-agent-runtime/bin/python
    python scripts/verify_templates.py --runtime /opt/agent-runtime/bin/python --template customer-support

Exit status is non-zero if any repository fails lint, formatting, tests or its evaluation targets.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))

from app.compiler import compile_requirement  # noqa: E402
from app.compiler.templates import TEMPLATES, TEMPLATES_BY_ID  # noqa: E402
from app.generator.engine import generate_repository  # noqa: E402
from app.sandbox.base import SANDBOX_ENV  # noqa: E402

GATES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("lint", ("-m", "ruff", "check", "--no-cache", "--output-format", "concise", ".")),
    ("format", ("-m", "ruff", "format", "--no-cache", "--check", ".")),
    (
        "tests",
        (
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--cov=src",
            "--cov-report=json:.agentforge-out/coverage.json",
        ),
    ),
    ("evals", ("-m", "evals.run", "--report", ".agentforge-out/eval-report.json")),
)


def run_gates(template_id: str, runtime: Path, keep: Path | None) -> dict[str, object]:
    spec = compile_requirement(TEMPLATES_BY_ID[template_id].requirement).spec
    repository = generate_repository(spec)
    workdir = Path(tempfile.mkdtemp(prefix=f"agentforge-{template_id}-", dir=keep))
    for relative, content in repository.files.items():
        target = workdir.joinpath(*relative.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    (workdir / ".agentforge-out").mkdir()
    env = {
        **SANDBOX_ENV,
        "PATH": os.pathsep.join([str(runtime.parent), os.environ.get("PATH", "")]),
        "PYTHONPATH": str(workdir),
    }
    if os.name == "nt":
        env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", r"C:\Windows")
    result: dict[str, object] = {
        "template": template_id,
        "files": len(repository.files),
        "path": str(workdir),
    }
    for name, argv in GATES:
        started = time.perf_counter()
        completed = subprocess.run(  # fixed argv, local runtime interpreter
            [str(runtime), *argv],
            cwd=workdir,
            env=env,
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )
        result[name] = {
            "ok": completed.returncode == 0,
            "seconds": round(time.perf_counter() - started, 1),
            "tail": completed.stdout[-1500:] + completed.stderr[-800:],
        }
    coverage = workdir / ".agentforge-out" / "coverage.json"
    if coverage.is_file():
        result["coverage"] = round(json.loads(coverage.read_text())["totals"]["percent_covered"], 1)
    report = workdir / ".agentforge-out" / "eval-report.json"
    if report.is_file():
        data = json.loads(report.read_text())
        result["eval"] = {
            key: data["metrics"][key] for key in ("cases", "passed_cases", "task_success", "unsafe_actions")
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--runtime", required=True, type=Path, help="python of the agent runtime virtualenv")
    parser.add_argument(
        "--template", action="append", choices=sorted(TEMPLATES_BY_ID), help="limit to these templates"
    )
    parser.add_argument(
        "--keep", type=Path, help="write repositories under this directory instead of the system temp dir"
    )
    parser.add_argument("--json", action="store_true", help="print machine-readable results")
    args = parser.parse_args()
    if not args.runtime.exists():
        parser.error(f"runtime interpreter not found: {args.runtime} (create it with `make runtime`)")
    if args.keep:
        args.keep.mkdir(parents=True, exist_ok=True)
    selected = args.template or [template.id for template in TEMPLATES]
    results = [run_gates(template_id, args.runtime, args.keep) for template_id in selected]
    failed = [r for r in results if not all(r[gate]["ok"] for gate, _ in GATES)]  # type: ignore[index]
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            gates = "  ".join(f"{name} {'ok' if r[name]['ok'] else 'FAIL'}" for name, _ in GATES)  # type: ignore[index]
            evaluation = r.get("eval") or {}
            print(
                f"{r['template']:<22} {r['files']:>3} files  {gates}  coverage {r.get('coverage', '—')}%  "
                f"evals {evaluation.get('passed_cases', '—')}/{evaluation.get('cases', '—')}"
            )
        for r in failed:
            for name, _ in GATES:
                gate = r[name]  # type: ignore[index]
                if not gate["ok"]:
                    print(f"\n--- {r['template']} · {name} ({r['path']})\n{gate['tail']}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
