"""Resolve native custom-loss target routing from the task-owned contract."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from agent.schemas.custom_loss_contract import (
    parse_custom_loss_contract_snapshot,
    resolve_custom_loss_snapshot,
)
from core.capability_registry import CapabilityContractSnapshot


class CustomLossTarget(BaseModel):
    """The two target representations currently supported by native loss routing."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    declaration: Literal["long", "float"]

    @property
    def dtype_name(self) -> str:
        return "int64" if self.declaration == "long" else "float32"

    @property
    def torch_dtype(self):
        import torch

        return getattr(torch, self.dtype_name)


def resolve_custom_loss_target(
    snapshot: CapabilityContractSnapshot | None,
) -> CustomLossTarget:
    """Use declared canonical targets; only uncontracted legacy losses default."""
    if snapshot is None:
        return CustomLossTarget(declaration="long")
    payload = parse_custom_loss_contract_snapshot(snapshot)
    canonical = payload.supervision_target.dtype.canonical.removeprefix("torch.")
    aliases = {"int64": "long", "long": "long", "float32": "float", "float": "float"}
    if canonical not in aliases:
        raise ValueError(
            f"Native custom-loss targets do not support canonical dtype {canonical!r}; "
            "supported representations are int64 and float32"
        )
    target = CustomLossTarget.model_validate({"declaration": aliases[canonical]})
    verdict = resolve_custom_loss_snapshot(snapshot, target_cast_dtype=target.dtype_name)
    if not verdict.eligible:
        raise ValueError(f"Custom-loss target contract refused: {verdict.reason}")
    return target


def validate_custom_loss_target_declaration(
    declaration: object,
    snapshot: CapabilityContractSnapshot | None,
) -> CustomLossTarget:
    """Validate actual plugin metadata without guessing or clamping invalid values."""
    actual = CustomLossTarget.model_validate({"declaration": declaration})
    if snapshot is not None:
        expected = resolve_custom_loss_target(snapshot)
        if actual != expected:
            raise ValueError(
                f"Custom-loss target declaration {actual.declaration!r} conflicts with "
                f"the task's canonical {expected.dtype_name} target"
            )
    return actual
