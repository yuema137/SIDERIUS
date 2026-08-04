"""A neighbour's presence is not contamination. Nor is its oscillation.

V20 PR C2, operator decisions 2026-08-04 and 2026-08-05. This rule has been
wrong twice in the same direction, and every case here names one of the ways.

The regression fixture is REAL: the six formal arms of Gate 2 Lite-A attempt
20, run against a live neighbour oscillating 692-844 MiB, sealed in
`c2_lite_a20_7f8e9ffabdef_c12a__sub1.json`. Attempt 20 refused all three
pairs on a pooled 150 MiB range while every arm measured an identical
1476 MiB -- the artifacts refuted the refusal they were subjected to. Those
exact samples now hold the rule to that outcome.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from core.runtime_control.environment_stability import (
    COMPARABLE_REQUIRED_CASES,
    CONTROLLED_NEIGHBOUR_CASES,
    ArmEnvironment,
    assess_environment,
    assess_pair_comparability,
    requirement_for_case,
    summarize_arm,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
HARNESS = REPO_ROOT / "scripts" / "c2_prephase_validation.py"
MODULE = REPO_ROOT / "core" / "runtime_control" / "environment_stability.py"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "c2_lite_a20_case12_environment.json"


@pytest.fixture(scope="module")
def attempt20() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _sample(at: float, *, own=0, other=None, total=None):
    """One driver reading as the artifact stores it -- plain dicts, so the
    tests exercise the replay shape the Gate's own evidence uses."""
    rows = [{"pid": pid, "used_mib": mib} for pid, mib in (other or [])]
    used = own + sum(r["used_mib"] for r in rows)
    return {
        "at": at,
        "telemetry_available": True,
        "own_tree_mib": own,
        "own_processes": [{"pid": 1001, "used_mib": own}] if own else [],
        "other_processes": rows,
        "other_mib": sum(r["used_mib"] for r in rows),
        "device_used_mib": total if total is not None else used,
    }


def _missed(at: float):
    return {"at": at, "telemetry_available": False}


def _arm(name, samples, **kw):
    kw.setdefault("candidate_peak_mib", 1476)
    kw.setdefault("admission_result", "admitted")
    kw.setdefault("identity", "punet/cfg-c12a")
    kw.setdefault("sampling_complete", True)
    return summarize_arm(name, samples, **kw)


def _replay(pair: dict):
    """The pair, through the SAME summarize/assess path the harness uses."""
    arms = []
    for name in pair["order"]:
        v = pair["arms"][name]
        arms.append(
            summarize_arm(
                name,
                v["samples"],
                candidate_peak_mib=v["training_peak_mib"],
                admission_result=v["admission"],
                identity="punet/cfg-c12a",
                sampling_complete=v["training_sampling_complete"]
                and v["inference_sampling_complete"],
                samples_missed=v["training_samples_missed"] + v["inference_samples_missed"],
            )
        )
    return assess_pair_comparability(arms[0], arms[1], case="c12a")


# ─────────────────────────────────────────────────────────────────────────
# The attempt-20 regression: the false negative must not recur
# ─────────────────────────────────────────────────────────────────────────


class TestTheAttempt20FalseNegative:
    def test_every_pair_is_comparable(self, attempt20):
        """THE regression. All three were refused; all three must pass."""
        for pair in attempt20["pairs"]:
            r = _replay(pair)
            assert r.pair_comparable is True, (
                f"pair {pair['pair']} refused again: {list(r.blocking_reasons)}"
            )
            assert r.blocking_reasons == ()

    def test_the_oscillation_is_still_reported(self, attempt20):
        """Recorded, not refused. Losing the observation would trade one
        error for its opposite -- silence about a real environment."""
        for pair in attempt20["pairs"]:
            r = _replay(pair)
            assert r.environment_shift_observed is True
            assert "varied" in r.shift_detail

    def test_the_observed_range_really_is_132_to_150_mib(self, attempt20):
        """Pins the fixture to the run it came from. If these numbers drift,
        the fixture was regenerated and no longer witnesses the incident."""
        ranges = sorted(
            {
                a.external_range_mib
                for pair in attempt20["pairs"]
                for a in _replay(pair).arms
                if a.external_range_mib
            }
        )
        assert ranges == [120, 132, 150], ranges

    def test_all_six_candidate_peaks_stay_1476(self, attempt20):
        peaks = {v["training_peak_mib"] for p in attempt20["pairs"] for v in p["arms"].values()}
        assert peaks == {1476}

    def test_all_six_inference_peaks_stay_3434(self, attempt20):
        peaks = {v["inference_peak_mib"] for p in attempt20["pairs"] for v in p["arms"].values()}
        assert peaks == {3434}

    def test_admission_is_identical_on_every_arm(self, attempt20):
        assert {v["admission"] for p in attempt20["pairs"] for v in p["arms"].values()} == {
            "admitted"
        }

    def test_one_arm_was_flat_while_its_partner_moved(self, attempt20):
        """WHY concatenation was wrong, in the real data. Pair 1's
        with-probe arm never moved at all; the 150 MiB 'shift between arms'
        was entirely the OTHER arm's internal wobble."""
        r = _replay(attempt20["pairs"][0])
        by_name = {a.arm: a for a in r.arms}
        assert by_name["with_probe"].external_range_mib == 0
        assert by_name["without_probe"].external_range_mib == 150
        assert r.pair_comparable is True


