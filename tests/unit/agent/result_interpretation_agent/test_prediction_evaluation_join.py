"""The prediction evaluator and the discovery renderer, joined.

THE DEFECT (found 2026-08-02 by a test audit, verified against production).

`evaluate_prediction` reads `predicted_value` from its INPUT to compute
boldness, then returned a dict that did not contain it:

    {metric, actual_value, current_sota, delta_from_sota,
     outcome, boldness, information_gain}

`generate_discoveries` receives only that dict -- it has no access to the
original prediction -- and renders:

    predicted = prediction_eval.get("predicted_value")
    predicted_str = f"{predicted:.4f}" if predicted is not None else "N/A"

so the guard was always falsy and EVERY discovery sentence in production
read "(predicted N/A)". The proposal agent's falsifiable prediction never
reached the next iteration's agent-facing text.

WHY NO TEST CAUGHT IT. All eight `TestGenerateDiscoveries` cases hand-build
`prediction_eval` with `"predicted_value": 6.0` -- a shape the real producer
never emits. Both sides green, interface broken.

That is the third instance of this exact shape: the A5 field-drop, the
compressed-summary takeaway (PR #157, same module), and this one. So every
test here runs the REAL producer and feeds its REAL output to the REAL
consumer. No hand-built evaluation dicts.
"""

from __future__ import annotations

import json

import pytest

from agent.schemas.interpretation import InterpretationOutput
from execute_tools.metric_order import MetricOrder
from nodes.interpretation_helpers import generate_discoveries

# Step 09a C1b: `evaluate_prediction` moved to the node's private `prediction`
# module (its single definition site); `generate_discoveries` stayed in the
# helpers module. The JOIN this file pins spans both, which is the point.
from nodes.result_interpretation_agent.prediction import evaluate_prediction
from tests.helpers.metric_fixtures import shipped_spec

#: Step 09a C3 — the migrated ordering consumers take the run's MetricOrder as a
#: REQUIRED keyword. The shipped TIDMAD spec is `higher`, so every expectation in
#: this file is unchanged; the direction is now stated instead of assumed.
_STEP09A_ORDER = MetricOrder(shipped_spec())

#: Step 09a C4 — a NEW prediction's default metric is the run's BOUND id,
#: never the literal `denoising_score` (one task's name, hardcoded).
_BOUND_METRIC_ID = shipped_spec().id

#: The SOTA the proposal was written against, and the value it predicted.
SOTA = 5.0
PREDICTED = 6.0

#: Actual scores that drive each outcome branch of `evaluate_prediction`,
#: with the label the renderer must emit. Derived from the real thresholds:
#: confirmed > 5.0; partial >= 5.0 * (1 - 0.05) = 4.75; refuted below that.
OUTCOMES = [
    ("confirmed", 5.5, "CONFIRMED"),
    ("partial", 4.8, "PARTIAL"),
    ("refuted", 4.0, "REFUTED"),
]


def _prediction(predicted_value: float | None = PREDICTED) -> dict:
    return {
        "metric": "denoising_score",
        "predicted_value": predicted_value,
        "current_value": SOTA,
    }


def _evaluate(actual: float, predicted_value: float | None = PREDICTED) -> dict:
    """Run the real producer exactly as production does."""
    return evaluate_prediction(
        _prediction(predicted_value),
        {"best_denoising_score": actual},
        current_sota=SOTA,
        order=_STEP09A_ORDER,
        bound_metric_id=_BOUND_METRIC_ID,
    )


def _discover(evaluation: dict, best_score: float | None) -> list:
    """Drive the real consumer over real producer output."""
    return generate_discoveries(
        prediction_eval=evaluation,
        model_type="punet",
        best_score=best_score,
        inherited_components=[],
        proposed_vocab_links=[],
        order=_STEP09A_ORDER,
    )


