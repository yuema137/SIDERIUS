"""Step 12 / PR-12d — D4c: the pack-local terminal metrics and the identity check.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12d_contrast_subprocess_closure.md`` §M `D4c`, rulings A2-b and A3.

A metric that is DECLARED but not implemented is not L4. Before D4c, `psnr`
and `mae` both resolved to ``GlobalMseMetric`` and `macro_f1` to
``AccuracyMetric``, and composition said nothing — the only identity check
compared the declaration to itself (**F-12d-3**). A terminal report could read
``psnr / HIGHER`` while mean squared error executed.

Every expectation below is **hand-computed and written as a literal**. Reading
a value back from the implementation under test would pass for any arithmetic,
which is the self-referential shape CLAUDE.md forbids; the arithmetic is
restated here in the docstrings so a reviewer can check it without running
anything.
"""

from __future__ import annotations

import json
import math
import pathlib
from typing import ClassVar

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


def _spec(declaration_rel: str):
    from execute_tools.evaluation_metric import metric_spec_from_declaration

    return metric_spec_from_declaration(
        json.loads((REPO_ROOT / declaration_rel).read_text(encoding="utf-8"))
    )


def _declaration_spec(metric_id: str, direction: str):
    """A spec built the way a pack builds one — through the declaration path.

    `MetricSpec.scoreability` is an executable contract, not a mapping, so
    constructing one by hand from a dict does not work and should not: the
    declaration path is the only route production uses.
    """
    from execute_tools.evaluation_metric import metric_spec_from_declaration

    return metric_spec_from_declaration(
        {
            "id": metric_id,
            "direction": direction,
            "aggregation": f"{metric_id}_test_fixture",
            "references": [],
            "scoreability": {"contract_id": "deliverable_presence"},
            "transform": None,
            "transform_params": {},
        }
    )


class _Row:
    def __init__(self, image_id, class_index):
        self.image_id = image_id
        self.class_index = class_index


class _Scope:
    def __init__(self, rows):
        self.rows = rows


# ======================================================================
# Pets — macro F1
# ======================================================================


