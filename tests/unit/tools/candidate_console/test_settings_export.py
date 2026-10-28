"""Native-format export: saved source, task profile and inline advice; write-once download."""

import hashlib
import json
import stat
from pathlib import Path

import pytest

from tests.unit.tools.candidate_console.test_settings_page import _client, _load
from tests.unit.tools.candidate_console.test_settings_page import workspace as settings_workspace
from workflows.advice import parse_advice_bytes

REPO = Path(__file__).resolve().parents[4]
EXAMPLE = REPO / "examples/workflow_declarations/reusable_training.py"
TUNE = '"result_authority": "diagnostic",'
SECRET = "sk-DO-NOT-EXPORT-0123456789"


@pytest.fixture
def exported(settings_workspace, tmp_path):
    """The settings workspace plus one editor project holding a tuning workflow with advice."""
    root = tmp_path / "project"
    root.mkdir()
    source = root / "workflow.py"
    source.write_text(
        EXAMPLE.read_text().replace(TUNE, TUNE + ' "human_advice_tune": "Stop early on plateaus",')
    )
    recovery = root / "recovery"
    recovery.mkdir(mode=0o700)
    credentials = tmp_path / "credentials.json"
    credentials.write_text(json.dumps({"OPENAI_API_KEY": SECRET}))
    credentials.chmod(0o600)
    config = settings_workspace / "settings" / "console.json"
    document = json.loads(config.read_text()) | {
        "credential_file": str(credentials),
        "editor_projects": [
            {
                "project_id": "demo",
                "project_root": str(root),
                "source_file": str(source),
                "recovery_directory": str(recovery),
            }
        ],
    }
    config.write_text(json.dumps(document))
    return settings_workspace, source


def _export(api, source: Path, name="my-export", sha=None):
    return api.post(
        "/api/settings/exports",
        json={
            "project_id": "demo",
            "task_id": "synthetic",
            "name": name,
            "expected_source_sha256": sha or hashlib.sha256(source.read_bytes()).hexdigest(),
        },
    )


def test_export_writes_native_files_with_inline_advice(exported):
    """Defect: export changes the source, loses an advice carrier or leaks a credential."""
    workspace, source = exported
    resolved = _load(workspace)
    response = _export(_client(resolved), source)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "name": "my-export",
        "files": ["workflow.py", "llm.json", "advice.json"],
    }
    target = workspace / "exported_configs" / "my-export"
    assert stat.S_IMODE(target.stat().st_mode) == 0o700
    assert (target / "workflow.py").read_bytes() == source.read_bytes()
    task_profile = Path(resolved.config.tasks[0].llm_config_file).read_bytes()
    assert (target / "llm.json").read_bytes() == task_profile
    advice = (target / "advice.json").read_bytes()
    assert json.loads(advice) == {
        "propose": "Prefer a small interpretable baseline",
        "implement": "Keep diagnostics explicit",
        "validate": "Inspect held-out residuals",
        "tune": "Stop early on plateaus",
    }
    parse_advice_bytes(advice, label="exported")  # the CLI loader accepts it
    for path in target.iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert SECRET not in path.read_text()


def test_workflow_without_advice_exports_no_advice_file(exported):
    """Defect: an empty advice.json is written, which the advice owner would refuse."""
    workspace, source = exported
    text = source.read_text().replace(' "human_advice_tune": "Stop early on plateaus",', "")
    for line in (
        "Prefer a small interpretable baseline",
        "Keep diagnostics explicit",
        "Inspect held-out residuals",
    ):
        text = text.replace(f'"{line}"', "None")
    source.write_text(text)
    response = _export(_client(_load(workspace)), source)
    assert response.status_code == 200, response.text
    assert response.json()["files"] == ["workflow.py", "llm.json"]
    assert not (workspace / "exported_configs" / "my-export" / "advice.json").exists()


def test_existing_names_and_stale_sources_are_refused_without_writes(exported):
    """Defect: an export overwrites an earlier one, or exports bytes the user did not review."""
    workspace, source = exported
    api = _client(_load(workspace))
    stale = _export(api, source, sha="0" * 64)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale"
    assert not (workspace / "exported_configs" / "my-export").exists()
    assert _export(api, source).status_code == 200
    first = (workspace / "exported_configs" / "my-export" / "workflow.py").read_bytes()
    source.write_text(source.read_text() + "\n# edited\n")
    again = _export(api, source)
    assert again.status_code == 409 and again.json()["error"]["code"] == "exists"
    assert "Try my-export-2" in again.json()["error"]["message"]
    assert (workspace / "exported_configs" / "my-export" / "workflow.py").read_bytes() == first


def test_download_returns_the_server_bytes_and_nothing_else(exported, tmp_path):
    """Defect: download differs from the exported file, or follows a planted link."""
    workspace, source = exported
    api = _client(_load(workspace))
    assert _export(api, source).status_code == 200
    target = workspace / "exported_configs" / "my-export"
    for name in ("workflow.py", "llm.json", "advice.json"):
        response = api.get(f"/api/settings/exports/my-export/{name}")
        assert response.status_code == 200 and response.content == (target / name).read_bytes()
    (target / "advice.json").rename(tmp_path / "moved.json")
    (target / "advice.json").symlink_to(tmp_path / "moved.json")
    assert api.get("/api/settings/exports/my-export/advice.json").status_code == 404
    assert api.get("/api/settings/exports/my-export/console.json").status_code == 422
    assert api.get("/api/settings/exports/nope/llm.json").status_code == 404


def test_export_requires_a_writable_console(exported):
    """Defect: a read-only console still writes export files."""
    workspace, source = exported
    config = workspace / "settings" / "console.json"
    config.write_text(
        json.dumps(
            json.loads(config.read_text()) | {"global_settings": {"browser_writable": False}}
        )
    )
    response = _export(_client(_load(workspace)), source)
    assert response.status_code == 403
    assert not (workspace / "exported_configs").exists()
