"""Relative imports share task types; existing metric arithmetic is unchanged."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from execute_tools.evaluation_metric import PresenceScoreabilityContract

from ..plugins._masked_metrics import MaskedMseMetric
from ._shared import require_scope


class SharedScopeMaskedMse(MaskedMseMetric):
    def _compute(
        self,
        deliverables: Mapping[int, str],
        /,
        *,
        evaluation_payload: Mapping[str, Mapping[str, Any]],
        task_scope: Any,
        data_dir: str | None = None,
    ) -> tuple[float, list[float | None] | None, tuple[str, ...]]:
        require_scope(task_scope)
        return super()._compute(
            deliverables,
            evaluation_payload=evaluation_payload,
            task_scope=task_scope,
            data_dir=data_dir,
        )


class ModularPresence(PresenceScoreabilityContract):
    """Task-local declaration of the same existing file-presence contract."""
