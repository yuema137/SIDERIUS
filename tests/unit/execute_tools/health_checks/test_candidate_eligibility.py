from __future__ import annotations

import math

import pytest

from execute_tools.health_checks.candidate_eligibility import (
    CandidateHealthValidity,
    classify_candidate_health,
)

REQUIRED = {"diversity", "output_std", "amplitude"}


def _gate(
    name: str,
    *,
    execution_status: str = "passed",
    check_passed: bool | None = True,
    would_invalidate: bool = False,
) -> dict:
    return {
        "gate_name": name,
        "execution_status": execution_status,
        "check_passed": check_passed,
        "would_invalidate_under_production_policy": would_invalidate,
        "resolved_action": "continue",
    }


def _record(**overrides) -> dict:
    record = {
        "status": "success",
        "denoising_score": 1.25,
        "health_gate_results": [_gate(name) for name in REQUIRED]
        + [_gate("recording", execution_status="failed", check_passed=False)],
    }
    record.update(overrides)
    return record


def _classify(record: dict) -> CandidateHealthValidity:
    return classify_candidate_health(record, required_gate_ids=REQUIRED)


def test_all_required_blocking_checks_pass() -> None:
    assert _classify(_record()) is CandidateHealthValidity.VALID


def test_recording_failure_does_not_invalidate() -> None:
    assert _classify(_record()) is CandidateHealthValidity.VALID


@pytest.mark.parametrize("execution_status", ["not_run", "error"])
def test_unobserved_required_gate_is_unknown(execution_status: str) -> None:
    gates = [_gate(name) for name in REQUIRED]
    gates[0] = _gate(gates[0]["gate_name"], execution_status=execution_status, check_passed=None)
    assert _classify(_record(health_gate_results=gates)) is CandidateHealthValidity.UNKNOWN


def test_missing_required_gate_is_unknown() -> None:
    assert _classify(_record(health_gate_results=[_gate("diversity")])) is (
        CandidateHealthValidity.UNKNOWN
    )


def test_failed_check_is_invalid_even_when_action_continues() -> None:
    gates = [_gate(name) for name in REQUIRED]
    gates[0] = _gate(gates[0]["gate_name"], execution_status="failed", check_passed=False)
    assert _classify(_record(health_gate_results=gates)) is CandidateHealthValidity.INVALID


def test_counterfactual_invalidation_is_invalid() -> None:
    gates = [_gate(name) for name in REQUIRED]
    gates[0] = _gate(gates[0]["gate_name"], would_invalidate=True)
    assert _classify(_record(health_gate_results=gates)) is CandidateHealthValidity.INVALID


def test_mode_collapse_status_is_invalid() -> None:
    assert _classify(_record(status="failed_mode_collapse")) is CandidateHealthValidity.INVALID


def test_legacy_record_without_metadata_is_unknown() -> None:
    assert _classify(_record(health_gate_results=[])) is CandidateHealthValidity.UNKNOWN


@pytest.mark.parametrize("score", [math.nan, math.inf, -math.inf, None])
def test_non_finite_or_missing_score_is_invalid(score: float | None) -> None:
    assert _classify(_record(denoising_score=score)) is CandidateHealthValidity.INVALID


# ---------------------------------------------------------------------------
# DataScope DS5 — self-describing disabled-mode records (Option B)
# ---------------------------------------------------------------------------


def test_disabled_run_success_record_is_valid_without_gates() -> None:
    """health_gate_enabled=False stamped on the record waives the gate
    requirement — successful finite-score records are VALID."""
    record = _record(health_gate_results=[], health_gate_enabled=False)
    assert _classify(record) is CandidateHealthValidity.VALID


def test_disabled_run_failed_status_still_invalid() -> None:
    record = _record(status="error_training", health_gate_enabled=False)
    assert _classify(record) is CandidateHealthValidity.INVALID


def test_disabled_run_non_finite_score_still_invalid() -> None:
    record = _record(denoising_score=math.inf, health_gate_enabled=False)
    assert _classify(record) is CandidateHealthValidity.INVALID


