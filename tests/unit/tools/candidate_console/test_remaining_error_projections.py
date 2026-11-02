"""Issue 1328: raw nested causes must not cross settings/import/device boundaries."""

from pathlib import Path

import pytest

from tests.unit.tools.candidate_console.test_add_task import _main
from tests.unit.tools.candidate_console.test_add_task import workspace as task_workspace
from tests.unit.tools.candidate_console.test_bundle_import import bundle, bundle_zip
from tests.unit.tools.candidate_console.test_bundle_import import workspace as bundle_workspace
from tests.unit.tools.candidate_console.test_editor import editor_config
from tests.unit.tools.candidate_console.test_host_ledger import ledgered
from tests.unit.tools.candidate_console.test_settings_export import _export, exported
from tests.unit.tools.candidate_console.test_settings_page import _client, _load, workspace
from tests.unit.tools.candidate_console.test_settings_page import workspace as settings_workspace
from tools.candidate_console.package_mounts import device_warnings

SENTINEL = "private-cause-1328"


def _raise_private(*args, **kwargs):
    raise type("PrivateTaskError1328", (ValueError,), {})(SENTINEL)


@pytest.mark.parametrize("kind", ["llm", "advice"])
def test_upload_http_keeps_nested_causes_private(kind, workspace, monkeypatch, caplog):
    api = _client(_load(workspace))
    owner = (
        "tools.candidate_console.settings_library._profile"
        if kind == "llm"
        else "workflows.advice.parse_advice_bytes"
    )
    monkeypatch.setattr(owner, _raise_private)
    response = api.post(
        "/api/settings/library", json={"kind": kind, "label": "example", "content": "{}"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_file"
    assert SENTINEL not in response.text and "PrivateTaskError1328" not in response.text
    assert SENTINEL in caplog.text


def test_export_http_keeps_profile_cause_private(exported, monkeypatch, caplog):
    root, source = exported
    api = _client(_load(root))
    monkeypatch.setattr("workflows.llm_config.parse_llm_config_bytes", _raise_private)
    response = _export(api, source)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_profile"
    assert SENTINEL not in response.text and "PrivateTaskError1328" not in response.text
    assert SENTINEL in caplog.text
    assert not (root / "exported_configs" / "my-export").exists()


def test_external_manifest_cli_keeps_cause_private(task_workspace, monkeypatch, capsys, tmp_path):
    _, config, manifest = task_workspace
    external = tmp_path / "external.yaml"
    external.write_bytes(manifest.read_bytes())
    monkeypatch.setattr("workflows.task_package_refs.manifest_references", _raise_private)
    code, out, err = _main(
        monkeypatch,
        capsys,
        "add-task",
        "--config",
        str(config),
        "--manifest",
        str(external),
        "--task-id",
        "outside",
        "--external",
    )
    assert code == 2
    assert SENTINEL not in out + err and "PrivateTaskError1328" not in out + err
    assert "Invalid value." in err


def test_device_warning_retains_fixed_guidance_without_nested_cause(monkeypatch):
    def refuse(paths):
        raise ValueError(
            "devices must be explicit character-device paths under /dev"
        ) from ValueError(SENTINEL)

    monkeypatch.setattr(
        "tools.candidate_console.package_mounts.SandboxProfile.device_paths", refuse
    )
    (warning,) = device_warnings(("/dev/example",))
    assert "devices must be explicit character-device paths under /dev" in warning
    assert SENTINEL not in warning


def test_missing_gpu_warning_retains_host_recovery_guidance(monkeypatch):
    device = "/dev/nvidia987654321"
    exists = Path.exists
    monkeypatch.setattr(Path, "exists", lambda path: False if str(path) == device else exists(path))
    (warning,) = device_warnings((device,))
    assert f"GPU device {device} is not present on this machine" in warning
    assert "(ls /dev/nvidia*) or run on the machine that has it" in warning


def test_advice_upload_does_not_echo_unrecognised_keys(workspace):
    import json

    response = _client(_load(workspace)).post(
        "/api/settings/library",
        json={"kind": "advice", "label": "notes", "content": json.dumps({SENTINEL: "value"})},
    )
    assert response.status_code == 422
    assert SENTINEL not in response.text
    assert "recognised keys" in response.text and "propose" in response.text


@pytest.mark.parametrize("endpoint", ["draft", "review"])
def test_authoring_http_retains_validation_guidance_without_input_snapshot(editor_config, endpoint):
    from fastapi.testclient import TestClient

    from tests.unit.workflows.test_workflow_definition import definition
    from tools.candidate_console.app import create_app
    from workflows.definition import WorkflowDocument
    from workflows.definition.source import render_workflow_source

    document = WorkflowDocument(definition=definition())
    editor_config.editor_projects[0].source_file.write_text(render_workflow_source(document))
    draft = {
        "base_document": document.model_dump(mode="json"),
        "bindings": [
            {
                "node": "implement",
                "argument": "output",
                "source": {"kind": "result", "node": "validate", "port": "result"},
            }
        ],
    }
    headers = {
        "Authorization": "Bearer " + Path(editor_config.auth_token_file).read_text(),
        "Origin": editor_config.browser_origin,
    }
    with TestClient(create_app(editor_config), base_url=editor_config.browser_origin) as api:
        base = api.get("/api/editor/example", headers=headers).json()
        payload = {"expected_sha256": base["sha256"]}
        if endpoint == "draft":
            payload["draft"] = draft
        else:
            payload["proposal"] = {"kind": "draft", "draft": draft}
        response = api.post("/api/editor/example/" + endpoint, json=payload, headers=headers)
    assert response.status_code == (200 if endpoint == "draft" else 409)
    text = str(
        response.json()["inspection"]["diagnostics"]
        if endpoint == "draft"
        else response.json()["error"]["message"]
    )
    assert "implement.output: requires proposal.output, got validation.output" in text
    assert "input_value" not in text and "input_type" not in text


def test_copy_failure_cli_keeps_cause_private(bundle, bundle_workspace, monkeypatch, capsys):
    from tests.unit.tools.candidate_console.test_bundle_import import _import

    _, config = bundle_workspace

    def fail_write(*args, **kwargs):
        raise OSError(SENTINEL)

    monkeypatch.setattr("tools.candidate_console.files.write_once", fail_write)
    code, out, err = _import(monkeypatch, capsys, config, bundle)
    assert code == 2
    assert "Filesystem error." in err and "was left in place" in err
    assert SENTINEL not in out + err


def test_host_ledger_nested_cause_is_private(ledgered, monkeypatch, caplog):
    from core.runtime_control.budget_intake import HostBudgetFileError
    from tools.candidate_console.config import host_scheduling

    def refuse(*args):
        raise HostBudgetFileError(SENTINEL)

    monkeypatch.setattr("tools.candidate_console.config.load_host_budget_file", refuse)
    with pytest.raises(ValueError) as failure:
        host_scheduling(ledgered)
    assert SENTINEL not in str(failure.value)
    assert "host_ledger.budget_file" in str(failure.value)
    assert SENTINEL in caplog.text
