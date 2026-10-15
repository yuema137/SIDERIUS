"""Unsupported custom knobs must not disappear before a successful training record."""

from unittest.mock import Mock

import pytest

from core.sandbox_executor import TidmadSandbox
from execute_tools.data_paths import bind_physical_data_root
from ml_models.models_format_sandbox import LossConfig, get_config_class


@pytest.mark.parametrize("model_type", ["fcnet", "custom_boundary_model"])
@pytest.mark.parametrize("extra", [{"scale": 9}, {"loss_parameters": {"scale": 9}}])
def test_unknown_custom_knobs_refuse_before_training(
    tmp_path, monkeypatch, synthetic_run_authorities, model_type, extra
):
    """Both executor schema branches reject, without persisting misleading child inputs."""
    import core.sandbox_executor as executor

    if model_type != "fcnet":
        monkeypatch.setitem(executor.PLUGIN_CONFIG_REGISTRY, model_type, get_config_class("fcnet"))
    launched = Mock(side_effect=AssertionError("invalid loss must not launch"))
    monkeypatch.setattr(executor, "_run_observed_subprocess", launched)
    raw_loss = {"loss_type": "custom", "loss_name": "fresh_loss", **extra}
    with bind_physical_data_root(str(tmp_path), purpose="custom loss parameter regression"):
        sandbox = TidmadSandbox(run_name="loss_boundary", workspace=str(tmp_path))
        result = sandbox.execute_training(
            "attempt",
            "loss_boundary",
            model_type,
            {"model_type": "fcnet", "segmentation_size": 10000, "latent_dims": [100, 10]},
            {"epochs": 1, "device": "cpu"},
            raw_loss,
        )
    assert result["status"] == "error"
    assert "Unsupported custom-loss fields" in result["message"]
    assert "per-attempt plugin parameter overrides are not supported" in result["message"]
    launched.assert_not_called()
    assert not list(tmp_path.rglob("loss_config_attempt.json"))
    # The request remains an honest refused input, not a silently normalized success.
    assert all(raw_loss[key] == value for key, value in extra.items())


def test_valid_custom_router_roundtrip_preserves_existing_builtin_field_normalization():
    custom = LossConfig(loss_type="custom", loss_name="fresh_loss", alpha=0.7, beta=2.0)
    assert LossConfig.model_validate(custom.model_dump()) == custom
    assert custom.alpha is None and custom.beta is None


@pytest.mark.parametrize("loss_type", ["focal", "focal_cw", "ce", "smooth_l1"])
def test_builtin_unknown_field_compatibility_is_not_changed(loss_type):
    assert LossConfig.model_validate({"loss_type": loss_type, "legacy_metadata": 3}) == LossConfig(
        loss_type=loss_type
    )
