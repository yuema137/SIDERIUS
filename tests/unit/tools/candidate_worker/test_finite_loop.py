"""Two real authored bodies and declared feedback; only provider/training effects are doubled."""

from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from agent.schemas.interpretation import InterpretationInput
from tools.candidate_worker import launch_candidate
from tools.candidate_worker.layout import interpretation_input_path
from tools.candidate_worker.loop_evidence import verify_loop
from workflows.definition import AuthoredLoop, LoopFeedback, ResultSource

from .conftest import refresh
from .test_graph import initial
from .test_graph_training import graph_training_request
from .test_interpretation import interpretation_provider as interpretation_provider
from .test_native import native_runner as native_runner
from .test_training import training_request as training_request
from .test_training import training_runner as training_runner


def loop_request(prepared, final_iteration=2, stop_conditions=()):
    request = graph_training_request(prepared)
    definition = request.preview.document.definition.model_copy(
        update={
            "loop": AuthoredLoop(
                final_iteration=final_iteration,
                feedback=LoopFeedback(
                    source=ResultSource(node="train"),
                    target="interpret",
                    protocol="tuning-to-interpretation",
                    history="native-research/v1",
                ),
                stop_conditions=stop_conditions,
            )
        }
    )
    return refresh(
        request.model_copy(
            update={
                "preview": request.preview.model_copy(
                    update={
                        "document": request.preview.document.model_copy(
                            update={"definition": definition}
                        )
                    }
                )
            }
        )
    )


@pytest.fixture
def loop_tuner(prepared, training_runner, native_runner, monkeypatch):
    from tests.unit.workflows.test_model_exploration import _make_tuning_output
    from tools.candidate_worker import training
    from workflows.task_composition import compose_run_task_bindings

    composition = compose_run_task_bindings(prepared.preview.document.definition.task.manifest)

    def run(self, value):
        training_runner.append(("tuner", value))
        return _make_tuning_output(
            model_type=value.model_type,
            run_name=value.storage.local.run_name,
            score=0.75,
            fingerprint=value.task_composition_ref.semantic_fingerprint,
            metric_spec=composition.metric.spec,
        ).model_copy(
            update={
                "candidate_id": value.candidate_id,
                "best_valid_formal_denoising_score": 0.75,
            }
        )

    generate = native_runner.generate

    def distinct(self, *args, **kwargs):
        value = generate(self, *args, **kwargs)
        if "model_name" in value:
            value["model_name"] += f"_{self.context['iter']}"
        return value

    monkeypatch.setattr(native_runner, "generate", distinct)
    monkeypatch.setattr(training.HyperparamTuningAgent, "run", run)
    return training_runner


