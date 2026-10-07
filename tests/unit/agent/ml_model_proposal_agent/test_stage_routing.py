"""Actual proposer calls must honor stage selection, including repair paths."""

import ast
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agent.schemas.telemetry import LLMBridgeContextError
from nodes.ml_model_proposal_agent import MLModelProposalAgent
from workflows.llm_config import WorkflowLLMConfig

from .test_boldness_enforcement import _make_pipeline_input
from .test_causal_stage_validation import MALFORMED_REASONING, _pipeline_input
from .test_pipeline_runner import (
    FAKE_COMPARISON_OUTPUT,
    FAKE_PROPOSING_OUTPUT,
    FAKE_REASONING_OUTPUT,
)
from .test_proposal_agent import FAKE_COMMIT_RESPONSE, make_input

pytestmark = pytest.mark.usefixtures("synthetic_run_authorities")


class RecordingStageBridge:
    def __init__(self, settings, responses, calls):
        self.settings = settings
        self.responses = list(deepcopy(responses))
        self.calls = calls
        self.context = None

    def set_run_context(self, **context):
        if self.context and self.context["run_id"] != context["run_id"]:
            raise LLMBridgeContextError("run identity changed")
        self.context = context

    def generate(self, system, user, **kwargs):
        self.calls.append((self.settings, kwargs["label"], self.context, system, user))
        return self.responses.pop(0)

    def generate_text(self, system, user, **kwargs):
        self.calls.append((self.settings, kwargs["label"], self.context, system, user))
        return "Comparison text."


def factory_with(responses):
    bridges, calls = [], []

    def factory(**settings):
        bridge = RecordingStageBridge(settings, responses[settings["model_id"]], calls)
        bridges.append(bridge)
        return bridge

    return factory, bridges, calls


def distinct_config():
    return WorkflowLLMConfig.model_validate(
        {
            "propose": {
                "comparison": {"provider": "gemini", "model_id": "comparison", "max_retries": 0},
                "reasoning": {
                    "provider": "openai",
                    "model_id": "reasoning",
                    "reasoning_effort": "high",
                    "max_retries": 2,
                },
                "proposing": {
                    "provider": "openai",
                    "model_id": "proposing",
                    "reasoning_effort": "low",
                    "max_retries": 5,
                },
            }
        }
    )


@pytest.mark.parametrize("repair", [None, "comparison", "causal", "boldness", "proposing"])
def test_actual_pipeline_and_repairs_use_the_owning_route(tmp_path, repair):
    responses = {
        "comparison": [FAKE_COMPARISON_OUTPUT],
        "reasoning": [FAKE_REASONING_OUTPUT],
        "proposing": [FAKE_PROPOSING_OUTPUT],
    }
    if repair == "comparison":
        responses["comparison"].insert(
            0, dict(FAKE_COMPARISON_OUTPUT, proposed_vocab_candidates=None)
        )
    elif repair == "causal":
        responses["reasoning"].insert(0, MALFORMED_REASONING)
    elif repair == "boldness":
        timid = deepcopy(FAKE_REASONING_OUTPUT)
        timid["falsifiable_prediction"]["predicted_value"] = 5.51
        responses["reasoning"].insert(0, timid)
    elif repair == "proposing":
        responses["proposing"].insert(0, dict(FAKE_PROPOSING_OUTPUT, model_name="punet"))
    factory, bridges, calls = factory_with(responses)
    agent = MLModelProposalAgent(
        **distinct_config().get("propose"),
        bridge_factory=factory,
        capability_index_path=str(tmp_path / "index.json"),
    )
    assert len(bridges) == 1  # Unused stages must not require clients or keys.
    agent.set_run_context(workspace=tmp_path, iter=1, run_name="routing", run_id="run-1")
    agent.run(_make_pipeline_input(tmp_path) if repair == "boldness" else _pipeline_input(tmp_path))
    assert len(bridges) == 3
    assert len(calls) == (3 if repair is None else 4)
    for settings, label, context, _, _ in calls:
        role = (
            "comparison"
            if label.startswith("proposer.comparison")
            else "proposing"
            if label.startswith("proposer.proposing")
            else "reasoning"
        )
        assert settings["model_id"] == role
        assert context["run_id"] == "run-1"
        assert context["iter"] == 1
        expected = distinct_config().propose
        selected = getattr(expected, role)
        assert settings["provider"] == selected.provider
        assert settings["max_retries"] == selected.max_retries
        assert settings.get("reasoning_effort") == selected.reasoning_effort
    assert all(not b.responses for b in bridges)
    agent.set_run_context(workspace=tmp_path, iter=2, run_name="routing", run_id="run-1")
    assert all(b.context["iter"] == 2 for b in bridges)


def test_identical_routes_reuse_bridge_and_custom_stage_uses_reasoning(tmp_path):
    factory, bridges, _ = factory_with({"same": []})
    agent = MLModelProposalAgent(
        model_id="same", bridge_factory=factory, capability_index_path=str(tmp_path / "index.json")
    )
    for name in ("comparison", "causal_reasoning", "proposing", "custom_scientific_step"):
        assert agent._bridge_for_stage(name) is agent.bridge
    assert len(bridges) == 1


