"""``add-task --from-bundle``: verified copy, task registration and the first setup."""

import hashlib
import json
import re
import stat
import subprocess
import sys
import zipfile
from pathlib import Path
from uuid import uuid4

import pytest

from tools.candidate_console.config import load_console
from tools.candidate_console.reusable_preparation import NewRunSelection, ReusablePreparation
from tools.candidate_console.service import CandidateConsole
from tools.candidate_console.setups import SetupStore
from tools.candidate_console.workspace import init_workspace
from tools.release.build_example_bundle import build
from tools.workflow_authoring.templates import render_shape
from workflows.definition import ReusableTaskReferences

SETUP_ID = "quickstart-research-loop"


def _main(monkeypatch, capsys, *argv):
    from tools.candidate_console.__main__ import main

    monkeypatch.setattr(sys, "argv", ["candidate_console", *argv])
    code = main()
    captured = capsys.readouterr()
    return code, captured.out, captured.err


@pytest.fixture(scope="module")
def bundle_zip(tmp_path_factory) -> Path:
    return build(tmp_path_factory.mktemp("zip"), "0.0.0")


@pytest.fixture
def bundle(bundle_zip, tmp_path) -> Path:
    """The release zip unpacked as a user would."""
    with zipfile.ZipFile(bundle_zip) as archive:
        archive.extractall(tmp_path / "download")
    (top,) = (tmp_path / "download").iterdir()
    return top


@pytest.fixture
def workspace(tmp_path) -> tuple[Path, Path]:
    parent = tmp_path / "project"
    parent.mkdir(mode=0o700)
    config = init_workspace(str(parent))
    return config.parent.parent, config


def _fetch(bundle: Path, root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(bundle / "fetch_data.py"), "--workspace", str(root)],
        capture_output=True,
        text=True,
        timeout=120,
    )


def _import(monkeypatch, capsys, config: Path, bundle: Path, *extra):
    return _main(
        monkeypatch,
        capsys,
        "add-task",
        "--config",
        str(config),
        "--from-bundle",
        str(bundle),
        *extra,
    )


def test_from_bundle_registers_the_task_and_creates_the_setup_and_check_passes(
    bundle, workspace, monkeypatch, capsys
):
    """Defect: the imported package, its task entry or its first setup is incomplete.

    Fails if fetch_data does not write private hash-checked shards into
    ``data/quickstart``, if the package is not copied privately to
    ``tasks/quickstart``, if the task entry does not point at it with the
    bundle's label, if no registry setup bound to the task is created from the
    descriptor's template through the template owner, or if the follow-up check
    (exit 0 of the command) fails.
    """
    root, config = workspace
    fetched = _fetch(bundle, root)
    assert fetched.returncode == 0, fetched.stderr
    data = root / "data" / "quickstart"
    assert stat.S_IMODE(data.stat().st_mode) == 0o700
    shards = sorted(data.iterdir())
    assert [p.name for p in shards] == [f"shard_{i:04d}.csv" for i in range(4)]
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in shards)
    assert not list(bundle.rglob("__pycache__"))  # the verified bundle stays unchanged

    code, out, err = _import(monkeypatch, capsys, config, bundle)
    assert code == 0, err
    assert "Restart the console to load the new task." in out
    package = root / "tasks" / "quickstart"
    copied = sorted(p.relative_to(package).as_posix() for p in package.rglob("*") if p.is_file())
    assert copied == sorted(
        p.relative_to(bundle / "task").as_posix()
        for p in (bundle / "task").rglob("*")
        if p.is_file()
    )
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in package.rglob("*") if p.is_file())
    (entry,) = json.loads(config.read_text())["tasks"]
    assert entry["task_id"] == "quickstart"
    assert entry["label"] == "Quickstart (synthetic classification)"
    assert entry["task_manifest"] == str(package / "task.yaml")
    assert entry["task_read_only"] == [str(package)]
    registry = json.loads((root / "settings" / "experiment_setups.json").read_text())
    (setup,) = registry["setups"]
    assert (setup["setup_id"], setup["task_id"]) == (SETUP_ID, "quickstart")
    assert setup["origin"] == {"template_id": "single-loop-with-advice"}
    source = root / "projects" / SETUP_ID / "workflow.py"
    references = ReusableTaskReferences(
        manifest=str(package / "task.yaml"), data_root=str(root / "data" / "quickstart")
    )
    assert source.read_text() == render_shape("single-loop-with-advice", references)
    assert _main(monkeypatch, capsys, "check", "--config", str(config))[0] == 0


