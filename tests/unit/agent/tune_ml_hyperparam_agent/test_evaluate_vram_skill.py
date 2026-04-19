"""
Tests for agent/skills/evaluate_vram_skill/wrapper.py

Covers:
  - Error: no GPU available (CUDA not present)
  - Error: GPU present but free VRAM < 4 GB
  - Success feasible: config fits within 80% of free VRAM
  - Success infeasible: config exceeds 80% of free VRAM (OOM risk)
  - CPU device: skips VRAM check, always feasible
  - Focal loss: one_hot term correctly increases estimated memory
  - Suggestion present when infeasible
"""

import pytest
from unittest.mock import patch

from agent.skills.evaluate_vram_skill.wrapper import run_skill

# ---------------------------------------------------------------------------
# Shared fixtures / constants
# ---------------------------------------------------------------------------

_GB = 1024 ** 3
_4GB  = 4  * _GB
_8GB  = 8  * _GB
_16GB = 16 * _GB
_3GB  = 3  * _GB   # below the 4 GB floor → should error


class FakeSandbox:
    """Minimal stand-in; evaluate_vram_skill never calls sandbox methods."""
    pass


# Tiny RNN that instantiates quickly on CPU
SMALL_RNN_CFG = {
    "model_type": "rnn",
    "segmentation_size": 1000,
    "embedding_dim": 8,
    "hidden_dim": 8,
    "num_layers": 1,
}
CUDA_TRAIN_CFG = {"lr": 1e-4, "epochs": 1, "batch_size": 2, "device": "cuda"}
CPU_TRAIN_CFG  = {"lr": 1e-4, "epochs": 1, "batch_size": 2, "device": "cpu"}
CE_LOSS_CFG    = {"loss_type": "ce"}
FOCAL_LOSS_CFG = {"loss_type": "focal"}

# ---------------------------------------------------------------------------
# Error conditions
# ---------------------------------------------------------------------------

class TestErrorConditions:

    def test_no_cuda_available_returns_error(self):
        """If device='cuda' but torch says CUDA is unavailable → error."""
        with patch("torch.cuda.is_available", return_value=False):
            result = run_skill(
                FakeSandbox(),
                model_type="rnn",
                model_config=SMALL_RNN_CFG,
                train_config=CUDA_TRAIN_CFG,
                loss_config=CE_LOSS_CFG,
            )
        assert result["status"] == "error"
        assert "no GPU" in result["message"].lower() or "cuda" in result["message"].lower()

    def test_free_vram_below_4gb_returns_error(self):
        """If free VRAM < 4 GB → error regardless of config size."""
        with patch("torch.cuda.is_available", return_value=True), \
             patch("torch.cuda.mem_get_info", return_value=(_3GB, _16GB)):
            result = run_skill(
                FakeSandbox(),
                model_type="rnn",
                model_config=SMALL_RNN_CFG,
                train_config=CUDA_TRAIN_CFG,
                loss_config=CE_LOSS_CFG,
            )
        assert result["status"] == "error"
        assert "4 GB" in result["message"]

    def test_free_vram_exactly_4gb_does_not_error(self):
        """Free VRAM == 4 GB is the floor; should proceed to feasibility check."""
        with patch("torch.cuda.is_available", return_value=True), \
             patch("torch.cuda.mem_get_info", return_value=(_4GB, _16GB)):
            result = run_skill(
                FakeSandbox(),
                model_type="rnn",
                model_config=SMALL_RNN_CFG,
                train_config=CUDA_TRAIN_CFG,
                loss_config=CE_LOSS_CFG,
            )
        assert result["status"] == "success"   # not an error

# ---------------------------------------------------------------------------
# Feasibility verdicts
# ---------------------------------------------------------------------------

