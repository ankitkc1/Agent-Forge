# Generated repositories

Every successful build produces a ZIP containing a complete Python project for one agent. This page
describes what is inside, how it behaves, and how to take it to production. The repository's own
`README.md` repeats the agent-specific parts (its workflow, tools, sources and targets).

## Layout

```text
<agent-name>-agent/
├── src/
│   ├── agent/
│   │   ├── graph.py        LangGraph StateGraph: nodes, conditional edges, checkpointer
│   │   ├── state.py        typed graph state with additive reducers (JSON-serialisable)
│   │   ├── prompts.py      system prompt and per-task user prompts (data framed as data)
│   │   ├── nodes.py        one function per workflow step, delegating to patterns.py
│   │   ├── patterns.py     step archetypes: classify, assess, retrieve, lookup, draft, verify, approval, execute, …
│   │   ├── blueprint.py    constants derived from agent-spec.yaml (workflow, tools, guardrails, targets)
│   │   ├── llm.py          OpenAI-compatible, Anthropic and offline providers; validated JSON outputs
│   │   ├── offline.py      deterministic model for tests, evaluations and demos
│   │   ├── service.py      run lifecycle: start, resume after approval, memory, audit
│   │   └── contracts.py    structured outputs and the approval-digest contract
│   ├── tools/              one module per tool (Pydantic input model + handler), registry, backends
│   ├── rag/                chunking, embeddings, vector store (memory or pgvector), retriever
│   ├── memory/             SQL conversation memory with PII redaction and retention; checkpointers
│   ├── guardrails/         prompt-injection scanner, PII redaction, action policy
│   ├── api/                FastAPI app: runs, approvals, memory erasure, health, metrics
│   ├── mcp_server.py       Model Context Protocol server (read-only tools + run_agent)
│   ├── cli.py              run (with --approve/--reject), ingest, purge-memory
│   └── config.py           settings from environment / .env with production guards
├── mcp/                    server entry point, client configuration and notes
├── tests/
│   ├── unit/               tools, backends, guardrails, patterns, retrieval, memory, model layer, config, spec drift
│   ├── integration/        HTTP API, graph topology, MCP server
│   └── agent/              end-to-end workflows, approvals (full, partial, rejected, tampered), adversarial cases
├── evals/                  dataset.json, graders.py, run.py
├── data/                   fixtures for tools, seed knowledge per source
├── Dockerfile, docker-compose.yml, Makefile, .github/workflows/ci.yml
├── pyproject.toml, requirements.lock, requirements-dev.lock (hash-pinned)
├── agent-spec.yaml, architecture.md, README.md, .env.example
└── .agentforge/            build evidence (see below)
```

## Run it

```bash
python -m venv .venv && . .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install --require-hashes -r requirements-dev.lock && pip install -e . --no-deps
cp .env.example .env
make test && make evals                               # same gates AgentForge ran
uvicorn src.api.main:app --reload --port 8000
```

`MODEL_PROVIDER=offline` runs the whole workflow without credentials. Set `MODEL_PROVIDER` to `local`,
`openai` or `anthropic` (with the matching key) for real use; nothing needs regenerating.

## The approval contract

Side effects never happen inside a model call. The `draft` step *proposes* actions; each proposal is
validated against the tool's input model and bound to `SHA-256(tool + canonical arguments)`. The
graph then interrupts at `human_approval` and persists its state through the checkpointer, so a
pending decision survives restarts.

```bash
curl -s localhost:8000/v1/runs -H "X-API-Key: $CALLER_KEY" -H "Content-Type: application/json" \
  -d '{"message": "The shower drain at P-1002 is blocked"}'
# → {"status": "awaiting_approval", "pending_approval": {"actions": [{"id": "act_1_…", "digest": "…"}]}}

curl -s localhost:8000/v1/runs/$RUN_ID/approval -H "X-API-Key: $APPROVER_KEY" -H "Content-Type: application/json" \
  -d '{"approved": true, "reviewer": "Dana", "action_ids": ["act_1_…"]}'
```

Only approver keys can decide. The execute step re-computes each approved action's digest and skips
anything that changed after approval; partial approval executes exactly the chosen subset.

## Connecting real systems

Tools call a backend chosen by `TOOL_BACKEND`:

- `fixture` (default): sample records from `data/fixtures/tools.json`; side effects are journaled in
  memory so tests can prove nothing ran before approval.
- `http`: a small integration gateway you own —
  `POST {TOOL_BACKEND_URL}/tools/{tool}/{read|preview|execute}` with a bearer token. Reads are retried;
  side effects are never retried automatically and carry an `Idempotency-Key`.

Or replace a tool's `handle` function to call an SDK directly; its input model keeps validation.

## Evaluations

`evals/dataset.json` contains functional cases per label, assessment cases per level, retrieval and
grounding cases, an approval-rejection case, benign controls and adversarial cases (prompt injection,
approval bypass, data exfiltration, poisoned tool output). `evals/graders.py` scores:

- **task success**: expected status, classification, assessment, grounding and response checks;
- **tool accuracy**: micro-F1 between expected and observed tool calls;
- **unsafe actions**: any side effect before approval, after rejection, during an attack or outside
  the approved set.

`python -m evals.run` uses the offline model (what AgentForge gates on); `--live` scores your model.

## Build evidence (`.agentforge/`)

| File | Content |
| --- | --- |
| `build-report.json` | plan, gate results, repairs, security summary, timings |
| `junit.xml`, `coverage.json` | raw pytest evidence from the sandbox |
| `eval-report.json` | per-case evaluation results and metrics |
| `security-report.json`, `security-report.sarif`, `bandit.json` | findings (SARIF uploads to GitHub code scanning) |
| `sbom.cdx.json` | CycloneDX 1.6 SBOM of the locked dependencies |
| `provenance.json` | in-toto statement with a SLSA v1 provenance predicate |
| `MANIFEST.sha256` | digest of every file in the archive |
| `MANIFEST.sha256.sig`, `signing-key.pub`, `SIGNATURE.json` | Ed25519 signature (when the instance has a key) |

Verify a download against the key published by your AgentForge instance:

```bash
curl -fsS https://agentforge.example.com/api/v1/system/signing-key -o agentforge.pub
python -m app.cli verify-artifact my-agent-1a2b3c4d.zip --public-key agentforge.pub
```

## Production checklist

- `ENV=production` refuses to start with default API keys, the offline model, fixture tools or
  in-memory checkpoints.
- Use PostgreSQL for memory and checkpoints (`CHECKPOINT_BACKEND=postgres`), so approvals survive
  restarts and scale across replicas.
- Replace the sample knowledge under `data/knowledge/` with your approved documents.
- Keep the evaluation suite growing with real, labelled requests; run `--live` before each model change.