class TestPetsMacroF1:
    """Hand-computed against a 4-sample, 3-class-in-play fixture."""

    #: truth / prediction, chosen so precision and recall DIFFER for class 0 —
    #: a fixture where they coincide cannot tell F1 from accuracy.
    #:
    #:   id  truth  pred
    #:   a     0      0     <- TP for 0
    #:   b     0      1     <- FN for 0, FP for 1
    #:   c     1      1     <- TP for 1
    #:   d     2      0     <- FN for 2, FP for 0
    #:
    #: class 0: TP=1 predicted=2 actual=2 -> P=1/2 R=1/2 F1=0.5
    #: class 1: TP=1 predicted=2 actual=1 -> P=1/2 R=1   F1=2*(.5*1)/(1.5)=2/3
    #: class 2: TP=0 predicted=0 actual=1 -> undefined   F1=0
    #: all other 34 classes: no support, no predictions  F1=0
    #: macro = (0.5 + 2/3 + 0 + 34*0) / 37
    TRUTH: ClassVar[dict[str, int]] = {"a": 0, "b": 0, "c": 1, "d": 2}
    PREDICTIONS: ClassVar[dict[str, int]] = {"a": 0, "b": 1, "c": 1, "d": 0}
    EXPECTED = (0.5 + 2.0 / 3.0) / 37.0

    def _metric(self):
        from examples.oxford_iiit_pet.plugins._pets_metrics import PetsMacroF1Metric

        return PetsMacroF1Metric(_spec("examples/oxford_iiit_pet/declared/metric_macro_f1.json"))

    def test_it_computes_the_hand_calculated_macro_f1(self):
        scope = _Scope([_Row(k, v) for k, v in self.TRUTH.items()])
        scalar, per_sample, references = self._metric()._compute(
            {0: "deliverable"},
            evaluation_payload=self.PREDICTIONS,
            task_scope=scope,
            data_dir=None,
        )
        assert scalar == pytest.approx(self.EXPECTED, abs=1e-12)
        assert scalar == pytest.approx(0.031531531531531535, abs=1e-12)
        assert per_sample is None
        assert references == ()

    def test_it_is_NOT_accuracy(self):
        """The reason macro-F1 is worth declaring beside accuracy.

        The same fixture scores 0.5 accuracy (2 of 4 correct). If this metric
        were quietly bound to ``AccuracyMetric`` — which is exactly what the
        shipped declaration did before D4c — the number would be 0.5, and the
        report would carry the wrong science under the right label.
        """
        scope = _Scope([_Row(k, v) for k, v in self.TRUTH.items()])
        scalar, _, _ = self._metric()._compute(
            {0: "d"}, evaluation_payload=self.PREDICTIONS, task_scope=scope, data_dir=None
        )
        assert scalar != pytest.approx(0.5)

    def test_a_missing_prediction_is_not_correct_rather_than_excluded(self):
        """A partial deliverable is penalised, never silently flattered.

        With ``d`` dropped, class 0 loses its false positive: TP=1
        predicted=1 actual=2 -> P=1 R=0.5 F1=2/3. Class 1 is unchanged at 2/3.
        Class 2 still has support and no prediction -> 0.
        macro = (2/3 + 2/3) / 37.
        """
        scope = _Scope([_Row(k, v) for k, v in self.TRUTH.items()])
        partial = {k: v for k, v in self.PREDICTIONS.items() if k != "d"}
        scalar, _, _ = self._metric()._compute(
            {0: "d"}, evaluation_payload=partial, task_scope=scope, data_dir=None
        )
        assert scalar == pytest.approx((2.0 / 3.0 + 2.0 / 3.0) / 37.0, abs=1e-12)

    def test_a_perfect_run_over_every_class_is_exactly_one(self):
        """The only input for which the 37-denominator can reach 1.0."""
        from examples.oxford_iiit_pet.plugins._pets_metrics import PETS_CLASS_COUNT

        truth = {f"img{i}": i for i in range(PETS_CLASS_COUNT)}
        scope = _Scope([_Row(k, v) for k, v in truth.items()])
        scalar, _, _ = self._metric()._compute(
            {0: "d"}, evaluation_payload=dict(truth), task_scope=scope, data_dir=None
        )
        assert scalar == pytest.approx(1.0, abs=1e-12)

    def test_an_empty_scope_is_a_wiring_defect_not_a_score(self):
        with pytest.raises(ValueError, match="non-empty evaluation scope"):
            self._metric()._compute(
                {0: "d"}, evaluation_payload={}, task_scope=_Scope([]), data_dir=None
            )


# ======================================================================
# Pets — log loss
# ======================================================================


