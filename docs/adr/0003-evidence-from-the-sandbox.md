# 3. Gate on evidence produced by the generated repository in a sandbox

Status: accepted

## Context

A generator can claim its output works. Users need to know that the code they download passes its own
tests and evaluations, and that the numbers shown are real.

## Decision

Every build writes the repository to a workspace and runs its own `ruff`, `pytest` (JUnit + coverage) and
evaluation suite inside a sandbox. Metrics are parsed only from the reports those commands write; stale
reports are deleted first and a missing report is a gate error. Two sandbox backends exist: a process
sandbox (dedicated hash-locked virtualenv, scrubbed environment, rlimits, process-group kill) and a
Docker sandbox (container per command, no network, no capabilities, optional gVisor) on a dedicated
daemon.

## Consequences

- Build time is dominated by the generated test suite (tens of seconds).
- The agent runtime is pinned with hashes and versioned with AgentForge; upgrading it is a deliberate change.