def test_two_native_bodies_preserve_advice_and_verify_feedback(
    prepared, loop_tuner, native_runner, interpretation_provider, monkeypatch
):
    request = loop_request(prepared)
    receipt = launch_candidate(request)
    assert receipt.status == "completed", receipt.error
    assert receipt.loop_trace.attempted_iterations == 2
    assert receipt.graph_trace is None
    workspace = Path(receipt.workspace)
    first = InterpretationInput.model_validate_json(
        interpretation_input_path(workspace, "interpret").read_bytes()
    )
    second_path = interpretation_input_path(workspace, "interpret", iteration=2)
    second = InterpretationInput.model_validate_json(second_path.read_bytes())
    assert first.cold_start and not second.cold_start
    assert second.iteration == 2
    assert second.summaries[0].best_denoising_score == 0.75
    assert second.human_advice == first.human_advice
    assert second.previous_proposal["model_name"] == second.summaries[0].model_type
    assert {context["iter"] for _, context in native_runner.calls} == {1, 2}
    proposals = [value for name, value in loop_tuner if name == "proposal"]
    assert len(proposals) == 2
    tuned = [value for name, value in loop_tuner if name == "tuner"]
    assert [value.current_run_best_formal_score for value in tuned] == [None, 0.75]
    # Issue #983 T7 (F-SEED-2): each body's tuner derives under its own global
    # iteration and the authored node, from the one seed the launch receipt bound.
    from core.seeding import SeedCoordinates

    assert receipt.run_seed is not None and receipt.run_seed_source == "generated"
    assert [(value.run_seed, value.seed_coordinates) for value in tuned] == [
        (receipt.run_seed, SeedCoordinates(iteration=1, node_id="train")),
        (receipt.run_seed, SeedCoordinates(iteration=2, node_id="train")),
    ]
    assert all(
        any(
            item.kind == "human" and "both output logits" in item.content
            for item in value.expert_context
        )
        for value in proposals
    )
    parent = initial(request).model_copy(update={"run_id": receipt.run_id})
    assert len(verify_loop(request, parent, receipt)) == 2
    from tools.candidate_console import graph_results
    from tools.candidate_operations.models import CandidateOperation, OperationFailure

    operation_id = UUID(hex=receipt.run_id)
    submission = CandidateOperation(request_id=operation_id, request=request)
    monkeypatch.setattr(
        graph_results,
        "read_operation",
        lambda *_: SimpleNamespace(state="completed", receipt=receipt),
    )
    monkeypatch.setattr(
        graph_results,
        "lookup_operation_request",
        lambda *_: submission,
    )
    monkeypatch.setattr(graph_results, "read_model", lambda *_args, **_kwargs: parent)
    projection = graph_results.read_graph_results(
        SimpleNamespace(operation_store=object()), operation_id
    )
    assert [item.iteration for item in projection.bodies] == [1, 2]
    assert [item.tuning_state for item in projection.bodies] == ["succeeded", "succeeded"]
    assert [item.result.headline.best_score for item in projection.bodies] == [0.75, 0.75]
    # Each body keeps its own native report in verified order (model names differ per body).
    assert [item.result.model_type for item in projection.bodies] == [
        "worker_linear_1",
        "worker_linear_2",
    ]
    assert "iteration_002" not in projection.model_dump_json()

    second_path.write_text(second.model_copy(update={"human_advice": "tampered"}).model_dump_json())
    with pytest.raises(ValueError, match="capture mismatch"):
        verify_loop(request, parent, receipt)
    # The console maps a refused loop body to a typed, path-free integrity failure.
    with pytest.raises(OperationFailure, match="verified loop bodies are unavailable") as refused:
        graph_results.read_graph_results(SimpleNamespace(operation_store=object()), operation_id)
    assert refused.value.detail.code == "integrity"


@pytest.mark.parametrize("paused_first", [False, True])
def test_operation_stop_finishes_active_body_without_next_dispatch(
    prepared, loop_tuner, monkeypatch, tmp_path, paused_first
):
    import importlib
    from uuid import uuid4

    from tools.candidate_operations import (
        CandidateOperation,
        OperationStoreConfig,
        request_loop_pause,
        request_loop_stop,
        review_loop_resume,
        submit_operation,
    )
    from tools.candidate_operations.models import (
        OperationFailure,
        OperationSnapshot,
        ProcessObservation,
    )
    from tools.candidate_operations.store import load_record
    from tools.candidate_worker import training

    request = loop_request(prepared)
    config = OperationStoreConfig(
        state_root=str(tmp_path / "operations"),
        preparation_roots=(str(tmp_path),),
        candidate_roots=(str(tmp_path),),
    )
    submission = CandidateOperation(request_id=uuid4(), request=request)
    monkeypatch.setattr(
        importlib.import_module("tools.candidate_operations.submit"), "spawn", lambda *args: None
    )
    submit_operation(config, submission, launch_environment={"OPENAI_API_KEY": "offline-stub"})
    record = load_record(config, submission.request_id)
    # Before the worker claims its workspace, Pause and Resume review are typed not_ready.
    for control in (request_loop_pause, review_loop_resume):
        with pytest.raises(OperationFailure) as refused:
            control(config, submission.request_id)
        assert refused.value.detail.code == "not_ready"
    observed = OperationSnapshot(
        operation_id=submission.request_id,
        kind="candidate",
        request_digest=record.request_digest,
        observed_at=record.admitted_at,
        state="active",
        process=ProcessObservation(status="alive", reason="fixture"),
        reason="fixture",
    )
    monkeypatch.setattr(
        importlib.import_module("tools.candidate_operations.read"),
        "read_operation",
        lambda *args: observed,
    )
    real = training.HyperparamTuningAgent.run

    def stop_at_tuning(self, value):
        output = real(self, value)
        if paused_first:
            # Stop is terminal and wins even over an earlier Pause at the same boundary.
            request_loop_pause(config, submission.request_id)
        marker = request_loop_stop(config, submission.request_id)
        assert marker.run_id == record.native_id.hex
        return output

    monkeypatch.setattr(training.HyperparamTuningAgent, "run", stop_at_tuning)
    # As the operation child does: the admitted record's nonce and run seed.
    receipt = launch_candidate(request, invocation_id=record.native_id, run_seed=record.run_seed)
    assert receipt.status == "stopped", receipt.error
    assert receipt.loop_trace.attempted_iterations == 1
    assert len([item for item in loop_tuner if item[0] == "tuner"]) == 1
    assert not (Path(receipt.workspace) / "candidate_run/iteration_002").exists()
    verify_loop(request, initial(request).model_copy(update={"run_id": receipt.run_id}), receipt)


