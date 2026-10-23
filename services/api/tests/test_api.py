from __future__ import annotations

import hashlib
import json
import uuid
from base64 import b64decode
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.routes import builds as builds_routes
from app.compiler.templates import TEMPLATES_BY_ID
from app.core.config import get_settings
from app.models.build import BuildRecord
from app.packaging.archive import build_package, provenance_statement
from app.packaging.signing import generate_key

REQUIREMENT = TEMPLATES_BY_ID["maintenance-triage"].requirement


class FakeTask:
    def __init__(self) -> None:
        self.dispatched: list[str] = []

    def apply_async(self, args: list[str], task_id: str):  # type: ignore[no-untyped-def]
        self.dispatched.append(args[0])
        return type("Result", (), {"id": task_id})()


@pytest.fixture
def task(monkeypatch: pytest.MonkeyPatch) -> FakeTask:
    fake = FakeTask()
    monkeypatch.setattr(builds_routes, "run_build", fake)
    return fake


def compile_spec(client: TestClient) -> dict:
    response = client.post("/api/v1/specs/compile", json={"requirement": REQUIREMENT})
    assert response.status_code == 200, response.text
    return response.json()


def test_compile_returns_spec_analysis_and_hash(client: TestClient) -> None:
    body = compile_spec(client)
    assert len(body["spec_hash"]) == 64
    assert body["analysis"]["engine"] == "heuristic"
    assert body["analysis"]["domain"] == "property_maintenance"
    assert body["spec"]["workflow"][0]["kind"] == "classify"


def test_validate_yaml_document_returns_plan(client: TestClient) -> None:
    import yaml

    spec = compile_spec(client)["spec"]
    response = client.post("/api/v1/specs/validate", json={"document": yaml.safe_dump(spec)})
    body = response.json()
    assert body["valid"] is True
    assert body["plan"]["checks"]
    assert all(check["passed"] for check in body["plan"]["checks"])


def test_validate_reports_errors_with_locations(client: TestClient) -> None:
    spec = compile_spec(client)["spec"]
    spec["tools"][-1]["approval_required"] = False
    spec["tools"][-1]["mode"] = "execute"
    body = client.post("/api/v1/specs/validate", json={"spec": spec}).json()
    assert body["valid"] is False
    assert body["errors"][0]["loc"].startswith("tools")


def test_build_lifecycle(client: TestClient, task: FakeTask) -> None:
    compiled = compile_spec(client)
    created = client.post(
        "/api/v1/builds", json={"spec": compiled["spec"], "spec_hash": compiled["spec_hash"]}
    )
    assert created.status_code == 202, created.text
    build = created.json()
    assert build["status"] == "queued"
    assert len(build["stages"]) == 10
    assert task.dispatched == [build["id"]]
    assert build["events"][0]["message"].startswith("AgentSpec hash verified")

    listed = client.get("/api/v1/builds").json()
    assert listed["items"][0]["id"] == build["id"]
    assert client.get(f"/api/v1/builds/{build['id']}/events").json()[0]["level"] == "info"

    cancelled = client.post(f"/api/v1/builds/{build['id']}/cancel")
    assert cancelled.status_code == 202
    assert cancelled.json()["status"] == "cancelled"
    assert client.post(f"/api/v1/builds/{build['id']}/cancel").status_code == 409

    retried = client.post(f"/api/v1/builds/{build['id']}/retry")
    assert retried.status_code == 202
    assert retried.json()["parent_build_id"] == build["id"]
    assert client.get(f"/api/v1/builds/{build['id']}/artifact").status_code == 409

    assert client.delete(f"/api/v1/builds/{retried.json()['id']}").status_code == 409
    assert client.delete(f"/api/v1/builds/{build['id']}").status_code == 204
    assert client.get(f"/api/v1/builds/{build['id']}").status_code == 404


def test_tampered_hash_is_rejected(client: TestClient, task: FakeTask) -> None:
    compiled = compile_spec(client)
    response = client.post("/api/v1/builds", json={"spec": compiled["spec"], "spec_hash": "0" * 64})
    assert response.status_code == 409
    assert task.dispatched == []


