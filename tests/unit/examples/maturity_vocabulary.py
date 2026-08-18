"""The ONE place the example packs' maturity vocabulary is written down.

Q3 sub-ruling (operator, 2026-08-17). Each Step-07 PR added its own prose pins
naming its own PR id against the same two `STATUS.md` files — 07a's and 07b's
coexisted, seven cases across two modules. **At D14 every one of these strings
changes, and all seven would have to be rewritten together.** This module makes
that one edit instead of seven.

WHAT THIS IS NOT. It is not a derived claim, deliberately. The operator's
constraint on the Q3 conversion was:

    the authority being checked  !=  the source generating the expectation

A "derived" version that read the maturity row and then asserted the row
matched itself would be the self-referential anti-pattern this PR has now found
four times. So these stay **hardcoded expectations**; what is shared is only
*where they are written*, not where they come from. The authority being checked
remains the pack's own `STATUS.md` / `README.md` on disk, and — for the
capability claims — the executable seam the row is asserting about.

WHEN D14 LANDS: edit this module. The Pets and DAVIS packs move from
declaration/fixture-backed to production-backed, `MATURITY_L1_*` stops being
true of them, and the `D14` deferral token disappears from their rows.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = REPO_ROOT / "examples"

#: The three persistent tracks (roadmap §22.9a).
TRACKS = ("tidmad", "oxford_iiit_pet", "davis_future_prediction")

#: Packs whose claims are backed by real production execution today.
PRODUCTION_BACKED = ("tidmad",)

#: Packs still at L1 — declared or fixture-backed — until D14.
L1_PACKS = ("oxford_iiit_pet", "davis_future_prediction")

#: The maturity phrases each `STATUS.md` row must carry, by PR.
MATURITY_PRODUCTION_07A = "production-backed from 07a"
MATURITY_PRODUCTION_07B = "**production-backed from 07b**"
MATURITY_L1_FIXTURE = "L1 — fixture-backed"
MATURITY_L1_DECLARATION = "**L1 — declaration-backed**"

#: The token that marks a claim as deferred to the D14 milestone. Its presence
#: is what makes an L1 row honest rather than a silent gap.
DEFERRAL_TOKEN = "D14"

#: Contrast rungs named in the rows, by the PR that introduced them.
RUNG_07A = "B-07a-1"
RUNGS_07B = ("B-07b-1", "B-07b-2")

#: The 07a L1 evidence file the Pets/DAVIS rows must name.
L1_FIXTURE_BASENAME = "training_history_l1_fixture.json"

#: Every README must state the three training-history rungs.
HISTORY_RUNGS = ("R1", "R2", "R3")


def status_text(pack: str) -> str:
    """The pack's `STATUS.md`, as the authority a claim is checked against."""
    return (EXAMPLES / pack / "STATUS.md").read_text(encoding="utf-8")


def readme_text(pack: str) -> str:
    return (EXAMPLES / pack / "README.md").read_text(encoding="utf-8")