@pytest.mark.parametrize("paused", [False, True])
def test_failed_feedback_never_dispatches_the_next_body(prepared, loop_tuner, monkeypatch, paused):
    from tools.candidate_worker import training
    from tools.candidate_worker.loop_models import LoopPause
    from tools.candidate_worker.models import CandidateRunReceipt

    request = loop_request(prepared)
    real = training.HyperparamTuningAgent.run

    def abort(self, value):
        if paused:
            # A failed body never becomes a resumable paused checkpoint.
            control = Path(request.preview.document.definition.task.workspace) / "candidate_run"
            launched = CandidateRunReceipt.model_validate_json(
                (control / "launch.json").read_bytes()
            )
            (control / "pause.json").write_text(
                LoopPause(
                    run_id=launched.run_id, declaration_digest=launched.declaration_digest
                ).model_dump_json()
            )
        return real(self, value).model_copy(
            update={"termination_reason": "infrastructure_abort", "status": "failed"}
        )

    monkeypatch.setattr(training.HyperparamTuningAgent, "run", abort)
    receipt = launch_candidate(request)
    assert receipt.status == "failed", receipt.error
    assert receipt.loop_trace.attempted_iterations == 1
    assert len([item for item in loop_tuner if item[0] == "tuner"]) == 1
    assert not (Path(receipt.workspace) / "candidate_run/iteration_002").exists()
    verify_loop(request, initial(request).model_copy(update={"run_id": receipt.run_id}), receipt)


def test_loop_declaration_roundtrips_without_rewriting_body_or_absent_defaults(prepared):
    from workflows.definition.source import parse_workflow_source, render_workflow_source

    request = loop_request(prepared)
    document = request.preview.document
    source = render_workflow_source(document)
    assert parse_workflow_source(source) == document
    assert "AuthoredLoop(" in source and "LoopFeedback(" in source
    plain = document.model_copy(
        update={"definition": document.definition.model_copy(update={"loop": None})}
    )
    source = render_workflow_source(plain)
    assert "AuthoredLoop" not in source and "LoopFeedback" not in source and "loop=" not in source
    assert "loop" not in plain.definition.model_dump()


def test_native_completed_fold_retains_first_qualified_incumbent_on_tie():
    from core.chain_state import ChainState
    from tests.unit.workflows.test_model_exploration import (
        _make_interpretation_output,
        _make_proposal_output,
        _make_tune_output,
    )
    from workflows.research_history import advance_completed_history

    state = ChainState.cold_start()
    for name in ("first_model", "second_model"):
        output = _make_tune_output(name, 1.8)
        output.best_valid_formal_denoising_score = float("0.75")
        if name == "first_model":
            first_score = output.best_valid_formal_denoising_score
        advance_completed_history(
            state,
            _make_interpretation_output(),
            _make_proposal_output(name),
            output,
            required_gate_ids=None,
            run_metric_spec=output.metric_spec,
            bound_metric_spec=None,
        )
    assert state.chain_formal_incumbent_reference is first_score
    assert state.best_score_overall == 1.8
    assert state.all_model_types == ["first_model", "second_model"]


