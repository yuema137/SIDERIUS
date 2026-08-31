"""Plugin-contract tests for the synthetic model-plugin fixture.

The template is the source string the StubLLMBridge's ``implementor.code``
label returns verbatim. Production code in ``ml_models/plugin_loader.py``
asserts three things on every plugin file it loads:

  - ``PLUGIN_MODEL_TYPE`` / ``PLUGIN_CONFIG_CLASS`` / ``PLUGIN_MODEL_CLASS``
    exist as module-level attributes.
  - ``PLUGIN_CONFIG_CLASS`` is a Pydantic ``BaseModel`` subclass that
    instantiates with default arguments.
  - ``PLUGIN_MODEL_CLASS`` forward pass satisfies the chain-wide tensor
    contract: ``[B, T] int → [B, 256, T] float``.

These tests pin those guarantees on the hardcoded template so any drift
fails fast in unit tests instead of mid-chain at training time.
"""

from __future__ import annotations

import importlib.util
import os
import sys

import torch
from pydantic import BaseModel

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_TEMPLATE_PATH = os.path.join(
    _REPO_ROOT, "tests", "fixtures", "generated_capabilities", "stub_model_template.py"
)


def _import_template():
    """Mirror ``ml_models/plugin_loader.py::_load_plugin`` for one file.

    The plugin loader's directory scan skips files starting with ``_``,
    so we can't go through the public ``extend_registries`` path —
    we call its inner ``importlib`` machinery directly.
    """
    spec = importlib.util.spec_from_file_location(
        "siderius_plugin__stub_plugin_template",
        _TEMPLATE_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_template_file_exists():
    """The B1 commit creates this file. Missing file → B1 not landed."""
    assert os.path.isfile(_TEMPLATE_PATH), f"stub template missing at {_TEMPLATE_PATH!r}"


def test_template_exposes_three_plugin_symbols():
    """Loader's contract gate: all three PLUGIN_* attrs must be present."""
    mod = _import_template()
    for attr in ("PLUGIN_MODEL_TYPE", "PLUGIN_CONFIG_CLASS", "PLUGIN_MODEL_CLASS"):
        assert hasattr(mod, attr), f"missing required plugin symbol: {attr!r}"


def test_plugin_model_type_is_stub_arch():
    """Pin the slug. ``_synth_stub_model_name`` builds on this prefix."""
    mod = _import_template()
    assert mod.PLUGIN_MODEL_TYPE == "stub_arch"


def test_config_class_is_pydantic_basemodel_and_instantiates_with_defaults():
    """The loader trusts that calling ``PLUGIN_CONFIG_CLASS()`` succeeds."""
    mod = _import_template()
    assert issubclass(mod.PLUGIN_CONFIG_CLASS, BaseModel)
    cfg = mod.PLUGIN_CONFIG_CLASS()
    assert cfg.model_type == "stub_arch"


def test_forward_shape_contract():
    """Pin ``[B, T] int → [B, 256, T] float`` on the model.

    This is the assertion the StubSandbox's ``execute_training`` will rely
    on at chain time — if the template's forward shape ever drifts, the
    smoke run crashes before evolution_log.jsonl gets a row.
    """
    mod = _import_template()
    cfg = mod.PLUGIN_CONFIG_CLASS()
    model = mod.PLUGIN_MODEL_CLASS(cfg).eval()

    B, T = 1, 8
    x = torch.zeros((B, T), dtype=torch.long)
    with torch.no_grad():
        y = model(x)
    assert y.shape == (B, 256, T), f"got {tuple(y.shape)}"
    assert y.dtype.is_floating_point, f"got non-float dtype {y.dtype}"
