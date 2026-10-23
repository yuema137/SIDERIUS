"""Parent ownership and fail-closed reconciliation; native behavior tested separately."""

import importlib
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from tools.candidate_worker import launch_candidate
from tools.candidate_worker.models import CandidateRunReceipt
from tools.workspace_sandbox.runner import ExecutionResult

launch_module = importlib.import_module("tools.candidate_worker.launch")


def test_parent_import_does_not_discover_native_nodes():
    """Fails if public Python/CLI imports can discover plugins before child binding."""
    code = "import sys; import tools.candidate_worker; assert not any(k.startswith(('ml_models.', 'nodes.ml_', 'workflows.task_composition')) for k in sys.modules)"
    subprocess.run([sys.executable, "-c", code], check=True, timeout=20)


@pytest.mark.parametrize("change", ["bytes", "declaration", "routes"])
def test_stale_review_refused_before_workspace_claim(prepared, change):
    """Mutation of any selected review surface must fail without creating workspace."""
    if change == "bytes":
        (Path(prepared.preview.project_root) / "seed.json").write_text("{}")
    else:
        prepared = prepared.model_copy(
            update={"declaration_digest": "stale"}
            if change == "declaration"
            else {"selected_constructor_routes": ()}
        )
    with pytest.raises(ValueError, match="stale"):
        launch_candidate(prepared)
    assert not Path(prepared.preview.document.definition.task.workspace).exists()


def test_competing_launches_have_one_writer(prepared, monkeypatch):
    """A lost mkdir claim must not overwrite the winner's snapshots or receipt."""
    barrier = Barrier(2)
    from tools.candidate_worker import preflight

    real_preview = preflight.preview_workflow

    def together(request):
        result = real_preview(request)
        barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(preflight, "preview_workflow", together)
    monkeypatch.setattr(
        launch_module,
        "run",
        lambda *_: ExecutionResult(status="timed_out", returncode=124, elapsed_seconds=0.1),
    )

    def invoke():
        try:
            return launch_candidate(prepared)
        except FileExistsError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        outputs = list(pool.map(lambda _: invoke(), range(2)))
    assert sum(item is None for item in outputs) == 1
    winner = next(item for item in outputs if item is not None)
    control = Path(winner.workspace) / "candidate_run"
    assert winner.status == "timed_out"
    assert (
        CandidateRunReceipt.model_validate_json((control / "receipt.json").read_bytes()) == winner
    )
    assert len(list(control.glob("*.snapshot"))) == len(prepared.files)


@pytest.mark.parametrize(
    "case", ["missing", "malformed", "wrong_identity", "timeout", "failed", "inconsistent"]
)
def test_process_outcome_cannot_become_validation_success(prepared, monkeypatch, case):
    """Even a success-looking child artifact cannot override supervisor failure."""

    def run(profile, argv):
        control = profile.workspace / "candidate_run"
        initial = CandidateRunReceipt.model_validate_json((control / "launch.json").read_bytes())
        child = initial.model_copy(
            update={
                "status": "accepted",
                "validation_passed": True,
                "native_output_paths": ("a", "b", "c"),
            }
        )
        if case == "wrong_identity":
            child = child.model_copy(update={"run_id": "other"})
        if case == "inconsistent":
            child = child.model_copy(update={"validation_passed": False})
        if case != "missing":
            (control / "child.json").write_text(
                "{" if case == "malformed" else child.model_dump_json()
            )
        return ExecutionResult(
            status="timed_out"
            if case == "timeout"
            else "failed"
            if case == "failed"
            else "completed",
            returncode=124 if case == "timeout" else 1 if case == "failed" else 0,
            elapsed_seconds=0.1,
        )

    monkeypatch.setattr(launch_module, "run", run)
    receipt = launch_candidate(prepared)
    assert receipt.status == ("timed_out" if case == "timeout" else "failed")
    assert receipt.validation_passed is None


