"""Process-separated native loop checkpoints; providers/training remain offline doubles."""

import importlib
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from core.runtime_control.process_group import GroupCleanup, GroupObservation
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

#: Names the offline fixtures bind in the test process that a real launcher would
#: provide some other way; every other inherited name is dropped like Popen(env=...).
FIXTURE_ENVIRONMENT = (
    "HOME",
    "TMPDIR",
    "SIDERIUS_GENERATED_LIBRARY_DIR",
    "SIDERIUS_CHAIN_WORKSPACE",
    "PYTHONPATH",
)


@pytest.fixture
def process_segments(monkeypatch):
    """Fork retains only SDK doubles; each native segment runs in a separate process."""
    from core.runtime_control.process_group import terminate_observed_group
    from tools.candidate_operations.child import execute as operation
    from tools.candidate_worker.child import execute
    from tools.candidate_worker.loop_resume import execute_continuation

    operations = []

    def observed(profile, argv, *, cancel_requested=None, **_supervision):
        from tools.workspace_sandbox.command import child_environment

        # The real sandbox owner: a declared name missing from the operation child's
        # environment (e.g. an unset placed device selector) refuses the launch.
        child_environment(profile, os.environ)
        # Like the runner, poll a supplied probe first: a fired probe ends the segment as
        # cancelled before any body runs. Without a recorded intent the probe is False.
        if cancel_requested is not None and cancel_requested():
            return ObservedExecutionResult(
                execution=ExecutionResult(status="cancelled", returncode=-15, elapsed_seconds=0),
                direct_child_reaped=True,
                cleanup=GroupCleanup(required=False, final=GroupObservation(status="absent")),
            )
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
            # Production Popen(close_fds=True) inherits neither the admission lock nor
            # the host ledger lock held across admission and spawn.
            for descriptor in Path("/proc/self/fd").iterdir():
                try:
                    if os.readlink(descriptor).endswith(("/admission.lock", "/ledger.lock")):
                        os.close(int(descriptor.name))
                except FileNotFoundError:
                    pass
            # Like Popen(env=..., start_new_session=True): the child's environment is
            # replaced by the spawn environment, plus only the names this test's
            # fixtures bind in place of a real launcher, and it leads its own session.
            os.setsid()
            fixture = {key: os.environ[key] for key in FIXTURE_ENVIRONMENT if key in os.environ}
            os.environ.clear()
            os.environ.update({**fixture, **env})
            try:
                code = operation(path)
            except BaseException:
                import traceback

                traceback.print_exc()
                os._exit(1)
            os._exit(code)
        operations.append(pid)
        # Like Popen: a host-ledger slot binds the unreaped child's identity.
        return SimpleNamespace(pid=pid)

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
    # Console projections resolve the root through the operations owner, never directories:
    # the resumed segment keeps the root's bound and shows every verified body so far.
    from types import SimpleNamespace

    from tools.candidate_console.graph_results import read_graph_results
    from tools.candidate_console.models import LoopStatusView
    from tools.candidate_console.service import loop_status

    assert loop_status(config, historical) == LoopStatusView(
        final_iteration=3, attempted_iterations=1
    )
    assert loop_status(config, second) == LoopStatusView(final_iteration=3, attempted_iterations=3)
    # M-1: requests are read from the worker's own durable markers, with the worker's
    # scoping: the root's Pause belongs to the root segment only; the successor's to it.
    from tools.candidate_operations import loop_control_requests

    assert loop_control_requests(config, first_id) == (False, True)
    assert loop_control_requests(config, next_id) == (False, True)
    (root / f"continuations/{next_id}/pause.json").rename(tmp_path / "successor-pause.json")
    assert loop_control_requests(config, next_id) == (False, False), "root Pause leaked"
    (tmp_path / "successor-pause.json").rename(root / f"continuations/{next_id}/pause.json")
    (root / "stop.json").write_text(json.dumps(stop))
    assert loop_control_requests(config, next_id) == (True, True), "Stop is run-scoped"
    assert loop_status(config, second, requests=True).stop_requested
    (root / "stop.json").rename(tmp_path / "stop.json.aside")
    # A malformed or foreign marker is not a recorded request, and never breaks the status read.
    (root / "stop.json").write_text("{not json")
    assert loop_control_requests(config, next_id) == (False, True), "malformed Stop"
    (root / "stop.json").write_text(json.dumps({**stop, "run_id": "another-run"}))
    assert loop_control_requests(config, next_id) == (False, True), "foreign Stop"
    (root / "stop.json").rename(tmp_path / "stop.json.bad")
    console = SimpleNamespace(operation_store=config)
    paused_results = read_graph_results(console, first_id)
    resumed_results = read_graph_results(console, next_id)
    assert paused_results.available and resumed_results.available
    assert [body.iteration for body in paused_results.bodies] == [1]
    assert [body.iteration for body in resumed_results.bodies] == [1, 2, 3]
    # Body 1 is the same verified record whether read through the root or the segment.
    assert resumed_results.bodies[0] == paused_results.bodies[0]
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
    # Edit a test-owned input, never files[0] (the checkout's shared task manifest):
    # concurrent CI shards observe that file and fail "selected input changed" (#973).
    project = Path(request.preview.project_root)
    owned = (Path(item.path) for item in request.files)
    source = next((path for path in owned if path.is_relative_to(project)), None)
    assert source is not None, f"no captured input under the tmp project {project}"
    assert project.is_relative_to(tmp_path) and source.is_relative_to(tmp_path)
    original = source.read_bytes()
    source.write_bytes(original + b"\n")
    try:
        with pytest.raises(OperationFailure, match="captured loop inputs changed"):
            resume(root_id, first_id)
    finally:
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
    assert verify_segment(initial, second.receipt).resumed_at == 2
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
    # Issue #983 T7/M8: every segment continues the root's admitted seed, and a
    # resumed segment's bodies keep the global iteration (3-4, never 1-2 again).
    from agent.schemas.hyperparam_tuning import HyperparamTuningInput
    from core.seeding import SeedCoordinates

    seed = read_operation(config, root_id).run_seed
    assert seed is not None and seed.source == "generated"
    assert [read_operation(config, item).run_seed for item in (first_id, second_id)] == [seed] * 2
    assert (initial.run_seed, initial.run_seed_source) == (seed.value, seed.source)
    tuned = [
        HyperparamTuningInput.model_validate_json(
            tuning_input_path(Path(initial.workspace), "train", iteration=iteration).read_bytes()
        )
        for iteration in range(1, 5)
    ]
    assert [(value.run_seed, value.seed_coordinates) for value in tuned] == [
        (seed.value, SeedCoordinates(iteration=iteration, node_id="train"))
        for iteration in range(1, 5)
    ]


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


