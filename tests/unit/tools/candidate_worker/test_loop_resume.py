"""Process-separated native loop checkpoints; providers/training remain offline doubles."""

import importlib
import json
import os
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from tools.candidate_operations import (
    CandidateLoopResumeOperation,
    CandidateLoopResumeRequest,
    CandidateOperation,
    OperationStoreConfig,
    read_operation,
    read_operation_tokens,
    request_loop_pause,
    review_loop_resume,
    submit_operation,
)
from tools.candidate_operations.models import OperationFailure
from tools.candidate_worker.layout import interpretation_input_path, tuning_input_path
from tools.workspace_sandbox.runner import ExecutionResult, ObservedExecutionResult

from .test_finite_loop import loop_request
from .test_finite_loop import loop_tuner as loop_tuner
from .test_interpretation import interpretation_provider as interpretation_provider
from .test_native import native_runner as native_runner
from .test_training import training_runner as training_runner


@pytest.fixture
def process_segments(monkeypatch):
    """Fork retains only SDK doubles; each native segment runs in a separate process."""
    from core.runtime_control.process_group import terminate_observed_group
    from tools.candidate_operations.child import execute as operation
    from tools.candidate_worker.child import execute
    from tools.candidate_worker.loop_resume import execute_continuation

    operations = []

    def observed(profile, argv):
        pid = os.fork()
        if pid == 0:
            try:
                os.setsid()
                path = Path(argv[-1])
                (execute_continuation if path.name == "continuation.json" else execute)(path)
            except BaseException:
                import traceback

                traceback.print_exc()
                os._exit(1)
            os._exit(0)
        _, status = os.waitpid(pid, 0)
        code = os.waitstatus_to_exitcode(status)
        cleanup = terminate_observed_group(
            pid, retain_unknown=True, grace_seconds=1.0, poll_seconds=0.05
        )
        return ObservedExecutionResult(
            execution=ExecutionResult(
                status="completed" if code == 0 else "failed", returncode=code, elapsed_seconds=0
            ),
            direct_child_reaped=True,
            cleanup=cleanup,
        )

    def spawn(path, env):
        pid = os.fork()
        if pid == 0:
            # Production Popen(close_fds=True) does not inherit the admission lock.
            for descriptor in Path("/proc/self/fd").iterdir():
                try:
                    if os.readlink(descriptor).endswith("/admission.lock"):
                        os.close(int(descriptor.name))
                except FileNotFoundError:
                    pass
            try:
                code = operation(path)
            except BaseException:
                import traceback

                traceback.print_exc()
                os._exit(1)
            os._exit(code)
        operations.append(pid)

    monkeypatch.setattr(
        importlib.import_module("tools.candidate_worker.launch"), "run_observed", observed
    )
    monkeypatch.setattr(
        importlib.import_module("tools.candidate_worker.loop_resume"), "run_observed", observed
    )
    monkeypatch.setattr(
        importlib.import_module("tools.candidate_operations.submit"), "spawn", spawn
    )

    def wait():
        pid = operations.pop(0)
        _, status = os.waitpid(pid, 0)
        assert os.waitstatus_to_exitcode(status) == 0

    yield wait
    for pid in operations:
        os.waitpid(pid, 0)