# ─────────────────────────────────────────────────────────────────────────
# What is accepted
# ─────────────────────────────────────────────────────────────────────────


class TestAcceptedConditions:
    def test_a_stable_neighbour_is_accepted(self):
        s = [_sample(float(i), own=1476, other=[(2001, 800)]) for i in range(6)]
        r = assess_pair_comparability(_arm("a", s), _arm("b", s), case="c12a")
        assert r.pair_comparable is True
        assert r.environment_shift_observed is False

    def test_oscillation_on_both_arms_is_accepted(self):
        a = [_sample(float(i), own=1476, other=[(2001, 700 + 150 * (i % 2))]) for i in range(8)]
        b = [_sample(float(i), own=1476, other=[(2001, 720 + 130 * (i % 2))]) for i in range(8)]
        r = assess_pair_comparability(_arm("a", a), _arm("b", b), case="c12a")
        assert r.pair_comparable is True
        assert r.environment_shift_observed is True

    def test_a_neighbour_in_only_one_arm_is_recorded_not_refused(self):
        """The instruction exactly: recorded, and invalidating only when it
        affects the acceptance result. Here both arms measured 1476, so it
        did not."""
        a = [_sample(float(i), own=1476, other=[(2001, 800)]) for i in range(5)]
        b = [_sample(float(i), own=1476) for i in range(5)]
        r = assess_pair_comparability(_arm("a", a), _arm("b", b), case="c12a")
        assert r.pair_comparable is True
        assert r.environment_shift_observed is True
        assert "membership differs" in r.shift_detail

    def test_a_real_probe_effect_under_matched_conditions_stays_comparable(self):
        """The case must keep its power. Different peaks under IDENTICAL
        surroundings is a genuine perturbation finding, not a confound --
        if this refused, Case 12 could never report the thing it exists to
        detect."""
        s = [_sample(float(i), own=1476, other=[(2001, 800)]) for i in range(5)]
        r = assess_pair_comparability(
            _arm("a", s, candidate_peak_mib=1476),
            _arm("b", s, candidate_peak_mib=1600),
            case="c12a",
        )
        assert r.pair_comparable is True, "a real probe effect was suppressed as contamination"


# ─────────────────────────────────────────────────────────────────────────
# What is still refused — effect-based, every one
# ─────────────────────────────────────────────────────────────────────────


