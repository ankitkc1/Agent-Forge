# Changelog

## Unreleased

- Scope authenticated build history, events, reports, artifacts and lifecycle operations to the
  requesting principal; scope idempotency keys per principal and serialize PostgreSQL admission checks.
- Require and validate an Ed25519 signing key at production startup, and verify an artifact's stored
  SHA-256 digest before download.
- Restore unbuffered live build streams in nginx, disable production source maps by default and bound
  Compose log growth.
- Add migration round-trip coverage, an 80% backend coverage floor, dependency auditing, generated-agent
  CI gates and Dependabot maintenance.
- Remove the obsolete nested copy of the earlier AgentForge implementation.

## 1.0.0

AgentForge now generates real, verified agent repositories end to end. Previously the pipeline rendered
a fixed project template and reported simulated metrics; every stage below is new or rebuilt.

### Compiler and specification

- AgentSpec v1 with typed workflow steps (11 kinds), tool modes (read, draft, execute), labels with
  keyword hints, retrieval sources, guardrails, memory retention and evaluation targets; strict
  validation with cross-field invariants and transparent upgrade of older documents.
- Deterministic compiler with ten curated domain packs (maintenance, support, research, incidents, IT,
  recruiting, accounts payable, sales, e-commerce, contracts) and a general fallback.
- Optional model-assisted compiler (OpenAI, Anthropic, Ollama): drafts are repaired to the safety
  invariants and validated like hand-written specs; any defect falls back to the deterministic compiler.
- `POST /specs/validate` returns field-level errors or the spec, its hash and the verified plan.

### Planner

- Derives the LangGraph topology and proves six properties, including that human approval dominates
  every side-effecting node; risk register with mitigations.

### Generated repositories

- LangGraph agent with durable approval interrupts bound to SHA-256 action digests (full, partial and
  rejected approvals), typed allowlisted tools with fixture and HTTP backends, RAG with citations and
  injection quarantine, PII-redacting memory with retention, FastAPI service with caller/approver keys,
  MCP server, CLI, Docker assets, CI, hash-locked dependencies.
- Offline deterministic model plus OpenAI-compatible and Anthropic providers.
- 130–150 tests per agent (unit, integration, agent) and an evaluation suite with functional,
  assessment, retrieval, rejection, benign and 18 adversarial cases; graders for task success, tool
  accuracy and unsafe actions.

### Verification and delivery

- Process sandbox (separate hash-locked runtime, scrubbed environment, resource limits, process-group
  kill) and Docker sandbox (container per command, no network, no capabilities, optional gVisor).
- Gates parse real JUnit, coverage and evaluation reports; bounded repair (mechanical, optionally
  model-assisted on `src/` only); security scan with SARIF plus bandit.
- Deterministic ZIP with signed manifest (Ed25519), CycloneDX 1.6 SBOM and SLSA provenance;
  `verify-artifact` detects modified, missing, added and re-signed files.

### Platform

- Build lifecycle: events, live server-sent events, cancel, rebuild, delete, idempotency keys, capacity
  limits, cursor pagination, report and file browsing endpoints, retention purge on a schedule.
- Authentication modes: API keys (stored as digests) and trusted proxy headers; production start-up
  guards.
- In-process build dispatch for single-command local development.
- Command line: compile, validate, plan, generate, build, verify-artifact, generate-signing-key,
  purge-builds.

### Workbench

- New application: requirement composer with templates, editable specification with live validation,
  architecture preview, live build view with stage rail, and tabs for overview, architecture, tests,
  evaluation, security, files, provenance and activity; builds history, templates and system pages;
  API key support; self-hosted fonts.

### Operations

- Hash-locked control-plane image with a separate agent runtime, sandbox image, compose stack with
  beat and maintenance workers on an internal network, hardened nginx (streaming, CSP), CI that builds
  every template's repository and runs its own gates, documentation and decision records.

### Removed

- `app/services/compiler.py`, `generator.py`, `repository.py`, `security.py` (replaced by the
  `compiler`, `generator`, `security` and `packaging` packages) and the old single-page workbench code.
