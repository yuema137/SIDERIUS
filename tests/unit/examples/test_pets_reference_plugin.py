"""The Pets reference plugin loads through the REAL plugin mechanism (D14-2 C4).

Pollution-free: ``extend_registries`` takes the registries as ARGUMENTS, so
these tests scan the pack's ``plugins/`` dir (via the same
``SIDERIUS_PLUGIN_DIRS`` mechanism the gate runner uses) into FRESH dicts —
the global ``MODEL_REGISTRY`` is never touched. What only this catches: the
plugin source drifting off the plugin contract, or off the pack's DECLARED
``ModelIOContract`` boundary (`[B,3,144,144] f32 → [B,37] f32`).
"""

from __future__ import annotations

from pathlib import Path

import torch

import ml_models.plugin_loader as plugin_loader

REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGINS_DIR = REPO_ROOT / "examples" / "oxford_iiit_pet" / "plugins"


def _load_isolated(monkeypatch):
    monkeypatch.setenv("SIDERIUS_PLUGIN_DIRS", str(PLUGINS_DIR))
    models: dict = {}
    configs: dict = {}
    loaded = plugin_loader.extend_registries(models, configs)
    return loaded, models, configs


def test_loads_through_the_real_loader_with_the_contract_attrs(monkeypatch):
    loaded, models, configs = _load_isolated(monkeypatch)
    assert "pets_reference_cnn" in loaded
    assert "pets_reference_cnn" in models and "pets_reference_cnn" in configs


def test_forward_matches_the_declared_model_io_contract(monkeypatch):
    _, models, configs = _load_isolated(monkeypatch)
    cfg = configs["pets_reference_cnn"]()
    model = models["pets_reference_cnn"](cfg)
    out = model(torch.rand(2, 3, 144, 144))
    assert out.shape == (2, 37) and out.dtype == torch.float32


def test_deterministic_construction_under_a_pinned_seed(monkeypatch):
    _, models, configs = _load_isolated(monkeypatch)
    cfg = configs["pets_reference_cnn"]()
    torch.manual_seed(11)
    a = models["pets_reference_cnn"](cfg)
    torch.manual_seed(11)
    b = models["pets_reference_cnn"](cfg)
    for pa, pb in zip(a.parameters(), b.parameters(), strict=True):
        assert torch.equal(pa, pb)
