"""
Phase L (§11) — per-round attempt budget + fail-round abort.

Five sub-cases exercising the outer/inner loop split that replaced the
pre-Phase-L ``max_rounds * 3`` shared attempt pool:

  (a) Trial round succeeds within ``attempts_per_round`` attempts.
  (b) Trial round fails all ``attempts_per_round`` attempts then a
      later round succeeds → ``consecutive_fails`` increments AND
      resets on success.
  (c) ``max_fail_rounds`` consecutive failures abort the loop with
      ``termination_reason='aborted_fail_rounds'``.
  (d) Formal-round promotion fires only when
      ``completed_rounds == max_rounds - 1``: the larger
      ``attempts_per_formal_round`` budget is observable on the LAST
      round, not on earlier rounds.
  (e) Formal round uses ``attempts_per_formal_round`` rather than
      ``attempts_per_round``: with ``attempts_per_round=1`` /
      ``attempts_per_formal_round=3`` and an oversize-then-fitting
      sequence in round 2 (formal), round 2 is allowed to burn
      multiple attempts that the trial budget would have forbidden.

See ``docs/resource_estimator_implement.md`` §11.7 row 7 for the
sub-case spec, and §11.5 for the budget semantics.
"""

import tempfile
from unittest.mock import patch

import pytest

from agent.schemas.hyperparam_tuning import (
    HyperparamTuningInput,
    HyperparamTuningOutput,
)
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent
from nodes.scoring_reference import ReferenceScores


def _synth_reference_stub() -> ReferenceScores:
    """Minimal in-memory ReferenceScores so the agent's pre-loop
    ``load_reference_scores()`` call is hermetic — no on-disk JSONs required.
    """
    return ReferenceScores(
        raw_per_file_log=[-2.7] * 20,
        gt_per_file_log=[7.0] * 20,
        raw_per_file_linear_sum=[2.0] * 20,
        raw_per_file_n_segments=[200] * 20,
        gt_per_file_linear_sum=[2000.0] * 20,
        gt_per_file_n_segments=[200] * 20,
        raw_scalar_full=-2.7,
        gt_scalar_full=7.0,
        s_max=295_715_680.14,
    )


# ---------------------------------------------------------------------------
# Canned LLM responses + skill payloads
# ---------------------------------------------------------------------------

FAKE_PLAN = {
    "model_type": "punet",
    "hypothesis": "h",
    "reasoning": "r",
    "model_config": {"depth": 4, "segmentation_size": 40000, "batch_size": 1},
    "train_config": {"epochs": 5, "lr": 1e-4},
    "loss_config": {"loss_type": "ce"},
}

FAKE_REFLECT = {
    "conclusion": "c",
    "key_factor": "k",
    "discovery": "d",
    "memory_update": "m",
}

FAKE_CONFIG_MANUAL = {
    "status": "success",
    "data": {"punet": {"fields": ["depth", "segmentation_size"]}},
}

FAKE_VRAM_OK = {
    "status": "success",
    "feasible": True,
    "estimated_gb": 2.5,
    "limit_gb": 6.0,
    "vram_budget_gb": 8.0,
    "verdict": "FITS",
    "suggestion": "",
}

FAKE_VRAM_OOM = {
    "status": "success",
    "feasible": False,
    "estimated_gb": 12.0,
    "limit_gb": 8.0,
    "verdict": "Estimated 12 GB exceeds 8 GB limit.",
    "suggestion": "Reduce batch_size.",
}

FAKE_TRAIN = {"status": "success", "results": {"final_loss": 0.5, "model_params": 100000}}
FAKE_INFER = {"status": "success", "results": {}}
FAKE_SCORE = {"status": "success", "results": {"denoising_score": 1.75}}


def _make_input(
    tmp_path,
    *,
    max_rounds: int,
    attempts_per_round: int,
    attempts_per_formal_round: int,
    max_fail_rounds: int,
) -> HyperparamTuningInput:
    """Construct a tuner input with explicit Phase L knobs.

    Unlike the helpers in ``test_tuning_agent.py`` / ``test_constraint_aware_retry.py``
    (which pin to the pre-Phase-L worst case), each Phase L sub-case below
    sets its budgets explicitly — the asymmetry between the four knobs is
    the entire point of the exercise.
    """
    return HyperparamTuningInput(
        model_type="punet",
        file_index=6,
        max_rounds=max_rounds,
        attempts_per_round=attempts_per_round,
        attempts_per_formal_round=attempts_per_formal_round,
        max_fail_rounds=max_fail_rounds,
        expert_advice="",
        llm_provider="gemini",
        llm_model_id="test-model",
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="test_run"),
        ),
        progress_bar=False,
    )


