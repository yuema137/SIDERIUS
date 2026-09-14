"""Transient task-bound inputs carried into one training subprocess."""

from __future__ import annotations

from dataclasses import dataclass

from core.capability_registry import CapabilityContractSnapshot


@dataclass(frozen=True, slots=True)
class TrainingExecutionBindings:
    """Group resolved task authorities consumed only by training launch."""

    task_scopes: object | None = None
    expected_custom_loss_snapshot: CapabilityContractSnapshot | dict | None = None