class TestFeasibilityVerdicts:

    def test_small_config_is_feasible(self):
        """A tiny RNN config should comfortably fit in 16 GB."""
        with patch("torch.cuda.is_available", return_value=True), \
             patch("torch.cuda.mem_get_info", return_value=(_16GB, _16GB)):
            result = run_skill(
                FakeSandbox(),
                model_type="rnn",
                model_config=SMALL_RNN_CFG,
                train_config=CUDA_TRAIN_CFG,
                loss_config=CE_LOSS_CFG,
            )
        assert result["status"] == "success"
        assert result["feasible"] is True

    def test_large_config_is_infeasible(self):
        """A large batch+seg RNN with focal loss should exceed 80% of 4 GB."""
        big_rnn_cfg = {
            "model_type": "rnn",
            "segmentation_size": 50000,
            "embedding_dim": 64,
            "hidden_dim": 64,
            "num_layers": 2,
        }
        big_train = {"lr": 1e-4, "epochs": 1, "batch_size": 512, "device": "cuda"}
        with patch("torch.cuda.is_available", return_value=True), \
             patch("torch.cuda.mem_get_info", return_value=(_4GB, _16GB)):
            result = run_skill(
                FakeSandbox(),
                model_type="rnn",
                model_config=big_rnn_cfg,
                train_config=big_train,
                loss_config=FOCAL_LOSS_CFG,
            )
        assert result["status"] == "success"
        assert result["feasible"] is False

    def test_infeasible_result_has_suggestion(self):
        """An infeasible config must return a non-empty suggestion string."""
        big_rnn_cfg = {
            "model_type": "rnn",
            "segmentation_size": 50000,
            "embedding_dim": 64,
            "hidden_dim": 64,
            "num_layers": 2,
        }
        big_train = {"lr": 1e-4, "epochs": 1, "batch_size": 512, "device": "cuda"}
        with patch("torch.cuda.is_available", return_value=True), \
             patch("torch.cuda.mem_get_info", return_value=(_4GB, _16GB)):
            result = run_skill(
                FakeSandbox(),
                model_type="rnn",
                model_config=big_rnn_cfg,
                train_config=big_train,
                loss_config=FOCAL_LOSS_CFG,
            )
        assert result.get("suggestion", "") != ""

# ---------------------------------------------------------------------------
# CPU device
# ---------------------------------------------------------------------------

class TestCpuDevice:

    def test_cpu_device_always_feasible(self):
        """device='cpu' skips VRAM check entirely — always success + feasible."""
        # No torch.cuda mock needed: the skill short-circuits before touching cuda
        result = run_skill(
            FakeSandbox(),
            model_type="rnn",
            model_config=SMALL_RNN_CFG,
            train_config=CPU_TRAIN_CFG,
            loss_config=CE_LOSS_CFG,
        )
        assert result["status"] == "success"
        assert result["feasible"] is True

    def test_cpu_device_no_vram_fields(self):
        """CPU result must NOT include vram_free_gb (no GPU queried)."""
        result = run_skill(
            FakeSandbox(),
            model_type="rnn",
            model_config=SMALL_RNN_CFG,
            train_config=CPU_TRAIN_CFG,
            loss_config=CE_LOSS_CFG,
        )
        assert "vram_free_gb" not in result

# ---------------------------------------------------------------------------
# Memory breakdown correctness
# ---------------------------------------------------------------------------

class TestMemoryBreakdown:

    def test_focal_loss_increases_training_phase_estimate(self):
        """Focal loss (one_hot int64) increases the *training-phase* byte
        total. Post-K.2.5 the wrapper reports the peak across phases, and
        for the small RNN config inference dominates both CE and focal —
        so the loss-type difference only surfaces inside
        ``phase_breakdown['training']``, not in ``estimated_gb`` itself."""
        with patch("torch.cuda.is_available", return_value=True), \
             patch("torch.cuda.mem_get_info", return_value=(_16GB, _16GB)):
            result_ce = run_skill(
                FakeSandbox(),
                model_type="rnn",
                model_config=SMALL_RNN_CFG,
                train_config=CUDA_TRAIN_CFG,
                loss_config=CE_LOSS_CFG,
            )
            result_focal = run_skill(
                FakeSandbox(),
                model_type="rnn",
                model_config=SMALL_RNN_CFG,
                train_config=CUDA_TRAIN_CFG,
                loss_config=FOCAL_LOSS_CFG,
            )
        assert (
            result_focal["phase_breakdown"]["training"]["total_bytes"]
            > result_ce["phase_breakdown"]["training"]["total_bytes"]
        )

    def test_result_contains_num_params(self):
        """Result must include the exact parameter count from model instantiation."""
        with patch("torch.cuda.is_available", return_value=True), \
             patch("torch.cuda.mem_get_info", return_value=(_16GB, _16GB)):
            result = run_skill(
                FakeSandbox(),
                model_type="rnn",
                model_config=SMALL_RNN_CFG,
                train_config=CUDA_TRAIN_CFG,
                loss_config=CE_LOSS_CFG,
            )
        assert "num_params" in result
        assert result["num_params"] > 0