def test_enabled_true_stamp_takes_normal_path() -> None:
    """Explicit True behaves exactly like the legacy absent/None stamp."""
    record = _record(health_gate_results=[], health_gate_enabled=True)
    assert _classify(record) is CandidateHealthValidity.UNKNOWN


def test_legacy_none_stamp_takes_normal_path() -> None:
    record = _record(health_gate_results=[], health_gate_enabled=None)
    assert _classify(record) is CandidateHealthValidity.UNKNOWN


# ---------------------------------------------------------------------------
# Step 08a C3 — inapplicable is excluded from the required set; error is not
# ---------------------------------------------------------------------------


def _inapplicable_gate(name: str, verdicts: dict[str, str]) -> dict:
    """A gate that did not run, carrying the typed reason it did not."""
    gate = _gate(name, execution_status="not_run", check_passed=True)
    gate["check_verdicts"] = verdicts
    return gate


class TestInapplicableExclusion:
    def test_all_inapplicable_required_gate_does_not_make_the_round_unknown(self):
        """There was nothing for that gate to establish about this task.

        UNKNOWN means "evidence is missing". An inapplicable check is not
        missing evidence — it is a statement that the question does not
        arise, which is exactly the distinction the typed verdict added.
        """
        record = _record(
            health_gate_results=[
                _gate("diversity"),
                _gate("output_std"),
                _inapplicable_gate("amplitude", {"amplitude_collapse": "inapplicable"}),
            ]
        )
        assert (
            classify_candidate_health(record, required_gate_ids=REQUIRED)
            is CandidateHealthValidity.VALID
        )

    def test_errored_required_gate_is_never_excluded(self):
        """ "We could not compute it" IS missing evidence — fail closed."""
        record = _record(
            health_gate_results=[
                _gate("diversity"),
                _gate("output_std"),
                _inapplicable_gate("amplitude", {"amplitude_collapse": "error"}),
            ]
        )
        assert (
            classify_candidate_health(record, required_gate_ids=REQUIRED)
            is CandidateHealthValidity.UNKNOWN
        )

    def test_partially_inapplicable_gate_is_not_excluded(self):
        """One inapplicable check among several does not excuse the gate."""
        record = _record(
            health_gate_results=[
                _gate("diversity"),
                _gate("output_std"),
                _inapplicable_gate(
                    "amplitude",
                    {"amplitude_collapse": "inapplicable", "output_diversity": "error"},
                ),
            ]
        )
        assert (
            classify_candidate_health(record, required_gate_ids=REQUIRED)
            is CandidateHealthValidity.UNKNOWN
        )

    def test_legacy_record_without_verdicts_keeps_pre_08a_behaviour(self):
        """Absence of verdicts is not inapplicability.

        A pre-08a record has no ``check_verdicts`` at all. Reading that as
        "nothing applied here" would silently promote historical UNKNOWN
        rounds to VALID — inventing evidence that was never recorded.
        """
        record = _record(
            health_gate_results=[
                _gate("diversity"),
                _gate("output_std"),
                _gate("amplitude", execution_status="not_run"),
            ]
        )
        assert (
            classify_candidate_health(record, required_gate_ids=REQUIRED)
            is CandidateHealthValidity.UNKNOWN
        )

    def test_empty_verdict_map_is_not_inapplicability(self):
        record = _record(
            health_gate_results=[
                _gate("diversity"),
                _gate("output_std"),
                _inapplicable_gate("amplitude", {}),
            ]
        )
        assert (
            classify_candidate_health(record, required_gate_ids=REQUIRED)
            is CandidateHealthValidity.UNKNOWN
        )

    def test_tidmad_shaped_record_is_unaffected(self):
        """Every check applicable ⇒ the required set is exactly what it was."""
        record = _record(
            health_gate_results=[
                dict(_gate(name), check_verdicts={name: "passed"}) for name in REQUIRED
            ]
        )
        assert (
            classify_candidate_health(record, required_gate_ids=REQUIRED)
            is CandidateHealthValidity.VALID
        )
