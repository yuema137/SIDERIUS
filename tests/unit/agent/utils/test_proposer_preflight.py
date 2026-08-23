"""Fix 2 Commit 5 — proposer-side pre-flight wall-time wrapper.

Covers ``estimate_proposal_time`` in
``agent/utils/proposer_preflight.py``. The wrapper is a CPU-only,
disk-free static-formula call into the three per-phase estimators
(training + inference + scoring). It must:

* Return the documented 4-key dict with numeric + boolean fields.
* Gate infeasible drafts: iter-2-style overshoots read as ``factor > 10``
  and ``feasible=False``.
* Let feasible drafts through: iter-4-style configs read as ``factor <
  5`` and ``feasible=True``.
* Reject nonsensical inputs early (``num_params<=0``,
  ``time_budget_minutes<=0``) instead of silently returning
  ``factor=0``.
* Never touch ``MODEL_REGISTRY`` — an invented novel architecture is
  fine because ``num_params`` is caller-supplied and the inference
  estimator has K.2.5-8 soft-fallback for unregistered types.
* Synthesise a default ``sample_set`` when absent (no HDF5 reads, no
  ``data_dir`` required).

See ``docs/reliable_resource_proposer.md`` §7 Decision 3 + §9 Commit 5.
"""

from __future__ import annotations

import pytest

from agent.utils.proposer_preflight import (
    _synthesise_default_sample_set,
    estimate_proposal_time,
)

# ---------------------------------------------------------------------------
# Config factories — shapes mirror the live proposer/tuner output.
# ---------------------------------------------------------------------------


def _train_cfg(epochs: int = 10, batch_size: int = 1) -> dict:
    return {
        "lr": 1e-4,
        "epochs": epochs,
        "batch_size": batch_size,
        "optimizer_type": "adamw",
        "weight_decay": 1e-5,
        "device": "cuda",
    }


def _loss_cfg() -> dict:
    return {"loss_type": "focal", "alpha": 0.5, "gamma": 2.0, "reduction": "mean"}


def _iter2_ssm_model_cfg() -> dict:
    """iter 2 of explore_novel_v3_0420 — 12-block SSM over seg=40000."""
    return {"segmentation_size": 40000, "num_blocks": 12, "state_dim": 16}


def _iter4_tcn_model_cfg() -> dict:
    """iter 4 of explore_novel_v3_0420 — the feasible baseline."""
    return {"segmentation_size": 40000, "num_blocks": 6, "kernel_size": 3}


# ---------------------------------------------------------------------------
# Return-shape invariants
# ---------------------------------------------------------------------------


