"""Read-only training-budget diagnostics; never allocate work or stop a run."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from core.runtime_control.phases import RuntimePhase
from core.runtime_control.records import RuntimeObservation

if TYPE_CHECKING:
    from core.runtime_control.session import RuntimeVerificationSession


class TrainingBudgetDiagnostic(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: str
    epochs: int = Field(ge=1)
    optimizer_steps: int = Field(ge=0)
    budget_seconds: float | None = Field(default=None, gt=0)
    predicted_training_seconds: float | None = Field(default=None, ge=0)
    actual_training_seconds: float | None = Field(default=None, ge=0)
    predicted_training_budget_fraction: float | None = Field(default=None, ge=0)
    missing_prediction_phases: list[str]
    message: str


def training_budget_diagnostic(
    observation: RuntimeObservation,
    *,
    stage: str,
    epochs: int,
    optimizer_steps: int,
    budget_seconds: float | None,
) -> TrainingBudgetDiagnostic:
    """Keep missing phase evidence distinct from measured zero cost.

    Low training projection is a diagnostic only: it cannot establish unused
    whole-attempt budget, model convergence, or a need to consume more VRAM.
    """
    training = observation.components.get("training")
    predicted = (
        training.prediction.predicted_seconds
        if training is not None and training.prediction is not None
        else None
    )
    actual = training.actual_seconds if training is not None else None
    phases: tuple[RuntimePhase, ...] = ("training", "validation", "inference", "scoring")
    missing = [
        phase
        for phase in phases
        if (component := observation.components.get(phase)) is None or component.prediction is None
    ]
    fraction = predicted / budget_seconds if predicted is not None and budget_seconds else None
    message = (
        "Fixed epoch horizon; execution will not add epochs to consume remaining budget. "
        "Budget is admission-only, not guaranteed optimization time. "
        "Missing phase predictions are unknown, not zero; no unused-budget claim is possible."
    )
    if fraction is not None and fraction < 0.1:
        message = (
            "LOW_TRAINING_BUDGET_PROJECTION: predicted training loop uses less than "
            "10% of the attempt budget. Review the epoch ceiling, selected rows and "
            "measured phase costs before the next campaign. " + message
        )
    return TrainingBudgetDiagnostic(
        stage=stage,
        epochs=epochs,
        optimizer_steps=optimizer_steps,
        budget_seconds=budget_seconds,
        predicted_training_seconds=predicted,
        actual_training_seconds=actual,
        predicted_training_budget_fraction=fraction,
        missing_prediction_phases=missing,
        message=message,
    )


def report_training_budget(
    session: RuntimeVerificationSession | None, *, stage: str, epochs: int
) -> None:
    """Emit early evidence into the existing attempt log, without new policy."""
    if session is None or session.policy.training_budget is not None:
        return
    observation = session.observation
    component = observation.components.get("training")
    steps = component.workload.unit_count if component and component.workload else 0
    report = training_budget_diagnostic(
        observation,
        stage=stage,
        epochs=epochs,
        optimizer_steps=steps,
        budget_seconds=session.policy.operator_budget_seconds,
    )
    print(f"[training_budget] {report.model_dump_json()}", flush=True)