def test_completed_pause_resumes_actual_body_in_new_process(
    prepared, loop_tuner, interpretation_provider, process_segments, monkeypatch, tmp_path
):
    from agent.schemas.hyperparam_tuning import HyperparamTuningInput
    from agent.schemas.interpretation import InterpretationInput
    from tools.candidate_worker import training

    # Three bodies: body 3 proves the root Pause marker is not consumed by the successor.
    # The narrow per-model interpretation double degrades body 3 identically in both runs;
    # this witness claims only its dispatch, and compares body-2 inputs below.
    request = loop_request(prepared, final_iteration=3)
    config = OperationStoreConfig(
        state_root=str(tmp_path / "operations"),
        preparation_roots=(str(tmp_path),),
        candidate_roots=(str(tmp_path),),
    )
    first_id = uuid4()
    real_tune = training.HyperparamTuningAgent.run
    # Forked segments inherit this map: native iteration slot -> operation to Pause.
    pause_during = {"iteration_001": first_id}

    # The tuner double intentionally has no provider context; iteration comes from managed slot.
    def pause_at_first(self, value):
        output = real_tune(self, value)
        for slot, operation_id in pause_during.items():
            if slot in value.storage.local.workspace:
                request_loop_pause(config, operation_id)
        return output

    monkeypatch.setattr(training.HyperparamTuningAgent, "run", pause_at_first)
    submit_operation(
        config,
        CandidateOperation(request_id=first_id, request=request),
        launch_environment={"OPENAI_API_KEY": "offline-stub"},
    )
    process_segments()
    first = read_operation(config, first_id)
    assert first.receipt is not None and first.receipt.status == "paused", first
    assert first.receipt.loop_trace.attempted_iterations == 1
    workspace = Path(first.receipt.workspace)
    root = workspace / "candidate_run"
    assert not (root / "iteration_002").exists()
    # Every predecessor control, body and capture; Resume may only add successor.json.
    paused_tree = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    # A receipt alone is insufficient: each refusal occurs before claiming a successor.
    supervision_path = root / "supervision.json"
    supervision = supervision_path.read_bytes()
    uncertain = json.loads(supervision)
    uncertain["cleanup"]["final"] = {"status": "unknown", "error": "fixture"}
    supervision_path.write_text(json.dumps(uncertain))
    with pytest.raises(OperationFailure, match="clean supervision"):
        review_loop_resume(config, first_id)
    supervision_path.unlink()
    with pytest.raises(OperationFailure, match="clean supervision"):
        review_loop_resume(config, first_id)
    supervision_path.write_bytes(supervision)
    read_module = importlib.import_module("tools.candidate_operations.read")
    from tools.candidate_operations.models import ProcessObservation

    with monkeypatch.context() as patch:
        patch.setattr(
            read_module, "observe", lambda _: ProcessObservation(status="alive", reason="fixture")
        )
        with pytest.raises(OperationFailure, match="exited"):
            review_loop_resume(config, first_id)
    # A partial next slot already invalidates the paused readback, before admission.
    (root / "iteration_002").mkdir()
    with pytest.raises(OperationFailure, match="verified paused"):
        review_loop_resume(config, first_id)
    (root / "iteration_002").rmdir()
    stop = {"run_id": first.receipt.run_id, "declaration_digest": first.receipt.declaration_digest}
    (root / "stop.json").write_text(json.dumps(stop))
    with pytest.raises(OperationFailure, match="terminal"):
        review_loop_resume(config, first_id)
    (root / "stop.json").unlink()
    review = review_loop_resume(config, first_id)
    next_id = uuid4()
    submission = CandidateLoopResumeOperation(
        request_id=next_id,
        request=CandidateLoopResumeRequest(
            predecessor_operation_id=first_id, expected_receipt_digest=review.receipt_digest
        ),
    )
    # Final iteration wins over a Pause requested on the successor during body 3.
    pause_during = {"iteration_003": next_id}
    handle = submit_operation(
        config, submission, launch_environment={"OPENAI_API_KEY": "offline-stub"}
    )
    assert submit_operation(config, submission, launch_environment={}).observation == "existing"
    process_segments()
    # After the successor exits, a competing ID meets the reservation, not store occupancy.
    with pytest.raises(OperationFailure, match="already has a successor"):
        submit_operation(
            config,
            submission.model_copy(update={"request_id": uuid4()}),
            launch_environment={"OPENAI_API_KEY": "offline-stub"},
        )
    second = read_operation(config, handle.operation_id)
    assert second.receipt is not None and second.receipt.status == "completed", second
    assert second.receipt.run_id == first.receipt.run_id
    # Old root Pause did not stop body 3; the successor's own Pause lost to the final body.
    assert second.receipt.loop_trace.attempted_iterations == 3
    assert second.receipt.loop_trace.segment_id == next_id
    assert (root / f"continuations/{next_id}/pause.json").is_file()
    assert {path: path.read_bytes() for path in paused_tree} == paused_tree
    # Segments share the root run ledger (run-total), never a per-segment reducer.
    segment_tokens, root_tokens = (
        read_operation_tokens(config, operation_id).model_dump(exclude={"observed_at"})
        for operation_id in (next_id, first_id)
    )
    assert segment_tokens["run_id"] == first.receipt.run_id
    assert segment_tokens == root_tokens
    historical = read_operation(config, first_id)
    assert historical.receipt.status == "paused"
    assert historical.successor_operation_id == next_id
    interpreted = InterpretationInput.model_validate_json(
        interpretation_input_path(workspace, "interpret", iteration=2).read_bytes()
    )
    tuned = HyperparamTuningInput.model_validate_json(
        tuning_input_path(workspace, "train", iteration=2).read_bytes()
    )
    assert not interpreted.cold_start and interpreted.iteration == 2
    assert interpreted.human_advice == "Preserve the declared feature interface."
    assert interpreted.summaries[0].best_denoising_score == 0.75
    assert tuned.current_run_best_formal_score == 0.75
    assert tuned.human_advice == "Preserve both logits."
    with pytest.raises(OperationFailure):
        review_loop_resume(config, next_id)

    # The uninterrupted comparison uses a distinct workspace and fresh process state.
    from tools.candidate_worker.models import CandidateRunRequest

    from .conftest import refresh

    original_project = Path(request.preview.project_root)
    baseline_project = tmp_path / "baseline-project"
    baseline_workspace = tmp_path / "baseline-workspace"
    shutil.copytree(original_project, baseline_project)

    def rebase_paths(value):
        return value.replace(str(original_project), str(baseline_project)).replace(
            str(workspace), str(baseline_workspace)
        )

    for source in baseline_project.glob("*.json"):
        source.write_text(rebase_paths(source.read_text()))
    baseline_request = refresh(
        CandidateRunRequest.model_validate_json(rebase_paths(request.model_dump_json()))
    )
    baseline_id = uuid4()
    monkeypatch.setattr(training.HyperparamTuningAgent, "run", real_tune)
    submit_operation(
        config,
        CandidateOperation(request_id=baseline_id, request=baseline_request),
        launch_environment={"OPENAI_API_KEY": "offline-stub"},
    )
    process_segments()
    baseline_receipt = read_operation(config, baseline_id).receipt
    assert baseline_receipt.status == "completed"
    baseline_interpretation = InterpretationInput.model_validate_json(
        interpretation_input_path(baseline_workspace, "interpret", iteration=2).read_bytes()
    )
    baseline_tuning = HyperparamTuningInput.model_validate_json(
        tuning_input_path(baseline_workspace, "train", iteration=2).read_bytes()
    )
    # Separate runs own distinct storage slots and minted candidate IDs.
    run_identity = {"storage": True, "previous_proposal": {"candidate_id"}}
    assert interpreted.model_dump(exclude=run_identity) == baseline_interpretation.model_dump(
        exclude=run_identity
    )
    assert (
        tuned.current_run_best_formal_score,
        tuned.human_advice,
    ) == (
        baseline_tuning.current_run_best_formal_score,
        baseline_tuning.human_advice,
    )


