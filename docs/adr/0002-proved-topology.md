# 2. Prove the graph topology before generating code

Status: accepted

## Context

An agent that can call tools with side effects is safe only if every path to those side effects passes a
human decision. Checking this in generated tests alone would discover violations after code exists.

## Decision

The planner derives the LangGraph topology from the spec and proves six properties: reachability,
termination, acyclicity, a single guarded entry, approval dominance over every side-effecting node, and
side-effecting tools bound only to proposal steps. A failed proof stops the build. The generated repository
re-checks the same properties in `tests/integration/test_graph_topology.py`.

## Consequences

- Specs that would allow unapproved side effects are rejected with an explanation before any code runs.
- The workflow is a DAG; loops (for example, iterative research) are modelled inside a step, not as cycles.
