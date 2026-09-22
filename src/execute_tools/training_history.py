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
* That evidence must SURVIVE the storage boundary. Every record is written
  through :func:`execute_tools.scoring_utils.coerce_nonfinite_to_none`
  (``sandbox_executor.LocalRecorder.save_record``), which replaces every
  non-finite float with JSON ``null`` — RFC-8259 has no NaN/Infinity token.
  So the STORAGE IMAGE of a diverged objective is a ``None`` ELEMENT, and
  the objective series accept it: ``list[float | None]``. Positions are
  preserved, so ``epochs_completed == len(train_objective)`` and the
  R2/R3 length agreement are unaffected. A strict ``list[float]`` here made
  re-validation of a diverged run's own record raise, which discarded the
  whole scored attempt rather than declining to summarize it.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from core.checkpoint_selection import CheckpointSelection, SelectedCheckpoint
from core.runtime_control.training_budget import TrainingBudgetReceipt
from core.target_standardization import TargetStandardization, TargetStandardizationReceipt
from ml_models.models_format_sandbox import LossConfig

#: The three legacy trainer→tuner result keys. Their presence and values are
#: the compatibility floor (OD-S7-3): unchanged by 07a, feeding the reflect
#: merge and the record exactly as before.
LEGACY_TRAINING_RESULT_KEYS: tuple[str, ...] = ("final_loss", "loss_history", "model_params")

#: The additive results key carrying the dumped :class:`TrainingHistory`.
TRAINING_HISTORY_KEY = "training_history"

#: `R-OBS-1` — the additive results key carrying the run's STATIC observations
#: (``{name: float}``), written by the trainer ONLY when the task declared
#: static observables and at least one produced a value.
#:
#: A sibling of :data:`TRAINING_HISTORY_KEY` rather than a field on
#: :class:`TrainingHistory`, deliberately. A new schema field would appear in
#: every ``model_dump()``, so every future record's persisted JSON would gain
#: ``"static_observations": {}`` — a byte change to every artifact of every
#: run, to carry a value only a declaring task has. The conditional sibling
#: key is the shape ``secondary_metric_results`` already uses one layer up,
#: and it keeps a non-declaring run's payload byte-identical.
#:
#: The DYNAMIC family needs no such key: it lands in
#: :attr:`TrainingHistory.observations`, which has existed (and been empty)
#: all along.
STATIC_OBSERVATIONS_KEY = "static_observations"

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


def objective_config_fingerprint(
    loss_cfg: LossConfig, *, target_standardization: TargetStandardizationReceipt | None = None
) -> str:
    """Deterministic SHA-256 of the canonical serialized RESOLVED ``LossConfig``.

    Canonical = ``json.dumps(model_dump(), sort_keys=True, separators=(",", ":"))``
    — key order and whitespace cannot perturb it, so the value is stable
    across processes and hosts. It fingerprints the resolved CONFIGURATION
    SURFACE (loss_type, loss_name, alpha, gamma, beta, reduction,
    use_class_weights) plus an explicitly enabled fitted target transform;
    it is NOT a hash of plugin code. Default bytes are unchanged.
    """
    payload = loss_cfg.model_dump(mode="json")
    if target_standardization is not None:
        payload["target_standardization"] = target_standardization.model_dump(
            exclude={"fit_seconds"}
        )
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _declared_custom_reduction(loss_name: str | None) -> str | None:
    """The custom plugin's DECLARED reduction, or ``None``.

    Imported lazily: ``execute_tools`` must stay importable without
    ``agent_generated/`` on the path (the legacy isolation tests rely on it),
    and a comparability stamp is not worth coupling the two modules at import
    time. A loader that cannot be imported means nothing was declared, which
    is the honest answer rather than an error.
    """
    if not loss_name:
        return None
    try:
        from ml_models.loss_plugin_loader import get_loss_declared_reduction
    except ImportError:
        return None
    return get_loss_declared_reduction(loss_name)


