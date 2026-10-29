"""Reachable native interpretation -> proposal; only provider construction is stubbed."""

import importlib
import json
from pathlib import Path
from typing import ClassVar

import pytest

from agent.schemas.interpretation import InterpretationInput, InterpretationOutput, ModelRunSummary
from agent.schemas.proposal import ProposalInput, ReasoningPipelineConfig
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from tests.helpers.candidate_fanout import fanout_request
from tools.candidate_worker import launch_candidate
from tools.candidate_worker.graph_evidence import verify_graph_trace
from tools.candidate_worker.layout import graph_instance_dir
from tools.workflow_preview.config import parse_config
from workflows.proposal_pipeline import get_reasoning_pipeline
from workflows.task_composition import compose_run_task_bindings

from .conftest import refresh
from .test_graph import initial
from .test_native import native_runner


def interpretation_request(prepared, *, cold_start=True):
    request = fanout_request(prepared, branches=1)
    project = Path(request.preview.project_root)
    workspace = Path(request.preview.document.definition.task.workspace)
    composition = compose_run_task_bindings(request.preview.document.definition.task.manifest)

    def storage(node):
        return StorageConfig(
            backend="local",
            local=LocalStorageConfig(
                workspace=str(graph_instance_dir(workspace, request.run_name, node)),
                run_name=request.run_name,
            ),
        )

    seed = json.loads((project / "seed.json").read_text())
    rules = {"rules": {"train_config.epochs": {"exact": 1}}}
    constraints = {
        "known_sections": ["objective", "workflow_rules"],
        "objective": seed["task_composition_ref"]["objective"],
        "workflow_rules": rules,
    }
    interpreted = InterpretationInput(
        cold_start=cold_start,
        task_description=composition.task_description,
        task_blocks=composition.interpretation_blocks,
        description_source_policy="composed",
        metric_spec=composition.metric.spec,
        constraint_context=constraints,
        human_advice="Preserve the declared feature interface.",
        storage=storage("interpret"),
        summaries=[]
        if cold_start
        else [
            ModelRunSummary(
                model_type="prior_linear",
                run_name="recorded_seed",
                status="completed",
                completed_rounds=1,
                best_denoising_score=0.75,
                worst_denoising_score=0.75,
                round_scores=[0.75],
                model_description="A previous four feature classifier.",
            )
        ],
    )
    values = {
        "interpret_input": ("interpretation.input", interpreted.model_dump(mode="json")),
        "proposal_slot": ("storage", storage("propose").model_dump(mode="json")),
        "data_dir": ("optional.text", seed["data_dir"]),
        "task_ref": ("optional.task-composition-ref", seed["task_composition_ref"]),
        "advice": ("optional.expert-advice", "Keep both output logits; do not change the task."),
        "rules": ("optional.parameter-rules", rules),
        "constraints": ("optional.constraint-context", constraints),
    }
    raw = request.preview.document.model_dump(mode="json")
    definition = raw["definition"]
    definition["externals"] = [item for item in definition["externals"] if item["id"] != "seed"]
    for name, (contract, value) in values.items():
        (project / f"{name}.json").write_text(json.dumps(value))
        definition["externals"].append(
            {"id": name, "contract": contract, "location": f"{name}.json"}
        )
    proposal = definition["nodes"][0]
    proposal["request"] = {
        "kind": "protocol",
        "protocol": "interpretation-to-proposal",
        "arguments": [
            {"name": "output", "source": {"kind": "result", "node": "interpret"}},
            *(
                {"name": name, "source": {"kind": "external", "binding": binding}}
                for name, binding in (
                    ("storage", "proposal_slot"),
                    ("data_dir", "data_dir"),
                    ("task_composition_ref", "task_ref"),
                    ("human_advice", "advice"),
                    ("workflow_parameter_rules", "rules"),
                    ("constraint_context", "constraints"),
                )
            ),
        ],
    }
    definition["nodes"].append(
        {
            "id": "interpret",
            "capability": "interpretation",
            "request": {
                "kind": "external",
                "binding": "interpret_input",
            },
        }
    )
    preview = type(request.preview).model_validate_json(
        json.dumps(
            {
                **request.preview.model_dump(mode="json"),
                "document": raw,
                "execution_profile": "native-interpretation-candidate/v1",
            }
        )
    )
    return refresh(request.model_copy(update={"preview": preview}))


