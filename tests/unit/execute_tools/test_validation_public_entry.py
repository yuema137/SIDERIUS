"""A private coordinator can retain native dtype semantics without plugin code."""

from types import SimpleNamespace

import pytest
import torch
from torch.utils.data import TensorDataset

from agent.schemas.model_io_contract import ModelIOContract
from execute_tools.train_engine_sandbox import _validation_pass, observe_validation
from ml_models.loss_models_sandbox import get_target_torch_dtype
from ml_models.loss_plugin_loader import LOSS_TARGET_DTYPE_REGISTRY
from ml_models.models_format_sandbox import LossConfig


def test_public_entry_is_the_existing_native_implementation():
    assert observe_validation is _validation_pass


@pytest.mark.parametrize("declared,expected", [("float", torch.float32), ("long", torch.int64)])
def test_transported_custom_metadata_needs_no_plugin_registration(declared, expected):
    name = "private_validation_unregistered_loss"
    assert name not in LOSS_TARGET_DTYPE_REGISTRY
    config = LossConfig(loss_type="custom", loss_name=name)
    assert get_target_torch_dtype(config, resolved_custom_dtype=declared) == expected
    assert name not in LOSS_TARGET_DTYPE_REGISTRY  # No global binding was installed.
    assert get_target_torch_dtype(config) == torch.int64  # Legacy omission unchanged.


def test_conflicting_or_builtin_dtype_override_is_refused(monkeypatch):
    name = "private_validation_declared_loss"
    monkeypatch.setitem(LOSS_TARGET_DTYPE_REGISTRY, name, "float")
    with pytest.raises(ValueError, match="conflicts"):
        get_target_torch_dtype(
            LossConfig(loss_type="custom", loss_name=name), resolved_custom_dtype="long"
        )
    with pytest.raises(ValueError, match="requires a custom"):
        get_target_torch_dtype(LossConfig(loss_type="ce"), resolved_custom_dtype="float")
    with pytest.raises(ValueError, match="requires a custom"):
        get_target_torch_dtype(
            LossConfig(loss_type="custom", loss_name=name), resolved_custom_dtype="float16"
        )


def test_public_native_pass_uses_transported_floating_target_declaration():
    class FloatingObjective(torch.nn.Module):
        def forward(self, output, target):
            assert target.dtype == torch.float32
            return (output - target).square().mean()

    contract = ModelIOContract.model_validate(
        {
            name: {
                "axes": [
                    {"dimension": {"symbolic": "B"}, "role": "batch"},
                    {"dimension": {"fixed": 2}},
                ],
                "dtype": {"admissible": ["float32"]},
            }
            for name in ("input", "output")
        }
    )
    value, rows, _ = observe_validation(
        model=torch.nn.Identity(),
        criterion=FloatingObjective(),
        model_cfg=SimpleNamespace(model_type="wavenet"),
        loss_cfg=LossConfig(loss_type="custom", loss_name="floating_unregistered"),
        model_io=contract,
        device=torch.device("cpu"),
        data_path=SimpleNamespace(
            validation_dataset=lambda *_: TensorDataset(torch.ones(5, 2), torch.full((5, 2), 0.5))
        ),
        task_eval_scope=object(),
        data_dir="synthetic",
        batch_size=2,
        resolved_custom_target_dtype="float",
    )
    assert rows == 5 and value == 0.25
