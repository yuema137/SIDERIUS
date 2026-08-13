"""
RT2-B integration (in-process, tiny synthetic dataset): the streaming
trainer's runtime-verification preamble.

Design: docs/design/runtime_estimation_and_watchdog.md §2.1 — the RT2-B
checkpoint. Runs ``run_experiment_streaming`` directly with a tiny
1-segment synthetic HDF5 file and a minimal wavenet on CPU (seconds,
no GPU), pinning:

- setup measured exactly once, observation staged BEFORE verification;
- NO duplicated dataset construction (instrumented constructor count);
- admitted execution continues directly into training on the same
  objects (model saved, sentinel written, actuals recorded);
- rejection exits cleanly: no model, no sentinel, structured sidecar;
- ``runtime_session=None`` → behavior identical to pre-RT2-B code.
"""

from __future__ import annotations

import json
import os

import pytest

import execute_tools.train_engine_sandbox as tes
from core.runtime_control.session import RuntimeControlPolicy, RuntimeVerificationSession
from execute_tools.dataset_config import TIDMAD_PROFILE, bind_dataset_profile
from ml_models.models_format_sandbox import LossConfig, TrainConfig, WaveNetConfig

SEG_SIZE = 1000  # minimum segmentation_size; 1 PSD segment == 1 ML segment below


