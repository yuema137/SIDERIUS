"""HTTP admission ordering, isolated apps and sanitized error projections."""

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tools.candidate_console.app import create_app
from tools.candidate_console.boundary import BODY_LIMIT, RequestBoundary
from tools.candidate_console.models import PrepareSelection


def client(config):
    result = TestClient(
        create_app(config), base_url=config.browser_origin, raise_server_exceptions=False
    )
    result.headers.update(
        {
            "Authorization": "Bearer " + Path(config.auth_token_file).read_text(),
            "Origin": config.browser_origin,
        }
    )
    return result


def test_auth_before_any_body_receive_and_stream_limit(console_config):
    calls = []

    async def business(scope, receive, send):
        calls.append("business")

    app = RequestBoundary(business, config=console_config, token="test-token")

    async def invoke(auth, chunks):
        sent = []

        async def receive():
            calls.append("receive")
            return chunks.pop(0)

        async def send(message):
            sent.append(message)

        await app(
            {
                "type": "http",
                "path": "/api/preparations",
                "method": "POST",
                "headers": [
                    (b"host", b"127.0.0.1:8740"),
                    (b"origin", console_config.browser_origin.encode()),
                    (b"content-type", b"application/json"),
                    (b"content-length", b"1"),
                    (b"authorization", auth),
                ],
            },
            receive,
            send,
        )
        return sent[0]["status"]

    assert asyncio.run(invoke(b"wrong", [])) == 401
    assert calls == []
    assert (
        asyncio.run(
            invoke(
                b"Bearer test-token",
                [
                    {"type": "http.request", "body": b"{" * BODY_LIMIT, "more_body": True},
                    {"type": "http.request", "body": b"x", "more_body": False},
                ],
            )
        )
        == 413
    )
    assert calls == ["receive", "receive"]


def test_host_origin_content_and_sanitized_errors(console_config):
    api = client(console_config)
    assert api.get("/api/choices").status_code == 200
    assert api.get("/api/choices", headers={"Host": "evil.invalid"}).status_code == 403
    assert (
        api.get("/api/choices", headers={"X-Forwarded-Host": "127.0.0.1:8740"}).status_code == 403
    )
    assert api.get("/api/choices", headers={"Origin": "null"}).status_code == 403
    assert api.post("/api/preparations", content="{", headers={"Origin": ""}).status_code == 403
    assert (
        api.post(
            "/api/preparations", content="{", headers={"Content-Type": "text/plain"}
        ).status_code
        == 415
    )
    for response in (
        api.post("/api/preparations", json={"secret": "DO-NOT-ECHO"}),
        api.get("/api/operations/DO-NOT-ECHO"),
        api.get(f"/api/operations/{uuid4()}/log?offset=DO-NOT-ECHO"),
        api.post(
            "/api/preparations",
            content="{DO-NOT-ECHO",
            headers={"Content-Type": "application/json"},
        ),
    ):
        assert response.status_code == 422
        assert "DO-NOT-ECHO" not in response.text
    assert api.get(f"/api/operations/{uuid4()}").status_code == 404
    assert api.get("/docs").status_code == 404
    assert api.get("/llm.json").status_code == 404
    assert api.get("/").headers["cache-control"] == "no-store"


def test_same_uuid_retry_is_native_idempotency(console_config, monkeypatch):
    spawns = []
    monkeypatch.setattr(
        "tools.candidate_operations.submit.spawn", lambda *args: spawns.append(args)
    )
    api = client(console_config)
    selection = PrepareSelection(operation_id=uuid4(), task_id="synthetic", run_name="example")
    response = api.post("/api/preparations", json=selection.model_dump(mode="json"))
    assert response.status_code == 202, response.text
    retry = api.post("/api/preparations", json=selection.model_dump(mode="json"))
    assert retry.status_code == 202 and retry.json()["observation"] == "existing"
    assert len(spawns) == 1
    conflict = selection.model_copy(update={"run_name": "different"})
    assert api.post("/api/preparations", json=conflict.model_dump(mode="json")).status_code == 409


def test_http_policy_refusal_does_not_block_known_id_reads(prepared, monkeypatch):
    service, selection, _ = prepared
    task = service.config.tasks[0].model_copy(
        update={"candidate_environment_names": ("DIFFERENT_KEY",)}
    )
    api = client(service.config.model_copy(update={"tasks": (task,)}))

    def forbidden(*args, **kwargs):
        pytest.fail("unauthorized credential read or submission")

    monkeypatch.setattr("tools.candidate_console.service.credentials", forbidden)
    monkeypatch.setattr("tools.candidate_console.service.submit_operation", forbidden)
    assert api.get(f"/api/preparations/{selection.operation_id}/review").status_code == 409
    assert (
        api.post(
            "/api/candidates",
            json={
                "candidate_operation_id": str(uuid4()),
                "prepare_operation_id": str(selection.operation_id),
                "expected_prepared_digest": "0" * 64,
            },
        ).status_code
        == 409
    )
    assert (
        api.get(f"/api/operations/{selection.operation_id}").json()["native_status"] == "prepared"
    )
    assert "graph_trace" not in api.get(f"/api/operations/{selection.operation_id}").json()
    assert api.get(f"/api/operations/{selection.operation_id}/log").status_code == 200


