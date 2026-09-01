"""
Tests for refine_inference_time_estimator.md Commit D — the 3-branch
``inference_ms`` derivation in ``run_skill`` and the 10% slack rule.

Pins the contract:
  * Branch 1 (``trial_inference_warmup``): hint present + > 0 → use the
    measured per-PSD-segment cost, converted via
    ``hint × inf_batch / ml_per_psd`` (the **corrected** formula — see
    the design doc §3.5 correction note for why the inverted form was
    rejected during implementation).
  * Branch 2 (``training_warmup_x2.7_fallback``): hint absent or 0 +
    training warmup measured → legacy ``measured × _INFERENCE_VS_TRAINING_RATIO``.
  * Branch 3 (``static_formula``): nothing measured → ``inference_ms = None``,
    inference estimator falls through to its internal static formula.

  * 10% slack: only when ``inference_ms_source == "trial_inference_warmup"``
    AND the strict check would have failed AND the loose check passes.

Phase estimators are monkeypatched to return controllable seconds so
the slack-rule tests can hit each window precisely without exercising
torch / model code.
"""

from __future__ import annotations

import pytest

from agent.skills.evaluate_time_skill import wrapper as ts
from agent.skills.inference_skill import estimator as _inf_est
from tests.helpers.two_family_profile import make_two_family_profile

PHYSICAL_SEGMENT_LENGTH = 1_600_000
PROFILE = make_two_family_profile(
    num_files=20,
    psd_segment_length=PHYSICAL_SEGMENT_LENGTH,
    segments_per_file=20,
)


class FakeSandbox:
    """run_skill ignores the sandbox argument."""


def _base_kwargs(**overrides) -> dict:
    kw = {
        "model_type": "rnn",  # registered in inference_batch_for
        "model_config": {"segmentation_size": 16000},
        "train_config": {"batch_size": 1, "epochs": 1, "device": "cpu"},
        "loss_config": {"loss_type": "focal"},
        "sample_set": {str(i): list(range(20)) for i in range(20)},
        "train_portion": 1.0,
        "time_budget_minutes": 60.0,
        # Step 05b: the run-bound topology is a REQUIRED kwarg — the skill
        # no longer resolves one of its own.
        "dataset_profile": PROFILE,
    }
    kw.update(overrides)
    return kw


def _stub_phase(phase_name: str, seconds: float) -> dict:
    """Phase-estimator return shape that ``run_skill`` consumes."""
    return {
        "phase": phase_name,
        "seconds": seconds,
        "breakdown": {
            "total_train_steps": 100,
            "ms_per_step": 1.0,
            "k_correction": 1.0,
            "safety_multiplier": 2.0,
            # C8c: the source must be a value the production training
            # estimator can actually emit — the runtime adapter treats an
            # uninterpretable provenance as an evidence-channel failure
            # rather than pricing it. `static_uncalibrated` matches this
            # stub's `formal_execution_eligible: False`.
            "ms_source": "static_uncalibrated",
            "formal_execution_eligible": False,
            "gpu_name": "test_gpu",
            "total_inference_steps": 100,
            "inference_batch": _inf_est.inference_batch_for("rnn"),
            "inference_batch_uncalibrated": False,
        },
    }


def _patch_phases(
    monkeypatch,
    train_sec: float,
    inf_sec: float,
    score_sec: float,
    *,
    capture: dict | None = None,
) -> None:
    """Replace the three phase estimators with controllable stubs.

    When ``capture`` is provided, the inference stub stashes its received
    ``inference_ms_per_step`` into ``capture["inference_ms_per_step"]`` so
    a test can assert the exact value the wrapper computed for the
    measured-hint branch.
    """
    monkeypatch.setattr(
        ts._training_est,
        "estimate_wall_time_seconds",
        lambda *a, **kw: _stub_phase("training", train_sec),
    )

    def _inf_stub(*a, **kw):
        if capture is not None:
            capture["inference_ms_per_step"] = kw.get("inference_ms_per_step")
        return _stub_phase("inference", inf_sec)

    monkeypatch.setattr(ts._inference_est, "estimate_wall_time_seconds", _inf_stub)
    monkeypatch.setattr(
        ts._scoring_est,
        "estimate_wall_time_seconds",
        lambda *a, **kw: _stub_phase("scoring", score_sec),
    )
    # ``_count_params`` only matters when the static fallback fires;
    # patch it cheaply to a constant so the path doesn't try to
    # instantiate a real model.
    monkeypatch.setattr(ts, "_count_params", lambda mt, mc, lt: 100_000)