@pytest.fixture
def tiny_setup(tmp_path, synthetic_h5, monkeypatch):
    """Tiny streaming-mode setup: 1 file, 1 PSD segment, 1 optimizer step."""
    data_dir, _fname = synthetic_h5(seg_size=SEG_SIZE)
    # The synthetic file holds exactly SEG_SIZE samples; shrink the PSD
    # segment so the streaming slicer sees one full PSD segment.
    # Geometry override is a DECLARATION. Was
    # ``monkeypatch.setattr(tes, "PSD_SEGMENT_LENGTH", SEG_SIZE)`` until
    # PR-02a C3 moved the loaders onto the resolved Dataset Profile, so the
    # module constant is no longer the authority. Assertions unchanged.

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
    loss_cfg = LossConfig()

    sandbox_dirs = {
        "models": str(tmp_path / "cached_models"),
        "results": str(tmp_path / "records"),
    }
    os.makedirs(sandbox_dirs["models"], exist_ok=True)
    os.makedirs(sandbox_dirs["results"], exist_ok=True)

    counter = {"dataset_constructions": 0}
    orig_init = tes.TIDMADEpochDataset.__init__

    def counting_init(self, *args, **kwargs):
        counter["dataset_constructions"] += 1
        orig_init(self, *args, **kwargs)

    monkeypatch.setattr(tes.TIDMADEpochDataset, "__init__", counting_init)

    _tiny = TIDMAD_PROFILE.model_copy(
        update={
            "dataset": TIDMAD_PROFILE.dataset.model_copy(update={"psd_segment_length": SEG_SIZE})
        }
    )
    with bind_dataset_profile(_tiny):
        yield {
            "data_dir": data_dir,
            "sample_set": {"0": [0]},
            "model_cfg": model_cfg,
            "train_cfg": train_cfg,
            "loss_cfg": loss_cfg,
            "sandbox_dirs": sandbox_dirs,
            "counter": counter,
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


class TestAdmittedPath:
    def test_admitted_run_trains_and_finalizes_observation(self, tiny_setup, tmp_path):
        sidecar = tmp_path / "rv.json"
        session = RuntimeVerificationSession(str(sidecar), attempt_id="exp_adm")

        # Event log exists BEFORE any verification/training happened.
        assert json.load(open(sidecar))["final_status"] == "setup_started"

        summary = _run(tiny_setup, session, "exp_adm")

        assert summary is not None and "final_loss" in summary
        # Exactly ONE dataset construction — the measured setup's dataset
        # IS the training dataset (no double materialization).
        assert tiny_setup["counter"]["dataset_constructions"] == 1
        # Model + sentinel written (training genuinely continued).
        assert os.path.exists(
            os.path.join(tiny_setup["sandbox_dirs"]["models"], "model_wavenet_exp_adm_agent.pth")
        )
        assert os.path.exists(os.path.join(tiny_setup["sandbox_dirs"]["models"], "_OK_exp_adm"))

        obs = json.load(open(sidecar))
        assert obs["final_status"] == "completed"
        assert obs["admission"]["decision"] == "admitted"
        setup_comp = obs["components"]["setup"]
        assert setup_comp["actual_seconds"] > 0.0
        training = obs["components"]["training"]
        assert training["workload"]["unit"] == "optimizer_step"
        assert training["workload"]["unit_count"] == 1  # 1 sample, bs=1, 1 epoch
        assert training["actual_seconds"] > 0.0

    def test_within_budget_admits(self, tiny_setup, tmp_path):
        session = RuntimeVerificationSession(
            str(tmp_path / "rv.json"),
            policy=RuntimeControlPolicy(operator_budget_seconds=3600.0),
        )
        summary = _run(tiny_setup, session, "exp_budget_ok")
        assert summary is not None
        assert session.observation.admission is not None
        assert session.observation.admission.decision == "admitted"


class TestRejectedPath:
    def test_rejection_exits_cleanly_without_model_or_sentinel(self, tiny_setup, tmp_path):
        sidecar = tmp_path / "rv.json"
        session = RuntimeVerificationSession(
            str(sidecar),
            policy=RuntimeControlPolicy(operator_budget_seconds=1e-9),
            attempt_id="exp_rej",
        )

        summary = _run(tiny_setup, session, "exp_rej")

        assert summary is None
        # Setup happened exactly once, then execution stopped.
        assert tiny_setup["counter"]["dataset_constructions"] == 1
        models_dir = tiny_setup["sandbox_dirs"]["models"]
        assert not os.path.exists(os.path.join(models_dir, "model_wavenet_exp_rej_agent.pth"))
        assert not os.path.exists(os.path.join(models_dir, "_OK_exp_rej"))

        obs = json.load(open(sidecar))
        assert obs["final_status"] == "rejected"
        assert obs["admission"]["decision"] == "rejected"
        assert obs["admission"]["stage"] == "post_setup_runtime_verification"
        assert obs["admission"]["setup_cost_seconds"] > 0.0
        # Setup evidence retained despite rejection (§6.2 event log).
        assert obs["components"]["setup"]["actual_seconds"] > 0.0
        assert obs["storage"]["expected_raw_bytes"] > 0


class TestNoSessionCompatibility:
    def test_none_session_is_pre_rt2b_behavior(self, tiny_setup):
        summary = _run(tiny_setup, None, "exp_legacy")
        assert summary is not None and "final_loss" in summary
        assert tiny_setup["counter"]["dataset_constructions"] == 1
        assert os.path.exists(os.path.join(tiny_setup["sandbox_dirs"]["models"], "_OK_exp_legacy"))


class TestMainArgvWiring:
    """The main() seam: argv → session construction → rejection handling.

    Uses a stubbed ``run_experiment_streaming`` (the function itself is
    covered above); pins that main() creates the session from
    ``--runtime_observation_out``/``--runtime_policy_json``, threads it
    through, and writes NO results JSON when the run is rejected.
    """

    def _main_with_argv(self, tmp_path, monkeypatch, extra_argv, streaming_result):
        cfg_dir = tmp_path / "cfg"
        cfg_dir.mkdir()
        m_cfg = {"model_type": "wavenet", "segmentation_size": 1000}
        t_cfg = {"epochs": 1, "batch_size": 1, "device": "cpu"}
        l_cfg = {}
        for name, payload in (("m", m_cfg), ("t", t_cfg), ("l", l_cfg)):
            with open(cfg_dir / f"{name}.json", "w") as f:
                json.dump(payload, f)
        ss_path = cfg_dir / "ss.json"
        with open(ss_path, "w") as f:
            json.dump({"0": [0]}, f)

        captured: dict = {}

        def fake_streaming(*args, **kwargs):
            captured.update(kwargs)
            return streaming_result

        monkeypatch.setattr(tes, "run_experiment_streaming", fake_streaming)
        monkeypatch.setattr(
            "sys.argv",
            [
                "train_engine_sandbox.py",
                "--model_cfg",
                str(cfg_dir / "m.json"),
                "--train_cfg",
                str(cfg_dir / "t.json"),
                "--loss_cfg",
                str(cfg_dir / "l.json"),
                "--data_dir",
                str(tmp_path),
                "--sandbox_dir",
                str(tmp_path / "sandbox"),
                "--exp_id",
                "exp_main",
                "--run_name",
                "rt2b_main",
                "--sample_set_json",
                str(ss_path),
                *extra_argv,
            ],
        )
        tes.main()
        return captured

    def test_session_created_and_threaded(self, tmp_path, monkeypatch):
        rv_path = tmp_path / "rv.json"
        rp_path = tmp_path / "rp.json"
        with open(rp_path, "w") as f:
            json.dump({"operator_budget_seconds": 90.0}, f)

        captured = self._main_with_argv(
            tmp_path,
            monkeypatch,
            ["--runtime_observation_out", str(rv_path), "--runtime_policy_json", str(rp_path)],
            streaming_result={"final_loss": 0.1, "loss_history": [0.1], "model_params": 1},
        )
        session = captured["runtime_session"]
        assert isinstance(session, RuntimeVerificationSession)
        assert session.policy.operator_budget_seconds == 90.0
        # Session sidecar staged before the trainer even ran.
        assert json.load(open(rv_path))["final_status"] == "setup_started"
        # Success path still writes the results JSON.
        res = (
            tmp_path
            / "sandbox"
            / "records"
            / "rt2b_main"
            / "experiment_results_wavenet_exp_main.json"
        )
        assert res.exists()

    def test_no_argv_means_no_session(self, tmp_path, monkeypatch):
        captured = self._main_with_argv(
            tmp_path,
            monkeypatch,
            [],
            streaming_result={"final_loss": 0.1, "loss_history": [0.1], "model_params": 1},
        )
        assert captured["runtime_session"] is None

    def test_rejection_skips_results_json(self, tmp_path, monkeypatch):
        rv_path = tmp_path / "rv.json"
        self._main_with_argv(
            tmp_path,
            monkeypatch,
            ["--runtime_observation_out", str(rv_path)],
            streaming_result=None,  # trainer signalled rejection
        )
        res = (
            tmp_path
            / "sandbox"
            / "records"
            / "rt2b_main"
            / "experiment_results_wavenet_exp_main.json"
        )
        assert not res.exists()
