"""Reachable authored training body; native upstream nodes/staging, offline tuner effects."""

import hashlib
import importlib
import json
import subprocess
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from agent.schemas.proposal import ProposalInput
from tools.candidate_prepare import (
    ReusableCandidatePreparationRequest,
    preflight_reusable_candidate,
    prepare_reusable_candidate,
)
from tools.candidate_prepare.reusable_interpretation import verify_payloads
from tools.candidate_worker import launch_candidate
from tools.candidate_worker.graph_evidence import verify_graph_trace
from tools.candidate_worker.layout import tuning_input_path
from tools.candidate_worker.models import CandidateRunRequest
from tools.workspace_sandbox.runner import ExecutionResult
from workflows.definition import (
    AuthoredLoop,
    LoopFeedback,
    ManagedCandidateBinding,
    ResultSource,
    ReusableTaskReferences,
    ReusableWorkflowDefinition,
    ReusableWorkflowDocument,
    WorkflowDocument,
    parse_workflow_source,
    render_workflow_source,
)

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
    config["tune"] = {"planner_strategy": "native-timing-v1"}
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


def reusable_graph_request(request):
    """Capture this native five-node graph through the existing reusable source path."""
    project = Path(request.preview.project_root)
    concrete = request.preview.document
    raw = concrete.model_dump(mode="json")
    definition = raw["definition"]
    externals = [
        ManagedCandidateBinding(id=item["id"], contract=item["contract"])
        for item in definition["externals"]
    ]
    settings = json.loads((project / "training.json").read_bytes())
    options = {
        "proposal_advice": "Preserve the declared feature interface.",
        "implementation_advice": request.implementation_advice,
        "validation_advice": request.validation_advice,
        "allowed_output_types": ("classifier",),
    }
    document = ReusableWorkflowDocument(
        definition=ReusableWorkflowDefinition(
            task=ReusableTaskReferences(
                manifest=definition["task"]["manifest"],
                data_root=definition["task"]["data_root"],
            ),
            externals=tuple(externals),
            nodes=tuple(concrete.definition.nodes),
            loop=concrete.definition.loop,
        ),
        positions=concrete.positions,
        preparation_options=options,
        execution_profile="native-interpretation-candidate/v1",
        training_settings=settings,
    )
    source_path = project / "reusable-interpretation.py"
    authored = "# saved editable source\n" + render_workflow_source(document)
    source_path.write_text(authored)
    reopened = parse_workflow_source(source_path.read_text())
    assert reopened == document
    runs = project / "runs"
    runs.mkdir(exist_ok=True)
    return (
        ReusableCandidatePreparationRequest(
            source_path=str(source_path),
            project_root=str(project),
            expected_source_sha256=hashlib.sha256(source_path.read_bytes()).hexdigest(),
            runs_root=str(runs),
            run_id=uuid4(),
            run_name=request.run_name,
            llm_config_file=str(project / "llm.json"),
            preparation_timeout_seconds=30.0,
            candidate_timeout_seconds=request.timeout_seconds,
            task_read_only=(),
            candidate_network=request.network,
            candidate_devices=request.devices,
            candidate_environment_names=request.environment_names,
        ),
        source_path,
        authored,
    )