def test_no_improvement_window_spans_paused_segments(
    prepared, loop_tuner, interpretation_provider, process_segments, monkeypatch, tmp_path
):
    from tools.candidate_worker import training
    from tools.candidate_worker.loop_evidence import verify_loop
    from tools.candidate_worker.loop_stop import NoImprovementReason
    from tools.candidate_worker.models import CandidateRunReceipt
    from workflows.definition import NoImprovementStop

    # Every body scores 0.75: body 1 improves, bodies 2 and 3 tie (non-improving).
    request = loop_request(
        prepared, final_iteration=5, stop_conditions=(NoImprovementStop(completed_bodies=2),)
    )
    config = OperationStoreConfig(
        state_root=str(tmp_path / "operations"),
        preparation_roots=(str(tmp_path),),
        candidate_roots=(str(tmp_path),),
    )
    env = {"OPENAI_API_KEY": "offline-stub"}
    root_id, next_id = uuid4(), uuid4()
    real_tune = training.HyperparamTuningAgent.run

    def pause_at_second(self, value):
        output = real_tune(self, value)
        if "iteration_002" in value.storage.local.workspace:
            request_loop_pause(config, root_id)
        return output

    monkeypatch.setattr(training.HyperparamTuningAgent, "run", pause_at_second)
    submit_operation(
        config, CandidateOperation(request_id=root_id, request=request), launch_environment=env
    )
    process_segments()
    paused = read_operation(config, root_id).receipt
    assert paused.status == "paused" and paused.loop_trace.attempted_iterations == 2
    assert paused.loop_trace.stop_reason is None
    review = review_loop_resume(config, root_id)
    submit_operation(
        config,
        CandidateLoopResumeOperation(
            request_id=next_id,
            request=CandidateLoopResumeRequest(
                predecessor_operation_id=root_id, expected_receipt_digest=review.receipt_digest
            ),
        ),
        launch_environment=env,
    )
    process_segments()
    resumed = read_operation(config, next_id).receipt
    # A segment-local window would see one non-improving body at 3 and run body 4.
    assert resumed.status == "completed", resumed
    assert resumed.loop_trace.attempted_iterations == 3
    # Equal to the uninterrupted run's reason: the window and incumbent span segments.
    assert resumed.loop_trace.stop_reason == NoImprovementReason(
        condition_index=0,
        iteration=3,
        k=2,
        non_improving_bodies=2,
        last_improvement_iteration=1,
        incumbent=0.75,
    )
    root = Path(resumed.workspace) / "candidate_run"
    assert not (root / "iteration_004").exists()
    launched = CandidateRunReceipt.model_validate_json((root / "launch.json").read_bytes())
    assert len(verify_loop(request, launched, resumed)) == 3
    # A condition-completed run is not a resumable checkpoint.
    with pytest.raises(OperationFailure):
        review_loop_resume(config, next_id)


