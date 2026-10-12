from fastapi.testclient import TestClient

from app.api.routes import builds

REQUIREMENT = (
    "Build a property maintenance triage agent with property lookup, work-order drafts, "
    "human approval, Postgres memory, and zero unsafe actions."
)


def test_compile_and_queue_build(client: TestClient, monkeypatch) -> None:
    dispatched: list[str] = []
    monkeypatch.setattr(builds.run_build, "delay", lambda build_id: dispatched.append(build_id))

    compiled = client.post("/api/v1/specs/compile", json={"requirement": REQUIREMENT})
    assert compiled.status_code == 200
    body = compiled.json()
    assert len(body["spec_hash"]) == 64

    created = client.post(
        "/api/v1/builds",
        json={"spec": body["spec"], "spec_hash": body["spec_hash"]},
    )
    assert created.status_code == 202
    build = created.json()
    assert build["status"] == "queued"
    assert build["artifact_ready"] is False
    assert len(build["stages"]) == 10
    assert dispatched == [build["id"]]

    fetched = client.get(f"/api/v1/builds/{build['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["spec_hash"] == body["spec_hash"]


def test_build_rejects_tampered_spec_hash(client: TestClient) -> None:
    compiled = client.post("/api/v1/specs/compile", json={"requirement": REQUIREMENT}).json()
    response = client.post(
        "/api/v1/builds",
        json={"spec": compiled["spec"], "spec_hash": "0" * 64},
    )
    assert response.status_code == 409
