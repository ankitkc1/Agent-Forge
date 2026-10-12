# AgentForge

AgentForge is a deterministic agent-engineering workbench. It compiles a natural-language business requirement into a validated **AgentSpec v1**, then plans, generates, tests, evaluates, security-checks, and packages a production-shaped agent repository.

Raw user text never enters the source-generation boundary. The compiler accepts the requirement; the worker accepts only a schema-valid specification and verifies its canonical SHA-256 hash before starting a build.

## Stack

- React 19, TypeScript, Vite, TanStack Query
- FastAPI, Pydantic v2, SQLAlchemy 2, Alembic
- Celery and Redis for durable build execution
- PostgreSQL for persisted build state and audit logs
- Nginx for the production frontend and same-origin API proxy
- Multi-stage Docker images, health checks, resource limits, internal networks
- Pytest, Ruff, Vitest, ESLint, strict TypeScript

## Repository

```text
agentforge/
├── apps/web/                 React + TypeScript workbench
├── services/api/             FastAPI control plane and Celery worker
│   ├── app/api/              Versioned HTTP routes
│   ├── app/schemas/          AgentSpec and build contracts
│   ├── app/services/         Compiler, generator, sandbox gates, security
│   ├── app/tasks/            Durable Celery jobs
│   ├── alembic/              Database migrations
│   └── tests/                API, compiler, generator, security tests
├── docs/                     Architecture and production guidance
├── compose.yaml              Full local stack
└── .env.example              Safe development defaults
```

## Run with Docker

Requirements: Docker Engine 25+ with Compose v2.

```bash
cp .env.example .env
docker compose up --build
```

Open:

- Workbench: <http://localhost:8080>
- API documentation: <http://localhost:8080/api/docs>
- Readiness: <http://localhost:8080/healthz>

Build artifacts are stored in the named `artifacts` volume. PostgreSQL and Redis are not published to the host and live on an internal Docker network.

## Run without Docker

Use Node 22+ and Python 3.12+.

```bash
cp .env.example .env
npm --prefix apps/web install
python -m venv .venv
./.venv/bin/python -m pip install -e "services/api[dev]"
```

Run PostgreSQL and Redis, apply migrations, then start the processes:

```bash
alembic -c services/api/alembic.ini upgrade head
uvicorn app.main:app --app-dir services/api --reload
celery -A app.tasks.celery_app:celery --workdir services/api worker --loglevel=INFO
npm --prefix apps/web run dev
```

On Windows, use `.venv\Scripts\python.exe` and run Celery through Docker; Celery's prefork worker is designed for Linux production environments.

## Quality gates

```bash
npm --prefix apps/web run typecheck
npm --prefix apps/web run lint
npm --prefix apps/web test -- --run
python -m ruff check services/api
python -m pytest services/api/tests -q
docker compose config --quiet
```

Each generated repository is also compiled, linted, and tested inside the worker's isolated temporary workspace before packaging. Failed gates cannot produce a downloadable artifact.

## Production notes

The included Compose stack is hardened for a single-host deployment and local evaluation. Before internet-facing production use, add your organization's OIDC provider, managed PostgreSQL/Redis, TLS ingress, object storage, centralized logs, and a stronger execution boundary such as gVisor, Kata Containers, or Firecracker. Never mount the host Docker socket into the worker.

See [docs/architecture.md](docs/architecture.md) and [SECURITY.md](SECURITY.md).

