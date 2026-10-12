# AgentSpec v1 reference

AgentSpec is the contract between what a business asked for and what AgentForge generates. It is the
only input the generator accepts. The compiler produces one from a requirement; you can also write or
edit it by hand (the workbench validates as you type; `python -m app.cli validate agent-spec.yaml`
does the same offline).

Every document is validated strictly: unknown fields are rejected, identifiers are `snake_case`
(2–64 characters, starting with a letter, not a Python keyword), and the cross-field invariants below
are enforced. The canonical form (sorted-key JSON) is hashed with SHA-256; builds must present that
hash, and the generated repository embeds it.

## Minimal example

```yaml
version: "1.0"
agent:
  name: property_maintenance_triage
  domain: property_maintenance
  objective: Triage tenant maintenance requests and prepare governed work orders.
  description: Classifies requests, assesses urgency, looks up property context and drafts work orders that are only submitted after human approval.
  constraints:
    - Never advise tenants to perform electrical or gas work themselves.
model:
  provider: local            # local | openai | anthropic
  model: qwen2.5:14b
tools:
  - name: property_lookup
    mode: read               # read | draft | execute
    description: Look up a property's address, manager and open work orders.
    inputs:
      - { name: property_id, type: string, description: Property identifier, required: true }
  - name: create_work_order
    mode: draft
    approval_required: true
    inputs:
      - { name: property_id, type: string }
      - { name: summary, type: string }
retrieval:
  enabled: true
  sources:
    - { name: maintenance_policies, description: Response times and escalation rules }
workflow:
  - id: classify_request
    kind: classify
    labels:
      - { name: plumbing, hints: [leak, pipe, drain, toilet, sink, shower] }
      - { name: electrical, hints: [power, outlet, breaker, light, socket, wiring] }
      - { name: general_repair, hints: [door, window, lock, wall, ceiling] }
  - { id: retrieve_policies, kind: retrieve, sources: [maintenance_policies] }
  - { id: lookup_property, kind: lookup, tools: [property_lookup] }
  - { id: prepare_action, kind: draft, tools: [create_work_order] }
  - { id: safety_check, kind: safety_check }
  - { id: human_approval, kind: human_approval }
  - { id: execute, kind: execute }
  - { id: respond, kind: respond }
memory:
  type: postgres             # postgres | sqlite | none
  namespace: property_maintenance_triage
evaluation:
  task_success_target: 0.9
```

## `agent`

| Field | Type | Notes |
| --- | --- | --- |
| `name` | identifier | Python package and repository name (`property-maintenance-triage-agent`) |
| `domain` | identifier | Domain pack used for curated labels, tools and sample data; `general` otherwise |
| `objective` | 10–300 chars | One sentence; becomes part of the system prompt |
| `description` | 10–1200 chars | What the agent does and does not do |
| `constraints` | ≤ 8 × 3–240 chars | Hard rules rendered into the system prompt and the README |

## `model`

| Field | Default | Notes |
| --- | --- | --- |
| `provider` | — | `local` (any OpenAI-compatible server such as Ollama or vLLM), `openai`, `anthropic` |
| `model` | — | Provider model name |
| `temperature` | 0.1 | 0–1 |
| `max_output_tokens` | 1024 | 64–32768 |

The generated repository also ships a deterministic `offline` provider used by its tests and offline
evaluations; switch providers with `MODEL_PROVIDER` without regenerating.

## `tools`

| Field | Default | Notes |
| --- | --- | --- |
| `name` | — | Identifier; `base`, `registry`, `catalog`, `backends` are reserved |
| `description` | "" | ≤ 400 chars |
| `mode` | — | `read` (no side effects), `draft` (prepares a reviewable draft; can execute after approval), `execute` (changes an external system) |
| `approval_required` | false | Must be `true` for `execute` tools. Draft tools also require approval when `guardrails.external_messages.approval_required` is true (the default) |
| `timeout_seconds` | null | 1–300; falls back to `guardrails.tool_execution.timeout_seconds` |
| `inputs` | [] | ≤ 16 parameters: `name`, `type` (`string`, `integer`, `number`, `boolean`), `description`, `required` |

Each tool becomes `src/tools/<name>.py` with a Pydantic input model (`extra="forbid"`) and a handler
that calls the configured backend: fixtures in development, an HTTP integration gateway in production.

## `retrieval`

