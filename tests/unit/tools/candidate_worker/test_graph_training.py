"""Reachable authored training body; native upstream nodes/staging, offline tuner effects."""

import json
from pathlib import Path
from uuid import UUID

import pytest

from agent.schemas.proposal import ProposalInput
from tools.candidate_worker import launch_candidate
from tools.candidate_worker.graph_evidence import verify_graph_trace
from tools.candidate_worker.layout import tuning_input_path
from workflows.definition import WorkflowDocument

from .conftest import refresh
from .test_graph import initial
from .test_interpretation import interpretation_request
from .test_native import native_runner as native_runner
from .test_training import training_runner as training_runner


def graph_training_request(prepared):
    request = interpretation_request(prepared)
    root = Path(request.preview.project_root)
    document = request.preview.document.model_dump(mode="json")
    definition = document["definition"]
    validation = next(
        node["id"] for node in definition["nodes"] if node["capability"] == "validation"
    )
    definition["externals"].append(
        {"id": "settings", "contract": "native-training.settings", "location": "training.json"}
    )
    definition["nodes"].append(
        {
            "id": "train",
            "capability": "tuning",
            "request": {
                "kind": "protocol",
                "protocol": "validated-candidate-to-tuning",
                "arguments": [
                    {"name": "proposal", "source": {"kind": "result", "node": "propose"}},
                    {"name": "validation", "source": {"kind": "result", "node": validation}},
                    {"name": "settings", "source": {"kind": "external", "binding": "settings"}},
                ],
            },
        }
    )
    config = json.loads((root / "llm.json").read_bytes())
    config["tune"] = {
        "provider": "openai",
        "model_id": "tuner-test",
        "planner_strategy": "native-timing-v1",
    }
    (root / "llm.json").write_text(json.dumps(config))
    rules = json.loads((root / "rules.json").read_bytes())
    (root / "training.json").write_text(
        json.dumps(
            {
                "launch": {
                    "healthgate_mode": "observe_only",
                    "result_authority": "diagnostic",
                    "allowed_output_types": ["classifier"],
                    "trial_time_budget_minutes": 7,
                    "formal_time_budget_minutes": 19,
                    "max_rounds": 2,
                    "trial_max_epochs": 3,
                    "formal_max_epochs": 8,
                    "workflow_parameter_rules": rules,
                    "human_advice_tune": "Preserve both logits.",
                }
            }
        )
    )
    return refresh(
        request.model_copy(
            update={
                "preview": request.preview.model_copy(
                    update={"document": WorkflowDocument.model_validate_json(json.dumps(document))}
                )
            }
        )
    )


def test_five_node_native_training_and_parent_evidence(prepared, training_runner):
    request = graph_training_request(prepared)
    receipt = launch_candidate(request)
    assert receipt.status == "completed", receipt.error
    assert receipt.validation_passed is True
    assert len(receipt.native_output_paths) == 5
    tuned = next(value for name, value in training_runner if name == "tuner")
    proposed = next(value for name, value in training_runner if name == "proposal")
    assert (proposed.trial_time_budget_minutes, tuned.formal_time_budget_minutes) == (7, 19)
    assert tuned.current_run_best_formal_score is None
    assert any(
        item.kind == "human" and "both output logits" in item.content
        for item in proposed.expert_context
    )
    assert tuned.human_advice == "Preserve both logits."
    path = tuning_input_path(Path(receipt.workspace), "train")
    assert path.is_file()
    parent = initial(request).model_copy(update={"run_id": receipt.run_id})
    verify_graph_trace(request, parent, receipt)
    proposal_path = Path(receipt.workspace) / "candidate_run/proposal_inputs/propose.json"
    seed = ProposalInput.model_validate_json(proposal_path.read_bytes())
    proposal_path.write_text(seed.model_copy(update={"expert_context": []}).model_dump_json())
    with pytest.raises(ValueError, match="declared interpretation edge"):
        verify_graph_trace(request, parent, receipt)


