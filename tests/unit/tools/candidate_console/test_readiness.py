"""Readiness must not hide binding blockers or leak selected private values."""

import json
from pathlib import Path
from uuid import uuid4

import pytest

from tools.candidate_console.models import LaunchSelection, PreparedSelection
from tools.candidate_operations.models import OperationFailure


@pytest.fixture
def selection(selection):
    return selection.model_copy(update={"candidate_environment_names": ("OPENAI_API_KEY", "EXTRA")})


def test_private_file_states_are_names_only_and_launch_rereads(prepared, tmp_path, monkeypatch):
    """Missing/malformed/empty files must remain reviewable; launch cannot cache presence."""
    service, selection, _ = prepared
    path = tmp_path / "keys.json"
    service.config = service.config.model_copy(update={"credential_file": str(path)})
    selected = PreparedSelection(prepare_operation_id=selection.operation_id)
    assert service.review(selected).credential_readiness.file_status == "unavailable"
    path.write_text('{"EXTRA": "SECRET-MARKER", invalid')
    path.chmod(0o600)
    assert service.review(selected).credential_readiness.file_status == "unavailable"
    path.write_text(json.dumps({"OPENAI_API_KEY": "SECRET-MARKER", "EXTRA": ""}))
    blocked = service.review(selected)
    assert blocked.credential_readiness.missing_names == ("EXTRA",)
    assert not blocked.credential_readiness.ready
    path.write_text(json.dumps({"OPENAI_API_KEY": "SECRET-MARKER", "EXTRA": "nonempty"}))
    path.chmod(0o644)
    assert service.review(selected).credential_readiness.file_status == "unavailable"
    path.chmod(0o600)
    ready = service.review(selected)
    assert ready.credential_readiness.ready
    assert ready.credential_readiness.present_names == ("OPENAI_API_KEY", "EXTRA")
    assert "SECRET-MARKER" not in ready.model_dump_json()
    path.write_text("{}")
    monkeypatch.setattr(
        "tools.candidate_console.service.submit_operation", lambda *a, **k: pytest.fail("admission")
    )
    with pytest.raises(OperationFailure, match="OPENAI_API_KEY"):
        service.launch(
            LaunchSelection(
                prepare_operation_id=selection.operation_id,
                candidate_operation_id=uuid4(),
                expected_prepared_digest=ready.prepared_digest,
            )
        )


def test_policy_and_digest_fail_before_private_read(prepared, monkeypatch):
    """A fabricated association or stale launch must never read the private source."""
    service, selection, _ = prepared
    monkeypatch.setattr(
        "tools.candidate_console.files.private_bytes", lambda *a: pytest.fail("private access")
    )
    choice = service.choices()[0]
    assert choice.task_manifest == service.config.tasks[0].task_manifest
    assert choice.candidate_root == service.config.tasks[0].candidate_root
    with pytest.raises(OperationFailure, match="changed"):
        service.launch(
            LaunchSelection(
                prepare_operation_id=selection.operation_id,
                candidate_operation_id=uuid4(),
                expected_prepared_digest="0" * 64,
            )
        )
    task = service.config.tasks[0]
    service.config = service.config.model_copy(
        update={
            "tasks": (task.model_copy(update={"candidate_network": not task.candidate_network}),)
        }
    )
    with pytest.raises(OperationFailure, match="exactly one"):
        service.review(PreparedSelection(prepare_operation_id=selection.operation_id))


def test_http_projection_never_includes_values(prepared, tmp_path):
    """HTTP must use the bounded projection and retain declared extra requirements."""
    from tests.unit.tools.candidate_console.test_http import client

    service, selection, _ = prepared
    path = tmp_path / "keys.json"
    path.write_text(
        json.dumps({"OPENAI_API_KEY": "SECRET-HTTP", "EXTRA": "EXTRA-SECRET", "UNRELATED": "NO"})
    )
    path.chmod(0o600)
    config = service.config.model_copy(update={"credential_file": str(path)})
    with client(config) as http:
        response = http.get(f"/api/preparations/{selection.operation_id}/review")
        assert response.status_code == 200
        assert response.json()["credential_readiness"]["ready"]
        assert "SECRET" not in response.text and "UNRELATED" not in response.text
        path.write_text('{"EXTRA": "SECRET-HTTP", broken')
        response = http.get(f"/api/preparations/{selection.operation_id}/review")
        assert response.status_code == 200
        assert response.json()["credential_readiness"]["file_status"] == "unavailable"
        assert "SECRET" not in response.text and "broken" not in response.text


def test_mixed_routes_and_unused_private_file_follow_worker_policy(prepared, monkeypatch):
    """Console cannot drift from mixed worker routes or inspect keys for inactive routes."""
    from tools.candidate_console.readiness import credential_readiness
    from tools.candidate_operations import read_prepared_candidate
    from tools.candidate_worker.preflight import credential_requirements

    service, selection, _ = prepared
    request = read_prepared_candidate(
        service.config.operation_store, selection.operation_id
    ).request
    base = request.selected_constructor_routes[0]
    gemini = base.model_copy(
        update={
            "name": "other",
            "transport": base.transport.model_copy(update={"provider": "gemini"}),
        }
    )
    mixed = request.model_copy(
        update={
            "selected_constructor_routes": (base, gemini),
            "environment_names": ("OPENAI_API_KEY",),
        }
    )
    result = credential_readiness(mixed, None)
    assert result.required_names == ("GEMINI_API_KEY", "OPENAI_API_KEY")
    assert result.omitted_names == ("GEMINI_API_KEY",)
    assert (
        result.omitted_names
        == credential_requirements(
            mixed.selected_constructor_routes, mixed.environment_names
        ).omitted_names
    )
    assert "Set credential_file in console.json" in " ".join(result.instructions)
    monkeypatch.setattr(
        "tools.candidate_console.readiness.credential_values",
        lambda *a: pytest.fail("unused private source read"),
    )
    for applicability, expected_ready in (
        ("disabled", True),
        ("pseudo", True),
        ("conditional", False),
    ):
        route = base.model_copy(update={"transport": None, "applicability": applicability})
        inactive = request.model_copy(
            update={"selected_constructor_routes": (route,), "environment_names": ()}
        )
        result = credential_readiness(inactive, "/unused/private.json")
        assert result.file_status == "not_needed"
        assert result.ready is expected_ready
