"""Synthetic admission provenance; StubSandbox launches no subprocess."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict

from core.execution_calibration import RoleCeiling, resolve_role_ceiling


class PseudoAdmission(BaseModel):
    """No execution envelope; optional ceilings are declarations, never enforced here."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: Literal["pseudo: no execution envelope (StubSandbox launches no subprocess)"] = (
        "pseudo: no execution envelope (StubSandbox launches no subprocess)"
    )
    training: RoleCeiling
    inference: RoleCeiling
    scoring: RoleCeiling


def resolve_pseudo_admission(*, environ: Mapping[str, str] | None = None) -> PseudoAdmission:
    """Validate optional declarations through the sole ceiling parser, without discovery."""
    return PseudoAdmission(
        training=resolve_role_ceiling("training", environ=environ),
        inference=resolve_role_ceiling("inference", environ=environ),
        scoring=resolve_role_ceiling("scoring", environ=environ),
    )
