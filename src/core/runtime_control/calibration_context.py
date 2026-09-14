"""The one definition of a candidate's calibration identity context.

V20 PR C1 / C-C5b.

WHY THIS IS SHARED CODE AND NOT A CONVENTION. `candidate_config_hash` is
`config_hash12` over this whole dict, so the write side (the training engine,
which records what it ran) and the read side (the pre-launch time gate, which
asks what was recorded) must produce a BYTE-IDENTICAL mapping. If they drift
by one key or one expression, every lookup misses -- and a miss is
indistinguishable from "no calibration recorded yet". The subsystem would
look wired, report no errors, and never match anything.

That is not hypothetical. Before this module existed the two sides already
disagreed on the parameter count:

    engine      sum(p.numel() for p in model.parameters() if p.requires_grad)
    pre-flight  sum(p.numel() for p in model.parameters())

Identical for a fully-trainable model, silently different for any model with
frozen parameters. Nobody would have seen it: calibration would simply never
apply to those candidates. `trainable_param_count` now serves both.

WHAT MAY LIVE IN HERE. Only values that are (a) semantically part of the
candidate configuration and (b) deterministically derivable BOTH before
launch and inside the training loop. `precision` qualifies because the
pre-flight already instantiates the real model to count parameters, so it can
read the same dtype from the same expression. `runtime_flags` qualify because
they are literal constants of the training loop rather than measured facts.

WHAT MAY NOT. Anything realized only during execution -- a measured duration,
an observed peak, an achieved throughput. Those are evidence ABOUT a
candidate, not part of its identity, and folding one in here would make the
identity unknowable before launch and so unusable by the gate that needs it.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def training_loop_runtime_flags() -> dict[str, Any]:
    """Literal facts of the production training loop.

    Constants rather than measurements: the loop uses no worker processes,
    no pinned memory, no gradient accumulation and no `torch.compile`.
    Flipping any of them changes throughput materially, so they belong in
    the identity -- and because they are constants, the pre-launch side can
    state them exactly.

    If the loop ever gains one of these, changing it HERE updates both the
    recorded identity and the pre-launch lookup in one edit. That is the
    entire point of the shared definition.
    """
    return {
        "num_workers": 0,
        "pin_memory": False,
        "grad_accumulation": False,
        "torch_compile": False,
    }


def trainable_param_count(model: Any) -> int:
    """Trainable parameters, counted identically on both sides.

    `requires_grad` filtered: a frozen parameter costs no backward work, so
    two models differing only in what is frozen are genuinely different
    workloads. The filter is not the important part -- agreeing on it is.
    """
    return sum(p.numel() for p in model.parameters() if p.requires_grad)


def model_precision(model: Any) -> str:
    """The realized parameter dtype, as the recorded identity spells it.

    `str(torch.float32)` is `"torch.float32"`; the recorded form drops the
    prefix. Both sides call this rather than repeating the `.replace(...)`,
    because a differently-spelled dtype is a silently different bucket.

    Reads the FIRST parameter, matching what the engine records. A model
    with mixed dtypes is not described by this field -- it would need its
    own identity dimension, which is a schema decision, not a local fix.
    """
    return str(next(model.parameters()).dtype).replace("torch.", "")


class CalibrationContextInputs(BaseModel):
    """The candidate facts that make up its calibration identity.

    A typed object rather than six positional arguments so that adding a
    dimension is a schema change both sides see, instead of a call-site
    change one side can forget.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Realized parameter dtype, from `model_precision`.
    precision: str = Field(min_length=1)
    optimizer_type: str = Field(min_length=1)
    model_family: str = Field(min_length=1)
    #: Trainable parameters, from `trainable_param_count`.
    param_count: int = Field(gt=0)
    seg_size: int | None = Field(default=None, gt=0)
    batch_size: int = Field(gt=0)
    segmentation_applicability: Literal["temporal", "not_applicable"] = "temporal"

    @model_validator(mode="after")
    def _segmentation_shape_matches_applicability(self) -> CalibrationContextInputs:
        if self.segmentation_applicability == "temporal" and self.seg_size is None:
            raise ValueError("temporal calibration context requires seg_size")
        if self.segmentation_applicability == "not_applicable" and self.seg_size is not None:
            raise ValueError("non-temporal calibration context must omit seg_size")
        return self


def build_calibration_context(inputs: CalibrationContextInputs) -> dict[str, Any]:
    """The canonical mapping both sides hash.

    Key order is irrelevant to `config_hash12` (it sorts), but the KEY SET
    and the VALUE SPELLING are not. This function is the only definition of
    both.
    """
    context = {
        "precision": inputs.precision,
        "optimizer_type": inputs.optimizer_type,
        "model_family": inputs.model_family,
        "param_count": inputs.param_count,
        "batch_size": inputs.batch_size,
        "runtime_flags": training_loop_runtime_flags(),
    }
    if inputs.segmentation_applicability == "temporal":
        context["seg_size"] = inputs.seg_size
    else:
        context["segmentation_applicability"] = inputs.segmentation_applicability
    return context


def candidate_config_hash(context: dict[str, Any]) -> str:
    """`MeasurementIdentity.candidate_config_hash` for a calibration context.

    THE one definition. It lives beside `build_calibration_context` because
    the mapping and its hash are a single responsibility: a reader that built
    the mapping correctly but hashed it differently would still match
    nothing, and the failure would look identical.

    Takes the context MAPPING rather than the typed inputs, because the write
    path reads it back from a persisted `RuntimeObservation.calibration_
    context` while the read path builds it from a live candidate. Both must
    reach this function, and neither may reimplement it.
    """
    from core.runtime_control.identity import config_hash12

    return f"cfg:{config_hash12(context)}"
