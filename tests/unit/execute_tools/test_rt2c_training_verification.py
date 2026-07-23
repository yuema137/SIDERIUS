"""
RT2-C integration (in-process, tiny synthetic dataset): adaptive
training verification as the first production steps of the streaming
trainer's epoch-0 loop.

Design: docs/design/runtime_estimation_and_watchdog.md §2.5/§11 RT2-C
checkpoint — real micro-verification on a tiny config (seconds, CPU):

- verified path: steady state detected on real per-step timings, a
  measurement-backed training prediction lands on the observation, and
  execution continues seamlessly to completion;
- pathological path: an environment-scoped absolute unit threshold
  (§5) fails the verification mid-epoch and, with a budget in force,
  the attempt is rejected mid-loop (fail closed §2.11) with clean exit;
- record-only path: the same failure WITHOUT a budget records the
  evidence and completes training unchanged.
"""

from __future__ import annotations

import json
import os

import h5py
import numpy as np
import pytest

import execute_tools.train_engine_sandbox as tes
from core.runtime_control.adaptive import AdaptiveVerificationConfig
from core.runtime_control.session import RuntimeControlPolicy, RuntimeVerificationSession
from core.runtime_control.steady_state import SteadyStateConfig
from ml_models.models_format_sandbox import LossConfig, TrainConfig, WaveNetConfig

SEG_SIZE = 1000
N_PSD_SEGMENTS = 30  # 30 steps at batch_size=1


def _verification_config() -> AdaptiveVerificationConfig:
    """CPU-jitter-tolerant stopping policy for the tiny model."""
    return AdaptiveVerificationConfig(
        steady=SteadyStateConfig(window=3, stable_windows=2, rel_spread_tol=0.75, max_steps=25),
        min_timed_steps=3,
        min_timed_ms=1.0,
        max_steps=28,
        max_wall_ms=120_000.0,
    )


@pytest.fixture
def tiny_setup(tmp_path, monkeypatch):
    """Streaming-mode setup with enough segments for live verification."""
    monkeypatch.setattr(tes, "PSD_SEGMENT_LENGTH", SEG_SIZE)
    n_samples = N_PSD_SEGMENTS * SEG_SIZE
    rng = np.random.default_rng(7)
    with h5py.File(tmp_path / "abra_training_0000.h5", "w") as f:
        ts = f.create_group("timeseries")
        ts.create_group("channel0001").create_dataset(
            "timeseries", data=rng.integers(-128, 127, size=n_samples, dtype=np.int8)
        )
        ts.create_group("channel0002").create_dataset(
            "timeseries", data=rng.integers(-128, 127, size=n_samples, dtype=np.int16)
        )

    model_cfg = WaveNetConfig(
        segmentation_size=SEG_SIZE,
        input_channels=4,
        residual_channels=8,
        gate_channels=8,
        skip_channels=8,
        kernel_size=2,
        num_blocks=1,
    )
    train_cfg = TrainConfig(lr=1e-4, epochs=1, batch_size=1, optimizer_type="adam", device="cpu")

    sandbox_dirs = {
        "models": str(tmp_path / "cached_models"),
        "results": str(tmp_path / "records"),
    }
    os.makedirs(sandbox_dirs["models"], exist_ok=True)

    return {
        "data_dir": str(tmp_path),
        "sample_set": {"0": list(range(N_PSD_SEGMENTS))},
        "model_cfg": model_cfg,
        "train_cfg": train_cfg,
        "loss_cfg": LossConfig(),
        "sandbox_dirs": sandbox_dirs,
    }


def _run(setup, runtime_session, exp_id: str):
    return tes.run_experiment_streaming(
        setup["model_cfg"],
        setup["train_cfg"],
        setup["loss_cfg"],
        sample_set=setup["sample_set"],
        data_dir=setup["data_dir"],
        sandbox_dirs=setup["sandbox_dirs"],
        exp_id=exp_id,
        runtime_session=runtime_session,
    )