# ---------------------------------------------------------------------------
# Branch 1 — measured hint
# ---------------------------------------------------------------------------


class TestHintBranch:
    def test_hint_present_sets_source_trial_inference_warmup(self, monkeypatch):
        _patch_phases(monkeypatch, train_sec=600, inf_sec=120, score_sec=60)
        result = ts.run_skill(
            FakeSandbox(),
            **_base_kwargs(time_budget_minutes=60.0),
            inference_per_psd_seg_ms_hint=50.0,
        )
        assert result["status"] == "success"
        assert result["breakdown"]["inference_ms_source"] == "trial_inference_warmup"

    def test_hint_value_matches_corrected_formula(self, monkeypatch):
        """Regression guard for the §3.5 inversion bug. Asserts the
        wrapper feeds ``hint × inf_batch / ml_per_psd`` to the inference
        estimator — NOT the inverted ``hint × ml_per_psd / inf_batch``."""
        capture: dict = {}
        _patch_phases(
            monkeypatch,
            train_sec=600,
            inf_sec=120,
            score_sec=60,
            capture=capture,
        )
        seg_size = 16000
        hint = 50.0  # ms / PSD segment
        result = ts.run_skill(
            FakeSandbox(),
            **_base_kwargs(
                time_budget_minutes=60.0,
                model_config={"segmentation_size": seg_size},
            ),
            inference_per_psd_seg_ms_hint=hint,
        )
        inf_batch = _inf_est.inference_batch_for("rnn")
        ml_per_psd = max(PHYSICAL_SEGMENT_LENGTH // seg_size, 1)
        expected = hint * inf_batch / ml_per_psd
        assert capture["inference_ms_per_step"] == pytest.approx(expected)
        # Sanity: the inverted formula would be enormously larger.
        inverted = hint * ml_per_psd / inf_batch
        assert capture["inference_ms_per_step"] != pytest.approx(inverted)
        assert result["status"] == "success"

    def test_hint_zero_falls_through_to_fallback(self, monkeypatch):
        """``hint > 0`` is the gate — exact 0 is treated as 'no hint'
        because zero ms/psd_seg is physically impossible (would mean
        instant inference). Falling through to the training-fallback
        path is preferable to feeding a meaningless 0."""
        _patch_phases(monkeypatch, train_sec=600, inf_sec=120, score_sec=60)
        result = ts.run_skill(
            FakeSandbox(),
            **_base_kwargs(time_budget_minutes=60.0),
            inference_per_psd_seg_ms_hint=0.0,
        )
        # No data_dir → no warmup measured → static_formula
        assert result["breakdown"]["inference_ms_source"] == "static_formula"

    def test_hint_negative_falls_through_to_fallback(self, monkeypatch):
        """Defensive: a negative value (impossible from the aggregator,
        but cheap to guard) does not become a measured-path verdict."""
        _patch_phases(monkeypatch, train_sec=600, inf_sec=120, score_sec=60)
        result = ts.run_skill(
            FakeSandbox(),
            **_base_kwargs(time_budget_minutes=60.0),
            inference_per_psd_seg_ms_hint=-5.0,
        )
        assert result["breakdown"]["inference_ms_source"] != "trial_inference_warmup"


# ---------------------------------------------------------------------------
# Branch 2 / 3 — fallback paths
# ---------------------------------------------------------------------------


class TestFallbackBranches:
    def test_no_hint_no_warmup_lands_static_formula(self, monkeypatch):
        """No hint, no ``data_dir`` → no training warmup → branch 3."""
        _patch_phases(monkeypatch, train_sec=600, inf_sec=120, score_sec=60)
        result = ts.run_skill(FakeSandbox(), **_base_kwargs())
        assert result["breakdown"]["inference_ms_source"] == "static_formula"

    def test_no_hint_with_training_warmup_lands_x27_fallback(self, monkeypatch):
        """No hint, but training warmup measured ms/step → branch 2."""
        _patch_phases(monkeypatch, train_sec=600, inf_sec=120, score_sec=60)
        # Force the warmup helper to return a synthetic measurement so the
        # "elif measured > 0" branch fires without a real torch run.
        monkeypatch.setattr(
            ts,
            "_measure_ms_per_step",
            lambda **kwargs: (
                5.0,
                {
                    "n_warmup_batches": 1,
                    "n_timed_batches": 4,
                    "timings_ms": [],
                    "aggregator": "median",
                },
            ),
        )
        result = ts.run_skill(
            FakeSandbox(),
            **_base_kwargs(),
            data_dir="/some/fake/dir",  # required to reach the warmup branch
        )
        assert result["breakdown"]["inference_ms_source"] == "training_warmup_x2.7_fallback"


# ---------------------------------------------------------------------------
# Step 6.5 — 10% slack rule
# ---------------------------------------------------------------------------


class TestSlackRule:
    def test_measured_path_within_slack_window_is_feasible(self, monkeypatch):
        """``total_min == 63`` with ``budget == 60`` (105% of budget) →
        strict check would say infeasible, but slack window
        ``[60, 66]`` saves it. Verdict text mentions slack."""
        # 63 min total = 3780 sec
        _patch_phases(monkeypatch, train_sec=3500, inf_sec=200, score_sec=80)
        result = ts.run_skill(
            FakeSandbox(),
            **_base_kwargs(time_budget_minutes=60.0),
            inference_per_psd_seg_ms_hint=50.0,
        )
        assert result["feasible"] is True
        assert result["breakdown"]["slack_applied"] is True
        assert result["breakdown"]["effective_budget_minutes"] == pytest.approx(66.0)
        assert "slack" in result["verdict"].lower()

    def test_measured_path_beyond_slack_is_infeasible(self, monkeypatch):
        """``total_min == 70`` with ``budget == 60`` (117%) → outside
        the 110% slack window → infeasible even on the measured path."""
        # 70 min total = 4200 sec
        _patch_phases(monkeypatch, train_sec=4000, inf_sec=120, score_sec=80)
        result = ts.run_skill(
            FakeSandbox(),
            **_base_kwargs(time_budget_minutes=60.0),
            inference_per_psd_seg_ms_hint=50.0,
        )
        # C8c: `over_effective_budget` is the quantity the slack rule moves;
        # `feasible` is now the POLICY's verdict, and this stub's evidence is
        # static_uncalibrated, which may not gate a round.
        assert result["breakdown"]["over_effective_budget"] is True
        assert result["breakdown"]["runtime_decision"] == "ADVISORY"
        assert result["breakdown"]["slack_applied"] is True
        assert result["breakdown"]["effective_budget_minutes"] == pytest.approx(66.0)

    def test_measured_path_under_budget_no_slack_note(self, monkeypatch):
        """Hint present, total well under budget → feasible+slack_applied
        flag set, but the verdict note doesn't appear (slack didn't
        save the verdict)."""
        # 50 min total = 3000 sec, well under 60 min
        _patch_phases(monkeypatch, train_sec=2900, inf_sec=60, score_sec=40)
        result = ts.run_skill(
            FakeSandbox(),
            **_base_kwargs(time_budget_minutes=60.0),
            inference_per_psd_seg_ms_hint=50.0,
        )
        assert result["feasible"] is True
        assert result["breakdown"]["slack_applied"] is True
        # Slack was applied at the budget level, but didn't actually save
        # this verdict — the note is gated on ``total_min > budget_min``.
        assert "slack" not in result["verdict"].lower()

    def test_static_formula_path_strict_check(self, monkeypatch):
        """No hint → static_formula → strict ``total_min ≤ budget_min``.
        At 63/60, the measured path would slack to feasible; the static
        path must reject."""
        _patch_phases(monkeypatch, train_sec=3500, inf_sec=200, score_sec=80)
        result = ts.run_skill(
            FakeSandbox(),
            **_base_kwargs(time_budget_minutes=60.0),
        )
        assert result["breakdown"]["inference_ms_source"] == "static_formula"
        assert result["breakdown"]["over_effective_budget"] is True  # strict: 63 > 60
        assert result["breakdown"]["slack_applied"] is False
        assert result["breakdown"]["effective_budget_minutes"] == pytest.approx(60.0)

    def test_x27_fallback_path_strict_check(self, monkeypatch):
        """Training-warmup-fallback path keeps the strict check too —
        only the measured path gets slack, because only the measured
        path has the precision to justify it."""
        _patch_phases(monkeypatch, train_sec=3500, inf_sec=200, score_sec=80)
        monkeypatch.setattr(
            ts,
            "_measure_ms_per_step",
            lambda **kwargs: (
                5.0,
                {
                    "n_warmup_batches": 1,
                    "n_timed_batches": 4,
                    "timings_ms": [],
                    "aggregator": "median",
                },
            ),
        )
        result = ts.run_skill(
            FakeSandbox(),
            **_base_kwargs(time_budget_minutes=60.0),
            data_dir="/some/fake/dir",
        )
        assert result["breakdown"]["inference_ms_source"] == "training_warmup_x2.7_fallback"
        assert result["breakdown"]["over_effective_budget"] is True
        assert result["breakdown"]["slack_applied"] is False


# ---------------------------------------------------------------------------
# Breakdown shape — every gate result carries the new keys
# ---------------------------------------------------------------------------


class TestBreakdownShape:
    @pytest.mark.parametrize(
        "hint,data_dir,expected_source",
        [
            (50.0, None, "trial_inference_warmup"),
            (None, None, "static_formula"),
        ],
    )
    def test_breakdown_carries_required_keys(
        self,
        monkeypatch,
        hint,
        data_dir,
        expected_source,
    ):
        """Every successful gate verdict must surface the three new
        breakdown keys so the tuner / audit log can record them
        uniformly without ``.get(...)`` fallbacks dropping signal."""
        _patch_phases(monkeypatch, train_sec=600, inf_sec=120, score_sec=60)
        kwargs = _base_kwargs(time_budget_minutes=60.0)
        if data_dir is not None:
            kwargs["data_dir"] = data_dir
        if hint is not None:
            kwargs["inference_per_psd_seg_ms_hint"] = hint
        result = ts.run_skill(FakeSandbox(), **kwargs)
        assert result["breakdown"]["inference_ms_source"] == expected_source
        assert "slack_applied" in result["breakdown"]
        assert "effective_budget_minutes" in result["breakdown"]


# --------------------------------------------------------------------- #
# Tuner helper: _latest_trial_inference_marginal
# --------------------------------------------------------------------- #
#
# The helper feeds the wrapper's hint kwarg, so its eligibility predicate
# (status=success AND time_mode=trial AND measured>0) is a load-bearing
# part of the hint-path contract. Pin it here, next to the wrapper tests
# that consume it.


from nodes.ml_hyperparameter_tune_agent import (
    _latest_trial_inference_marginal,
)


def _rec(status: str, time_mode: str | None, measured) -> dict:
    """Synthesize a memory-history record with only the fields the helper
    inspects. Anything else is irrelevant — keep the fixture minimal."""
    mem: dict = {}
    if time_mode is not None:
        mem["time_mode"] = time_mode
    if measured is not None:
        mem["inference_per_psd_seg_ms_measured"] = measured
    return {"status": status, "memory": mem}


class TestLatestTrialInferenceMarginal:
    def test_returns_most_recent_successful_trial(self):
        history = [
            _rec("success", "trial", 0.40),
            _rec("success", "trial", 0.55),  # most recent — wins
        ]
        assert _latest_trial_inference_marginal(history) == pytest.approx(0.55)

    def test_skips_formal_records(self):
        history = [
            _rec("success", "trial", 0.40),
            _rec("success", "formal", 0.99),  # later but formal — ignored
        ]
        assert _latest_trial_inference_marginal(history) == pytest.approx(0.40)

    def test_skips_failed_records(self):
        history = [
            _rec("success", "trial", 0.42),
            _rec("oom_killed", "trial", 0.99),  # later but failed — ignored
        ]
        assert _latest_trial_inference_marginal(history) == pytest.approx(0.42)

    def test_returns_none_on_empty_history(self):
        assert _latest_trial_inference_marginal([]) is None

    def test_returns_none_when_no_qualifying_record(self):
        history = [
            _rec("oom_killed", "trial", 0.5),
            _rec("success", "formal", 0.6),
            _rec("success", "trial", None),  # measured missing
            _rec("success", "trial", 0.0),  # not strictly positive
        ]
        assert _latest_trial_inference_marginal(history) is None

    def test_handles_missing_memory_dict(self):
        # A record can land with memory=None when an early-failure path
        # writes the skeleton; the helper must tolerate that without
        # raising — the predicate is just "no qualifying value".
        history = [{"status": "success", "memory": None}]
        assert _latest_trial_inference_marginal(history) is None

    def test_skips_record_with_missing_time_mode(self):
        # A record where memory exists but time_mode key was never set
        # (legacy or partial write) must be treated as non-qualifying.
        history = [
            {"status": "success", "memory": {"inference_per_psd_seg_ms_measured": 0.5}},
        ]
        assert _latest_trial_inference_marginal(history) is None

    def test_oom_between_two_trials_does_not_displace_recent(self):
        # Realistic chain: trial r1 succeeds, trial r2 OOM, trial r3
        # succeeds. The reverse-walk picks r3 (most recent success), not r1.
        history = [
            _rec("success", "trial", 0.30),
            _rec("oom_killed", "trial", None),
            _rec("success", "trial", 0.50),
        ]
        assert _latest_trial_inference_marginal(history) == pytest.approx(0.50)