def test_idempotency_key_returns_the_same_build(client: TestClient, task: FakeTask) -> None:
    compiled = compile_spec(client)
    payload = {"spec": compiled["spec"], "spec_hash": compiled["spec_hash"]}
    first = client.post("/api/v1/builds", json=payload, headers={"Idempotency-Key": "abc-123"})
    second = client.post("/api/v1/builds", json=payload, headers={"Idempotency-Key": "abc-123"})
    assert first.status_code == 202 and second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert len(task.dispatched) == 1


def test_capacity_limit(client: TestClient, task: FakeTask, settings_env: pytest.MonkeyPatch) -> None:
    settings_env.setenv("AGENTFORGE_MAX_ACTIVE_BUILDS", "1")
    get_settings.cache_clear()
    compiled = compile_spec(client)
    payload = {"spec": compiled["spec"], "spec_hash": compiled["spec_hash"]}
    assert client.post("/api/v1/builds", json=payload).status_code == 202
    assert client.post("/api/v1/builds", json=payload).status_code == 429


def test_cursor_pagination(client: TestClient, task: FakeTask) -> None:
    compiled = compile_spec(client)
    payload = {"spec": compiled["spec"], "spec_hash": compiled["spec_hash"]}
    ids = [client.post("/api/v1/builds", json=payload).json()["id"] for _ in range(3)]
    first = client.get("/api/v1/builds", params={"limit": 2}).json()
    second = client.get("/api/v1/builds", params={"limit": 2, "cursor": first["next_cursor"]}).json()
    seen = [item["id"] for item in first["items"] + second["items"]]
    assert sorted(seen) == sorted(ids)
    assert second["next_cursor"] is None
    assert client.get("/api/v1/builds", params={"cursor": "garbage"}).status_code == 400


def test_api_key_authentication(client: TestClient, settings_env: pytest.MonkeyPatch) -> None:
    digest = hashlib.sha256(b"secret-key").hexdigest()
    settings_env.setenv("AGENTFORGE_AUTH_MODE", "api_key")
    settings_env.setenv("AGENTFORGE_API_KEYS", f"sha256:{digest},other-raw-key")
    get_settings.cache_clear()
    assert client.post("/api/v1/specs/compile", json={"requirement": REQUIREMENT}).status_code == 401
    assert (
        client.post(
            "/api/v1/specs/compile", json={"requirement": REQUIREMENT}, headers={"X-API-Key": "nope"}
        ).status_code
        == 401
    )
    ok = client.post(
        "/api/v1/specs/compile",
        json={"requirement": REQUIREMENT},
        headers={"Authorization": "Bearer secret-key"},
    )
    assert ok.status_code == 200
    assert client.get("/api/v1/builds", headers={"X-API-Key": "other-raw-key"}).status_code == 200
    assert client.get("/health/live").status_code == 200
    # Deployment details need a key; the signing public key stays public by design.
    assert client.get("/api/v1/system").status_code == 401
    assert client.get("/api/v1/system", headers={"X-API-Key": "other-raw-key"}).status_code == 200
    assert client.get("/api/v1/system/signing-key").status_code == 404  # public, but no key configured


def test_inline_dispatch_runs_builds_in_process(
    client: TestClient, settings_env: pytest.MonkeyPatch, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import dispatch

    submitted: list[str] = []
    monkeypatch.setattr(dispatch, "submit_inline", submitted.append)
    settings_env.setenv("AGENTFORGE_BUILD_DISPATCH", "inline")
    get_settings.cache_clear()
    compiled = compile_spec(client)
    created = client.post(
        "/api/v1/builds", json={"spec": compiled["spec"], "spec_hash": compiled["spec_hash"]}
    )
    assert created.status_code == 202
    assert submitted == [created.json()["id"]]
    assert client.get("/api/v1/system").json()["dispatch"] == "inline"


def test_inline_dispatch_is_refused_in_production() -> None:
    from app.core.config import Settings

    with pytest.raises(ValueError, match="BUILD_DISPATCH"):
        Settings(
            _env_file=None,  # type: ignore[call-arg]
            env="production",
            auth_mode="api_key",
            api_keys="k" * 40,
            database_url="postgresql+psycopg://svc:strong@db/agentforge",
            build_dispatch="inline",
        )


def test_production_requires_a_valid_signing_key() -> None:
    from app.core.config import Settings

    production = {
        "_env_file": None,
        "env": "production",
        "auth_mode": "api_key",
        "api_keys": "k" * 40,
        "database_url": "postgresql+psycopg://svc:strong@db/agentforge",
    }
    with pytest.raises(ValueError, match="SIGNING_KEY is required"):
        Settings(**production)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="SIGNING_KEY is invalid"):
        Settings(**production, signing_key="not-a-key")  # type: ignore[arg-type]
    seed, _ = generate_key()
    settings = Settings(**production, signing_key=seed)  # type: ignore[arg-type]
    assert settings.env == "production"