@pytest.fixture
def interpretation_provider(native_runner, monkeypatch):
    module = importlib.import_module(
        "nodes.result_interpretation_agent.result_interpretation_agent"
    )

    class Interpreter(native_runner):
        instances: ClassVar[list] = []

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.instances.append(self)

        def generate(self, system, user, **kwargs):
            assert kwargs["label"] == "interpretation.per_model"
            assert "0.75" in user
            self.calls.append((kwargs["label"], self.context))
            return {
                "key_findings": ["The captured seed scored 0.75."],
                "score_trend": "one observed run",
            }

    monkeypatch.setattr(module, "LLMBridge", Interpreter)
    return Interpreter


@pytest.mark.parametrize("cold_start,staged", [(True, True), (False, True), (True, False)])
def test_native_interpretation_reaches_proposal_and_parent_replays_edge(
    prepared, native_runner, interpretation_provider, cold_start, staged
):
    request = interpretation_request(prepared, cold_start=cold_start)
    config_path = Path(request.preview.project_root) / "llm.json"
    if not staged:
        config = json.loads(config_path.read_bytes())
        config["propose"] = None
        config_path.write_text(json.dumps(config))
        request = refresh(request)
    expected_pipeline = get_reasoning_pipeline(parse_config(config_path.read_bytes()))
    receipt = launch_candidate(request)
    assert receipt.status == "accepted", receipt.error
    assert (
        "interpretation.per_model" in [label for label, _ in native_runner.calls]
        if not cold_start
        else all(label != "interpretation.per_model" for label, _ in native_runner.calls)
    )
    assert all(
        context["iter"] == 1 and context["run_id"] == receipt.run_id
        for _, context in native_runner.calls
    )
    records = {item.capability: item for item in receipt.graph_trace.nodes}
    output = InterpretationOutput.model_validate_json(
        Path(records["interpretation"].record_path).read_bytes()
    )
    assert output.cold_start is cold_start
    assert output.model_types == ([] if cold_start else ["prior_linear"])
    path = Path(receipt.workspace) / "candidate_run/proposal_inputs/propose.json"
    proposal = ProposalInput.model_validate_json(path.read_bytes())
    assert proposal.reasoning_pipeline == (expected_pipeline or ReasoningPipelineConfig())
    assert (expected_pipeline is not None) is staged
    labels = [label for label, _ in native_runner.calls]
    assert ("proposer.comparison" in labels) is staged
    assert ("proposer.causal_reasoning" in labels) is staged
    assert proposal.cold_start is cold_start
    assert any(
        item.kind == "human" and "both output logits" in item.content
        for item in proposal.expert_context
    )
    assert proposal.workflow_parameter_rules.model_dump(mode="json") == json.loads(
        (Path(request.preview.project_root) / "rules.json").read_bytes()
    )
    assert proposal.constraint_context.workflow_rules == proposal.workflow_parameter_rules
    assert proposal.task_composition_ref is not None
    assert proposal.existing_model_types == output.model_types
    parent = initial(request).model_copy(update={"run_id": receipt.run_id})
    verify_graph_trace(request, parent, receipt)
    # A valid declaration is insufficient: a lost adapter/advice projection is rejected.
    mutation = (
        {"reasoning_pipeline": ReasoningPipelineConfig()} if staged else {"expert_context": []}
    )
    path.write_text(proposal.model_copy(update=mutation).model_dump_json())
    with pytest.raises(ValueError, match="declared interpretation edge"):
        verify_graph_trace(request, parent, receipt)


