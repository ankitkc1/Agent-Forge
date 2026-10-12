# 4. Gate builds on deterministic offline evaluations

Status: accepted

## Context

Evaluating with a live model in the build pipeline would need credentials and network access inside the
sandbox, cost money per build and make gate results non-deterministic.

## Decision

Generated repositories include a deterministic offline model that implements every structured task with
transparent heuristics driven by the spec (label hints, regex argument extraction, templates). The build
gates on the offline evaluation suite, which measures control flow and safety: routing, tool selection,
approval gating, guardrails and adversarial resistance. The same suite runs against the configured model
with `python -m evals.run --live`.

## Consequences

- Gate results are reproducible and need no secrets or network.
- Offline results do not measure language quality; documentation and the workbench say so explicitly.
- Domain packs must keep label hints distinctive; a test checks that curated examples classify correctly.