def test_console_graph_results_reuse_native_run_report_without_paths(
    prepared, training_runner, monkeypatch
):
    from types import SimpleNamespace

    from execute_tools.run_report import load_run_output, project_run
    from tools.candidate_console import graph_results
    from tools.candidate_operations.models import CandidateOperation, OperationFailure

    request = graph_training_request(prepared)
    receipt = launch_candidate(request)
    assert receipt.status == "completed", receipt.error
    parent = initial(request).model_copy(update={"run_id": receipt.run_id})
    verify_graph_trace(request, parent, receipt)
    tuning = next(node for node in receipt.graph_trace.nodes if node.capability == "tuning")
    assert tuning.record_path is not None
    operation_id = UUID(hex=receipt.run_id)
    monkeypatch.setattr(
        graph_results,
        "read_operation",
        lambda *_: SimpleNamespace(state="completed", receipt=receipt),
    )
    monkeypatch.setattr(
        graph_results,
        "lookup_operation_request",
        lambda *_: CandidateOperation(request_id=operation_id, request=request),
    )

    view = graph_results.read_graph_results(SimpleNamespace(operation_store=object()), operation_id)
    expected = project_run(
        load_run_output(Path(tuning.record_path)), source_path=tuning.record_path
    )

    assert view.available is True
    assert len(view.bodies) == 1
    assert view.bodies[0].iteration == 1
    assert view.bodies[0].tuning_state == "succeeded"
    assert view.bodies[0].result is not None
    assert view.bodies[0].result.headline == expected.headline
    assert view.bodies[0].result.metric == expected.metric
    assert view.bodies[0].result.status_counts == expected.status_counts
    payload = view.model_dump_json()
    assert tuning.record_path not in payload
    assert "source_path" not in payload
    assert '"attempts":' not in payload

    # A completed operation whose tuning stage did not succeed has no score, even
    # though its record file is still on disk: process completion is not success.
    failed_nodes = tuple(
        node.model_copy(update={"state": "failed"}) if node is tuning else node
        for node in receipt.graph_trace.nodes
    )
    failed = receipt.model_copy(
        update={"graph_trace": receipt.graph_trace.model_copy(update={"nodes": failed_nodes})}
    )
    monkeypatch.setattr(
        graph_results,
        "read_operation",
        lambda *_: SimpleNamespace(state="completed", receipt=failed),
    )
    no_score = graph_results.read_graph_results(
        SimpleNamespace(operation_store=object()), operation_id
    )
    assert [(body.tuning_state, body.result) for body in no_score.bodies] == [("failed", None)]

    # A record changed after verification is refused as integrity, without its path.
    monkeypatch.setattr(
        graph_results,
        "read_operation",
        lambda *_: SimpleNamespace(state="completed", receipt=receipt),
    )
    record = Path(tuning.record_path)
    record.write_bytes(record.read_bytes() + b" ")
    with pytest.raises(OperationFailure, match="verified tuning output changed") as refused:
        graph_results.read_graph_results(SimpleNamespace(operation_store=object()), operation_id)
    assert refused.value.detail.code == "integrity"
    assert tuning.record_path not in refused.value.detail.message


@pytest.mark.parametrize("fault", ["validator", "abort", "disclosure"])
def test_training_graph_failure_boundaries(
    prepared, training_runner, native_runner, monkeypatch, fault
):
    from tools.candidate_worker import training

    request = graph_training_request(prepared)
    if fault == "validator":
        native_runner.reject = True
    elif fault == "abort":
        real_run = training.HyperparamTuningAgent.run

        def abort(self, value):
            return real_run(self, value).model_copy(
                update={
                    "status": "failed",
                    "termination_reason": "infrastructure_abort",
                    "all_records": [],
                    "completed_rounds": 0,
                    "best_denoising_score": None,
                    "best_formal_denoising_score": None,
                }
            )

        monkeypatch.setattr(training.HyperparamTuningAgent, "run", abort)
    else:
        root = Path(request.preview.project_root)
        for name in ("interpret_input", "constraints"):
            path = root / f"{name}.json"
            payload = json.loads(path.read_bytes())
            constraints = payload["constraint_context"] if name == "interpret_input" else payload
            constraints["workflow_rules"] = {"rules": {"train_config.epochs": {"exact": 99}}}
            path.write_text(json.dumps(payload))
        request = refresh(request)
    receipt = launch_candidate(request)
    assert receipt.status == ("rejected" if fault == "validator" else "failed"), receipt.error
    if fault == "abort":
        assert receipt.validation_passed is True
        assert receipt.graph_trace.nodes[-1].state == "failed"
        assert receipt.graph_trace.nodes[-1].record_path is not None
        parent = initial(request).model_copy(update={"run_id": receipt.run_id})
        verify_graph_trace(request, parent, receipt)
        with pytest.raises(ValueError, match="aggregate outcome"):
            verify_graph_trace(request, parent, receipt.model_copy(update={"status": "completed"}))
    else:
        assert not any(name == "tuner" for name, _ in training_runner)
        if fault == "disclosure":
            assert not native_runner.calls
            assert "disagrees with native training" in receipt.error


def test_native_tuning_transports_explicit_iteration_and_incumbent(
    prepared, training_runner, monkeypatch
):
    from dataclasses import replace

    from agent.schemas.storage import LocalStorageConfig, StorageConfig
    from tools.candidate_worker import graph, training

    request = graph_training_request(prepared)
    captured = []
    real = graph.run_training
    contexts = []
    monkeypatch.setattr(
        training.HyperparamTuningAgent, "set_run_context", lambda self, **kw: contexts.append(kw)
    )

    def observe(*args, **kwargs):
        captured.append((args, kwargs))
        return real(*args, **kwargs)

    monkeypatch.setattr(graph, "run_training", observe)
    receipt = launch_candidate(request)
    assert receipt.status == "completed", receipt.error
    args, _ = captured[0]
    context = args[0]
    from tools.candidate_worker.layout import graph_instance_dir
    from workflows.task_composition import bind_run_task_composition

    directory = graph_instance_dir(Path(receipt.workspace), receipt.run_name, "train", iteration=2)
    storage = StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace=str(directory), run_name=receipt.run_name),
    )
    next_context = replace(context, iteration=2, storage_workspace=str(directory))
    with bind_run_task_composition(
        args[4].bindings.task_composition,
        physical_data_root=str(
            Path(request.preview.project_root) / request.preview.document.definition.task.data_root
        ),
    ):
        output, path = real(
            next_context, *args[1:], storage=storage, chain_formal_incumbent_reference=0.75
        )
    tuned = [value for name, value in training_runner if name == "tuner"]
    assert tuned[0].current_run_best_formal_score is None
    assert tuned[-1].current_run_best_formal_score == 0.75
    assert [item["iter"] for item in contexts] == [1, 2]
    assert path.is_file() and output.model_type == tuned[-1].model_type
