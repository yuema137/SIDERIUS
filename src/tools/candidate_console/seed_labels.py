"""The console's run-seed wording (issue #983); one owner for every page.

The console shows only the 53-bit ``run_seed``, which is exact in a JavaScript
number. Derived 63-bit seeds stay in record files.
"""

from core.seeding import SeedSource

#: The review line when the operator left Seed blank.
GENERATED_AT_LAUNCH = "Seed: generated at launch"
#: Readback of a record admitted before the seed contract.
UNRECORDED = "Seed: unrecorded (pre-seed run)"
#: Readback of a native chain whose lock does not yet record a seed.
CHAIN_PENDING = "Seed: not recorded yet (the chain records it when it starts)"
#: Readback of a native chain whose lock contradicts the reviewed declaration.
CHAIN_CONTRADICTED = "Seed: not shown (the run lock contradicts the reviewed declaration)"


def review_label(run_seed: int | None) -> str:
    """What a launch will use: the operator's seed, or one generated at launch."""
    return GENERATED_AT_LAUNCH if run_seed is None else f"Seed: {run_seed} (you set)"


def readback_label(
    run_seed: int | None, source: SeedSource | None, *, native_chain: bool = False
) -> str:
    """What a run recorded. ``source`` may be absent only for a lock that predates it."""
    if run_seed is None:
        return CHAIN_PENDING if native_chain else UNRECORDED
    if source == "operator":
        return f"Seed: {run_seed} (you set)"
    if source == "generated":
        return f"Seed: {run_seed} (generated)"
    return f"Seed: {run_seed}"
