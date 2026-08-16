"""Training observation payload and the typed trainer→tuner results contract.

Step 07 PR 07a (design: ``docs/design/generic_framework_upgrade/
step_07_tuner_policy_and_training_diagnostics/pr_07a_training_history_diagnosis.md``
§3.3, §3.4a, §3.5; genericity contract Seam 5). This module is the
PRODUCER-side schema — the trainer builds a :class:`TrainingHistory`, dumps
it beside the three legacy result keys, and the tuner re-validates it
through :func:`interpret_training_results`, the ONE validation site.

Frozen semantics this module carries:

* **R2** = the per-epoch TRAINING observation of the run-resolved objective
  (the SAME floats as the legacy ``loss_history``; its computation is
  untouched by 07a).
* **R3** = the per-epoch VALIDATION observation of the SAME resolved
  computation on the run-bound validation scope — no backprop, no
  optimizer step; ``None`` ONLY when no validation scope was given.
* R2 and R3 use ONE declared epoch estimator (:data:`EPOCH_STATISTIC`); they
  are claimed comparable AS THE SAME OBJECTIVE STATISTIC only when
  ``comparability == "established"`` (precondition P, §3.3): the criterion's
  batch scalar must be mean-normalized over the batch's samples. The
  audited built-in mean-reduced objectives satisfy it; ``reduction="sum"``
  and custom plugin losses are LABELLED ``not_established`` — recorded,
  never assumed.
* ``objective_kind`` is the objective FAMILY (``LossConfig.loss_type``, a
  label); ``objective_config_fingerprint`` is a deterministic SHA-256 of the
  canonical serialized RESOLVED ``LossConfig`` — a fingerprint of the
  configuration SURFACE (it separates ``focal(gamma=1)`` from ``focal(gamma=4)``);
  it does NOT hash or identify arbitrary custom plugin implementation code.
  No ``TrainingObjective`` abstraction is introduced.
* Expected validation ≠ optional validation (§3.4a): when the caller
  expected validation and the history carries no R3, that is a CONTRACT
  FAILURE (:class:`TrainingResultsContractError`), never a quiet
  ``absent``.
* Non-finite objective values are EVIDENCE (a diverged run), not a schema
  error; only the lengths must agree.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ml_models.models_format_sandbox import LossConfig

#: The three legacy trainer→tuner result keys. Their presence and values are
#: the compatibility floor (OD-S7-3): unchanged by 07a, feeding the reflect
#: merge and the record exactly as before.
LEGACY_TRAINING_RESULT_KEYS: tuple[str, ...] = ("final_loss", "loss_history", "model_params")

#: The additive results key carrying the dumped :class:`TrainingHistory`.
TRAINING_HISTORY_KEY = "training_history"

#: The ONE epoch estimator formula R2 and R3 both use — the sample-count-
#: weighted mean of the criterion's batch scalar. R2 (``np.mean`` over
#: ``drop_last=True`` equal-size batches) IS this estimator with equal
#: weights; R3 applies it over the ENTIRE validation set with the batch
#: sample counts as weights, so an unequal last batch is weighted exactly.
EPOCH_STATISTIC = "sample_count_weighted_mean_of_batch_criterion"

#: Built-in objective kinds whose batch scalar is mean-normalized over the
#: batch's samples under the framework's batching (design §3.3 audit at
#: ``ml_models/loss_models_sandbox.py``): ``focal`` / ``focal_cw`` take
#: ``.mean()`` over B×T with a fixed T per sample; ``ce`` and ``smooth_l1``
#: are element means (the streaming path always passes ``class_weights=None``).
#: A kind is added here by SOURCE AUDIT, never by assumption.
COMPARABILITY_ESTABLISHED_KINDS: frozenset[str] = frozenset(
    {"focal", "focal_cw", "ce", "smooth_l1"}
)

COMPARABILITY_REASON_SUM = "reduction=sum"
COMPARABILITY_REASON_CUSTOM = "custom_objective_undeclared"

Comparability = Literal["established", "not_established"]


class TrainingResultsContractError(ValueError):
    """The trainer's results violate the typed trainer→tuner contract.

    Raised at the tuner boundary (never silently downgraded) when the
    ``training_history`` payload is present but schema-invalid, disagrees
    with the legacy keys, or when validation was EXPECTED and no R3 arrived.
    """


def objective_config_fingerprint(loss_cfg: LossConfig) -> str:
    """Deterministic SHA-256 of the canonical serialized RESOLVED ``LossConfig``.

    Canonical = ``json.dumps(model_dump(), sort_keys=True, separators=(",", ":"))``
    — key order and whitespace cannot perturb it, so the value is stable
    across processes and hosts. It fingerprints the resolved CONFIGURATION
    SURFACE (loss_type, loss_name, alpha, gamma, beta, reduction,
    use_class_weights); it is NOT a hash of plugin code.
    """
    canonical = json.dumps(loss_cfg.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def stamp_comparability(loss_cfg: LossConfig) -> tuple[Comparability, str | None]:
    """Decide the R2/R3 comparability stamp from the RESOLVED ``LossConfig``.

    ``established`` iff ``reduction == "mean"`` AND the kind is in the audited
    built-in set; a custom objective is ``not_established`` with reason
    :data:`COMPARABILITY_REASON_CUSTOM` (the plugin contract declares no
    normalization); a ``sum`` reduction is ``not_established`` with reason
    :data:`COMPARABILITY_REASON_SUM`.
    """
    if loss_cfg.loss_type == "custom":
        return "not_established", COMPARABILITY_REASON_CUSTOM
    if loss_cfg.reduction != "mean":
        return "not_established", COMPARABILITY_REASON_SUM
    if loss_cfg.loss_type in COMPARABILITY_ESTABLISHED_KINDS:
        return "established", None
    # A future built-in kind not yet audited: honest by default.
    return "not_established", COMPARABILITY_REASON_CUSTOM


class TrainingHistory(BaseModel):
    """Per-epoch training observation payload (R2 + optional R3 + R4 slot).

    Frozen schema (design §3.5). ``extra="forbid"`` so a producer that adds an
    undeclared key fails at the tuner boundary rather than leaking.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    cadence: Literal["per_epoch"] = "per_epoch"
    objective_kind: str = Field(
        description="The run-resolved objective FAMILY (``LossConfig.loss_type``) — a label, not an identity."
    )
    objective_config_fingerprint: str = Field(
        description=(
            "SHA-256 of the canonical serialized RESOLVED LossConfig — the configuration "
            "surface only; not a hash of custom plugin code."
        )
    )
    objective_reduction: Literal["mean", "sum"]
    epoch_statistic: Literal["sample_count_weighted_mean_of_batch_criterion"] = EPOCH_STATISTIC
    comparability: Comparability
    comparability_reason: str | None = None
    epochs_planned: int = Field(ge=0)
    epochs_completed: int = Field(ge=0)
    train_objective: list[float] = Field(
        description="R2 — the SAME floats as the legacy loss_history."
    )
    validation_objective: list[float] | None = Field(
        default=None,
        description="R3 — None ONLY when no validation scope was given (legacy tolerance).",
    )
    validation_requested_samples: int | None = None
    validation_samples: int | None = None
    validation_seconds: list[float] | None = None
    observations: dict[str, list[float]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _consistent(self) -> TrainingHistory:
        n = len(self.train_objective)
        if self.epochs_completed != n:
            raise ValueError(
                f"epochs_completed ({self.epochs_completed}) must equal len(train_objective) ({n})."
            )
        if self.epochs_completed > self.epochs_planned:
            raise ValueError(
                f"epochs_completed ({self.epochs_completed}) exceeds epochs_planned "
                f"({self.epochs_planned})."
            )
        if self.comparability == "established":
            if self.comparability_reason is not None:
                raise ValueError(
                    "comparability_reason must be None when comparability is 'established'."
                )
        elif not self.comparability_reason:
            raise ValueError(
                "comparability_reason is required when comparability is 'not_established'."
            )

        validation_fields = (
            self.validation_objective,
            self.validation_requested_samples,
            self.validation_samples,
            self.validation_seconds,
        )
        present = [v is not None for v in validation_fields]
        if any(present) and not all(present):
            raise ValueError(
                "validation_objective, validation_requested_samples, validation_samples and "
                "validation_seconds must be present together or absent together."
            )
        if self.validation_objective is not None:
            if len(self.validation_objective) != n:
                raise ValueError(
                    f"len(validation_objective) ({len(self.validation_objective)}) must equal "
                    f"len(train_objective) ({n})."
                )
            assert self.validation_requested_samples is not None
            assert self.validation_samples is not None
            assert self.validation_seconds is not None
            if self.validation_requested_samples <= 0:
                raise ValueError(
                    "validation_requested_samples must be > 0 when validation is present."
                )
            if self.validation_samples != self.validation_requested_samples:
                raise ValueError(
                    f"validation_samples ({self.validation_samples}) must equal "
                    f"validation_requested_samples ({self.validation_requested_samples}) — the declared "
                    f"validation scope must materialize exactly (design §3.4b)."
                )
            if len(self.validation_seconds) != n:
                raise ValueError(
                    f"len(validation_seconds) ({len(self.validation_seconds)}) must equal "
                    f"epochs_completed ({n})."
                )
            if any(s < 0 for s in self.validation_seconds):
                raise ValueError("every validation_seconds value must be >= 0.")
        for name, series in self.observations.items():
            if len(series) != n:
                raise ValueError(
                    f"observations[{name!r}] has length {len(series)}, expected epochs_completed ({n})."
                )
        return self


class TrainingResults(BaseModel):
    """The typed trainer→tuner results contract (design §3.5).

    ``legacy_payload`` carries EXACTLY the legacy keys present in the raw
    results (presence and values as today) — it feeds the reflect merge and
    the record; ``history`` is the validated additive payload or ``None``
    when the producer emitted none.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    legacy_payload: dict[str, Any]
    history: TrainingHistory | None
    history_state: Literal["present", "absent"]

    def history_payload(self) -> dict[str, Any] | None:
        """The record-facing dump of the history (``None`` when absent)."""
        return None if self.history is None else self.history.model_dump()


def _same_float(a: object, b: object) -> bool:
    """NaN-aware equality for objective values (a diverged run is evidence)."""
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, int | float) and isinstance(b, int | float):
        fa, fb = float(a), float(b)
        return fa == fb or (math.isnan(fa) and math.isnan(fb))
    return a == b


def _same_series(xs: list[float], ys: object) -> bool:
    if not isinstance(ys, list) or len(xs) != len(ys):
        return False
    return all(_same_float(x, y) for x, y in zip(xs, ys, strict=True))


def interpret_training_results(raw: object, *, expected_validation: bool) -> TrainingResults:
    """Validate the trainer's raw results dict at the ONE validation site.

    Args:
        raw: the results mapping the executor forwarded verbatim (the JSON
            the trainer wrote, or a pseudo route's canned equivalent).
        expected_validation: ``True`` when the caller supplied an eval
            SampleSet for this attempt — R3 MUST then arrive (§3.4a).

    Raises:
        TrainingResultsContractError: raw is not a mapping; the
            ``training_history`` payload is present but schema-invalid;
            ``history.train_objective`` ≠ ``raw["loss_history"]``;
            ``final_loss`` ≠ ``train_objective[-1]``; or validation was
            expected and no history / no R3 arrived.
    """
    if not isinstance(raw, Mapping):
        raise TrainingResultsContractError(
            f"training results must be a mapping, got {type(raw).__name__}."
        )
    legacy_payload = {k: raw[k] for k in LEGACY_TRAINING_RESULT_KEYS if k in raw}

    history: TrainingHistory | None = None
    if TRAINING_HISTORY_KEY in raw:
        payload = raw[TRAINING_HISTORY_KEY]
        try:
            history = TrainingHistory.model_validate(payload)
        except ValidationError as exc:
            raise TrainingResultsContractError(
                f"training_history payload is schema-invalid: {exc}"
            ) from exc
        if not _same_series(history.train_objective, raw.get("loss_history")):
            raise TrainingResultsContractError(
                "training_history.train_objective disagrees with the legacy loss_history "
                f"({history.train_objective!r} vs {raw.get('loss_history')!r})."
            )
        if history.train_objective and (
            "final_loss" not in raw
            or not _same_float(raw["final_loss"], history.train_objective[-1])
        ):
            raise TrainingResultsContractError(
                "final_loss must equal the last training objective observation "
                f"({raw.get('final_loss')!r} vs {history.train_objective[-1]!r})."
            )

    if expected_validation and (history is None or history.validation_objective is None):
        raise TrainingResultsContractError(
            "validation was EXPECTED for this attempt (an eval SampleSet was supplied) but the "
            "training results carry no validation observation (R3): "
            + ("no training_history payload" if history is None else "validation_objective is None")
            + ". This is a contract failure, never a success with validation_state='absent'."
        )

    return TrainingResults(
        legacy_payload=legacy_payload,
        history=history,
        history_state="present" if history is not None else "absent",
    )