# ---------------------------------------------------------------------------
# Phase K — vram_budget_gb kwarg + contention log
# ---------------------------------------------------------------------------

class TestVramBudget:
    """``vram_budget_gb`` is an optional kwarg added in Phase K.

    When unset (legacy path), behaviour must be byte-identical to the
    defensive-only limit and the 4 GB minimum-free floor stays active. When
    set, ``limit = min(free × 0.80, budget × GB)``, the 4 GB floor is skipped
    (contended GPUs yield a feasibility verdict, not a crash), and a
    ``[VRAM] Contention detected`` log line is emitted when the defensive cap
    pinches the limit below half the budget.

    See docs/resource_estimator_implement.md §10.5.
    """

    def test_budget_passthrough_in_result(self):
        """The budget kwarg must appear unchanged in the result dict so the
        tuner can persist it in ``ExperimentMemory.vram_budget_gb``."""
        with patch("torch.cuda.is_available", return_value=True), \
             patch("torch.cuda.mem_get_info", return_value=(_16GB, _16GB)):
            result = run_skill(
                FakeSandbox(),
                model_type="rnn",
                model_config=SMALL_RNN_CFG,
                train_config=CUDA_TRAIN_CFG,
                loss_config=CE_LOSS_CFG,
                vram_budget_gb=10.0,
            )
        assert result["status"] == "success"
        assert result["vram_budget_gb"] == 10.0

    def test_none_budget_preserves_legacy_limit(self):
        """Regression: ``vram_budget_gb=None`` must produce the pre-Phase-K
        limit (``free × 0.80``) and pass through as ``None`` in the result."""
        with patch("torch.cuda.is_available", return_value=True), \
             patch("torch.cuda.mem_get_info", return_value=(_16GB, _16GB)):
            result = run_skill(
                FakeSandbox(),
                model_type="rnn",
                model_config=SMALL_RNN_CFG,
                train_config=CUDA_TRAIN_CFG,
                loss_config=CE_LOSS_CFG,
            )
        assert result["status"] == "success"
        # free × 0.80 == 16 × 0.80 == 12.8 GB
        assert result["limit_gb"] == pytest.approx(12.8, abs=0.01)
        assert result["vram_budget_gb"] is None

    def test_limit_is_min_defensive_when_budget_larger(self):
        """Defensive cap wins when ``budget > free × 0.80``."""
        with patch("torch.cuda.is_available", return_value=True), \
             patch("torch.cuda.mem_get_info", return_value=(_16GB, _16GB)):
            result = run_skill(
                FakeSandbox(),
                model_type="rnn",
                model_config=SMALL_RNN_CFG,
                train_config=CUDA_TRAIN_CFG,
                loss_config=CE_LOSS_CFG,
                vram_budget_gb=20.0,  # larger than defensive 12.8 GB
            )
        assert result["limit_gb"] == pytest.approx(12.8, abs=0.01)

    def test_limit_is_min_budget_when_budget_smaller(self):
        """Budget wins when it is below the defensive cap."""
        with patch("torch.cuda.is_available", return_value=True), \
             patch("torch.cuda.mem_get_info", return_value=(_16GB, _16GB)):
            result = run_skill(
                FakeSandbox(),
                model_type="rnn",
                model_config=SMALL_RNN_CFG,
                train_config=CUDA_TRAIN_CFG,
                loss_config=CE_LOSS_CFG,
                vram_budget_gb=8.0,  # below defensive 12.8 GB
            )
        assert result["limit_gb"] == pytest.approx(8.0, abs=0.01)

    def test_contention_log_emitted_when_defensive_below_half_budget(self, capsys):
        """Contention log fires when ``defensive_limit < budget_limit × 0.5``
        (another process is holding VRAM so the free-VRAM cap dominates).
        Here free=4 GB → defensive=3.2 GB; budget=20 GB → half=10 GB; 3.2 < 10
        → log fires."""
        with patch("torch.cuda.is_available", return_value=True), \
             patch("torch.cuda.mem_get_info", return_value=(_4GB, _16GB)):
            run_skill(
                FakeSandbox(),
                model_type="rnn",
                model_config=SMALL_RNN_CFG,
                train_config=CUDA_TRAIN_CFG,
                loss_config=CE_LOSS_CFG,
                vram_budget_gb=20.0,
            )
        captured = capsys.readouterr()
        assert "[VRAM] Contention detected" in captured.out

    def test_contention_log_not_emitted_when_defensive_above_half_budget(self, capsys):
        """No contention when the defensive cap is not pinching. free=16 GB
        → defensive=12.8 GB; budget=20 GB → half=10 GB; 12.8 > 10 → no log."""
        with patch("torch.cuda.is_available", return_value=True), \
             patch("torch.cuda.mem_get_info", return_value=(_16GB, _16GB)):
            run_skill(
                FakeSandbox(),
                model_type="rnn",
                model_config=SMALL_RNN_CFG,
                train_config=CUDA_TRAIN_CFG,
                loss_config=CE_LOSS_CFG,
                vram_budget_gb=20.0,
            )
        captured = capsys.readouterr()
        assert "Contention detected" not in captured.out

    def test_budget_set_bypasses_4gb_floor(self):
        """Free VRAM < 4 GB must NOT error when a budget is set — the
        contended-GPU case should yield a feasibility verdict (so the tuner
        saves a ``skipped_oom_risk`` record and keeps planning) rather than
        crashing the loop."""
        with patch("torch.cuda.is_available", return_value=True), \
             patch("torch.cuda.mem_get_info", return_value=(_3GB, _16GB)):
            result = run_skill(
                FakeSandbox(),
                model_type="rnn",
                model_config=SMALL_RNN_CFG,
                train_config=CUDA_TRAIN_CFG,
                loss_config=CE_LOSS_CFG,
                vram_budget_gb=20.0,
            )
        assert result["status"] == "success"   # NOT "error"
        assert "feasible" in result            # a verdict is produced

    def test_suggestion_is_generic_when_infeasible(self):
        """Phase K moved per-lever guidance to the planner prompt; the skill's
        suggestion is now a single generic line listing depth/width/
        batch_size/segmentation_size without a computed ``safe_bs``."""
        big_rnn_cfg = {
            "model_type": "rnn",
            "segmentation_size": 50000,
            "embedding_dim": 64,
            "hidden_dim": 64,
            "num_layers": 2,
        }
        big_train = {"lr": 1e-4, "epochs": 1, "batch_size": 512, "device": "cuda"}
        with patch("torch.cuda.is_available", return_value=True), \
             patch("torch.cuda.mem_get_info", return_value=(_4GB, _16GB)):
            result = run_skill(
                FakeSandbox(),
                model_type="rnn",
                model_config=big_rnn_cfg,
                train_config=big_train,
                loss_config=FOCAL_LOSS_CFG,
                vram_budget_gb=2.0,
            )
        assert result["feasible"] is False
        s = result["suggestion"]
        # No numeric per-field prescription (e.g. "Reduce batch_size to ~123")
        assert "~" not in s
        # Mentions the generic lever list
        for lever in ("depth", "width", "batch_size", "segmentation_size"):
            assert lever in s


