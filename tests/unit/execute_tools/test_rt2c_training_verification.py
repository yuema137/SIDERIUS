"""
RT2-C integration (in-process, tiny synthetic dataset): adaptive
training verification as the first production steps of the streaming
trainer's production epoch loops.

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
import sys

import pytest
import torch
from torch.utils.data import Dataset

import execute_tools.train_engine_sandbox as tes
from core.runtime_control.adaptive import AdaptiveVerificationConfig
from core.runtime_control.session import RuntimeControlPolicy, RuntimeVerificationSession
from core.runtime_control.steady_state import SteadyStateConfig
from execute_tools.task_data_path import (
    DeliverableWriteRequest,
    EpochSamplingParams,
    EvalMaterializationParams,
    EvaluationReadRequest,
    bind_task_data_path,
)
from ml_models.models_format_sandbox import LossConfig, TrainConfig, WaveNetConfig
from tests.helpers.two_family_profile import make_two_family_profile

SEG_SIZE = 1000
N_PSD_SEGMENTS = 30  # 30 steps at batch_size=1


class _VerificationDataset(Dataset):
    """Small deterministic classification stream for timing verification."""

    def __len__(self) -> int:
        return N_PSD_SEGMENTS

    def __getitem__(self, index: int):
        values = (torch.arange(SEG_SIZE, dtype=torch.int64) + index) % 256
        return values, values.clone()


class _VerificationDataPath:
    """Expose the timing fixture through the production task-data seam."""

    task_data_path_id = "rt2c_indexed_fixture"

    def training_dataset(self, scope: object, params: EpochSamplingParams):
        assert isinstance(scope, dict)
        return _VerificationDataset()

    def validation_dataset(self, scope: object, params: EvalMaterializationParams):
        raise AssertionError("RT2-C does not request validation data")

    def write_deliverable(self, outputs, request: DeliverableWriteRequest) -> None:
        raise AssertionError("RT2-C does not write deliverables")

    def read_evaluation_payload(self, request: EvaluationReadRequest) -> object:
        raise AssertionError("RT2-C does not read evaluation payloads")


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
def tiny_setup(tmp_path):
    """Streaming-mode setup with enough segments for live verification."""
    profile = make_two_family_profile(
        num_files=1,
        psd_segment_length=SEG_SIZE,
        segments_per_file=N_PSD_SEGMENTS,
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

    with bind_task_data_path(_VerificationDataPath()):
        yield {
            "data_dir": str(tmp_path),
            "profile": profile,
            "sample_set": {"0": list(range(N_PSD_SEGMENTS))},
            "model_cfg": model_cfg,
            "train_cfg": train_cfg,
            "loss_cfg": LossConfig(),
            "sandbox_dirs": sandbox_dirs,
        }


def _run(setup, runtime_session, exp_id: str, **kwargs):
    return tes.run_experiment_streaming(
        setup["model_cfg"],
        setup["train_cfg"],
        setup["loss_cfg"],
        sample_set=setup["sample_set"],
        data_dir=setup["data_dir"],
        sandbox_dirs=setup["sandbox_dirs"],
        exp_id=exp_id,
        runtime_session=runtime_session,
        task_scope=setup["sample_set"],
        profile=setup["profile"],
        **kwargs,
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


class _ObservedDataPath(_VerificationDataPath):
    """Record real loader visits without replacing optimizer or verification work."""

    def __init__(self):
        self.visits = []
        self.seeds = []

    def _dataset(self, phase):
        visits = []
        self.visits.append((phase, visits))

        class Rows(_VerificationDataset):
            def __getitem__(self, index):
                visits.append(index)
                return super().__getitem__(index)

        return Rows()

    def training_dataset(self, scope, params):
        self.seeds.append(params.epoch_seed)
        return self._dataset("training")

    def validation_dataset(self, scope, params):
        return self._dataset("validation")


def _cross_epoch_config():
    return _verification_config().model_copy(update={"min_timed_steps": 8, "max_steps": 60})


@pytest.mark.parametrize("with_validation", [False, True])
def test_short_epochs_preserve_verification_and_exact_training(
    tiny_setup, tmp_path, monkeypatch, with_validation
):
    """Actual CPU updates cross epoch boundaries; measurement cannot change training."""
    monkeypatch.setattr(sys.modules[__name__], "N_PSD_SEGMENTS", 4)
    tiny_setup["train_cfg"] = tiny_setup["train_cfg"].model_copy(update={"epochs": 6})
    sidecar = tmp_path / "cross_epoch.json"
    session = RuntimeVerificationSession(
        str(sidecar),
        policy=RuntimeControlPolicy(
            operator_budget_seconds=3600, verification=_cross_epoch_config()
        ),
    )
    options = (
        {"task_eval_scope": object(), "validation_requested_rows": 4} if with_validation else {}
    )
    visits = []
    summaries = []
    states = []
    for label, active_session in (("control", None), ("measured", session)):
        dirs = {"models": str(tmp_path / label), "results": str(tmp_path / (label + "_records"))}
        os.makedirs(dirs["models"])
        setup = {**tiny_setup, "sandbox_dirs": dirs}
        data_path = _ObservedDataPath()
        torch.manual_seed(1234)
        with bind_task_data_path(data_path):
            result = _run(setup, active_session, "cross_epoch", **options)
        assert result is not None
        summaries.append(result)
        visits.append((data_path.visits, data_path.seeds))
        checkpoint = next((tmp_path / label).glob("*.pth"))
        states.append(torch.load(checkpoint, weights_only=True))
    assert visits[0] == visits[1]
    expected_phases = ["training", "validation"] * 6 if with_validation else ["training"] * 6
    assert [phase for phase, _ in visits[1][0]] == expected_phases
    assert all(sorted(rows) == [0, 1, 2, 3] for _, rows in visits[1][0])
    assert summaries[0]["loss_history"] == summaries[1]["loss_history"]
    assert len(summaries[1]["loss_history"]) == 6
    assert states[0].keys() == states[1].keys()
    assert all(torch.equal(states[0][key], states[1][key]) for key in states[0])
    record = json.loads(sidecar.read_text())
    training = record["components"]["training"]
    assert record["final_status"] == "completed"
    assert training["prediction"]["formal_execution_eligible"] is True
    assert 4 < len(training["measurement"]["raw_timings_ms"]) <= 24
    assert training["workload"]["unit_count"] == 24
    assert training["measurement"]["detail"]["verification_excluded_inactive_seconds"] > 0
    if with_validation:
        validation = record["components"]["validation"]
        assert validation["prediction"]["formal_execution_eligible"] is True
        assert len(validation["measurement"]["raw_timings_ms"]) > 4


@pytest.mark.parametrize("budget", [None, 3600])
def test_true_end_retains_insufficient_evidence(tiny_setup, tmp_path, monkeypatch, budget):
    monkeypatch.setattr(sys.modules[__name__], "N_PSD_SEGMENTS", 2)
    sidecar = tmp_path / "short.json"
    session = RuntimeVerificationSession(
        str(sidecar),
        policy=RuntimeControlPolicy(
            operator_budget_seconds=budget, verification=_cross_epoch_config()
        ),
    )
    summary = _run(tiny_setup, session, "short")
    record = json.loads(sidecar.read_text())
    training = record["components"]["training"]
    assert len(training["measurement"]["raw_timings_ms"]) == 2
    assert training["prediction"] is None
    assert (summary is None) == (budget is not None)
    assert record["final_status"] == ("completed" if budget is None else "rejected")


def test_cooperative_stop_finalizes_pending_training(tiny_setup, tmp_path, monkeypatch):
    import time

    from core.runtime_control.training_budget import TrainingBudgetEnvelope

    monkeypatch.setattr(sys.modules[__name__], "N_PSD_SEGMENTS", 2)
    tiny_setup["train_cfg"] = tiny_setup["train_cfg"].model_copy(update={"epochs": 10})
    sidecar = tmp_path / "cooperative.json"
    session = RuntimeVerificationSession(
        str(sidecar),
        policy=RuntimeControlPolicy(
            verification=_cross_epoch_config(),
            training_budget=TrainingBudgetEnvelope(
                budget_seconds=300,
                reserve_fraction=0.2,
                max_epochs=10,
                max_optimizer_steps=4,
                started_monotonic_seconds=time.monotonic(),
            ),
        ),
    )
    summary = _run(tiny_setup, session, "cooperative")
    assert summary is not None
    assert summary["training_budget"]["optimizer_steps"] == 4
    assert summary["training_budget"]["completed_epochs"] == 2
    assert summary["training_budget"]["stop"]["reason"] == "step_limit"
    record = json.loads(sidecar.read_text())
    training = record["components"]["training"]
    assert len(training["measurement"]["raw_timings_ms"]) == 4
    assert training["prediction"] is None
    assert training["workload"]["unit_count"] == 4


@pytest.mark.parametrize(
    "stall_location,stall_seconds", [("dataset", 0.0), ("dataset", 61.0), ("cleanup", 61.0)]
)
def test_training_clock_excludes_validation_and_counts_reconstruction(
    tiny_setup, tmp_path, monkeypatch, stall_location, stall_seconds
):
    """Controlled clock attribution at the real trainer's task-data boundary."""
    from types import SimpleNamespace

    import core.runtime_control.adaptive as adaptive

    clock = [100.0]
    monkeypatch.setattr(adaptive, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(tes, "time", SimpleNamespace(perf_counter=lambda: clock[0]))
    monkeypatch.setattr(sys.modules[__name__], "N_PSD_SEGMENTS", 4)
    tiny_setup["train_cfg"] = tiny_setup["train_cfg"].model_copy(update={"epochs": 3})

    class TimedRows(_VerificationDataset):
        def __getitem__(self, index):
            clock[0] += 0.1
            return super().__getitem__(index)

    class TimedPath(_VerificationDataPath):
        epochs = 0

        def training_dataset(self, scope, params):
            if self.epochs and stall_location == "dataset":
                clock[0] += stall_seconds
            self.epochs += 1
            return TimedRows()

        def validation_dataset(self, scope, params):
            return TimedRows()

    original_validation = tes._validation_pass

    def delayed_validation(**kwargs):
        clock[0] += 300
        return original_validation(**kwargs)

    monkeypatch.setattr(tes, "_validation_pass", delayed_validation)
    if stall_location == "cleanup":

        def delayed_cleanup():
            clock[0] += stall_seconds

        monkeypatch.setattr(tes, "gc", SimpleNamespace(collect=delayed_cleanup))
    sidecar = tmp_path / "clock.json"
    session = RuntimeVerificationSession(
        str(sidecar),
        policy=RuntimeControlPolicy(
            verification=_cross_epoch_config().model_copy(update={"max_wall_ms": 1500})
        ),
    )
    with bind_task_data_path(TimedPath()):
        result = _run(
            tiny_setup, session, "clock", task_eval_scope=object(), validation_requested_rows=4
        )
    assert result is not None  # Record-only keeps evidence even on failure.
    training = json.loads(sidecar.read_text())["components"]["training"]
    detail = training["measurement"]["detail"]
    if stall_seconds:
        assert training["prediction"] is None
        assert detail["verification_active_wall_ms"] > 60_000
    else:
        assert training["prediction"] is not None
        assert len(training["measurement"]["raw_timings_ms"]) == 8
        assert detail["verification_excluded_inactive_seconds"] == pytest.approx(300.4)
        assert detail["verification_active_wall_ms"] <= 1500
    assert len(result["loss_history"]) == 3


def test_pathological_verdict_survives_epoch_boundary(tiny_setup, tmp_path, monkeypatch):
    monkeypatch.setattr(sys.modules[__name__], "N_PSD_SEGMENTS", 2)
    tiny_setup["train_cfg"] = tiny_setup["train_cfg"].model_copy(update={"epochs": 6})
    sidecar = tmp_path / "pathological_cross_epoch.json"
    session = RuntimeVerificationSession(
        str(sidecar),
        policy=RuntimeControlPolicy(
            operator_budget_seconds=3600,
            verification=_cross_epoch_config().model_copy(update={"max_unit_ms": 1e-4}),
        ),
    )
    assert _run(tiny_setup, session, "pathological_cross_epoch") is None
    record = json.loads(sidecar.read_text())
    training = record["components"]["training"]
    assert record["admission"]["reason_code"] == "verification_failed"
    assert training["prediction"] is None
    assert training["measurement"]["detail"]["state"] == "failed_pathological_unit"
    assert len(training["measurement"]["raw_timings_ms"]) > 2
    assert not list((tmp_path / "cached_models").glob("*.pth"))
