"""``add-task`` registration and ``check``'s task package mount admission (#1145 items 1, 5)."""

import hashlib
import json
import stat
import sys
from pathlib import Path

import pytest

from tests.unit.tools.candidate_console.conftest import copy_quickstart_package
from tools.candidate_console.add_task import (
    AddTaskRefused,
    AddTaskRequest,
    host_gpu_devices,
    plan_task,
    publish_task,
)
from tools.candidate_console.settings_models import SETTINGS_SCHEMA, GlobalSettings, LibraryRef
from tools.candidate_console.workspace import init_workspace

REPO = Path(__file__).resolve().parents[4]


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
    assert "candidate_devices: none (no NVIDIA GPU" in out  # the detection is printed
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


@pytest.mark.parametrize("command", ["check", "serve", "init"])
def test_registered_task_schema_errors_name_fields_without_values(
    command, workspace, monkeypatch, capsys
):
    """Defect: a config written by add-task loses field diagnostics or leaks an edited value."""
    root, config, manifest = workspace
    assert (
        _main(
            monkeypatch, capsys, "add-task", "--config", str(config), "--manifest", str(manifest)
        )[0]
        == 0
    )
    data = json.loads(config.read_text())
    del data["tasks"][0]["candidate_network"]
    data["tasks"][0]["label"] = {"secret": "DUMMY_REGISTERED_TASK_SECRET"}
    config.write_text(json.dumps(data))
    args = ("--workspace", str(root.parent)) if command == "init" else ("--config", str(config))
    code, out, err = _main(monkeypatch, capsys, command, *args)
    assert code == 2
    expected = {
        "console.json is invalid at tasks[0].candidate_network (missing)",
        "console.json is invalid at tasks[0].label (string_type)",
    }
    if command == "init":
        expected.add("Nothing was deleted.")
    assert set(err.splitlines()) == expected
    assert "DUMMY_REGISTERED_TASK_SECRET" not in out + err
    assert str(root) not in out + err


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


def test_add_task_refuses_and_check_warns_about_a_device_the_sandbox_cannot_pass(
    workspace, tmp_path, monkeypatch, capsys
):
    """Defect (walkthrough N2): add-task and check accepted /dev/nvidia* paths absent on
    the host, so the first sign was a refused GPU launch that blamed the device list.

    Fails if add-task writes an entry naming a missing path or a non-device file, if
    the refusal does not name the path with the sandbox's own reason, or if check
    either stays silent about such a hand-written entry or fails the whole console
    on it (a node like /dev/nvidia-uvm may appear only after first CUDA use).
    """
    _, config, manifest = workspace
    before = config.read_bytes()
    plain = tmp_path / "not-a-device"
    plain.write_text("")
    absent = "/dev/siderius-absent-node0"
    argv = ("add-task", "--config", str(config), "--manifest", str(manifest), "--device")
    for device, why in (
        (absent, f"declared path does not exist: {absent}"),
        (str(plain), "devices must be explicit character-device paths under /dev"),
        # Exists and is a character device, but is not canonical: the sandbox refuses it.
        ("/dev/../dev/null", "use a canonical absolute path without symlink aliases or '..'"),
    ):
        code, _, err = _main(monkeypatch, capsys, *argv, "/dev/null", device)
        assert code == 2
        assert f"candidate_devices names {device}, which the run sandbox refuses ({why})" in err
        assert config.read_bytes() == before, "a refused add-task wrote console.json"
    assert _main(monkeypatch, capsys, *argv, "/dev/null")[0] == 0
    document = json.loads(config.read_text())
    document["tasks"][0]["candidate_devices"] = ["/dev/null", absent]
    config.write_text(json.dumps(document))
    code, _, err = _main(monkeypatch, capsys, "check", "--config", str(config))
    assert code == 0, err
    assert (
        f"Warning: Task quickstart: Device {absent} cannot be passed into the run sandbox "
        f"(declared path does not exist: {absent}); a run given it will be refused."
    ) in err
    assert "/dev/null" not in err


def test_host_gpu_nodes_are_written_without_asking_and_no_gpu_opts_out(
    workspace, monkeypatch, capsys
):
    """Defect: on a GPU host add-task asks (or, without a TTY, silently writes no
    device), so the first GPU run is refused; or --no-gpu/--device do not override
    the detection. Fails if detection prompts, the detected nodes are not written and
    printed, --no-gpu writes a device, or --device is replaced by the detection."""
    _, config, manifest = workspace
    nodes = ("/dev/nvidia0", "/dev/nvidia1")
    monkeypatch.setattr("tools.candidate_console.add_task.host_gpu_devices", lambda: nodes)
    monkeypatch.setattr("tools.candidate_console.package_mounts.device_problem", lambda _: None)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("add-task must not ask"))
    plan = plan_task(AddTaskRequest(config=str(config), manifest=str(manifest)))
    assert plan.entry["candidate_devices"] == list(nodes)
    assert "candidate_devices: /dev/nvidia0, /dev/nvidia1 (NVIDIA GPU found" in (
        capsys.readouterr().out
    )
    argv = ("add-task", "--dry-run", "--config", str(config), "--manifest", str(manifest))
    code, out, err = _main(monkeypatch, capsys, *argv, "--no-gpu")
    assert code == 0, err
    assert '"candidate_devices": []' in out
    code, out, err = _main(monkeypatch, capsys, *argv, "--device", "/dev/nvidia1")
    assert code == 0, err
    assert '"candidate_devices": [\n' in out and '"/dev/nvidia0"' not in out
    with pytest.raises(SystemExit):
        _main(monkeypatch, capsys, *argv, "--no-gpu", "--device", "/dev/nvidia1")