# ---------------------------------------------------------------------------
# K.2.5 — peak aggregator over 3 phases
# ---------------------------------------------------------------------------

class TestPeakAggregation:
    """K.2.5 turns this skill into a peak aggregator over training,
    inference, and scoring. The binding constraint is the single phase
    with the highest byte total (phases run in isolated subprocesses, so
    they compete against the same VRAM ceiling one at a time)."""

    def test_phase_breakdown_contains_all_three_phases(self):
        """Every successful call exposes all 3 phases; scoring is always 0."""
        with patch("torch.cuda.is_available", return_value=True), \
             patch("torch.cuda.mem_get_info", return_value=(_16GB, _16GB)):
            result = run_skill(
                FakeSandbox(),
                model_type="rnn",
                model_config=SMALL_RNN_CFG,
                train_config=CUDA_TRAIN_CFG,
                loss_config=CE_LOSS_CFG,
            )
        assert set(result["phase_breakdown"].keys()) == {"training", "inference", "scoring"}
        assert result["phase_breakdown"]["scoring"]["total_bytes"] == 0
        assert result["phase_breakdown"]["scoring"]["phase"]       == "scoring"

    def test_training_dominant_matches_pre_k25_training_formula(self):
        """**Regression**: when training dominates, ``estimated_gb`` equals the
        training-phase byte total / GB — i.e. the pre-K.2.5 training-only
        formula is preserved exactly in that regime. A large-batch + focal
        config guarantees training dominance over inference (which uses the
        registered inference_batch, typically ≤25)."""
        big_rnn = {
            "model_type": "rnn",
            "segmentation_size": 50000,
            "embedding_dim": 64,
            "hidden_dim": 64,
            "num_layers": 2,
        }
        big_train = {"lr": 1e-4, "epochs": 1, "batch_size": 512, "device": "cuda"}
        with patch("torch.cuda.is_available", return_value=True), \
             patch("torch.cuda.mem_get_info", return_value=(_16GB, _16GB)):
            result = run_skill(
                FakeSandbox(),
                model_type="rnn",
                model_config=big_rnn,
                train_config=big_train,
                loss_config=FOCAL_LOSS_CFG,
                vram_budget_gb=1000.0,  # take the feasibility gate out of the way
            )
        assert result["dominant_phase"] == "training"
        training_bytes = result["phase_breakdown"]["training"]["total_bytes"]
        assert result["estimated_gb"] == pytest.approx(training_bytes / _GB, abs=0.01)

    def test_monkeypatched_huge_inference_batch_makes_inference_dominant(self):
        """**Crossover**: monkeypatch the inference batch to a huge number
        → inference's forward activations swamp training's grads+Adam. This
        is exactly the regime K.2.5 makes observable; before the peak
        aggregator, ``estimated_gb`` would have been the training-only
        number and the planner would have silently under-forecast."""
        from agent.skills.inference_skill import estimator as inf_est
        with patch("torch.cuda.is_available", return_value=True), \
             patch("torch.cuda.mem_get_info", return_value=(_16GB, _16GB)), \
             patch.object(inf_est, "inference_batch_for", return_value=10_000):
            result = run_skill(
                FakeSandbox(),
                model_type="rnn",
                model_config=SMALL_RNN_CFG,
                train_config=CUDA_TRAIN_CFG,
                loss_config=CE_LOSS_CFG,
            )
        assert result["dominant_phase"] == "inference"
        inference_bytes = result["phase_breakdown"]["inference"]["total_bytes"]
        training_bytes  = result["phase_breakdown"]["training"]["total_bytes"]
        assert inference_bytes > training_bytes
        assert result["estimated_gb"] == pytest.approx(inference_bytes / _GB, abs=0.01)

    def test_cpu_path_still_exposes_phase_breakdown(self):
        """CPU short-circuit skips the feasibility gate but must still
        return the per-phase breakdown (callers downstream may inspect
        it even without a GPU)."""
        result = run_skill(
            FakeSandbox(),
            model_type="rnn",
            model_config=SMALL_RNN_CFG,
            train_config=CPU_TRAIN_CFG,
            loss_config=CE_LOSS_CFG,
        )
        assert set(result["phase_breakdown"].keys()) == {"training", "inference", "scoring"}
        assert "dominant_phase" in result


