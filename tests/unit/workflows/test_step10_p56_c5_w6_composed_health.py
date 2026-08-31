"""Generic run-scoped Health requirement transport."""

from execute_tools.health_checks.candidate_eligibility import classify_candidate_health
from execute_tools.health_checks.schemas import CandidateHealthValidity


def _record(gate_ids: set[str]) -> dict:
    return {
        "status": "success",
        "denoising_score": 0.5,
        "health_gate_results": [
            {
                "gate_name": gate_id,
                "execution_status": "passed",
                "check_passed": True,
            }
            for gate_id in sorted(gate_ids)
        ],
    }


def test_classifier_consumes_the_resolved_requirement_set() -> None:
    required = frozenset({"shape_valid", "distribution_valid"})
    complete = classify_candidate_health(_record(set(required)), required_gate_ids=required)
    incomplete = classify_candidate_health(
        _record({"shape_valid"}),
        required_gate_ids=required,
    )
    assert complete is CandidateHealthValidity.VALID
    assert incomplete is not CandidateHealthValidity.VALID


def test_empty_resolved_set_does_not_invent_task_requirements() -> None:
    result = classify_candidate_health(_record(set()), required_gate_ids=frozenset())
    assert result is CandidateHealthValidity.VALID
