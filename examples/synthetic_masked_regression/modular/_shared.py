"""Shared task scope identity and observation-only model metadata."""

from __future__ import annotations

from torch import nn

from ..plugins._masked_task import MaskedScope


def require_scope(scope: object) -> MaskedScope:
    """The metric consumes the exact class returned by the data-path entry."""
    if not isinstance(scope, MaskedScope):
        raise TypeError("modular metric requires the data path's shared MaskedScope class")
    return scope


def trainable_parameters(model: nn.Module) -> float:
    return float(
        sum(parameter.numel() for parameter in model.parameters() if parameter.requires_grad)
    )
