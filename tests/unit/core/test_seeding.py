"""``core.seeding``: run-seed range, generation and ``siderius-seed/v1``.

Each test names the defect it catches; see
``docs/agent-reference/mechanisms/seeding.md``.
"""

from __future__ import annotations

import builtins
import hashlib
import os
import subprocess
import sys

import pytest
from pydantic import ValidationError

from core import seeding
from core.seeding import (
    RUN_SEED_MAX,
    RunSeedBinding,
    SeedCoordinates,
    canonical_json_bytes,
    derive_seed,
    generate_run_seed,
    resolve_run_seed,
)

C = SeedCoordinates

# (run_seed, purpose, coordinates, literal expected seed). The literals were
# computed once and are pinned: any change to the tuple order, the JSON
# encoding, the digest slice or the mask changes at least one of them.
# Design revision 3 removed the ``trainer.unit`` purpose, so its vector
# (0, "trainer.unit", C()) was replaced by the two purposes it added; the
# remaining v1 vectors are unchanged because the encoding is unchanged.
KNOWN_ANSWERS = [
    (0, "trainer.init_python", C(), 162581914680118109),
    (
        0,
        "trainer.init_numpy",
        C(iteration=1, attempt=1, epoch=0),
        850440478084799134,
    ),
    (
        1,
        "tuner.train_sampling",
        C(iteration=1, node_id="tune", attempt=1),
        4553676795526718866,
    ),
    (
        RUN_SEED_MAX,
        "trainer.epoch_subsample",
        C(iteration=3, node_id="tune", branch=0, round=2, attempt=7, epoch=0),
        3168058167598676115,
    ),
    (123456789, "data_analysis.sampling", C(node_id="analysis"), 8511396224963113650),
    (42, "validation.probe", C(epoch=10**12), 356388341707149431),
]


def _independent_v1(run_seed: int, purpose: str, at: SeedCoordinates) -> int:
    """The documented formula, written out without the module's encoder."""
    parts = [
        '"siderius-seed/v1"',
        str(run_seed),
        f'"{purpose}"',
        *(
            "null" if v is None else (f'"{v}"' if isinstance(v, str) else str(v))
            for v in (at.iteration, at.node_id, at.branch, at.round, at.attempt, at.epoch)
        ),
    ]
    digest = hashlib.sha256(("[" + ",".join(parts) + "]").encode("ascii")).digest()
    return int.from_bytes(digest[:8], "big") & (2**63 - 1)


@pytest.mark.parametrize(("run_seed", "purpose", "at", "expected"), KNOWN_ANSWERS)
def test_known_answer_vectors_pin_the_v1_encoding(run_seed, purpose, at, expected):
    """Defect: a silent change to the v1 byte encoding (field order, JSON
    separators, digest slice, mask) re-seeds every archived coordinate.
    Both the literal and the independent formula must agree."""
    assert derive_seed(run_seed, purpose, at) == expected
    assert _independent_v1(run_seed, purpose, at) == expected


def test_derivation_is_identical_across_hash_randomised_processes():
    """Defect: ``hash()``, set/dict iteration order or any per-process state
    entering the derivation makes seeds differ between interpreter launches."""
    script = (
        "from core.seeding import SeedCoordinates as C, derive_seed\n"
        "print(derive_seed(7, 'trainer.init', C(iteration=2, node_id='n', attempt=3)))\n"
    )
    outputs = set()
    for hash_seed in ("1", "2"):
        env = {**os.environ, "PYTHONHASHSEED": hash_seed}
        proc = subprocess.run(
            [sys.executable, "-c", script], env=env, capture_output=True, text=True, check=True
        )
        outputs.add(proc.stdout.strip())
    outputs.add(str(derive_seed(7, "trainer.init", C(iteration=2, node_id="n", attempt=3))))
    assert len(outputs) == 1, outputs


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (("a", "bc"), ("ab", "c")),  # string boundary (legacy f"{a}_{b}" shape)
        ((1,), ("1",)),  # int vs str
        ((None,), (0,)),  # absent vs zero
        ((None, 1), (1, None)),  # slot position
    ],
)
def test_canonical_encoding_keeps_boundaries_and_types(left, right):
    """Defect: a joined or untyped encoding maps two different tuples to the
    same bytes, so two stochastic units would share a seed."""
    assert canonical_json_bytes(left) != canonical_json_bytes(right)