class TestPetsLogLoss:
    def _metric(self):
        from examples.oxford_iiit_pet.plugins._pets_metrics import PetsLogLossMetric

        # Built through the DECLARATION path, exactly as a pack does. D5 ships
        # the shipped `metric_log_loss.json`; D4c owns the implementation.
        return PetsLogLossMetric(_declaration_spec("log_loss", "lower"))

    @staticmethod
    def _payload(distributions: dict):
        """The REAL production shape, not a stand-in.

        The metric reads ``evaluation_payload.probabilities`` (an attribute),
        never the mapping's own values — the mapping side carries arg-max
        LABELS, for every consumer that isn't this metric. Constructing a
        plain ``dict`` here would test a shape production never produces; a
        prior version of this file did exactly that, which is why these
        goldens moved when the sidecar landed (Step 12 / PR-12d, closing the
        D5 codec obligation).
        """
        from execute_tools.pets_data_path import PetsEvaluationPayload

        return PetsEvaluationPayload(labels={}, probabilities=distributions)

    def test_it_computes_the_hand_calculated_cross_entropy(self):
        """Two samples, truth 0 and 1, probability on the true class 0.5 and 0.25.

        mean(-ln 0.5, -ln 0.25) = (0.693147180559945 + 1.386294361119891) / 2
                                = 1.039720770839918
        """
        scope = _Scope([_Row("a", 0), _Row("b", 1)])
        payload = self._payload({"a": [0.5, 0.5], "b": [0.75, 0.25]})
        scalar, per_sample, references = self._metric()._compute(
            {0: "d"}, evaluation_payload=payload, task_scope=scope, data_dir=None
        )
        assert scalar == pytest.approx(1.0397207708399179, abs=1e-12)
        assert scalar == pytest.approx((math.log(2) + math.log(4)) / 2, abs=1e-12)
        assert per_sample is None
        assert references == ()

    def test_a_certain_and_correct_prediction_scores_zero(self):
        scope = _Scope([_Row("a", 1)])
        payload = self._payload({"a": [0.0, 1.0]})
        scalar, _, _ = self._metric()._compute(
            {0: "d"}, evaluation_payload=payload, task_scope=scope, data_dir=None
        )
        assert scalar == pytest.approx(0.0, abs=1e-12)

    def test_a_certain_and_WRONG_prediction_is_finite_not_infinite(self):
        """The clip earning its keep.

        Without it a single over-confident zero returns ``inf``, one sample
        dominates every aggregate, and a bad-but-real score becomes a
        non-number that no ordering can compare.
        """
        scope = _Scope([_Row("a", 0), _Row("b", 1)])
        payload = self._payload({"a": [0.0, 1.0], "b": [0.0, 1.0]})
        scalar, _, _ = self._metric()._compute(
            {0: "d"}, evaluation_payload=payload, task_scope=scope, data_dir=None
        )
        assert math.isfinite(scalar)
        assert scalar == pytest.approx(-math.log(1e-15) / 2, abs=1e-9)

    def test_a_MISSING_sidecar_is_REFUSED_with_the_reason(self):
        """The D5 obligation, CLOSED — a sidecar, not a widened CSV.

        A producer that hands back an already-decided class index (every
        pre-12d caller, and any model this run scores that made no
        probabilistic prediction) writes no ``_probs.npz`` sidecar, so
        ``evaluation_payload.probabilities`` is absent. The refusal must fire
        on that absence rather than silently reading the arg-max LABEL as a
        probability — which is what the pre-sidecar defect actually was.
        """
        from execute_tools.pets_data_path import PetsEvaluationPayload

        scope = _Scope([_Row("a", 0)])
        payload = PetsEvaluationPayload(labels={"a": 0}, probabilities=None)
        with pytest.raises(ValueError, match="probability vector"):
            self._metric()._compute(
                {0: "d"}, evaluation_payload=payload, task_scope=scope, data_dir=None
            )

    def test_a_PLAIN_dict_with_no_probabilities_attribute_is_ALSO_refused(self):
        """The pre-sidecar caller shape, still handled honestly.

        Not every caller constructs ``PetsEvaluationPayload`` — a plain
        ``dict`` of labels has no ``.probabilities`` attribute at all, and
        ``getattr(..., "probabilities", None)`` must treat that exactly like
        an explicit ``None`` rather than raising a different, confusing error.
        """
        scope = _Scope([_Row("a", 0)])
        with pytest.raises(ValueError, match="probability vector"):
            self._metric()._compute(
                {0: "d"}, evaluation_payload={"a": 0}, task_scope=scope, data_dir=None
            )


# ======================================================================
# DAVIS — MAE and PSNR
# ======================================================================


