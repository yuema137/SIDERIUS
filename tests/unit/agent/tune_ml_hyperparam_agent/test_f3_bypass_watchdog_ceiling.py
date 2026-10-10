"""Lane F3 — a forecast bypass raises only the forecast admission ceiling.

Forecast and measured admission are exclusive authorities.  A forecast-selected
attempt therefore keeps in-process runtime verification record-only; the
training policy must not acquire a measured watchdog budget as a side effect of
the bypass.  The elevated value governs the forecast decision and is recorded
on the admitted attempt, while an untriggered or unqualified attempt cannot
inherit it.
"""

from __future__ import annotations

import tempfile
from unittest.mock import patch

import pytest

from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent
from tests.helpers.scoring_stubs import stub_scoring
from tests.unit.agent.tune_ml_hyperparam_agent.test_tuning_agent import (
    FAKE_CONFIG_MANUAL,
    FAKE_INFERENCE_RESULT,
    FAKE_PLAN_WITH_TRIAL,
    FAKE_REFLECT_RESPONSE,
    FAKE_RESOURCE_CHECK_OK,
    FAKE_SCORE_RESULT,
    FAKE_SCORE_VECTOR_RESULT,
    FAKE_TRAIN_RESULT,
    _synth_reference,
)

TRIAL_TIME_OK = {
    "status": "success",
    "feasible": True,
    "estimated_minutes": 5.0,
    "limit_minutes": 20.0,
    "verdict": "FITS",
    "suggestion": "",
    "breakdown": {"over_effective_budget": False},
}


def _formal_over(estimated: float) -> dict:
    return {
        "status": "success",
        "feasible": False,
        "estimated_minutes": estimated,
        "limit_minutes": 120.0,
        "verdict": f"OVER BUDGET — Est {estimated} min vs budget 120.0 min.",
        "suggestion": "Reduce model depth/width.",
        "breakdown": {"over_effective_budget": True},
    }


