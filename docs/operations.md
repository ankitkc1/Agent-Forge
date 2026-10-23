# Operations

How to run AgentForge beyond a laptop: configuration, authentication, sandbox isolation, signing,
observability, retention and upgrades. All settings are environment variables prefixed with
`AGENTFORGE_`; `.env.example` lists them with defaults.

## Deployment shapes

| Shape | Builds run in | Use for |
| --- | --- | --- |
| `make dev` | the API process (`BUILD_DISPATCH=inline`), SQLite | local development only (refused in production) |
| `docker compose up` | Celery worker, process sandbox, PostgreSQL, Redis | single host, trusted users |
| Kubernetes / VMs | Celery workers on dedicated nodes, Docker sandbox with gVisor on a separate daemon | multi-tenant or internet-facing |

## Production settings

`AGENTFORGE_ENV=production` turns on startup guards. The API refuses to start when:

- `AUTH_MODE` is `none`, or `api_key` without `API_KEYS`;
- the database URL still uses the development credentials;
- `BUILD_DISPATCH=inline`;
- the artifact signing key is absent or invalid;
- the Docker sandbox is selected without a dedicated `SANDBOX_DOCKER_HOST`.

Recommended baseline:

```bash
AGENTFORGE_ENV=production
AGENTFORGE_AUTH_MODE=trusted_header                 # behind oauth2-proxy / Cloudflare Access / IAP
AGENTFORGE_TRUSTED_USER_HEADER=X-Forwarded-Email    # the proxy must strip this header from clients
AGENTFORGE_DATABASE_URL=postgresql+psycopg://agentforge:<secret>@db.internal:5432/agentforge
AGENTFORGE_REDIS_URL=rediss://:<secret>@redis.internal:6380/0
AGENTFORGE_SIGNING_KEY=<base64 Ed25519 seed from your secret store>
AGENTFORGE_BUILD_RETENTION_DAYS=30
```

### Authentication

- `api_key`: clients send `Authorization: Bearer <key>` or `X-API-Key`. Store digests, not keys:
  `AGENTFORGE_API_KEYS=sha256:<hex>,sha256:<hex>`. Comparison is constant-time. The workbench asks for a
  key when the server requires one and keeps it in the browser tab (optionally on the device).
- `trusted_header`: identity comes from an authenticating reverse proxy. Only safe when that proxy is
  the sole path to the API and strips the header from incoming requests.

Build records store the requesting principal (`requested_by`). In authenticated modes, build lists,
events, reports, previews, downloads, retries, cancellations and deletions are scoped to that
principal. Idempotency keys are scoped the same way, so different users can safely reuse a key.
Development mode remains a shared workspace. `GET /api/v1/system/signing-key` is intentionally
public; everything else under `/api/v1` requires authentication.

## Sandbox backends

Generated code is untrusted until it has passed the gates, and it is always executed through a
sandbox.

### Process (default)

The worker runs gate commands with `AGENTFORGE_SANDBOX_PYTHON`, a separate virtualenv installed from
`app/generator/runtime/requirements-dev.lock` (in the API image at `/opt/agent-runtime`). Each command
gets an environment built from scratch (no worker secrets, no proxy variables), its own `HOME` and
`TMPDIR` inside the workspace, `setrlimit` caps (address space, CPU time, file size, open files,
processes), a new session that is killed as a group on timeout or cancellation, and size-capped output.

Network isolation comes from the deployment: in `compose.yaml` the worker joins only the internal
`backend` network. Keep it that way; if you enable model-assisted repair, give the worker egress
through an allowlisting proxy rather than a general route.

### Docker

```bash
docker build -f services/api/sandbox.Dockerfile -t agentforge/sandbox-runtime:1.0.0 services/api
AGENTFORGE_SANDBOX_BACKEND=docker
AGENTFORGE_SANDBOX_DOCKER_HOST=tcp://sandbox-daemon.internal:2376
AGENTFORGE_SANDBOX_DOCKER_TLS_VERIFY=true
AGENTFORGE_SANDBOX_DOCKER_CERT_PATH=/run/secrets/sandbox-tls      # ca.pem, cert.pem, key.pem
AGENTFORGE_SANDBOX_DOCKER_RUNTIME=runsc                           # gVisor, strongly recommended
```

