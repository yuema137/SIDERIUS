"""An authored cold-start reference must not become observed SOTA evidence."""

import pytest

from agent.schemas.proposal import FalsifiablePrediction
from execute_tools.evaluation_metric import MetricSpec, PresenceScoreabilityContract
from execute_tools.metric_order import MetricOrder
from nodes.interpretation_helpers import generate_discoveries
from nodes.result_interpretation_agent.prediction import read_observed_prediction_reference


def test_cold_start_prediction_can_explicitly_lack_an_observed_baseline():
    prediction = FalsifiablePrediction(
        metric="synthetic_quality",
        current_value=None,
        predicted_value=2.0,
        threshold_for_refutation=0.5,
        rationale="An absolute hypothesis before any candidate has been measured.",
    )
    assert prediction.current_value is None
    assert prediction.boldness is None


@pytest.mark.parametrize(
    "direction,observed,authored", [("higher", -10.0, 1.0), ("lower", 5.0, 0.1)]
)
@pytest.mark.parametrize("has_observed_reference", [False, True])
def test_unevaluated_prediction_does_not_supply_a_score_comparison_reference(
    direction, observed, authored, has_observed_reference
):
    order = MetricOrder(
        MetricSpec(
            id="synthetic_quality",
            direction=direction,
            aggregation="mean",
            scoreability=PresenceScoreabilityContract(),
        )
    )
    discoveries = generate_discoveries(
        prediction_eval={
            "outcome": "unevaluated",
            "metric_resolution": "unrecognized",
            "actual_value": None,
            "current_sota": authored,
        },
        model_type="synthetic_model",
        best_score=observed,
        inherited_components=[],
        proposed_vocab_links=[],
        overall_best_score=observed if has_observed_reference else None,
        order=order,
    )
    comparisons = [d for d in discoveries if d.name.endswith("_vs_sota")]
    if has_observed_reference:
        assert len(comparisons) == 1
        assert f"SOTA ({observed:.4f})" in comparisons[0].description
    else:
        assert comparisons == []


def test_legacy_authored_reference_is_not_promoted_to_observation():
    assert (
        read_observed_prediction_reference(
            {"falsifiable_prediction": {"current_value": 1.0}},
            metric_id="synthetic_quality",
            direction="higher",
        )
        is None
    )


def test_explicit_observation_retains_its_metric_identity():
    proposal = {
        "observed_prediction_reference": {
            "metric_id": "synthetic_quality",
            "direction": "lower",
            "value": 3.0,
            "source": "interpretation_best_valid",
        }
    }
    assert (
        read_observed_prediction_reference(
            proposal, metric_id="synthetic_quality", direction="lower"
        )
        == 3.0
    )
    with pytest.raises(ValueError, match="bound metric identity"):
        read_observed_prediction_reference(
            proposal, metric_id="synthetic_quality", direction="higher"
        )
