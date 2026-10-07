"""Validated observations and arithmetic results for static preflight providers.

These contracts describe structural estimates, not live device allocations.
Execution owns candidate order, caps, admission and measurement separately.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

ByteCount = Annotated[int, Field(strict=True, ge=0)]
Phase = Literal["training", "inference"]


class RegisteredStateInventory(BaseModel):
    """Projected state allocation, or an explicit reason it is unavailable.

    Parameters are counted by object identity; buffer registrations are counted
    per slot in unique module objects. Distinct objects sharing host storage
    may separate during device conversion. Counts describe those objects/slots,
    not scalar elements. This is not a proof of device aliasing or peak usage.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    status: Literal["available", "unavailable"]
    parameter_bytes: ByteCount | None = None
    trainable_parameter_bytes: ByteCount | None = None
    buffer_bytes: ByteCount | None = None
    parameter_count: ByteCount | None = None
    buffer_count: ByteCount | None = None
    reason: str | None = Field(default=None, min_length=1)
    accounting: Literal["parameter_objects_and_buffer_slots_v1"] = (
        "parameter_objects_and_buffer_slots_v1"
    )

    @model_validator(mode="after")
    def consistent_availability(self) -> RegisteredStateInventory:
        counts = (
            self.parameter_bytes,
            self.trainable_parameter_bytes,
            self.buffer_bytes,
            self.parameter_count,
            self.buffer_count,
        )
        if self.status == "unavailable":
            if self.reason is None or any(value is not None for value in counts):
                raise ValueError("Unavailable inventory requires a reason and no byte/count values")
        elif self.reason is not None or any(value is None for value in counts):
            raise ValueError("Available inventory requires all byte/count values and no reason")
        elif (
            self.trainable_parameter_bytes is not None
            and self.parameter_bytes is not None
            and self.trainable_parameter_bytes > self.parameter_bytes
        ):
            raise ValueError("Trainable parameter bytes cannot exceed all parameter bytes")
        return self


class PhaseObservations(BaseModel):
    """Raw forward observations plus independent registered-state accounting.

    Keep the leaf-call fields unchanged: an explicit external estimator may
    qualify a historical formula using them. Unavailable inventory does not
    erase those observations. Native estimation requires available inventory.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    phase: Phase
    batch_size: Annotated[int, Field(strict=True, gt=0)]
    leaf_parameter_bytes: ByteCount
    leaf_output_bytes_sum: ByteCount
    leaf_output_bytes_max: ByteCount
    input_bytes: ByteCount
    output_bytes: ByteCount
    saved_tensor_bytes: ByteCount | None = None
    model_state: RegisteredStateInventory
    loss_state: RegisteredStateInventory | None = None
    optimizer_type: Literal["adam", "adamw", "sgd"] | None = None
    training_config: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def complete_phase(self) -> PhaseObservations:
        if self.phase == "training" and (
            self.saved_tensor_bytes is None
            or self.loss_state is None
            or self.optimizer_type is None
        ):
            raise ValueError("Training observations require tape, loss inventory and optimizer")
        if self.leaf_output_bytes_max > self.leaf_output_bytes_sum:
            raise ValueError("Maximum leaf output bytes cannot exceed their sum")
        return self


class PhaseEstimate(BaseModel):
    """Provider arithmetic only; no authority to select batches or admit work."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    phase: Phase
    admission_bytes: ByteCount
    diagnostic_bytes: ByteCount
    estimator: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")
    breakdown: dict[str, ByteCount]

    @model_validator(mode="after")
    def diagnostic_sum(self) -> PhaseEstimate:
        if sum(self.breakdown.values()) != self.diagnostic_bytes:
            raise ValueError("Diagnostic breakdown must sum to diagnostic_bytes")
        return self