@pytest.mark.parametrize("defect", ["task", "storage", "iteration", "constraints"])
def test_interpretation_binding_refusal_precedes_provider(
    prepared, native_runner, interpretation_provider, defect
):
    request = interpretation_request(prepared)
    path = Path(request.preview.project_root) / "interpret_input.json"
    value = json.loads(path.read_bytes())
    if defect == "task":
        value["task_description"] = "another task"
    elif defect == "storage":
        value["storage"]["local"]["workspace"] = str(path.parent)
    elif defect == "iteration":
        value["iteration"] = 2
    else:
        # Both channels agree with each other but lie about the task authority.
        value["constraint_context"]["objective"] = {"loss_type": "smooth_l1"}
        (path.parent / "constraints.json").write_text(json.dumps(value["constraint_context"]))
    path.write_text(json.dumps(value))
    receipt = launch_candidate(refresh(request))
    assert receipt.status == "failed"
    assert not native_runner.calls
    assert not interpretation_provider.instances
    assert {
        "task": "task disagrees",
        "storage": "storage disagrees",
        "iteration": "iteration disagrees",
        "constraints": "objective disagrees",
    }[defect] in receipt.error


def test_resume_advice_composes_after_declared_advice_and_is_absent_without_it():
    """Fails if a resume without operator advice changes the proposer's ``human_advice``
    (or the binding/request bytes that carry advice), or if operator advice replaces the
    declared advice instead of following it under its "after body N" header."""
    from uuid import UUID

    from agent.schemas.hyperparam_tuning import ExpertAdvice
    from tools.candidate_operations.models import CandidateLoopResumeRequest
    from tools.candidate_worker.interpretation import compose_proposal_advice
    from tools.candidate_worker.loop_models import LoopContinuation, ResumeAdvice

    structured = ExpertAdvice(focus_areas=["depth first"], freeform_notes="keep logits")
    for declared in (None, "Keep both logits.", structured):
        assert compose_proposal_advice(declared, None) is declared
    advice = ResumeAdvice(after_body=2, text="Try a smaller hidden width.")
    assert compose_proposal_advice(None, advice) == (
        "Operator advice after body 2:\nTry a smaller hidden width."
    )
    assert compose_proposal_advice("Keep both logits.", advice) == (
        "Keep both logits.\n\nOperator advice after body 2:\nTry a smaller hidden width."
    )
    assert compose_proposal_advice(structured, advice) == (
        "Focus areas: depth first\nNotes: keep logits\n\n"
        "Operator advice after body 2:\nTry a smaller hidden width."
    )
    identity = {"run_id": "a" * 32, "declaration_digest": "d" * 64}
    binding = LoopContinuation(
        **identity,
        operation_id=UUID(int=1),
        predecessor_segment=None,
        predecessor_receipt_digest="c" * 64,
        completed_iterations=2,
    )
    assert "operator_advice" not in binding.model_dump_json()
    assert binding.resume_advice() is None
    advised = binding.model_copy(update={"operator_advice": advice.text})
    assert advised.resume_advice() == advice
    request = CandidateLoopResumeRequest(
        predecessor_operation_id=UUID(int=1), expected_receipt_digest="c" * 64
    )
    assert request.model_dump_json() == (
        '{"predecessor_operation_id":"00000000-0000-0000-0000-000000000001",'
        '"expected_receipt_digest":"' + "c" * 64 + '"}'
    )


@pytest.mark.parametrize(
    ("raw", "accepted"),
    [
        ("  Try a smaller width.\n", "Try a smaller width."),
        ("line one\n\tline two", "line one\n\tline two"),
        ("", None),
        ("   \n", None),
        ("x" * 4001, None),
        ("nul\x00byte", None),
        ("carriage\rreturn", None),
        ("escape\x1b[31m", None),
    ],
)
def test_operator_advice_is_trimmed_bounded_and_free_of_control_characters(raw, accepted):
    """Fails if advice text with terminal/control characters, no content, or more than
    4000 characters reaches a binding, or if trimming makes retries differ."""
    from uuid import UUID

    from pydantic import ValidationError

    from tools.candidate_operations.models import CandidateLoopResumeRequest

    def build():
        return CandidateLoopResumeRequest(
            predecessor_operation_id=UUID(int=1),
            expected_receipt_digest="c" * 64,
            operator_advice=raw,
        )

    if accepted is None:
        with pytest.raises(ValidationError):
            build()
    else:
        assert build().operator_advice == accepted
