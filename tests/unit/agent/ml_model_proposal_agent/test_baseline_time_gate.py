"""
Tests for the proposer's baseline time-budget gate (Phase E2).

The gate is implemented in ``nodes.ml_model_proposal_agent._apply_time_gate``
and called from ``MLModelProposalAgent.run`` after the LLM proposal lands but
before persistence. It mutates ``output.time_risk`` per the gate-and-annotate
policy in docs/time_estimator_implement.md §2.7.4:

  - feasible=True   → time_risk stays None.
  - feasible=False  → time_risk = result["suggestion"].
  - status="error"  → time_risk stays None, warning printed.
  - budget=None     → skill not called at all (one-time process warning).

LLM calls are mocked (we don't exercise the actual proposing pipeline here);
the skill module's ``run_skill`` is patched so each test controls the verdict.
"""
import pytest
from unittest.mock import MagicMock, patch

from agent.schemas.proposal import ProposalInput, ProposalOutput
from agent.schemas.storage import StorageConfig, LocalStorageConfig
from nodes.ml_model_proposal_agent import (
    MLModelProposalAgent,
    _apply_time_gate,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FAKE_INTERPRETATION = {
    "model_types": ["punet"],
    "model_descriptions": {"punet": "PUNet description..."},
    "total_experiments": 5,
    "per_model_best": {"punet": 1.5},
    "per_model_worst": {"punet": 0.8},
    "best_denoising_score": 1.5,
    "worst_denoising_score": 0.8,
    "best_config": {"model_config": {"depth": 3}},
    "key_findings": ["focal loss outperforms ce"],
    "bottlenecks": ["architecture capacity"],
    "take_home_message": "A new architecture is needed.",
}


FAKE_BASELINE = {
    "model_config": {"segmentation_size": 10000, "depth": 4},
    "train_config": {"batch_size": 1, "epochs": 10, "lr": 1e-4,
                     "optimizer_type": "adamw", "weight_decay": 1e-5,
                     "device": "cuda"},
    "loss_config": {"loss_type": "focal", "alpha": 0.5, "gamma": 2.0,
                    "reduction": "mean"},
}


def _make_input(tmp_path, *, time_budget_minutes=30.0, data_dir=None,
                is_trial=False):
    return ProposalInput(
        interpretation=FAKE_INTERPRETATION,
        existing_model_types=["punet"],
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="r1"),
        ),
        time_budget_minutes=time_budget_minutes,
        data_dir=data_dir,
        is_trial=is_trial,
    )


def _make_output(model_name="attn_unet", baseline=None):
    return ProposalOutput.model_validate({
        "model_name": model_name,
        "model_description": "A new model.",
        "mathematical_definition": "Stuff happens.",
        "motivation": "Because.",
        "expert_advice": {},
        "baseline_config": baseline if baseline is not None else FAKE_BASELINE,
    })


# ---------------------------------------------------------------------------
# _apply_time_gate — direct unit tests
# ---------------------------------------------------------------------------