Every command runs in a fresh container: `NetworkMode=none`, all capabilities dropped,
`no-new-privileges`, uid 65534, memory = swap limit, CPU quota, PID limit, a size-limited `/tmp`, and the
workspace copied in and the reports copied out through the Engine API. Containers are force-removed
afterwards, including on timeout and cancellation.

Point `SANDBOX_DOCKER_HOST` at a **dedicated** daemon on an isolated host (or VM) that runs nothing
else. Never give the worker the host's Docker socket: access to it is root on that host.

## Artifact signing

```bash
docker compose run --rm api python -m app.cli generate-signing-key
```

Store the seed in your secret manager as `AGENTFORGE_SIGNING_KEY` (base64 seed or PKCS#8 PEM) and
publish the public key (`GET /api/v1/system/signing-key`). Each archive's `.agentforge/MANIFEST.sha256`
is signed; `verify-artifact --public-key` checks every file, rejects added or removed files and
detects re-signing with a different key. To rotate, deploy the new key with a new
`AGENTFORGE_SIGNING_KEY_ID`; old archives stay verifiable with the old public key.

Production mode will not start without a valid Ed25519 signing key. Development and test instances
may still create unsigned archives so contributors can run the pipeline without production secrets.

## Observability

- **Logs**: structured JSON (structlog) with `request_id`; build events are also persisted per build
  and streamed to the workbench.
- **Metrics** (`/metrics`, Prometheus): `agentforge_http_requests_total{method,path,status}`,
  `agentforge_http_request_duration_seconds`, `agentforge_builds{status}`.
- **Health**: `/health/live` (process) and `/health/ready` (database reachable). nginx answers
  `/healthz` itself.
- Useful alerts: builds stuck in `running` longer than `4 × SANDBOX_TIMEOUT_SECONDS` (the Celery hard
  limit), failure ratio by stage, queue depth of `builds`, artifact volume usage.

## Capacity and limits

| Setting | Default | Effect |
| --- | --- | --- |
| `MAX_ACTIVE_BUILDS` | 20 | queued + running builds; beyond this `POST /builds` returns 429 |
| `SANDBOX_TIMEOUT_SECONDS` | 300 | per gate command; Celery's hard limit is 4× this plus 5 minutes |
| `SANDBOX_MEMORY_MB` / `SANDBOX_CPU_SECONDS` / `SANDBOX_MAX_PROCESSES` | 2048 / 300 / 512 | per command |
| `REPAIR_MAX_ATTEMPTS` | 2 | repair rounds per failing gate |
| `MAX_REQUIREMENT_CHARS` | 12000 | compile request size |

A build typically takes 20–60 seconds of worker time, dominated by the generated test suite. Scale
throughput with worker replicas (`--concurrency` per replica); keep one sandbox command per CPU.

## Retention and data

Celery beat schedules `purge_expired_builds` daily (03:17 UTC) on the `maintenance` queue; it deletes
finished builds older than `BUILD_RETENTION_DAYS` together with their archives. `python -m app.cli
purge-builds` does the same on demand. Back up PostgreSQL (build history, reports, specs) and the
artifact volume; Redis holds only queue state.

## Upgrades

1. Read the release notes for migration and generator changes.
2. `docker compose build && docker compose run --rm api alembic upgrade head`.
3. Restart API, worker, maintenance and beat. Running builds on the old worker finish; queued builds
   run on the new one.

Generator output is a pure function of (spec, AgentForge version): rebuilding a spec after an upgrade
can produce different files, and the build report records the version that produced each archive.

## Air-gapped installation

The control plane and agent runtime are installed from hash-locked files
(`services/api/requirements.lock`, `app/generator/runtime/requirements-dev.lock`). Mirror those
packages (and the base images) into your internal registry and index; nothing is downloaded at build
time, and the compiler, evaluations and offline model need no network.
