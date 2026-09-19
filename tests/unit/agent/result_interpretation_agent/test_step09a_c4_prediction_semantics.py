"""Step 09a — C4: the sign-safe prediction band and the version partition.

Design: ``docs/design/generic_framework_upgrade/step_09_interpretation_task_blocks/
pr_09a_interpreter_evidence_ordering.md`` §3.4, §4.5; parent §8, §13 ¶1;
operator rulings Q-09a-2, Q-09a-3.

Three defects, all of which looked like working code
----------------------------------------------------
1. **Direction-blind.** ``actual > sota`` means "confirmed" only for a
   MAXIMISED metric. Under a minimised one it labels every regression a
   confirmation — and the proposer then builds on it.
2. **Sign-degenerate.** The band was ``actual >= sota * (1 - margin)``.
   Scaling a NEGATIVE reference by 0.95 moves it toward zero, so for TIDMAD
   (every score negative) the band sat on the wrong side of the SOTA
   entirely: `partial` was unreachable, and a competitive model was recorded
   as `refuted`.
3. **Uncomputable counted as evidence.** An unresolvable metric returned
   ``outcome="partial"``, which entered the accuracy pool and was published
   as a discovery reading "achieved metric=N/A".

Why the counts are partitioned
------------------------------
Outcomes from the corrected rule are not comparable with outcomes from the
old one. Pooling them yields a hit-rate that means nothing — and the proposer
RENDERS that number. So the legacy dict is frozen as the v1 pool and the new
outcomes accumulate under their own semantics id, with both pool sizes stated
in the digest.

Every expectation below is hand-computed and hardcoded.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
from typing import ClassVar

import pytest

from execute_tools.metric_order import MetricOrder
from nodes.interpretation_helpers import generate_discoveries
from nodes.result_interpretation_agent.prediction import (
    COMPARABLE_OUTCOMES,
    OUTCOME_UNEVALUATED,
    PREDICTION_SEMANTICS_LEGACY_V1,
    PREDICTION_SEMANTICS_SIGNSAFE_V2,
    accumulate_information_gain,
    accumulate_prediction_outcomes,
    evaluate_prediction,
    prediction_pool_sizes,
)
from tests.helpers.metric_fixtures import direction_only_spec, shipped_spec

HIGHER = MetricOrder(shipped_spec())
LOWER = MetricOrder(direction_only_spec())
BOUND_ID = shipped_spec().id


def _evaluate(actual, sota, *, order, metric=None, per_sample=None, predicted=None, margin=0.05):
    prediction = {"current_value": sota, "predicted_value": predicted}
    if metric is not None:
        prediction["metric"] = metric
    results = {"best_denoising_score": actual, "best_file_vector": per_sample}
    return evaluate_prediction(
        prediction,
        results,
        current_sota=sota,
        partial_margin=margin,
        order=order,
        bound_metric_id=BOUND_ID,
    )


# ---------------------------------------------------------------------------
# 1. The band — every direction x sign quadrant, hand-computed
# ---------------------------------------------------------------------------


class TestTheFrozenBand:
    @pytest.mark.parametrize(
        "order,sota,actual,expected,gain",
        [
            # --- higher / NEGATIVE (TIDMAD's real regime). band = 0.05*2.55 = 0.1275
            (HIGHER, -2.55, -2.43, "confirmed", 0.12),
            (HIGHER, -2.55, -2.60, "partial", 0.0),  # distance 0.05 <= 0.1275
            (HIGHER, -2.55, -2.90, "refuted", 0.0),  # distance 0.35 >  0.1275
            # --- lower / POSITIVE (DAVIS's regime). band = 0.05*0.0174 = 0.00087
            (LOWER, 0.0174, 0.0165, "confirmed", 0.0009),
            (LOWER, 0.0174, 0.0178, "partial", 0.0),  # distance 0.0004 <= 0.00087
            (LOWER, 0.0174, 0.0190, "refuted", 0.0),  # distance 0.0016 >  0.00087
            # --- higher / POSITIVE. band = 0.05*5.0 = 0.25
            (HIGHER, 5.0, 5.5, "confirmed", 0.5),
            (HIGHER, 5.0, 4.8, "partial", 0.0),
            (HIGHER, 5.0, 4.0, "refuted", 0.0),
            # --- lower / NEGATIVE. band = 0.05*2.0 = 0.10
            (LOWER, -2.0, -2.5, "confirmed", 0.5),
            (LOWER, -2.0, -1.95, "partial", 0.0),
            (LOWER, -2.0, -1.5, "refuted", 0.0),
        ],
        ids=[
            "higher/neg/confirmed",
            "higher/neg/partial",
            "higher/neg/refuted",
            "lower/pos/confirmed",
            "lower/pos/partial",
            "lower/pos/refuted",
            "higher/pos/confirmed",
            "higher/pos/partial",
            "higher/pos/refuted",
            "lower/neg/confirmed",
            "lower/neg/partial",
            "lower/neg/refuted",
        ],
    )
    def test_the_band_matrix(self, order, sota, actual, expected, gain):
        result = _evaluate(actual, sota, order=order)
        assert result["outcome"] == expected
        assert result["information_gain"] == pytest.approx(gain, abs=1e-4)

    def test_the_negative_partial_is_reachable_at_all(self):
        """The single most important cell.

        Under the OLD rule a negative SOTA made `partial` unreachable: the
        comparison `actual >= sota * 0.95` required beating a bar ABOVE the
        SOTA. Every near-miss on TIDMAD was therefore recorded as `refuted`.
        """
        assert _evaluate(-2.60, -2.55, order=HIGHER)["outcome"] == "partial"

    def test_equality_belongs_to_the_partial_band(self):
        for order in (HIGHER, LOWER):
            result = _evaluate(-2.55, -2.55, order=order)
            assert result["outcome"] == "partial"
            assert result["delta_from_sota"] == 0.0

    def test_the_band_edge_is_inclusive(self):
        """distance == band_width is INSIDE. Values chosen so both sides are
        exact in binary floating point (1.0 == 0.05 * 20.0)."""
        assert abs(-21.0 - (-20.0)) == 0.05 * abs(-20.0), "fixture no longer sits ON the edge"
        assert _evaluate(-21.0, -20.0, order=HIGHER)["outcome"] == "partial"

    @pytest.mark.parametrize(
        "order,actual,expected",
        [(HIGHER, 0.5, "confirmed"), (HIGHER, 0.0, "partial"), (HIGHER, -0.5, "refuted")],
    )
    def test_a_zero_sota_gives_a_zero_width_band(self, order, actual, expected):
        """band = 0.05 * 0 = 0, so ONLY exact equality is partial. A rule that
        divided by the reference would blow up here instead."""
        assert _evaluate(actual, 0.0, order=order)["outcome"] == expected

    def test_information_gain_is_the_distance_only_when_confirmed(self):
        assert _evaluate(-2.43, -2.55, order=HIGHER)["information_gain"] == 0.12
        assert _evaluate(-2.60, -2.55, order=HIGHER)["information_gain"] == 0.0
        assert _evaluate(-2.90, -2.55, order=HIGHER)["information_gain"] == 0.0

    def test_the_gain_is_a_magnitude_under_lower_too(self):
        """Under `lower`, confirming means a SMALLER number, so a signed delta
        would record a NEGATIVE information gain for a success."""
        result = _evaluate(0.0165, 0.0174, order=LOWER)
        assert result["information_gain"] > 0
        assert result["delta_from_sota"] < 0, "the SIGNED delta still says which way it moved"

    def test_the_same_input_gets_opposite_verdicts_under_opposite_directions(self):
        """The whole correction in one assertion.

        The actual is far enough from the SOTA to fall OUTSIDE the band
        (distance 0.35 > 0.05 * 2.55 = 0.1275), so the two directions really
        do land on opposite verdicts rather than both on `partial`.
        """
        assert _evaluate(-2.20, -2.55, order=HIGHER)["outcome"] == "confirmed"
        assert _evaluate(-2.20, -2.55, order=LOWER)["outcome"] == "refuted"


# ---------------------------------------------------------------------------
# 2. unevaluated
# ---------------------------------------------------------------------------


class TestUnevaluated:
    def test_an_uncomputable_metric_is_unevaluated_not_partial(self):
        result = _evaluate(None, -2.55, order=HIGHER)
        assert result["outcome"] == OUTCOME_UNEVALUATED
        assert result["information_gain"] == 0.0
        assert result["delta_from_sota"] is None
        assert "not evaluated" in result["notes"]

    def test_a_missing_baseline_is_unevaluated(self):
        result = _evaluate(-2.43, None, order=HIGHER)
        assert result["outcome"] == OUTCOME_UNEVALUATED
        assert "no SOTA baseline" in result["notes"]

    def test_unevaluated_is_not_one_of_the_comparable_outcomes(self):
        assert OUTCOME_UNEVALUATED not in COMPARABLE_OUTCOMES

    def test_it_increments_neither_pool(self):
        evaluation = _evaluate(None, -2.55, order=HIGHER)
        pools, accuracy = accumulate_prediction_outcomes({}, evaluation)
        assert pools[PREDICTION_SEMANTICS_SIGNSAFE_V2] == dict.fromkeys(COMPARABLE_OUTCOMES, 0)
        assert accuracy is None, "an empty pool has NO hit-rate, not a zero one"
        assert accumulate_information_gain({}, evaluation) == {}

    def test_it_publishes_no_discovery(self):
        """The E5 half of the defect: production published
        "PARTIAL: <model> achieved metric=N/A ... inconclusive" as a finding
        and carried it in the vocabulary."""
        evaluation = _evaluate(None, -2.55, order=HIGHER)
        discoveries = generate_discoveries(
            prediction_eval=evaluation,
            model_type="m",
            best_score=None,
            inherited_components=[],
            proposed_vocab_links=[],
            order=HIGHER,
        )
        assert [d for d in discoveries if d.name.startswith("prediction_")] == []

    def test_a_comparable_outcome_still_publishes_one(self):
        """Anti-vacuity for the test above."""
        evaluation = _evaluate(-2.43, -2.55, order=HIGHER)
        discoveries = generate_discoveries(
            prediction_eval=evaluation,
            model_type="m",
            best_score=-2.43,
            inherited_components=[],
            proposed_vocab_links=[],
            order=HIGHER,
        )
        assert [d for d in discoveries if d.name == "prediction_m_confirmed"]


# ---------------------------------------------------------------------------
# 3. The metric grammar
# ---------------------------------------------------------------------------


class TestTheMetricGrammar:
    def test_the_default_metric_is_the_bound_id_not_a_task_name(self):
        """`denoising_score` was ONE task's metric name, hardcoded as the
        framework's default. A second task's prediction would have silently
        resolved against a field that is not its metric."""
        result = _evaluate(-2.43, -2.55, order=HIGHER, metric=None)
        assert result["metric"] == BOUND_ID
        assert result["metric_resolution"] == "bound_id"

    def test_the_bound_id_resolves_against_the_primary_scalar(self):
        result = _evaluate(-2.43, -2.55, order=HIGHER, metric=BOUND_ID)
        assert result["actual_value"] == -2.43
        assert result["metric_resolution"] == "bound_id"

    @pytest.mark.parametrize(
        "alias",
        [
            "denoising_score",
            "best_score",
            "overall denoising score",
            "score",
            "best_denoising_score",
        ],
    )
    def test_every_frozen_legacy_alias_still_evaluates_and_says_so(self, alias):
        """Read-only compatibility: a chain crossing the 09a boundary must
        still be able to evaluate the prediction its previous iteration wrote.
        The resolution is RECORDED rather than silently normalised."""
        result = _evaluate(-2.43, -2.55, order=HIGHER, metric=alias)
        assert result["actual_value"] == -2.43
        assert result["metric_resolution"] == "legacy_alias"

    def test_the_alias_table_is_not_grown_for_other_tasks(self):
        from nodes.result_interpretation_agent.prediction import _LEGACY_METRIC_ALIASES

        assert _LEGACY_METRIC_ALIASES == {
            "denoising_score",
            "best_score",
            "overall denoising score",
            "score",
            "best_denoising_score",
        }, (
            "the legacy alias table is FROZEN (R-09-5). A new task's metric is "
            "recognised by its own bound id, never by being added here — growing it "
            "rebuilds the per-task vocabulary Step 09 exists to remove."
        )

    def test_the_slice_mean_form_is_refused_even_when_the_evidence_exists(self):
        """UPGRADED by F-SCAND-1 — this asserted the slice mean RESOLVED.

        The evidence being present is exactly the dangerous case: the value
        was computable, so nothing downstream could tell the resulting number
        was a "mean of per-file LOG scores" — the aggregation the standard
        forbids by name for Jensen's inequality gap. Refusing it lands the
        prediction in the existing `unevaluated` pool.
        """
        result = _evaluate(
            -2.43,
            1.5,
            order=HIGHER,
            metric="mean(file_vector[0:5])",
            per_sample=[1.0, 1.5, 2.0, 2.5, 3.0, *([None] * 15)],
        )
        assert result["actual_value"] is None
        assert result["metric_resolution"] == "refused_forbidden_aggregation"
        assert result["outcome"] == OUTCOME_UNEVALUATED

    def test_a_single_index_form_resolves(self):
        result = _evaluate(
            -2.43, 1.0, order=HIGHER, metric="file_vector[2]", per_sample=[1.0, 1.5, 2.0]
        )
        assert result["actual_value"] == 2.0
        assert result["metric_resolution"] == "per_sample_index"

    def test_a_per_sample_form_on_a_scalar_only_task_is_capability_not_corruption(self):
        """Pets and DAVIS are both scalar-only. The resolution distinguishes
        "this task has no per-sample evidence" from "that string is nonsense",
        which the old single `None` return could not."""
        result = _evaluate(-2.43, -2.55, order=HIGHER, metric="mean(file_vector[0:5])")
        assert result["outcome"] == OUTCOME_UNEVALUATED
        assert result["metric_resolution"] == "per_sample_unavailable"

    def test_an_unrecognized_metric_is_named_as_such(self):
        result = _evaluate(-2.43, -2.55, order=HIGHER, metric="a_metric_nobody_declared")
        assert result["outcome"] == OUTCOME_UNEVALUATED
        assert result["metric_resolution"] == "unrecognized"

    def test_a_malformed_slice_form_is_refused_rather_than_unrecognized(self):
        """UPGRADED by F-SCAND-1 — this asserted `unrecognized`.

        The refusal now precedes index parsing, deliberately: the form is
        forbidden whether or not its indices are well-formed, and "fix your
        typo" would be the wrong remedy to report for a request that would
        be refused even when spelled correctly.
        """
        result = _evaluate(
            -2.43, -2.55, order=HIGHER, metric="mean(file_vector[a:b])", per_sample=[1.0, 2.0]
        )
        assert result["metric_resolution"] == "refused_forbidden_aggregation"


class TestTheRecordShapeIsUniform:
    EXPECTED_KEYS: ClassVar[set[str]] = {
        "metric",
        "metric_resolution",
        "predicted_value",
        "actual_value",
        "current_sota",
        "delta_from_sota",
        "outcome",
        "boldness",
        "information_gain",
        "notes",
        "prediction_evaluation_semantics",
    }

    @pytest.mark.parametrize(
        "actual,sota",
        [(-2.43, -2.55), (-2.60, -2.55), (-2.90, -2.55), (None, -2.55), (-2.43, None)],
        ids=["confirmed", "partial", "refuted", "no-metric", "no-sota"],
    )
    def test_every_branch_emits_the_same_keys(self, actual, sota):
        """The pre-09a uncomputable branch returned a DIFFERENT key set, so a
        consumer reading the record had to guess which shape it had."""
        assert set(_evaluate(actual, sota, order=HIGHER)) == self.EXPECTED_KEYS

    def test_every_branch_stamps_the_semantics_that_produced_it(self):
        for actual, sota in [(-2.43, -2.55), (None, -2.55)]:
            result = _evaluate(actual, sota, order=HIGHER)
            assert result["prediction_evaluation_semantics"] == PREDICTION_SEMANTICS_SIGNSAFE_V2

    def test_boldness_is_unchanged_and_survives_a_missing_baseline(self):
        assert _evaluate(-2.43, -2.55, order=HIGHER, predicted=-2.40)["boldness"] == 0.0588
        assert _evaluate(-2.43, None, order=HIGHER, predicted=-2.40)["boldness"] == 0.0


# ---------------------------------------------------------------------------
# 4. The version partition (Q-09a-2, per-field)
# ---------------------------------------------------------------------------


class TestTheVersionPartition:
    def test_a_legacy_only_input_starts_a_fresh_v2_pool(self):
        legacy = {"confirmed": 1, "partial": 0, "refuted": 1}
        evaluation = _evaluate(-2.43, -2.55, order=HIGHER)

        pools, accuracy = accumulate_prediction_outcomes({}, evaluation)
        gains = accumulate_information_gain({}, evaluation)
        sizes = prediction_pool_sizes(legacy, pools)

        assert pools == {
            PREDICTION_SEMANTICS_SIGNSAFE_V2: {"confirmed": 1, "partial": 0, "refuted": 0}
        }
        assert accuracy == {"confirmed": 1.0, "partial": 0.0, "refuted": 0.0}
        assert gains == {PREDICTION_SEMANTICS_SIGNSAFE_V2: 0.12}
        assert sizes == {PREDICTION_SEMANTICS_LEGACY_V1: 2, PREDICTION_SEMANTICS_SIGNSAFE_V2: 1}

    def test_the_legacy_pool_is_never_incremented(self):
        """MUTATION TARGET. Incrementing it would make the two rules' outcomes
        indistinguishable forever — there is no field recording which rule
        produced which count."""
        legacy = {"confirmed": 1, "partial": 0, "refuted": 1}
        before = dict(legacy)
        accumulate_prediction_outcomes({}, _evaluate(-2.43, -2.55, order=HIGHER))
        assert legacy == before

    def test_an_existing_v2_pool_keeps_accumulating(self):
        prior = {PREDICTION_SEMANTICS_SIGNSAFE_V2: {"confirmed": 1, "partial": 0, "refuted": 1}}
        pools, accuracy = accumulate_prediction_outcomes(
            prior, _evaluate(-2.43, -2.55, order=HIGHER)
        )
        assert pools[PREDICTION_SEMANTICS_SIGNSAFE_V2] == {
            "confirmed": 2,
            "partial": 0,
            "refuted": 1,
        }
        assert accuracy == {"confirmed": 0.6667, "partial": 0.0, "refuted": 0.3333}
        assert prior[PREDICTION_SEMANTICS_SIGNSAFE_V2]["confirmed"] == 1, "input was mutated"

    def test_gains_are_never_pooled_across_versions(self):
        """MUTATION TARGET: adding the v2 gain into the legacy scalar."""
        gains = accumulate_information_gain(
            {PREDICTION_SEMANTICS_SIGNSAFE_V2: 0.30}, _evaluate(-2.43, -2.55, order=HIGHER)
        )
        assert gains == {PREDICTION_SEMANTICS_SIGNSAFE_V2: pytest.approx(0.42)}
        assert PREDICTION_SEMANTICS_LEGACY_V1 not in gains

    def test_accuracy_is_computed_from_the_v2_pool_alone(self):
        """A legacy pool with a very different shape must not move the
        fraction by even one digit."""
        evaluation = _evaluate(-2.43, -2.55, order=HIGHER)
        _, accuracy = accumulate_prediction_outcomes({}, evaluation)
        assert accuracy == {"confirmed": 1.0, "partial": 0.0, "refuted": 0.0}
        sizes = prediction_pool_sizes(
            {"refuted": 99}, {PREDICTION_SEMANTICS_SIGNSAFE_V2: {"confirmed": 1}}
        )
        assert sizes[PREDICTION_SEMANTICS_LEGACY_V1] == 99
        assert sizes[PREDICTION_SEMANTICS_SIGNSAFE_V2] == 1

    def test_pool_sizes_always_state_both_pools_even_when_empty(self):
        sizes = prediction_pool_sizes({}, {})
        assert sizes == {
            PREDICTION_SEMANTICS_LEGACY_V1: 0,
            PREDICTION_SEMANTICS_SIGNSAFE_V2: 0,
        }

    def test_no_single_number_anywhere_equals_legacy_plus_v2(self):
        """The claim stated as an assertion, on a fixture where BOTH are
        non-zero so a pooled scalar would be visibly different."""
        legacy_gain = 0.30
        gains = accumulate_information_gain(
            {PREDICTION_SEMANTICS_SIGNSAFE_V2: 0.12}, _evaluate(-2.43, -2.55, order=HIGHER)
        )
        pooled = legacy_gain + gains[PREDICTION_SEMANTICS_SIGNSAFE_V2]
        assert pooled not in gains.values()
        assert legacy_gain not in gains.values()


class TestTheSemanticsIdsHaveOneAuthority:
    """The prediction-accounting vocabulary is DECLARED once and imported.

    F-09a-17 originally copied these literals into three modules with an
    equality pin, because the obvious home (`prediction.py`) cannot be imported
    by the schema — that direction is a real cycle. The declaration now lives in
    `agent/schemas/interpretation.py`, the lowest layer every consumer already
    depends on downward, so the copies are gone.

    This class replaces the drift pin with the stronger property: there is
    exactly ONE declaration, and the modules that used to copy it now consume
    it. It fails if a future edit re-introduces a second spelling.
    """

    #: Every production module that reads these ids. `prediction.py` implements
    #: the v2 rule and re-exports; the other three consume.
    _CONSUMERS = (
        "src/nodes/result_interpretation_agent/prediction.py",
        "src/nodes/result_interpretation_agent/result_interpretation_agent.py",
        "src/nodes/interpretation_helpers.py",
        "src/core/resume.py",
    )

    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parents[4]

    def test_each_id_is_declared_exactly_once_in_production(self):
        """MUTATION TARGET: copying a literal back into a consumer.

        Scans assignments and call arguments — a bare occurrence in a docstring
        is prose, not a second authority, so only lines that are not inside a
        string literal count. The check is done on the parsed source so a
        quoted example in documentation cannot satisfy or break it
        (ledger F-09a-14).
        """
        root = self._repo_root()
        for value in (
            PREDICTION_SEMANTICS_SIGNSAFE_V2,
            PREDICTION_SEMANTICS_LEGACY_V1,
            OUTCOME_UNEVALUATED,
        ):
            sites: list[str] = []
            for rel in ("src/agent/schemas/interpretation.py", *self._CONSUMERS):
                tree = ast.parse((root / rel).read_text(encoding="utf-8"))
                docstrings = {
                    ast.get_docstring(n, clean=False)
                    for n in ast.walk(tree)
                    if isinstance(n, ast.Module | ast.ClassDef | ast.FunctionDef)
                }
                for node in ast.walk(tree):
                    if (
                        isinstance(node, ast.Constant)
                        and node.value == value
                        and node.value not in docstrings
                    ):
                        sites.append(f"{rel}:{node.lineno}")
            assert sites == [
                s for s in sites if s.startswith("src/agent/schemas/interpretation.py")
            ], f"{value!r} is spelled outside its declaration: {sites}"
            assert len(sites) == 1, f"{value!r} has {len(sites)} declarations: {sites}"

    def test_every_consumer_imports_the_declaration(self):
        """Anti-vacuity for the census above: the ids could be absent from a
        consumer because the consumer stopped using them entirely."""
        root = self._repo_root()
        for rel in self._CONSUMERS:
            source = (root / rel).read_text(encoding="utf-8")
            assert "from agent.schemas.interpretation import" in source, rel

    def test_the_schema_default_is_the_legacy_id(self):
        from agent.schemas.interpretation import InterpretationOutput

        default = InterpretationOutput.model_fields["prediction_evaluation_semantics"].default
        assert default == PREDICTION_SEMANTICS_LEGACY_V1, (
            "a digest written before Step 09a has no such key and must read as the "
            "semantics that actually produced it"
        )

    def test_the_node_re_exports_them_under_the_names_callers_use(self):
        """The move must not churn every import site: `prediction.py` remains
        the place the interpreter imports these from."""
        prediction = importlib.import_module("nodes.result_interpretation_agent.prediction")
        helpers = importlib.import_module("nodes.interpretation_helpers")
        assert prediction.PREDICTION_SEMANTICS_SIGNSAFE_V2 == PREDICTION_SEMANTICS_SIGNSAFE_V2
        assert prediction.PREDICTION_SEMANTICS_LEGACY_V1 == PREDICTION_SEMANTICS_LEGACY_V1
        assert prediction.COMPARABLE_OUTCOMES == COMPARABLE_OUTCOMES
        assert helpers.OUTCOME_UNEVALUATED == OUTCOME_UNEVALUATED

    def test_a_step09a_run_stamps_the_v2_id(self):
        from agent.schemas.interpretation import InterpretationOutput

        digest = InterpretationOutput(
            model_types=["m"],
            model_descriptions={"m": "d"},
            total_experiments=1,
            key_findings=[],
            bottlenecks=[],
            take_home_message="",
            prediction_evaluation_semantics=PREDICTION_SEMANTICS_SIGNSAFE_V2,
        )
        assert digest.prediction_evaluation_semantics == "metric_order_signsafe_v2"


class TestTheEvaluatorRefusesToGuess:
    def test_order_and_bound_id_are_required_keywords(self):
        with pytest.raises(TypeError):
            evaluate_prediction({"current_value": -2.55}, {"best_denoising_score": -2.43})
        with pytest.raises(TypeError):
            evaluate_prediction(
                {"current_value": -2.55}, {"best_denoising_score": -2.43}, order=HIGHER
            )