def test_reusable_resolution_preserves_authored_loop_declaration(prepared):
    request = graph_training_request(prepared)
    reusable, source_path, _ = reusable_graph_request(request)
    document = parse_workflow_source(source_path.read_text())
    loop = AuthoredLoop(
        final_iteration=2,
        feedback=LoopFeedback(
            source=ResultSource(node="train"),
            target="interpret",
            protocol="tuning-to-interpretation",
            history="native-research/v1",
        ),
    )
    document = ReusableWorkflowDocument.model_validate_json(
        document.model_copy(
            update={"definition": document.definition.model_copy(update={"loop": loop})}
        ).model_dump_json()
    )
    source_path.write_text(render_workflow_source(document))
    reusable = reusable.model_copy(
        update={"expected_source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest()}
    )

    plan = preflight_reusable_candidate(reusable)
    assert plan.document.definition.loop == loop
    assert plan.resolved_document.definition.loop == loop
    assert parse_workflow_source(render_workflow_source(plan.resolved_document)) == (
        plan.resolved_document
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


@pytest.mark.parametrize("forged", ["run_seed", "seed_coordinates"])
def test_graph_readback_refuses_a_forged_tuning_seed(prepared, training_runner, forged):
    """(b) Fails if a persisted tuning input may claim another seed or position than launched."""
    from agent.schemas.hyperparam_tuning import HyperparamTuningInput
    from core.seeding import SeedCoordinates
    from tools.candidate_worker.graph_evidence import read_graph_control
    from tools.candidate_worker.models import CandidateRunReceipt

    request = graph_training_request(prepared)
    receipt = launch_candidate(request)
    assert receipt.status == "completed", receipt.error
    workspace = Path(receipt.workspace)
    launched = CandidateRunReceipt.model_validate_json(
        read_graph_control(workspace / "candidate_run/launch.json")
    )
    assert launched.run_seed is not None
    verify_graph_trace(request, launched, receipt)
    path = tuning_input_path(workspace, "train")
    value = HyperparamTuningInput.model_validate_json(read_graph_control(path))
    assert (value.run_seed, value.seed_coordinates) == (
        launched.run_seed,
        SeedCoordinates(iteration=1, node_id="train"),
    )
    update = (
        {"run_seed": launched.run_seed + 1}
        if forged == "run_seed"
        else {"seed_coordinates": SeedCoordinates(iteration=2, node_id="train")}
    )
    path.write_text(value.model_copy(update=update).model_dump_json(indent=2))
    with pytest.raises(ValueError, match="graph native training identity"):
        verify_graph_trace(request, launched, receipt)


def test_saved_reusable_interpretation_profile_reaches_same_native_five_node_path(
    prepared, native_runner, training_runner, monkeypatch
):
    """The saved v2 graph resolves managed inputs, then uses the existing native worker path."""
    interpreter = importlib.import_module(
        "nodes.result_interpretation_agent.result_interpretation_agent"
    )
    monkeypatch.setattr(interpreter, "LLMBridge", native_runner)
    concrete = graph_training_request(prepared)
    reusable, source_path, authored = reusable_graph_request(concrete)

    def direct_child(profile, argv):
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        if completed.returncode:
            raise AssertionError(
                completed.stderr
                + (
                    Path(reusable.runs_root)
                    / str(reusable.run_id)
                    / "inputs/preparation/worker.log"
                ).read_text()
            )
        return ExecutionResult(status="completed", returncode=0, elapsed_seconds=0.0)

    monkeypatch.setattr(
        importlib.import_module("tools.candidate_prepare.launch"), "run", direct_child
    )
    receipt = prepare_reusable_candidate(reusable)
    assert receipt.status == "prepared", receipt.error
    output = Path(receipt.envelope) / "inputs"
    candidate = CandidateRunRequest.model_validate_json(
        Path(receipt.candidate_request_path).read_bytes()
    )
    assert candidate.preview.execution_profile == "native-interpretation-candidate/v1"
    assert len(candidate.preview.document.definition.nodes) == 5
    assert parse_workflow_source(source_path.read_text()) == parse_workflow_source(authored)
    assert source_path.read_text() == authored
    managed = {item.id: item.location for item in candidate.preview.document.definition.externals}
    assert managed["interpret_input"] == str(output / "external.interpret_input.json")
    assert managed["proposal_slot"] == str(output / "storage.propose.json")
    assert (output / "training_settings.json").is_file()
    assert {Path(item.path).name for item in candidate.files} >= {
        "external.interpret_input.json",
        "external.data_dir.json",
        "external.task_ref.json",
        "external.advice.json",
        "external.rules.json",
        "external.constraints.json",
        "storage.propose.json",
        "training_settings.json",
    }
    prepared_source = parse_workflow_source(source_path.read_text())
    from tools.candidate_prepare.reusable_models import ReusableBindingCapture

    capture = ReusableBindingCapture.model_validate_json(
        (output.parent / "binding.json").read_bytes()
    )
    verify_payloads(prepared_source, capture.request, output, Path.read_bytes)

    def tampered_read(path):
        if path.name == "external.advice.json":
            return b"{}\n"
        return path.read_bytes()

    with pytest.raises(ValueError, match="managed protocol input differs"):
        verify_payloads(prepared_source, capture.request, output, tampered_read)

    receipt = launch_candidate(candidate)
    assert receipt.status == "completed", receipt.error
    assert receipt.graph_trace is not None
    assert [item.capability for item in receipt.graph_trace.nodes] == [
        "proposal",
        "implementation",
        "validation",
        "interpretation",
        "tuning",
    ]
    assert all(item.state == "succeeded" for item in receipt.graph_trace.nodes)
    proposal = next(value for name, value in training_runner if name == "proposal")
    tuned = next(value for name, value in training_runner if name == "tuner")
    assert proposal.task_composition_ref is not None
    assert any(item.kind == "human" for item in proposal.expert_context)
    assert tuned.current_run_best_formal_score is None
    verify_graph_trace(
        candidate, initial(candidate).model_copy(update={"run_id": receipt.run_id}), receipt
    )


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
    from tools.candidate_worker import training

    request = graph_training_request(prepared)
    captured = []
    real = training.run_training
    contexts = []
    monkeypatch.setattr(
        training.HyperparamTuningAgent, "set_run_context", lambda self, **kw: contexts.append(kw)
    )

    def observe(*args, **kwargs):
        captured.append((args, kwargs))
        return real(*args, **kwargs)

    # The tuning unit resolves the native call at dispatch (B3-3 unit_child).
    monkeypatch.setattr(training, "run_training", observe)
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


def test_nonfinite_tuning_score_crosses_the_tuning_unit(prepared, training_runner, monkeypatch):
    """Fails if the unit boundary refuses a -inf tuning score sentinel, which would
    fail a tuning node whose in-process output was valid. (Nonfinite settings
    transport is covered directly in test_unit_process.)"""
    from tools.candidate_worker import training
    from tools.candidate_worker.graph_evidence import read_graph_control
    from tools.candidate_worker.unit_models import NodeUnitResult
    from tools.candidate_worker.unit_transport import decode_transport

    tuner = training.HyperparamTuningAgent
    real = tuner.run
    monkeypatch.setattr(
        tuner,
        "run",
        lambda self, value: real(self, value).model_copy(
            update={"best_denoising_score": float("-inf")}
        ),
    )
    receipt = launch_candidate(graph_training_request(prepared))
    assert receipt.status == "completed", receipt.error
    path = Path(receipt.workspace) / "candidate_run/units/train/result.json"
    result = decode_transport(NodeUnitResult, read_graph_control(path))
    assert result.outcome == "returned" and result.output is not None
    output = decode_transport(training.HyperparamTuningOutput, result.output.encode())
    assert output.best_denoising_score == float("-inf")


# Pinned on base bce9c452 (before adaptor execution): sha256 of the trained graph
# receipt's trace, status, validation flag and output index, with the workspace and
# native record digests (which embed tmp paths) masked. Adaptor support must not
# move these bytes.
TRAINED_TRACE_SHA256 = {
    "completed": "18c39b0014c87cf80f936184529bf32133f2735dcb1a36d8de0babfb5878ae9e",
    "rejected": "5b6c189069ab88d4a67bbf8613661c70d3b27a1a411aa54184976651418c767d",
}


@pytest.mark.parametrize("outcome", sorted(TRAINED_TRACE_SHA256))
def test_unadapted_training_trace_bytes_are_unchanged(
    prepared, training_runner, native_runner, outcome
):
    """Fails if adaptor execution alters serialization or outcome of a trained graph run."""
    import re

    native_runner.reject = outcome == "rejected"
    request = graph_training_request(prepared)
    receipt = launch_candidate(request)
    payload = receipt.model_dump_json(
        include={"status", "validation_passed", "graph_trace", "native_output_paths"}
    ).replace(receipt.workspace, "<ws>")
    payload = re.sub(r'"record_sha256":"[0-9a-f]{64}"', '"record_sha256":"<sha>"', payload)
    assert hashlib.sha256(payload.encode()).hexdigest() == TRAINED_TRACE_SHA256[outcome], payload
    verify_graph_trace(
        request, initial(request).model_copy(update={"run_id": receipt.run_id}), receipt
    )


def test_nonfinite_launch_values_survive_the_graph_tuning_input(prepared, training_runner):
    """#1012: the graph writes the tuner input as JSON and evidence rereads it.

    The default inf->null encoding turned an accepted infinite penalty into
    None, so the reread evidence disagreed with the value the tuner ran.
    """
    request = graph_training_request(prepared)
    path = Path(request.preview.project_root) / "training.json"
    settings = json.loads(path.read_text())
    settings["launch"]["degenerate_penalty_score"] = "-inf"
    path.write_text(json.dumps(settings))
    request = refresh(request)
    receipt = launch_candidate(request)
    assert receipt.status == "completed", receipt.error
    from agent.schemas.hyperparam_tuning import HyperparamTuningInput

    saved = HyperparamTuningInput.model_validate_json(
        tuning_input_path(Path(receipt.workspace), "train").read_bytes()
    )
    assert saved.degenerate_penalty_score == float("-inf")
    verify_graph_trace(
        request, initial(request).model_copy(update={"run_id": receipt.run_id}), receipt
    )


def test_native_run_output_with_nonfinite_scores_is_not_a_disagreement(
    prepared, training_runner, monkeypatch
):
    """#1046: the native writer stores run_output through the storage owner
    (inf/NaN -> null), and capture_record then compared that record with the
    returned output (-inf, NaN) and raised "native record disagrees", failing a
    real graph training run. The record must keep the storage owner's strict
    JSON, and the in-memory output must keep -inf for the next phase."""
    from nodes.ml_hyperparameter_tune_agent.records import publish_run_output
    from tools.candidate_worker import training
    from tools.candidate_worker.graph_evidence import read_graph_control
    from tools.candidate_worker.unit_models import NodeUnitResult
    from tools.candidate_worker.unit_transport import decode_transport

    tuner = training.HyperparamTuningAgent
    real = tuner.run

    def native_run(self, value):
        output = real(self, value).model_copy(
            update={
                "best_denoising_score": float("-inf"),
                "best_formal_denoising_score": float("nan"),
            }
        )
        local = value.storage.local
        publish_run_output(str(Path(local.workspace) / f"run_output_{local.run_name}.json"), output)
        return output

    monkeypatch.setattr(tuner, "run", native_run)
    receipt = launch_candidate(graph_training_request(prepared))
    assert receipt.status == "completed", receipt.error
    (path,) = Path(receipt.workspace).rglob("run_output_*.json")
    raw = path.read_text()
    assert "Infinity" not in raw and "NaN" not in raw
    saved = training.HyperparamTuningOutput.model_validate_json(raw)
    assert saved.best_denoising_score is None and saved.best_formal_denoising_score is None
    result = decode_transport(
        NodeUnitResult,
        read_graph_control(Path(receipt.workspace) / "candidate_run/units/train/result.json"),
    )
    assert result.output is not None
    returned = decode_transport(training.HyperparamTuningOutput, result.output.encode())
    assert returned.best_denoising_score == float("-inf")
