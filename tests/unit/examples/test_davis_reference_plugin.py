"""The DAVIS reference predictor loads through the REAL plugin mechanism (D14-3 C6).

Pollution-free (fresh registries via the argument form). What only this
catches: the plugin drifting off the plugin contract or off the pack's
DECLARED `ModelIOContract` boundary
(`[B,3,8,128,224] f32 → [B,3,4,128,224] f32`), and the residual-over-
last-frame property that makes an untrained net a usable baseline.
"""

from __future__ import annotations

from pathlib import Path

import torch

import ml_models.plugin_loader as plugin_loader

REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGINS_DIR = REPO_ROOT / "examples" / "davis_future_prediction" / "plugins"


def _load_isolated(monkeypatch):
    monkeypatch.setenv("SIDERIUS_PLUGIN_DIRS", str(PLUGINS_DIR))
    models: dict = {}
    configs: dict = {}
    loaded = plugin_loader.extend_registries(models, configs)
    return loaded, models, configs


def test_loads_through_the_real_loader(monkeypatch):
    loaded, models, configs = _load_isolated(monkeypatch)
    assert "davis_reference_predictor" in loaded
    assert "davis_reference_predictor" in models and "davis_reference_predictor" in configs
    assert plugin_loader.PLUGIN_OUTPUT_TYPE_REGISTRY["davis_reference_predictor"] == "regressor"


def test_forward_matches_the_declared_model_io_contract(monkeypatch):
    _, models, configs = _load_isolated(monkeypatch)
    model = models["davis_reference_predictor"](configs["davis_reference_predictor"]())
    out = model(torch.rand(2, 3, 8, 128, 224))
    assert out.shape == (2, 3, 4, 128, 224) and out.dtype == torch.float32


def test_output_is_the_last_context_frame_plus_a_residual(monkeypatch):
    """The baseline property: zero the head's weights and the prediction is
    EXACTLY the last context frame repeated — which is why an untrained net
    still yields a finite, meaningful MSE at gate budget."""
    _, models, configs = _load_isolated(monkeypatch)
    model = models["davis_reference_predictor"](configs["davis_reference_predictor"]())
    head = model.body[-1]
    with torch.no_grad():
        head.weight.zero_()
        head.bias.zero_()
    x = torch.rand(1, 3, 8, 16, 24)
    out = model(x)
    expected = x[:, :, -1:, :, :].expand(-1, -1, 4, -1, -1)
    assert torch.allclose(out, expected, atol=1e-6)
