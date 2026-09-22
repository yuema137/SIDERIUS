"""Long generated-model probes must not consume the chain's host memory."""

from __future__ import annotations

from nodes.ml_code_validator_agent import _check_instantiation_and_gradient

_PLUGIN = '''
import torch
from torch import nn
from pydantic import BaseModel

PLUGIN_MODEL_TYPE = "synthetic_temporal"
PLUGIN_OUTPUT_TYPE = "regressor"

class Config(BaseModel):
    segmentation_size: int = 8192

PLUGIN_CONFIG_CLASS = Config

class Model(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.weight = nn.Parameter(torch.ones(()))
        {allocation}

    def forward(self, x):
        return x.float() * self.weight

PLUGIN_MODEL_CLASS = Model
'''


def test_long_temporal_probe_passes_in_isolated_worker(tmp_path) -> None:
    path = tmp_path / "valid_model.py"
    path.write_text(_PLUGIN.format(allocation=""), encoding="utf-8")

    assert _check_instantiation_and_gradient(str(path)) == (
        True, True, True, None, 1, 1
    )


def test_excessive_allocation_rejects_candidate_without_killing_parent(tmp_path) -> None:
    path = tmp_path / "huge_model.py"
    path.write_text(
        _PLUGIN.format(allocation="torch.empty((100_000_000_000,), dtype=torch.float32)"),
        encoding="utf-8",
    )

    instantiated, gradient, output_type, error, total, trainable = (
        _check_instantiation_and_gradient(str(path))
    )
    assert (instantiated, gradient, output_type, total, trainable) == (
        False, False, False, None, None
    )
    assert error is not None
    assert "alloc" in error.lower() or "memory" in error.lower()