def test_trusted_header_authentication(
    client: TestClient, settings_env: pytest.MonkeyPatch, task: FakeTask
) -> None:
    settings_env.setenv("AGENTFORGE_AUTH_MODE", "trusted_header")
    get_settings.cache_clear()
    assert client.get("/api/v1/builds").status_code == 401
    compiled = client.post(
        "/api/v1/specs/compile",
        json={"requirement": REQUIREMENT},
        headers={"X-Forwarded-Email": "dana@example.com"},
    ).json()
    created = client.post(
        "/api/v1/builds",
        json={"spec": compiled["spec"], "spec_hash": compiled["spec_hash"]},
        headers={"X-Forwarded-Email": "dana@example.com"},
    )
    assert created.json()["requested_by"] == "dana@example.com"


def test_authenticated_builds_and_idempotency_keys_are_scoped_to_principal(
    client: TestClient, settings_env: pytest.MonkeyPatch, task: FakeTask
) -> None:
    settings_env.setenv("AGENTFORGE_AUTH_MODE", "trusted_header")
    get_settings.cache_clear()
    dana = {"X-Forwarded-Email": "dana@example.com", "Idempotency-Key": "shared-key"}
    lee = {"X-Forwarded-Email": "lee@example.com", "Idempotency-Key": "shared-key"}
    compiled = client.post("/api/v1/specs/compile", json={"requirement": REQUIREMENT}, headers=dana).json()
    payload = {"spec": compiled["spec"], "spec_hash": compiled["spec_hash"]}
    dana_build = client.post("/api/v1/builds", json=payload, headers=dana)
    lee_build = client.post("/api/v1/builds", json=payload, headers=lee)

    assert dana_build.status_code == 202 and lee_build.status_code == 202
    assert dana_build.json()["id"] != lee_build.json()["id"]
    assert [item["id"] for item in client.get("/api/v1/builds", headers=dana).json()["items"]] == [
        dana_build.json()["id"]
    ]
    assert client.get(f"/api/v1/builds/{lee_build.json()['id']}", headers=dana).status_code == 404
    assert client.post(f"/api/v1/builds/{lee_build.json()['id']}/cancel", headers=dana).status_code == 404
    assert client.get("/api/v1/specs/schema").status_code == 401
    assert client.get("/api/v1/specs/schema", headers=dana).status_code == 200


def test_system_templates_and_schema(client: TestClient) -> None:
    system = client.get("/api/v1/system").json()
    assert system["compiler"]["engines"] == ["heuristic"]
    assert "human_approval" in system["step_kinds"]
    assert client.get("/api/v1/system/signing-key").status_code == 404
    templates = client.get("/api/v1/specs/templates").json()
    assert len(templates) >= 10
    assert "properties" in client.get("/api/v1/specs/schema").json()
    assert any(domain["key"] == "general" for domain in client.get("/api/v1/specs/domains").json())


