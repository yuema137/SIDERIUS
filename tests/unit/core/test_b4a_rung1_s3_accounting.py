"""V21 PR B4a rung 1 — the frozen S3 semantics on reconstructed numbers.

No GPU, no training. Part III's rule is that **real training is never the
discovery tool**, so the semantics is exercised deterministically first
and the live rungs only confirm.

Two things are proved here that the Stage B unit tests do not:

1. **The V20 numbers, replayed.** The P6.4 evidence is the reason PR B
   exists; the semantics has to be checked against it rather than against
   invented values. Only figures actually recorded in the design ledger
   are used, at the precision they were recorded — see `_V20` below.
2. **Non-retroactivity.** S3's hardest requirement is a negative: a
   realized peak above the threshold, discovered after the phase ran,
   must not reach back and change the admission that was already made.
   Nothing in the admission path may consult it.

Design doc: ``docs/design/v21_priorities/pr_b_resource_budget_semantics.md``
§0.1 (V20 posture), §B0.E (frozen S3), Commit B4a.
"""

from __future__ import annotations

import pytest

from core.runtime_control.decision_policy import (
    RuntimeBudget,
    RuntimeDecisionPolicy,
    RuntimeMode,
)
from core.runtime_control.estimate_types import make_estimate
from core.runtime_control.realized_memory import (
    realized_vs_admitted,
    threshold_exceedance_notices,
)

_GB_MIB = 1024

#: Recorded V20 attempt-3 facts, at the precision the ledger records them.
#: Nothing here is interpolated: §0.1 records the declared budget and the
#: realized figure, §B4a records the two co-resident peaks and the free
#: memory at the time. A number not in the artifacts is not invented.
_V20 = {
    "declared_budget_gib": 12.0,  # --{trial,formal}_vram_budget_gb 12
    "realized_peak_gib": 20.13,  # §0.1, the figure that OOMed
    "coresident_a_gib": 17.46,  # §B4a rung 1 plan
    "coresident_b_gib": 13.45,
    "free_at_the_time_mib": 149,
}

_FORMAL = RuntimeMode(phase="formal", candidate_stage="post_implementation", probe_available=True)
_TIME_ONLY = 99_999.0


def _evidence(peak_gb, *, blocking: bool):
    """A candidate estimate at one of the two evidence grades S3 names."""
    if blocking:
        return make_estimate(
            provenance="bounded_live_probe",
            confidence="medium",
            expected_seconds=100.0,
            peak_vram_gb=peak_gb,
            concurrency_identity="single_candidate_idle",
            measurement_validity="valid_current_conditions",
            verification_passed=True,
            steady_state=True,
        )
    return make_estimate(
        provenance="static_uncalibrated",
        confidence="low",
        expected_seconds=100.0,
        peak_vram_gb=peak_gb,
    )


@pytest.fixture
def policy():
    return RuntimeDecisionPolicy()


class TestTheEightCaseMatrix:
    """Every case §11 rung 1 names, asserted on decision AND grade AND reason."""

    @pytest.mark.parametrize(
        ("label", "peak", "blocking", "budget_gb", "expect_kind", "expect_reason"),
        [
            ("measured below", 8.0, True, 12.0, "ALLOW", None),
            ("measured above", 20.0, True, 12.0, "REJECT", "measured peak VRAM"),
            ("projected below", 8.0, False, 12.0, "ALLOW", None),
            ("projected above", 20.0, False, 12.0, "ADVISORY", "projected peak VRAM"),
            ("equality boundary", 12.0, True, 12.0, "ALLOW", None),
            ("no operator budget", 20.0, True, None, "ALLOW", None),
            ("unavailable evidence", None, True, 12.0, "ALLOW", None),
            # physical cap BELOW the operator budget: admission is handed the
            # EFFECTIVE threshold, so the physical cap is what binds.
            ("physical cap binds", 30.0, True, 25.0, "REJECT", "measured peak VRAM"),
        ],
    )
    def test_case(self, policy, label, peak, blocking, budget_gb, expect_kind, expect_reason):
        decision = policy.decide(
            _evidence(peak, blocking=blocking),
            RuntimeBudget(time_seconds=_TIME_ONLY, vram_gb=budget_gb),
            _FORMAL,
        )
        assert decision.kind == expect_kind, f"{label}: {decision.reasons}"
        if expect_reason is None:
            assert not any("VRAM" in r for r in decision.reasons), label
        else:
            assert any(expect_reason in r for r in decision.reasons), f"{label}: {decision.reasons}"

    def test_the_two_grades_differ_on_identical_numbers(self, policy):
        """The whole point of "graded": same peak, same threshold, different
        authority. If these ever agree, S3 has collapsed into S1 or S2."""
        args = (RuntimeBudget(time_seconds=_TIME_ONLY, vram_gb=12.0), _FORMAL)
        measured = policy.decide(_evidence(20.0, blocking=True), *args)
        projected = policy.decide(_evidence(20.0, blocking=False), *args)
        assert (measured.kind, projected.kind) == ("REJECT", "ADVISORY")


