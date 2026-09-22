"""Portable affine regression wrapper and its strict checkpoint loader.

No fitting or dataset access lives here. All fitted values travel inside the
state dict, so ordinary inference and certified historical inference agree.
"""

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import torch
from torch import nn

_VERSION = "_siderius_target_standardization_version"


class StandardizedTargetModel(nn.Module):
    """The base predicts standardized values; public outputs retain task units."""

    target_mean: torch.Tensor
    target_scale: torch.Tensor

    def __init__(self, model: nn.Module, *, mean: float, scale: float) -> None:
        super().__init__()
        if not torch.isfinite(torch.tensor([mean, scale], dtype=torch.float64)).all() or scale <= 0:
            raise ValueError("target standardization requires finite mean and positive scale")
        self.base_model = model
        self.register_buffer(_VERSION, torch.tensor(1, dtype=torch.int64))
        self.register_buffer("target_mean", torch.tensor(mean, dtype=torch.float64))
        self.register_buffer("target_scale", torch.tensor(scale, dtype=torch.float64))

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        output = self.base_model(inputs)
        return output * self.target_scale.to(output) + self.target_mean.to(output)


class StandardizedTargetLoss(nn.Module):
    """Apply the same fixed affine transform to predictions and targets."""

    target_mean: torch.Tensor
    target_scale: torch.Tensor

    def __init__(self, criterion: nn.Module, *, mean: float, scale: float) -> None:
        super().__init__()
        self.criterion = criterion
        self.register_buffer("target_mean", torch.tensor(mean, dtype=torch.float64))
        self.register_buffer("target_scale", torch.tensor(scale, dtype=torch.float64))

    def forward(self, prediction: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        if prediction.shape != target.shape:
            raise ValueError(
                "target standardization requires identical regression prediction/target shapes"
            )
        mean, scale = self.target_mean.to(prediction), self.target_scale.to(prediction)
        return self.criterion((prediction - mean) / scale, (target - mean) / scale)


def load_trained_state(
    model: nn.Module, state: Mapping[str, Any], *, require_standardized: bool | None = None
) -> nn.Module:
    """Preserve plain strict loading; reconstruct an explicitly marked wrapper."""
    standardized = _VERSION in state
    if require_standardized is not None and standardized != require_standardized:
        raise ValueError("checkpoint target standardization disagrees with certified construction")
    if standardized:
        version = state[_VERSION]
        if not isinstance(version, torch.Tensor) or version.numel() != 1 or version.item() != 1:
            raise ValueError("unsupported target standardization checkpoint version")
        values = []
        for name in ("target_mean", "target_scale"):
            value = state.get(name)
            if not isinstance(value, torch.Tensor) or value.numel() != 1:
                raise ValueError(f"invalid target standardization checkpoint {name}")
            values.append(float(value.item()))
        resident = next(model.parameters(), None)
        if resident is None:
            resident = next(model.buffers(), None)
        device = resident.device if resident is not None else torch.device("cpu")
        model = StandardizedTargetModel(model, mean=values[0], scale=values[1]).to(device)
    model.load_state_dict(state, strict=True)
    return model


def target_standardization_implementation_sha256() -> str:
    """Identity covers reconstruction, inverse transform and loss semantics."""
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