class TestReturnShape:
    def test_returns_six_documented_keys(self):
        out = estimate_proposal_time(
            model_type="gated_fourier_tcn",
            model_config=_iter4_tcn_model_cfg(),
            train_config=_train_cfg(epochs=2),
            loss_config=_loss_cfg(),
            num_params=1_000_000,
            time_budget_minutes=20.0,
        )
        assert set(out.keys()) == {
            "estimated_minutes",
            "factor",
            "verdict",
            "feasible",
            "provenance",
            "advisory_only",
        }

    def test_provenance_constants_are_producer_derived(self):
        """C1: the static path ALWAYS stamps static_uncalibrated +
        advisory_only=True — there is no caller input that can change
        them (no kwarg exists), so static evidence can never present
        itself as blocking-eligible."""
        out = estimate_proposal_time(
            model_type="gated_fourier_tcn",
            model_config=_iter4_tcn_model_cfg(),
            train_config=_train_cfg(epochs=2),
            loss_config=_loss_cfg(),
            num_params=1_000_000,
            time_budget_minutes=20.0,
        )
        assert out["provenance"] == "static_uncalibrated"
        assert out["advisory_only"] is True
        import inspect

        from agent.utils.proposer_preflight import estimate_proposal_time as f

        params = inspect.signature(f).parameters
        assert "provenance" not in params
        assert "advisory_only" not in params

    def test_factor_matches_estimated_over_budget(self):
        """``factor == round(estimated / budget, 3)`` — guards against a
        unit mismatch sneaking in later."""
        out = estimate_proposal_time(
            model_type="gated_fourier_tcn",
            model_config=_iter4_tcn_model_cfg(),
            train_config=_train_cfg(epochs=2),
            loss_config=_loss_cfg(),
            num_params=1_000_000,
            time_budget_minutes=20.0,
        )
        expected = round(out["estimated_minutes"] / 20.0, 3)
        assert out["factor"] == pytest.approx(expected, rel=1e-2)

    def test_verdict_reflects_feasibility(self):
        infeasible = estimate_proposal_time(
            model_type="scan_net",
            model_config=_iter2_ssm_model_cfg(),
            train_config=_train_cfg(epochs=10),
            loss_config=_loss_cfg(),
            num_params=50_000_000,
            time_budget_minutes=20.0,
        )
        # Budget 120.0 (not 20.0) on the feasible case: the iter4-style
        # 500k-param TCN reads as ~82 min worst-case under the current
        # estimator constants (SAFETY_MULTIPLIER=1.3, _STATIC_MS_PER_FLOP=3e-9,
        # per_psd_segment_seconds=2.21 — the scoring tail rebaselined
        # 2026-04-30 from a warm-cache micro-benchmark to a full-validation
        # measurement, +3.6x). 120 min preserves the test's narrative
        # ("config that succeeded in the live run reads as FITS") without
        # changing the model config itself.
        feasible = estimate_proposal_time(
            model_type="gated_fourier_tcn",
            model_config=_iter4_tcn_model_cfg(),
            train_config=_train_cfg(epochs=2),
            loss_config=_loss_cfg(),
            num_params=500_000,
            time_budget_minutes=120.0,
        )
        assert "OVER BUDGET" in infeasible["verdict"]
        assert "FITS" in feasible["verdict"]


# ---------------------------------------------------------------------------
# Feasibility gate — iter 2 infeasible vs iter 4 feasible
# ---------------------------------------------------------------------------


class TestFeasibilityGate:
    def test_iter2_style_overshoot_flagged_infeasible(self):
        """iter 2's 12-block SSM at seg=40000 × 10 epochs × a typical
        SSM param budget (~50M) must read as ``feasible=False`` with a
        factor well above the 5× structural threshold used downstream —
        this is exactly the configuration that blew up in the live run.
        """
        out = estimate_proposal_time(
            model_type="selective_bidirectional_scan_conv",
            model_config=_iter2_ssm_model_cfg(),
            train_config=_train_cfg(epochs=10),
            loss_config=_loss_cfg(),
            num_params=50_000_000,
            time_budget_minutes=20.0,
        )
        assert out["feasible"] is False
        assert out["factor"] > 10.0, f"iter-2 overshoot must read ≫1×; got factor={out['factor']}"

    def test_iter4_style_tcn_passes_feasibility(self):
        """iter 4's 6-block TCN at a modest ~500k param budget completes
        inside the trial budget. Must not be false-banned — this is the
        pattern that actually succeeded in the live run.

        Budget calibration (current constants): Phase 6.8 §4.2 raised the
        safety multiplier from 1.1 to 2.0 and the per-FLOP coefficient
        from 6e-10 to 3e-9 to absorb formula error on novel architectures.
        The multiplier was subsequently relaxed to 1.3 once overshoot data
        showed 2.0 was over-conservative, and the scoring tail constant
        ``per_psd_segment_seconds`` was rebaselined 0.613 -> 2.21 on
        2026-04-30 (warm-cache micro-bench was 3.6x optimistic about the
        full-validation per-segment cost). Net effect: a 500k-param
        6-block TCN at seg=40000 x 2 epochs now reads ~82 min worst-case
        under the default snapshot-0.1 sample_set, dominated by the
        scoring tail. The 120-min budget below preserves the test's
        intent ("this config that succeeded in the live run reads as
        feasible"); the live wall-clock for this style of config was
        ~20 min — the formula is deliberately pessimistic so novel-arch
        overshoots are caught before they consume the cluster.
        """
        out = estimate_proposal_time(
            model_type="gated_fourier_tcn",
            model_config=_iter4_tcn_model_cfg(),
            train_config=_train_cfg(epochs=2),
            loss_config=_loss_cfg(),
            num_params=500_000,
            time_budget_minutes=120.0,
        )
        assert out["feasible"] is True
        assert out["factor"] < 5.0

    def test_factor_monotonic_in_num_params(self):
        """Doubling ``num_params`` roughly doubles the training-static
        formula's contribution; even after the fixed scoring tail,
        ``factor`` must strictly increase. Guards against accidental
        saturation in the aggregation logic."""
        base = estimate_proposal_time(
            model_type="tcn",
            model_config=_iter4_tcn_model_cfg(),
            train_config=_train_cfg(epochs=2),
            loss_config=_loss_cfg(),
            num_params=1_000_000,
            time_budget_minutes=20.0,
        )
        bigger = estimate_proposal_time(
            model_type="tcn",
            model_config=_iter4_tcn_model_cfg(),
            train_config=_train_cfg(epochs=2),
            loss_config=_loss_cfg(),
            num_params=10_000_000,
            time_budget_minutes=20.0,
        )
        assert bigger["factor"] > base["factor"]

    def test_factor_monotonic_in_epochs(self):
        """More epochs → more total steps → larger factor. Belt-and-
        braces against the training estimator dropping the epochs term.
        """
        few = estimate_proposal_time(
            model_type="tcn",
            model_config=_iter4_tcn_model_cfg(),
            train_config=_train_cfg(epochs=2),
            loss_config=_loss_cfg(),
            num_params=1_000_000,
            time_budget_minutes=20.0,
        )
        many = estimate_proposal_time(
            model_type="tcn",
            model_config=_iter4_tcn_model_cfg(),
            train_config=_train_cfg(epochs=20),
            loss_config=_loss_cfg(),
            num_params=1_000_000,
            time_budget_minutes=20.0,
        )
        assert many["factor"] > few["factor"]