def test_a_file_that_does_not_match_sha256sums_is_refused_before_any_write(
    bundle, workspace, monkeypatch, capsys
):
    """Defect: a modified or corrupted bundle file is copied and registered.

    Fails if the command does not exit 2 naming the file, or if it copies
    anything to ``tasks/`` or changes console.json.
    """
    root, config = workspace
    plugin = bundle / "task" / "plugins" / "_quickstart_task.py"
    plugin.write_text(plugin.read_text() + "\n# changed\n")
    before = config.read_bytes()
    code, _, err = _import(monkeypatch, capsys, config, bundle)
    assert code == 2
    assert "task/plugins/_quickstart_task.py does not match SHA256SUMS" in err
    assert config.read_bytes() == before
    assert list((root / "tasks").iterdir()) == []
    assert not (root / "settings" / "experiment_setups.json").exists()


def test_an_existing_task_folder_is_never_overwritten(bundle, workspace, monkeypatch, capsys):
    """Defect: importing replaces or merges into a task package already in tasks/.

    Fails if the command does not refuse with exit 2, if the existing file
    changes, if anything is added to the folder, or if console.json changes.
    """
    root, config = workspace
    existing = root / "tasks" / "quickstart"
    existing.mkdir(mode=0o700)
    (existing / "task.yaml").write_text("mine\n")
    before = config.read_bytes()
    code, _, err = _import(monkeypatch, capsys, config, bundle)
    assert code == 2
    assert "already exists; nothing was copied" in err
    assert [p.name for p in existing.iterdir()] == ["task.yaml"]
    assert (existing / "task.yaml").read_text() == "mine\n"
    assert config.read_bytes() == before


def test_the_imported_setup_is_admitted_by_a_cpu_only_run_review(
    bundle, workspace, monkeypatch, capsys
):
    """Defect: the imported setup looks configured but New run refuses it.

    The review is the inert New run preflight (no preparation, no model call,
    no GPU device). Fails if the setup is not runnable for its task, if its
    source or the task's mounted package do not pass reusable admission, or if
    the review resolves another data folder.
    """
    root, config = workspace
    assert _fetch(bundle, root).returncode == 0
    assert _import(monkeypatch, capsys, config, bundle)[0] == 0
    resolved = load_console(str(config))
    store = SetupStore.load(
        resolved.config, resolved.settings.workspace_root, resolved.settings.setups_policy
    )
    adapter = ReusablePreparation(CandidateConsole(resolved.config, store))
    source = root / "projects" / SETUP_ID / "workflow.py"
    review = adapter.review(
        SETUP_ID,
        NewRunSelection(
            task_id="quickstart",
            run_name="first-run",
            run_id=uuid4(),
            preparation_operation_id=uuid4(),
            expected_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        ),
    )
    assert review.devices == ()
    assert review.data_root == str(root / "data" / "quickstart")
    assert review.read_only == (str(root / "tasks" / "quickstart"),)


def test_fetch_data_refuses_a_group_writable_data_folder(bundle, workspace):
    """Defect: the data writer puts task data where another user could replace it.

    Fails if fetch_data exits 0 or writes a shard when ``data/`` is group-writable.
    A relative label must not become a chmod command aimed at the caller's cwd.
    """
    root, _ = workspace
    (root / "data").chmod(0o770)
    result = _fetch(bundle, root)
    assert result.returncode == 2
    assert "data must not have group/other write permissions" in result.stderr
    assert "chmod" not in result.stderr
    assert not (root / "data" / "quickstart").exists()


def test_read_bundle_accepts_the_trailing_slash_tab_completion_adds(bundle):
    """Defect: ``--from-bundle DIR/`` (as tab completion types it) is refused."""
    from tools.candidate_console.example_bundle import BundleRefused, read_bundle

    assert read_bundle(f"{bundle}/").root == bundle
    with pytest.raises(BundleRefused, match=re.escape("without '..'")):
        read_bundle(f"{bundle}/../{bundle.name}/")
