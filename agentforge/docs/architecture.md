# Architecture

## Core invariant

```text
untrusted requirement
        │
        ▼
deterministic compiler ──► validated AgentSpec + SHA-256
                                      │
                                      ▼
                            durable build record
                                      │
                                      ▼
                             queued worker pipeline
                                      │
             ┌────────────────────────┼────────────────────────┐
             ▼                        ▼                        ▼
       source generator          quality gates             evaluators
             │                        │                        │
             └────────────────────────┴────────────────────────┘
                                      │
                                      ▼
                              security validator
                                      │
                                      ▼
                              immutable ZIP artifact
```

The requirement compiler is the only component allowed to receive raw business text. `POST /api/v1/builds` accepts a Pydantic-validated AgentSpec and its canonical hash. The worker validates both again before rendering templates.

## Services

### Web

The React workbench compiles requirements, renders YAML/JSON contracts, submits builds, polls durable state, and downloads successful artifacts. TanStack Query owns server state; component state is limited to the current draft and presentation controls.

### API

FastAPI provides versioned contracts, request IDs, structured logging, security headers, metrics, readiness checks, and artifact delivery. SQLAlchemy writes build records; Alembic owns schema evolution.

### Worker

Celery consumes build IDs, then reloads the immutable specification from PostgreSQL. Stages are idempotent at the record level, progress is persisted after every transition, and worker crashes are retried with late acknowledgement.

The development worker executes generated code only from deterministic templates in an ephemeral directory. Internet-facing production must execute artifacts in a stronger separate sandbox boundary with no network by default, an immutable filesystem, seccomp/AppArmor, tight CPU/memory/PID limits, and a short deadline.

### Data

- PostgreSQL: AgentSpecs, build lifecycle, metrics, audit logs, artifact metadata.
- Redis: Celery broker and short-lived task results.
- Artifact volume: ZIP files. Replace with S3/R2/GCS plus signed URLs in multi-node deployments.

## Failure model

- Invalid requirements/specifications fail before task creation.
- A hash mismatch returns `409 Conflict`.
- Queue unavailability marks the build failed and returns `503`.
- Each pipeline exception marks the active stage failed and persists a sanitized error.
- Artifacts are unavailable until every blocking gate passes.
- Downloads are confined to the configured artifact root.

## Horizontal scaling

The API is stateless and can scale behind a load balancer. Worker concurrency is independent. PostgreSQL and object storage provide coordination. Use queue routing to separate CPU-heavy builds, security scans, and model-backed evaluation pools.