def test_paused_continuation_resumes_again_across_two_hops(
    prepared, loop_tuner, interpretation_provider, process_segments, monkeypatch, tmp_path
):
    from tools.candidate_worker import training
    from tools.candidate_worker.loop_models import LoopContinuation
    from tools.candidate_worker.loop_resume import verify_segment
    from tools.candidate_worker.models import CandidateRunReceipt

    request = loop_request(prepared, final_iteration=4)
    config = OperationStoreConfig(
        state_root=str(tmp_path / "operations"),
        preparation_roots=(str(tmp_path),),
        candidate_roots=(str(tmp_path),),
    )
    env = {"OPENAI_API_KEY": "offline-stub"}
    root_id, first_id, second_id = uuid4(), uuid4(), uuid4()
    real_tune = training.HyperparamTuningAgent.run
    # Forked segments inherit this map: body 1 pauses the root, body 2 pauses hop A.
    pause_during = {"iteration_001": root_id, "iteration_002": first_id}

    def pause_by_slot(self, value):
        output = real_tune(self, value)
        for slot, operation_id in pause_during.items():
            if slot in value.storage.local.workspace:
                request_loop_pause(config, operation_id)
        return output

    def resume(predecessor_id, request_id):
        review = review_loop_resume(config, predecessor_id)
        submit_operation(
            config,
            CandidateLoopResumeOperation(
                request_id=request_id,
                request=CandidateLoopResumeRequest(
                    predecessor_operation_id=predecessor_id,
                    expected_receipt_digest=review.receipt_digest,
                ),
            ),
            launch_environment=env,
        )
        process_segments()
        return read_operation(config, request_id)

    monkeypatch.setattr(training.HyperparamTuningAgent, "run", pause_by_slot)
    submit_operation(
        config, CandidateOperation(request_id=root_id, request=request), launch_environment=env
    )
    process_segments()
    root = Path(read_operation(config, root_id).receipt.workspace) / "candidate_run"
    # An edited captured input refuses BEFORE reservation, so the one Resume stays unused.
    source = Path(request.files[0].path)
    original = source.read_bytes()
    source.write_bytes(original + b"\n")
    with pytest.raises(OperationFailure, match="captured loop inputs changed"):
        resume(root_id, first_id)
    source.write_bytes(original)
    assert not (root / "successor.json").exists()

    first = resume(root_id, first_id)
    assert first.receipt.status == "paused", first
    assert first.receipt.loop_trace.attempted_iterations == 2
    assert first.receipt.loop_trace.segment_id == first_id
    paused_tree = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}

    second = resume(first_id, second_id)
    assert second.receipt.status == "completed", second
    assert second.receipt.loop_trace.attempted_iterations == 4
    assert second.receipt.loop_trace.segment_id == second_id
    # Hop B is bound to A's own paused receipt, reserved beside A's own Pause marker.
    hop = root / f"continuations/{first_id}"
    assert (hop / "pause.json").is_file()
    binding = LoopContinuation.model_validate_json((hop / "successor.json").read_bytes())
    assert binding.operation_id == second_id
    assert binding.predecessor_segment == first_id
    assert binding.predecessor_receipt_digest == first.receipt_digest
    assert binding.completed_iterations == 2
    # Ancestry B -> A -> root verifies, and B resumed after two completed bodies.
    initial = CandidateRunReceipt.model_validate_json((root / "launch.json").read_bytes())
    assert verify_segment(initial, second.receipt) == 2
    assert {path: path.read_bytes() for path in paused_tree} == paused_tree
    historical = read_operation(config, root_id)
    assert historical.receipt.status == "paused"
    assert historical.receipt.loop_trace.segment_id is None
    assert historical.successor_operation_id == first_id
    assert read_operation(config, first_id).successor_operation_id == second_id
    tokens = [
        read_operation_tokens(config, operation_id).model_dump(exclude={"observed_at"})
        for operation_id in (root_id, first_id, second_id)
    ]
    assert tokens[1] == tokens[0] and tokens[2] == tokens[0]


