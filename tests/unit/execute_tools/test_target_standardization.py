from pathlib import Path
from types import SimpleNamespace

import pytest
import torch
from torch import nn
from torch.utils.data import TensorDataset

from execute_tools.target_standardization import fit_training_target_standardization
from execute_tools.task_data_path import EpochSamplingParams, bind_task_data_path
from ml_models.target_standardization import (
    StandardizedTargetLoss,
    StandardizedTargetModel,
    load_trained_state,
)


class ScopedData:
    def training_dataset(self, scope, params):
        assert scope == "train"
        assert params.train_portion == 1.0
        return TensorDataset(
            torch.tensor([[0.0], [1.0], [2.0], [3.0]]),
            torch.tensor([[10.0], [12.0], [14.0], [16.0]]),
        )

    def validation_dataset(self, scope, params):
        assert scope == "val"
        return TensorDataset(torch.tensor([[0.0], [1.0]]), torch.tensor([[1000.0], [2000.0]]))


def test_scoped_fit_does_not_consume_validation_and_roundtrips_units(tmp_path):
    stats = fit_training_target_standardization(
        ScopedData(),
        "train",
        sampling=EpochSamplingParams(data_dir=str(tmp_path), train_portion=1),
        batch_size=3,
        check_allocation=lambda: None,
    )
    assert stats.mean == 13
    assert stats.scale == pytest.approx(5**0.5)
    assert stats.training_rows == stats.target_elements == 4
    model = StandardizedTargetModel(nn.Linear(1, 1), mean=stats.mean, scale=stats.scale)
    with torch.no_grad():
        model.base_model.weight.fill_(1)
        model.base_model.bias.zero_()
    x = torch.tensor([[0.0], [1.0]])
    path = tmp_path / "model.pt"
    torch.save(model.state_dict(), path)
    restored = load_trained_state(
        nn.Linear(1, 1), torch.load(path, weights_only=True), require_standardized=True
    )
    torch.testing.assert_close(restored(x), torch.tensor([[13.0], [13 + 5**0.5]]))
    criterion = StandardizedTargetLoss(nn.MSELoss(), mean=stats.mean, scale=stats.scale)
    loss = criterion(restored(x), torch.full((2, 1), 13.0))
    assert loss.item() == pytest.approx(0.5, abs=1e-6)
    loss.backward()
    assert restored.base_model.weight.grad.item() == pytest.approx(1.0, abs=1e-6)


def test_plain_and_transformed_checkpoints_cannot_be_confused():
    plain = nn.Linear(1, 1)
    state = plain.state_dict()
    assert load_trained_state(plain, state, require_standardized=False) is plain
    with pytest.raises(ValueError, match="disagrees"):
        load_trained_state(plain, state, require_standardized=True)
    wrapped = StandardizedTargetModel(nn.Linear(1, 1), mean=10, scale=2).state_dict()
    wrapped["target_scale"] = torch.tensor(0.0)
    with pytest.raises(ValueError, match="positive scale"):
        load_trained_state(nn.Linear(1, 1), wrapped)


def test_native_training_exports_fitted_transform_with_best_checkpoint(tmp_path, monkeypatch):
    import execute_tools.train_engine_sandbox as engine
    from ml_models.models_format_sandbox import LossConfig, TrainConfig
    from tests.helpers.two_family_profile import write_two_family_fixture

    (tmp_path / "profile").mkdir()
    fixture = write_two_family_fixture(tmp_path / "profile")
    monkeypatch.setitem(engine.MODEL_REGISTRY, "normalization_fixture", lambda cfg: nn.Linear(1, 1))
    monkeypatch.setattr(engine, "get_output_type", lambda model_type: "regressor")
    monkeypatch.setattr(engine, "resolve_input_dtype", lambda *args, **kwargs: torch.float32)
    dirs = {"models": str(tmp_path / "models"), "results": str(tmp_path / "results")}
    for path in dirs.values():
        Path(path).mkdir()
    with bind_task_data_path(ScopedData()):
        summary = engine.run_experiment_streaming(
            SimpleNamespace(model_type="normalization_fixture", segmentation_size=1),
            TrainConfig(
                epochs=3,
                batch_size=2,
                device="cpu",
                target_standardization="training_pool_global",
                checkpoint_selection="best_validation_loss",
            ),
            LossConfig(loss_type="smooth_l1"),
            sample_set={},
            data_dir=str(tmp_path),
            sandbox_dirs=dirs,
            exp_id="test",
            profile=fixture.profile,
            train_portion=1,
            task_scope="train",
            task_eval_scope="val",
            validation_requested_rows=2,
        )
    assert len(summary["loss_history"]) == 3
    assert summary["target_standardization"]["mean"] == 13
    assert summary["target_standardization"]["training_rows"] == 4
    from execute_tools.training_history import (
        TrainingResultsContractError,
        interpret_training_results,
        objective_config_fingerprint,
    )

    result = interpret_training_results(
        summary,
        expected_validation=True,
        expected_checkpoint_selection="best_validation_loss",
        expected_target_standardization="training_pool_global",
    )
    assert result.target_standardization is not None
    assert summary["training_history"][
        "objective_config_fingerprint"
    ] != objective_config_fingerprint(LossConfig(loss_type="smooth_l1"))
    missing = {key: value for key, value in summary.items() if key != "target_standardization"}
    with pytest.raises(TrainingResultsContractError, match="requested policy"):
        interpret_training_results(
            missing,
            expected_validation=True,
            expected_target_standardization="training_pool_global",
        )
    saved = next((tmp_path / "models").glob("*.pth"))
    restored = load_trained_state(nn.Linear(1, 1), torch.load(saved, weights_only=True))
    assert restored.target_mean.item() == 13
    assert torch.isfinite(restored(torch.zeros(1, 1))).all()
