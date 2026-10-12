# AgentForge control plane

FastAPI service, Celery worker and command line for AgentForge: requirement compiler, architecture
planner, repository generator, sandboxed verification, security validation and signed packaging.

```bash
python -m app.cli compile "<requirement>" -o agent-spec.yaml   # or @requirement.txt
python -m app.cli validate agent-spec.yaml
python -m app.cli plan agent-spec.yaml
python -m app.cli generate agent-spec.yaml -o ./my-agent
python -m app.cli build agent-spec.yaml -o ./artifacts            # needs AGENTFORGE_SANDBOX_PYTHON
python -m app.cli verify-artifact ./artifacts/<id>.zip --public-key agentforge.pub
python -m app.cli generate-signing-key
python -m app.cli purge-builds
```

| Package | Purpose |
| --- | --- |
| `app/compiler` | requirement analysis, domain packs, optional LLM analyzer, validation |
| `app/planner` | topology proofs and risk register |
| `app/generator` | templates, render filters, sample data and evaluation datasets, hash-locked agent runtime |
| `app/sandbox` | process and Docker sandboxes |
| `app/verification` | gates, report parsers, repair agent |
| `app/security` | static security validation, SARIF |
| `app/packaging` | deterministic archives, Ed25519 signing, CycloneDX SBOM, SLSA provenance |
| `app/services` | pipeline orchestration, build lifecycle, artifact browsing, inline dispatch |
| `app/api` | HTTP routes |
| `app/tasks` | Celery app, build and maintenance tasks |

Tests: `pytest -m "not sandbox"` (fast) and `AGENTFORGE_SANDBOX_PYTHON=<runtime python> pytest -m sandbox`
(real builds). See the repository README and `docs/` for architecture and operations.
