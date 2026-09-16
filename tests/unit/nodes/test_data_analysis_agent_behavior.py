from __future__ import annotations

from pathlib import Path

import pytest

from agent.schemas.data_analysis.common import canonical_sha256
from tests.helpers.data_analysis_behavioral import (
    PRIMARY_CASES,
    run_behavioral_case,
    run_behavioral_matrix,
)


@pytest.mark.allow_real_subprocess
def test_same_scientific_input_changes_trajectory_only_through_advice_and_budget(
    tmp_path: Path,
) -> None:
    """Catches advice/budget being ignored, promoted to authority, or lost before reporting."""

    receipts = run_behavioral_matrix(tmp_path)
    by_id = {item["case"].case_id: item for item in receipts}

    no_advice_low = by_id["regular-none-low"]
    periodic_low = by_id["regular-periodicity-low"]
    drift_low = by_id["regular-drift-low"]
    benign_low = by_id["regular-benign-low"]
    medium = by_id["regular-none-medium"]
    high = by_id["regular-none-high"]
    exhausted = by_id["regular-exhausted"]

    # The fixture, brief and access policy remain identical while only the
    # caller request identity, advice and resource envelope vary.
    baseline_input = no_advice_low["input"]
    for receipt in (periodic_low, drift_low, benign_low, medium, high, exhausted):
        current = receipt["input"]
        assert current.available_assets == baseline_input.available_assets
        assert current.analysis_brief == baseline_input.analysis_brief
        assert current.access_policy == baseline_input.access_policy
        assert canonical_sha256(current.access_policy) == canonical_sha256(
            baseline_input.access_policy
        )

    def planned(receipt):
        return tuple(item["skill_id"] for item in receipt["plan"]["invocations"])

    assert len(planned(no_advice_low)) == 2
    assert set(planned(periodic_low)) <= {"welch_psd", "autocorrelation", "fft_peak_summary"}
    assert set(planned(drift_low)) <= {"temporal_stability_summary", "stft_energy_map"}
    assert planned(periodic_low) != planned(drift_low)
    assert planned(benign_low) == planned(no_advice_low)

    assert len(planned(medium)) > len(planned(no_advice_low))
    assert len(planned(high)) > len(planned(medium))
    assert len(set(planned(high))) == len(planned(high))
    assert {"welch_psd", "temporal_stability_summary", "autocorrelation"}.issubset(planned(high))

    for receipt in receipts:
        for stage in ("data_analysis.skill_selection", "data_analysis.plan"):
            assert receipt["prompt_receipts"][stage]["advice_visible"]
            assert receipt["prompt_receipts"][stage]["budget_visible"]
        candidates = receipt["prompt_receipts"]["data_analysis.skill_selection"][
            "candidate_skill_ids"
        ]
        assert set(planned(receipt)).issubset(candidates)
        report = receipt["report"]
        assert all(
            requirement.information_class == "data"
            for request in receipt["materialization_requests"]
            for requirement in request.requested_information
        )
        result_refs = {item.result_id for item in report.skill_result_refs}
        assert all(
            evidence.result_ref.result_id in result_refs
            and (
                finding.coverage.total_available is None
                or finding.coverage.analyzed_count <= finding.coverage.total_available
            )
            for finding in report.findings
            for evidence in finding.evidence
        )

    assert exhausted["report"].resource_usage.attempted_invocations == 0
    assert exhausted["report"].findings == ()
    assert exhausted["report"].limitations[0].limitation_id == "budget-exhausted"
    assert exhausted["report"].unresolved_questions


@pytest.mark.allow_real_subprocess
def test_irregular_periodicity_trajectory_uses_irregular_capability_without_failure_churn(
    tmp_path: Path,
) -> None:
    """Catches the planner wasting budget on regular-only spectra for certified irregular time."""

    case = next(item for item in PRIMARY_CASES if item.case_id == "irregular-periodicity-low")
    receipt = run_behavioral_case(
        case,
        tmp_path,
    )
    planned = tuple(item["skill_id"] for item in receipt["plan"]["invocations"])
    executed = tuple(item.skill_id for item in receipt["report"].skill_result_summaries)

    assert planned == ("sampling_cadence_and_gaps", "lomb_scargle_periodogram")
    assert executed == planned
    assert all(item.status == "completed" for item in receipt["report"].skill_result_summaries)
    assert not {"fft_peak_summary", "welch_psd", "stft_energy_map"} & set(executed)
    assert receipt["report"].findings