def _make_scripted_skill(vram_verdicts):
    """Return a ``_run_skill`` side_effect that walks ``vram_verdicts``
    in order, one entry per attempt.

    ``vram_verdicts`` is a list of either ``FAKE_VRAM_OK`` or
    ``FAKE_VRAM_OOM`` (or any custom dict). Each call to
    ``evaluate_vram_skill`` consumes the next entry; non-VRAM skills
    (training/inference/scoring) return their canned successful result.

    Raises ``IndexError`` if the loop tries more attempts than the
    schedule allows — a useful early-fail signal that the test setup
    is mismatched against the loop's actual behaviour.
    """
    counter = {"i": 0}

    def side_effect(skill_folder, sandbox, **params):
        if skill_folder == "check_config_format_skill":
            return FAKE_CONFIG_MANUAL
        if skill_folder == "evaluate_vram_skill":
            i = counter["i"]
            counter["i"] = i + 1
            if i >= len(vram_verdicts):
                raise IndexError(
                    f"vram_verdicts exhausted at attempt {i + 1}; "
                    f"schedule length={len(vram_verdicts)}"
                )
            return vram_verdicts[i]
        if skill_folder == "training_skill":
            return FAKE_TRAIN
        if skill_folder == "inference_skill":
            return FAKE_INFER
        if skill_folder == "denoising_score_skill":
            return FAKE_SCORE
        return {"status": "error", "message": f"unknown skill {skill_folder}"}

    return side_effect, counter


@pytest.fixture
def agent_with_scripted_skill():
    """Yield a factory that wires up the agent against a custom VRAM
    schedule. The factory is the unit of parameterisation — each
    sub-case calls it with its own ``vram_verdicts`` list.
    """

    def make(vram_verdicts):
        side_effect, counter = _make_scripted_skill(vram_verdicts)
        cm = (
            patch("nodes.ml_hyperparameter_tune_agent.LLMBridge"),
            patch("nodes.ml_hyperparameter_tune_agent.TidmadSandbox"),
            patch("nodes.ml_hyperparameter_tune_agent._run_skill", side_effect=side_effect),
            patch(
                "nodes.ml_hyperparameter_tune_agent.load_reference_scores",
                return_value=_synth_reference_stub(),
            ),
            tempfile.TemporaryDirectory(),
        )
        return cm, counter

    yield make


def _setup(make_factory, vram_verdicts):
    """Open all five context managers + return (agent, saved_records, counter,
    cleanup-callable)."""
    (mock_bridge_cm, mock_sandbox_cm, mock_skill_cm, mock_ref_cm, configs_cm), counter = (
        make_factory(vram_verdicts)
    )
    MockBridge = mock_bridge_cm.__enter__()
    MockSandbox = mock_sandbox_cm.__enter__()
    mock_skill_cm.__enter__()
    mock_ref_cm.__enter__()
    configs_dir = configs_cm.__enter__()

    mock_brain = MockBridge.return_value
    mock_brain.plan.return_value = FAKE_PLAN
    mock_brain.reflect.return_value = FAKE_REFLECT

    saved = []
    mock_sandbox = MockSandbox.return_value
    mock_sandbox.get_summary.side_effect = lambda: list(saved)
    mock_sandbox.save_record.side_effect = lambda r: saved.append(r)
    mock_sandbox.dirs = {"configs": configs_dir}

    def cleanup():
        configs_cm.__exit__(None, None, None)
        mock_ref_cm.__exit__(None, None, None)
        mock_skill_cm.__exit__(None, None, None)
        mock_sandbox_cm.__exit__(None, None, None)
        mock_bridge_cm.__exit__(None, None, None)

    return HyperparamTuningAgent(), saved, counter, cleanup


def _round_records(saved, round_index):
    """Records emitted during a specific outer-loop round."""
    return [r for r in saved if (r.get("memory") or {}).get("round_index") == round_index]


# ===========================================================================
# (a) Trial round succeeds within attempts_per_round attempts
# ===========================================================================