def test_cli_passes_exact_typed_request_to_python_boundary(prepared, monkeypatch, tmp_path, capsys):
    """Fails if CLI invents configuration or bypasses the shared launch callable."""
    from tools.candidate_worker import __main__ as cli

    request_file = tmp_path / "request.json"
    request_file.write_text(prepared.model_dump_json())
    captured = []
    monkeypatch.setattr(
        launch_module,
        "run",
        lambda *_: ExecutionResult(status="timed_out", returncode=124, elapsed_seconds=0.0),
    )
    receipt = launch_candidate(prepared)

    def launch(request):
        captured.append(request)
        return receipt

    monkeypatch.setattr(cli, "launch_candidate", launch)
    monkeypatch.setattr(sys, "argv", ["candidate_worker", "--request", str(request_file)])
    assert cli.main() == 1
    assert captured == [prepared]
    assert CandidateRunReceipt.model_validate_json(capsys.readouterr().out) == receipt


def test_fresh_child_binds_before_first_native_import(prepared, monkeypatch, tmp_path):
    """An import hook observes ordering in a new interpreter, not pytest's warm registry."""
    import os

    from .conftest import refresh

    seed_path = Path(prepared.preview.project_root) / "seed.json"
    import json

    seed = json.loads(seed_path.read_text())
    seed.pop("interpretation_evidence")
    seed_path.write_text(json.dumps(seed))
    script = tmp_path / "observe_imports.py"
    script.write_text("""import builtins, os, sys
from pathlib import Path
from core.generated_library import generated_library_is_workspace_bound, generated_library_root
from tools.candidate_worker.child import execute
assert not any(k.startswith("ml_models.") for k in sys.modules)
original = builtins.__import__
def observe(name, *args, **kwargs):
    if name == "native" or name.startswith(("ml_models.", "nodes.ml_", "workflows.task_composition")):
        assert generated_library_is_workspace_bound(), name
        assert generated_library_root() == str(Path(sys.argv[1]).parent.parent / "generated_library")
        Path(sys.argv[1]).parent.joinpath("import-order-observed").touch()
    return original(name, *args, **kwargs)
builtins.__import__ = observe
try:
    execute(Path(sys.argv[1]))
except ValueError as error:
    assert "interpretation_evidence" in str(error), str(error)
else:
    raise AssertionError("malformed seed did not fail")
""")

    def run(profile, argv):
        env = dict(os.environ)
        env.pop("SIDERIUS_CHAIN_WORKSPACE", None)
        env["SIDERIUS_GENERATED_LIBRARY_DIR"] = str(tmp_path / "unrelated-library")
        checked = subprocess.run(
            [sys.executable, str(script), argv[-1]],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert checked.returncode == 0, checked.stderr
        assert (profile.workspace / "candidate_run/import-order-observed").exists()
        return ExecutionResult(status="failed", returncode=1, elapsed_seconds=0.0)

    monkeypatch.setattr(launch_module, "run", run)
    receipt = launch_candidate(refresh(prepared))
    assert receipt.status == "failed"
    assert receipt.error == "worker exit 1"


def test_interrupted_runner_preserves_partial_outputs_without_success(prepared, monkeypatch):
    """The runner owns cleanup; the launch boundary must record interruption honestly."""

    def interrupted(profile, argv):
        (profile.workspace / "partial-native-artifact").write_text("partial")
        raise KeyboardInterrupt

    monkeypatch.setattr(launch_module, "run", interrupted)
    receipt = launch_candidate(prepared)
    assert receipt.status == "interrupted"
    assert receipt.validation_passed is None
    assert (Path(receipt.workspace) / "partial-native-artifact").read_text() == "partial"
    stored = CandidateRunReceipt.model_validate_json(
        (Path(receipt.workspace) / "candidate_run/receipt.json").read_bytes()
    )
    assert stored == receipt


def test_workspace_populated_after_preview_is_refused(prepared, monkeypatch):
    """A successful claim cannot bless content created after the preview check."""
    from tools.candidate_worker import preflight

    real_preview = preflight.preview_workflow

    def changed(request):
        observed = real_preview(request)
        workspace = Path(observed.workspace)
        workspace.mkdir(parents=True)
        (workspace / "unexpected.txt").write_text("preserve me")
        return observed

    monkeypatch.setattr(preflight, "preview_workflow", changed)
    monkeypatch.setattr(launch_module, "run", lambda *_: pytest.fail("must not execute"))
    receipt = launch_candidate(prepared)
    assert receipt.status == "failed"
    assert "nonempty" in receipt.error
    assert (Path(receipt.workspace) / "unexpected.txt").read_text() == "preserve me"
    assert not (Path(receipt.workspace) / "candidate_run/request.json").exists()
