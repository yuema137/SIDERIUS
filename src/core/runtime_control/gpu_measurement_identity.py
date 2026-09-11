"""Two identities for one measurement, and the check that they agree.

V20 PR C2 / D-C2-7, approved 2026-08-03.

A pre-phase measurement has two identity problems and they are not the same
problem:

* the **parent** must be able to prove that the result it got back answers
  the request it sent -- not a stale worker, not a different candidate, not
  a misrouted result file;
* the **requirement** must be identified by what was *actually built*, so a
  measurement can later be compared with anything else describing the same
  realized candidate.

One hash cannot do both. C1's `candidate_config_hash` needs REALIZED values
-- `param_count` from the instantiated module and `precision` from its
parameter dtype (`calibration_context.py:99-105`) -- and the parent cannot
have them: PR A's isolation rule is that *"the parent must not instantiate
the candidate model -- once the model is in the parent, a child limit is
already too late."*

So the roles are split:

```text
planned identity   -> binds the request the parent issued.
                      Request-binding and audit evidence. NEVER capacity
                      authority.
realized identity  -> identifies what the worker actually constructed and
                      measured. THE authoritative measurement identity.
```

**The realized hash uses C1's builder, unchanged.**
`build_calibration_context` + `candidate_config_hash` are the one canonical
definition of "same realized configuration", and this module calls them
rather than restating them. That is what makes a C2 requirement and a C1
duration observation comparable instead of merely similarly shaped -- the
D-4 divergence, avoided rather than repeated.

**The planned hash is deliberately a different key set**, over only the
fields the parent can know before construction. It is named differently, it
means something different, and it is never offered as the measurement's
identity.

**A mismatch fails closed.** It is an integrity failure of the measurement
system -- never candidate blame, never GPU capacity evidence, never a
scientific result.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

#: Why a planned request and a realized measurement do not describe the same
#: candidate. Each is separately actionable -- a nonce mismatch means a
#: stale or misrouted result, a config mismatch means the worker built
#: something other than what was asked for.
IdentityMismatch = Literal[
    "inference_batch_size_mismatch",
    "inference_batch_size_absent",
    "request_id_mismatch",
    "realized_identity_absent",
    "model_type_mismatch",
    "model_family_mismatch",
    "optimizer_type_mismatch",
    "seg_size_mismatch",
    "batch_size_mismatch",
    "realized_hash_missing",
]

#: The fields both sides can state. `param_count` and `precision` are
#: deliberately absent: only the worker can know them, and demanding that
#: the parent predict them is exactly what would weaken the realized
#: identity to fit the parent's blindness.
#:
#: `batch_size` here is the TRAINING batch. It is not the inference
#: workload -- see `INFERENCE_COMPARABLE_FIELDS`.
COMPARABLE_FIELDS: tuple[str, ...] = (
    "model_type",
    "model_family",
    "optimizer_type",
    "seg_size",
    "batch_size",
)

#: Additionally compared for an INFERENCE-phase measurement.
#:
#: Formal inference runs at `inference_batch_for(model_type)` -- 25 for
#: punet -- while training runs at `train_config["batch_size"]`. Gate
#: attempt 6's characterization measured the inference phase at the
#: TRAINING batch of 1 and reported 1050 MiB where the real phase held
#: 3642 MiB, a 3.47x under-read that would have been handed to admission.
#:
#: Comparison is phase-aware on purpose: an inference field must not
#: invalidate an otherwise valid training measurement, and the training
#: identity -- validated at 1474 vs 1476 MiB -- is unchanged.
INFERENCE_COMPARABLE_FIELDS: tuple[str, ...] = ("inference_batch_size",)


class PlannedCandidateIdentity(BaseModel):
    """What the parent asserts it is asking to have measured.

    Every field here is knowable from the configs the parent already holds,
    without constructing anything.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_type: str = Field(min_length=1)
    model_family: str = Field(min_length=1)
    optimizer_type: str = Field(min_length=1)
    seg_size: int = Field(gt=0)
    batch_size: int = Field(gt=0)
    #: `cfg:<12 hex>` over the fields above plus the production loop's
    #: runtime flags. Shaped like C1's hash and NOT the same hash -- a
    #: different key set, a different name, and never capacity authority.
    planned_config_hash: str = Field(min_length=1)
    #: The batch the INFERENCE phase runs at, resolved by
    #: `resolve_inference_batch` exactly as `execute_inference` resolves
    #: it: the probe-derived hint when one exists (the agent path), else
    #: the `inference_batch_for` table (V21 PR G G3 — previously this
    #: recorded the table value unconditionally while runtime preferred
    #: the hint). `None` for a training-phase measurement, where it is
    #: not part of the workload.
    inference_batch_size: int | None = Field(default=None, gt=0)
    #: Present only for an inference measurement: the realized/planned hash
    #: bound to the inference batch. Kept SEPARATE from the config hash
    #: above so C1's definition of "same realized configuration" -- which
    #: describes a training configuration -- is not redefined.
    inference_workload_hash: str | None = None