def _run(
    tmp_path,
    *,
    formal_check,
    bypass_minutes,
    bypass_delta=0.0,
    trial_check=None,
    watchdog_enabled=False,
    deadline_policy="budget-ceiling-v1",
):
    """Drive run() through a REAL trial round then the forced-formal round.

    Round 1 (trial): time check OK → success record → trial winner.
    Round 2 (formal, forced by force_formal_round default True at
    max_rounds=2): time check returns OVER at the 120 budget with the given
    estimate → the bypass block decides. Returns (saved_records,
    skill_calls) — the training calls' params carry the runtime_policy the
    watchdog enforces.
    """
    with (
        patch("nodes.ml_hyperparameter_tune_agent.LLMBridge") as MockBridge,
        patch("nodes.ml_hyperparameter_tune_agent.TidmadSandbox") as MockSandbox,
        patch("nodes.ml_hyperparameter_tune_agent.runtime._run_skill") as mock_skill,
        patch("nodes.ml_hyperparameter_tune_agent.load_anchor_map") as mock_anchor,
        patch(
            "nodes.ml_hyperparameter_tune_agent.load_reference_scores",
            return_value=_synth_reference(),
        ),
        patch("os.path.exists", return_value=True),
        tempfile.TemporaryDirectory() as configs_dir,
    ):
        mock_brain = MockBridge.return_value
        mock_brain.plan.return_value = FAKE_PLAN_WITH_TRIAL
        mock_brain.reflect.return_value = FAKE_REFLECT_RESPONSE
        mock_anchor.return_value = {"anchors": {}, "s_max": 1.0}

        saved_records: list[dict] = []
        skill_calls: list[tuple[str, dict]] = []
        mock_sandbox = MockSandbox.return_value
        mock_sandbox.get_summary.side_effect = lambda: list(saved_records)
        mock_sandbox.save_record.side_effect = saved_records.append
        mock_sandbox.dirs = {"configs": configs_dir, "data": configs_dir}
        stub_scoring(mock_sandbox, *FAKE_SCORE_VECTOR_RESULT)

        def dispatch(skill_folder, sandbox, **params):
            skill_calls.append((skill_folder, params))
            if skill_folder == "check_config_format_skill":
                return FAKE_CONFIG_MANUAL
            if skill_folder == "evaluate_vram_skill":
                return FAKE_RESOURCE_CHECK_OK
            if skill_folder == "evaluate_time_skill":
                # Trial rounds pass; the FORMAL round's check is OVER at
                # the normal budget with the leg's estimate.
                if params.get("runtime_phase") == "formal":
                    return dict(formal_check)
                return dict(trial_check) if trial_check is not None else dict(TRIAL_TIME_OK)
            if skill_folder == "training_skill":
                return FAKE_TRAIN_RESULT
            if skill_folder == "inference_skill":
                return FAKE_INFERENCE_RESULT
            if skill_folder == "denoising_score_skill":
                return FAKE_SCORE_RESULT
            return {"status": "error", "message": f"unknown skill {skill_folder}"}

        mock_skill.side_effect = dispatch

        inp = HyperparamTuningInput(
            planner_strategy="native-timing-v1",
            model_type="punet",
            file_index=6,
            max_rounds=2,
            is_trial=True,
            expert_advice="",
            llm_provider="gemini",
            llm_model_id="test-model",
            storage=StorageConfig(
                backend="local",
                local=LocalStorageConfig(workspace=str(tmp_path), run_name="f3_witness"),
            ),
            progress_bar=False,
            trial_time_budget_minutes=20.0,
            formal_time_budget_minutes=120.0,
            runtime_watchdog_enabled=watchdog_enabled,
            runtime_watchdog_deadline_policy=deadline_policy,
            trial_time_admission_source="forecast",
            formal_time_admission_source="forecast",
            bypass_formal_time_budget_minutes=bypass_minutes,
            bypass_formal_time_budget_min_delta=bypass_delta,
            # DS5 waiver: disabled HealthGate mode stamps records
            # health_gate_enabled=False => trial winners are VALID without
            # standing up the gate subsystem in the harness.
            health_gate_enabled=False,
            # V20 PR D §16.C — the -inf bootstrap: gates ON with no chain
            # incumbent resolves the bypass threshold to the bootstrap, so
            # a fresh chain's qualified winner can fire the bypass at all.
            enable_chain_incumbent_formal_gates=True,
        )
        HyperparamTuningAgent().run(inp)
        return saved_records, skill_calls


def _training_policies(skill_calls) -> list[dict]:
    """Runtime policies delivered to training, in execution order."""
    return [
        p["runtime_policy"]
        for s, p in skill_calls
        if s == "training_skill" and "runtime_policy" in p
    ]


def test_bypass_raises_the_forecast_ceiling_without_arming_a_measured_watchdog(tmp_path):
    """A qualified forecast proceeds and records 200 without changing authority."""
    _records, calls = _run(tmp_path, formal_check=_formal_over(150.0), bypass_minutes=200.0)
    policies = _training_policies(calls)
    assert len(policies) == 2, "trial and admitted formal rounds must both train"
    assert policies[1]["time_admission_source"] == "forecast"
    assert policies[1]["operator_budget_seconds"] is None


def test_untriggered_bypass_leaves_the_normal_ceiling_the_global_raise_catch(tmp_path):
    """Direction 2 (supervisor addition 1) — the defect only this catches:
    the CONFIGURED bypass value leaking into attempts that never qualified
    — a global raise wearing a disguise. Mechanism: the formal forecast
    (100) FITS the normal 120 budget, so the bypass block is never reached
    while 200 is configured. Fails by: any formal training call carrying
    anything but 120*60."""
    formal_fits = {
        "status": "success",
        "feasible": True,
        "estimated_minutes": 100.0,
        "limit_minutes": 120.0,
        "verdict": "FITS",
        "suggestion": "",
        "breakdown": {"over_effective_budget": False},
    }
    _, calls = _run(tmp_path, formal_check=formal_fits, bypass_minutes=200.0)
    policies = _training_policies(calls)
    assert len(policies) == 2
    assert all(policy["operator_budget_seconds"] is None for policy in policies)