def test_resumed_segment_reports_run_total_tokens_from_both_segments(
    prepared,
    loop_tuner,
    native_runner,
    interpretation_provider,
    process_segments,
    monkeypatch,
    tmp_path,
):
    """Gap G4: a successor's reported usage is the root run's whole ledger.

    Every provider double appends one row with fixed counts to the ledger its
    production run context binds, and one line to a test-owned witness. Fails if
    the successor token read is segment-local (body 2 only, or the empty
    continuation directory), if a segment binds rows to another run identity
    (rows become invalid), or if the operations read path stops redirecting a
    ``candidate_loop_resume`` record to its root.
    """
    from tools.candidate_worker import training

    witness = tmp_path / "reported_calls.log"

    def report(bridge):
        context = bridge.context
        assert context is not None, "provider called without a bound run context"
        row = {
            "ts": "2026-10-27T10:00:00Z",
            "run_id": context["run_id"],
            "run_name": context["run_name"],
            "label": "response",
            "provider": "openai",
            "model": "fixture-model",
            "served_model": None,
            "tokens": {"prompt": 11, "completion": 2, "total": 13},
            "chars": {"system": 0, "user": 0, "total": 0},
        }
        with (Path(context["workspace"]) / "token_usage.jsonl").open("a") as ledger:
            ledger.write(json.dumps(row) + "\n")
        with witness.open("a") as stream:
            stream.write("call\n")

    def reporting(method):
        def call(self, *args, **kwargs):
            result = method(self, *args, **kwargs)
            report(self)
            return result

        return call

    for owner in (native_runner, interpretation_provider):
        for name in ("generate", "generate_text"):
            if name in vars(owner):  # wrap each provider method exactly once
                monkeypatch.setattr(owner, name, reporting(vars(owner)[name]))

    request = loop_request(prepared, final_iteration=2)
    config = OperationStoreConfig(
        state_root=str(tmp_path / "operations"),
        preparation_roots=(str(tmp_path),),
        candidate_roots=(str(tmp_path),),
    )
    env = {"OPENAI_API_KEY": "offline-stub"}
    first_id, next_id = uuid4(), uuid4()
    real_tune = training.HyperparamTuningAgent.run

    def pause_after_body_one(self, value):
        output = real_tune(self, value)
        if "iteration_001" in value.storage.local.workspace:
            request_loop_pause(config, first_id)
        return output

    monkeypatch.setattr(training.HyperparamTuningAgent, "run", pause_after_body_one)
    submit_operation(
        config, CandidateOperation(request_id=first_id, request=request), launch_environment=env
    )
    process_segments()
    first = read_operation(config, first_id)
    assert first.receipt is not None and first.receipt.status == "paused", first
    first_segment_calls = len(witness.read_text().splitlines())
    assert first_segment_calls > 0

    review = review_loop_resume(config, first_id)
    submit_operation(
        config,
        CandidateLoopResumeOperation(
            request_id=next_id,
            request=CandidateLoopResumeRequest(
                predecessor_operation_id=first_id, expected_receipt_digest=review.receipt_digest
            ),
        ),
        launch_environment=env,
    )
    process_segments()
    second = read_operation(config, next_id)
    assert second.receipt is not None and second.receipt.status == "completed", second
    all_calls = len(witness.read_text().splitlines())
    assert all_calls > first_segment_calls  # the successor segment reported usage too

    segment = read_operation_tokens(config, next_id)
    assert segment.availability == "available"
    assert segment.reason == "reported_responses"
    assert segment.run_id == first.receipt.run_id
    assert segment.quality.invalid_rows == 0 and not segment.quality.partial
    assert [
        (
            group.provider,
            group.requested_model,
            group.response_rows,
            group.reported_input_tokens,
            group.reported_output_tokens,
            group.reported_total_tokens,
        )
        for group in segment.groups
    ] == [("openai", "fixture-model", all_calls, 11 * all_calls, 2 * all_calls, 13 * all_calls)]
    root = read_operation_tokens(config, first_id)
    assert segment.model_dump(exclude={"observed_at"}) == root.model_dump(exclude={"observed_at"})


