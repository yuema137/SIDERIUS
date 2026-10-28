"""Per-attempt seeds derived from the run's locked seed (issue #983 S3b).

Contract: ``docs/agent-reference/mechanisms/seeding.md``.

Every tuner attempt sits at ``scope`` (the coordinates the caller owns: the
global ``iteration``, an authored ``node_id``, a fan-out ``branch``) plus the
tuner-owned ``round`` and ``attempt`` (``total_attempts``). Its sampling seeds
and the trainer's :class:`~core.training_seeds.SeedContext` are pure functions
of that position and the run seed; labels such as ``run_name`` never enter.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.seeding import MissingRunSeed, SeedCoordinates, derive_seed
from core.training_seeds import SeedContext


@dataclass(frozen=True, slots=True)
class AttemptSeeds:
    """The seeds one attempt executes with."""

    context: SeedContext
    train_sampling: int
    eval_sampling: int


def require_run_seed(run_seed: int | None) -> int:
    """Refuse a tuner run without a seed: only an entry boundary may generate one."""
    if run_seed is None:
        raise MissingRunSeed(
            "HyperparamTuningInput.run_seed is None: the tuner derives every attempt "
            "seed from the run seed its entry boundary resolved, and never generates one"
        )
    return run_seed


def derive_attempt_seeds(
    run_seed: int | None,
    scope: SeedCoordinates,
    *,
    round_index: int,
    attempt: int,
    align: bool,
) -> AttemptSeeds:
    """Seeds for attempt ``attempt`` of round ``round_index`` at ``scope``.

    ``align`` (``train_validation_align``) makes evaluation reuse the training
    selection seed, so both legs select the same segments.
    """
    seed = require_run_seed(run_seed)
    at = SeedCoordinates.model_validate(
        {**scope.model_dump(), "round": round_index, "attempt": attempt}
    )
    train = derive_seed(seed, "tuner.train_sampling", at)
    evaluation = train if align else derive_seed(seed, "tuner.eval_sampling", at)
    return AttemptSeeds(SeedContext(run_seed=seed, at=at), train, evaluation)
