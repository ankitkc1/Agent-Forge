"""AgentForge command line.

agentforge compile "Build a maintenance triage agent ..." -o agent-spec.yaml
agentforge validate agent-spec.yaml
agentforge plan agent-spec.yaml
agentforge generate agent-spec.yaml -o ./maintenance-agent
agentforge build agent-spec.yaml -o ./artifacts          # full pipeline, no Celery/Redis needed
agentforge generate-signing-key
agentforge verify-artifact ./artifacts/<id>.zip
agentforge purge-builds
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml


def _load_spec(path: Path):  # type: ignore[no-untyped-def]
    from app.compiler.validation import validate_document

    outcome = validate_document(path.read_text(encoding="utf-8"))
    if not outcome.valid or outcome.spec is None:
        for issue in outcome.errors:
            print(f"error: {issue.loc}: {issue.message}", file=sys.stderr)
        raise SystemExit(2)
    for warning in outcome.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return outcome.spec


def cmd_compile(args: argparse.Namespace) -> int:
    from app.compiler import compile_requirement

    requirement = (
        Path(args.requirement[1:]).read_text(encoding="utf-8")
        if args.requirement.startswith("@")
        else args.requirement
    )
    result = compile_requirement(requirement)
    document = yaml.safe_dump(result.spec.model_dump(mode="json"), sort_keys=False, width=100)
    if args.output:
        Path(args.output).write_text(document, encoding="utf-8")
    else:
        print(document)
    print(
        f"# sha256 {result.spec_hash} · domain {result.analysis.domain} · confidence {result.analysis.confidence}",
        file=sys.stderr,
    )
    for note in [*result.analysis.assumptions, *result.analysis.inferences, *result.warnings]:
        print(f"# {note}", file=sys.stderr)
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    from app.compiler import spec_hash

    spec = _load_spec(Path(args.spec))
    print(f"valid · sha256 {spec_hash(spec)}")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    from app.planner.architecture import plan_architecture

    plan = plan_architecture(_load_spec(Path(args.spec)))
    for check in plan.checks:
        print(f"{'PASS' if check.passed else 'FAIL'}  {check.title} — {check.detail}")
    print(f"risk level: {plan.risk.level}{' (blocking)' if plan.risk.blocking else ''}")
    for finding in plan.risk.findings:
        print(f"  [{finding.severity}/{finding.status}] {finding.title}")
    print(plan.mermaid)
    return 0 if plan.passed else 1


def cmd_generate(args: argparse.Namespace) -> int:
    from app.generator.engine import generate_repository

    repository = generate_repository(_load_spec(Path(args.spec)))
    output = Path(args.output)
    if output.exists() and any(output.iterdir()) and not args.force:
        print(f"error: {output} is not empty (use --force)", file=sys.stderr)
        return 2
    for relative, content in repository.files.items():
        target = output.joinpath(*relative.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    print(f"wrote {len(repository.files)} files to {output}")
    for note in repository.notes:
        print(f"note: {note}")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.compiler import spec_hash
    from app.core.config import get_settings
    from app.db.base import Base
    from app.models.build import BuildRecord
    from app.services.pipeline import execute_build, initial_stages

    spec = _load_spec(Path(args.spec))
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    database = output / "builds.db"
    settings = get_settings().model_copy(
        update={
            "artifact_root": output,
            "database_url": f"sqlite:///{database}",
            "workspace_root": output / ".workspaces",
        }
    )
    engine = create_engine(settings.database_url)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        record = BuildRecord(
            agent_name=spec.agent.name,
            spec_hash=spec_hash(spec),
            spec=spec.model_dump(mode="json"),
            status="queued",
            progress=0.0,
            stages=initial_stages(),
            requested_by="cli",
        )
        session.add(record)
        session.commit()
        build_id = str(record.id)
    status = execute_build(build_id, settings=settings, session_factory=session_factory)
    with session_factory() as session:
        record = session.get(BuildRecord, record.id)
        assert record is not None
        for stage in record.stages:
            print(f"{stage['status']:>9}  {stage['name']:<22} {stage.get('summary') or ''}")
        if record.metrics:
            print(json.dumps(record.metrics, indent=2))
        if record.artifact_path:
            print(f"artifact: {record.artifact_path}\nsha256:   {record.artifact_sha256}")
        if record.error:
            print(f"error: {record.error}", file=sys.stderr)
    return 0 if status == "succeeded" else 1


def cmd_generate_signing_key(_: argparse.Namespace) -> int:
    from app.packaging.signing import generate_key

    seed, public_pem = generate_key()
    print("# Add to your secret store / .env (keep private):")
    print(f"AGENTFORGE_SIGNING_KEY={seed}")
    print("\n# Public key (share with artifact consumers):")
    print(public_pem)
    return 0


def cmd_verify_artifact(args: argparse.Namespace) -> int:
    from app.packaging.archive import verify_package

    trusted = Path(args.public_key).read_text(encoding="utf-8") if args.public_key else None
    result = verify_package(Path(args.artifact), trusted_public_pem=trusted)
    print(json.dumps(result, indent=2))
    if result["valid"] and trusted is None and result["signature_valid"]:
        print(
            "note: the signature was checked against the key embedded in the archive; pass "
            "--public-key with the key published by your AgentForge instance to verify origin.",
            file=sys.stderr,
        )
    return 0 if result["valid"] else 1


def cmd_purge(_: argparse.Namespace) -> int:
    from app.core.config import get_settings
    from app.db.session import SessionLocal
    from app.services.builds import purge_expired

    with SessionLocal() as session:
        print(f"purged {purge_expired(session, get_settings())} build(s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agentforge", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    compile_parser = commands.add_parser("compile", help="compile a requirement (or @file) into an AgentSpec")
    compile_parser.add_argument("requirement")
    compile_parser.add_argument("-o", "--output")
    compile_parser.set_defaults(handler=cmd_compile)
    for name, handler, help_text in (
        ("validate", cmd_validate, "validate an AgentSpec YAML/JSON file"),
        ("plan", cmd_plan, "print the verified architecture plan"),
    ):
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument("spec")
        sub.set_defaults(handler=handler)
    generate = commands.add_parser("generate", help="render the repository without running gates")
    generate.add_argument("spec")
    generate.add_argument("-o", "--output", required=True)
    generate.add_argument("--force", action="store_true")
    generate.set_defaults(handler=cmd_generate)
    build = commands.add_parser("build", help="run the full verified pipeline locally")
    build.add_argument("spec")
    build.add_argument("-o", "--output", default="./artifacts")
    build.set_defaults(handler=cmd_build)
    commands.add_parser("generate-signing-key", help="create an Ed25519 signing key").set_defaults(
        handler=cmd_generate_signing_key
    )
    verify = commands.add_parser("verify-artifact", help="verify an artifact's manifest and signature")
    verify.add_argument("artifact")
    verify.add_argument("--public-key", help="PEM public key of the AgentForge instance that signed it")
    verify.set_defaults(handler=cmd_verify_artifact)
    commands.add_parser("purge-builds", help="delete builds past the retention period").set_defaults(
        handler=cmd_purge
    )
    args = parser.parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    sys.exit(main())
