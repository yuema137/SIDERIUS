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


def loop_request(prepared):
    request = graph_training_request(prepared)
    definition = request.preview.document.definition.model_copy(
        update={
            "loop": AuthoredLoop(
                final_iteration=2,
                feedback=LoopFeedback(
                    source=ResultSource(node="train"),
                    target="interpret",
                    protocol="tuning-to-interpretation",
                    history="native-research/v1",
                ),
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


def test_operation_stop_finishes_active_body_without_next_dispatch(
    prepared, loop_tuner, monkeypatch, tmp_path
):
    import importlib
    from uuid import uuid4

    from tools.candidate_operations import (
        CandidateOperation,
        OperationStoreConfig,
        request_loop_stop,
        submit_operation,
    )
    from tools.candidate_operations.models import OperationSnapshot, ProcessObservation
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
        marker = request_loop_stop(config, submission.request_id)
        assert marker.run_id == record.native_id.hex
        return output

    monkeypatch.setattr(training.HyperparamTuningAgent, "run", stop_at_tuning)
    receipt = launch_candidate(request, invocation_id=record.native_id)
    assert receipt.status == "stopped", receipt.error
    assert receipt.loop_trace.attempted_iterations == 1
    assert len([item for item in loop_tuner if item[0] == "tuner"]) == 1
    assert not (Path(receipt.workspace) / "candidate_run/iteration_002").exists()
    verify_loop(request, initial(request).model_copy(update={"run_id": receipt.run_id}), receipt)


def test_failed_feedback_never_dispatches_the_next_body(prepared, loop_tuner, monkeypatch):
    from tools.candidate_worker import training

    request = loop_request(prepared)
    real = training.HyperparamTuningAgent.run

    def abort(self, value):
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
def test_fixed_profile_readback_rejects_loop_stopped_status(request, fixture):
    from tools.candidate_worker.records import verify_candidate_records

    selected = request.getfixturevalue(fixture)
    launched = initial(selected)
    stopped = launched.model_copy(update={"status": "stopped"})
    with pytest.raises(ValueError, match="fixed candidate receipt cannot claim loop Stop"):
        verify_candidate_records(
            selected,
            launched,
            expected_request=selected,
            expected_run_id=launched.run_id,
            workspace=Path(launched.workspace),
            receipt=stopped,
        )
