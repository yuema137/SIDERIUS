"""Offline training effects in the existing detached operation and sandbox harness.

The real operation child, candidate worker, admission, staging and output readers
run unchanged. Only provider, hardware/measurement and tuner effects use the
existing native-training fixture. No production injection surface is added.
"""

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURE = Path(__file__).resolve()
# Test scaffolding is outside the editable src package; use this exact checkout.
if __name__ == "__main__":
    sys.path.insert(0, str(FIXTURE.parents[2]))


def install_operation_fixture() -> None:
    """Change only the fixture server's operation subprocess entrypoint."""
    real_popen = subprocess.Popen

    def popen(argv, *args, **kwargs):
        if len(argv) >= 3 and argv[1:3] == ["-m", "tools.candidate_operations.child"]:
            argv = [argv[0], str(FIXTURE), "operation", *argv[3:]]
        return real_popen(argv, *args, **kwargs)

    subprocess.Popen = popen


def operation(path: Path) -> int:
    launch = importlib.import_module("tools.candidate_worker.launch")
    native_run = launch.run

    def run(profile, argv):
        return native_run(profile, [argv[0], str(FIXTURE), "worker", argv[-1]])

    launch.run = run
    from tools.candidate_operations.child import execute

    return execute(path)


def worker(path: Path) -> None:
    from core.generated_library import bind_generated_library_to_workspace

    bind_generated_library_to_workspace(str(path.parent.parent))
    from tests.unit.tools.candidate_worker.test_native import native_runner
    from tests.unit.tools.candidate_worker.test_training import training_runner
    from tools.candidate_worker.child import execute

    with pytest.MonkeyPatch.context() as patch:
        seen = training_runner.__wrapped__(native_runner.__wrapped__(patch), patch)
        receipt = execute(path)
        assert receipt.status == "completed", receipt.error
        observed = {
            name: value.model_dump(mode="json")
            for name, value in seen
            if name in {"proposal", "tuner"}
        }
        (path.parent / "offline_training_observed.json").write_text(json.dumps(observed))


def code_equivalent(root: Path) -> None:
    """Prepare/launch the same saved declaration through the public code services."""
    import hashlib
    import time
    from uuid import uuid4

    from tools.candidate_console.models import ConsoleConfig
    from tools.candidate_console.reusable_candidate import ReusableCandidate
    from tools.candidate_console.reusable_models import ReusableCaptureChoice, ReusableCaptureLaunch
    from tools.candidate_console.reusable_preparation import (
        NewRunIntent,
        NewRunSelection,
        ReusablePreparation,
    )
    from tools.candidate_console.service import CandidateConsole
    from tools.candidate_operations import read_operation
    from tools.candidate_operations.read import releasable

    install_operation_fixture()
    config = ConsoleConfig.model_validate_json((root / "console.json").read_bytes())
    console = CandidateConsole(config)
    prepare = ReusablePreparation(console)
    selection = NewRunSelection(
        task_id="synthetic",
        run_name="code_equivalent",
        run_id=uuid4(),
        preparation_operation_id=uuid4(),
        expected_source_sha256=hashlib.sha256((root / "workflow.py").read_bytes()).hexdigest(),
    )
    review = prepare.review("capture", selection)

    def wait(handle):
        deadline = time.monotonic() + 90
        while not releasable(config.operation_store, handle.operation_id):
            if time.monotonic() > deadline:
                raise TimeoutError("offline native operation did not exit")
            time.sleep(0.1)
        return read_operation(config.operation_store, handle.operation_id)

    prepared = wait(
        prepare.prepare(
            "capture", NewRunIntent(selection=selection, expectation=review.expectation)
        )
    )
    assert prepared.receipt is not None and prepared.receipt.status == "prepared", prepared
    candidate = ReusableCandidate(console)
    capture = candidate.select(
        "capture", ReusableCaptureChoice(task_id="synthetic", run_id=selection.run_id)
    )
    reviewed = candidate.review("capture", capture)
    status = wait(
        candidate.launch(
            "capture",
            ReusableCaptureLaunch(
                selection=capture,
                expected_request_digest=reviewed.request_digest,
                candidate_operation_id=uuid4(),
            ),
        )
    )
    assert status.receipt is not None and status.receipt.status == "completed", status
    observations = [
        json.loads(path.read_bytes())
        for path in (root / "runs").glob("*/workspace/candidate_run/offline_training_observed.json")
    ]
    assert len(observations) == 2
    for stage in ("proposal", "tuner"):
        for name in (
            "sampling_seed",
            "trial_time_budget_minutes",
            "formal_time_budget_minutes",
            "trial_portion",
            "train_portion",
            "workflow_parameter_rules",
        ):
            assert observations[0][stage][name] == observations[1][stage][name], (stage, name)
    assert (
        observations[0]["tuner"]["train_base_seed"]
        == observations[1]["tuner"]["train_base_seed"]
        == 29
    )


if __name__ == "__main__":
    mode, filename = sys.argv[1:]
    if mode == "operation":
        raise SystemExit(operation(Path(filename)))
    path = Path(filename)
    with (path.parent / "worker.log").open("x") as log:
        os.dup2(log.fileno(), 1)
        os.dup2(log.fileno(), 2)
        worker(path)
