"""F-SCAND-1 — the forbidden aggregation is refused, not computed.

**The defect.** ``prediction.py`` resolved ``mean(file_vector[N:M])`` by
arithmetic-meaning that slice. The values reaching it are per-file
**log_5.27** scores, so a slice mean is a *"mean of per-file log scores"* —
the FIRST form the aggregation standard forbids by name, for **Jensen's
inequality gap**: the mean of logs is not the log of the mean, so the result
is not the score of anything.

**Trace the value, not the producer.** ``score_vector`` returns LINEAR
per-file means, and stopping there is how this docstring was first written
the other way round. They do not arrive in that form: the tuner converts via
``file_vector_to_log_space`` before building the score table, the table's
``model`` field is declared ``log_{5.27}``, and the SOLE caller of
``evaluate_prediction`` synthesizes this vector from exactly that field.

A band slice compounds a SECOND violation — *"mean of per-band linear
means"*, the third forbidden form — because the campaign's bands are
**4/6/5/5** and averaging a 4-file band against a 6-file band gives each file
in the smaller band 1.5x the influence.

**Why removing the prompt examples was rejected as the fix.** The grammar has
never fired in 1,819 historical records — but four historical predictions
asked for a file-subset mean *in prose*, and were saved only because the
grammar was too obscure to find. Removing the examples makes it MORE obscure.
That is protection by obscurity, and it gets weaker exactly as models get
better at finding the affordance. A refusal is what survives a stronger model.

**No new semantics.** A refused prediction returns ``None``, which lands it in
the existing ``unevaluated`` pool — the frozen class for a prediction that
cannot be computed, counted in NO pool (09a).
"""

from __future__ import annotations

import pytest

from execute_tools.metric_order import MetricOrder
from nodes.result_interpretation_agent.prediction import evaluate_prediction
from tests.helpers.metric_fixtures import shipped_spec

HIGHER = MetricOrder(shipped_spec())
BOUND_ID = "tidmad_denoising_score"

#: Stand-ins for per-file log scores. Ten entries so a slice can mirror the
#: campaign's non-uniform 4/6/5/5 banding, which is the compounding second
#: violation on top of the Jensen gap.
FILE_VECTOR = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5]


def _resolve(metric: str, per_sample=FILE_VECTOR):
    """Drive the PUBLIC entry point, the way production does.

    Returns ``(actual_value, metric_resolution)`` so each test reads as the
    two facts it cares about.
    """
    result = evaluate_prediction(
        {"current_value": 1.5, "predicted_value": None, "metric": metric},
        {"best_denoising_score": -2.43, "best_file_vector": per_sample},
        partial_margin=0.05,
        order=HIGHER,
        bound_metric_id=BOUND_ID,
    )
    return result["actual_value"], result["metric_resolution"]


class TestTheSliceMeanIsRefused:
    @pytest.mark.parametrize(
        "metric",
        ["mean(file_vector[0:5])", "mean(file_vector[4:10])", "mean(file_vector[0:4])"],
    )
    def test_no_value_is_produced(self, metric):
        """RED before the fix: this returned the arithmetic mean."""
        value, resolution = _resolve(metric)
        assert value is None, "a refused aggregation must not yield a number"
        assert resolution == "refused_forbidden_aggregation"

    def test_the_resolution_says_refused_rather_than_unrecognized(self):
        """The grammar IS recognized — that is why it can be refused precisely.

        Reporting ``unrecognized`` would misattribute a deliberate refusal to
        a parse failure, and would send whoever reads the record looking for a
        typo in a prediction that was well-formed.
        """
        _value, resolution = _resolve("mean(file_vector[0:5])")
        assert resolution != "unrecognized"
        assert "refused" in resolution


class TestTheAdjacentFormsStillWork:
    """The refusal must be narrow: only the slice MEAN is forbidden."""

    def test_a_single_index_still_resolves(self):
        value, resolution = _resolve("file_vector[2]")
        assert value == 2.0
        assert resolution == "per_sample_index"

    def test_the_bound_scalar_still_resolves(self):
        value, resolution = _resolve(BOUND_ID)
        assert value == -2.43
        assert resolution == "bound_id"

    def test_a_scalar_only_task_is_still_capability_not_refusal(self):
        """Pets and DAVIS have no per-sample evidence at all.

        That is a missing capability, and it must stay distinguishable from a
        refusal — the two have different causes and different remedies.
        """
        _value, resolution = _resolve("file_vector[2]", per_sample=None)
        assert resolution == "per_sample_unavailable"


def test_no_alternative_aggregation_was_invented():
    """SCOPE PIN — a deliberate omission, pinned so implementing it fails here.

    The obvious "improvement" is to compute a *correct* band score here —
    weighting by each band's file count, or re-aggregating in linear space.
    That is rejected: the metric authority is frozen, and a second aggregation
    living in the interpreter would be a second scoring authority answering
    the same question as ``scoring_utils``.

    If a band breakdown is wanted, ``score_vector`` on a scoped ``SampleSet``
    is the supported route. This asserts the refusal stayed a refusal — if
    someone makes it return a number, however defensible the arithmetic, this
    fails and says why it was left out.
    """
    for metric in ("mean(file_vector[0:4])", "mean(file_vector[4:10])"):
        value, _resolution = _resolve(metric)
        assert value is None, (
            "the interpreter must not compute ANY band aggregation — "
            "the metric authority is frozen and lives in scoring_utils"
        )