def test_cancel_reaches_resumed_segment_and_reads_back_trace_less(
    prepared, loop_tuner, interpretation_provider, process_segments, monkeypatch, tmp_path
):
    """Fails if the operation child stops passing its cancel probe to a resumed segment's
    supervisor (the resumed body would run to completion), or if a trace-less ``cancelled``
    continuation receipt cannot be read back through ``read_segment`` as a verified,
    unresumable terminal."""
    from tools.candidate_operations import child
    from tools.candidate_operations.cancel import CANCEL_FILE
    from tools.candidate_operations.files import publish
    from tools.candidate_operations.models import CancelRequest
    from tools.candidate_operations.store import now, operation_path
    from tools.candidate_worker import training

    request = loop_request(prepared, final_iteration=2)
    config = OperationStoreConfig(
        state_root=str(tmp_path / "operations"),
        preparation_roots=(str(tmp_path),),
        candidate_roots=(str(tmp_path),),
    )
    env = {"OPENAI_API_KEY": "offline-stub"}
    first_id, next_id = uuid4(), uuid4()
    real_tune = training.HyperparamTuningAgent.run

    def pause_after_body_one(self, value):
        output = real_tune(self, value)
        if "iteration_001" in value.storage.local.workspace:
            request_loop_pause(config, first_id)
        return output

    monkeypatch.setattr(training.HyperparamTuningAgent, "run", pause_after_body_one)
    # Forked operation children inherit this: only the resumed segment's probe fires.
    real_probe = child.cancel_probe
    monkeypatch.setattr(
        child,
        "cancel_probe",
        lambda path, record: (
            (lambda: True) if record.submission.request_id == next_id else real_probe(path, record)
        ),
    )
    submit_operation(
        config, CandidateOperation(request_id=first_id, request=request), launch_environment=env
    )
    process_segments()
    review = review_loop_resume(config, first_id)
    submit_operation(
        config,
        CandidateLoopResumeOperation(
            request_id=next_id,
            request=CandidateLoopResumeRequest(
                predecessor_operation_id=first_id, expected_receipt_digest=review.receipt_digest
            ),
        ),
        launch_environment=env,
    )
    process_segments()
    unvouched = read_operation(config, next_id)
    assert (unvouched.state, unvouched.reason) == ("unknown", "integrity_failure"), unvouched
    publish(
        operation_path(config, next_id) / CANCEL_FILE,
        CancelRequest(
            operation_id=next_id, request_digest=unvouched.request_digest, requested_at=now()
        ),
    )
    second = read_operation(config, next_id)
    assert second.state == "completed" and second.cancel_requested, second
    assert second.receipt is not None and second.receipt.status == "cancelled"
    assert second.receipt.loop_trace is None and second.receipt_digest
    workspace = Path(second.receipt.workspace)
    assert not (workspace / "candidate_run" / "iteration_002").exists()
    assert read_operation(config, first_id).successor_operation_id == next_id
    with pytest.raises(OperationFailure):
        review_loop_resume(config, next_id)


