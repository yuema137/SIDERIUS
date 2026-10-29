"""CLI configuration failures identify repairs without echoing invalid values."""

import json

import pytest

from tests.unit.tools.candidate_console.test_workspace import _main
from tools.candidate_console.workspace import init_workspace


@pytest.mark.parametrize("command", ["check", "serve", "init"])
@pytest.mark.parametrize(
    ("field", "value", "kind"),
    [
        ("candidate_network", None, "missing"),
        ("label", {"secret": "DUMMY_SECRET_VALUE"}, "string_type"),
        ("unknown_option", "DUMMY_SECRET_VALUE", "extra_forbidden"),
    ],
)
def test_cli_names_schema_location_without_values(
    command, field, value, kind, console_config, tmp_path, monkeypatch, capsys
):
    """Defect: CLI hides the failing field, leaks input values, or starts on invalid input."""
    path = init_workspace(str(tmp_path))
    data = console_config.model_dump(mode="json")
    if kind == "missing":
        del data["tasks"][0][field]
    else:
        data["tasks"][0][field] = value
    path.write_text(json.dumps(data))
    args = ("--workspace", str(tmp_path)) if command == "init" else ("--config", str(path))
    code, out, err = _main(monkeypatch, capsys, command, *args)
    assert code == 2
    notice = "Nothing was deleted.\n" if command == "init" else ""
    assert err == f"console.json is invalid at tasks[0].{field} ({kind})\n" + notice
    assert "DUMMY_SECRET_VALUE" not in out + err
    assert str(tmp_path) not in out + err


@pytest.mark.parametrize("resource", ["source", "task_manifest", "llm_config_file"])
def test_cli_names_missing_configured_file(resource, console_config, tmp_path, monkeypatch, capsys):
    """Defect: an absent project source or task resource produces only a generic refusal."""
    data = console_config.model_dump(mode="json")
    missing = tmp_path / "missing.py"
    if resource == "source":
        recovery = tmp_path / "recovery"
        recovery.mkdir(mode=0o700)
        data["editor_projects"] = [
            dict(
                project_id="quickstart",
                project_root=str(tmp_path),
                source_file=str(missing),
                recovery_directory=str(recovery),
            )
        ]
        item = "experiment setup quickstart"
    else:
        data["tasks"][0][resource] = str(missing)
        item = "task synthetic"
    path = tmp_path / "console.json"
    path.write_text(json.dumps(data))
    path.chmod(0o600)
    code, _, err = _main(monkeypatch, capsys, "check", "--config", str(path))
    assert code == 2
    assert err == f"{item}: {resource} file {missing} is missing\n"


@pytest.mark.parametrize(
    "key",
    [
        "long_" + "field_" * 5,
        "ghp_dummy_token",
        "sk-dummy-token",
        "sk_dummy_token",
        "AbCdEfGhIjKlMnOp1234",
        "AbCdEfGhIjKlMnOp_1234",
    ],
)
def test_cli_redacts_token_like_extra_keys(key, console_config, tmp_path, monkeypatch, capsys):
    """Defect: a pasted token used as an extra JSON key is disclosed as a field location."""
    data = console_config.model_dump(mode="json")
    data["tasks"][0][key] = "DUMMY_VALUE"
    path = tmp_path / "console.json"
    path.write_text(json.dumps(data))
    path.chmod(0o600)
    code, out, err = _main(monkeypatch, capsys, "check", "--config", str(path))
    assert code == 2
    assert err == "console.json is invalid at tasks[0].<key> (extra_forbidden)\n"
    assert key not in out + err
    assert "DUMMY_VALUE" not in out + err
