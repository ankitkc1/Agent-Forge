# Contributing

1. Create a focused branch.
2. Add or update tests with every behavior change.
3. Run frontend typecheck/lint/tests and backend Ruff/Pytest checks.
4. Update AgentSpec schemas and Alembic migrations together.
5. Keep raw requirements out of generator and worker interfaces.
6. Never add provider credentials, generated artifacts, or local `.env` files to Git.

Pull requests should explain the trust-boundary impact of any new tool, execution feature, integration, or external side effect.

