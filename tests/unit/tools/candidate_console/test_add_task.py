"""``add-task`` registration and ``check``'s task package mount admission (#1145 items 1, 5)."""

import hashlib
import json
import stat
import sys
from pathlib import Path

import pytest

from tests.unit.tools.candidate_console.conftest import copy_quickstart_package
from tools.candidate_console.add_task import AddTaskRefused, AddTaskRequest, plan_task, publish_task
from tools.candidate_console.settings_models import SETTINGS_SCHEMA, GlobalSettings, LibraryRef
from tools.candidate_console.workspace import init_workspace

REPO = Path(__file__).resolve().parents[4]
GPU_WARNING = (
    "GPU devices are passed but /sys is not mounted read-only; CUDA may fail to start "
    "inside the run sandbox (see README)."
)


def _main(monkeypatch, capsys, *argv):
    from tools.candidate_console.__main__ import main

    monkeypatch.setattr(sys, "argv", ["candidate_console", *argv])
    code = main()
    captured = capsys.readouterr()
    return code, captured.out, captured.err


@pytest.fixture
def workspace(tmp_path):
    """An init workspace holding the quickstart package as ``tasks/quickstart`` and its data."""
    parent = tmp_path / "project"
    parent.mkdir(mode=0o700)
    config = init_workspace(str(parent))
    root = config.parent.parent
    manifest, _ = copy_quickstart_package(root / "tasks" / "quickstart")
    (root / "data" / "quickstart").mkdir()
    return root, config, manifest


def _tasks(config: Path) -> list[dict]:
    return json.loads(config.read_text())["tasks"]


def test_add_task_writes_starter_fields_and_package_mount_and_check_passes(
    workspace, monkeypatch, capsys
):
    """Defect: add-task omits a required field, leaves the package unmounted or breaks check.

    Fails if the entry carries any field beyond the five resource fields plus
    identity and package mount, if a starter value drifts from 300 s / 3600 s /
    network on, if the package folder is not ``task_read_only``, if other
    console.json keys are reordered, or if the follow-up check does not pass.
    """
    root, config, manifest = workspace
    before = list(json.loads(config.read_text()))
    code, out, err = _main(
        monkeypatch, capsys, "add-task", "--config", str(config), "--manifest", str(manifest)
    )
    assert code == 0, err
    assert "Restart the console to load the new task." in out
    assert "candidate_devices: none" in out  # non-interactive default is printed
    (entry,) = _tasks(config)
    assert entry == {
        "task_id": "quickstart",
        "label": "quickstart",
        "task_manifest": str(manifest),
        "task_read_only": [str(root / "tasks" / "quickstart")],
        "preparation_timeout_seconds": 300.0,
        "candidate_timeout_seconds": 3600.0,
        "candidate_network": True,
        "candidate_devices": [],
        "candidate_environment_names": ["OPENAI_API_KEY"],
    }
    assert list(json.loads(config.read_text())) == before
    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    assert stat.S_IMODE((root / "tasks").stat().st_mode) == 0o700  # created by init
    for parent in ("preparations", "candidates", "runs"):
        assert (root / parent / "quickstart").is_dir()  # folder creation ran
    assert _main(monkeypatch, capsys, "check", "--config", str(config))[0] == 0


def test_environment_names_come_from_the_selected_llm_profile(workspace, monkeypatch, capsys):
    """Defect: env names are hard-coded instead of read from the task's LLM profile.

    The DeepSeek profile selected in global settings needs only DEEPSEEK_API_KEY;
    the assertion fails if the init default (OpenAI) or a fixed list is written.
    """
    root, config, manifest = workspace
    profile = (REPO / "configs/llm/deepseek_tiered_pro.json").read_bytes()
    digest = hashlib.sha256(profile).hexdigest()
    name = f"deepseek-{digest[:12]}.json"
    (root / "library" / "llm" / name).write_bytes(profile)
    settings = root / "settings" / "global_settings.json"
    selection = GlobalSettings(
        schema_version=SETTINGS_SCHEMA, llm_profile=LibraryRef(name=name, sha256=digest)
    )
    settings.write_text(selection.model_dump_json())
    settings.chmod(0o600)
    code, _, err = _main(
        monkeypatch,
        capsys,
        "add-task",
        "--config",
        str(config),
        "--manifest",
        str(manifest),
        "--env",
        "EXTRA_NAME",
    )
    assert code == 0, err
    assert _tasks(config)[0]["candidate_environment_names"] == ["DEEPSEEK_API_KEY", "EXTRA_NAME"]


def test_compare_and_swap_refuses_a_console_json_changed_after_reading(workspace):
    """Defect: add-task overwrites an edit made between its read and its write.

    Fails if publish replaces the concurrently written bytes.
    """
    _, config, manifest = workspace
    plan = plan_task(AddTaskRequest(config=str(config), manifest=str(manifest), devices=()))
    edited = config.read_text().replace('"tasks": []', '"tasks": [], "credential_file": null')
    config.write_text(edited)
    with pytest.raises(AddTaskRefused, match="changed since add-task read it"):
        publish_task(plan)
    assert config.read_text() == edited


def test_dry_run_prints_the_entry_and_writes_nothing(workspace, monkeypatch, capsys):
    """Defect: --dry-run writes console.json or creates task folders."""
    root, config, manifest = workspace
    original = config.read_bytes()
    code, out, _ = _main(
        monkeypatch,
        capsys,
        "add-task",
        "--config",
        str(config),
        "--manifest",
        str(manifest),
        "--dry-run",
    )
    assert code == 0
    assert '"task_id": "quickstart"' in out and "was not changed" in out
    assert config.read_bytes() == original
    assert not (root / "preparations" / "quickstart").exists()


