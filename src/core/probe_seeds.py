"""Validation-probe seeds derived from the run seed (issue #983); torch-free.

Contract: ``docs/agent-reference/mechanisms/seeding.md`` "Validation probes".

A model probe (the implementor's self-check, the validator's instantiation
and gradient check, and a task-owned probe run by generated pytest) builds a
model and draws probe inputs. Its seeds are the ``validation.probe`` value of
the probe's :class:`~core.training_seeds.SeedContext`: the run seed plus the
coordinates ``(iteration, node_id or None, attempt)``. The context reaches a
probe child only through the environment variable :data:`PROBE_SEED_ENV`,
never through generated source, so generated test files keep their bytes.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from core.seeding import (
    MissingRunSeed,
    SeedCoordinates,
    derive_seed,
    format_seed_line,
    resolve_run_seed,
)
from core.training_seeds import NUMPY_SEED_MASK, ProcessSeedRecord, SeedContext

PROBE_SEED_ENV: Final = "SIDERIUS_PROBE_SEED_CONTEXT"


def probe_process_seeds(context: SeedContext) -> ProcessSeedRecord:
    """Python, NumPy (low 32 bits) and torch seeds of one probe, one purpose."""
    value = derive_seed(context.run_seed, "validation.probe", context.at)
    return ProcessSeedRecord(torch=value, numpy=value & NUMPY_SEED_MASK, python=value)


def probe_seed_env(context: SeedContext) -> dict[str, str]:
    """The environment entry that hands ``context`` to a probe child."""
    return {PROBE_SEED_ENV: context.model_dump_json()}


def require_probe_seed(
    context: SeedContext | None, environ: Mapping[str, str] | None = None
) -> SeedContext:
    """``context``, else the one inherited through ``environ``; never generated.

    Raises:
        MissingRunSeed: neither supplies a context.
    """
    if context is not None:
        return context
    inherited = None if environ is None else environ.get(PROBE_SEED_ENV)
    if inherited is None:
        raise MissingRunSeed(
            "a model probe requires its validation.probe SeedContext; seeds derive "
            "from run_seed and only an entry boundary may generate one"
        )
    return SeedContext.model_validate_json(inherited)


def probe_seed_context(
    run_seed: int | None, *, iteration: int, node_id: str | None, attempt: int
) -> SeedContext:
    """A probe's context at ``(iteration, node_id or None, attempt)``.

    ``attempt`` is the 1-based implementation number within the iteration, so
    a retried implementation gets its own draw. Raises :class:`MissingRunSeed`
    for ``None``.
    """
    if run_seed is None:
        raise MissingRunSeed("a model probe requires the run seed; none was supplied")
    return SeedContext(
        run_seed=run_seed,
        at=SeedCoordinates(iteration=iteration, node_id=node_id, attempt=attempt),
    )


def standalone_probe_seed(explicit: int | None) -> SeedContext:
    """The entry boundary of a standalone implementor/validator CLI run.

    Outside a workflow there is no run lock: the CLI's ``--run_seed`` is bound,
    or :func:`core.seeding.resolve_run_seed` generates one; the ``[seed]`` line
    is printed before any probe, and probes run at empty coordinates.
    """
    binding = resolve_run_seed(explicit)
    print(format_seed_line(binding.value, binding.source), flush=True)
    return SeedContext(run_seed=binding.value)
