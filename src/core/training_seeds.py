"""Torch-free trainer seed plan derived from one run seed.

Contract: ``docs/agent-reference/mechanisms/seeding.md``.

A :class:`SeedContext` is what a parent hands a trainer: the run seed plus the
coordinates of the training unit. :class:`TrainingSeedPlan` turns it into every
seed the trainer consumes, each one a ``siderius-seed/v1`` value of a separate
:data:`~core.seeding.SeedPurpose`. The module imports neither torch nor NumPy,
so a parent that must predict the trainer's epoch-0 selection can import it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.durable_io import publish_bytes_write_once
from core.seeding import (
    SEED_DERIVATION,
    MissingRunSeed,
    RunSeed,
    SeedCoordinates,
    SeedPurpose,
    derive_seed,
    format_seed_line,
    resolve_run_seed,
)

#: Legacy ``np.random.seed`` accepts only 32-bit seeds; the low 32 bits of a
#: SHA-256-derived value are uniform, so no second hash is needed.
NUMPY_SEED_MASK: Final = 2**32 - 1

#: ``supplied``: the parent passed a ``SeedContext``. ``generated``: the trainer
#: CLI is the entry boundary and drew a fresh run seed itself.
TrainerSeedSource = Literal["supplied", "generated"]


class SeedContext(BaseModel):
    """The run seed and the coordinates of one training unit."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    run_seed: RunSeed
    at: SeedCoordinates = Field(default_factory=SeedCoordinates)

    @model_validator(mode="after")
    def _epoch_is_trainer_owned(self) -> SeedContext:
        if self.at.epoch is not None:
            raise ValueError("SeedContext.at.epoch must be unset: the trainer owns the epoch")
        return self


class EpochSeeds(NamedTuple):
    """The three independent per-epoch streams."""

    subsample: int
    order: int
    shuffle: int


class ProcessSeedRecord(BaseModel):
    """The process-global seeds applied before model construction."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    torch: int
    numpy: int
    python: int


@dataclass(frozen=True, slots=True)
class TrainingSeedPlan:
    """Every trainer seed, as a pure function of a :class:`SeedContext`."""

    context: SeedContext

    def _derive(self, purpose: SeedPurpose, epoch: int | None = None) -> int:
        at = self.context.at
        if epoch is not None:
            at = SeedCoordinates.model_validate({**at.model_dump(), "epoch": epoch})
        return derive_seed(self.context.run_seed, purpose, at)

    @property
    def init_torch(self) -> int:
        return self._derive("trainer.init")

    @property
    def init_numpy32(self) -> int:
        return self._derive("trainer.init_numpy") & NUMPY_SEED_MASK

    @property
    def init_python(self) -> int:
        return self._derive("trainer.init_python")

    def process_seeds(self) -> ProcessSeedRecord:
        return ProcessSeedRecord(
            torch=self.init_torch, numpy=self.init_numpy32, python=self.init_python
        )

    def epoch(self, k: int, *, freeze_subsample: bool = False) -> EpochSeeds:
        """Seeds for epoch ``k``; ``freeze_subsample`` pins only the subsample to epoch 0."""
        subsample_epoch = 0 if freeze_subsample else k
        return EpochSeeds(
            subsample=self._derive("trainer.epoch_subsample", subsample_epoch),
            order=self._derive("trainer.epoch_order", k),
            shuffle=self._derive("trainer.epoch_shuffle", k),
        )


def publish_seed_context(path: str, context: SeedContext) -> None:
    """Write the trainer handoff once; a retry of the same attempt must match it."""
    payload = context.model_dump_json().encode()
    try:
        publish_bytes_write_once(path, payload)
    except FileExistsError:
        with open(path, "rb") as existing:
            if existing.read() != payload:
                raise ValueError(f"{path} already holds a different SeedContext") from None


def require_seed_plan(plan: TrainingSeedPlan | None) -> TrainingSeedPlan:
    """Return ``plan``, refusing ``None`` with :class:`MissingRunSeed`."""
    if plan is None:
        raise MissingRunSeed(
            "training requires a TrainingSeedPlan; seeds derive from run_seed "
            "and only an entry boundary may generate one"
        )
    return plan


def resolve_trainer_seed_plan(
    context: SeedContext | None,
) -> tuple[TrainingSeedPlan, TrainerSeedSource]:
    """The trainer CLI entry boundary: use the supplied context or generate one.

    Inside a run the tuner always supplies a context; generation serves only a
    direct trainer invocation.
    """
    if context is not None:
        return TrainingSeedPlan(context), "supplied"
    return TrainingSeedPlan(SeedContext(run_seed=resolve_run_seed(None).value)), "generated"


def seed_log_line(plan: TrainingSeedPlan, source: TrainerSeedSource) -> str:
    """The stdout line the trainer prints before any training work starts."""
    return format_seed_line(plan.context.run_seed, source)


def trainer_seed_record(plan: TrainingSeedPlan, source: TrainerSeedSource) -> dict[str, object]:
    """The seed fields a trainer adds to its results JSON (never LLM-visible)."""
    return {
        "seed_context": plan.context.model_dump(mode="json"),
        "seed_derivation": SEED_DERIVATION,
        "seed_source": source,
        "process_seeds": plan.process_seeds().model_dump(mode="json"),
    }
