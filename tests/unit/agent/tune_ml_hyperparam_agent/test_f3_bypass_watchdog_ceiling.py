"""Lane F3 / F-BYPASS-WD-1 — the bypass raises the WATCHDOG ceiling, not
just the admission flag; witnessed at the runtime consumer (SRI-2, both
directions).

The defect (campaign ledger P7-C): the bypass mutated
``time_check["feasible"] = True`` in place — forecast overridden, while the
runtime policy's ``operator_budget_seconds`` stayed at the normal formal
budget. Admitted on the promise of extra time, killed at the normal
deadline. The fix: ONE resolved value (``chosen_time_budget``) is raised at
the bypass site and read by BOTH admission and the runtime policy; feasibility
is RE-EVALUATED against the elevated ceiling, never flag-forced.

Every leg reads the verdict from the TRAINING CALL's captured
``runtime_policy["operator_budget_seconds"]`` — the value the watchdog
actually enforces — never from a config fingerprint. Frozen campaign
numbers: normal formal 120 → ceiling 120; bypass-qualified 200 → ceiling
200; the watchdog is never disabled; 200 is never global.
"""

from __future__ import annotations

import tempfile
from unittest.mock import patch

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
}


def _formal_over(estimated: float) -> dict:
    return {
        "status": "success",
        "feasible": False,
        "estimated_minutes": estimated,
        "limit_minutes": 120.0,
        "verdict": f"OVER BUDGET — Est {estimated} min vs budget 120.0 min.",
        "suggestion": "Reduce model depth/width.",
    }


def _run(tmp_path, *, formal_check, bypass_minutes, bypass_delta=0.0, trial_check=None):
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


def _training_budgets(skill_calls) -> list[float | None]:
    """operator_budget_seconds of every TRAINING call, in order — the value
    the watchdog enforces (trial trainings carry None by design)."""
    return [
        p["runtime_policy"]["operator_budget_seconds"]
        for s, p in skill_calls
        if s == "training_skill" and "runtime_policy" in p
    ]


def test_bypass_raises_the_watchdog_ceiling_at_the_runtime_consumer(tmp_path):
    """THE witness, direction 1 — the defect only this catches: P7-C itself.
    A qualified bypass whose forecast (150) fits the elevated ceiling (200)
    must execute with operator_budget_seconds == 200*60 — the ceiling MOVED
    with the admission verdict. Fails by: the formal training call carrying
    120*60 (admitted on a promise, killed at the normal deadline — the
    original defect, which the restored flag-flip reproduces exactly)."""
    records, calls = _run(tmp_path, formal_check=_formal_over(150.0), bypass_minutes=200.0)
    budgets = _training_budgets(calls)
    formal_budgets = [b for b in budgets if b is not None]
    assert formal_budgets, "the formal round must have trained (bypass admitted it)"
    assert formal_budgets == [200.0 * 60.0]
    # Provenance rides the record's time_check.
    bypassed = [r for r in records if (r.get("time_check") or {}).get("bypass_ceiling_minutes")]
    assert not bypassed or bypassed[0]["time_check"]["bypass_ceiling_minutes"] == 200.0


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
    }
    _, calls = _run(tmp_path, formal_check=formal_fits, bypass_minutes=200.0)
    budgets = _training_budgets(calls)
    formal_budgets = [b for b in budgets if b is not None]
    assert formal_budgets == [120.0 * 60.0], (
        "a FEASIBLE formal attempt with the bypass value merely CONFIGURED "
        "must run at the NORMAL ceiling — anything else is a global raise"
    )
    assert [b for b in budgets if b is None], (
        "trial trainings must still ship operator_budget_seconds=None"
    )


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
    assert 200.0 * 60.0 not in _training_budgets(calls)


def test_qualified_but_no_ceiling_configured_grants_nothing(tmp_path):
    """The None-default safety leg — the defect only this catches: a
    qualified bypass extending time with NO configured ceiling (the
    global-raise-through-a-default failure mode; the None semantics are
    load-bearing per the schema). Fails by: the formal attempt training at
    all, or any non-trial budget appearing."""
    records, calls = _run(tmp_path, formal_check=_formal_over(150.0), bypass_minutes=None)
    assert any(r.get("status") == "skipped_time_risk" for r in records)
    assert [b for b in _training_budgets(calls) if b is not None] == []


def test_forecast_past_even_the_elevated_ceiling_is_refused(tmp_path):
    """The re-evaluation ruling — the defect only this catches: the bypass
    degrading back into 'ignore forecasts' (a 260-minute forecast admitted
    at a 200-minute ceiling would be P7-C one level up: admitted on a
    promise, killed at 200). Fails by: the formal attempt training."""
    records, calls = _run(tmp_path, formal_check=_formal_over(260.0), bypass_minutes=200.0)
    assert any(r.get("status") == "skipped_time_risk" for r in records)
    assert [b for b in _training_budgets(calls) if b is not None] == []
