"""Admission and reconciliation failure classes; real sandbox owns supervision."""

import importlib
from pathlib import Path

import pytest

from tools.candidate_prepare import prepare_candidate
from tools.workspace_sandbox.runner import ExecutionResult

launch = importlib.import_module("tools.candidate_prepare.launch")


@pytest.mark.parametrize(
    "change",
    [
        "alias",
        "overlap",
        "source_parent",
        "broad_mount",
        "existing_output",
        "existing_run",
        "bad_profile",
        "reserved_env",
    ],
)
def test_invalid_selection_never_claims_output(selection, change):
    """Incorrect destination/config admission must fail before any owned writes."""
    if change == "alias":
        selection = selection.model_copy(update={"data_root": selection.data_root + "/."})
    elif change == "overlap":
        selection = selection.model_copy(update={"candidate_workspace": selection.output_dir})
    elif change == "source_parent":
        selection = selection.model_copy(
            update={"task_read_only": (str(Path(selection.output_dir).parent),)}
        )
    elif change == "broad_mount":
        selection = selection.model_copy(update={"task_read_only": ("/home",)})
    elif change == "existing_output":
        Path(selection.output_dir).mkdir()
    elif change == "existing_run":
        Path(selection.candidate_workspace).mkdir()
    elif change == "bad_profile":
        Path(selection.llm_config_file).write_text('{"typo":true}')
    else:
        selection = selection.model_copy(update={"candidate_environment_names": ("PYTHONPATH",)})
    with pytest.raises(ValueError):
        prepare_candidate(selection)
    assert not (Path(selection.output_dir) / "preparation").exists()


@pytest.mark.parametrize("status", ["failed", "timed_out"])
def test_process_failure_dominates_and_future_options_are_not_applied(
    selection, monkeypatch, status
):
    """A success-shaped child file cannot override process failure or grant network/env."""
    selection = selection.model_copy(
        update={"candidate_network": True, "candidate_environment_names": ("OPENAI_API_KEY",)}
    )

    def run(profile, argv):
        assert not profile.network and profile.devices == () and profile.environment_names == ()
        assert Path(selection.data_root) in profile.read_only
        assert profile.timeout_seconds == 30.0
        assert argv[-2] == "tools.candidate_prepare.child"
        (profile.workspace / "preparation/child.json").write_text("{}")
        return ExecutionResult(status=status, returncode=1, elapsed_seconds=0.0)

    monkeypatch.setattr(launch, "run", run)
    receipt = prepare_candidate(selection)
    assert receipt.status == status
    assert not Path(selection.candidate_workspace).exists()
    assert not (Path(selection.output_dir) / "candidate_request.json").exists()
    with pytest.raises(ValueError, match="absent"):
        prepare_candidate(selection)


def test_changed_original_after_claim_refuses_before_native_import(selection, monkeypatch):
    """Rechecking original bytes is reachable in the fixed child entry."""

    def run(profile, argv):
        from tools.candidate_prepare.child import execute

        Path(selection.llm_config_file).write_text('{"propose":null}')
        execute(Path(argv[-1]))
        raise AssertionError("changed source reached preparation")

    monkeypatch.setattr(launch, "run", run)
    receipt = prepare_candidate(selection)
    assert receipt.status == "failed"
    assert "selected input changed" in receipt.error
    assert not (Path(selection.output_dir) / "proposal.json").exists()


def test_missing_child_index_is_failed_not_prepared(selection, monkeypatch):
    monkeypatch.setattr(
        launch,
        "run",
        lambda *args: ExecutionResult(status="completed", returncode=0, elapsed_seconds=0.0),
    )
    receipt = prepare_candidate(selection)
    assert receipt.status == "failed"
    assert receipt.candidate_request_path is None


@pytest.mark.parametrize(
    "change", ["control", "index_id", "fingerprint", "artifact", "workspace", "source"]
)
def test_successful_child_requires_complete_unchanged_reconciliation(
    selection, monkeypatch, change
):
    """Completed child status alone cannot publish a launchable request."""
    import json
    import subprocess

    def child_then_change(profile, argv):
        child = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        assert child.returncode == 0, child.stderr
        output = profile.workspace
        index_path = output / "preparation/child.json"
        index = json.loads(index_path.read_text())
        if change == "control":
            path = output / "preparation/request.json"
            payload = json.loads(path.read_text())
            payload["request"]["run_name"] = "changed"
            path.write_text(json.dumps(payload))
        elif change == "index_id":
            index["preparation_id"] = "00000000-0000-0000-0000-000000000000"
            index_path.write_text(json.dumps(index))
        elif change == "fingerprint":
            index["composition_fingerprint"] = "different"
            index_path.write_text(json.dumps(index))
        elif change == "artifact":
            (output / "interpretation.json").write_text("{}")
        elif change == "workspace":
            Path(selection.candidate_workspace).mkdir()
        else:
            Path(selection.llm_config_file).write_text('{"propose":null}')
        return ExecutionResult(status="completed", returncode=0, elapsed_seconds=0.0)

    monkeypatch.setattr(launch, "run", child_then_change)
    receipt = prepare_candidate(selection)
    assert receipt.status == "failed"
    assert not (Path(selection.output_dir) / "candidate_request.json").exists()


def test_competing_preparers_have_one_claim(selection, monkeypatch):
    """Both callers may admit, but only the mkdir winner can write a receipt."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    barrier = Barrier(2)
    original = launch.admit

    def together(request):
        result = original(request)
        barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(launch, "admit", together)
    monkeypatch.setattr(
        launch,
        "run",
        lambda *args: ExecutionResult(status="failed", returncode=1, elapsed_seconds=0.0),
    )

    def call():
        try:
            return prepare_candidate(selection)
        except FileExistsError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: call(), range(2)))
    assert sum(item is not None for item in results) == 1
    assert (Path(selection.output_dir) / "preparation/receipt.json").is_file()
