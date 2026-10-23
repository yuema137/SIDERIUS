"""Actual prepared-binding regression and preserved bridge security refusal."""

import json
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest


@pytest.fixture
def selection(selection):
    profile = {
        role: {"provider": "gemini", "model_id": "gemini-3.1-flash-lite-preview"}
        for role in ("implement", "validate_model")
    }
    profile["propose"] = {
        stage: {"provider": "gemini", "model_id": "gemini-3.1-flash-lite-preview"}
        for stage in ("comparison", "reasoning", "proposing")
    }
    Path(selection.llm_config_file).write_text(json.dumps(profile))
    assert selection.candidate_environment_names == ()
    return selection


def test_actual_prepared_gemini_refused_before_new_claim(prepared, monkeypatch):
    """#809: actual offline preparation with omitted Gemini binding cannot claim an operation."""
    from tools.candidate_console import LaunchSelection, PreparedSelection
    from tools.candidate_operations import read_prepared_candidate

    service, selection, _ = prepared
    saved = read_prepared_candidate(service.config.operation_store, selection.operation_id)
    assert saved.request.environment_names == ()
    assert {route.transport.provider for route in saved.request.selected_constructor_routes} == {
        "gemini"
    }
    review = service.review(PreparedSelection(prepare_operation_id=selection.operation_id))
    monkeypatch.setattr("tools.candidate_operations.submit.releasable", lambda *args: True)
    candidate_id = uuid4()
    spawn = Mock()
    monkeypatch.setattr("tools.candidate_operations.submit.spawn", spawn)
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        service.launch(
            LaunchSelection(
                prepare_operation_id=selection.operation_id,
                candidate_operation_id=candidate_id,
                expected_prepared_digest=review.prepared_digest,
            )
        )
    assert not (
        Path(service.config.operation_store.state_root) / "operations" / str(candidate_id)
    ).exists()
    assert not Path(saved.request.preview.document.definition.task.workspace).exists()
    spawn.assert_not_called()


def test_native_provider_helper_refuses_unbound_gemini_without_constructing_client(monkeypatch):
    from agent.llm_bridge import LLMBridge, _provider_credential_or_refuse
    from agent.llm_settings import KNOWN_PROVIDERS
    from agent.schemas.telemetry import LLMBridgeContextError

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    client = Mock(side_effect=AssertionError("client construction must not happen"))
    monkeypatch.setattr("agent.llm_bridge.OpenAI", client)
    with pytest.raises(LLMBridgeContextError, match="GEMINI_API_KEY"):
        _provider_credential_or_refuse("gemini", KNOWN_PROVIDERS["gemini"])
    with pytest.raises(LLMBridgeContextError, match="GEMINI_API_KEY"):
        LLMBridge(provider="gemini", model_id="gemini-3.1-flash-lite-preview")
    client.assert_not_called()


def test_missing_binding_is_safe_public_http_and_cli_error(prepared, monkeypatch, tmp_path, capsys):
    """A plain ValueError regresses HTTP to 500 and CLI to uncategorized input failure."""
    from tests.unit.tools.candidate_console.test_http import client
    from tools.candidate_console import PreparedSelection
    from tools.candidate_operations import CandidateOperation, read_prepared_candidate
    from tools.candidate_operations import __main__ as cli

    service, selection, _ = prepared
    saved = read_prepared_candidate(service.config.operation_store, selection.operation_id)
    review = service.review(PreparedSelection(prepare_operation_id=selection.operation_id))
    monkeypatch.setattr("tools.candidate_operations.submit.releasable", lambda *args: True)
    spawn = Mock()
    monkeypatch.setattr("tools.candidate_operations.submit.spawn", spawn)
    candidate_id = uuid4()
    with client(service.config) as http:
        response = http.post(
            "/api/candidates",
            json={
                "prepare_operation_id": str(selection.operation_id),
                "candidate_operation_id": str(candidate_id),
                "expected_prepared_digest": review.prepared_digest,
            },
        )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "credentials"
    assert "GEMINI_API_KEY" in response.text
    config_path, request_path = tmp_path / "store.json", tmp_path / "candidate.json"
    config_path.write_text(service.config.operation_store.model_dump_json())
    request_path.write_text(
        CandidateOperation(request_id=candidate_id, request=saved.request).model_dump_json()
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "candidate_operations",
            "submit",
            "--store-config",
            str(config_path),
            "--request",
            str(request_path),
        ],
    )
    assert cli.main() == 2
    error = json.loads(capsys.readouterr().err)
    assert error["code"] == "credentials" and "GEMINI_API_KEY" in error["message"]
    assert not (
        Path(service.config.operation_store.state_root) / "operations" / str(candidate_id)
    ).exists()
    spawn.assert_not_called()
