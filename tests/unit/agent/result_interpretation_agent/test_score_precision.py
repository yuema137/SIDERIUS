"""Issue737: prompt text must distinguish adjacent representable scores."""

import math
import re

import pytest

from agent.prompt_templates.interpretation.rendering import _build_per_model_prompt
from agent.prompt_templates.tuner.rendering import render_training_dynamics_line
from agent.prompts import _format_active_resource_budgets_block
from agent.schemas.interpretation import ModelRunSummary
from agent.schemas.training_diagnosis import TrainingDiagnosis


@pytest.mark.parametrize("value", [1.0, -1.0, 1e-12, -1e-12, 1e100, 5e-324])
def test_adjacent_floats_survive_both_actual_prompt_channels(value):
    """Any fixed precision that merges the witnesses breaks this round-trip check."""
    neighbor = math.nextafter(value, math.inf)
    summary = ModelRunSummary(
        model_type="fixture",
        run_name="precision",
        status="completed",
        completed_rounds=2,
        round_scores=[value, neighbor],
    )
    text = _build_per_model_prompt(summary, None)
    tokens = re.findall(r"Round \d+: score=(\S+)", text)
    assert len(tokens) == 2
    assert tokens[0] != tokens[1]
    assert [float(token) for token in tokens] == [value, neighbor]

    diagnosis = TrainingDiagnosis(
        state="ok",
        validation_state="present",
        comparability="established",
        train_first=value,
        train_last=neighbor,
        validation_first=value,
        validation_last=neighbor,
        train_validation_gap_final=neighbor,
        final_vs_best_validation_degradation=abs(value),
    )
    line = render_training_dynamics_line(diagnosis)
    for name in ("train", "val"):
        match = re.search(rf"{name} (\S+)->(\S+) ", line)
        assert match is not None
        assert match[1] != match[2]
        assert [float(match[1]), float(match[2])] == [value, neighbor]
    gap = re.search(r"gap (\S+) \(comparable\)", line)
    assert gap is not None and float(gap[1]) == neighbor
    drift = re.search(r", \+(\S+) after best", line)
    assert drift is not None and float(drift[1]) == abs(value)


def test_zero_sign_and_missing_score_are_preserved_in_trajectory():
    summary = ModelRunSummary(
        model_type="fixture",
        run_name="precision",
        status="completed",
        completed_rounds=3,
        round_scores=[0.0, -0.0, None],
    )
    text = _build_per_model_prompt(summary, None)
    assert re.findall(r"Round \d+: score=(\S+)", text) == ["0.0", "-0.0", "skipped"]


@pytest.mark.parametrize("gap, token", [(0.0, "+0.0"), (-0.0, "-0.0")])
def test_diagnostic_gap_preserves_zero_sign(gap, token):
    diagnosis = TrainingDiagnosis(
        state="ok",
        validation_state="absent",
        comparability="established",
        train_validation_gap_final=gap,
    )
    assert f"gap {token} (comparable)" in render_training_dynamics_line(diagnosis)


def test_resource_context_preserves_adjacent_budget_and_estimate():
    text = _format_active_resource_budgets_block(
        trial_time_budget_minutes=1.0,
        formal_time_budget_minutes=1.0000000000000002,
        last_time_estimate_minutes=1.0000000000000004,
    )
    assert "Trial: VRAM not supplied; time 1.0 min" in text
    assert "Formal: VRAM not supplied; time 1.0000000000000002 min" in text
    assert "Time estimate: 1.0000000000000004 min" in text