def _succeeded_build_with_artifact(session_factory, artifact_root: Path) -> str:  # type: ignore[no-untyped-def]
    build_id = uuid.uuid4()
    provenance = provenance_statement(
        package="demo-agent",
        digest="0",
        build_id=str(build_id),
        spec_hash="0" * 64,
        agent="demo",
        agentforge_version="1.0.0",
        generator="g",
        sandbox="process",
        lock_digest="0",
        started_at=datetime.now(UTC),
        builder_id="agentforge://test",
    )
    result = build_package(
        destination=artifact_root / f"{build_id}.zip",
        package="demo-agent",
        source_files={"README.md": b"# Demo\n", "src/agent/graph.py": b"GRAPH = 1\n"},
        evidence={"build-report.json": b"{}"},
        signer=None,
        sbom_inputs={},
        provenance=provenance,
    )
    with session_factory() as session:
        session.add(
            BuildRecord(
                id=build_id,
                agent_name="demo",
                spec_hash="0" * 64,
                spec={},
                status="succeeded",
                progress=100.0,
                stages=[],
                artifact_path=str(result.path),
                artifact_sha256=result.sha256,
                artifact_size=result.size_bytes,
                report={"package": {"archive_sha256": result.sha256}},
            )
        )
        session.commit()
    return str(build_id)


def test_files_preview_and_download(client: TestClient, session_factory) -> None:  # type: ignore[no-untyped-def]
    build_id = _succeeded_build_with_artifact(session_factory, get_settings().artifact_root)
    files = client.get(f"/api/v1/builds/{build_id}/files").json()
    paths = {entry["path"] for entry in files}
    assert {"README.md", "src/agent/graph.py", ".agentforge/MANIFEST.sha256"} <= paths
    preview = client.get(f"/api/v1/builds/{build_id}/files/src/agent/graph.py").json()
    assert preview["language"] == "python" and preview["content"] == "GRAPH = 1\n"
    assert client.get(f"/api/v1/builds/{build_id}/files/../../etc/passwd").status_code == 404
    download = client.get(f"/api/v1/builds/{build_id}/artifact")
    assert download.status_code == 200
    assert download.headers["X-Artifact-SHA256"] == hashlib.sha256(download.content).hexdigest()
    assert (
        b64decode(download.headers["Digest"].removeprefix("sha-256="))
        == hashlib.sha256(download.content).digest()
    )
    assert download.headers["Content-Digest"].startswith("sha-256=:")
    assert client.get(f"/api/v1/builds/{build_id}/report").json()["package"]["archive_sha256"]


def test_tampered_artifact_is_not_downloaded(client: TestClient, session_factory) -> None:  # type: ignore[no-untyped-def]
    build_id = _succeeded_build_with_artifact(session_factory, get_settings().artifact_root)
    with session_factory() as session:
        record = session.get(BuildRecord, uuid.UUID(build_id))
        assert record is not None and record.artifact_path
        Path(record.artifact_path).write_bytes(b"tampered")
    response = client.get(f"/api/v1/builds/{build_id}/artifact")
    assert response.status_code == 409
    assert response.json()["detail"] == "artifact failed its integrity check"
    assert client.get(f"/api/v1/builds/{build_id}/files").status_code == 409


def test_stream_of_finished_build(client: TestClient, session_factory) -> None:  # type: ignore[no-untyped-def]
    build_id = _succeeded_build_with_artifact(session_factory, get_settings().artifact_root)
    with client.stream("GET", f"/api/v1/builds/{build_id}/stream") as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())
    first = body.split("\n\n")[0]
    assert first.startswith("event: build")
    assert json.loads(first.split("data: ", 1)[1])["status"] == "succeeded"


def test_metrics_and_request_ids(client: TestClient) -> None:
    response = client.get("/health/live", headers={"X-Request-ID": "trace-123"})
    assert response.headers["X-Request-ID"] == "trace-123"
    assert "agentforge_http_requests_total" in client.get("/metrics").text


def test_timestamps_are_explicit_utc(client: TestClient, task: FakeTask) -> None:
    compiled = compile_spec(client)
    created = client.post(
        "/api/v1/builds", json={"spec": compiled["spec"], "spec_hash": compiled["spec_hash"]}
    ).json()
    for field in ("created_at", "updated_at"):
        assert created[field].endswith(("Z", "+00:00")), created[field]
    assert all(event["created_at"].endswith(("Z", "+00:00")) for event in created["events"])


def test_readiness_skips_the_queue_for_inline_dispatch(
    client: TestClient, settings_env: pytest.MonkeyPatch
) -> None:
    settings_env.setenv("AGENTFORGE_BUILD_DISPATCH", "inline")
    get_settings.cache_clear()
    response = client.get("/health/ready")
    assert response.status_code == 200 and response.json()["queue"].startswith("not used")
