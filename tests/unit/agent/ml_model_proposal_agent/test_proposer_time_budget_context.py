"""Operator budgets must survive the protocol all the way to each LLM request.

The original defect passed transport tests: ProposalInput retained both values,
but the bridge received neither. These tests inspect production request assembly,
including independently assembled retries and the legacy commit that cannot rely
on its preceding free-text response to repeat operator context.
"""

from copy import deepcopy
from unittest.mock import MagicMock

import pytest

from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.proposal import ReasoningPipelineConfig, ReasoningStage
from agent.schemas.protocols.ml_result_interp_to_ml_model_propose import local_full_context
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from agent.schemas.task_config import ForwardContract
from nodes.ml_model_proposal_agent import MLModelProposalAgent

from .test_pipeline_runner import (
    FAKE_COMPARISON_OUTPUT,
    FAKE_INTERPRETATION,
    FAKE_PROPOSING_OUTPUT,
    FAKE_REASONING_OUTPUT,
)

pytestmark = pytest.mark.usefixtures("synthetic_dataset_profile")


def _input(tmp_path, *, mode="explore", trial=13.25, formal=47.5, is_trial=False):
    interpretation = InterpretationOutput.model_validate(
        {**deepcopy(FAKE_INTERPRETATION), "best_valid_denoising_score": 5.5}
    )
    stages = (
        []
        if mode == "legacy"
        else [
            ReasoningStage(name="comparison", system_prompt_key="COMPARATIVE_ANALYSIS"),
            ReasoningStage(name="causal_reasoning", system_prompt_key="CAUSAL_REASONING"),
        ]
    )
    inp = local_full_context(
        interpretation,
        StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="budget-context"),
        ),
        reasoning_pipeline=ReasoningPipelineConfig(
            stages=stages, exploration_mode="explore" if mode == "legacy" else mode
        ),
        trial_time_budget_minutes=trial,
        formal_time_budget_minutes=formal,
        is_trial=is_trial,
    )
    # Legacy contract rendering requires the same declared model I/O as a run.
    inp.forward_contract = ForwardContract(
        input_shape="[B, T] int64",
        input_description="class indices",
        output_shape="[B, 256, T] float32",
        output_description="per-timestep class logits",
        num_classes=256,
        task_type="classification",
    )
    return inp


def _reasoning():
    result = deepcopy(FAKE_REASONING_OUTPUT)
    result["falsifiable_prediction"]["metric"] = "tidmad_denoising_score"
    return result


def _run(inp, responses=None):
    captured = []
    queue = iter(
        deepcopy(
            responses
            if responses is not None
            else [FAKE_COMPARISON_OUTPUT, _reasoning(), FAKE_PROPOSING_OUTPUT]
        )
    )
    bridge = MagicMock()

    def generate(system, user, **kwargs):
        captured.append((kwargs["label"], system, user))
        return next(queue)

    def generate_text(system, user, **kwargs):
        captured.append((kwargs["label"], system, user))
        # Deliberately omit budgets: the next call must receive operator facts
        # from its typed input rather than trusting a model to repeat them.
        return "Choose a spectral convolution."

    bridge.generate.side_effect = generate
    bridge.generate_text.side_effect = generate_text
    agent = MLModelProposalAgent(
        provider="gemini", model_id="offline-budget-test", bridge_factory=lambda **_: bridge
    )
    agent.run(inp)
    return captured


def _assert_budgets(calls, trial=13.25, formal=47.5):
    expected = [
        f"{role} time budget: "
        + ("not configured in this input" if value is None else f"{value} minutes")
        for role, value in (("Trial", trial), ("Formal", formal))
    ]
    for label, _system, user in calls:
        for line in expected:
            assert line in user, f"{label} lost or changed operator context: {line}"


