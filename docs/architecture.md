# Architecture

AgentForge is a compiler with a verification pipeline attached. Natural language goes in at one end;
at the other end is a signed archive whose contents passed their own tests in a sandbox. Everything
in between is designed so that the only thing crossing each boundary is a validated, typed artifact.

```text
            untrusted                       validated                      executed
┌──────────────────────────┐    ┌──────────────────────────────┐    ┌──────────────────────────┐
│ requirement (text)       │    │ AgentSpec v1 + SHA-256       │    │ generated repository     │
│                          │──► │ ArchitecturePlan (proved)    │──► │ in the sandbox           │
│ compiler (heuristic/LLM) │    │ templates (escaped context)  │    │ gates parse real reports │
└──────────────────────────┘    └──────────────────────────────┘    └──────────────────────────┘
                                                                              │
                                     signed ZIP + SBOM + provenance  ◄────────┘  security scan
```

## Components

| Component | Code | Responsibility |
| --- | --- | --- |
| Workbench | `apps/web` | Compose requirements, edit and validate specs, watch builds live, inspect evidence, download |
| API | `services/api/app/api` | Versioned HTTP contract, authentication, SSE build stream, artifact delivery |
| Compiler | `app/compiler` | Requirement → AgentSpec. Ten curated domain packs plus a general pack; optional LLM analyzer |
| Planner | `app/planner` | AgentSpec → graph topology, six verified properties, risk register |
| Generator | `app/generator` | Spec + plan → repository files via Jinja2 with per-context escaping filters |
| Sandbox | `app/sandbox` | Runs gate commands: process backend (venv + rlimits) or Docker backend (container per command) |
| Gates | `app/verification` | Quality, tests, evaluation; parses JUnit/coverage/eval JSON; bounded repair loop |
| Security | `app/security` | Static policy scan + bandit results; SARIF export |
| Packaging | `app/packaging` | Deterministic ZIP, Ed25519-signed manifest, CycloneDX SBOM, SLSA provenance |
| Pipeline | `app/services/pipeline.py` | Orchestrates the ten stages, persists every transition and event |
| Worker | `app/tasks` | Celery tasks (`builds` and `maintenance` queues), beat schedule for retention |

## Trust boundaries

1. **Requirement → spec.** Only the compiler sees raw requirement text. Its output is an `AgentSpec`
   (strict Pydantic, frozen, `extra="forbid"`), whose free-text fields are length-limited. When the
   optional LLM analyzer drafts a spec, deterministic code re-applies the safety invariants (execute
   tools require approval, allowlisted tools only, zero unsafe-action target, an approval step before
   execution) and the result is validated exactly like a hand-written document; any defect falls back
   to the deterministic analyzer.
2. **Spec → code.** `POST /builds` requires the spec *and* its canonical SHA-256; the worker re-hashes
   the stored spec before generating. Templates may only interpolate through escaping filters
   (`py`, `py_tuple`, `ident`, `toml`, `json`, `md`), and a test enforces that rule for every template.
   The generator writes only inside the workspace (path traversal is rejected).
3. **Code → execution.** Generated code is treated as untrusted. It runs only through the sandbox:
   an environment built from scratch (no inherited secrets or proxy settings), offline model, fixture
   tools, memory checkpoints, resource limits and a process-group kill on timeout or cancellation. The
   Docker backend adds no network, dropped capabilities, `no-new-privileges`, uid 65534 and optionally
   gVisor. Report files coming back from the sandbox are size-capped and parsed with defusedxml.
4. **Artifact → user.** Downloads are confined to the artifact root. Each archive carries a manifest of
   every file's digest, signed with the instance's Ed25519 key; `verify-artifact` detects modified,
   missing and added files, and a trusted public key detects re-signing.

## Pipeline

| # | Stage | Fails the build when |
| --- | --- | --- |
| 1 | Spec analysis | the stored spec no longer validates or its hash does not match |
| 2 | Architecture planner | any topology property fails |
| 3 | Risk analysis | a finding is open and blocking |
| 4 | Code generation | rendering fails or a path escapes the workspace |
| 5 | Static checks | syntax, `ruff check` or `ruff format --check` fail (after repair) |
| 6 | Sandbox tests | any test fails or errors, or no JUnit report is produced |
| 7 | Evaluation suite | targets are missed (when enforced) or no report is produced |
| 8 | Repair agent | — (runs only after a gate failure; bounded by `repair_max_attempts`) |
| 9 | Security validation | any critical or high finding (AgentForge rules or bandit) |
| 10 | Signed packaging | the archive cannot be written or signed |