class TestThePredictedValueReachesTheDiscovery:
    """The join. Each case runs producer -> consumer end to end."""

    @pytest.mark.parametrize("outcome,actual,label", OUTCOMES, ids=[o[0] for o in OUTCOMES])
    def test_the_prediction_is_rendered(self, outcome, actual, label):
        evaluation = _evaluate(actual)
        assert evaluation["outcome"] == outcome, "fixture no longer drives this branch"

        description = _discover(evaluation, actual)[0].description

        assert description.startswith(label)
        assert f"(predicted {PREDICTED:.4f})" in description, (
            f"{outcome}: the proposal predicted {PREDICTED} and the discovery "
            f"sentence did not say so -- got {description!r}"
        )
        assert "predicted N/A" not in description

    def test_the_placeholder_still_appears_when_nothing_was_predicted(self):
        """The negative control. Without it, a renderer that hardcoded a
        number would pass every case above.

        A FalsifiablePrediction may legitimately omit `predicted_value`;
        "N/A" is correct there and only there.
        """
        evaluation = _evaluate(5.5, predicted_value=None)
        assert evaluation["predicted_value"] is None
        assert "(predicted N/A)" in _discover(evaluation, 5.5)[0].description

    def test_the_actual_value_travels_the_same_path(self):
        """The other half of the sentence. If the consumer read the wrong
        name for one field it could for the other."""
        description = _discover(_evaluate(5.5), 5.5)[0].description
        assert "denoising_score=5.5000" in description

    def test_the_degenerate_branch_also_carries_it(self):
        """`evaluate_prediction` has a second, earlier return for an
        uncomputable metric. It is a separate dict literal, so it can drift
        from the main one independently -- which is how this defect would
        come back at half strength.
        """
        evaluation = evaluate_prediction(
            _prediction(),
            {},
            current_sota=None,
            order=_STEP09A_ORDER,
            bound_metric_id=_BOUND_METRIC_ID,
        )
        assert "notes" in evaluation, "fixture no longer reaches the degenerate branch"
        assert evaluation["predicted_value"] == PREDICTED


class TestTheProducerContractTheConsumerRelieson:
    """Pins the field name across the seam, so a rename on either side fails
    here rather than silently rendering the placeholder."""

    @pytest.mark.parametrize("actual", [5.5, 4.0])
    def test_the_producer_emits_the_name_the_consumer_reads(self, actual):
        assert "predicted_value" in _evaluate(actual)

    def test_the_outcome_does_not_depend_on_the_predicted_value(self):
        """The evaluator is deliberately SOTA-based: predicting exact scores
        is unreliable, so a wildly wrong prediction must not change the
        verdict. Echoing the value back must not have made it load-bearing.
        """
        for predicted in (PREDICTED, 0.0, 99.0, None):
            evaluation = _evaluate(5.5, predicted_value=predicted)
            assert evaluation["outcome"] == "confirmed"
            assert evaluation["delta_from_sota"] == 0.5


class TestItSurvivesPersistence:
    """The evaluation is written to the output record and read back by the
    next iteration. A field that renders but does not persist would fail
    only on a resumed chain."""

    def test_it_round_trips_through_the_output_schema(self):
        evaluation = _evaluate(5.5)
        output = InterpretationOutput(
            model_types=["punet"],
            model_descriptions={"punet": "d"},
            total_experiments=1,
            key_findings=["f"],
            bottlenecks=["b"],
            take_home_message="m",
            prediction_evaluation=evaluation,
        )
        restored = InterpretationOutput.model_validate(json.loads(output.model_dump_json()))
        assert restored.prediction_evaluation is not None
        assert restored.prediction_evaluation["predicted_value"] == PREDICTED

    def test_the_documented_key_list_matches_what_is_emitted(self):
        """The field description enumerates the contained keys; a consumer
        author reads that list instead of the producer. It omitted
        `predicted_value` for as long as the producer did.

        Scoped to the enumeration and compared as a SET. A substring search
        over the whole description passes on any prose that happens to
        mention the name -- this test did exactly that until the mutation
        run caught it, matching a later sentence of its own docstring.
        """
        described = InterpretationOutput.model_fields["prediction_evaluation"].description
        assert described is not None

        # "... Contains: metric, predicted_value, ..., information_gain. ..."
        enumeration = described.split("Contains:", 1)[1].split(". ", 1)[0]
        documented = {part.split()[0].strip(",") for part in enumeration.split(",")}

        assert documented == set(_evaluate(5.5)), (
            "the documented key list and the emitted keys have diverged: "
            f"documented-only={documented - set(_evaluate(5.5))}, "
            f"emitted-only={set(_evaluate(5.5)) - documented}"
        )