@pytest.mark.parametrize("mode", ["explore", "exploit", "legacy"])
@pytest.mark.parametrize("trial,formal", [(13.25, 47.5), (13.25, None), (None, 47.5), (None, None)])
def test_protocol_budgets_reach_every_initial_request(tmp_path, mode, trial, formal):
    """A dropped/swapped budget or a fabricated limit for None fails at the bridge."""
    inp = _input(tmp_path, mode=mode, trial=trial, formal=formal)
    responses = [FAKE_PROPOSING_OUTPUT] if mode == "legacy" else None
    calls = _run(inp, responses)
    expected_labels = (
        ["proposer.legacy_reasoning", "proposer.legacy_commit"]
        if mode == "legacy"
        else ["proposer.comparison", "proposer.causal_reasoning", "proposer.proposing"]
    )
    assert [call[0] for call in calls] == expected_labels
    assert inp.hardware_context is None  # Time context must also reach CPU/no-GPU inputs.
    _assert_budgets(calls, trial, formal)


@pytest.mark.parametrize("retry", ["comparison", "boldness", "causal", "proposing"])
def test_independently_assembled_retries_retain_both_role_budgets(tmp_path, retry):
    """Each retry has a real invalid response trigger; call labels prove reachability."""
    inp = _input(tmp_path, is_trial=True)
    comparison = deepcopy(FAKE_COMPARISON_OUTPUT)
    reasoning = _reasoning()
    proposal = deepcopy(FAKE_PROPOSING_OUTPUT)
    if retry == "comparison":
        comparison["proposed_vocab_links"] = [{"feature": "missing-required-fields"}]
        responses = [comparison, FAKE_COMPARISON_OUTPUT, reasoning, proposal]
        labels = ["comparison", "comparison.correction", "causal_reasoning", "proposing"]
    elif retry == "boldness":
        reasoning["falsifiable_prediction"]["predicted_value"] = 5.51
        responses = [comparison, reasoning, _reasoning(), proposal]
        labels = ["comparison", "causal_reasoning", "causal_reasoning", "proposing"]
    elif retry == "causal":
        reasoning["inherited_components"] = [
            {
                "component": "spectral",
                "source_type": "external_agent",
                "source_id": "iter_004",
                "contribution_evidence": "Reuse spectral processing.",
            }
        ]
        responses = [comparison, reasoning, _reasoning(), proposal]
        labels = ["comparison", "causal_reasoning", "causal_reasoning.correction", "proposing"]
    else:
        proposal["model_name"] = "wavenet"  # Already present in interpretation.
        responses = [comparison, reasoning, proposal, FAKE_PROPOSING_OUTPUT]
        labels = ["comparison", "causal_reasoning", "proposing", "proposing"]
    calls = _run(inp, responses)
    assert [call[0] for call in calls] == [f"proposer.{label}" for label in labels]
    _assert_budgets(calls)


def test_text_reasoning_stages_receive_operator_context(tmp_path):
    """The generate_text route must disclose the same facts as JSON stages."""
    inp = _input(tmp_path)
    for stage in inp.reasoning_pipeline.stages:
        stage.output_mode = "text"
    calls = _run(inp, [FAKE_PROPOSING_OUTPUT])
    assert [call[0] for call in calls] == [
        "proposer.comparison",
        "proposer.causal_reasoning",
        "proposer.proposing",
    ]
    _assert_budgets(calls)


def test_prior_stage_truncation_cannot_remove_operator_budgets(tmp_path):
    """Operator limits must survive even when previous model prose is truncated."""
    inp = _input(tmp_path)
    inp.reasoning_pipeline.policy.prior_stage_max_chars = 64
    comparison = deepcopy(FAKE_COMPARISON_OUTPUT)
    comparison["sota_mechanism"] = "OVERSIZED-STAGE-PROSE-" * 200
    calls = _run(inp, [comparison, _reasoning(), FAKE_PROPOSING_OUTPUT])
    assert comparison["sota_mechanism"] not in calls[-1][2]
    _assert_budgets(calls)


def test_proposing_request_describes_static_estimate_as_advisory(tmp_path):
    """The old test inspected only user sentinels; the contradiction was in system prose."""
    calls = _run(_input(tmp_path))
    label, system, user = calls[-1]
    assert label == "proposer.proposing"
    normalized = " ".join(system.lower().split())
    assert "the gate will reject the draft" not in normalized
    assert "advisory" in normalized
    assert "not a utilization target" in user.lower()