def test_resumed_segment_bounds_validator_pytest_by_its_own_worker_budget(
    prepared, loop_tuner, interpretation_provider, process_segments, monkeypatch, tmp_path
):
    """Fails if loop.py or the continuation entry drops ``budget=`` (issue #984)."""
    from tools.candidate_worker import training

    validator = importlib.import_module("nodes.ml_code_validator_agent.ml_code_validator_agent")
    record = tmp_path / "pytest_limits.jsonl"

    # Forked segments inherit this double; a file carries their observations back.
    def launched(test_file_path, env, *, limit=None):
        with record.open("a") as stream:
            stream.write(
                json.dumps(
                    {
                        "path": test_file_path,
                        "limit": None if limit is None else limit.model_dump(),
                    }
                )
                + "\n"
            )
        return True, "1 passed"

    monkeypatch.setattr(validator, "run_generated_pytest", launched)
    request = loop_request(prepared, final_iteration=2)
    config = OperationStoreConfig(
        state_root=str(tmp_path / "operations"),
        preparation_roots=(str(tmp_path),),
        candidate_roots=(str(tmp_path),),
    )
    first_id = uuid4()
    real_tune = training.HyperparamTuningAgent.run

    def pause_after_first_body(self, value):
        output = real_tune(self, value)
        if "iteration_001" in value.storage.local.workspace:
            request_loop_pause(config, first_id)
        return output

    monkeypatch.setattr(training.HyperparamTuningAgent, "run", pause_after_first_body)
    submit_operation(
        config,
        CandidateOperation(request_id=first_id, request=request),
        launch_environment={"OPENAI_API_KEY": "offline-stub"},
    )
    process_segments()
    first = read_operation(config, first_id)
    assert first.receipt is not None and first.receipt.status == "paused", first
    review = review_loop_resume(config, first_id)
    next_id = uuid4()
    submit_operation(
        config,
        CandidateLoopResumeOperation(
            request_id=next_id,
            request=CandidateLoopResumeRequest(
                predecessor_operation_id=first_id, expected_receipt_digest=review.receipt_digest
            ),
        ),
        launch_environment={"OPENAI_API_KEY": "offline-stub"},
    )
    process_segments()
    second = read_operation(config, next_id)
    assert second.receipt is not None and second.receipt.status == "completed", second
    rows = [json.loads(line) for line in record.read_text().splitlines()]
    resumed = [row for row in rows if "iteration_002" in row["path"]]
    assert resumed and len(resumed) < len(rows)
    assert all(
        row["limit"] is not None
        and row["limit"]["source"] == "worker_budget"
        and 0 < row["limit"]["seconds"] <= request.timeout_seconds
        for row in rows
    )


