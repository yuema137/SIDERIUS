"""
Tests for agent/skills/evaluate_time_skill/wrapper.py (K.2.5 Commit 6 —
sum aggregator over 3 phases).

Covers:
  - _suggest_lever routing (3 branches) — still lives in the wrapper.
  - run_skill feasible / infeasible branches (with _count_params
    monkeypatched so tests run without torch / model code).
  - run_skill error path on malformed model_config.
  - run_skill preserves the output contract shape (including new
    dominant_phase + phase_breakdown fields).
  - Sum semantics: estimated_minutes == Σ phase seconds / 60.
  - Warmup -> source routing: warmup ms/step propagates to
    breakdown.source; fallback lands as "static_formula".

Pure step-count and static-ms/step coverage is now in
tests/unit/agent/training_skill/test_estimator.py (the helpers moved
to the training estimator). This file focuses on the wrapper's
aggregation + contract behaviour.
"""

from __future__ import annotations

import pytest

from agent.skills.evaluate_time_skill import wrapper as ts

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class FakeSandbox:
    """TimeEval skill does not call sandbox methods."""


def _patch_count_params(monkeypatch, n_params: int) -> None:
    """Replace the wrapper's _count_params + the training estimator's internal
    _count_params so tests run without torch / model code. The inference
    estimator accepts num_params via kwarg, so no patch is needed there once
    the wrapper supplies it."""
    monkeypatch.setattr(ts, "_count_params", lambda mt, mc, lt: n_params)


def _base_kwargs(**overrides) -> dict:
    """Default kwargs for run_skill. Uses "rnn" as the model type because
    that's a registered inference-batch plugin — the inference estimator
    calls assert_inference_batch_registered at the top of its wall-time
    function, so an unregistered type would raise before anything runs."""
    kw = {
        "model_type": "rnn",
        "model_config": {"segmentation_size": 16000},
        "train_config": {"batch_size": 1, "epochs": 1, "device": "cpu"},
        "loss_config": {"loss_type": "focal"},
        "sample_set": {str(i): list(range(20)) for i in range(20)},  # 400 PSDs
        "train_portion": 1.0,
        "time_budget_minutes": 60.0,
    }
    kw.update(overrides)
    return kw


# ---------------------------------------------------------------------------
# _suggest_lever — three branches
# ---------------------------------------------------------------------------


def test_suggest_lever_high_ms_per_step_recommends_shrinking_model():
    assert "model depth/width" in ts._suggest_lever(ms_per_step=80.0, seg_size=1000, batch_size=1)


def test_suggest_lever_small_seg_bs1_recommends_raising_batch():
    assert "batch_size" in ts._suggest_lever(ms_per_step=2.0, seg_size=1000, batch_size=1)


def test_suggest_lever_otherwise_recommends_raising_seg_size():
    # ms below 50 and (seg >= 10_000 or batch > 1) → seg_size branch
    msg = ts._suggest_lever(ms_per_step=10.0, seg_size=16000, batch_size=1)
    assert "segmentation_size" in msg


# ---------------------------------------------------------------------------
# run_skill — contract shape + success path
# ---------------------------------------------------------------------------


_EXPECTED_KEYS = {
    "status",
    "feasible",
    "verdict",
    "suggestion",
    "estimated_minutes",
    "limit_minutes",
    "breakdown",
    "dominant_phase",
    "phase_breakdown",
    "inference_batch_uncalibrated",  # K.2.5-8 — soft-fallback flag (always present, True/False)
}


def test_run_skill_returns_contract_shape(monkeypatch):
    _patch_count_params(monkeypatch, 100_000)
    result = ts.run_skill(FakeSandbox(), **_base_kwargs())
    assert set(result.keys()) == _EXPECTED_KEYS
    assert result["status"] == "success"
    # Flat breakdown preserves the pre-K.2.5 keys used by
    # nodes/ml_hyperparameter_tune_agent.py (source + gpu_name for Phase F).
    assert set(result["breakdown"].keys()) >= {
        "total_train_steps",
        "ms_per_step_warmup",
        "k_correction",
        "safety_multiplier",
        "train_minutes",
        "num_params",
        "source",
        "gpu_name",
    }