class TestDavisMetrics:
    #: One clip, four elements. errors: +1, -1, +2, 0
    #:   MAE = (1 + 1 + 2 + 0) / 4 = 1.0
    #:   MSE = (1 + 1 + 4 + 0) / 4 = 1.5
    TRUTH: ClassVar[dict[str, list[list[float]]]] = {"seq:0": [[0.0, 0.0], [0.0, 0.0]]}
    PREDICTIONS: ClassVar[dict[str, list[list[float]]]] = {"seq:0": [[1.0, -1.0], [2.0, 0.0]]}

    def _mae(self):
        from examples.davis_future_prediction.plugins._davis_metrics import DavisMaeMetric

        return DavisMaeMetric(_spec("examples/davis_future_prediction/declared/metric_mae.json"))

    def _psnr(self):
        from examples.davis_future_prediction.plugins._davis_metrics import DavisPsnrMetric

        return DavisPsnrMetric(_spec("examples/davis_future_prediction/declared/metric_psnr.json"))

    def _accumulate(self, absolute):
        from examples.davis_future_prediction.plugins._davis_metrics import _accumulate

        return _accumulate(self.PREDICTIONS, self.TRUTH, absolute=absolute)

    def test_mae_is_the_hand_calculated_global_mean_absolute_error(self):
        total, count = self._accumulate(absolute=True)
        assert (total, count) == (4.0, 4)
        assert total / count == pytest.approx(1.0, abs=1e-12)

    def test_psnr_is_the_hand_calculated_decibel_value(self):
        """data_range 1.0, MSE 1.5 -> 10*log10(1/1.5) = -1.7609125905568124 dB."""
        total, count = self._accumulate(absolute=False)
        assert (total, count) == (6.0, 4)
        mse = total / count
        assert mse == pytest.approx(1.5, abs=1e-12)
        assert 10.0 * math.log10(1.0 / mse) == pytest.approx(-1.7609125905568124, abs=1e-12)

    def test_mae_and_mse_are_DIFFERENT_numbers_on_this_fixture(self):
        """The fixture is asymmetric on purpose.

        If MAE and MSE agreed here, binding `mae` to ``GlobalMseMetric`` — what
        the shipped declaration did — would be undetectable by value.
        """
        mae_total, count = self._accumulate(absolute=True)
        mse_total, _ = self._accumulate(absolute=False)
        assert mae_total / count != pytest.approx(mse_total / count)

    def test_the_global_mean_is_not_a_mean_of_means(self):
        """Unequal sample sizes: the frozen aggregation divides ONCE.

        clip A: 1 element, error 4 -> squared 16
        clip B: 4 elements, error 0 -> squared 0
        global = 16/5 = 3.2   ·   mean-of-means = (16 + 0)/2 = 8.0
        """
        from examples.davis_future_prediction.plugins._davis_metrics import _accumulate

        truth = {"a": [0.0], "b": [0.0, 0.0, 0.0, 0.0]}
        predictions = {"a": [4.0], "b": [0.0, 0.0, 0.0, 0.0]}
        total, count = _accumulate(predictions, truth, absolute=False)
        assert (total, count) == (16.0, 5)
        assert total / count == pytest.approx(3.2, abs=1e-12)

    def test_psnr_REFUSES_a_declaration_carrying_no_data_range(self):
        """``transform_params`` stops being decoration.

        The same MSE over ``[0,1]`` and over ``[0,255]`` differs by ~48 dB, so
        a default would report dB in the wrong scale and look entirely
        plausible doing it.
        """
        from examples.davis_future_prediction.plugins._davis_metrics import DavisPsnrMetric

        metric = DavisPsnrMetric(_declaration_spec("psnr", "higher"))
        with pytest.raises(ValueError, match="requires a positive `data_range`"):
            metric._compute(
                {0: "d"}, evaluation_payload={}, task_scope=_Scope([_Row("a", 0)]), data_dir="x"
            )

    def test_the_shipped_psnr_declaration_actually_carries_the_range(self):
        """Reachability: the refusal above must not be the production state."""
        assert self._psnr().spec.transform_params["data_range"] == 1.0

    def test_a_missing_dense_prediction_is_LOUD(self):
        from examples.davis_future_prediction.plugins._davis_metrics import _accumulate

        with pytest.raises(ValueError, match="no prediction for clip"):
            _accumulate({}, self.TRUTH, absolute=True)

    def test_a_shape_mismatch_is_LOUD(self):
        from examples.davis_future_prediction.plugins._davis_metrics import _accumulate

        with pytest.raises(ValueError, match="does not match target shape"):
            _accumulate({"seq:0": [[1.0]]}, self.TRUTH, absolute=True)