@pytest.mark.parametrize("bad", [True, 1.0, b"x", ("nested",)])
def test_canonical_encoding_refuses_non_atoms(bad):
    """Defect: ``True`` would encode as ``true`` and floats as ``1.0``, opening
    encodings that the v1 contract does not define."""
    with pytest.raises(TypeError):
        canonical_json_bytes((bad,))


def test_each_coordinate_and_the_purpose_change_the_seed():
    """Defect: a coordinate dropped from the tuple, or ``None`` collapsed to
    ``0``, makes distinct units (epochs, attempts, branches ...) share a seed."""
    base = C(iteration=1, node_id="tune", branch=0, round=1, attempt=1, epoch=0)
    variants = [
        base,
        base.model_copy(update={"iteration": 2}),
        base.model_copy(update={"node_id": "tune2"}),
        base.model_copy(update={"branch": 1}),
        base.model_copy(update={"branch": None}),
        base.model_copy(update={"round": 2}),
        base.model_copy(update={"attempt": 2}),
        base.model_copy(update={"epoch": 1}),
        base.model_copy(update={"epoch": None}),
    ]
    seeds = [derive_seed(5, "trainer.init", v) for v in variants]
    seeds.append(derive_seed(5, "trainer.epoch_order", base))
    seeds.append(derive_seed(6, "trainer.init", base))
    assert len(set(seeds)) == len(seeds)


def test_equal_values_in_different_slots_give_different_seeds():
    """Defect: coordinates hashed as an unordered or name-less bag would let
    iteration=1 collide with round=1 or attempt=1."""
    slots = [C(iteration=1), C(round=1), C(attempt=1)]
    assert len({derive_seed(9, "trainer.init", s) for s in slots}) == len(slots)


@pytest.mark.parametrize("value", [0, RUN_SEED_MAX])
def test_run_seed_bounds_are_inclusive(value):
    """Defect: an off-by-one bound rejects a seed the console can display."""
    assert resolve_run_seed(value) == RunSeedBinding(value=value, source="operator")
    assert 0 <= derive_seed(value, "trainer.init", C()) < 2**63


@pytest.mark.parametrize("value", [-1, RUN_SEED_MAX + 1, True, 3.0, "7"])
def test_out_of_range_or_coerced_run_seeds_fail_closed(value):
    """Defect: a seed above 2**53-1 loses precision in the browser, and a lax
    ``"7"``/``True``/``3.0`` would be silently coerced into a different run."""
    with pytest.raises(ValidationError):
        resolve_run_seed(value)
    with pytest.raises(ValidationError):
        derive_seed(value, "trainer.init", C())


@pytest.mark.parametrize("purpose", ["trainer.whatever", "trainer.unit"])
def test_unknown_or_retired_purpose_is_refused(purpose):
    """Defect: a free-form purpose string would create an unreviewed stream,
    and the retired ``trainer.unit`` would reintroduce a 63-bit intermediate
    root that later seeds are derived from instead of the run seed."""
    with pytest.raises(ValueError, match="unknown seed purpose"):
        derive_seed(1, purpose, C())


def test_generation_spans_the_full_range_without_python_hash(monkeypatch):
    """Defect: generation that uses ``hash()``/time, or draws from a range
    other than ``[0, 2**53 - 1]``, yields unrecordable or reused seeds."""

    def _no_hash(*_args):
        raise AssertionError("Python hash() must not be used for seeds")

    monkeypatch.setattr(builtins, "hash", _no_hash)
    for _ in range(64):
        assert 0 <= generate_run_seed() <= RUN_SEED_MAX
    derive_seed(1, "trainer.init", C(node_id="x"))

    bounds: list[int] = []

    def _top(n: int) -> int:
        bounds.append(n)
        return n - 1

    monkeypatch.setattr(seeding.secrets, "randbelow", _top)
    binding = resolve_run_seed(None)
    assert bounds == [RUN_SEED_MAX + 1]
    assert binding == RunSeedBinding(value=RUN_SEED_MAX, source="generated")