def stamp_comparability(loss_cfg: LossConfig) -> tuple[Comparability, str | None]:
    """Decide the R2/R3 comparability stamp from the RESOLVED ``LossConfig``.

    ``established`` iff ``reduction == "mean"`` AND the kind is in the audited
    built-in set; a custom objective is ``not_established`` with reason
    :data:`COMPARABILITY_REASON_CUSTOM` (the plugin contract declares no
    normalization); a ``sum`` reduction is ``not_established`` with reason
    :data:`COMPARABILITY_REASON_SUM`.
    """
    if loss_cfg.loss_type == "custom":
        # Step 12 / PR-12d D4c. This used to be an unconditional refusal, and
        # the reason string named the way out: `custom_objective_undeclared`
        # is a statement about what the PLUGIN failed to say, not about custom
        # objectives being inherently incomparable.
        #
        # A plugin that declares `PLUGIN_LOSS_REDUCTION = "mean"` makes the
        # same claim the audited built-in kinds make by construction, so the
        # same rule applies to it: mean-reduced values are comparable across
        # epochs, sum-reduced ones are not (they scale with batch count).
        # Declaring nothing stays `not_established` — unchanged, and for the
        # same honest reason.
        declared = _declared_custom_reduction(loss_cfg.loss_name)
        if declared is None:
            return "not_established", COMPARABILITY_REASON_CUSTOM
        if declared != "mean":
            return "not_established", COMPARABILITY_REASON_SUM
        return "established", None
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
            "surface and optional fitted target transform; not a hash of custom plugin code."
        )
    )
    objective_reduction: Literal["mean", "sum"]
    epoch_statistic: Literal["sample_count_weighted_mean_of_batch_criterion"] = EPOCH_STATISTIC
    comparability: Comparability
    comparability_reason: str | None = None
    epochs_planned: int = Field(ge=0)
    epochs_completed: int = Field(ge=0)
    training_samples: list[int] | None = Field(default=None, exclude_if=lambda v: v is None)
    train_objective: list[float | None] = Field(
        description=(
            "R2 — the SAME floats as the legacy loss_history. An ELEMENT is "
            "None where that epoch's objective was non-finite and the record "
            "has crossed the storage boundary (see the module docstring's "
            "storage-image note); the LIST itself is never None."
        )
    )
    validation_objective: list[float | None] | None = Field(
        default=None,
        description=(
            "R3 — the LIST is None ONLY when no validation scope was given "
            "(legacy tolerance). An ELEMENT is None on the same storage-image "
            "grounds as train_objective: R3 is the SAME criterion, so a "
            "diverged model produces non-finite R3 rows too."
        ),
    )
    validation_requested_samples: int | None = None
    validation_samples: int | None = None
    validation_requested_samples_before_limit: int | None = Field(
        default=None,
        description=(
            "Step 07 / PR 07c C6 (Q-07c-9). The NATURAL validation scope, "
            "before ``validation_max_samples`` was applied. ``None`` when no "
            "ceiling was configured.\n\n"
            "An explicit field because the clamp's provenance is otherwise "
            "UNRECOVERABLE. The ceiling is applied to the REQUESTED scope, so "
            "``validation_requested_samples`` afterwards means the EFFECTIVE "
            "requested scope and equals ``validation_samples`` by "
            "construction; and the run-level input cannot disambiguate "
            "either — ``ceiling=2000, requested=2000`` reads identically "
            "whether the natural scope was 2,000 and the ceiling did not "
            "bind, or was 12,000 and the ceiling clamped it. So::\n\n"
            "    was_limited = validation_requested_samples_before_limit\n"
            "                      > validation_requested_samples\n\n"
            "is derivable with certainty, and 07a's exact-materialization "
            "invariant is untouched. Preferred over a boolean flag because "
            "the pre-limit count is strictly more informative and cannot go "
            "stale relative to the other two.\n\n"
            "This is SCOPE provenance and is deliberately NOT expressed "
            "through ``comparability``, which is a function of the resolved "
            "``LossConfig`` alone and owns R2-vs-R3 computation "
            "comparability, not cross-round scope."
        ),
    )
    validation_seconds: list[float] | None = None
    observations: dict[str, list[float]] = Field(
        default_factory=dict,
        description=(
            "Named per-epoch series ALONGSIDE R2/R3 — a validation quantity "
            "that is NOT the resolved objective (pets: validation_accuracy "
            "under a `ce` objective; davis: validation_psnr under `mae`). "
            "Each series must be `epochs_completed` long, enforced below.\n\n"
            "**READ THIS BEFORE BUILDING ON IT (Lane E, F1).** The carrier is "
            "real but the feature is UNFINISHED, and the shape of what is "
            "missing is not obvious from the type:\n\n"
            "* there is NO DECLARATION SURFACE — the manifest's "
            "``_MANIFEST_KEYS`` has no section through which a task can say "
            "it wants a validation quantity distinct from its objective;\n"
            "* there is NO PRODUCTION PRODUCER — the training subprocess "
            "never populates this dict, so every persisted record carries "
            "``{}``;\n"
            "* NO REAL TRAINING RUN HAS EVER PRODUCED AN OBSERVATION. The "
            "only populated instances are the two HAND-AUTHORED L1 fixtures "
            "under ``examples/{oxford_iiit_pet,davis_future_prediction}/"
            "expected/``. The ``real_component`` fixtures — whose R2/R3 came "
            "from actual bounded D14 gate runs — carry ``{}``.\n\n"
            "So this field is not a placeholder and not dead: it is the "
            "typed evidence that ONE history schema spans three sciences "
            "unchanged, which both packs' STATUS.md cite as L1 maturity, and "
            "which rung B-07a-1 asserts. Do not delete it to tidy up — that "
            "removes genericity evidence and breaks four committed fixtures "
            "against ``extra='forbid'``. Do not read it as production "
            "state either; it is empty in every real record."
        ),
    )

    @model_validator(mode="after")
    def _consistent(self) -> TrainingHistory:
        if self.training_samples is not None and (
            len(self.training_samples) != self.epochs_completed
            or any(count <= 0 for count in self.training_samples)
        ):
            raise ValueError("training_samples requires one positive row count per completed epoch")
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
            # 07c C6. A ceiling can only REDUCE the scope, so the pre-limit
            # count can never be smaller than the effective one. The reverse
            # would mean the clamp had somehow enlarged the requested scope,
            # which is the one thing a maximum must never do — and it would
            # invert `was_limited` for every downstream consumer.
            if (
                self.validation_requested_samples_before_limit is not None
                and self.validation_requested_samples_before_limit
                < self.validation_requested_samples
            ):
                raise ValueError(
                    f"validation_requested_samples_before_limit "
                    f"({self.validation_requested_samples_before_limit}) is smaller than "
                    f"validation_requested_samples ({self.validation_requested_samples}) — a "
                    f"validation-scope ceiling may only reduce the requested scope, never "
                    f"enlarge it."
                )
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
    training_budget: TrainingBudgetReceipt | None = None
    selected_checkpoint: SelectedCheckpoint | None = None
    target_standardization: TargetStandardizationReceipt | None = None
    static_observations: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "`R-OBS-1` — the run's STATIC observations, read off the trained "
            "model once after the final optimizer step. Empty for every run "
            "that declared none, which is every run today; the record writer "
            "then emits no key at all and the persisted artifact is "
            "byte-identical to its pre-R-OBS-1 self.\n\n"
            "Carried here rather than on ``TrainingHistory`` because a schema "
            "field would materialize in every history dump. See "
            "``STATIC_OBSERVATIONS_KEY``."
        ),
    )

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


