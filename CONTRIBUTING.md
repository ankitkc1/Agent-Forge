# Contributing

## Setup

```bash
make bootstrap      # .venv (control plane), apps/web/node_modules, .venv-agent-runtime
make dev-api        # terminal 1: API with in-process builds and reload
make dev-web        # terminal 2: workbench with hot reload
```

## Before opening a pull request

```bash
make lint           # ruff check + ruff format --check, ESLint
make test           # pytest (no sandbox) + vitest
make test-sandbox   # full builds through the real process sandbox
make generated      # every template: generate, lint, test and evaluate the output
```

CI runs all of these plus container builds.

## Ground rules

1. **Raw text stays out of generation.** New features enter through AgentSpec fields (schema,
   invariants, docs in `docs/agentspec.md`), never by passing requirement text to the generator.
2. **Templates interpolate through filters.** In `*.py.j2` every `{{ … }}` ends with `|py`, `|py_tuple`,
   `|ident`, `|ident_upper`, `|toml` or `|json`; `tests/test_generator.py` enforces it. Prefer static
   files under `templates/agent/` for code that does not vary by spec.
3. **Generated repositories must pass their own gates.** Template changes need `make generated` green
   for all ten templates, and new runtime behaviour needs tests in the template's `tests/`.
4. **Domain packs stay consistent.** Label hints must be disjoint within a pack and curated examples must
   classify to their own label; `tests/test_domains.py` checks both.
5. **Metrics come from evidence.** Gates read numbers from reports the sandbox produced; never estimate.
6. **Schema and migrations change together.** Database changes come with an Alembic migration that
   upgrades and downgrades on SQLite and PostgreSQL.
7. **Dependencies are locked.** Update `services/api/requirements.lock` or the runtime locks with the
   commands in their headers; never add unpinned dependencies to images.
8. **No secrets or generated artifacts in Git**: `.env`, keys, archives and local databases are ignored.

Pull requests should describe the trust-boundary impact of any new tool mode, execution feature,
integration or external side effect.
