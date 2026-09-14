"""03A2b regressions: legacy temporal consumers fail before side effects."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.skills.inference_skill import estimator as inference_estimator
from agent.skills.training_skill import estimator as training_estimator
from tests.helpers.two_family_profile import make_two_family_profile

ABSENT = "03a2b_generated_without_temporal_geometry"
PROFILE = make_two_family_profile(num_files=2, psd_segment_length=1600, segments_per_file=2)


def test_training_wall_time_refuses_before_counting_parameters():
    with pytest.raises(training_estimator.SegmentationDimensionUnavailableError):
        training_estimator.estimate_wall_time_seconds(
            ABSENT,
            {},
            {"batch_size": 1, "epochs": 1},
            {"0": [0]},
            loss_type="ce",
            ms_per_step=1.0,
            num_params=1,
            dataset_profile=PROFILE,
        )


def test_inference_wall_time_refuses_before_step_division():
    with pytest.raises(training_estimator.SegmentationDimensionUnavailableError):
        inference_estimator.estimate_wall_time_seconds(
            ABSENT,
            {},
            {"0": [0]},
            inference_ms_per_step=1.0,
            num_params=1,
            dataset_profile=PROFILE,
        )


def test_evaluate_time_legacy_forecast_refuses_before_measurement(monkeypatch):
    from agent.skills.evaluate_time_skill import wrapper

    monkeypatch.setattr(wrapper, "_count_params", lambda *_: pytest.fail("counted"))
    with pytest.raises(training_estimator.SegmentationDimensionUnavailableError):
        wrapper.run_skill(
            None,
            model_type=ABSENT,
            model_config={},
            train_config={"batch_size": 1, "epochs": 1},
            loss_config={"loss_type": "ce"},
            sample_set={"0": [0]},
            dataset_profile=PROFILE,
            time_budget_minutes=1,
        )


def test_production_probe_refuses_before_bounded_batch(monkeypatch, tmp_path):
    import torch.nn as nn
    from pydantic import BaseModel

    from core.runtime_control import probe_production
    from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY
    from ml_models.models_sandbox import MODEL_REGISTRY

    class Config(BaseModel):
        hidden: int = 2

    class Model(nn.Module):
        def __init__(self, cfg):
            super().__init__()
            self.layer = nn.Linear(cfg.hidden, 1)

    monkeypatch.setitem(PLUGIN_CONFIG_REGISTRY, ABSENT, Config)
    monkeypatch.setitem(MODEL_REGISTRY, ABSENT, Model)
    monkeypatch.setattr(
        training_estimator,
        "resolve_optional_segmentation_size",
        lambda *_: None,
    )
    with pytest.raises(training_estimator.SegmentationDimensionUnavailableError):
        probe_production.production_probe_executors(
            model_type=ABSENT,
            model_config={},
            train_config={"batch_size": 1},
            loss_config={"loss_type": "ce"},
            data_dir=str(tmp_path),
            device="cpu",
        ).setup()


def test_worker_legacy_temporal_branch_refuses_but_task_probe_branch_is_separate(monkeypatch, tmp_path):
    from core.runtime_control.gpu_measurement_worker_main import build_production_components
    from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY, WaveNetConfig
    from ml_models.models_sandbox import MODEL_REGISTRY, SimpleWaveNet

    # The worker's typed task-probe path is covered by its existing integration
    # double; this assertion pins the legacy branch's refusal boundary.
    MODEL_REGISTRY.setdefault("wavenet", SimpleWaveNet)
    PLUGIN_CONFIG_REGISTRY.setdefault("wavenet", WaveNetConfig)
    monkeypatch.setattr(
        training_estimator,
        "require_declared_segmentation_size",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            training_estimator.SegmentationDimensionUnavailableError("segmentation_size absent")
        ),
    )
    spec = SimpleNamespace(
        task_probe_data=None,
        request=SimpleNamespace(model_type="wavenet"),
        model_config_payload={},
        train_config={"batch_size": 1},
        loss_config={"loss_type": "ce"},
        phase="training",
        inference_batch_size=None,
        device="cpu",
        data_dir=str(tmp_path),
    )
    with pytest.raises(training_estimator.SegmentationDimensionUnavailableError, match="segmentation_size"):
        build_production_components(spec)()


def test_tuner_legacy_sample_set_does_not_admit_absent_geometry(monkeypatch):
    import nodes.ml_hyperparameter_tune_agent as tuner

    monkeypatch.setattr(training_estimator, "resolve_optional_segmentation_size", lambda *_: None)
    assert tuner._resolve_guardrail_steps(
        {"0": [0]},
        {},
        {"batch_size": 1, "epochs": 1},
        1.0,
        PROFILE,
        model_type=ABSENT,
    ) is None