def test_unqualified_attempt_cannot_reach_the_elevated_ceiling(tmp_path):
    """The defect only this catches: 200 reachable WITHOUT qualification.
    On a fresh chain the -inf bootstrap (V20 §16.C) deliberately makes the
    SCORE side unconditional — observed live: reference(-inf) means any
    winner qualifies, and a delta of inf does NOT disable under the
    bootstrap. So the reachable unqualified state is qualification's OTHER
    conjunct: NO HealthGate-valid trial winner exists (here: the trial
    rounds are themselves time-refused, so no winner is ever produced).
    The infeasible formal attempt must then be REFUSED and no training may
    carry 200*60. Fails by: a formal training executing, or 200 appearing
    anywhere."""
    trial_over = {
        "status": "success",
        "feasible": False,
        "estimated_minutes": 90.0,
        "limit_minutes": 20.0,
        "verdict": "OVER BUDGET",
        "suggestion": "",
        "breakdown": {"over_effective_budget": True},
    }
    records, calls = _run(
        tmp_path,
        formal_check=_formal_over(150.0),
        bypass_minutes=200.0,
        trial_check=trial_over,
    )
    assert any(r.get("status") == "skipped_time_risk" for r in records), (
        "the unqualified (winner-less) infeasible formal attempt must be refused"
    )
    assert all(policy["operator_budget_seconds"] is None for policy in _training_policies(calls))


def test_qualified_but_no_ceiling_configured_grants_nothing(tmp_path):
    """The None-default safety leg — the defect only this catches: a
    qualified bypass extending time with NO configured ceiling (the
    global-raise-through-a-default failure mode; the None semantics are
    load-bearing per the schema). Fails by: the formal attempt training at
    all, or any non-trial budget appearing."""
    records, calls = _run(tmp_path, formal_check=_formal_over(150.0), bypass_minutes=None)
    assert any(r.get("status") == "skipped_time_risk" for r in records)
    assert all(policy["operator_budget_seconds"] is None for policy in _training_policies(calls))


def test_forecast_past_even_the_elevated_ceiling_is_refused(tmp_path):
    """The re-evaluation ruling — the defect only this catches: the bypass
    degrading back into 'ignore forecasts' (a 260-minute forecast admitted
    at a 200-minute ceiling would be P7-C one level up: admitted on a
    promise, killed at 200). Fails by: the formal attempt training."""
    records, calls = _run(tmp_path, formal_check=_formal_over(260.0), bypass_minutes=200.0)
    assert any(r.get("status") == "skipped_time_risk" for r in records)
    assert all(policy["operator_budget_seconds"] is None for policy in _training_policies(calls))


pytestmark = pytest.mark.usefixtures("synthetic_run_authorities")


@pytest.mark.parametrize("policy", ["budget-ceiling-v1", "forecast-tightening-v1"])
def test_enabled_watchdog_receives_resolved_bypass_without_changing_admission(tmp_path, policy):
    from core.runtime_control.session import RuntimeControlPolicy
    from core.runtime_control.watchdog_deadline import watchdog_deadline_provider

    _records, calls = _run(
        tmp_path,
        formal_check=_formal_over(150.0),
        bypass_minutes=200.0,
        watchdog_enabled=True,
        deadline_policy=policy,
    )
    policies = [RuntimeControlPolicy.model_validate(p) for p in _training_policies(calls)]
    assert len(policies) == 2
    for actual, minutes in zip(policies, [20.0, 200.0], strict=True):
        assert actual.operator_budget_seconds is None
        assert actual.time_admission_source == "forecast"
        assert actual.watchdog.deadline_policy == policy
        if policy == "budget-ceiling-v1":
            assert actual.watchdog.budget_seconds == minutes * 60
            deadline, _ = watchdog_deadline_provider(actual, "/missing")()
            assert deadline == minutes * 60
        else:
            assert actual.watchdog.budget_seconds is None