@pytest.mark.parametrize("queued", [False, True])
def test_budgeted_resume_reaches_its_segment_placed_or_queued(
    prepared,
    loop_tuner,
    interpretation_provider,
    process_segments,
    monkeypatch,
    tmp_path,
    queued,
):
    """B3-5b: a host-ledger Resume reserves with its root's declaration and runs placed.

    The launch environment carries no ``CUDA_VISIBLE_DEVICES``: placed, the slot
    overlay supplies it; queued, admission must defer the name (otherwise the
    Resume is refused ``credentials``) and the waiting child sets it once placed.
    Either way the segment's supervisor must receive ``on_sandbox_spawn``, or the
    placed segment never publishes ``sandbox.json`` and its release evidence is
    missing.
    """
    import subprocess

    from core.runtime_control.pair_admission import ResolvedGpuCeiling
    from core.runtime_control.scheduling import (
        GpuHardwareClass,
        GpuSlot,
        HostBudget,
        plan_dispatch,
    )
    from tools.candidate_operations.host_ledger import (
        HostReservation,
        HostScheduling,
        locked_ledger,
        read_state,
        write_state,
    )
    from tools.candidate_operations.models import OperationResources
    from tools.candidate_operations.process import identity_of
    from tools.candidate_operations.store import operation_path
    from tools.candidate_worker import loop_resume as worker_loop_resume
    from tools.candidate_worker import training

    monkeypatch.setattr("tools.candidate_operations.host_queue.QUEUE_POLL_SECONDS", 0.05)
    slot = "GPU-aaaa"
    budget = HostBudget(
        gpus=(
            GpuSlot(
                uuid=slot,
                hardware_class=GpuHardwareClass(
                    device_name="NVIDIA H100",
                    total_memory_bytes=80 * 1024**3,
                    compute_capability=(9, 0),
                ),
                ceiling=ResolvedGpuCeiling(
                    operator_ceiling_gib=4.0,
                    operator_source="caller",
                    host_quota_gib=None,
                    measured_capacity_gib=80.0,
                ),
            ),
        ),
        host_memory_gib=64.0,
        cpu_slots=16,
        max_concurrent_units=4,
        source="file",
    )
    ledger = tmp_path / "ledger"
    ledger.mkdir(mode=0o700)
    host = HostScheduling(ledger_root=str(ledger), budget=budget)
    request = loop_request(prepared, final_iteration=2)
    request = request.model_copy(
        update={"environment_names": (*request.environment_names, "CUDA_VISIBLE_DEVICES")}
    )
    config = OperationStoreConfig(
        state_root=str(tmp_path / "operations"),
        preparation_roots=(str(tmp_path),),
        candidate_roots=(str(tmp_path),),
    )
    env = {"OPENAI_API_KEY": "offline-stub"}
    first_id, next_id = uuid4(), uuid4()
    real_tune = training.HyperparamTuningAgent.run

    def pause_after_body_one(self, value):
        output = real_tune(self, value)
        if "iteration_001" in value.storage.local.workspace:
            request_loop_pause(config, first_id)
        return output

    monkeypatch.setattr(training.HyperparamTuningAgent, "run", pause_after_body_one)
    supervised = worker_loop_resume.run_observed

    def spy(profile, argv, **supervision):
        # Forked operation child: report the sandbox through whatever hook arrived.
        if supervision.get("on_spawn") is not None:
            supervision["on_spawn"](os.getpid())
        return supervised(profile, argv, **supervision)

    monkeypatch.setattr(worker_loop_resume, "run_observed", spy)
    resources = OperationResources(
        gpu_count=1,
        vram_gib=3.0,
        vram_source="configured_cap",
        host_memory_gib=4.0,
        cpu_slots=1,
        time_budgeted=False,
    )
    submit_operation(
        config,
        CandidateOperation(request_id=first_id, request=request, resources=resources),
        launch_environment=env,
        host=host,
    )
    process_segments()
    review = review_loop_resume(config, first_id)
    holder = None
    if queued:
        holder = subprocess.Popen(["sleep", "60"], start_new_session=True)
        owner = SimpleNamespace(
            submission=SimpleNamespace(request_id=uuid4()), request_digest="0" * 64
        )
        reserved = resources.request(
            unit_id=str(owner.submission.request_id), dispatch_ordinal=0, wall_seconds=60.0
        )
        with locked_ledger(str(ledger)) as root:
            state = read_state(root)
            placed = plan_dispatch(
                (reserved.model_copy(update={"dispatch_ordinal": state.next_ordinal}),),
                (),
                budget,
                on_refusal="continue",
            ).placed[0]
            write_state(
                root,
                state.model_copy(update={"next_ordinal": state.next_ordinal + 1}).replacing(
                    (
                        HostReservation(
                            operation_id=owner.submission.request_id,
                            request_digest=owner.request_digest,
                            state_root=str(tmp_path / "elsewhere"),
                            placement=placed,
                            process=identity_of(owner, holder.pid),
                        ),
                    )
                ),
            )
    handle = submit_operation(
        config,
        CandidateLoopResumeOperation(
            request_id=next_id,
            request=CandidateLoopResumeRequest(
                predecessor_operation_id=first_id, expected_receipt_digest=review.receipt_digest
            ),
        ),
        launch_environment=env,
        host=host,
    )
    assert handle.observation == ("queued" if queued else "starting")
    if holder is not None:
        import time

        deadline = time.monotonic() + 30
        while read_operation(config, next_id).process.reason == "missing_identity":
            assert time.monotonic() < deadline, "waiting child never published itself"
            time.sleep(0.05)
        assert read_operation(config, next_id).state == "queued"
        holder.kill()
        holder.wait()
    process_segments()
    path = operation_path(config, next_id)
    assert json.loads((path / "placement.json").read_text())["gpu_uuid"] == slot
    assert (path / "sandbox.json").exists(), "on_sandbox_spawn never reached the segment"
    resumed = read_operation(config, next_id)
    assert resumed.receipt is not None and resumed.receipt.status == "completed", resumed