class TestApplyTimeGate:

    def test_feasible_leaves_time_risk_none(self, tmp_path):
        out = _make_output()
        inp = _make_input(tmp_path, time_budget_minutes=30.0)
        with patch(
            "agent.skills.evaluate_time_skill.wrapper.run_skill",
            return_value={
                "status": "success",
                "feasible": True,
                "verdict": "FITS",
                "suggestion": "",
                "estimated_minutes": 12.0,
                "limit_minutes": 30.0,
            },
        ):
            _apply_time_gate(out, inp)
        assert out.time_risk is None

    def test_infeasible_sets_time_risk_to_suggestion(self, tmp_path):
        out = _make_output()
        inp = _make_input(tmp_path, time_budget_minutes=30.0)
        suggestion = "Reduce model depth/width — per-step cost is dominant."
        with patch(
            "agent.skills.evaluate_time_skill.wrapper.run_skill",
            return_value={
                "status": "success",
                "feasible": False,
                "verdict": "OVER BUDGET",
                "suggestion": suggestion,
                "estimated_minutes": 90.0,
                "limit_minutes": 30.0,
            },
        ):
            _apply_time_gate(out, inp)
        assert out.time_risk == suggestion

    def test_skill_error_leaves_time_risk_none(self, tmp_path):
        out = _make_output()
        inp = _make_input(tmp_path, time_budget_minutes=30.0)
        with patch(
            "agent.skills.evaluate_time_skill.wrapper.run_skill",
            return_value={
                "status": "error",
                "message": "model_type 'attn_unet' not in MODEL_REGISTRY",
            },
        ):
            _apply_time_gate(out, inp)
        assert out.time_risk is None

    def test_none_budget_skips_skill(self, tmp_path):
        out = _make_output()
        inp = _make_input(tmp_path, time_budget_minutes=None)
        with patch(
            "agent.skills.evaluate_time_skill.wrapper.run_skill"
        ) as mock_skill:
            _apply_time_gate(out, inp)
        mock_skill.assert_not_called()
        assert out.time_risk is None

    def test_skill_receives_baseline_config(self, tmp_path):
        out = _make_output()
        inp = _make_input(tmp_path, time_budget_minutes=30.0)
        with patch(
            "agent.skills.evaluate_time_skill.wrapper.run_skill",
            return_value={
                "status": "success", "feasible": True,
                "verdict": "ok", "suggestion": "",
            },
        ) as mock_skill:
            _apply_time_gate(out, inp)
        kwargs = mock_skill.call_args.kwargs
        assert kwargs["model_type"] == "attn_unet"
        assert kwargs["model_config"] == FAKE_BASELINE["model_config"]
        assert kwargs["train_config"] == FAKE_BASELINE["train_config"]
        assert kwargs["loss_config"] == FAKE_BASELINE["loss_config"]
        assert kwargs["time_budget_minutes"] == 30.0

    def test_skill_receives_data_dir_when_set(self, tmp_path):
        out = _make_output()
        inp = _make_input(tmp_path, time_budget_minutes=30.0,
                          data_dir="/mnt/tidmad")
        with patch(
            "agent.skills.evaluate_time_skill.wrapper.run_skill",
            return_value={"status": "success", "feasible": True,
                          "verdict": "ok", "suggestion": ""},
        ) as mock_skill:
            _apply_time_gate(out, inp)
        assert mock_skill.call_args.kwargs["data_dir"] == "/mnt/tidmad"

    def test_sample_set_built_from_trial_mirror(self, tmp_path):
        """is_trial=False → build_sample_set returns a single-file SampleSet
        keyed on file_index=6 (the legacy default)."""
        out = _make_output()
        inp = _make_input(tmp_path, time_budget_minutes=30.0, is_trial=False)
        with patch(
            "agent.skills.evaluate_time_skill.wrapper.run_skill",
            return_value={"status": "success", "feasible": True,
                          "verdict": "ok", "suggestion": ""},
        ) as mock_skill:
            _apply_time_gate(out, inp)
        sample_set = mock_skill.call_args.kwargs["sample_set"]
        # is_trial=False → file_index=6, all 200 segments
        assert sample_set == {6: list(range(200))}

    def test_infeasible_with_empty_suggestion_falls_back_to_verdict(self, tmp_path):
        """If the skill returns feasible=False but no suggestion text, the
        verdict text is the next-best signal — still better than empty."""
        out = _make_output()
        inp = _make_input(tmp_path, time_budget_minutes=30.0)
        with patch(
            "agent.skills.evaluate_time_skill.wrapper.run_skill",
            return_value={
                "status": "success",
                "feasible": False,
                "verdict": "OVER BUDGET — Est 90 min vs 30 min.",
                "suggestion": "",
            },
        ):
            _apply_time_gate(out, inp)
        assert out.time_risk == "OVER BUDGET — Est 90 min vs 30 min."


# ---------------------------------------------------------------------------
# Full-agent integration — gate is wired into run()
# ---------------------------------------------------------------------------

FAKE_REASONING = "Reasoning text..."
FAKE_COMMIT_RESPONSE = {
    "model_name": "attn_unet",
    "model_description": "A U-Net variant with attention.",
    "mathematical_definition": "1. Embedding 2. Encoder 3. Bottleneck 4. Decoder.",
    "motivation": "Address receptive field bottleneck.",
    "expert_advice": {},
    "baseline_config": FAKE_BASELINE,
}


@pytest.fixture
def agent():
    with patch("nodes.ml_model_proposal_agent.LLMBridge") as MockBridge:
        MockBridge.return_value.generate_text.return_value = FAKE_REASONING
        MockBridge.return_value.generate.return_value = FAKE_COMMIT_RESPONSE
        a = MLModelProposalAgent(provider="gemini", model_id="test")
        a.bridge = MockBridge.return_value
        yield a


class TestGateWiredIntoRun:

    def test_run_calls_gate_and_persists_time_risk(self, agent, tmp_path):
        inp = _make_input(tmp_path, time_budget_minutes=30.0)
        with patch(
            "agent.skills.evaluate_time_skill.wrapper.run_skill",
            return_value={
                "status": "success", "feasible": False,
                "verdict": "OVER", "suggestion": "Reduce depth.",
            },
        ):
            output = agent.run(inp)
        assert output.time_risk == "Reduce depth."
        # Persisted JSON must round-trip with time_risk preserved
        import json
        data = json.loads(
            (tmp_path / "proposal_r1.json").read_text()
        )
        assert data["time_risk"] == "Reduce depth."

    def test_run_with_no_budget_leaves_time_risk_none(self, agent, tmp_path):
        inp = _make_input(tmp_path, time_budget_minutes=None)
        with patch(
            "agent.skills.evaluate_time_skill.wrapper.run_skill"
        ) as mock_skill:
            output = agent.run(inp)
        mock_skill.assert_not_called()
        assert output.time_risk is None

    def test_run_with_skill_error_does_not_crash(self, agent, tmp_path):
        """The most common production case: skill errors because the proposed
        model_type isn't in MODEL_REGISTRY yet. Proposer must continue and
        emit a valid ProposalOutput with time_risk=None."""
        inp = _make_input(tmp_path, time_budget_minutes=30.0)
        with patch(
            "agent.skills.evaluate_time_skill.wrapper.run_skill",
            return_value={"status": "error", "message": "no such model"},
        ):
            output = agent.run(inp)
        assert output.model_name == "attn_unet"
        assert output.time_risk is None
