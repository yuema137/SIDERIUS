"""``TrainingDiagnosis`` — a PURE, deterministic derivation from ``TrainingHistory``.

Step 07 PR 07a (design §3.6; genericity contract Seam 5; parent §8.2 item 3).

* A pure function of the history: no I/O, no LLM, no clock, no randomness —
  identical output for identical input. Computed ONCE at the tuner boundary
  and persisted on ``ExperimentRecord``; never re-derived elsewhere.
* v1 carries FACTUAL, calibration-free fields only: state, best validation
  epoch, endpoints / minima, trends with an EXPLICIT symmetric scale-free
  deadband, final-vs-best validation degradation, and the train-validation
  gap. **No ``overfitting`` / ``underfitting`` / ``converged`` / ``plateau``
  labels** — each needs a window, a tolerance policy or an "is this good
  enough" scale that curve shape alone cannot supply (07b renders selected
  facts; Step 09 may derive calibrated labels by explicit act).
* Cross-curve fields (the gap) are ``None`` unless the history's
  ``comparability == "established"`` (§3.3) — a ``sum``-reduced or custom
  objective is recorded, not compared.
* Symmetric scale-free relative change (§0.5 item 6, no zero-reference
  pathology)::

      r(a, b) = 0                       if |a| = |b| = 0
              = |b - a| / max(|a|, |b|) otherwise
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from execute_tools.training_history import TrainingHistory

#: The named deadband of the boundary: |last − first| relative to the larger
#: magnitude at or below this is "flat". Recorded on every diagnosis as
#: ``flat_rel_tol`` so a consumer can re-derive the trend from the endpoints.
FLAT_REL_TOL = 1e-2

DiagnosisState = Literal["ok", "absent", "invalid"]
ValidationState = Literal["present", "absent"]
Trend = Literal["decreasing", "increasing", "flat", "single_point"]


def symmetric_relative_change(a: float, b: float) -> float:
    """``r(a, b) = |b − a| / max(|a|, |b|)``; ``0`` when both are zero.

    Scale-invariant and symmetric in its arguments; bounded in ``[0, 2]``.
    """
    denom = max(abs(a), abs(b))
    if denom == 0.0:
        return 0.0
    return abs(b - a) / denom


def _trend(series: list[float], tol: float) -> Trend:
    if len(series) < 2:
        return "single_point"
    first, last = series[0], series[-1]
    if symmetric_relative_change(first, last) <= tol:
        return "flat"
    return "decreasing" if last < first else "increasing"


def _all_finite(series: list[float] | None) -> bool:
    return series is None or all(math.isfinite(v) for v in series)


class TrainingDiagnosis(BaseModel):
    """Deterministic, compact, calibration-free facts about one training run.

    Frozen schema (design §3.6). Every optional field is ``None`` exactly when
    the history cannot support it: ``absent`` / ``invalid`` states carry no
    curve facts; validation fields need R3; the gap needs
    ``comparability == "established"``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: DiagnosisState = Field(
        description=(
            "ok — a finite history; absent — no history payload (legacy trainer / crash); "
            "invalid — empty R2, or any non-finite value in R2/R3 (divergence evidence; the raw "
            "values stay on the record)."
        )
    )
    validation_state: ValidationState = Field(
        description="absent → 'not fully supported' (OD-20-4 legacy tolerance)."
    )
    comparability: Literal["established", "not_established"] | None = Field(
        default=None,
        description="Copied from the history so a consumer of the diagnosis alone knows why the gap is None.",
    )
    epochs_planned: int | None = None
    epochs_completed: int | None = None
    truncated: bool | None = Field(
        default=None, description="completed < planned (stability stop / early exit)."
    )

    train_first: float | None = None
    train_last: float | None = None
    train_min: float | None = None
    train_min_epoch: int | None = Field(
        default=None, description="0-based, the trainer's numbering."
    )

    validation_first: float | None = None
    validation_last: float | None = None
    validation_min: float | None = None
    best_validation_epoch: int | None = Field(default=None, description="argmin R3, 0-based.")

    final_vs_best_validation_degradation: float | None = Field(
        default=None, description="validation_last − validation_min (≥ 0)."
    )
    final_vs_best_validation_degradation_rel: float | None = Field(
        default=None, description="r(validation_min, validation_last)."
    )
    validation_degraded_after_best: bool | None = Field(
        default=None,
        description=(
            "r(validation_min, validation_last) > flat_rel_tol AND validation_last > validation_min "
            "— the calibration-free shape fact; NOT an overfitting label."
        ),
    )

    train_validation_gap_final: float | None = Field(
        default=None,
        description="validation_last − train_last (signed); None unless comparability is established.",
    )
    train_validation_gap_final_rel: float | None = Field(
        default=None, description="r(train_last, validation_last); same gating as the gap."
    )

    train_trend: Trend | None = None
    validation_trend: Trend | None = None
    flat_rel_tol: float = FLAT_REL_TOL


