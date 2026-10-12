# 1. A typed specification is the only input to code generation

Status: accepted

## Context

Users describe agents in natural language. Generating code directly from that text (or from a model's
free-form interpretation of it) would let any phrase in a requirement reach source files, prompts or
configuration, and would make builds impossible to reproduce or review.

## Decision

The compiler turns the requirement into AgentSpec v1, a strict, frozen Pydantic model. Only that object
crosses into planning and generation. Builds must present the spec together with its canonical SHA-256,
and the worker re-hashes the stored spec before generating. Templates may interpolate values only through
context-specific escaping filters (Python literal, identifier, TOML, JSON, Markdown); a test fails if a
template interpolates anything else.

## Consequences

- Generation is a pure function of (spec, AgentForge version) and is byte-reproducible.
- Every build can be reviewed as a YAML diff of its specification.
- Features must be expressible in the spec before the generator can use them; this is deliberate friction.