def test_omitted_seed_metric_uses_native_stamp_when_completed_cache_needs_capping(
    prepared, loop_tuner, interpretation_provider, monkeypatch
):
    import importlib
    import json

    request = loop_request(prepared)
    seed_path = Path(request.preview.project_root) / "interpret_input.json"
    seed = json.loads(seed_path.read_bytes())
    seed.pop("metric_spec")
    seed_path.write_text(json.dumps(seed))
    request = refresh(request)
    agent = importlib.import_module(
        "nodes.result_interpretation_agent.result_interpretation_agent"
    ).ResultInterpretationAgent
    real = agent.run

    def complete_cache(self, value):
        output = real(self, value)
        if value.iteration == 1:
            output.model_knowledge_cache = {
                name: {"_stats": {"best_denoising_score": score}}
                for name, score in (
                    ("worker_linear_1", 0.75),
                    *((f"cached_{i}", i) for i in range(1, 6)),
                )
            }
        return output

    monkeypatch.setattr(agent, "run", complete_cache)
    receipt = launch_candidate(request)
    assert receipt.status == "completed", receipt.error
    second = InterpretationInput.model_validate_json(
        interpretation_input_path(Path(receipt.workspace), "interpret", iteration=2).read_bytes()
    )
    assert second.metric_spec is not None
    assert set(second.model_knowledge_cache) == {
        "worker_linear_1",
        "cached_2",
        "cached_3",
        "cached_4",
        "cached_5",
    }
    verify_loop(request, initial(request).model_copy(update={"run_id": receipt.run_id}), receipt)


@pytest.mark.parametrize("fixture", ["prepared", "training_request"])
@pytest.mark.parametrize("status", ["stopped", "paused"])
def test_fixed_profile_readback_rejects_loop_stopped_status(request, fixture, status):
    from tools.candidate_worker.records import verify_candidate_records

    selected = request.getfixturevalue(fixture)
    launched = initial(selected)
    stopped = launched.model_copy(update={"status": status})
    with pytest.raises(ValueError, match="fixed candidate receipt cannot claim loop Stop"):
        verify_candidate_records(
            selected,
            launched,
            expected_request=selected,
            expected_run_id=launched.run_id,
            workspace=Path(launched.workspace),
            receipt=stopped,
        )


def run_metric(prepared):
    from workflows.task_composition import compose_run_task_bindings

    return compose_run_task_bindings(prepared.preview.document.definition.task.manifest).metric.spec


def scored_bodies(monkeypatch, scores, *, fail_at=None, on_body=None):
    """Per-body valid formal scores by managed slot; everything else stays the loop double."""
    from tools.candidate_worker import training

    real = training.HyperparamTuningAgent.run

    def run(self, value):
        output = real(self, value)
        iteration = next(
            i for i in range(1, 10) if f"iteration_{i:03d}" in value.storage.local.workspace
        )
        if on_body is not None:
            on_body(iteration)
        update = {"best_valid_formal_denoising_score": scores[iteration - 1]}
        if iteration == fail_at:
            update |= {"termination_reason": "infrastructure_abort", "status": "failed"}
        return output.model_copy(update=update)

    monkeypatch.setattr(training.HyperparamTuningAgent, "run", run)


def threshold_for(prepared):
    """A threshold the (low, high) pair straddles under the run's declared direction."""
    metric = run_metric(prepared)
    if metric.direction == "higher":
        return metric, 0.8, (0.5, 0.9)
    return metric, 0.6, (0.9, 0.4)


def test_met_threshold_completes_before_limit_and_beats_a_pending_stop(
    prepared, loop_tuner, monkeypatch
):
    from tools.candidate_worker.loop_models import LoopStop
    from tools.candidate_worker.loop_stop import MetricThresholdReason
    from tools.candidate_worker.models import CandidateRunReceipt
    from workflows.definition import MetricThresholdStop

    metric, threshold, (low, high) = threshold_for(prepared)
    request = loop_request(
        prepared,
        final_iteration=4,
        stop_conditions=(MetricThresholdStop(metric_id=metric.id, threshold=threshold),),
    )
    control = Path(request.preview.document.definition.task.workspace) / "candidate_run"

    def stop_during_second(iteration):
        if iteration == 2:
            launched = CandidateRunReceipt.model_validate_json(
                (control / "launch.json").read_bytes()
            )
            (control / "stop.json").write_text(
                LoopStop(
                    run_id=launched.run_id, declaration_digest=launched.declaration_digest
                ).model_dump_json()
            )

    scored_bodies(monkeypatch, (low, high, low, low), on_body=stop_during_second)
    receipt = launch_candidate(request)
    # A pending Stop would yield "stopped" if read before the completed-body evaluation.
    assert receipt.status == "completed", receipt.error
    assert receipt.loop_trace.attempted_iterations == 2
    assert not (control / "iteration_003").exists()
    expected = MetricThresholdReason(
        condition_index=0,
        iteration=2,
        metric_id=metric.id,
        direction=metric.direction,
        threshold=threshold,
        incumbent=high,
        incumbent_iteration=2,
    )
    assert receipt.loop_trace.stop_reason == expected
    parent = initial(request).model_copy(update={"run_id": receipt.run_id})
    assert len(verify_loop(request, parent, receipt)) == 2
    # Readback re-derives the reason: a tampered or missing value is refused.
    for trace in (
        receipt.loop_trace.model_copy(
            update={"stop_reason": expected.model_copy(update={"incumbent": low})}
        ),
        receipt.loop_trace.model_copy(update={"stop_reason": None}),
    ):
        with pytest.raises(ValueError, match="stop reason disagrees"):
            verify_loop(request, parent, receipt.model_copy(update={"loop_trace": trace}))


