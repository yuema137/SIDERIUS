"""Retain one CPU state snapshot, without changing the optimization trajectory."""

import copy
import math
from collections import OrderedDict
from typing import Any

import torch

from core.checkpoint_selection import CheckpointSelection, SelectedCheckpoint


class _ModelState(OrderedDict[str, Any]):
    _metadata: dict[str, Any]


class CheckpointSelector:
    def __init__(self, policy: CheckpointSelection, *, has_validation: bool) -> None:
        if policy == "best_validation_loss" and not has_validation:
            raise ValueError(
                "best_validation_loss requires an explicit fixed training-validation scope; "
                "configure validation before training or use last_completed_epoch"
            )
        self.policy = policy
        self.selected: SelectedCheckpoint | None = None
        self._state: OrderedDict[str, Any] | None = None

    def observe(self, model: torch.nn.Module, *, epoch: int, validation_loss: float) -> None:
        if self.policy == "last_completed_epoch":
            return
        if not math.isfinite(validation_loss):
            raise ValueError("best_validation_loss cannot select a non-finite validation objective")
        if self.selected is not None and validation_loss >= self.selected.validation_loss:
            return  # Ties retain the earliest epoch; optimizer state is never restored.
        selected = SelectedCheckpoint(epoch=epoch, validation_loss=validation_loss)
        source = model.state_dict()
        self._state = None  # Release the previous snapshot before allocating another.
        snapshot = _ModelState(
            (
                key,
                value.detach().to(device="cpu", copy=True)
                if isinstance(value, torch.Tensor)
                else copy.deepcopy(value),
            )
            for key, value in source.items()
        )
        # Module load versioning and get_extra_state/set_extra_state are preserved.
        metadata = getattr(source, "_metadata", None)
        if metadata is not None:
            snapshot._metadata = copy.deepcopy(metadata)
        self._state = snapshot
        self.selected = selected

    def restore(self, model: torch.nn.Module) -> SelectedCheckpoint | None:
        if self.policy == "last_completed_epoch":
            return None
        if self._state is None or self.selected is None:
            raise ValueError(
                "best_validation_loss has no completed validation checkpoint to export"
            )
        model.load_state_dict(self._state, strict=True)
        self._state = None
        return self.selected