def test_run_skill_phase_breakdown_contains_all_three_phases(monkeypatch):
    _patch_count_params(monkeypatch, 100_000)
    result = ts.run_skill(FakeSandbox(), **_base_kwargs())
    assert set(result["phase_breakdown"].keys()) == {"training", "inference", "scoring"}
    for phase, pb in result["phase_breakdown"].items():
        assert pb["phase"] == phase
        assert pb["seconds"] >= 0.0
        assert "breakdown" in pb


def test_run_skill_estimated_minutes_is_sum_of_phase_seconds(monkeypatch):
    _patch_count_params(monkeypatch, 100_000)
    result = ts.run_skill(FakeSandbox(), **_base_kwargs())
    total_sec = sum(p["seconds"] for p in result["phase_breakdown"].values())
    assert result["estimated_minutes"] == pytest.approx(total_sec / 60.0, rel=1e-3)


def test_run_skill_dominant_phase_is_training_for_typical_config(monkeypatch):
    # 100k params × 16000 seg × 400 PSDs is training-dominated under the
    # 2026-04-30 calibration (_INFERENCE_VS_TRAINING_RATIO=2.7, data-driven
    # median over V7 formal-success records). Per-step training cost × 250k
    # steps overwhelms the forward-only inference pass + FFT-bound scoring.
    _patch_count_params(monkeypatch, 100_000)
    result = ts.run_skill(FakeSandbox(), **_base_kwargs())
    assert result["dominant_phase"] == "training"


# ---------------------------------------------------------------------------
# Feasibility gate — keyed on the SUM of phase seconds
# ---------------------------------------------------------------------------


def test_run_skill_feasible_tiny_model(monkeypatch):
    # 100k params is tiny. Under the 2026-04-30 recalibration the static-path
    # total for this case is ≈ 88 min (train 26 + inf 60 + score 2). Budget is
    # the V7 formal-mode 120 min — still well within reach for a 100k-param
    # model.
    _patch_count_params(monkeypatch, 100_000)
    result = ts.run_skill(FakeSandbox(), **_base_kwargs(time_budget_minutes=120.0))
    assert result["feasible"] is True
    assert "FITS" in result["verdict"]
    assert result["suggestion"] == ""
    assert result["estimated_minutes"] < 120.0


def test_run_skill_infeasible_large_model(monkeypatch):
    # 50M params → ~480 ms/step × 250k steps × 1.1 safety → training alone
    # blows past 60 min, well before inference + scoring are added.
    _patch_count_params(monkeypatch, 50_000_000)
    result = ts.run_skill(FakeSandbox(), **_base_kwargs(time_budget_minutes=60.0))
    assert result["feasible"] is False
    assert "OVER BUDGET" in result["verdict"]
    assert result["suggestion"]  # non-empty
    assert result["estimated_minutes"] > 60.0


def test_run_skill_error_on_malformed_model_config(monkeypatch):
    # Don't patch _count_params — let it actually try to load a bogus model.
    # The error is caught by the wrapper's top-level try/except before any
    # estimator runs (so the unregistered-type assert in the inference
    # estimator is never reached).
    result = ts.run_skill(FakeSandbox(), **_base_kwargs(model_type="nonexistent_model"))
    assert result["status"] == "error"
    assert "message" in result


def test_run_skill_infeasible_suggestion_reflects_lever(monkeypatch):
    # High-ms/step path → model-shrink suggestion.
    _patch_count_params(monkeypatch, 100_000_000)  # 100M → ~960 ms/step at seg=16000
    result = ts.run_skill(FakeSandbox(), **_base_kwargs(time_budget_minutes=60.0))
    assert "model depth/width" in result["suggestion"]


