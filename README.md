# AgentForge

AgentForge turns a business requirement written in plain language into a **verified, downloadable agent repository**.

```text
"Build a property maintenance triage agent … require human approval before any work order is sent …"
                                   │
                                   ▼
   compile ──► AgentSpec v1 (validated, SHA-256 hashed) ──► plan ──► generate ──► sandbox gates ──► sign
                                                                                                    │
                                                                                                    ▼
                                                                                         Download source
```

What you download is a real project, not a demo:

```text
property-maintenance-triage-agent/
├── src/
│   ├── agent/        graph.py, state.py, prompts.py, nodes.py — a LangGraph state machine
│   ├── tools/        one typed, allowlisted module per tool (read / draft / execute)
│   ├── rag/          ingestion, embeddings, retrieval with citations and injection quarantine
│   ├── memory/       PII-redacted conversation memory, durable checkpoints
│   ├── guardrails/   prompt-injection scanner, PII redaction, action policy
│   └── api/          FastAPI service: runs, human approvals, health, metrics
├── mcp/              Model Context Protocol server (read-only tools + agent runs)
├── tests/            unit/, integration/, agent/ — 130–150 tests per generated agent
├── evals/            dataset.json (functional + adversarial cases) and graders.py
├── Dockerfile, docker-compose.yml, pyproject.toml, requirements*.lock, .env.example
├── agent-spec.yaml   the exact specification it was generated from
├── architecture.md   the verified topology, risks and components
└── .agentforge/      build evidence: test and eval reports, SBOM, provenance, signed manifest
```

Before an archive becomes downloadable, the generated repository's **own** lint, test suite and evaluation suite run inside a sandbox, its code is security-scanned, and the result is packaged with an Ed25519-signed manifest, a CycloneDX SBOM and SLSA provenance. A build that fails a gate never produces an artifact.

## How it works

| Stage | What happens | Evidence |
| --- | --- | --- |
| Compile | The requirement is analysed (deterministically, or model-assisted with safety invariants re-applied) into AgentSpec v1. Raw text never reaches the generator. | Spec SHA-256, assumptions, inferences |
| Plan | The workflow becomes a graph with an input guard, conditional exits and an approval gate. Six properties are proven, including *human approval dominates every side effect*. | Topology checks, risk register |
| Generate | Jinja templates render a deterministic repository: the same spec always produces byte-identical files. | File count, generator notes |
| Gates | Syntax, `ruff check`, `ruff format --check`, `pytest` with coverage and the offline evaluation suite run in the sandbox. Every number comes from JUnit, coverage.json or eval-report.json. | Test cases, coverage, eval cases |
| Repair | Lint failures get mechanical fixes; optionally a model proposes patches to `src/` only — never to tests or evals. | Repair attempts and diffs |
| Security | Secrets, dangerous calls, dependency pins, container and compose policy, seed knowledge, plus bandit. Critical and high findings block packaging. | Findings, SARIF |
| Package | Deterministic ZIP, `MANIFEST.sha256` signed with Ed25519, CycloneDX 1.6 SBOM, in-toto/SLSA provenance. | Archive digest, key ID |

## Quick start

### Everything in containers

Requirements: Docker Engine 25+ with Compose v2.

```bash
cp .env.example .env
docker compose up --build
```

Open <http://localhost:8080> (API reference at <http://localhost:8080/api/docs>). The stack runs nginx + workbench, API, Celery worker, beat, PostgreSQL and Redis. The worker sits on an internal network with no internet route; generated code runs in a separate hash-locked virtualenv with resource limits.

To sign artifacts, add a key to `.env`:

```bash
docker compose run --rm api python -m app.cli generate-signing-key
```

### Local development (no Docker, no Redis)

Python 3.12+ and Node 22+.

```bash
make bootstrap      # API virtualenv, web dependencies, agent runtime
make dev            # API with in-process builds on :8000, workbench on :5173
```

On Windows (PowerShell):

```powershell
py -3.12 -m venv .venv; .venv\Scripts\python -m pip install --require-hashes --no-deps -r services/api/requirements.lock
.venv\Scripts\python -m pip install --no-deps -e services/api
py -3.12 -m venv .venv-agent-runtime; .venv-agent-runtime\Scripts\python -m pip install --require-hashes --no-deps -r services/api/app/generator/runtime/requirements-dev.lock
npm --prefix apps/web ci
cd services/api
$env:AGENTFORGE_BUILD_DISPATCH="inline"; $env:AGENTFORGE_SANDBOX_PYTHON="$PWD\..\..\.venv-agent-runtime\Scripts\python.exe"; $env:AGENTFORGE_DATABASE_URL="sqlite:///./agentforge.db"
..\..\.venv\Scripts\alembic upgrade head
..\..\.venv\Scripts\uvicorn app.main:app --port 8000      # second terminal: npm --prefix apps/web run dev
```

The process sandbox applies kernel resource limits on Linux; on Windows it runs with a scrubbed environment and timeouts only, which is fine for development but not for untrusted workloads.

### Command line

The pipeline also runs without the web stack:

```bash
cd services/api
python -m app.cli compile "Build a customer support agent that …" -o agent-spec.yaml
python -m app.cli plan agent-spec.yaml
python -m app.cli generate agent-spec.yaml -o ./customer-support-agent      # render only
python -m app.cli build agent-spec.yaml -o ./artifacts                      # full verified build
python -m app.cli verify-artifact ./artifacts/<build-id>.zip --public-key agentforge.pub
```

## Repository

```text
agentforge/
├── apps/web/                    React 19 + TypeScript workbench (Vite, TanStack Query)
├── services/api/                FastAPI control plane, Celery worker, CLI
│   ├── app/compiler/            requirement → AgentSpec (domain packs, optional LLM analyzer)
│   ├── app/planner/             graph topology proofs and risk register
│   ├── app/generator/           templates for the generated repository, hash-locked runtime
│   ├── app/sandbox/             process and Docker sandboxes
│   ├── app/verification/        quality gates, report parsers, repair agent
│   ├── app/security/            static security validation and SARIF export
│   ├── app/packaging/           deterministic archives, signing, SBOM, provenance
│   ├── app/services/            build pipeline and lifecycle
│   ├── alembic/                 database migrations
│   └── tests/                   unit, API, pipeline and real-sandbox tests
├── scripts/verify_templates.py  generate every template and run its own gates
├── docs/                        architecture, AgentSpec reference, operations, ADRs
└── compose.yaml                 single-host production-shaped stack
```

## Quality gates for AgentForge itself

```bash
make lint test          # ruff + ESLint, pytest (240+ tests) + vitest
make test-sandbox       # full builds through the real process sandbox
make generated          # all ten templates: generate, lint, test, evaluate
```

CI runs the same checks, builds the three container images and verifies that each template's generated repository passes its own suite.

## Documentation

- [Architecture](docs/architecture.md): components, trust boundaries, data flow, failure model
- [AgentSpec v1 reference](docs/agentspec.md): every field, invariant and example
- [Generated repositories](docs/generated-repository.md): what users download and how to run it
- [Operations](docs/operations.md): deployment, authentication, sandbox backends, signing, observability
- [Decision records](docs/adr): why the boundaries are where they are
- [Security policy](SECURITY.md) and [contributing guide](CONTRIBUTING.md)