def test_condition_met_on_final_body_completes_at_limit_without_reason(
    prepared, loop_tuner, monkeypatch
):
    from workflows.definition import MetricThresholdStop

    metric, threshold, scores = threshold_for(prepared)
    request = loop_request(
        prepared,
        stop_conditions=(MetricThresholdStop(metric_id=metric.id, threshold=threshold),),
    )
    scored_bodies(monkeypatch, scores)
    receipt = launch_candidate(request)
    assert receipt.status == "completed", receipt.error
    # The final limit wins its boundary; the trace is byte-identical to a condition-free loop.
    assert receipt.loop_trace.model_dump_json() == '{"attempted_iterations":2}'
    verify_loop(request, initial(request).model_copy(update={"run_id": receipt.run_id}), receipt)


def test_failed_body_never_completes_by_condition(prepared, loop_tuner, monkeypatch):
    from workflows.definition import MetricThresholdStop

    metric, threshold, (_, high) = threshold_for(prepared)
    request = loop_request(
        prepared,
        final_iteration=3,
        stop_conditions=(MetricThresholdStop(metric_id=metric.id, threshold=threshold),),
    )
    scored_bodies(monkeypatch, (high, high, high), fail_at=1)
    receipt = launch_candidate(request)
    assert receipt.status == "failed"
    assert not (Path(receipt.workspace) / "candidate_run/iteration_002").exists()
    assert receipt.loop_trace.stop_reason is None
    verify_loop(request, initial(request).model_copy(update={"run_id": receipt.run_id}), receipt)


@pytest.mark.parametrize(
    ("final_iteration", "leading"),
    [
        (3, ()),
        # Review N2: an earlier no_improvement (k=1 fires at body 2) or a one-body limit
        # would otherwise hide the mismatch until, or past, the end of the run.
        (3, ("no_improvement",)),
        (1, ()),
    ],
)
def test_mismatched_threshold_metric_is_refused_before_any_body_is_dispatched(
    prepared, loop_tuner, monkeypatch, final_iteration, leading
):
    """Review N1: fails if the identity check only runs after body 1 trained and committed."""
    from workflows.definition import MetricThresholdStop, NoImprovementStop

    _, threshold, (low, _) = threshold_for(prepared)
    conditions = (
        *(NoImprovementStop(completed_bodies=1) for _ in leading),
        MetricThresholdStop(metric_id="undeclared_metric", threshold=threshold),
    )
    request = loop_request(prepared, final_iteration=final_iteration, stop_conditions=conditions)
    dispatched = []
    scored_bodies(monkeypatch, (low, low, low), on_body=dispatched.append)
    receipt = launch_candidate(request)
    assert receipt.status == "failed"
    assert f"stop condition {len(leading)} (metric_threshold)" in receipt.error
    assert "'undeclared_metric'" in receipt.error
    assert dispatched == []
    # Only the launch capture exists: no body slot, native record or tuner workspace.
    written = {
        p.relative_to(receipt.workspace).parts[:2] for p in Path(receipt.workspace).rglob("*")
    }
    assert not [
        parts for parts in written if parts[0] != "candidate_run" or "iteration" in parts[-1]
    ]