def test_run_skill_safety_multiplier_surfaced_in_breakdown(monkeypatch):
    # The 1.1× safety multiplier is applied inside the training estimator,
    # and surfaces on the flat breakdown for compatibility with pre-K.2.5
    # callers. It also appears on the training-phase's phase_breakdown entry.
    _patch_count_params(monkeypatch, 1_000_000)
    result = ts.run_skill(FakeSandbox(), **_base_kwargs(time_budget_minutes=60.0))
    from agent.skills.training_skill import estimator as te

    assert result["breakdown"]["safety_multiplier"] == te.SAFETY_MULTIPLIER
    train_bd = result["phase_breakdown"]["training"]["breakdown"]
    assert train_bd["safety_multiplier"] == te.SAFETY_MULTIPLIER

    # Training phase seconds == total_steps × ms/step × k × safety / 1000.
    train_minutes = result["phase_breakdown"]["training"]["seconds"] / 60.0
    raw = train_bd["total_train_steps"] * train_bd["ms_per_step"] / 60_000.0
    assert train_minutes == pytest.approx(
        raw * train_bd["k_correction"] * te.SAFETY_MULTIPLIER, rel=1e-3
    )


# ---------------------------------------------------------------------------
# Warmup vs static-formula source routing
# ---------------------------------------------------------------------------


def _stub_warmup_breakdown(aggregator: str | None = "median") -> dict:
    """Match the shape of the real warmup breakdown for monkeypatched returns
    (Phase 6.7 Fix 1: ``_measure_ms_per_step`` now returns a tuple)."""
    return {
        "n_warmup_batches": 3,
        "n_timed_batches": 7,
        "timings_ms": [3.5] * 10 if aggregator else [],
        "aggregator": aggregator,
    }


def test_run_skill_uses_warmup_when_data_dir_and_measurement_available(monkeypatch):
    # When data_dir is passed and _measure_ms_per_step returns a positive
    # value, run_skill must use it and flag the source accordingly.
    _patch_count_params(monkeypatch, 100_000)
    monkeypatch.setattr(
        ts, "_measure_ms_per_step", lambda **kw: (3.5, _stub_warmup_breakdown("median"))
    )
    result = ts.run_skill(
        FakeSandbox(),
        **_base_kwargs(data_dir="/any/path"),
    )
    assert result["breakdown"]["source"] == "real_dataset_warmup"
    assert result["breakdown"]["ms_per_step_warmup"] == pytest.approx(3.5)


def test_run_skill_falls_back_to_static_when_warmup_returns_none(monkeypatch):
    # Warmup returns None (no CUDA, build failure, etc.) → static formula path.
    # Training estimator reports ms_source="static_formula"; wrapper surfaces
    # it as breakdown.source.
    _patch_count_params(monkeypatch, 100_000)
    monkeypatch.setattr(
        ts, "_measure_ms_per_step", lambda **kw: (None, _stub_warmup_breakdown(None))
    )
    result = ts.run_skill(
        FakeSandbox(),
        **_base_kwargs(data_dir="/any/path"),
    )
    assert result["breakdown"]["source"] == "static_formula_phase_b"


def test_run_skill_skips_warmup_without_data_dir(monkeypatch):
    # No data_dir → _measure_ms_per_step must not be invoked at all.
    _patch_count_params(monkeypatch, 100_000)
    calls = []

    def _should_not_be_called(**kw):
        calls.append(kw)
        return 99.0, _stub_warmup_breakdown("median")

    monkeypatch.setattr(ts, "_measure_ms_per_step", _should_not_be_called)
    result = ts.run_skill(FakeSandbox(), **_base_kwargs())
    assert calls == []
    assert result["breakdown"]["source"] == "static_formula_phase_b"


# ---------------------------------------------------------------------------
# Warmup propagation to inference phase
# ---------------------------------------------------------------------------


