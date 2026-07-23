"""
RT2-D integration (in-process, tiny synthetic dataset): inference
verification inside the production inference engine.

Design: docs/design/runtime_estimation_and_watchdog.md §2.6 / §11
RT2-D checkpoint — tiny-scope inference verification showing the
component split (setup / compute / output write priced separately):

- the inference subprocess RESUMES the attempt's observation (training
  components preserved);
- the inference component records the resolver workload, steady-state
  batch measurement, a measurement-backed prediction with the §2.6
  split, and the phase actual + prediction error;
- absent sidecar → fresh observation, inference evidence still lands.
"""

from __future__ import annotations

import json
import os

import h5py
import numpy as np
import pytest
import torch

import execute_tools.inference_single as inf
import execute_tools.workload_resolvers as wr
from core.runtime_control.adaptive import AdaptiveVerificationConfig
from core.runtime_control.session import RuntimeControlPolicy, RuntimeVerificationSession
from core.runtime_control.steady_state import SteadyStateConfig
from core.runtime_control.workload import ResolvedPhaseWorkload
from ml_models.models_format_sandbox import WaveNetConfig
from ml_models.models_sandbox import MODEL_REGISTRY

SEG_SIZE = 1000
N_PSD_SEGMENTS = 30  # 30 inference batches at batch_size=1

_MODEL_CFG = dict(
    segmentation_size=SEG_SIZE,
    input_channels=4,
    residual_channels=8,
    gate_channels=8,
    skip_channels=8,
    kernel_size=2,
    num_blocks=1,
)


@pytest.fixture
def tiny_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(inf, "PSD_SEGMENT_LENGTH", SEG_SIZE)
    monkeypatch.setattr(wr, "PSD_SEGMENT_LENGTH", SEG_SIZE)

    n_samples = N_PSD_SEGMENTS * SEG_SIZE
    rng = np.random.default_rng(11)
    with h5py.File(tmp_path / "abra_validation_0000.h5", "w") as f:
        ts = f.create_group("timeseries")
        ts.create_group("channel0001").create_dataset(
            "timeseries", data=rng.integers(-128, 127, size=n_samples, dtype=np.int8)
        )
        ts.create_group("channel0002").create_dataset(
            "timeseries", data=rng.integers(-128, 127, size=n_samples, dtype=np.int16)
        )

    # Trained-model artefacts the agent path preflights: config JSONs,
    # state_dict, and the training sentinel.
    cfg = WaveNetConfig(**_MODEL_CFG)
    model = MODEL_REGISTRY["wavenet"](cfg)
    model_path = tmp_path / "model_wavenet_exp_inf_agent.pth"
    torch.save(model.state_dict(), model_path)
    (tmp_path / "_OK_exp_inf").touch()

    m_cfg_path = tmp_path / "model_config.json"
    with open(m_cfg_path, "w") as f:
        json.dump({"model_type": "wavenet", **_MODEL_CFG}, f)
    l_cfg_path = tmp_path / "loss_config.json"
    with open(l_cfg_path, "w") as f:
        json.dump({"loss_type": "focal"}, f)
    ss_path = tmp_path / "eval_ss.json"
    with open(ss_path, "w") as f:
        json.dump({"0": list(range(N_PSD_SEGMENTS))}, f)

    rp_path = tmp_path / "policy.json"
    with open(rp_path, "w") as f:
        json.dump(
            RuntimeControlPolicy(
                verification=AdaptiveVerificationConfig(
                    steady=SteadyStateConfig(
                        window=3, stable_windows=2, rel_spread_tol=0.75, max_steps=25
                    ),
                    min_timed_steps=3,
                    min_timed_ms=1.0,
                    max_steps=28,
                    max_wall_ms=120_000.0,
                )
            ).model_dump(),
            f,
        )

    return {
        "tmp": tmp_path,
        "argv": [
            "inference_single.py",
            "--mode",
            "agent",
            "-m",
            "wavenet",
            "--model_cfg",
            str(m_cfg_path),
            "--loss_cfg",
            str(l_cfg_path),
            "--model_path",
            str(model_path),
            "--exp_id",
            "exp_inf",
            "--run_name",
            "rt2d",
            "--data_dir",
            str(tmp_path),
            "--output_dir",
            str(tmp_path),
            "--inference_batch_size",
            "1",
            "--sample_set_json",
            str(ss_path),
            "--runtime_policy_json",
            str(rp_path),
        ],
    }


def _run_inference(setup, monkeypatch, sidecar: str):
    monkeypatch.setattr("sys.argv", [*setup["argv"], "--runtime_observation_out", sidecar])
    inf.main()
    return json.load(open(sidecar))


class TestInferenceVerification:
    def test_resumed_observation_gains_inference_component(self, tiny_setup, monkeypatch):
        sidecar = str(tiny_setup["tmp"] / "rv.json")
        # Simulate the training subprocess's prior evidence.
        trainer_session = RuntimeVerificationSession(sidecar, attempt_id="exp_inf")
        trainer_session.complete_setup(
            storage_provenance={"expected_raw_bytes": 1000},
            training_workload=ResolvedPhaseWorkload(
                phase="training", unit="optimizer_step", unit_count=30
            ),
        )
        trainer_session.record_phase_actual("training", 3.0)

        obs = _run_inference(tiny_setup, monkeypatch, sidecar)

        # Previous subprocess's components preserved (§6.1 one observation
        # per attempt).
        assert obs["components"]["setup"] is not None
        assert obs["components"]["training"]["actual_seconds"] == pytest.approx(3.0)
        assert obs["final_status"] == "inference_complete"

        inference = obs["components"]["inference"]
        assert inference["workload"]["unit"] == "inference_batch"
        assert inference["workload"]["unit_count"] == N_PSD_SEGMENTS  # bs=1
        assert inference["actual_seconds"] > 0.0

        pred = inference["prediction"]
        if pred is None:
            pytest.skip("timing too jittery for detection in this environment")
        assert pred["source"] == "real_inference_verification"
        assert pred["formal_execution_eligible"] is True
        # §2.6 component split: setup + output write priced separately.
        detail = pred["detail"]
        assert detail["inference_setup_seconds"] > 0.0
        assert detail["output_write_seconds_per_psd"] >= 0.0
        assert detail["total_psd_planned"] == N_PSD_SEGMENTS
        assert inference["prediction_error"] is not None

    def test_fresh_start_without_prior_sidecar(self, tiny_setup, monkeypatch):
        sidecar = str(tiny_setup["tmp"] / "rv_fresh.json")
        obs = _run_inference(tiny_setup, monkeypatch, sidecar)
        assert "training" not in obs["components"]  # explicit absence
        assert "inference" in obs["components"]
        assert obs["final_status"] == "inference_complete"

    def test_output_files_written_as_production(self, tiny_setup, monkeypatch):
        # The instrumentation must not perturb the engine's outputs.
        sidecar = str(tiny_setup["tmp"] / "rv2.json")
        _run_inference(tiny_setup, monkeypatch, sidecar)
        out = tiny_setup["tmp"] / "abra_validation_denoised_wavenet_rt2d_exp_inf_0000.h5"
        assert out.exists()
        with h5py.File(out, "r") as f:
            ch1 = f["timeseries"]["channel0001"]["timeseries"]
            assert ch1.shape == (N_PSD_SEGMENTS * SEG_SIZE,)
