"""Reachable native interpretation -> proposal; only provider construction is stubbed."""

import importlib
import json
from pathlib import Path
from typing import ClassVar

import pytest

from agent.schemas.interpretation import InterpretationInput, InterpretationOutput, ModelRunSummary
from agent.schemas.proposal import ProposalInput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from tests.helpers.candidate_fanout import fanout_request
from tools.candidate_worker import launch_candidate
from tools.candidate_worker.graph_evidence import verify_graph_trace
from tools.candidate_worker.layout import graph_instance_dir
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


@pytest.mark.parametrize("cold_start", [True, False])
def test_native_interpretation_reaches_proposal_and_parent_replays_edge(
    prepared, native_runner, interpretation_provider, cold_start
):
    request = interpretation_request(prepared, cold_start=cold_start)
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
    path.write_text(proposal.model_copy(update={"expert_context": []}).model_dump_json())
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