class TestTrialRoundSucceedsWithinBudget:
    """Round 1 (trial) burns 2 of its 3-attempt budget on OOM-skips,
    then attempt 3 succeeds. Round 2 (formal) succeeds first try.

    Verifies: a trial round can recover from early failures within its
    inner budget without consuming any of the outer ``consecutive_fails``
    counter — the round counts as a SUCCESS the moment any attempt
    lands.
    """

    def test_succeeds_within_budget(self, agent_with_scripted_skill, tmp_path):
        # 2 OOMs then OK in round 1; OK in round 2 (formal).
        verdicts = [
            FAKE_VRAM_OOM,
            FAKE_VRAM_OOM,
            FAKE_VRAM_OK,  # round 1
            FAKE_VRAM_OK,
        ]  # round 2 (formal)
        agent, saved, counter, cleanup = _setup(agent_with_scripted_skill, verdicts)
        try:
            output = agent.run(
                _make_input(
                    tmp_path,
                    max_rounds=2,
                    attempts_per_round=3,
                    attempts_per_formal_round=3,
                    max_fail_rounds=3,
                )
            )
        finally:
            cleanup()

        assert output.status == "completed"
        assert output.completed_rounds == 2
        assert output.total_attempts == 4
        assert output.termination_reason == "completed"
        assert output.consecutive_fail_rounds_at_exit == 0

        # Round 1 burned 3 attempts (2 skipped + 1 success); the success
        # is the LAST record of the round.
        r1 = _round_records(saved, 1)
        assert len(r1) == 3
        assert r1[0]["status"] == "skipped_oom_risk"
        assert r1[1]["status"] == "skipped_oom_risk"
        assert r1[2]["status"] == "success"
        assert r1[0]["memory"]["attempt_in_round"] == 1
        assert r1[2]["memory"]["attempt_in_round"] == 3


# ===========================================================================
# (b) Trial fail-round increments consecutive_fails; success resets it
# ===========================================================================


class TestConsecutiveFailsIncrementsThenResets:
    """Schedule [OOM, OK, OOM, OOM] with ``max_fail_rounds=2``,
    ``attempts_per_round=1``, ``attempts_per_formal_round=1``,
    ``max_rounds=3``:

      iter 1: OOM → consecutive_fails 0 → 1
      iter 2: OK  → completed_rounds 0 → 1, consecutive_fails RESET to 0
      iter 3: OOM → consecutive_fails 0 → 1
      iter 4: OOM → consecutive_fails 1 → 2 → ABORT (== max_fail_rounds)

    Total attempts = 4 — the load-bearing observation. Without the
    increment, abort would never fire (counter stuck at 0). Without
    the reset, abort would fire one iteration earlier (after iter 3
    instead of iter 4) for a total of 3 attempts. Observing 4 is the
    only outcome consistent with both increment AND reset working.

    This is the cleanest single-output proxy for the consecutive-fails
    contract — an internal-state probe (mid-loop counter inspection)
    would require monkey-patching, which adds fragility for no
    additional coverage.
    """

    def test_increments_then_resets(self, agent_with_scripted_skill, tmp_path):
        verdicts = [FAKE_VRAM_OOM, FAKE_VRAM_OK, FAKE_VRAM_OOM, FAKE_VRAM_OOM]
        agent, saved, counter, cleanup = _setup(agent_with_scripted_skill, verdicts)
        try:
            output = agent.run(
                _make_input(
                    tmp_path,
                    max_rounds=3,
                    attempts_per_round=1,
                    attempts_per_formal_round=1,
                    max_fail_rounds=2,
                )
            )
        finally:
            cleanup()

        assert output.status == "partial"
        assert output.completed_rounds == 1  # only iter 2 advanced it
        assert output.total_attempts == 4  # the load-bearing proof
        assert output.termination_reason == "aborted_fail_rounds"
        assert output.consecutive_fail_rounds_at_exit == 2

        # 4 records: 3 OOM + 1 success
        statuses = [r["status"] for r in saved]
        assert statuses.count("skipped_oom_risk") == 3
        assert statuses.count("success") == 1
        # The success is the second record (iter 2).
        assert saved[1]["status"] == "success"


# ===========================================================================
# (c) max_fail_rounds consecutive failures abort the loop
# ===========================================================================


class TestMaxFailRoundsAborts:
    """All attempts OOM. With ``max_rounds=5`` and ``max_fail_rounds=2``,
    the outer loop must abort after 2 consecutive fail-rounds rather
    than spending all 5 round slots.

    Verifies the consecutive-failure brake fires at the documented
    threshold and surfaces ``termination_reason='aborted_fail_rounds'``.
    """

    def test_aborts_at_max_fail_rounds(self, agent_with_scripted_skill, tmp_path):
        verdicts = [FAKE_VRAM_OOM] * 4  # 2 fail-rounds × 2 attempts each
        agent, saved, counter, cleanup = _setup(agent_with_scripted_skill, verdicts)
        try:
            output = agent.run(
                _make_input(
                    tmp_path,
                    max_rounds=5,
                    attempts_per_round=2,
                    attempts_per_formal_round=2,
                    max_fail_rounds=2,
                )
            )
        finally:
            cleanup()

        assert output.status == "partial"
        assert output.completed_rounds == 0
        assert output.total_attempts == 4  # 2 fail-rounds × 2-budget = 4
        assert output.termination_reason == "aborted_fail_rounds"
        assert output.consecutive_fail_rounds_at_exit == 2
        # Loop did NOT spin through the remaining 3 round slots.
        assert counter["i"] == 4