class TestVerifiedPath:
    def test_live_steps_verify_and_training_completes(self, tiny_setup, tmp_path):
        sidecar = tmp_path / "rv.json"
        session = RuntimeVerificationSession(
            str(sidecar),
            policy=RuntimeControlPolicy(
                operator_budget_seconds=3600.0, verification=_verification_config()
            ),
            attempt_id="exp_verified",
        )
        summary = _run(tiny_setup, session, "exp_verified")

        assert summary is not None and "final_loss" in summary
        assert os.path.exists(
            os.path.join(tiny_setup["sandbox_dirs"]["models"], "_OK_exp_verified")
        )

        obs = json.load(open(sidecar))
        assert obs["final_status"] == "completed"
        assert obs["admission"]["decision"] == "admitted"
        assert obs["admission"]["stage"] == "post_training_verification"
        assert obs["admission"]["verification_cost_seconds"] > 0.0

        training = obs["components"]["training"]
        assert training["prediction"] is not None
        assert training["prediction"]["source"] == "real_training_verification"
        assert training["prediction"]["formal_execution_eligible"] is True
        assert training["prediction"]["ms_per_unit"] > 0.0
        assert training["measurement"]["steady_state_reached"] is True
        # Actual recorded after the run → prediction error derived (§2.3).
        assert training["actual_seconds"] > 0.0
        assert training["prediction_error"] is not None

    def test_verification_overhead_is_fraction_of_run(self, tiny_setup, tmp_path):
        # §2.12: overhead reporting — the verification cost is bounded by
        # the steps it measured, which continue into training (0 wasted).
        sidecar = tmp_path / "rv.json"
        session = RuntimeVerificationSession(
            str(sidecar),
            policy=RuntimeControlPolicy(verification=_verification_config()),
        )
        _run(tiny_setup, session, "exp_overhead")
        obs = json.load(open(sidecar))
        training = obs["components"]["training"]
        if training["prediction"] is None:
            pytest.skip("CPU timing too jittery for detection in this environment")
        verification_s = training["prediction"]["detail"]["verification_seconds"]
        assert verification_s <= training["actual_seconds"]


class TestPathologicalRejection:
    def test_absolute_threshold_rejects_mid_epoch_with_budget(self, tiny_setup, tmp_path):
        sidecar = tmp_path / "rv.json"
        # Every real step exceeds 1e-4 ms → first post-declaration step is
        # pathological (§5 absolute rule) → fail closed (§2.11) → reject.
        cfg = _verification_config().model_copy(update={"max_unit_ms": 1e-4})
        session = RuntimeVerificationSession(
            str(sidecar),
            policy=RuntimeControlPolicy(operator_budget_seconds=3600.0, verification=cfg),
            attempt_id="exp_path",
        )
        summary = _run(tiny_setup, session, "exp_path")

        assert summary is None
        models_dir = tiny_setup["sandbox_dirs"]["models"]
        assert not os.path.exists(os.path.join(models_dir, "model_wavenet_exp_path_agent.pth"))
        assert not os.path.exists(os.path.join(models_dir, "_OK_exp_path"))

        obs = json.load(open(sidecar))
        assert obs["final_status"] == "rejected"
        assert obs["admission"]["decision"] == "rejected"
        assert obs["admission"]["stage"] == "post_training_verification"
        assert "2.11" in obs["admission"]["reason"]
        training = obs["components"]["training"]
        assert training["prediction"] is None
        assert training["measurement"] is not None  # evidence retained

    def test_same_failure_without_budget_records_and_completes(self, tiny_setup, tmp_path):
        sidecar = tmp_path / "rv.json"
        cfg = _verification_config().model_copy(update={"max_unit_ms": 1e-4})
        session = RuntimeVerificationSession(
            str(sidecar),
            policy=RuntimeControlPolicy(verification=cfg),  # record-only
            attempt_id="exp_rec",
        )
        summary = _run(tiny_setup, session, "exp_rec")

        assert summary is not None  # training completed unchanged
        assert os.path.exists(os.path.join(tiny_setup["sandbox_dirs"]["models"], "_OK_exp_rec"))
        obs = json.load(open(sidecar))
        assert obs["final_status"] == "completed"
        assert obs["admission"]["decision"] == "admitted"
        assert "record-only" in obs["admission"]["reason"]
        assert obs["components"]["training"]["prediction"] is None
        assert obs["components"]["training"]["measurement"] is not None