# ======================================================================
# FALSIFIER 1 — a declaration bound to the WRONG implementation
# ======================================================================


class TestFalsifier1WrongImplementationIsRefused:
    """F-12d-3. The check that did not exist.

    ``_compose_metric``'s identity check was ``metric.spec.id != spec.id``, and
    ``EvaluationMetric.__init__`` assigns ``self.spec = spec`` — so it compared
    the declaration to itself and could fire only for an implementation that
    rewrites its own id. It was blind to the case the acceptance names, which
    is why `psnr`, `mae` and `macro_f1` all composed green while bound to
    implementations computing something else.
    """

    def test_every_pack_metric_states_what_it_implements(self):
        from examples.davis_future_prediction.plugins._davis_metrics import (
            DavisMaeMetric,
            DavisPsnrMetric,
        )
        from examples.oxford_iiit_pet.plugins._pets_metrics import (
            PetsLogLossMetric,
            PetsMacroF1Metric,
        )

        assert PetsMacroF1Metric.IMPLEMENTS == ("macro_f1",)
        assert PetsLogLossMetric.IMPLEMENTS == ("log_loss",)
        assert DavisMaeMetric.IMPLEMENTS == ("mae",)
        assert DavisPsnrMetric.IMPLEMENTS == ("psnr",)

    def test_the_builtins_state_theirs_too(self):
        from execute_tools.evaluation_metric import (
            TIDMAD_METRIC_ID,
            AccuracyMetric,
            GlobalMseMetric,
            TidmadDenoisingMetric,
        )

        assert AccuracyMetric.IMPLEMENTS == ("accuracy",)
        assert GlobalMseMetric.IMPLEMENTS == ("mse",)
        assert TidmadDenoisingMetric.IMPLEMENTS == (TIDMAD_METRIC_ID,)

    @pytest.mark.parametrize(
        ("declared_id", "implementation"),
        [
            ("psnr", "GlobalMseMetric"),
            ("mae", "GlobalMseMetric"),
            ("macro_f1", "AccuracyMetric"),
        ],
    )
    def test_composition_REFUSES_the_exact_mis_bindings_that_shipped(
        self, declared_id, implementation, tmp_path
    ):
        """The three real mis-bindings, each refused by name."""
        from workflows.task_composition import TaskCompositionError, _compose_metric

        declaration = tmp_path / f"metric_{declared_id}.json"
        declaration.write_text(
            json.dumps(
                {
                    "id": declared_id,
                    "direction": "higher",
                    "aggregation": "whatever",
                    "references": [],
                    "scoreability": {"contract_id": "deliverable_presence"},
                    "transform": None,
                    "transform_params": {},
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(TaskCompositionError, match="states it implements"):
            _compose_metric(
                {
                    "declaration": str(declaration),
                    "implementation": {
                        "module": "execute_tools.evaluation_metric",
                        "symbol": implementation,
                    },
                },
                str(tmp_path),
                "metric",
            )

    def test_an_implementation_making_NO_claim_still_composes_under_any_id(self, tmp_path):
        """`MetricSpec.id` stays OPAQUE (D16/C5).

        The refusal is about two parties DISAGREEING, never about the framework
        parsing an id. An implementation that claims nothing composes anywhere,
        which is what keeps every pre-D4c binding valid and a genuinely generic
        implementation reusable.
        """
        from execute_tools.evaluation_metric import EvaluationMetric

        assert EvaluationMetric.IMPLEMENTS == ()