class TestTheV20Replay:
    """The recorded P6.4 numbers, run through the frozen semantics.

    What this establishes is narrow and worth stating precisely: **had the
    threshold been armed and had a bounded probe measured the true peak,
    admission would have refused.** It does NOT establish that V20 would
    have avoided the OOM — V20's admission never had a measured peak to
    judge, which is exactly §B0.E's finding, and B1 could not have
    supplied one either.
    """

    def test_the_realized_peak_would_have_been_refused_as_measured_evidence(self, policy):
        decision = policy.decide(
            _evidence(_V20["realized_peak_gib"], blocking=True),
            RuntimeBudget(time_seconds=_TIME_ONLY, vram_gb=_V20["declared_budget_gib"]),
            _FORMAL,
        )
        assert decision.kind == "REJECT"
        assert any("20.13 GB exceeds budget 12.00 GB" in r for r in decision.reasons)

    def test_the_same_number_as_a_FORECAST_would_only_have_advised(self, policy):
        """And this is why V20 proceeded.

        A forecast above the threshold is advisory under S3 — deliberately,
        because a static prior is not evidence about this candidate. The
        remedy S3 offers is not "block on forecasts" but "get a
        measurement", which is what the probe path now supplies.
        """
        decision = policy.decide(
            _evidence(_V20["realized_peak_gib"], blocking=False),
            RuntimeBudget(time_seconds=_TIME_ONLY, vram_gb=_V20["declared_budget_gib"]),
            _FORMAL,
        )
        assert decision.kind == "ADVISORY"

    def test_each_coresident_peak_alone_exceeds_the_declared_budget(self, policy):
        """17.46 and 13.45 GiB against a declared 12 GiB.

        Recorded because it bears on B4b: neither candidate was within the
        budget on its own, so the pair's failure is not purely a
        concurrency effect. Aggregate/pair accounting is P6.4 territory and
        remains out of PR B's scope.
        """
        for key in ("coresident_a_gib", "coresident_b_gib"):
            decision = policy.decide(
                _evidence(_V20[key], blocking=True),
                RuntimeBudget(time_seconds=_TIME_ONLY, vram_gb=_V20["declared_budget_gib"]),
                _FORMAL,
            )
            assert decision.kind == "REJECT", key

    def test_the_free_memory_figure_is_carried_but_not_used_as_candidate_evidence(self):
        """149 MiB free is device CONTEXT, not this candidate's usage.

        Asserted as a property of the observation, not the policy: nothing
        in the candidate's realized row is derived from device-level free
        memory. Peer and device state may explain a failure; they may not
        become the candidate's measurement.
        """
        row = realized_vs_admitted(
            "training",
            resource_check={"estimated_gb": 8.0, "limit_gb": 12.0, "vram_budget_gb": 12.0},
            runtime_verification={
                "components": {
                    "training": {
                        "realized_memory": {
                            "reserved_peak_mib": int(_V20["realized_peak_gib"] * _GB_MIB),
                            "measurement_completeness": "complete",
                            "owning_process_pid": 1234,
                        }
                    }
                }
            },
        )
        assert row is not None
        assert row.realized_peak_mib == int(_V20["realized_peak_gib"] * _GB_MIB)
        assert row.owning_process_pid == 1234
        # No field anywhere carries device-level free memory into the
        # candidate's own account.
        dumped = row.model_dump()
        assert not any("free" in k for k in dumped)


class TestPostAdmissionExceedanceIsNotRetroactive:
    """S3's hardest requirement is a negative one."""

    def test_a_realized_exceedance_does_not_change_the_admission(self, policy):
        """Same inputs, decided before and after the exceedance is recorded.

        The admission is a function of the pre-phase estimate and the
        threshold. Recording a realized peak afterwards must leave it
        bit-identical — the notice is downstream of the decision, never an
        input to it.
        """
        estimate = _evidence(8.0, blocking=True)  # admitted: forecast under budget
        budget = RuntimeBudget(time_seconds=_TIME_ONLY, vram_gb=12.0)
        before = policy.decide(estimate, budget, _FORMAL)
        assert before.kind == "ALLOW"

        # ...the phase then realizes 20 GiB, and a notice is produced.
        row = realized_vs_admitted(
            "training",
            resource_check={"estimated_gb": 8.0, "limit_gb": 12.0, "vram_budget_gb": 12.0},
            runtime_verification={
                "components": {
                    "training": {
                        "realized_memory": {
                            "reserved_peak_mib": 20 * _GB_MIB,
                            "measurement_completeness": "complete",
                        }
                    }
                }
            },
        )
        assert row is not None and row.realized_above_threshold is True
        assert len(threshold_exceedance_notices({"training": row})) == 1

        after = policy.decide(estimate, budget, _FORMAL)
        assert after.kind == before.kind == "ALLOW"
        assert after.reasons == before.reasons
        assert after.evidence_provenance == before.evidence_provenance

    def test_the_exceedance_is_recorded_rather_than_discarded(self):
        """Non-retroactive must not mean unrecorded — that would be S1."""
        row = realized_vs_admitted(
            "training",
            resource_check={"estimated_gb": 8.0, "limit_gb": 12.0, "vram_budget_gb": 12.0},
            runtime_verification={
                "components": {
                    "training": {
                        "realized_memory": {
                            "reserved_peak_mib": 20 * _GB_MIB,
                            "measurement_completeness": "complete",
                        }
                    }
                }
            },
        )
        assert row is not None
        assert row.realized_minus_threshold_mib == 8 * _GB_MIB
        assert row.realized_minus_estimated_mib == 12 * _GB_MIB
        notice = threshold_exceedance_notices({"training": row})[0]
        assert notice.action_taken == "none_recorded_only"
