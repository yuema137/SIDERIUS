"""Synthetic admission provenance and the pseudo evaluation ceiling; StubSandbox launches no subprocess."""

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


#: Pseudo evaluation ceiling in framework rows (``ScopeBuildRequest.max_samples``).
#: Synthetic Health evidence needs a few deliverable rows, not the full scope, so
#: pseudo cost is bounded by this count rather than by dataset size.
PSEUDO_VALIDATION_MAX_SAMPLES = 256


def resolve_pseudo_validation_max_samples(
    explicit: int | None, *, is_pseudo_training: bool
) -> int | None:
    """Return the evaluation row ceiling a launch records.

    An operator value always wins. Pseudo training without one receives
    ``PSEUDO_VALIDATION_MAX_SAMPLES``; every other launch keeps ``explicit``.
    The task's own ``build_eval_scope`` honours the ceiling (deterministic,
    order-preserving, task-owned); the framework never edits an opaque scope.
    """
    if explicit is not None or not is_pseudo_training:
        return explicit
    return PSEUDO_VALIDATION_MAX_SAMPLES
