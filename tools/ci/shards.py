"""Deterministic file-level shard planning.

Directory-level sharding was rejected on measurement, not taste:
``tests/unit/agent`` alone is 4,654 of 12,992 tests (36 %), so a
directory-per-shard split guarantees the long pole the design forbids. At file
level the largest unit is 129 tests — 1.0 % — so no single file can dominate
(docs/audit/ci_parity_audit.md §1).

Planning is pure: it takes a file list, a shard count, the sensitive set and
optional weights, and returns an assignment. It reads no filesystem and runs no
tests, which is what makes the properties below testable without executing
anything.

Guaranteed properties, each with a test that fails when it breaks:

* **deterministic** — same (files, count, sensitive, weights) ⇒ same plan
* **partition** — every bulk file lands in exactly one shard, none invented
* **isolation** — no sensitive file ever appears in a bulk shard
* **balance** — with weights, greedy longest-processing-time-first
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field


class Shard(BaseModel):
    """One independently executable unit of work."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    index: int
    files: tuple[str, ...]
    #: Sum of the weights of ``files``; equals ``len(files)`` when unweighted.
    weight: float

    @property
    def size(self) -> int:
        return len(self.files)


class ShardPlan(BaseModel):
    """A complete assignment of the bulk lane, plus the excluded sensitive set."""

    model_config = ConfigDict(extra="forbid")

    shards: list[Shard] = Field(default_factory=list)
    #: Files deliberately withheld from the bulk lane. They run in the
    #: sensitive lane, under controlled load and — for the git-state test — an
    #: exclusive checkout.
    sensitive: tuple[str, ...] = ()

    @property
    def bulk_files(self) -> list[str]:
        return [f for shard in self.shards for f in shard.files]

    def imbalance(self) -> float:
        """Heaviest shard ÷ mean shard weight. 1.0 is perfect.

        The acceptance target is "no shard dominates wall-clock", so this is
        the number to report before and after a balancing change.
        """
        if not self.shards:
            return 0.0
        weights = [s.weight for s in self.shards]
        mean = sum(weights) / len(weights)
        return max(weights) / mean if mean else 0.0


def plan_shards(
    files: Iterable[str],
    *,
    count: int,
    sensitive: Iterable[str] = (),
    weights: Mapping[str, float] | None = None,
) -> ShardPlan:
    """Assign ``files`` to ``count`` bulk shards, excluding ``sensitive``.

    Args:
        files: candidate test files. Duplicates are collapsed.
        count: number of bulk shards; must be >= 1.
        sensitive: files withheld from the bulk lane entirely.
        weights: optional per-file cost (measured runtime). Absent files
            default to 1.0, so an unweighted plan balances by file count.

    Returns:
        A :class:`ShardPlan` whose bulk shards partition ``files - sensitive``.

    Raises:
        ValueError: if ``count`` < 1.

    Determinism: inputs are sorted before assignment and every tie is broken by
    file name, so the plan never depends on set iteration order or on the order
    the caller happened to discover files in.
    """
    if count < 1:
        raise ValueError(f"shard count must be >= 1, got {count}")

    sensitive_set = frozenset(sensitive)
    # Sorted + deduplicated: the two sources of nondeterminism a planner can
    # accidentally inherit are set iteration order and caller discovery order.
    candidates = sorted(set(files) - sensitive_set)

    if weights is None:
        # Round-robin over the sorted list. With no cost information, file
        # count is the only honest proxy, and round-robin spreads adjacent
        # (often same-directory, often similar-cost) files across shards.
        buckets: list[list[str]] = [[] for _ in range(count)]
        for position, name in enumerate(candidates):
            buckets[position % count].append(name)
        return ShardPlan(
            shards=[
                Shard(index=i, files=tuple(b), weight=float(len(b))) for i, b in enumerate(buckets)
            ],
            sensitive=tuple(sorted(sensitive_set)),
        )

    # Greedy longest-processing-time-first: repeatedly place the heaviest
    # remaining file into the lightest shard. Simple, deterministic, and within
    # a small constant of optimal for makespan — good enough that a more
    # elaborate packer would be unjustified complexity.
    ordered = sorted(candidates, key=lambda n: (-weights.get(n, 1.0), n))
    loads: list[float] = [0.0] * count
    picked: list[list[str]] = [[] for _ in range(count)]
    for name in ordered:
        target = min(range(count), key=lambda i: (loads[i], i))
        picked[target].append(name)
        loads[target] += weights.get(name, 1.0)
    return ShardPlan(
        shards=[
            Shard(index=i, files=tuple(sorted(picked[i])), weight=loads[i]) for i in range(count)
        ],
        sensitive=tuple(sorted(sensitive_set)),
    )


def verify_plan(plan: ShardPlan, expected: Sequence[str]) -> list[str]:
    """Return the reasons ``plan`` is not a valid partition of ``expected``.

    An empty list means valid. This exists so the harness can assert the
    property at runtime rather than trusting the planner — a silently dropped
    shard would look exactly like a green run.
    """
    problems: list[str] = []
    assigned = plan.bulk_files
    if len(assigned) != len(set(assigned)):
        seen: set[str] = set()
        dupes = sorted({f for f in assigned if f in seen or seen.add(f)})  # type: ignore[func-returns-value]
        problems.append(f"duplicate files across shards: {dupes}")

    want = set(expected) - set(plan.sensitive)
    missing = sorted(want - set(assigned))
    if missing:
        problems.append(f"{len(missing)} file(s) never assigned: {missing[:5]}")

    invented = sorted(set(assigned) - want)
    if invented:
        problems.append(f"{len(invented)} file(s) assigned but not expected: {invented[:5]}")

    leaked = sorted(set(assigned) & set(plan.sensitive))
    if leaked:
        problems.append(f"sensitive file(s) leaked into the bulk lane: {leaked}")

    return problems