class TestRefusedConditions:
    def _pair(self, **b_kw):
        s = [_sample(float(i), own=1476, other=[(2001, 800)]) for i in range(5)]
        return assess_pair_comparability(_arm("a", s), _arm("b", s, **b_kw), case="c12a")

    def test_incomplete_sampling_refuses(self):
        s = [_sample(0.0, own=1476), _missed(1.0), _sample(2.0, own=1476)]
        r = assess_pair_comparability(
            _arm("a", [_sample(float(i), own=1476) for i in range(4)]),
            _arm("b", s, sampling_complete=False),
            case="c12a",
        )
        assert r.pair_comparable is False
        assert any("sampling incomplete" in x for x in r.blocking_reasons)

    def test_external_termination_refuses(self):
        r = self._pair(externally_terminated=True)
        assert r.pair_comparable is False
        assert any("terminated from outside" in x for x in r.blocking_reasons)

    def test_capacity_induced_failure_refuses(self):
        """c5's lesson: a failure caused by the DEVICE being full given other
        tenants is not a candidate property."""
        r = self._pair(capacity_induced_failure=True)
        assert r.pair_comparable is False
        assert any("external-capacity cause" in x for x in r.blocking_reasons)

    def test_exhausted_free_capacity_refuses(self):
        s = [_sample(float(i), own=1476, other=[(2001, 800)], total=32607) for i in range(4)]
        r = assess_pair_comparability(
            _arm("a", s, device_total_mib=32607),
            _arm("b", s, device_total_mib=2276),  # nothing left
            case="c12a",
        )
        assert r.pair_comparable is False
        assert any("free memory reached zero" in x for x in r.blocking_reasons)

    def test_missing_attribution_refuses(self):
        """A peak with no owned process behind it describes nothing."""
        s = [_sample(float(i), own=0, other=[(2001, 800)]) for i in range(4)]
        r = assess_pair_comparability(
            _arm("a", [_sample(float(i), own=1476) for i in range(4)]),
            _arm("b", s),
            case="c12a",
        )
        assert r.pair_comparable is False
        assert any("no candidate-owned process" in x for x in r.blocking_reasons)

    def test_different_identities_refuse(self):
        s = [_sample(float(i), own=1476) for i in range(4)]
        r = assess_pair_comparability(
            _arm("a", s), _arm("b", s, identity="punet/other-config"), case="c12a"
        )
        assert r.pair_comparable is False
        assert any("different candidates" in x for x in r.blocking_reasons)

    def test_disagreement_under_disjoint_conditions_refuses(self):
        """The one case where a peak difference IS unattributable: the arms
        met conditions with no overlap at all."""
        a = [_sample(float(i), own=1476, other=[(2001, 700)]) for i in range(5)]
        b = [_sample(float(i), own=2400, other=[(2001, 9000)]) for i in range(5)]
        r = assess_pair_comparability(
            _arm("a", a, candidate_peak_mib=1476),
            _arm("b", b, candidate_peak_mib=2400),
            case="c12a",
        )
        assert r.pair_comparable is False
        assert any("cannot be attributed to the probe" in x for x in r.blocking_reasons)

    def test_differing_admission_under_disjoint_conditions_refuses(self):
        a = [_sample(float(i), own=1476, other=[(2001, 700)]) for i in range(5)]
        b = [_sample(float(i), own=1476, other=[(2001, 9000)]) for i in range(5)]
        r = assess_pair_comparability(
            _arm("a", a, admission_result="admitted"),
            _arm("b", b, admission_result="rejected"),
            case="c12a",
        )
        assert r.pair_comparable is False


class TestTheWholeSeriesIsUsed:
    def test_equal_endpoints_cannot_hide_a_mid_arm_event(self):
        """The 2026-08-04 amendment, still enforced. A neighbour that starts
        after the first sample and exits before the last leaves both
        endpoints identical."""
        s = [
            _sample(0.0, own=1476),
            _sample(1.0, own=1476, other=[(2001, 8000)]),
            _sample(2.0, own=1476, other=[(2001, 8000)]),
            _sample(3.0, own=1476),
        ]
        arm = _arm("a", s)
        assert arm.external_pids == (2001,), "a before/after rule would have missed this"
        assert arm.max_external_mib == 8000
        assert arm.external_range_mib == 8000

    def test_a_failed_query_is_missed_not_an_empty_device(self):
        arm = _arm(
            "a",
            [_sample(0.0, own=1476, other=[(2001, 800)]), _missed(1.0)],
            sampling_complete=False,
        )
        assert arm.samples_missed == 1
        assert arm.min_external_mib == 800, "a gap must not read as the neighbour leaving"


# ─────────────────────────────────────────────────────────────────────────
# Structural: the defect cannot come back
# ─────────────────────────────────────────────────────────────────────────


