"""The compiled LangGraph must match the topology AgentForge verified."""

from __future__ import annotations

from collections import defaultdict, deque

from src.agent import blueprint
from src.agent.service import AgentService


def compiled_edges(service: AgentService) -> set[tuple[str, str, str | None]]:
    graph = service.graph.get_graph()
    return {
        (edge.source, edge.target, str(edge.data) if edge.conditional else None)
        for edge in graph.edges
    }


def test_nodes_match_blueprint(service: AgentService) -> None:
    nodes = set(service.graph.get_graph().nodes) - {"__start__", "__end__"}
    assert nodes == {node["id"] for node in blueprint.TOPOLOGY["nodes"]}


def test_edges_match_blueprint(service: AgentService) -> None:
    expected = {
        (edge["source"], edge["target"], edge["condition"]) for edge in blueprint.TOPOLOGY["edges"]
    }
    assert compiled_edges(service) == expected


def test_human_approval_dominates_side_effects(service: AgentService) -> None:
    approval = {n["id"] for n in blueprint.TOPOLOGY["nodes"] if n["kind"] == "human_approval"}
    execute = {n["id"] for n in blueprint.TOPOLOGY["nodes"] if n["kind"] == "execute"}
    adjacency: dict[str, list[str]] = defaultdict(list)
    for source, target, _ in compiled_edges(service):
        if source not in approval and target not in approval:
            adjacency[source].append(target)
    reachable, queue = {"__start__"}, deque(["__start__"])
    while queue:
        for target in adjacency[queue.popleft()]:
            if target not in reachable:
                reachable.add(target)
                queue.append(target)
    assert not (execute & reachable), "an execute node is reachable without human approval"


def test_input_guard_is_the_only_entry(service: AgentService) -> None:
    starts = {target for source, target, _ in compiled_edges(service) if source == "__start__"}
    assert starts == {"guard_input"}