@pytest.mark.parametrize(
    "profile",
    [
        "native-proposal-fanout/v1",
        "native-proposal-families/v1",
        "native-literature-candidate/v1",
        None,  # the fixed single-candidate profile
    ],
)
def test_loop_on_unsupported_profile_is_refused_before_record_and_dispatch(
    prepared, tmp_path, monkeypatch, profile
):
    """Gap G2 (R1): only the native interpretation profile may launch an authored loop.

    Fails if launch admission (``fresh_preview`` in ``submit_operation``) stops refusing
    a looped declaration on another profile: a durable record, the active marker,
    the run workspace and a worker spawn would then appear. The control submission
    proves the same loop and credentials dispatch on the supported profile.
    ``admit_loop`` and each profile's shape check in ``preview_workflow`` refuse these
    declarations independently, so removing only one of them stays green.
    """
    from unittest.mock import Mock
    from uuid import uuid4

    from tools.candidate_operations import (
        CandidateOperation,
        OperationStoreConfig,
        submit_operation,
    )
    from tools.candidate_operations.models import OperationFailure

    supported = loop_request(prepared)
    assert supported.preview.execution_profile == "native-interpretation-candidate/v1"
    config = OperationStoreConfig(
        state_root=str(tmp_path / "state"),
        preparation_roots=(str(tmp_path),),
        candidate_roots=(str(tmp_path),),
    )
    spawn = Mock()
    monkeypatch.setattr("tools.candidate_operations.submit.spawn", spawn)
    unsupported = supported.model_copy(
        update={"preview": supported.preview.model_copy(update={"execution_profile": profile})}
    )
    submission = CandidateOperation(request_id=uuid4(), request=unsupported)
    with pytest.raises(OperationFailure) as refused:
        submit_operation(
            config, submission, launch_environment={"OPENAI_API_KEY": "offline-test-key"}
        )
    assert refused.value.detail.code == "candidate_preflight"
    assert refused.value.detail.message == "candidate inputs or routes changed; review again"
    state = Path(config.state_root)
    assert not (state / "operations" / str(submission.request_id)).exists()
    assert not (state / "active.json").exists()
    assert not Path(unsupported.preview.document.definition.task.workspace).exists()
    spawn.assert_not_called()

    handle = submit_operation(
        config,
        CandidateOperation(request_id=uuid4(), request=supported),
        launch_environment={"OPENAI_API_KEY": "offline-test-key"},
    )
    assert handle.observation == "starting"
    spawn.assert_called_once()


SEEDS = (4503599627370497, 9007199254740991)


def test_candidate_llm_requests_are_seed_invariant(
    prepared, loop_tuner, native_runner, interpretation_provider, monkeypatch
):
    """T15 (candidate): fails if any run seed or derived seed reaches an LLM-visible request.

    Two runs of the same two-body loop differ only in the explicit run seed and
    in minted identities (run/candidate UUIDs), which are masked. Every recorded
    proposer, implementor, validator and interpreter request is byte-identical.
    """
    import re

    recorded: list[str] = []
    # The interpreter double overrides only `generate`; it inherits `generate_text`.
    for owner, name in (
        (native_runner, "generate"),
        (native_runner, "generate_text"),
        (interpretation_provider, "generate"),
    ):
        real = owner.__dict__[name]

        def capture(self, system, user, *args, _real=real, **kwargs):
            recorded.append(f"{kwargs.get('label')}\n{system}\n{user}")
            return _real(self, system, user, *args, **kwargs)

        monkeypatch.setattr(owner, name, capture)
    workspace = Path(prepared.preview.document.definition.task.workspace)
    runs = {}
    for seed in SEEDS:
        recorded.clear()
        request = loop_request(prepared).model_copy(update={"run_seed": seed})
        receipt = launch_candidate(request)
        assert receipt.status == "completed", receipt.error
        assert (receipt.run_seed, receipt.run_seed_source) == (seed, "operator")
        masked = [
            re.sub(r"[0-9a-f]{32}|[0-9a-f-]{36}", "<id>", item).replace(str(workspace), "<ws>")
            for item in recorded
        ]
        labels = {item.split("\n", 1)[0] for item in recorded}
        assert "interpretation.per_model" in labels and len(labels) > 2, labels
        runs[seed] = masked
        # Move the run aside (never delete) so the second run claims a fresh workspace.
        workspace.rename(workspace.with_name(f"workspace-seed-{seed}"))
        # Raw, unmasked request text: no seed's digits and no seed field name.
        assert not any(str(value) in item for item in recorded for value in SEEDS)
        assert not any("run_seed" in item for item in recorded)
    first, second = runs.values()
    assert first == second