class TestTheOldRulesAreGone:
    def test_no_absolute_mib_threshold_survives(self):
        """MUTATION TARGET: reintroducing a fixed tolerance.

        The number is not replaced by a bigger number; refusal is
        effect-based, so there is nothing to tune.
        """
        source = MODULE.read_text(encoding="utf-8")
        tree = ast.parse(source)
        offenders = [
            n.targets[0].id
            for n in ast.walk(tree)
            if isinstance(n, ast.Assign)
            and n.targets
            and isinstance(n.targets[0], ast.Name)
            and "DELTA_MIB" in n.targets[0].id.upper()
        ]
        assert not offenders, f"an absolute MiB refusal threshold is back: {offenders}"

    def test_the_harness_does_not_pool_the_arms(self):
        """MUTATION TARGET: concatenating both arms' samples again.

        The pooled range is what refused attempt 20. The harness must
        summarize each arm and compare, never build one series from both.
        """
        tree = ast.parse(HARNESS.read_text(encoding="utf-8"))
        fn = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "run_formal_comparison"
        )
        called = {
            c.func.id
            for c in ast.walk(fn)
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
        }
        assert "summarize_formal_arm" in called, "arms are no longer summarized individually"
        assert "assess_pair_comparability" in called
        assert "assess_environment" not in called, (
            "the single-arm assessor is being fed a pooled pair again"
        )

    def test_shift_and_comparability_are_separate_fields(self):
        """Conflating them IS the defect. Two names, two meanings."""
        s = [_sample(float(i), own=1476, other=[(2001, 700 + 200 * (i % 2))]) for i in range(6)]
        r = assess_pair_comparability(_arm("a", s), _arm("b", s), case="c12a")
        assert r.environment_shift_observed is True
        assert r.pair_comparable is True

    def test_the_harness_no_longer_uses_a_single_pid_as_ownership(self):
        """The 2026-08-04 defect. Ownership is by ancestry."""
        tree = ast.parse(HARNESS.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            if "own" not in [t.id for t in node.targets if isinstance(t, ast.Name)]:
                continue
            assert not isinstance(node.value, ast.Set), (
                "ownership is by ancestry, not a single-PID set"
            )


class TestNoCaseRequiresAnIdleDevice:
    @pytest.mark.parametrize("case", ["c1", "c2", "c4", "c5", "c7", "c9", "c10", "c11", "c12a"])
    def test_no_case_demands_an_empty_card(self, case):
        assert requirement_for_case(case) != "quiet"

    @pytest.mark.parametrize("case", sorted(COMPARABLE_REQUIRED_CASES))
    def test_paired_cases_need_comparable_conditions(self, case):
        assert requirement_for_case(case) == "comparable"

    def test_c9_requires_its_controlled_neighbour(self):
        assert requirement_for_case("c9") == "controlled_neighbour"
        assert "c9" in CONTROLLED_NEIGHBOUR_CASES
        quiet = _arm("c9", [_sample(float(i), own=1474) for i in range(4)])
        assert assess_environment(quiet, case="c9").acceptable is False
        withn = _arm("c9", [_sample(float(i), own=1474, other=[(2001, 500)]) for i in range(4)])
        assert assess_environment(withn, case="c9").acceptable is True

    def test_c9_still_excludes_the_neighbour_from_the_requirement(self):
        """Attempt 20's live c9, replayed: 1474 MiB measured with a 1714 MiB
        neighbour resident. 1474, never 3188."""
        arm = _arm(
            "c9",
            [_sample(0.0, own=1474, other=[(2001, 1008), (2002, 706)])],
            candidate_peak_mib=1474,
        )
        assert arm.candidate_peak_mib == 1474
        assert arm.max_external_mib == 1714
        assert arm.max_device_used_mib == 1474 + 1714

    def test_an_ordinary_case_tolerates_a_moving_neighbour(self):
        arm = _arm(
            "c1",
            [_sample(float(i), own=1474, other=[(2001, 700 + 150 * (i % 2))]) for i in range(6)],
        )
        a = assess_environment(arm, case="c1")
        assert a.acceptable is True
        assert a.environment_shift_observed is True


class TestHeadroomStillCountsEveryone:
    def test_device_occupancy_includes_the_neighbour(self):
        """The one place external memory MUST be counted: how much room is
        left, as opposed to what the candidate needs."""
        arm = _arm("a", [_sample(0.0, own=1476, other=[(2001, 1714)])])
        assert arm.candidate_peak_mib == 1476
        assert arm.max_device_used_mib == 1476 + 1714
        assert arm.max_external_mib == 1714


class TestArmSummaryShape:
    def test_it_reads_pydantic_samples_and_dicts_alike(self):
        """The replay path and the live path must reach one implementation.
        A second reader would let a fixture pass while the Gate failed."""
        from core.runtime_control.gpu_accounting import ProcessOccupancy
        from core.runtime_control.gpu_measurement_sampler import TreeMemorySample

        live = TreeMemorySample(
            at=1.0,
            telemetry_available=True,
            own_tree_mib=1476,
            own_processes=(ProcessOccupancy(pid=1001, used_mib=1476),),
            other_processes=(ProcessOccupancy(pid=2001, used_mib=800),),
            other_mib=800,
            device_used_mib=2276,
        )
        replayed = _sample(1.0, own=1476, other=[(2001, 800)])
        a, b = _arm("live", [live]), _arm("replay", [replayed])
        assert a.external_pids == b.external_pids == (2001,)
        assert a.max_external_mib == b.max_external_mib == 800
        assert a.max_device_used_mib == b.max_device_used_mib == 2276

    def test_the_median_is_reported(self):
        arm = _arm(
            "a",
            [_sample(float(i), own=1476, other=[(2001, m)]) for i, m in enumerate([700, 800, 900])],
        )
        assert (arm.min_external_mib, arm.median_external_mib, arm.max_external_mib) == (
            700,
            800,
            900,
        )