def test_condition_input_pause_resumes_without_pause_marker_and_refuses_forgery(
    prepared, loop_tuner, interpretation_provider, process_segments, tmp_path
):
    """A ``request_input`` pause is a verified checkpoint without ``pause.json``.

    Fails if readback still demands an operator Pause marker for a condition pause (the
    successor's ``verify_loop`` raises), if a resumed condition re-fires at the very next
    boundary instead of counting from its anchor, or if a forged or edited input request
    on the paused receipt is accepted.
    """
    from tools.candidate_worker.loop_evidence import verify_loop
    from tools.candidate_worker.models import CandidateRunReceipt
    from workflows.definition import NoImprovementStop

    # Every body scores 0.75: body 1 improves, bodies 2 and 3 tie, so k=2 asks after 3.
    request = loop_request(
        prepared,
        final_iteration=5,
        stop_conditions=(NoImprovementStop(completed_bodies=2, on_met="request_input"),),
    )
    config = OperationStoreConfig(
        state_root=str(tmp_path / "operations"),
        preparation_roots=(str(tmp_path),),
        candidate_roots=(str(tmp_path),),
    )
    env = {"OPENAI_API_KEY": "offline-stub"}
    root_id, next_id = uuid4(), uuid4()
    submit_operation(
        config, CandidateOperation(request_id=root_id, request=request), launch_environment=env
    )
    process_segments()
    paused = read_operation(config, root_id).receipt
    assert paused.status == "paused", paused
    assert paused.loop_trace.attempted_iterations == 3
    assert paused.loop_trace.input_request.reason.iteration == 3
    root = Path(paused.workspace) / "candidate_run"
    assert not (root / "pause.json").exists()
    launched = CandidateRunReceipt.model_validate_json((root / "launch.json").read_bytes())
    # Forged pause: dropping or editing the recorded request disagrees with the replay.
    request_value = paused.loop_trace.input_request
    edited = request_value.model_copy(
        update={"summary": request_value.summary.model_copy(update={"incumbent": 0.5})}
    )
    for forged in (None, edited):
        trace = paused.loop_trace.model_copy(update={"input_request": forged})
        with pytest.raises(ValueError, match="disagrees"):
            verify_loop(request, launched, paused.model_copy(update={"loop_trace": trace}))

    review = review_loop_resume(config, root_id)
    submit_operation(
        config,
        CandidateLoopResumeOperation(
            request_id=next_id,
            request=CandidateLoopResumeRequest(
                predecessor_operation_id=root_id, expected_receipt_digest=review.receipt_digest
            ),
        ),
        launch_environment=env,
    )
    process_segments()
    resumed = read_operation(config, next_id).receipt
    # Counting from the anchor (body 3), body 4 is one body later: no second request.
    assert resumed.status == "completed", resumed
    assert resumed.loop_trace.attempted_iterations == 5
    assert resumed.loop_trace.input_request is None
    assert not (root / "pause.json").exists()
    assert len(verify_loop(request, launched, resumed)) == 5
