"""Framework Health classification is independent of task codecs."""

from execute_tools.health_checks.candidate_eligibility import classify_candidate_health
from execute_tools.health_checks.schemas import CandidateHealthValidity


def test_failed_required_gate_invalidates_a_finite_result() -> None:
    record = {
        "status": "success",
        "denoising_score": 1.0,
        "health_gate_results": [{"gate_name": "required", "execution_status": "failed"}],
    }
    assert (
        classify_candidate_health(record, required_gate_ids={"required"})
        is CandidateHealthValidity.INVALID
    )