def test_duplicate_task_id_is_refused(workspace, monkeypatch, capsys):
    """Defect: a second add-task with the same ID appends a duplicate or rewrites the first."""
    _, config, manifest = workspace
    argv = ("add-task", "--config", str(config), "--manifest", str(manifest))
    assert _main(monkeypatch, capsys, *argv)[0] == 0
    written = config.read_bytes()
    code, _, err = _main(monkeypatch, capsys, *argv, "--label", "Other")
    assert code == 2 and "already has a task 'quickstart'" in err
    assert config.read_bytes() == written


def test_manifest_outside_tasks_needs_external_and_mounts_its_referenced_folders(
    workspace, tmp_path, monkeypatch, capsys
):
    """Defect: a manifest outside <workspace>/tasks/ is accepted silently, or --external
    registers it without mounting the folders its plugins and declarations live in."""
    _, config, _ = workspace
    manifest, package = copy_quickstart_package(tmp_path / "elsewhere")
    argv = ("add-task", "--config", str(config), "--manifest", str(manifest))
    code, _, err = _main(monkeypatch, capsys, *argv, "--task-id", "quickstart")
    assert code == 2 and "pass --external" in err
    assert _tasks(config) == []
    (Path(config).parent.parent / "data" / "outside").mkdir()
    code, _, err = _main(monkeypatch, capsys, *argv, "--task-id", "outside", "--external")
    assert code == 0, err
    assert _tasks(config)[0]["task_read_only"] == [
        str(package / "declared"),
        str(package / "plugins"),
    ]


def test_check_refuses_a_referenced_plugin_outside_every_mount_and_names_it(
    workspace, monkeypatch, capsys
):
    """Defect (#1145 item 1): check accepts a package whose plugin the sandbox cannot see.

    A hand-written entry without ``task_read_only`` leaves ``plugins/`` unmounted;
    the assertion fails if check passes or does not name the plugin file.
    """
    root, config, manifest = workspace
    document = json.loads(config.read_text())
    document["tasks"] = [
        {
            "task_id": "quickstart",
            "label": "Quickstart",
            "task_manifest": str(manifest),
            "preparation_timeout_seconds": 300,
            "candidate_timeout_seconds": 3600,
            "candidate_network": False,
            "candidate_devices": [],
            "candidate_environment_names": [],
        }
    ]
    config.write_text(json.dumps(document))
    init_workspace(str(root.parent))
    code, _, err = _main(monkeypatch, capsys, "check", "--config", str(config))
    plugin = root / "tasks/quickstart/examples/quickstart/plugins/_quickstart_task.py"
    assert code == 2
    assert f"names {plugin}, which is outside every mounted path" in err


@pytest.mark.parametrize("read_only_sys", [False, True])
def test_check_warns_when_gpu_devices_are_passed_without_sys(
    read_only_sys, workspace, monkeypatch, capsys
):
    """Defect (#1145 item 5): GPU device nodes without a read-only /sys pass silently.

    The warning must appear (and check still succeed) without /sys, and must
    not appear when /sys is listed in task_read_only.
    """
    _, config, manifest = workspace
    argv = ("add-task", "--config", str(config), "--manifest", str(manifest))
    assert _main(monkeypatch, capsys, *argv, "--device", "/dev/nvidia0", "/dev/nvidiactl")[0] == 0
    if read_only_sys:
        document = json.loads(config.read_text())
        document["tasks"][0]["task_read_only"].append("/sys")
        config.write_text(json.dumps(document))
    code, _, err = _main(monkeypatch, capsys, "check", "--config", str(config))
    assert code == 0, err
    assert (GPU_WARNING in err) is not read_only_sys


def test_interactive_prompt_passes_the_listed_nvidia_nodes(workspace, monkeypatch, capsys):
    """Defect: without --device on a TTY, the listed host GPU nodes are not offered or not used."""
    _, config, manifest = workspace
    nodes = ("/dev/nvidia0", "/dev/nvidiactl")
    monkeypatch.setattr("tools.candidate_console.add_task.host_gpu_devices", lambda: nodes)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    plan = plan_task(AddTaskRequest(config=str(config), manifest=str(manifest)))
    assert plan.entry["candidate_devices"] == list(nodes)
    assert "/dev/nvidia0, /dev/nvidiactl" in capsys.readouterr().out


def test_add_task_and_check_never_print_a_credential_value(workspace, monkeypatch, capsys):
    """Defect: a configured credential value reaches add-task or check output."""
    root, config, manifest = workspace
    secret = "sk-never-printed-" + "x" * 24
    credentials = root.parent / "credentials.env"
    credentials.write_text(f"OPENAI_API_KEY={secret}\n")
    credentials.chmod(0o600)
    document = json.loads(config.read_text())
    document["credential_file"] = str(credentials)
    config.write_text(json.dumps(document))
    code, out, err = _main(
        monkeypatch, capsys, "add-task", "--config", str(config), "--manifest", str(manifest)
    )
    assert code == 0, err
    check = _main(monkeypatch, capsys, "check", "--config", str(config))
    assert check[0] == 0
    assert secret not in out + err + check[1] + check[2]
