"""Rung B-09a-1 — interpretation evidence across three tasks (L1, atomic).

Design: ``docs/design/generic_framework_upgrade/step_09_interpretation_task_blocks/
pr_09a_interpreter_evidence_ordering.md`` §3.6 / §4.8; parent §10, Q-09-5;
roadmap §22.23.7 (an ``expected/`` fixture is legitimate ONLY if the tests
consume it — this test is that consumer).

What only this rung catches
---------------------------
Every other Step-09a test drives ONE task's shape. A contract can pass all of
them and still be TIDMAD-shaped in a way nobody notices until a second task
arrives — which is exactly the history Step 09 exists to end. So the SAME
production boundaries (`tuning_output_to_model_run_summary`,
`ordering.precompute_evidence`, `prediction.evaluate_prediction`) are driven
over three materially different declarations:

===========  ==============  ============  =========================
task         primary         per-sample    declared secondaries
===========  ==============  ============  =========================
TIDMAD       higher, neg.    present       none
Pets         accuracy,       scalar-only   macro_f1 (higher)
             higher, [0,1]
DAVIS        mse, **LOWER**  scalar-only   psnr (higher), mae (absent)
===========  ==============  ============  =========================

DAVIS is the load-bearing row: under `lower`, "best" is the SMALLEST number.
A direction literal anywhere on the path inverts it, and every expectation
below is a hand-computed literal so the inversion cannot be absorbed.

Honestly an L1 rung. Pets and DAVIS have no tuner/workflow integration, and
their fixtures say so in their ``_fixture`` note. Production keeps ZERO
dependency on ``examples/`` — this test imports the fixtures, production does
not.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
from agent.schemas.interpretation import SecondaryMetricEvidence
from execute_tools.evaluation_metric import metric_spec_from_declaration
from execute_tools.metric_order import MetricOrder
from nodes.result_interpretation_agent import tuning_output_to_model_run_summary
from nodes.result_interpretation_agent.prediction import evaluate_prediction
from tests.helpers.metric_fixtures import shipped_spec

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = REPO_ROOT / "examples"

_ordering = importlib.import_module("nodes.result_interpretation_agent.ordering")


# ---------------------------------------------------------------------------
# TIDMAD — production-backed, so its fixture lives with the test (07a precedent)
# ---------------------------------------------------------------------------


def _tidmad_record(exp_id, score, *, is_trial, per_sample=None):
    return {
        "exp_id": exp_id,
        "status": "success",
        "model_type": "wavenet",
        "timestamp": "2026-08-19T00:00:00Z",
        "params": {},
        "denoising_score": score,
        "file_vector": per_sample,
        "is_trial": is_trial,
        "health_gate_enabled": False,
        "metric_result": {
            "metric_id": "tidmad_denoising_score",
            "direction": "higher",
            "scalar": score,
            "per_sample": per_sample,
        },
    }


def _tidmad_case():
    spec = shipped_spec()
    n = 20
    per_sample = [round(-2.30 + 0.01 * i, 4) for i in range(n)]
    payload = {
        "run_name": "tidmad_l1",
        "model_type": "wavenet",
        "file_index": 6,
        "status": "completed",
        "completed_rounds": 3,
        "total_attempts": 3,
        "started_at": "2026-08-19T00:00:00Z",
        "finished_at": "2026-08-19T01:00:00Z",
        "best_denoising_score": -2.00,
        "all_records": [
            _tidmad_record("t1", -2.60, is_trial=True),
            _tidmad_record("t2", -2.00, is_trial=False, per_sample=per_sample),
            _tidmad_record("t3", -2.90, is_trial=False),
        ],
        "metric_spec": json.loads(spec.model_dump_json()),
    }
    return {
        "task": "tidmad",
        "output": HyperparamTuningOutput.model_validate(payload),
        "spec": spec,
        "secondaries": [],
        # Hand-computed under `higher`: best is the LARGEST, worst the SMALLEST.
        "expected_best": -2.00,
        "expected_worst": -2.90,
        "expected_direction": "higher",
        "expected_metric_id": "tidmad_denoising_score",
        "expected_per_sample": True,
        # SOTA -2.55, actual -2.00 -> better under `higher`; gain = 0.55.
        "prediction": {"metric": "tidmad_denoising_score", "current_value": -2.55},
        "expected_outcome": "confirmed",
        "expected_gain": 0.55,
    }


def _pack_case(pack: str, task: str):
    fixture = json.loads(
        (EXAMPLES / pack / "expected" / "interpretation_evidence_l1_fixture.json").read_text(
            encoding="utf-8"
        )
    )
    assert fixture["_fixture"]["label"] == "l1_fixture"
    output = HyperparamTuningOutput.model_validate(fixture["tuning_output"])
    spec = metric_spec_from_declaration(fixture["tuning_output"]["metric_spec"])
    secondaries = [SecondaryMetricEvidence.model_validate(s) for s in fixture["secondary_metrics"]]
    scores = [r.denoising_score for r in output.all_records]
    order = MetricOrder(spec)
    prediction = fixture["prediction"]
    return {
        "task": task,
        "output": output,
        "spec": spec,
        "secondaries": secondaries,
        "expected_best": order.best(scores, key=lambda v: v),
        "expected_worst": order.worst(scores, key=lambda v: v),
        "expected_direction": spec.direction,
        "expected_metric_id": spec.id,
        "expected_per_sample": False,
        "prediction": prediction,
        "expected_outcome": prediction["_expected_outcome"],
        "expected_gain": prediction["_expected_information_gain"],
    }


CASES = {
    "tidmad": _tidmad_case,
    "pets": lambda: _pack_case("oxford_iiit_pet", "pets"),
    "davis": lambda: _pack_case("davis_future_prediction", "davis"),
}


@pytest.fixture(params=sorted(CASES), ids=sorted(CASES))
def case(request):
    return CASES[request.param]()


# ---------------------------------------------------------------------------
# The rung
# ---------------------------------------------------------------------------


class TestTheSameBoundariesServeThreeDeclarations:
    def test_the_declared_direction_is_what_orders(self, case):
        """DAVIS is the row that matters: under `lower` the best score is the
        SMALLEST, so a `>` anywhere on this path reports the worst model as
        the best."""
        summary = tuning_output_to_model_run_summary(
            case["output"], order=MetricOrder(case["spec"])
        )
        assert summary.best_valid_denoising_score == case["expected_best"]
        assert summary.worst_denoising_score == case["expected_worst"]

    def test_the_hand_computed_davis_expectation_is_the_smallest_value(self):
        """Anti-vacuity for the row above: if the DAVIS fixture's expectation
        were computed the TIDMAD way, the parametrized test would pass while
        proving nothing."""
        davis = CASES["davis"]()
        scores = [r.denoising_score for r in davis["output"].all_records]
        assert davis["expected_direction"] == "lower"
        assert davis["expected_best"] == min(scores)
        assert davis["expected_worst"] == max(scores)
        pets = CASES["pets"]()
        assert pets["expected_best"] == max(r.denoising_score for r in pets["output"].all_records)

    def test_the_evidence_borne_identity_matches_the_declaration(self, case):
        summary = tuning_output_to_model_run_summary(
            case["output"], order=MetricOrder(case["spec"])
        )
        assert summary.metric_identity is not None
        assert summary.metric_identity.metric_id == case["expected_metric_id"]
        assert summary.metric_identity.direction == case["expected_direction"]

    def test_the_precomputation_agrees_with_the_builder(self, case):
        order = MetricOrder(case["spec"])
        summary = tuning_output_to_model_run_summary(case["output"], order=order)
        summary.model_description = "d"
        evidence = _ordering.precompute_evidence([summary], {}, [summary.model_type], order=order)
        assert evidence.overall_best_score == case["output"].best_denoising_score
        assert evidence.overall_worst_score == case["expected_worst"]

    def test_the_prediction_band_is_direction_correct_for_this_task(self, case):
        result = evaluate_prediction(
            case["prediction"],
            {
                "best_denoising_score": case["output"].best_denoising_score,
                "best_file_vector": None,
            },
            order=MetricOrder(case["spec"]),
            bound_metric_id=case["spec"].id,
        )
        assert result["outcome"] == case["expected_outcome"]
        assert result["information_gain"] == pytest.approx(case["expected_gain"], abs=1e-4)

    def test_per_sample_evidence_is_a_capability_not_an_assumption(self, case):
        """Two of the three tasks are scalar-only (the 08b finding). A
        per-sample prediction form must resolve to a NAMED unavailability
        there, not to a crash or a silent zero."""
        result = evaluate_prediction(
            {"metric": "mean(file_vector[0:5])", "current_value": 1.0},
            {
                "best_denoising_score": case["output"].best_denoising_score,
                "best_file_vector": (
                    case["output"].all_records[1].file_vector
                    if case["expected_per_sample"]
                    else None
                ),
            },
            order=MetricOrder(case["spec"]),
            bound_metric_id=case["spec"].id,
        )
        if case["expected_per_sample"]:
            # UPGRADED by F-SCAND-1. This asserted the slice mean RESOLVED to
            # a value. It is now refused: the values reaching the evaluator
            # are per-file LOG scores, so a slice mean is a "mean of per-file
            # log scores", which the aggregation standard forbids for
            # Jensen's inequality gap. The rung's point is unchanged — a task WITH
            # per-sample evidence is distinguishable from one without — but
            # the distinguishing resolution is now the refusal rather than a
            # computed number.
            assert result["metric_resolution"] == "refused_forbidden_aggregation"
            assert result["actual_value"] is None
        else:
            assert result["metric_resolution"] == "per_sample_unavailable"
            assert result["outcome"] == "unevaluated"

    def test_secondaries_are_present_when_present_with_their_own_directions(self, case):
        by_id = {s.spec.id: s for s in case["secondaries"]}
        if case["task"] == "tidmad":
            assert by_id == {}, "TIDMAD declares no secondary metric (Step-06 §16-Q4)"
        elif case["task"] == "pets":
            assert by_id["macro_f1"].status == "scored"
            assert by_id["macro_f1"].spec.direction == "higher"
        else:
            assert by_id["psnr"].status == "scored"
            assert by_id["psnr"].spec.direction == "higher"
            # The third state, and the reason it exists.
            assert by_id["mae"].status == "unavailable"
            assert by_id["mae"].spec.direction == "lower"
            assert by_id["mae"].result is None, "a named absence must never carry a number"

    def test_a_secondary_never_changes_an_ordering_result(self, case):
        """The observational rule, on every task."""
        order = MetricOrder(case["spec"])
        summary = tuning_output_to_model_run_summary(case["output"], order=order)
        summary.model_description = "d"
        baseline = _ordering.precompute_evidence([summary], {}, [summary.model_type], order=order)
        with_secondaries = _ordering.precompute_evidence(
            [summary.model_copy(update={"secondary_metrics": case["secondaries"]})],
            {},
            [summary.model_type],
            order=order,
        )
        assert baseline.overall_best_score == with_secondaries.overall_best_score
        assert baseline.per_model_worst == with_secondaries.per_model_worst

    def test_a_spec_identity_mismatch_refuses_at_construction(self, case):
        """Fail-closed on every task, not only the one it was written for."""
        from pydantic import ValidationError

        from agent.schemas.interpretation import InterpretationInput

        order = MetricOrder(case["spec"])
        summary = tuning_output_to_model_run_summary(case["output"], order=order)
        wrong = case["spec"].model_copy(update={"id": "a_different_metric"})
        with pytest.raises(ValidationError, match="metric identity mismatch"):
            InterpretationInput(summaries=[summary], metric_spec=wrong)


class TestTheRungIsAtomicAndHonest:
    def test_only_the_declared_axis_varies_between_the_pack_cases(self):
        """Atomicity: Pets and DAVIS differ in their DECLARATION, not in the
        shape of the evidence around it, so a behavioural difference cannot be
        attributed to anything but the declaration."""
        pets, davis = CASES["pets"](), CASES["davis"]()
        assert len(pets["output"].all_records) == len(davis["output"].all_records)
        assert pets["expected_per_sample"] == davis["expected_per_sample"] is False
        assert pets["expected_direction"] != davis["expected_direction"]

    @pytest.mark.parametrize("pack", ["oxford_iiit_pet", "davis_future_prediction"])
    def test_the_fixture_is_labelled_l1_and_says_what_it_is_not(self, pack):
        fixture = json.loads(
            (EXAMPLES / pack / "expected" / "interpretation_evidence_l1_fixture.json").read_text(
                encoding="utf-8"
            )
        )
        meta = fixture["_fixture"]
        assert meta["label"] == "l1_fixture"
        assert meta["kind"] == "interpretation_evidence"
        assert "NOT a real tuning output" in meta["note"]
        assert "Step 10" in meta["note"], (
            "the note must name the owner of the production half, or a reader "
            "will take the secondaries block for a production capability"
        )
        assert "test_step09a_interpretation_evidence_rung" in meta["provenance"]

    @pytest.mark.parametrize("pack", ["oxford_iiit_pet", "davis_future_prediction"])
    def test_the_fixture_uses_the_packs_OWN_declared_specs(self, pack):
        """Not a hand-written copy: a fixture that restated the declaration
        could drift from it silently."""
        fixture = json.loads(
            (EXAMPLES / pack / "expected" / "interpretation_evidence_l1_fixture.json").read_text(
                encoding="utf-8"
            )
        )
        declared = {
            json.loads(p.read_text(encoding="utf-8"))["id"]: json.loads(
                p.read_text(encoding="utf-8")
            )
            for p in (EXAMPLES / pack / "declared").glob("metric_*.json")
        }
        assert (
            fixture["tuning_output"]["metric_spec"]
            == declared[fixture["tuning_output"]["metric_spec"]["id"]]
        )
        for secondary in fixture["secondary_metrics"]:
            assert secondary["spec"] == declared[secondary["spec"]["id"]]

    def test_production_does_not_import_examples(self):
        """The standing pack-governance rule, re-asserted at the Step-09a head
        because this commit is the one that adds interpretation fixtures."""
        offenders = []
        for root in ("nodes", "agent", "core", "execute_tools", "workflows"):
            for path in sorted((REPO_ROOT / root).rglob("*.py")):
                source = path.read_text(encoding="utf-8")
                if "import examples" in source or "from examples" in source:
                    offenders.append(path.relative_to(REPO_ROOT).as_posix())
        assert offenders == [], offenders
