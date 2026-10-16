"""Issue734: small scientific objectives must survive every diagnostic channel."""

import pytest

from agent.prompt_templates.interpretation.rendering import render_interpretation_diagnosis_lines
from agent.prompt_templates.tuner.rendering import (
    render_planner_dynamics_block,
    render_reflector_dynamics_block,
)
from tests.helpers.tuner_prompt_fixtures import DIAGNOSIS


@pytest.mark.parametrize(
    ("first", "last", "gap", "expected", "signed_gap"),
    [
        (0.016548, 0.006254, 0.0000895854, "0.016548->0.006254", "+8.95854e-05"),
        (1.23456e-12, 9.87654e-14, -2.34567e-14, "1.23456e-12->9.87654e-14", "-2.34567e-14"),
        (1.23456e12, 9.87654e10, 2.34567e9, "1.23456e+12->9.87654e+10", "+2.34567e+09"),
        (-0.0000123456, -0.0000234567, 0.0, "-1.23456e-05->-2.34567e-05", "+0"),
        (0.0, 0.0, 0.0, "0->0", "+0"),
    ],
)
def test_precision_reaches_planner_reflector_and_interpreter(
    first, last, gap, expected, signed_gap
):
    """Fixed decimals or a bypassed shared renderer loses these literal witnesses."""
    diagnosis = DIAGNOSIS.model_copy(
        update={
            "train_first": first,
            "train_last": last,
            "validation_first": first,
            "validation_last": last,
            "train_validation_gap_final": gap,
            "final_vs_best_validation_degradation": 0.0000895854,
        }
    )
    planner = render_planner_dynamics_block(
        [{"exp_id": "precision", "training_diagnosis": diagnosis.model_dump(mode="json")}]
    )
    reflector = render_reflector_dynamics_block(diagnosis)
    interpreter = "\n".join(render_interpretation_diagnosis_lines(diagnosis, diagnosis))
    for text in (planner, reflector, interpreter):
        assert f"train {expected}" in text
        assert f"val {expected}" in text
        assert f"gap {signed_gap} (comparable)" in text
        assert "+8.95854e-05 after best" in text