def test_apps_do_not_share_task_choices(console_config):
    first = client(console_config)
    task = console_config.tasks[0].model_copy(update={"label": "Other task"})
    second = client(console_config.model_copy(update={"tasks": (task,)}))
    assert first.get("/api/choices").json()[0]["label"] == "Synthetic task"
    assert second.get("/api/choices").json()[0]["label"] == "Other task"


def test_unexpected_failure_has_secured_sanitized_response(console_config, monkeypatch, caplog):
    api = client(console_config)

    def fail(self):
        raise RuntimeError("SECRET-LIKE-EXCEPTION")

    monkeypatch.setattr("tools.candidate_console.service.CandidateConsole.choices", fail)
    response = api.get("/api/choices")
    assert response.status_code == 500
    assert "SECRET-LIKE-EXCEPTION" not in response.text + caplog.text
    assert response.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_concurrent_same_uuid_admits_once(console_config, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    spawns = []
    monkeypatch.setattr(
        "tools.candidate_operations.submit.spawn", lambda *args: spawns.append(args)
    )
    selection = PrepareSelection(operation_id=uuid4(), task_id="synthetic", run_name="concurrent")

    def submit():
        with client(console_config) as api:
            return api.post("/api/preparations", json=selection.model_dump(mode="json"))

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: submit(), range(2)))
    assert all(response.status_code == 202 for response in responses)
    assert {response.json()["observation"] for response in responses} == {"starting", "existing"}
    assert len(spawns) == 1


def test_config_loader_refuses_symlink_swap_after_canonical_check(
    console_config, tmp_path, monkeypatch
):
    from tools.candidate_console import files
    from tools.candidate_console.config import load_config

    config_path = tmp_path / "console.json"
    config_path.write_text(console_config.model_dump_json())
    assert load_config(str(config_path)) == console_config
    replacement = tmp_path / "replacement.json"
    replacement.write_text(console_config.model_dump_json())
    original = files.canonical

    def swapped(value):
        path = original(value)
        if path == config_path:
            path.unlink()
            path.symlink_to(replacement)
        return path

    monkeypatch.setattr(files, "canonical", swapped)
    with pytest.raises(OSError):
        load_config(str(config_path))


def test_tokens_route_auth_uuid_and_sanitized_integrity(console_config, monkeypatch):
    """Every boundary refusal precedes reader access; valid GET reaches only token service."""
    from tools.candidate_operations.models import OperationFailure
    from tools.candidate_worker.token_models import CandidateTokenSnapshot

    calls = []

    def tokens(config, operation_id):
        calls.append(operation_id)
        if len(calls) > 1:
            raise OperationFailure("integrity", "/secret/path raw ledger extra DO-NOT-ECHO")
        return CandidateTokenSnapshot(
            observed_at="2026-10-22T12:00:00Z",
            availability="unavailable",
            reason="native_evidence_unavailable",
        )

    monkeypatch.setattr("tools.candidate_console.service.read_operation_tokens", tokens)
    api = client(console_config)
    operation_id = uuid4()
    url = f"/api/operations/{operation_id}/tokens"
    for headers, expected in (
        ({"Authorization": ""}, 401),
        ({"Authorization": "Bearer wrong"}, 401),
        ({"Host": "evil.invalid"}, 403),
        ({"Origin": "null"}, 403),
    ):
        assert api.get(url, headers=headers).status_code == expected
    assert api.get("/api/operations/DO-NOT-ECHO/tokens").status_code == 422
    assert not calls
    response = api.get(url)
    assert response.status_code == 200 and response.json()["availability"] == "unavailable"
    assert calls == [operation_id]
    assert (
        response.headers["cache-control"] == "no-store"
        and "frame-ancestors 'none'" in response.headers["content-security-policy"]
    )
    assert not any(
        key in response.json() for key in ("workspace", "ledger_path", "extra", "components")
    )
    failure = api.get(url)
    assert failure.status_code == 409 and failure.json()["error"]["code"] == "integrity"
    assert "DO-NOT-ECHO" not in failure.text and "/secret/path" not in failure.text


def test_navigation_assets_keep_exact_static_security_boundary(console_config):
    """Missing shell dependencies break navigation; a wildcard leaks adjacent files."""
    api = client(console_config)
    for name in ("session.js", "navigation.js", "editor-entry.js"):
        response = api.get("/" + name, headers={"Authorization": ""})
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert "script-src 'self'" in response.headers["content-security-policy"]
        assert response.headers["x-frame-options"] == "DENY"
        assert api.get("/" + name, headers={"Host": "evil.invalid"}).status_code == 403
    assert api.get("/session.js.map").status_code == 404
    assert api.get("/../console-contract.md").status_code == 404
    assert api.get("/api/choices", headers={"Authorization": ""}).status_code == 401