# ===========================================================================
# (d) Formal-round promotion fires only when completed_rounds == max_rounds-1
# ===========================================================================


class TestFormalPromotionFiresOnLastRound:
    """``max_rounds=3`` with ``attempts_per_round=2`` and
    ``attempts_per_formal_round=4``. Schedule: rounds 1 + 2 succeed
    first try (so each consumes 1 of its 2-attempt trial budget),
    then round 3 (formal) burns 3 attempts on OOM before succeeding
    on attempt 4.

    Verifies the formal budget activates on round 3 specifically: if
    formal had triggered earlier, round 1 or 2 would have had a
    4-attempt budget (irrelevant here, both succeed first try). The
    LOAD-BEARING signal is round 3 burning 4 attempts — which is
    impossible under the trial budget of 2.
    """

    def test_only_last_round_uses_formal_budget(self, agent_with_scripted_skill, tmp_path):
        verdicts = [
            FAKE_VRAM_OK,  # round 1
            FAKE_VRAM_OK,  # round 2
            FAKE_VRAM_OOM,
            FAKE_VRAM_OOM,
            FAKE_VRAM_OOM,
            FAKE_VRAM_OK,
        ]  # round 3 (formal)
        agent, saved, counter, cleanup = _setup(agent_with_scripted_skill, verdicts)
        try:
            output = agent.run(
                _make_input(
                    tmp_path,
                    max_rounds=3,
                    attempts_per_round=2,
                    attempts_per_formal_round=4,
                    max_fail_rounds=3,
                )
            )
        finally:
            cleanup()

        assert output.status == "completed"
        assert output.completed_rounds == 3
        # 1 + 1 + 4 = 6: round 3 used the formal budget, not the trial budget.
        assert output.total_attempts == 6
        assert output.termination_reason == "completed"

        r3 = _round_records(saved, 3)
        # Round 3 produced 4 records — impossible under attempts_per_round=2.
        assert len(r3) == 4
        assert [r["memory"]["attempt_in_round"] for r in r3] == [1, 2, 3, 4]
        assert [r["status"] for r in r3] == [
            "skipped_oom_risk",
            "skipped_oom_risk",
            "skipped_oom_risk",
            "success",
        ]


# ===========================================================================
# (e) Formal round uses attempts_per_formal_round (asymmetry vs trial)
# ===========================================================================


class TestFormalBudgetDistinctFromTrial:
    """``attempts_per_round=1`` / ``attempts_per_formal_round=3``.
    Round 1 (trial) succeeds on its single attempt; round 2 (formal)
    is allowed to burn 2 attempts before succeeding on attempt 3 —
    behaviour that would be impossible under the trial budget of 1.

    Note on design-doc text: §11.7 row 7 sub-case (e) reads "round 1
    fails on attempt 1 (1-budget) while round 2 (formal) burns 2
    attempts before succeeding". Under Phase L semantics formal
    promotion requires ``completed_rounds == max_rounds - 1``, so
    round 1 MUST succeed for round 2 to be formal. The corrected
    interpretation tested here keeps the spirit of the sub-case (the
    asymmetry between trial-budget=1 and formal-budget=3) without
    relying on impossible state.
    """

    def test_formal_budget_asymmetry(self, agent_with_scripted_skill, tmp_path):
        verdicts = [
            FAKE_VRAM_OK,  # round 1 (trial, 1-budget)
            FAKE_VRAM_OOM,
            FAKE_VRAM_OOM,
            FAKE_VRAM_OK,
        ]  # round 2 (formal, 3-budget)
        agent, saved, counter, cleanup = _setup(agent_with_scripted_skill, verdicts)
        try:
            output = agent.run(
                _make_input(
                    tmp_path,
                    max_rounds=2,
                    attempts_per_round=1,
                    attempts_per_formal_round=3,
                    max_fail_rounds=3,
                )
            )
        finally:
            cleanup()

        assert output.status == "completed"
        assert output.completed_rounds == 2
        # 1 + 3 = 4: round 2 used 3 attempts → only possible because formal
        # budget was 3, not 1.
        assert output.total_attempts == 4
        assert output.termination_reason == "completed"

        # Round 1 used its sole 1-attempt budget for a success.
        r1 = _round_records(saved, 1)
        assert len(r1) == 1
        assert r1[0]["status"] == "success"
        assert r1[0]["memory"]["attempt_in_round"] == 1

        # Round 2 (formal) burned 3 attempts.
        r2 = _round_records(saved, 2)
        assert len(r2) == 3
        assert [r["status"] for r in r2] == [
            "skipped_oom_risk",
            "skipped_oom_risk",
            "success",
        ]
