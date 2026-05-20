"""Tests for the proposer-side baseline_config validators on ProposalOutput.

See docs/improving_validation_awareness.md Phase A.1.

Currently covers:
  - segmentation_size divisor rule
"""

import pytest
from pydantic import ValidationError

from agent.schemas.hyperparam_tuning import ExpertAdvice
from agent.schemas.proposal import ProposalOutput
from execute_tools.dataset_config import TIDMAD


@pytest.fixture
def expert_advice():
    return ExpertAdvice(
        focus_areas=["start with depth=2"],
        constraints=["VRAM < 8 GB"],
        known_failures=["large batch_size"],
        suggested_directions=["try focal gamma=2"],
        rationale="x",
    )


def _make_output(expert_advice, **baseline_overrides):
    """Construct a minimal valid ProposalOutput with the given baseline_config."""
    base = {
        "model_config": baseline_overrides.get("model_config", {}),
        "train_config": {"lr": 1e-4, "epochs": 1},
        "loss_config": {"loss_type": "focal"},
    }
    if "model_config" not in baseline_overrides and not base["model_config"]:
        # caller didn't supply model_config — drop it entirely to test absence
        base.pop("model_config")
    return ProposalOutput(
        model_name="x",
        model_description="x",
        mathematical_definition="x",
        motivation="x",
        expert_advice=expert_advice,
        baseline_config=base,
    )


# ---- segmentation_size divisor rule ----


def test_valid_segmentation_size_passes(expert_advice):
    """16000 is a valid divisor of 10_000_000."""
    out = _make_output(expert_advice, model_config={"segmentation_size": 16000})
    assert out.baseline_config["model_config"]["segmentation_size"] == 16000


def test_invalid_power_of_two_segmentation_raises(expert_advice):
    """16384 is the value the LLM kept proposing. Must be rejected."""
    with pytest.raises(ValidationError) as exc:
        _make_output(expert_advice, model_config={"segmentation_size": 16384})
    msg = str(exc.value)
    assert "segmentation_size" in msg
    assert "16384" in msg
    assert "10000000" in msg
    # Error message must list valid divisors so the LLM has actionable feedback.
    assert "Valid segmentation_size values" in msg
    assert "16000" in msg


def test_missing_segmentation_size_no_op(expert_advice):
    """Not all architectures have segmentation_size — validator must skip silently."""
    out = _make_output(expert_advice, model_config={"depth": 4})
    assert "segmentation_size" not in out.baseline_config["model_config"]


def test_missing_model_config_no_op(expert_advice):
    """baseline_config without model_config key — validator must skip."""
    out = ProposalOutput(
        model_name="x",
        model_description="x",
        mathematical_definition="x",
        motivation="x",
        expert_advice=expert_advice,
        baseline_config={
            "train_config": {"lr": 1e-4, "epochs": 1},
            "loss_config": {"loss_type": "focal"},
        },
    )
    assert "model_config" not in out.baseline_config


def test_empty_baseline_config_no_op(expert_advice):
    """Backwards compatibility with existing tests that pass baseline_config={}."""
    out = ProposalOutput(
        model_name="x",
        model_description="x",
        mathematical_definition="x",
        motivation="x",
        expert_advice=expert_advice,
        baseline_config={},
    )
    assert out.baseline_config == {}


def test_negative_segmentation_size_raises(expert_advice):
    with pytest.raises(ValidationError) as exc:
        _make_output(expert_advice, model_config={"segmentation_size": -100})
    assert "segmentation_size" in str(exc.value)


def test_zero_segmentation_size_raises(expert_advice):
    with pytest.raises(ValidationError) as exc:
        _make_output(expert_advice, model_config={"segmentation_size": 0})
    assert "segmentation_size" in str(exc.value)


def test_non_int_segmentation_size_raises(expert_advice):
    with pytest.raises(ValidationError) as exc:
        _make_output(expert_advice, model_config={"segmentation_size": "16000"})
    assert "segmentation_size" in str(exc.value)


def test_other_valid_divisors_pass(expert_advice):
    """A handful of valid divisors of 10_000_000 should all pass."""
    for seg in (100, 1000, 1250, 16000, 50000):
        assert TIDMAD.psd_segment_length % seg == 0  # guard against test rot
        out = _make_output(expert_advice, model_config={"segmentation_size": seg})
        assert out.baseline_config["model_config"]["segmentation_size"] == seg
