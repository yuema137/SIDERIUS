"""Run seed owner: the typed run seed, its generation and ``siderius-seed/v1``.

Contract: ``docs/agent-reference/mechanisms/seeding.md``.

A run has exactly one ``run_seed``, an integer in ``[0, 2**53 - 1]`` (exact
in a JavaScript number). The operator may set it; otherwise
:func:`generate_run_seed` draws one from the operating system CSPRNG. Every
stochastic unit seed is :func:`derive_seed` of the run seed, a closed
:data:`SeedPurpose` and :class:`SeedCoordinates`. The derivation is a SHA-256
digest of a canonical JSON array, so it is identical in every process and
never depends on Python ``hash()``, wall time, PID or run labels.

This module is pure apart from :func:`generate_run_seed`. It imports neither
torch nor NumPy.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from typing import Annotated, Final, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

SEED_DERIVATION: Final = "siderius-seed/v1"
RUN_SEED_MAX: Final = 2**53 - 1
DERIVED_SEED_BITS: Final = 63

RunSeed = Annotated[int, Field(ge=0, le=RUN_SEED_MAX, strict=True)]
SeedSource = Literal["operator", "generated"]
SeedPurpose = Literal[
    "tuner.train_sampling",
    "tuner.eval_sampling",
    "trainer.unit",
    "trainer.init",
    "trainer.epoch_subsample",
    "trainer.epoch_order",
    "trainer.epoch_shuffle",
    "data_analysis.sampling",
    "data_analysis.program",
    "validation.probe",
]

_RUN_SEED: Final = TypeAdapter(RunSeed)
_PURPOSES: Final = frozenset(get_args(SeedPurpose))

CanonicalAtom = str | int | None


class RunSeedBinding(BaseModel):
    """The resolved seed of one run, as recorded before execution starts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: RunSeed
    source: SeedSource
    derivation: Literal["siderius-seed/v1"] = SEED_DERIVATION


class SeedCoordinates(BaseModel):
    """Where in a run a stochastic unit sits. Absent coordinates stay ``None``.

    Labels such as ``run_name``, ``exp_id`` or workspace paths are not
    coordinates, so renaming a run never changes numerics.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    iteration: Annotated[int, Field(ge=1)] | None = None
    node_id: Annotated[str, Field(min_length=1)] | None = None
    branch: Annotated[int, Field(ge=0)] | None = None
    round: Annotated[int, Field(ge=1)] | None = None
    attempt: Annotated[int, Field(ge=1)] | None = None
    epoch: Annotated[int, Field(ge=0)] | None = None


def generate_run_seed() -> int:
    """Draw a fresh run seed uniformly from ``[0, 2**53 - 1]`` with ``secrets``."""
    return secrets.randbelow(RUN_SEED_MAX + 1)


def resolve_run_seed(explicit: int | None) -> RunSeedBinding:
    """Bind an explicit operator seed, or generate one when none is given.

    Raises ``pydantic.ValidationError`` for an out-of-range or non-``int``
    explicit value (``bool`` included).
    """
    if explicit is None:
        return RunSeedBinding(value=generate_run_seed(), source="generated")
    return RunSeedBinding(value=explicit, source="operator")


def canonical_json_bytes(atoms: tuple[CanonicalAtom, ...]) -> bytes:
    """Encode ``atoms`` as a compact ASCII JSON array.

    JSON keeps element boundaries and types: ``("a", "bc")`` differs from
    ``("ab", "c")``, ``1`` from ``"1"`` and ``None`` (``null``) from ``0``.
    """
    for atom in atoms:
        if isinstance(atom, bool) or not isinstance(atom, str | int | None):
            raise TypeError(f"canonical seed atom must be str, int or None, got {atom!r}")
    return json.dumps(list(atoms), separators=(",", ":"), ensure_ascii=True).encode("ascii")


def derive_seed(run_seed: int, purpose: SeedPurpose, at: SeedCoordinates) -> int:
    """Return the 63-bit ``siderius-seed/v1`` seed for one stochastic unit.

    The value is the first eight big-endian bytes of
    ``sha256(canonical_json([derivation, run_seed, purpose, iteration,
    node_id, branch, round, attempt, epoch]))`` masked to 63 bits.
    """
    seed = _RUN_SEED.validate_python(run_seed)
    if purpose not in _PURPOSES:
        raise ValueError(f"unknown seed purpose {purpose!r}; expected one of {sorted(_PURPOSES)}")
    payload = canonical_json_bytes(
        (
            SEED_DERIVATION,
            seed,
            purpose,
            at.iteration,
            at.node_id,
            at.branch,
            at.round,
            at.attempt,
            at.epoch,
        )
    )
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], "big") & ((1 << DERIVED_SEED_BITS) - 1)