def test_met_input_request_pauses_with_summary_and_leaves_next_slot_unused(
    prepared, loop_tuner, monkeypatch
):
    """Fails if a met ``request_input`` condition completes or continues the loop, records
    its pause as a stop reason, or summarizes facts other than the verified scores."""
    from tools.candidate_worker.loop_stop import InputRequestSummary, NoImprovementReason
    from workflows.definition import NoImprovementStop

    metric, _, (low, high) = threshold_for(prepared)
    request = loop_request(
        prepared,
        final_iteration=4,
        stop_conditions=(NoImprovementStop(completed_bodies=2, on_met="request_input"),),
    )
    scored_bodies(monkeypatch, (high, low, low, high))
    receipt = launch_candidate(request)
    assert receipt.status == "paused", receipt.error
    trace = receipt.loop_trace
    assert trace.attempted_iterations == 3 and trace.stop_reason is None
    assert trace.input_request.reason == NoImprovementReason(
        condition_index=0,
        iteration=3,
        k=2,
        non_improving_bodies=2,
        last_improvement_iteration=1,
        incumbent=high,
    )
    assert trace.input_request.summary == InputRequestSummary(
        iteration=3,
        final_iteration=4,
        metric_id=metric.id,
        direction=metric.direction,
        incumbent=high,
        incumbent_iteration=1,
        non_improving_bodies=2,
        input_anchor=0,
        bodies_since_input=3,
    )
    control = Path(receipt.workspace) / "candidate_run"
    assert not (control / "iteration_004").exists()
    # A condition pause needs no operator Pause marker; readback re-derives it instead.
    assert not (control / "pause.json").exists()
    parent = initial(request).model_copy(update={"run_id": receipt.run_id})
    assert len(verify_loop(request, parent, receipt)) == 3


def test_operator_pause_and_condition_request_at_one_boundary_record_the_request(
    prepared, loop_tuner, monkeypatch
):
    """Fails if an operator Pause pending at a boundary where a ``request_input``
    condition fires hides the request (the condition is decided first), or if readback
    then depends on the marker either way."""
    from tools.candidate_worker.loop_models import LoopPause
    from tools.candidate_worker.models import CandidateRunReceipt
    from workflows.definition import NoImprovementStop

    _, _, (low, high) = threshold_for(prepared)
    request = loop_request(
        prepared,
        final_iteration=4,
        stop_conditions=(NoImprovementStop(completed_bodies=2, on_met="request_input"),),
    )
    control = Path(request.preview.document.definition.task.workspace) / "candidate_run"

    def pause_during_third(iteration):
        if iteration == 3:
            launched = CandidateRunReceipt.model_validate_json(
                (control / "launch.json").read_bytes()
            )
            (control / "pause.json").write_text(
                LoopPause(
                    run_id=launched.run_id, declaration_digest=launched.declaration_digest
                ).model_dump_json()
            )

    scored_bodies(monkeypatch, (high, low, low, high), on_body=pause_during_third)
    receipt = launch_candidate(request)
    assert receipt.status == "paused", receipt.error
    assert receipt.loop_trace.attempted_iterations == 3
    assert receipt.loop_trace.input_request.reason.iteration == 3
    parent = initial(request).model_copy(update={"run_id": receipt.run_id})
    assert len(verify_loop(request, parent, receipt)) == 3
    # The re-derived request alone justifies the pause: moving the marker aside changes nothing.
    (control / "pause.json").rename(control / "pause.json.aside")
    assert len(verify_loop(request, parent, receipt)) == 3


def test_readback_refuses_a_segment_that_continued_past_a_condition_input_request(
    prepared, loop_tuner, monkeypatch
):
    """Fails if readback accepts bodies dispatched after a re-derived ``request_input``
    boundary that is not a resumed checkpoint (the loop must have paused there)."""
    from workflows.definition import NoImprovementStop

    _, _, (low, high) = threshold_for(prepared)
    request = loop_request(prepared, final_iteration=4)
    scored_bodies(monkeypatch, (high, low, low, low))
    receipt = launch_candidate(request)
    assert receipt.status == "completed", receipt.error
    parent = initial(request).model_copy(update={"run_id": receipt.run_id})
    loop = request.preview.document.definition.loop
    asking = loop.model_copy(
        update={"stop_conditions": (NoImprovementStop(completed_bodies=2, on_met="request_input"),)}
    )
    # The same verified bodies replayed under a declaration that asks after body 3.
    replayed = request.model_copy(
        update={
            "preview": request.preview.model_copy(
                update={
                    "document": request.preview.document.model_copy(
                        update={
                            "definition": request.preview.document.definition.model_copy(
                                update={"loop": asking}
                            )
                        }
                    )
                }
            )
        }
    )
    with pytest.raises(ValueError, match="loop continued past a condition input request"):
        verify_loop(replayed, parent, receipt)