# ---------------------------------------------------------------------------
# K.2.5-8 — soft fallback for unregistered model_type in inference estimator.
# Mirrors the surfacing tests in test_evaluate_time_skill.py. Both gates call
# the same inference estimator, so the breakdown flag is identical; both
# wrappers must (a) emit a prominent !!! stdout warning so the substitution is
# never silent and (b) propagate the flag onto their return dict so the tuner
# can stash it in ExperimentMemory.inference_batch_uncalibrated.
# See docs/resource_estimator_implement.md §10.14 K.2.5-8.
# ---------------------------------------------------------------------------

class TestUnregisteredModelTypeFallback:

    def test_unregistered_model_type_emits_warning_and_flags_breakdown(
        self, monkeypatch, capsys,
    ):
        """A model_type with no entry in _INFERENCE_BATCH_SIZES (the K.8.1
        ``pe_wavenet_delta`` case) must:
          1. NOT crash the gate (pre-K.2.5-8 raised ValueError),
          2. Emit a prominent ``!!! [evaluate_vram_skill]`` warning line so the
             substitution is auditable in the run log,
          3. Carry ``inference_batch_uncalibrated == True`` on the return dict
             so the tuner can stash it on the ExperimentMemory record."""
        # _count_params would fail on an unregistered model_type because it
        # indexes MODEL_REGISTRY. Stub it so the test exercises the gate path,
        # not the model-loading path.
        import agent.skills.evaluate_vram_skill.wrapper as vw
        monkeypatch.setattr(vw, "_count_params", lambda mt, mc, lt: 100_000)

        with patch("torch.cuda.is_available", return_value=True), \
             patch("torch.cuda.mem_get_info", return_value=(_16GB, _16GB)):
            result = run_skill(
                FakeSandbox(),
                model_type="pe_wavenet_delta",
                model_config=SMALL_RNN_CFG,
                train_config=CUDA_TRAIN_CFG,
                loss_config=CE_LOSS_CFG,
            )

        assert result["status"] == "success"
        assert result["inference_batch_uncalibrated"] is True

        captured = capsys.readouterr()
        assert "!!! [evaluate_vram_skill]" in captured.out
        assert "pe_wavenet_delta" in captured.out
        assert "uncalibrated" in captured.out.lower()

    def test_registered_model_type_does_not_emit_warning(self, capsys):
        """Regression: the warning must fire ONLY for unregistered model_types.
        Every successful gate call on a seed model (rnn/wavenet/punet/...) would
        otherwise spam the run log."""
        with patch("torch.cuda.is_available", return_value=True), \
             patch("torch.cuda.mem_get_info", return_value=(_16GB, _16GB)):
            result = run_skill(
                FakeSandbox(),
                model_type="rnn",
                model_config=SMALL_RNN_CFG,
                train_config=CUDA_TRAIN_CFG,
                loss_config=CE_LOSS_CFG,
            )
        assert result["inference_batch_uncalibrated"] is False
        captured = capsys.readouterr()
        assert "!!! [evaluate_vram_skill]" not in captured.out

    def test_cpu_path_also_propagates_flag(self, monkeypatch):
        """The CPU short-circuit returns early but must still surface the flag
        so downstream records stay consistent across device modes."""
        import agent.skills.evaluate_vram_skill.wrapper as vw
        monkeypatch.setattr(vw, "_count_params", lambda mt, mc, lt: 100_000)

        result = run_skill(
            FakeSandbox(),
            model_type="pe_wavenet_delta",
            model_config=SMALL_RNN_CFG,
            train_config=CPU_TRAIN_CFG,
            loss_config=CE_LOSS_CFG,
        )
        assert result["status"] == "success"
        assert result["inference_batch_uncalibrated"] is True