def derive_training_diagnosis(
    history: TrainingHistory | None, *, flat_rel_tol: float = FLAT_REL_TOL
) -> TrainingDiagnosis:
    """The ONE derivation (design §3.6). Pure; deterministic; no I/O.

    Args:
        history: the validated payload, or ``None`` when the producer emitted
            none (legacy trainer, pseudo route not upgraded, crash).
        flat_rel_tol: the symmetric relative deadband (default the module
            constant); recorded on the result.
    """
    if history is None:
        return TrainingDiagnosis(
            state="absent", validation_state="absent", flat_rel_tol=flat_rel_tol
        )

    r2 = list(history.train_objective)
    r3 = list(history.validation_objective) if history.validation_objective is not None else None
    validation_state: ValidationState = "present" if r3 is not None else "absent"

    if not r2 or not _all_finite(r2) or not _all_finite(r3):
        # Divergence / non-finite criterion is EVIDENCE — the raw values stay
        # on the record's history; the diagnosis declines to summarize them.
        return TrainingDiagnosis(
            state="invalid",
            validation_state=validation_state,
            comparability=history.comparability,
            epochs_planned=history.epochs_planned,
            epochs_completed=history.epochs_completed,
            truncated=history.epochs_completed < history.epochs_planned,
            flat_rel_tol=flat_rel_tol,
        )

    train_min_epoch = min(range(len(r2)), key=lambda i: r2[i])
    fields: dict[str, object] = {
        "state": "ok",
        "validation_state": validation_state,
        "comparability": history.comparability,
        "epochs_planned": history.epochs_planned,
        "epochs_completed": history.epochs_completed,
        "truncated": history.epochs_completed < history.epochs_planned,
        "train_first": r2[0],
        "train_last": r2[-1],
        "train_min": r2[train_min_epoch],
        "train_min_epoch": train_min_epoch,
        "train_trend": _trend(r2, flat_rel_tol),
        "flat_rel_tol": flat_rel_tol,
    }
    if r3 is not None:
        best = min(range(len(r3)), key=lambda i: r3[i])
        degradation_rel = symmetric_relative_change(r3[best], r3[-1])
        fields.update(
            {
                "validation_first": r3[0],
                "validation_last": r3[-1],
                "validation_min": r3[best],
                "best_validation_epoch": best,
                "final_vs_best_validation_degradation": r3[-1] - r3[best],
                "final_vs_best_validation_degradation_rel": degradation_rel,
                "validation_degraded_after_best": bool(
                    degradation_rel > flat_rel_tol and r3[-1] > r3[best]
                ),
                "validation_trend": _trend(r3, flat_rel_tol),
            }
        )
        if history.comparability == "established":
            fields.update(
                {
                    "train_validation_gap_final": r3[-1] - r2[-1],
                    "train_validation_gap_final_rel": symmetric_relative_change(r2[-1], r3[-1]),
                }
            )
    return TrainingDiagnosis.model_validate(fields)