@pytest.mark.parametrize("fault", ["native_lease", "supervisor"])
def test_uncertain_cleanup_never_publishes_resumable_pause(
    prepared, loop_tuner, monkeypatch, fault
):
    from contextlib import contextmanager

    import core.native_writer
    from core.runtime_control.process_group import GroupObservation
    from tools.candidate_worker import launch_candidate, training
    from tools.candidate_worker.loop_models import LoopPause
    from tools.candidate_worker.models import CandidateRunReceipt

    request = loop_request(prepared)
    control = Path(request.preview.document.definition.task.workspace) / "candidate_run"
    run = training.HyperparamTuningAgent.run

    def pause(self, value):
        output = run(self, value)
        initial = CandidateRunReceipt.model_validate_json((control / "launch.json").read_bytes())
        (control / "pause.json").write_text(
            LoopPause(
                run_id=initial.run_id, declaration_digest=initial.declaration_digest
            ).model_dump_json()
        )
        return output

    monkeypatch.setattr(training.HyperparamTuningAgent, "run", pause)
    if fault == "native_lease":
        owner = core.native_writer.iteration_owner

        @contextmanager
        def uncertain(workspace):
            with owner(workspace) as lease:
                lease.mark_unresolved("fixture")
                yield lease

        monkeypatch.setattr(core.native_writer, "iteration_owner", uncertain)
    else:
        module = importlib.import_module("tools.candidate_worker.launch")
        observed = module.run_observed

        def uncertain_supervisor(profile, argv):
            result = observed(profile, argv)
            return result.model_copy(
                update={
                    "cleanup": result.cleanup.model_copy(
                        update={"final": GroupObservation(status="unknown", error="fixture")}
                    )
                }
            )

        monkeypatch.setattr(module, "run_observed", uncertain_supervisor)
    receipt = launch_candidate(request)
    assert receipt.status == "failed"
    assert (control / "body.json").is_file()
    assert not (control / "iteration_002").exists()
    assert "cleanup" in receipt.error or "clean supervision" in receipt.error