# ---------------------------------------------------------------------------
# Invalid input — early rejection with a clear ValueError
# ---------------------------------------------------------------------------


class TestInvalidInputs:
    def test_zero_num_params_raises(self):
        with pytest.raises(ValueError, match="num_params must be positive"):
            estimate_proposal_time(
                model_type="tcn",
                model_config=_iter4_tcn_model_cfg(),
                train_config=_train_cfg(),
                loss_config=_loss_cfg(),
                num_params=0,
                time_budget_minutes=20.0,
            )

    def test_negative_num_params_raises(self):
        with pytest.raises(ValueError, match="num_params must be positive"):
            estimate_proposal_time(
                model_type="tcn",
                model_config=_iter4_tcn_model_cfg(),
                train_config=_train_cfg(),
                loss_config=_loss_cfg(),
                num_params=-1,
                time_budget_minutes=20.0,
            )

    def test_zero_time_budget_raises(self):
        with pytest.raises(ValueError, match="time_budget_minutes must be positive"):
            estimate_proposal_time(
                model_type="tcn",
                model_config=_iter4_tcn_model_cfg(),
                train_config=_train_cfg(),
                loss_config=_loss_cfg(),
                num_params=1_000_000,
                time_budget_minutes=0.0,
            )

    def test_negative_time_budget_raises(self):
        with pytest.raises(ValueError, match="time_budget_minutes must be positive"):
            estimate_proposal_time(
                model_type="tcn",
                model_config=_iter4_tcn_model_cfg(),
                train_config=_train_cfg(),
                loss_config=_loss_cfg(),
                num_params=1_000_000,
                time_budget_minutes=-20.0,
            )


# ---------------------------------------------------------------------------
# MODEL_REGISTRY independence — the novel-architecture invariant
# ---------------------------------------------------------------------------


class TestUnregisteredModelType:
    """The whole point of this wrapper is that the proposer calls it
    **before** the implementor has registered the new architecture. The
    test asserts that an invented model_type like ``"brand_new_tag"``
    does not cause a ``KeyError`` — unlike calling
    ``evaluate_time_skill.run_skill`` directly which instantiates via
    ``MODEL_REGISTRY[model_type]``."""

    def test_invented_model_type_does_not_raise(self):
        out = estimate_proposal_time(
            model_type="completely_invented_architecture_v42",
            model_config=_iter4_tcn_model_cfg(),
            train_config=_train_cfg(epochs=2),
            loss_config=_loss_cfg(),
            num_params=1_000_000,
            time_budget_minutes=20.0,
        )
        assert "estimated_minutes" in out
        assert out["estimated_minutes"] > 0.0