def test_warmup_scales_inference_ms_by_ratio(monkeypatch):
    # When the training warmup reports M ms/step, the wrapper must hand the
    # inference estimator M × _INFERENCE_VS_TRAINING_RATIO as its
    # inference_ms_per_step. Asserts against the imported constant rather than
    # a literal so the test remains correct under future recalibrations.
    from agent.skills.inference_skill.estimator import _INFERENCE_VS_TRAINING_RATIO

    _patch_count_params(monkeypatch, 100_000)
    measured = 9.0
    monkeypatch.setattr(
        ts, "_measure_ms_per_step", lambda **kw: (measured, _stub_warmup_breakdown("median"))
    )
    result = ts.run_skill(FakeSandbox(), **_base_kwargs(data_dir="/any/path"))
    inf_bd = result["phase_breakdown"]["inference"]["breakdown"]
    assert inf_bd["ms_source"] == "derived_from_training_warmup"
    assert inf_bd["ms_per_step"] == pytest.approx(measured * _INFERENCE_VS_TRAINING_RATIO, rel=1e-6)


# ---------------------------------------------------------------------------
# K.2.5-8 — soft fallback for unregistered model_type in inference estimator.
# Mirror of the surfacing tests in test_evaluate_vram_skill.py. Both wrappers
# call the same inference estimator and must independently (a) emit a
# prominent !!! stdout warning and (b) propagate inference_batch_uncalibrated
# onto the return dict so the tuner can stash it on ExperimentMemory.
# See docs/resource_estimator_implement.md §10.14 K.2.5-8.
# ---------------------------------------------------------------------------


class TestUnregisteredModelTypeFallback:
    def test_unregistered_model_type_emits_warning_and_flags_breakdown(
        self,
        monkeypatch,
        capsys,
    ):
        """An invented model_type (the K.8.1 ``pe_wavenet_delta`` case) must
        not crash the time gate, must emit a prominent ``!!! [evaluate_time_skill]``
        warning line, and must surface ``inference_batch_uncalibrated == True``
        on the return dict so the tuner record can carry it."""
        _patch_count_params(monkeypatch, 100_000)
        result = ts.run_skill(
            FakeSandbox(),
            **_base_kwargs(model_type="pe_wavenet_delta"),
        )
        assert result["status"] == "success"
        assert result["inference_batch_uncalibrated"] is True

        captured = capsys.readouterr()
        assert "!!! [evaluate_time_skill]" in captured.out
        assert "pe_wavenet_delta" in captured.out
        assert "uncalibrated" in captured.out.lower()

    def test_registered_model_type_does_not_emit_warning(
        self,
        monkeypatch,
        capsys,
    ):
        """Regression: the warning must fire ONLY for unregistered model_types
        — otherwise every seed-model gate call (rnn/wavenet/punet/...) would
        spam the run log."""
        _patch_count_params(monkeypatch, 100_000)
        result = ts.run_skill(FakeSandbox(), **_base_kwargs())  # default rnn
        assert result["inference_batch_uncalibrated"] is False
        captured = capsys.readouterr()
        assert "!!! [evaluate_time_skill]" not in captured.out


# ---------------------------------------------------------------------------
# Phase 6.7 Fix 1 — Steady-state warmup aggregator
#
# Pure helper tests: no torch, no CUDA, no DataLoader. The aggregator is the
# decision boundary between (a) reporting a steady-state median, (b) firing
# the fast-fail short-circuit, and (c) bailing to None. Pin all three branches
# plus the median's outlier-robustness vs the legacy mean.
# ---------------------------------------------------------------------------