class RealizedCandidateIdentity(BaseModel):
    """What the worker actually constructed, recomputed from the module.

    THE authoritative measurement identity. `parameter_count` and
    `precision` come from the instantiated model, never from the LLM's
    estimate (F-1b).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_type: str = Field(min_length=1)
    model_family: str = Field(min_length=1)
    optimizer_type: str = Field(min_length=1)
    seg_size: int = Field(gt=0)
    batch_size: int = Field(gt=0)
    precision: str = Field(min_length=1)
    parameter_count: int = Field(gt=0)
    trainable_parameter_count: int = Field(ge=0)
    #: C1's `candidate_config_hash`, from C1's builder. The one definition
    #: of "same realized configuration".
    realized_config_hash: str = Field(min_length=1)
    #: The batch the INFERENCE phase runs at, resolved by
    #: `resolve_inference_batch` exactly as `execute_inference` resolves
    #: it: the probe-derived hint when one exists, else the
    #: `inference_batch_for` table (V21 PR G G3). `None` for a
    #: training-phase measurement, where it is not part of the workload.
    inference_batch_size: int | None = Field(default=None, gt=0)
    #: Present only for an inference measurement: the realized/planned hash
    #: bound to the inference batch. Kept SEPARATE from the config hash
    #: above so C1's definition of "same realized configuration" -- which
    #: describes a training configuration -- is not redefined.
    inference_workload_hash: str | None = None


def resolve_inference_batch(model_type: str, explicit: int | None = None) -> int:
    """The batch formal inference will actually run at.

    Mirrors `execute_inference`'s own resolution (`sandbox_executor.py:1543`):
    a non-None probe-derived batch is AUTHORITATIVE; the registry table is
    the fallback only when no hint exists (baselines, legacy callers, a
    measurement requested before any preflight ran). V21 PR G G3: the
    tuner's pre-phase site passes `active_params["inference_batch"]` (the
    current attempt's probed batch), so the recorded planned-identity
    payload states the batch production would really run — previously it
    recorded the table value while runtime used the probe, a latent trap
    for a future inference-phase measurement caller (a wrong-batch
    inference measurement once produced a 3.47x under-read).

    Deliberately NOT an operator CLI value: a production-resolved
    constant, not a Gate knob. An invalid explicit value is rejected
    loudly — never silently clamped or substituted (fail-closed).
    """
    if explicit is not None:
        # bool is an int subclass; a True/False batch is a caller bug.
        if isinstance(explicit, bool) or not isinstance(explicit, int) or explicit <= 0:
            raise ValueError(f"explicit inference batch must be a positive int; got {explicit!r}.")
        return explicit
    from core.inference_defaults import inference_batch_for

    return int(inference_batch_for(model_type))


def build_planned_identity(
    *,
    model_type: str,
    model_config: dict[str, Any],
    train_config: dict[str, Any],
    inference_batch_size: int | None = None,
) -> PlannedCandidateIdentity:
    """The parent's identity for a candidate it has not built.

    `model_family` is `model_type`, matching production
    (`evaluate_time_skill/wrapper.py:499`). The defaults for `seg_size` and
    `batch_size` are the same ones the measurement worker will apply, so
    the two sides cannot disagree because one of them filled a blank
    differently.
    """
    from agent.skills.training_skill.estimator import resolve_model_field
    from core.runtime_control.calibration_context import training_loop_runtime_flags
    from core.runtime_control.identity import config_hash12

    # C12-P / B11. `seg_size` is HASHED into `planned_config_hash`, so a
    # literal fallback does not merely mis-size a batch — it writes a durable
    # false provenance: two candidates that will train at different sizes
    # collide under one calibration identity, and the recorded `seg_size` names
    # a workload nobody ran. Resolved through the one authority that reproduces
    # what the model will be constructed with; unchanged whenever the key is
    # present, which is every production plan.
    seg_size = resolve_model_field(
        model_type, model_config, "segmentation_size", safety_margin=40_000
    )
    batch_size = int(train_config.get("batch_size", 1))
    optimizer_type = str(train_config.get("optimizer_type", "adamw"))
    payload = {
        "model_type": model_type,
        "model_family": model_type,
        "optimizer_type": optimizer_type,
        "seg_size": seg_size,
        "batch_size": batch_size,
        "runtime_flags": training_loop_runtime_flags(),
    }
    planned_hash = f"cfg:{config_hash12(payload)}"
    return PlannedCandidateIdentity(
        model_type=model_type,
        model_family=model_type,
        optimizer_type=optimizer_type,
        seg_size=seg_size,
        batch_size=batch_size,
        planned_config_hash=planned_hash,
        inference_batch_size=inference_batch_size,
        inference_workload_hash=_inference_workload_hash(planned_hash, inference_batch_size),
    )


def _inference_workload_hash(base_hash: str, inference_batch_size: int | None) -> str | None:
    """Bind a config hash to the inference batch, or `None` for training.

    Separate from the config hash rather than folded into it: C1's hash
    describes a TRAINING configuration, and redefining it would break the
    cross-subsystem comparability D-C2-7 exists to preserve. This is the
    inference workload's own identity, and it changes when the batch does --
    which is what stops a batch-1 measurement answering for batch 25.
    """
    if inference_batch_size is None:
        return None
    from core.runtime_control.identity import config_hash12

    return f"inf:{config_hash12({'base': base_hash, 'inference_batch_size': inference_batch_size})}"


def build_realized_identity(
    *,
    model_type: str,
    optimizer_type: str,
    seg_size: int,
    batch_size: int,
    precision: str,
    parameter_count: int,
    trainable_parameter_count: int,
    inference_batch_size: int | None = None,
) -> RealizedCandidateIdentity:
    """The worker's identity for the candidate it just built.

    The hash comes from C1's `build_calibration_context` +
    `candidate_config_hash` -- called, not reimplemented. A reader that
    built the mapping correctly but hashed it differently would still match
    nothing, and the failure would look identical.
    """
    from core.runtime_control.calibration_context import (
        CalibrationContextInputs,
        build_calibration_context,
        candidate_config_hash,
    )

    context = build_calibration_context(
        CalibrationContextInputs(
            precision=precision,
            optimizer_type=optimizer_type,
            model_family=model_type,
            param_count=trainable_parameter_count or parameter_count,
            seg_size=seg_size,
            batch_size=batch_size,
        )
    )
    return RealizedCandidateIdentity(
        model_type=model_type,
        model_family=model_type,
        optimizer_type=optimizer_type,
        seg_size=seg_size,
        batch_size=batch_size,
        precision=precision,
        parameter_count=parameter_count,
        trainable_parameter_count=trainable_parameter_count,
        realized_config_hash=candidate_config_hash(context),
        inference_batch_size=inference_batch_size,
        inference_workload_hash=_inference_workload_hash(
            candidate_config_hash(context), inference_batch_size
        ),
    )


def compare_identities(
    planned: PlannedCandidateIdentity,
    realized: RealizedCandidateIdentity | None,
    *,
    requested_id: str,
    reported_id: str | None,
    phase: str = "training",
) -> IdentityMismatch | None:
    """Whether the result answers the request. `None` means it does.

    Ordered most-fundamental first: a nonce mismatch means this is not the
    result at all, and reporting a field difference in that case would
    describe the wrong pair of objects.

    Returns a *value*. A mismatch is an expected outcome of checking, not
    an error in checking.
    """
    if reported_id != requested_id:
        return "request_id_mismatch"
    if realized is None:
        return "realized_identity_absent"
    if not realized.realized_config_hash:
        return "realized_hash_missing"
    for field in COMPARABLE_FIELDS:
        if getattr(planned, field) != getattr(realized, field):
            return f"{field}_mismatch"  # type: ignore[return-value]
    if phase == "inference":
        # Phase-aware on purpose. A training measurement must not be
        # invalidated by an inference field, and an inference measurement
        # must not be authorised by the training batch -- which is exactly
        # how attempt 6 reported 1050 MiB for a 3642 MiB phase.
        if planned.inference_batch_size is None or realized.inference_batch_size is None:
            return "inference_batch_size_absent"
        for field in INFERENCE_COMPARABLE_FIELDS:
            if getattr(planned, field) != getattr(realized, field):
                return f"{field}_mismatch"  # type: ignore[return-value]
    return None