# ---------------------------------------------------------------------------
# Default sample_set synthesis — no disk, correct shape
# ---------------------------------------------------------------------------


class TestDefaultSampleSet:
    def test_default_sample_set_has_twenty_files(self):
        """Snapshot strategy must produce 20 files (matches NUM_FILES in
        dataset_config.py for the TIDMAD dataset)."""
        ss = _synthesise_default_sample_set()
        assert len(ss) == 20

    def test_default_sample_set_has_non_empty_per_file_segments(self):
        ss = _synthesise_default_sample_set()
        for fi, segs in ss.items():
            assert len(segs) > 0, f"file {fi} has empty segment list"

    def test_default_sample_set_is_deterministic(self):
        """Same seed → identical sample_set. Required so two pre-flight
        calls on identical configs produce identical verdicts."""
        a = _synthesise_default_sample_set()
        b = _synthesise_default_sample_set()
        assert a == b

    def test_estimate_runs_without_sample_set_argument(self):
        """End-to-end smoke: the caller can omit ``sample_set`` and the
        wrapper synthesises one internally. This is the path the
        proposer will take in Commit 6."""
        out = estimate_proposal_time(
            model_type="tcn",
            model_config=_iter4_tcn_model_cfg(),
            train_config=_train_cfg(epochs=2),
            loss_config=_loss_cfg(),
            num_params=1_000_000,
            time_budget_minutes=20.0,
            # sample_set intentionally omitted
        )
        assert out["estimated_minutes"] > 0.0

    def test_trial_portion_kwarg_scales_default_sample_set(self):
        """trial_portion=0.02 must shrink the synthesised sample_set vs
        the 0.1 default — otherwise a caller that runs with
        ``HyperparamTuningInput.trial_portion=0.02`` (e.g. the score-table
        smoke gate) gets a 5x over-projected estimate even though its
        actual training scope is 5x smaller."""
        ss_default = _synthesise_default_sample_set()  # 0.1
        ss_small = _synthesise_default_sample_set(trial_portion=0.02)
        n_default = sum(len(v) for v in ss_default.values())
        n_small = sum(len(v) for v in ss_small.values())
        assert n_small < n_default, (
            f"trial_portion=0.02 sample_set ({n_small} segs) should be smaller "
            f"than the 0.1 default ({n_default} segs)"
        )

    def test_estimate_proposal_time_respects_trial_portion(self):
        """estimate_proposal_time must thread ``trial_portion`` into the
        synthesised sample_set so the wall-time estimate scales with the
        caller's actual scope.

        Expected ratio under the RT1 trainer-mirroring resolver
        (train_engine_sandbox per-file ``max(1, round(portion × n))`` +
        drop_last floor), with ``train_portion=0.1`` applied on top of the
        synthesised set:
          default: 20 files × ceil(0.1 × 200) = 20 segs/file
                   → keep round(0.1 × 20) = 2/file → 40 PSD trained
          small:   20 files × ceil(0.02 × 200) = 4 segs/file
                   → keep max(1, round(0.4)) = 1/file → 20 PSD trained
        Training scales ×0.5 (NOT the naive ×0.2 — the trainer's
        ``max(1, ·)`` per-file floor keeps one PSD per file, and the old
        global-product estimator under-predicted exactly this case);
        inference + scoring scale with the sample_set itself (×0.2). The
        blended ratio therefore lands strictly inside (0.2, 0.5).

        Regression target: pre-fix, trial_portion was ignored — a
        trial_portion=0.02 run was over-projected because the gate always
        synthesised snapshot@0.1 (ratio would be ~1.0).
        """
        kwargs = dict(
            model_type="tcn",
            model_config=_iter4_tcn_model_cfg(),
            train_config=_train_cfg(epochs=2),
            loss_config=_loss_cfg(),
            num_params=1_000_000,
            time_budget_minutes=20.0,
        )
        out_default = estimate_proposal_time(**kwargs)  # trial_portion=0.1
        out_small = estimate_proposal_time(**kwargs, trial_portion=0.02)

        actual_ratio = out_small["estimated_minutes"] / out_default["estimated_minutes"]
        assert 0.2 < actual_ratio < 0.5, (
            f"trial_portion=0.02 should land between the inference-scaling "
            f"bound (0.2) and the training max(1,·)-floor bound (0.5); got "
            f"{actual_ratio:.3f} ({out_small['estimated_minutes']:.2f} / "
            f"{out_default['estimated_minutes']:.2f} min)"
        )


