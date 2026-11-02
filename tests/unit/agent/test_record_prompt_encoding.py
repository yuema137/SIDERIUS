"""Storage metadata never becomes model-facing history or outcome text."""

import pytest

from agent.prompts import get_planner_user_prompt, get_reflector_user_prompt
from core.record_encoding import METADATA, encoded_record


@pytest.mark.parametrize("score", [0.5, None, float("-inf"), float("inf"), float("nan")])
@pytest.mark.parametrize("count", [1, 20])
def test_planner_raw_and_decoded_history_render_identical_bytes(score, count):
    history = [
        {"exp_id": str(i), "status": "success", "denoising_score": score} for i in range(count)
    ]
    expected = get_planner_user_prompt(history)
    actual = get_planner_user_prompt([encoded_record(row) for row in history])
    assert actual == expected
    assert METADATA not in actual
    assert '"-Infinity"' not in actual
    assert '"Infinity"' not in actual
    assert '"NaN"' not in actual


@pytest.mark.parametrize("score", [0.5, None, float("-inf"), float("inf"), float("nan")])
def test_reflector_raw_and_decoded_outcomes_render_identical_bytes(score):
    result = {"denoising_score": score}
    expected = get_reflector_user_prompt("trial", "hypothesis", result)
    actual = get_reflector_user_prompt("trial", "hypothesis", encoded_record(result))
    assert actual == expected
    assert METADATA not in actual