def _same_series(xs: Sequence[float | None], ys: object) -> bool:
    if not isinstance(ys, list) or len(xs) != len(ys):
        return False
    return all(_same_float(x, y) for x, y in zip(xs, ys, strict=True))


def interpret_training_results(
    raw: object,
    *,
    expected_validation: bool,
    expected_checkpoint_selection: CheckpointSelection | None = None,
    expected_target_standardization: TargetStandardization | None = None,
) -> TrainingResults:
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

    budget = None
    if raw.get("training_budget") is not None:
        try:
            budget = TrainingBudgetReceipt.model_validate(raw["training_budget"])
        except ValidationError as exc:
            raise TrainingResultsContractError(
                f"training_budget payload is schema-invalid: {exc}"
            ) from exc
    selected = None
    if raw.get("selected_checkpoint") is not None:
        try:
            selected = SelectedCheckpoint.model_validate(raw["selected_checkpoint"])
        except ValidationError as exc:
            raise TrainingResultsContractError(
                f"selected_checkpoint is schema-invalid: {exc}"
            ) from exc
        curve = history.validation_objective if history is not None else None
        if not curve or any(value is None or not math.isfinite(value) for value in curve):
            raise TrainingResultsContractError(
                "selected_checkpoint requires finite validation history"
            )
        finite_curve = [float(value) for value in curve if value is not None]
        best_epoch = min(range(len(finite_curve)), key=lambda index: finite_curve[index]) + 1
        if selected.epoch != best_epoch or selected.validation_loss != curve[best_epoch - 1]:
            raise TrainingResultsContractError(
                "selected_checkpoint disagrees with validation history"
            )
    if budget is not None and (budget.checkpoint_selection == "best_validation_loss") != (
        selected is not None
    ):
        raise TrainingResultsContractError("training_budget and selected_checkpoint disagree")
    if expected_checkpoint_selection is not None and (
        expected_checkpoint_selection == "best_validation_loss"
    ) != (selected is not None):
        raise TrainingResultsContractError(
            "selected_checkpoint does not match requested selection policy"
        )
    target_standardization = None
    if raw.get("target_standardization") is not None:
        try:
            target_standardization = TargetStandardizationReceipt.model_validate(
                raw["target_standardization"]
            )
        except ValidationError as exc:
            raise TrainingResultsContractError(
                f"target_standardization is schema-invalid: {exc}"
            ) from exc
    if expected_target_standardization is not None and (
        expected_target_standardization != "none"
    ) != (target_standardization is not None):
        raise TrainingResultsContractError("target_standardization does not match requested policy")
    return TrainingResults(
        legacy_payload=legacy_payload,
        history=history,
        history_state="present" if history is not None else "absent",
        static_observations=_read_static_observations(raw),
        training_budget=budget,
        selected_checkpoint=selected,
        target_standardization=target_standardization,
    )


def _read_static_observations(raw: Mapping) -> dict[str, float]:
    """`R-OBS-1` — the trainer's optional static-observation payload.

    A MALFORMED payload is dropped, not raised on. The rule the whole family
    follows is that an observation which cannot be produced is an ABSENCE:
    letting a broken diagnostic value turn a successful training attempt into
    a contract failure would invert that, and would make declaring an
    observable riskier than not declaring one. The two SCIENTIFIC payloads —
    the legacy keys and ``training_history`` — keep their fail-closed
    treatment above, which is the distinction that matters.
    """
    payload = raw.get(STATIC_OBSERVATIONS_KEY)
    if not isinstance(payload, Mapping):
        return {}
    values: dict[str, float] = {}
    for name, value in payload.items():
        if (
            isinstance(name, str)
            and not isinstance(value, bool)
            and isinstance(value, (int, float))
        ):
            observed = float(value)
            if math.isfinite(observed):
                values[name] = observed
    return values