| Field | Default | Notes |
| --- | --- | --- |
| `enabled` | true | When true, at least one source is required |
| `sources` | [] | `{name, description}`; each becomes `data/knowledge/<name>/` with seed documents |
| `top_k` | 4 | 1–20 |
| `min_score` | 0.05 | 0–1 |
| `citations_required` | false | Needs a `retrieve` step; responses must cite evidence (`[S1]`) |
| `chunk_size` / `chunk_overlap` | 800 / 120 | overlap must be smaller than size |
| `embeddings` | hashing | `hashing` (offline, deterministic), `openai`, `ollama` |
| `store` | memory | `memory` or `pgvector` (requires `memory.type: postgres`) |

Retrieved chunks are scanned for instruction-like content and quarantined before they reach a prompt.

## `workflow`

2–24 steps, executed in order between the platform's input guard and its finalizer.

| Kind | Purpose | Kind-specific fields |
| --- | --- | --- |
| `classify` | pick one label | `labels` (2–12, each with ≤ 24 lowercase `hints`) |
| `assess` | rate along a dimension (urgency, risk, …) | `labels` (levels, ordered), `dimension` |
| `retrieve` | fetch evidence | `sources` (subset of `retrieval.sources`) |
| `lookup` | call read tools | `tools` (read tools only; empty = all read tools) |
| `analyze` | structured reasoning over the evidence so far | — |
| `draft` | propose actions and a reply | `tools` (draft/execute tools; empty = all of them) |
| `safety_check` | apply the action policy to proposals | — |
| `verify` | check claims against evidence | — |
| `human_approval` | interrupt for a reviewer decision | `review`: `when_required` (default) or `always` |
| `execute` | run approved actions, re-checking each action's SHA-256 digest | — |
| `respond` | compose the final answer | — |

Step ids `guard_input`, `finalize`, `runtime`, `start` and `end` are reserved. Label hints drive the
offline model and the generated evaluation cases; keep them distinctive between labels.

## `guardrails`

| Field | Default | Notes |
| --- | --- | --- |
| `external_messages.approval_required` | true | Must stay true when any tool has `mode: execute` |
| `tool_execution.allowlist_only` | true | Must be true |
| `tool_execution.timeout_seconds` | 30 | Default per-call timeout |
| `tool_execution.max_calls_per_run` | 12 | Budget across lookups and previews |
| `prompt_injection.action` | block_and_log | or `human_review` (flag and continue to review) |
| `prompt_injection.scan_retrieved_content` | true | Scan retrieved chunks and tool outputs |
| `pii.redact_logs` / `pii.redact_memory` | true / true | Emails, phone numbers and card numbers |

## `memory`

| Field | Default | Notes |
| --- | --- | --- |
| `type` | — | `postgres`, `sqlite` or `none` |
| `namespace` | — | Identifier; isolates this agent's threads |
| `pii_retention_days` | 30 | 0–365; 0 stores nothing |
| `conversation_window` | 10 | Turns of history given to the model |

## `evaluation`

| Field | Default | Notes |
| --- | --- | --- |
| `task_success_target` | 0.9 | Share of cases whose outcome matches expectations |
| `tool_accuracy_target` | 0.95 | Micro-F1 of tool calls against expected tools |
| `unsafe_action_target` | 0 | Side effects without a matching approval; 0–10 (the compiler always emits 0) |
| `adversarial_cases` | 18 | Prompt injection, approval bypass, exfiltration and tool-output attacks |

## Cross-field invariants

- Tool names and step ids are unique; steps reference only declared tools and sources.
- `lookup` steps bind only `read` tools; `draft` steps bind only `draft`/`execute` tools.
- A `draft` step whose tools need approval must be followed by a `human_approval` step.
- An `execute` step must come after both a `draft` and a `human_approval` step, and the workflow cannot
  start with either.
- `retrieve` steps require `retrieval.enabled`; `citations_required` requires a `retrieve` step.

The planner then proves the topology properties described in [architecture.md](architecture.md#verified-topology);
a spec that validates but fails a proof cannot be built.

## Older documents

Version 1 documents written before typed workflow steps (a flat list of step names such as
`classify_request`, `draft_response`, `send_reply`) are upgraded on load: step kinds are inferred from
names and tools are bound to the inferred lookup and draft steps. Re-save them from the workbench to
get the explicit form.
