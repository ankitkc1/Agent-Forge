# 5. Ship every artifact with a signed manifest, SBOM and provenance

Status: accepted

## Context

Downloaded archives travel through email, chat and object storage. Recipients need to know that the files
are the ones AgentForge verified and what they depend on.

## Decision

Archives are deterministic ZIPs (sorted entries, fixed timestamps and permissions). `.agentforge/` holds
the raw test and evaluation evidence, a CycloneDX 1.6 SBOM from the locked dependencies, an in-toto
statement with a SLSA v1 provenance predicate, and `MANIFEST.sha256` covering every file. When the
instance has a key, the manifest is signed with Ed25519 and the public key is published at
`/api/v1/system/signing-key`. `verify-artifact` detects modified, missing and added files; passing a
trusted public key also detects re-signing.

## Consequences

- Operators must manage one signing key (rotation is supported by key ID).
- Evidence timestamps differ between builds of the same spec; the source digest does not.
