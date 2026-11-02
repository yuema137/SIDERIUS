"""Explicit resource declarations for synthetic training, never GPU evidence."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict

from core.execution_calibration import RoleCeiling, resolve_role_ceiling


class PseudoEnvelopeRequired(ValueError):
    """Pseudo training has no explicit positive resource envelope."""


class PseudoEnvelope(BaseModel):
    """Caller-declared address-space limits, not measured candidate demand."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    training: RoleCeiling
    inference: RoleCeiling
    scoring: RoleCeiling


def resolve_pseudo_envelope(*, environ: Mapping[str, str] | None = None) -> PseudoEnvelope:
    """Reuse the ceiling owner; omitted/unbounded limits cannot admit a smoke run."""
    roles = {
        role: resolve_role_ceiling(role, environ=environ)
        for role in ("training", "inference", "scoring")
    }
    if any(ceiling.gib is None or ceiling.gib == 0 for ceiling in roles.values()):
        raise PseudoEnvelopeRequired(
            "PSEUDO_ENVELOPE_REQUIRED: pseudo training requires explicit positive "
            "SIDERIUS_SUBPROCESS_RSS_GB ceilings for training, inference and scoring. "
            "Declare one integer GiB value or a complete role mapping. These are "
            "synthetic admission limits, not measured GPU capacity."
        )
    return PseudoEnvelope(**roles)