# ---------------------------------------------------------------------------
# No GPU / no disk — negative assertions via monkeypatch
# ---------------------------------------------------------------------------


class TestNoGpuNoDisk:
    """The wrapper must run on CPU-only CI without ever importing
    ``torch.cuda`` or reading from the HDF5 data dir. Verified
    indirectly: if an estimator tried to open data files it would need
    ``data_dir``; we never pass one. If it tried to use CUDA it would
    need ``torch`` to report ``cuda_available``; the training estimator
    in static mode never consults that."""

    def test_runs_without_data_dir(self):
        """The synthesised sample_set is a plain dict of ints — no file
        paths, so no disk access can happen downstream."""
        out = estimate_proposal_time(
            model_type="tcn",
            model_config=_iter4_tcn_model_cfg(),
            train_config=_train_cfg(),
            loss_config=_loss_cfg(),
            num_params=1_000_000,
            time_budget_minutes=20.0,
        )
        assert out["estimated_minutes"] >= 0.0

    def test_no_cuda_probe_via_wrapper(self, monkeypatch):
        """The wrapper must not call ``torch.cuda.is_available`` in the
        pure path. We monkeypatch it to raise if called — if this test
        fails, a regression introduced a CUDA touch."""
        import sys

        if "torch" in sys.modules:

            def _boom():
                raise AssertionError(
                    "torch.cuda.is_available was called during pre-flight "
                    "— the wrapper must run on CPU-only CI without any "
                    "CUDA probe"
                )

            monkeypatch.setattr(sys.modules["torch"].cuda, "is_available", _boom)
        out = estimate_proposal_time(
            model_type="tcn",
            model_config=_iter4_tcn_model_cfg(),
            train_config=_train_cfg(),
            loss_config=_loss_cfg(),
            num_params=1_000_000,
            time_budget_minutes=20.0,
        )
        assert out["estimated_minutes"] > 0.0


# ---------------------------------------------------------------------------
# DS7b — pre-flight synthesis within the DataScope
# ---------------------------------------------------------------------------

from agent.utils.proposer_preflight import (
    _synthesise_default_sample_set,
)
from execute_tools.dataset_config import (
    NUM_FILES,
    DataScope,
)


class TestScopedSynthesis:
    def test_full_scope_unchanged(self):
        default = _synthesise_default_sample_set()
        explicit_full = _synthesise_default_sample_set(scope=DataScope.default())
        assert default == explicit_full
        assert sorted(default.keys()) == list(range(20))

    def test_partial_scope_covers_exactly_scope_files(self):
        scoped = _synthesise_default_sample_set(scope=DataScope(file_indices=[4, 5, 6, 7, 8, 9]))
        assert sorted(scoped.keys()) == [4, 5, 6, 7, 8, 9]
        # Same per-file segment count as the full-scope set — only the file
        # universe shrinks, so the estimate reflects the true training cost.
        full = _synthesise_default_sample_set()
        assert len(scoped[4]) == len(full[4])

    def test_estimate_uses_scoped_set(self):
        from agent.utils.proposer_preflight import estimate_proposal_time

        kwargs = dict(
            model_type="x",
            model_config={"segmentation_size": 4000},
            train_config={"batch_size": 8, "epochs": 1},
            loss_config={"loss_type": "focal"},
            num_params=1_000_000,
            time_budget_minutes=20.0,
        )
        full = estimate_proposal_time(**kwargs)
        scoped = estimate_proposal_time(
            **kwargs, data_scope=DataScope(file_indices=[4, 5, 6, 7, 8, 9])
        )
        # 6 of 20 files → strictly cheaper estimate.
        assert scoped["estimated_minutes"] < full["estimated_minutes"]