@pytest.mark.parametrize(
    "override",
    [
        {"comparison_reasoning_effort": None},
        {"comparison_max_retries": None},
        {"comparison_max_retries": 0},
    ],
)
def test_explicit_none_or_zero_changes_complete_bridge_identity(tmp_path, override):
    factory, bridges, _ = factory_with({"same": []})
    agent = MLModelProposalAgent(
        provider="openai",
        model_id="same",
        reasoning_effort="high",
        max_retries=7,
        bridge_factory=factory,
        capability_index_path=str(tmp_path / "index.json"),
        **override,
    )
    comparison = agent._bridge_for_stage("comparison")
    assert comparison is not agent.bridge
    assert len(bridges) == 2
    for key, value in override.items():
        assert comparison.settings.get(key.removeprefix("comparison_")) == value
    assert agent._bridge_for_stage("proposing") is agent.bridge


def test_failed_context_binding_does_not_cache_new_stage(tmp_path):
    factory, _bridges, _ = factory_with({"reasoning": [], "comparison": []})
    agent = MLModelProposalAgent(
        model_id="reasoning",
        comparison_model_id="comparison",
        bridge_factory=factory,
        capability_index_path=str(tmp_path / "index.json"),
    )
    agent.set_run_context(workspace=tmp_path, iter=1, run_name="routing", run_id="run-1")

    def refusing(**settings):
        bridge = factory(**settings)
        bridge.context = {"run_id": "other-run"}
        return bridge

    agent._bridge_factory = refusing
    with pytest.raises(LLMBridgeContextError, match="identity changed"):
        agent._bridge_for_stage("comparison")
    assert not agent._stage_bridges


def test_disabled_stage_never_constructs_its_bridge(tmp_path):
    factory, bridges, _ = factory_with(
        {"reasoning": [FAKE_REASONING_OUTPUT], "proposing": [FAKE_PROPOSING_OUTPUT]}
    )
    agent = MLModelProposalAgent(
        **distinct_config().get("propose"),
        bridge_factory=factory,
        capability_index_path=str(tmp_path / "index.json"),
    )
    inp = _pipeline_input(tmp_path)
    inp.reasoning_pipeline.stages[0].enabled = False
    agent.run(inp)
    assert [b.settings["model_id"] for b in bridges] == ["reasoning", "proposing"]


def test_text_comparison_uses_comparison_route(tmp_path):
    factory, _, calls = factory_with(
        {
            "comparison": [],
            "reasoning": [FAKE_REASONING_OUTPUT],
            "proposing": [FAKE_PROPOSING_OUTPUT],
        }
    )
    agent = MLModelProposalAgent(
        **distinct_config().get("propose"),
        bridge_factory=factory,
        capability_index_path=str(tmp_path / "index.json"),
    )
    inp = _pipeline_input(tmp_path)
    inp.reasoning_pipeline.stages[0].output_mode = "text"
    agent.run(inp)
    assert [(settings["model_id"], label) for settings, label, *_ in calls] == [
        ("comparison", "proposer.comparison"),
        ("reasoning", "proposer.causal_reasoning"),
        ("proposing", "proposer.proposing"),
    ]


def test_legacy_two_call_mode_keeps_reasoning_route(tmp_path):
    factory, bridges, calls = factory_with({"reasoning": [FAKE_COMMIT_RESPONSE]})
    agent = MLModelProposalAgent(
        **distinct_config().get("propose"),
        bridge_factory=factory,
        capability_index_path=str(tmp_path / "index.json"),
    )
    agent.run(make_input(tmp_path))
    assert len(calls) == 2
    assert len(bridges) == 1
    assert all(settings["model_id"] == "reasoning" for settings, *_ in calls)


def test_workflow_dispatches_context_to_agent_owner(tmp_path):
    # Execute the actual nested dispatcher without starting the workflow.
    import workflows.model_exploration as workflow

    tree = ast.parse(Path(workflow.__file__).read_text())
    run = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_workflow")
    binder = next(
        n for n in run.body if isinstance(n, ast.FunctionDef) and n.name == "_bind_iter_context"
    )
    assert any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "_bind_iter_context"
        and n.args
        and isinstance(n.args[0], ast.Name)
        and n.args[0].id == "_propose_agent"
        for n in ast.walk(run)
    )
    namespace = {
        "bindings": SimpleNamespace(
            workspace=str(tmp_path), chain_run_name="routing", run_id="run-1"
        ),
        "iteration": 3,
        "_Path": Path,
    }
    exec(compile(ast.Module(body=[binder], type_ignores=[]), workflow.__file__, "exec"), namespace)
    agent = SimpleNamespace(set_run_context=Mock(), bridge=Mock())
    namespace["_bind_iter_context"](agent)
    agent.set_run_context.assert_called_once_with(
        workspace=tmp_path,
        iter=3,
        run_name="routing",
        run_id="run-1",
    )
    agent.bridge.set_run_context.assert_not_called()
