# Security policy

## Trust model

Natural-language requirements, retrieved content, generated test fixtures, and tool responses are untrusted. Only a validated AgentSpec may cross into code generation. Tool names and artifact paths are allowlisted and validated.

## Reporting

Do not open a public issue for a vulnerability. Report it privately to the repository owner with reproduction steps, affected revision, and expected impact.

## Deployment requirements

- Replace development credentials before deployment.
- Put the web service behind TLS and an OIDC-aware access proxy.
- Use managed PostgreSQL/Redis with encryption and least-privilege identities.
- Store artifacts in private object storage with short-lived download URLs.
- Run generated code in a separate sandbox service; never mount the host Docker socket.
- Add SBOM generation, dependency scanning, SAST, container scanning, and artifact signing to CI.
- Keep the default deny-on-uncertainty behavior for external actions.

The included secret scanner is a blocking defense-in-depth check, not a replacement for enterprise secret scanning.