class TestAggregateWarmupTimings:
    def test_empty_list_returns_none_and_aggregator_none(self):
        ms, bd = ts._aggregate_warmup_timings([], n_warmup_batches=3)
        assert ms is None
        assert bd["aggregator"] is None
        assert bd["n_warmup_batches"] == 3
        assert bd["n_timed_batches"] == 0
        assert bd["timings_ms"] == []

    def test_fast_fail_step0_above_threshold_returns_that_step_ms(self):
        # Step 0 already over the threshold → fast-fail branch wins, returns
        # that step's ms (worst-case-conservative; trips the time gate).
        ms, bd = ts._aggregate_warmup_timings(
            [7000.0, 6000.0, 6000.0],
            n_warmup_batches=3,
            fast_fail_threshold_ms=5000.0,
        )
        assert ms == 7000.0
        assert bd["aggregator"] == "fast_fail"
        # In the fast-fail branch we did NOT collect steady-state samples,
        # so n_timed_batches is 0 even if the loop completed extra iters.
        assert bd["n_timed_batches"] == 0
        # Raw timings are still surfaced so the audit log is complete.
        assert bd["timings_ms"] == [7000.0, 6000.0, 6000.0]

    def test_fast_fail_uses_default_threshold_constant(self):
        # The default threshold pulls from the module-level constant. This
        # pins the contract: changes to _WARMUP_FAST_FAIL_MS automatically
        # propagate through the aggregator without test churn.
        ms, bd = ts._aggregate_warmup_timings(
            [ts._WARMUP_FAST_FAIL_MS + 1.0],
            n_warmup_batches=1,
        )
        assert ms == ts._WARMUP_FAST_FAIL_MS + 1.0
        assert bd["aggregator"] == "fast_fail"

    def test_median_branch_discards_warmup_then_takes_median(self):
        # Three warmup steps (high) + four timed steps with a clear median.
        ms, bd = ts._aggregate_warmup_timings(
            [
                50.0,
                40.0,
                30.0,  # warmup
                10.0,
                12.0,
                14.0,
                16.0,
            ],  # timed → median 13.0
            n_warmup_batches=3,
        )
        assert ms == pytest.approx(13.0)
        assert bd["aggregator"] == "median"
        assert bd["n_timed_batches"] == 4

    def test_median_is_robust_to_one_outlier_unlike_mean(self):
        # The whole point of switching from mean to median: a single rogue
        # slow step (cudnn re-tune, scheduler hiccup) must NOT inflate the
        # estimate. Mean of [10, 10, 10, 10, 10, 10, 5000] = 722.86 ms →
        # would falsely fail the time budget. Median = 10 ms.
        timed_with_outlier = [10.0] * 6 + [5000.0]
        ms, bd = ts._aggregate_warmup_timings(
            [0.0, *timed_with_outlier],  # 1 warmup, 7 timed
            n_warmup_batches=1,
            # Raise threshold so the outlier doesn't trip fast-fail (we're
            # testing the median branch's robustness, not fast-fail).
            fast_fail_threshold_ms=10000.0,
        )
        assert ms == pytest.approx(10.0)
        # And confirm the legacy mean WOULD have been spoiled — not asserted
        # against the result, just an in-test sanity check.
        legacy_mean = sum(timed_with_outlier) / len(timed_with_outlier)
        assert legacy_mean > 700.0  # would have inflated the estimate

    def test_no_timed_steps_returns_none(self):
        # Loop terminated after warmup (StopIteration). No steady-state
        # samples → aggregator returns None and caller falls back to static.
        ms, bd = ts._aggregate_warmup_timings(
            [10.0, 10.0, 10.0],  # exactly n_warmup = 3, nothing timed
            n_warmup_batches=3,
        )
        assert ms is None
        assert bd["aggregator"] is None
        assert bd["n_timed_batches"] == 0


