# Security policy

## Reporting a vulnerability

Do not open a public issue. Report privately to the repository owner with reproduction steps, the
affected revision and the expected impact.

## Threat model

AgentForge accepts untrusted natural language and turns it into code that it then executes. The design
assumes every one of these is hostile:

| Input | Treated as | Controls |
| --- | --- | --- |
| Requirement text | data for the compiler only | never reaches templates; LLM output re-validated and safety invariants re-applied |
| AgentSpec documents | contract | strict schema, cross-field invariants, canonical hash checked at submission and in the worker |
| Template values | data | interpolated only through per-context escaping filters (enforced by a test) |
| Generated code | untrusted until verified | sandboxed execution, security scan, bandit; critical/high findings block packaging |
| Sandbox reports | untrusted files | size caps, defusedxml, schema parsing; stale reports deleted before each run |
| Model repair patches | untrusted code | only `src/` files, must parse, must pass the security AST rules; tests and evals are immutable |
| Archive contents | evidence for recipients | signed manifest; verification detects modified, missing, added and re-signed files |

Generated agents carry their own controls: prompt-injection scanning of requests, retrieved chunks and
tool outputs; allowlisted, schema-validated, phase-checked tools; side effects only after a human
approval bound to a SHA-256 digest of the exact arguments; separate caller and approver keys; PII
redaction in logs and memory; production start-up guards.

## Deployment requirements

- Set `AGENTFORGE_ENV=production`; it refuses development credentials, unauthenticated access and
  in-process build execution.
- Authenticate with API key digests or an authenticating proxy (`trusted_header`) that strips the
  identity header from client requests. Terminate TLS in front of nginx.
- Keep the worker on an internal network. For multi-tenant or internet-facing use, run the Docker
  sandbox on a dedicated daemon with gVisor. Never mount the host Docker socket into any AgentForge
  container.
- Configure `AGENTFORGE_SIGNING_KEY` from a secret store and publish the public key to artifact consumers.
- Use managed PostgreSQL and Redis with encryption, least-privilege credentials and backups; store
  archives in private object storage for multi-node deployments.
- Keep the hash-locked dependency files current and rebuild images regularly for base-image patches.

The built-in secret and policy scanner is a blocking defence-in-depth check, not a replacement for
organisation-wide secret scanning, SAST and container scanning in CI.