Gate metrics are never estimated: tests and coverage come from `junit.xml` and `coverage.json`,
evaluation from `eval-report.json`, written by the generated repository inside the sandbox. Stale
reports are deleted before each run so an old pass cannot be reused.

## Verified topology

The planner derives a DAG from the workflow:

```text
START → guard_input ─(continue)→ step₁ → … → stepₙ → finalize → END
            └─(blocked)→ finalize
safety_check ─(blocked)→ finalize
human_approval ─(approved)→ execute     human_approval ─(rejected)→ finalize
```

and proves: every node is reachable; every node reaches END; the graph is acyclic; the input guard is
the only entry; **removing the approval nodes disconnects every side-effecting node** (approval
dominates side effects); side-effecting tools are bound only to proposal steps. The generated
repository re-checks the same properties in `tests/integration/test_graph_topology.py`.

## Data

| Store | Contents |
| --- | --- |
| PostgreSQL (`builds`, `build_events`) | spec, hash, status, stages, metrics, report JSON, artifact metadata, idempotency keys, event log |
| Redis | Celery broker (`noeviction`) and short-lived results |
| Artifact volume | `<build-id>.zip` archives; workspaces under `.workspaces/` are deleted after each build |

Builds past `AGENTFORGE_BUILD_RETENTION_DAYS` are purged daily (beat → `maintenance` queue), including
their archives.

## API surface

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/v1/specs/compile` | requirement → spec, hash, analysis, warnings |
| POST | `/api/v1/specs/validate` | YAML/JSON or object → errors with locations, or spec + hash + plan |
| POST | `/api/v1/specs/plan` | spec → architecture plan |
| GET | `/api/v1/specs/templates`, `/domains`, `/schema` | curated requirements, domain packs, JSON Schema |
| POST | `/api/v1/builds` | start a build (`Idempotency-Key` supported; 409 on hash mismatch, 429 at capacity) |
| GET | `/api/v1/builds` | cursor-paginated list, filter by status and agent |
| GET | `/api/v1/builds/{id}` | build with stages, metrics and recent events |
| GET | `/api/v1/builds/{id}/stream` | server-sent events: `build`, `log`, `end` |
| GET | `/api/v1/builds/{id}/events?after=` | event log |
| GET | `/api/v1/builds/{id}/report` | full build report (plan, gates, repairs, security, package) |
| GET | `/api/v1/builds/{id}/files`, `/files/{path}` | browse the packaged archive without extracting it |
| GET | `/api/v1/builds/{id}/artifact` | download (`X-Artifact-SHA256`, `Digest` headers) |
| POST | `/api/v1/builds/{id}/cancel`, `/retry` | lifecycle |
| DELETE | `/api/v1/builds/{id}` | remove a finished build and its archive |
| GET | `/api/v1/system`, `/system/signing-key` | instance configuration (authenticated), public signing key (public) |
| GET | `/health/live`, `/health/ready`, `/metrics` | probes and Prometheus metrics |

## Failure model

- Invalid requirements and specifications fail before any build exists (422 with field locations).
- A spec whose hash does not match is rejected with 409, before and again inside the worker.
- Queue unavailability marks the build failed and returns 503; capacity returns 429 with `Retry-After`.
- A gate failure is a terminal build state with evidence, not a task error; only infrastructure errors
  (database connectivity) are retried by Celery, with late acknowledgement and `reject_on_worker_lost`.
- Cancellation is cooperative: the sandbox polls `cancel_requested` and kills the process group or
  container; nothing is packaged.
- Artifacts exist only for builds that passed every blocking gate.

## Scaling

The API is stateless behind a load balancer. Workers scale independently and can be routed by queue.
PostgreSQL holds all coordination state. For multiple hosts, move archives to object storage with
short-lived signed URLs and run sandboxes on dedicated, isolated nodes (see [operations](operations.md)).
