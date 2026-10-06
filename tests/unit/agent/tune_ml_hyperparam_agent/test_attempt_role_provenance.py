"""#369: roles survive actual failure producers and attempt-local resets."""

import pytest

from core.record_role import formal_evidence_of

from .test_error_ordering_provenance import run_failure


@pytest.mark.parametrize(
    "phase,payload",
    [
        (
            "time_preflight",
            {
                "feasible": False,
                "breakdown": {"over_effective_budget": True},
                "estimated_minutes": 2,
                "limit_minutes": 1,
            },
        ),
        ("evaluate_vram_skill", {"status": "schema_violation", "violations": []}),
        ("training_skill", {"status": "error", "message": "failed"}),
        ("training_skill", {"status": "rejected_time_risk", "message": "measured refusal"}),
        ("inference_skill", {"status": "error", "message": "failed"}),
        ("denoising_score_skill", RuntimeError("scoring failed")),
        (
            "training_skill",
            {
                "status": "skipped_resource_admission",
                "admission": {"reason_code": "insufficient_headroom"},
            },
        ),
    ],
)
@pytest.mark.parametrize("trial", [True, False])
def test_failed_attempt_keeps_resolved_role(run_failure, phase, payload, trial):
    saved, _, _, output = run_failure(phase=phase, payload=payload, trial=trial)
    assert saved[0]["is_trial"] is trial
    assert saved[0]["attempt_role"] == ("trial" if trial else "formal")
    evidence = formal_evidence_of(output)
    assert evidence.formal_record_count == (0 if trial else 1)
    assert evidence.formal_success_count == 0


@pytest.mark.parametrize("trial", [False, True])
def test_role_reset_excludes_preplan_failure_without_erasing_formal_attempt(run_failure, trial):
    saved, _, _, output = run_failure(phase="preparation", attempts=2, trial=trial)
    assert [r["attempt_role"] for r in saved] == ["trial" if trial else "formal", "unresolved"]
    assert formal_evidence_of(output).formal_record_count == (0 if trial else 1)
    assert formal_evidence_of(output).record_count == 2


def test_condensed_native_history_retains_unresolved_role():
    from agent.prompts import PLANNER_FULL_WINDOW, _truncate_memory_history

    history = [
        {
            "exp_id": "before-plan",
            "status": "error",
            "is_trial": False,
            "attempt_role": "unresolved",
        }
    ] + [
        {"exp_id": f"later-{i}", "status": "success", "is_trial": False}
        for i in range(PLANNER_FULL_WINDOW)
    ]
    assert _truncate_memory_history(history)[0]["attempt_role"] == "unresolved"
