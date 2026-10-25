"""Native entry ownership and existing phase-cleanup propagation, without training."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from core.native_writer import WriterRefusal
from core.native_writer.models import Participation
from core.native_writer.ownership import TRANSPORT_ENV, acquire, inspect_writer
from core.native_writer.state import WriterState
from workflows import run_one_iteration

ROOT = Path(__file__).resolve().parents[4]


def arguments(workspace):
    return [
        "--workspace",
        str(workspace),
        "--run_name",
        "writer_test",
        "--start_iteration",
        "1",
        "--task_composition",
        str(ROOT / "configs/task_composition/quickstart.yaml"),
        "--data_dir",
        str(workspace.parent),
    ]


def test_direct_main_exclusion_precedes_package_and_failure_writes(tmp_path, monkeypatch):
    """Bypassing the ingress context would reach the injected native body and fail."""
    workspace = tmp_path / "run"
    lease = acquire(workspace)
    monkeypatch.setattr(
        run_one_iteration, "_run_owned_iteration", lambda *a, **k: pytest.fail("entered")
    )
    try:
        with pytest.raises(WriterRefusal, match="writer_active"):
            run_one_iteration.main(arguments(workspace))
        assert not workspace.exists()
    finally:
        lease.close(clean=True)


def test_readonly_main_creates_no_owner_and_legacy_error_releases(tmp_path, monkeypatch):
    workspace = tmp_path / "run"
    monkeypatch.setattr(run_one_iteration, "_run_owned_iteration", lambda *a, **k: None)
    run_one_iteration.main([*arguments(workspace), "--print_resolved_launch_config"])
    assert list(tmp_path.iterdir()) == []

    def failure(*args, **kwargs):
        raise SystemExit(1)

    monkeypatch.setattr(run_one_iteration, "_run_owned_iteration", failure)
    with pytest.raises(SystemExit) as error:
        run_one_iteration.main(arguments(workspace))
    assert error.value.code == 1
    assert inspect_writer(workspace).status == "unregistered"
    another = acquire(workspace)
    another.close(clean=True)


@pytest.mark.parametrize("failed_marker", [False, True])
def test_actual_training_dispatch_cleanup_reaches_ingress_even_when_swallowed(
    tmp_path, monkeypatch, failed_marker
):
    """Real native phase dispatch exits nonzero; caught errors cannot erase uncertainty.

    Only the scientific child command is substituted with a bounded CPU exit.
    Actual main, skill wrapper, sandbox phase and subprocess supervisor run.
    This proves lifecycle propagation, not scientific training qualification.
    """
    from core.sandbox_executor import TidmadSandbox
    from nodes.ml_hyperparameter_tune_agent.runtime import _run_skill
    from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

    workspace = tmp_path / "run"
    lease = acquire(workspace, capture_sha256="a" * 64)
    monkeypatch.setenv(TRANSPORT_ENV, lease.transport.model_dump_json())
    original_publish = WriterState.publish
    if failed_marker:

        def publish(self, name, value):
            if name == "unresolved":
                raise OSError("injected marker persistence failure")
            return original_publish(self, name, value)

        monkeypatch.setattr(WriterState, "publish", publish)
    monkeypatch.setattr("core.sandbox_executor._make_phase_observer", lambda sandbox: None)
    monkeypatch.setattr(
        "core.sandbox_executor.validation_training_command",
        lambda command: [sys.executable, "-c", "import sys; sys.exit(3)"],
    )
    results = []

    def phase_body(*args, **kwargs):
        composition = compose_run_task_bindings(
            str(ROOT / "configs/task_composition/quickstart.yaml")
        )
        with bind_run_task_composition(composition, physical_data_root=str(tmp_path)):
            sandbox = TidmadSandbox(run_name="writer_test", workspace=str(workspace))
            results.append(
                _run_skill(
                    "training_skill",
                    sandbox,
                    exp_id="writer_probe",
                    run_name="writer_test",
                    model_type="fcnet",
                    model_config={
                        "model_type": "fcnet",
                        "segmentation_size": 10000,
                        "latent_dims": [100, 10],
                    },
                    train_config={"lr": 1e-4, "epochs": 1, "batch_size": 1, "device": "cpu"},
                    loss_config={"loss_type": "ce"},
                )
            )

    monkeypatch.setattr(run_one_iteration, "_run_owned_iteration", phase_body)
    try:
        run_one_iteration.main(arguments(workspace))
        assert len(results) == 1
        assert results[0]["status"] == "error"
        assert "exit code 3" in results[0]["message"]
        if failed_marker:
            assert lease.state.read("iteration.active", Participation) is not None
            assert not (lease.state.path / "unresolved").exists()
        else:
            assert (lease.state.path / "unresolved").is_file()
            assert lease.state.read("iteration.active", Participation) is None
    finally:
        lease.close(clean=True)
    assert inspect_writer(workspace).status == "unresolved"


def test_observer_failure_does_not_mask_original_process_exception():
    from core.runtime_control.observed_subprocess import (
        observe_process_lifecycle,
        supervise_process,
    )

    def observation(_lifecycle):
        raise OSError("observer failed")

    with (
        observe_process_lifecycle(observation),
        pytest.raises(subprocess.CalledProcessError) as error,
    ):
        supervise_process(
            [sys.executable, "-c", "raise SystemExit(7)"],
            env=dict(os.environ),
            preexec_fn=None,
            capture_stdout=True,
        )
    assert error.value.returncode == 7