def test_host_gpu_devices_lists_only_gpu_nodes(monkeypatch):
    """Defect: control nodes such as /dev/nvidia-uvm are written into candidate_devices;
    the node can be absent until first CUDA use, and admission then refuses the run.
    Fails if anything but /dev/nvidia<N> character devices is returned, or if they are
    ordered as text (nvidia10 before nvidia2) instead of by GPU number."""
    from tools.candidate_console import add_task

    names = ["/dev/nvidia-uvm", "/dev/nvidia0", "/dev/nvidia10", "/dev/nvidia2", "/dev/nvidiactl"]
    monkeypatch.setattr(add_task.glob, "glob", lambda _: names)
    monkeypatch.setattr(add_task.Path, "is_char_device", lambda self: True)
    monkeypatch.setattr(add_task.Path, "is_symlink", lambda self: False)
    # The real function: conftest stubs add_task.host_gpu_devices for every other test.
    assert host_gpu_devices() == ("/dev/nvidia0", "/dev/nvidia2", "/dev/nvidia10")


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


def _set_task_data_config(manifest: Path, config: dict) -> None:
    import yaml

    document = yaml.safe_load(manifest.read_text())
    document["task_data_path"]["config"] = config
    manifest.write_text(yaml.safe_dump(document, sort_keys=False))


def test_constructor_config_values_are_not_paths_but_ref_envelopes_are(
    workspace, tmp_path, monkeypatch, capsys
):
    """Defect: task-owned constructor arguments named file/dir/... are checked as paths.

    Composition passes a ``config`` mapping to the constructor unchanged and resolves
    only ``{ref: ...}`` envelopes, which may name a directory or a path that does not
    exist yet. Fails if plain ``file``/``dir``/``declaration`` values (at any depth)
    are refused, if an envelope naming a directory, a missing path or a file under
    the mounted ``/usr`` is refused, or if an envelope outside every mount passes.
    """
    _, config, manifest = workspace
    _set_task_data_config(
        manifest,
        {
            "train_shards": [0, 1],
            "file": "shard_0.csv",
            "dir": "train",
            "nested": {"declaration": "not/a/path.json", "config": "free text"},
            "tool": {"ref": "/usr/bin/env"},
            "cache_dir": {"ref": "cache"},  # an existing directory beside the manifest
            "out": {"ref": "not_yet"},  # a path the task creates later
        },
    )
    (manifest.parent / "cache").mkdir()
    argv = ("add-task", "--config", str(config), "--manifest", str(manifest))
    code, _, err = _main(monkeypatch, capsys, *argv, "--dry-run")
    assert code == 0, err
    outside = tmp_path / "outside.csv"
    outside.write_text("")
    _set_task_data_config(manifest, {"shard": {"ref": str(outside)}})
    code, _, err = _main(monkeypatch, capsys, *argv, "--dry-run")
    assert code == 2
    assert f"task_data_path.config.shard.ref names {outside}, which is outside" in err


@pytest.mark.parametrize("target", ["home", "console"])
def test_external_refuses_mounting_home_or_console_private_folders(
    target, workspace, tmp_path, monkeypatch, capsys
):
    """Defect: --external mounts a folder that is the home folder or holds console secrets.

    Fails if a referenced file directly in $HOME, or in the folder holding the
    workspace (and so its settings/ and token), becomes a task_read_only mount.
    """
    root, config, _ = workspace
    manifest, package = copy_quickstart_package(tmp_path / "elsewhere")
    if target == "home":
        monkeypatch.setenv("HOME", str(package / "plugins"))
        expected = "is or contains your home folder"
    else:
        stray = root.parent / "stray.json"
        stray.write_text("{}")
        _set_task_data_config(manifest, {"extra": {"ref": str(stray)}})
        expected = "overlaps the console's private path"
    code, _, err = _main(
        monkeypatch,
        capsys,
        "add-task",
        "--config",
        str(config),
        "--manifest",
        str(manifest),
        "--external",
        "--task-id",
        "outside",
    )
    assert code == 2 and expected in err and "tasks/<name>/ instead" in err
    assert _tasks(config) == []


def test_relative_manifest_refuses_plainly(workspace, monkeypatch, capsys):
    """Defect: a relative --manifest gets an unexplained 'canonical' refusal."""
    _, config, _ = workspace
    code, _, err = _main(
        monkeypatch, capsys, "add-task", "--config", str(config), "--manifest", "tasks/q.yaml"
    )
    assert code == 2 and "--manifest must be an absolute path" in err
    assert _tasks(config) == []