class TestBreakdownSurfacesWarmupAggregator:
    """The audit log routes off ``breakdown.warmup_aggregator``. Pin the
    propagation from ``_measure_ms_per_step``'s tuple return through to the
    final flat breakdown so visibility doesn't silently regress."""

    def test_median_aggregator_surfaces_on_breakdown(self, monkeypatch):
        _patch_count_params(monkeypatch, 100_000)
        monkeypatch.setattr(
            ts,
            "_measure_ms_per_step",
            lambda **kw: (
                3.5,
                {
                    "n_warmup_batches": 3,
                    "n_timed_batches": 7,
                    "timings_ms": [3.5] * 10,
                    "aggregator": "median",
                },
            ),
        )
        result = ts.run_skill(FakeSandbox(), **_base_kwargs(data_dir="/any/path"))
        bd = result["breakdown"]
        assert bd["warmup_aggregator"] == "median"
        assert bd["warmup_n_warmup_batches"] == 3
        assert bd["warmup_n_timed_batches"] == 7
        assert bd["warmup_timings_ms"] == [3.5] * 10

    def test_fast_fail_aggregator_surfaces_on_breakdown(self, monkeypatch):
        # When step 0 trips the threshold, the breakdown must show
        # 'fast_fail' so the audit log distinguishes a DOA model from a
        # genuinely slow-but-finished steady-state estimate.
        _patch_count_params(monkeypatch, 100_000)
        monkeypatch.setattr(
            ts,
            "_measure_ms_per_step",
            lambda **kw: (
                7000.0,
                {
                    "n_warmup_batches": 3,
                    "n_timed_batches": 0,  # short-circuited before any timed step
                    "timings_ms": [7000.0],
                    "aggregator": "fast_fail",
                },
            ),
        )
        result = ts.run_skill(FakeSandbox(), **_base_kwargs(data_dir="/any/path"))
        bd = result["breakdown"]
        assert bd["warmup_aggregator"] == "fast_fail"
        assert bd["warmup_n_timed_batches"] == 0
        assert bd["warmup_timings_ms"] == [7000.0]

    def test_no_data_dir_aggregator_is_none(self, monkeypatch):
        # Without data_dir the warmup never runs, so the aggregator field
        # must be None — not 'median' from a stale default.
        _patch_count_params(monkeypatch, 100_000)
        result = ts.run_skill(FakeSandbox(), **_base_kwargs())  # no data_dir
        bd = result["breakdown"]
        assert bd["warmup_aggregator"] is None
        assert bd["warmup_n_timed_batches"] == 0
        assert bd["warmup_timings_ms"] == []

    def test_legacy_breakdown_keys_still_present(self, monkeypatch):
        # Phase F's per-GPU EMA update in nodes/ml_hyperparameter_tune_agent.py
        # reads breakdown.source + breakdown.gpu_name. The new warmup_*
        # keys must coexist with these — not replace them.
        _patch_count_params(monkeypatch, 100_000)
        monkeypatch.setattr(
            ts,
            "_measure_ms_per_step",
            lambda **kw: (
                3.5,
                {
                    "n_warmup_batches": 3,
                    "n_timed_batches": 7,
                    "timings_ms": [3.5] * 10,
                    "aggregator": "median",
                },
            ),
        )
        result = ts.run_skill(FakeSandbox(), **_base_kwargs(data_dir="/any/path"))
        legacy_keys = {
            "total_train_steps",
            "ms_per_step_warmup",
            "k_correction",
            "safety_multiplier",
            "train_minutes",
            "num_params",
            "source",
            "gpu_name",
        }
        assert legacy_keys.issubset(set(result["breakdown"].keys()))


class TestMeasureMsPerStepDefaults:
    """The default warmup count moved from 1+2 to 3+7 in Phase 6.7. Pin the
    signature so a regression toward the legacy 1+2 (which is what the audit
    blamed for the cudnn-autotune-inflated mean) is loud."""

    def test_defaults_are_3_warmup_7_timed(self):
        import inspect

        sig = inspect.signature(ts._measure_ms_per_step)
        assert sig.parameters["n_warmup_batches"].default == 3
        assert sig.parameters["n_timed_batches"].default == 7

    def test_return_annotation_is_tuple(self):
        # The tuple return is the contract Commit 4's orchestrator (and any
        # future caller) reads against. Pin that the function advertises
        # ``tuple[float | None, dict]`` rather than the legacy bare scalar.
        import inspect

        sig = inspect.signature(ts._measure_ms_per_step)
        ret = sig.return_annotation
        # Either as the typing.Tuple form or the PEP 604 ``tuple[...]``.
        assert "tuple" in str(ret).lower()
        assert "dict" in str(ret).lower()
