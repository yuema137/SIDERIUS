"""Shared golden-assertion helper for the Step-00 baseline harness.

Design: ``docs/design/generic_framework_upgrade/step_00_golden_baseline_harness.md``
§14 (capture mechanics) / §16 (comparison ergonomics) / §17 (update policy).

One tiny helper, no snapshot library: reads are explicit UTF-8, failures are
readable unified diffs, and trailing-newline divergence is called out
explicitly (it is invisible in a line diff but IS a byte difference the
Type-1 criterion protects).

Tests NEVER regenerate goldens (§17 rule 1). A missing golden fails with
capture instructions instead of a bare FileNotFoundError.
"""

from __future__ import annotations

import difflib
from pathlib import Path


def assert_golden(actual: str, golden_path: Path, *, surface: str) -> None:
    """Assert ``actual`` is byte-identical to the committed golden.

    Args:
        actual: The string produced by the REAL production render/producer.
        golden_path: Path to the committed ``.txt`` golden.
        surface: Baseline ID + human name for the failure message
            (e.g. ``"PB-1 planner user prompt"``).

    Raises:
        AssertionError: with a unified diff (and an explicit trailing-newline
            note when that is the only divergence), or with capture
            instructions when the golden does not exist yet.
    """
    if not golden_path.exists():
        raise AssertionError(
            f"[{surface}] golden missing: {golden_path}\n"
            "Step-00 policy (design §17): goldens are captured by an explicit "
            "developer act in a test-only commit stating provenance "
            "('captured at <sha>, clean tree'). Tests never write goldens."
        )
    expected = golden_path.read_text(encoding="utf-8")
    if actual == expected:
        return
    if actual.rstrip("\n") == expected.rstrip("\n"):
        raise AssertionError(
            f"[{surface}] differs from {golden_path.name} ONLY in trailing "
            f"newline bytes (expected {expected[len(expected.rstrip(chr(10))) :]!r}, "
            f"got {actual[len(actual.rstrip(chr(10))) :]!r}). Trailing newlines "
            "are part of the Type-1 byte contract (design §16)."
        )
    diff = "\n".join(
        difflib.unified_diff(
            expected.splitlines(),
            actual.splitlines(),
            fromfile=f"golden/{golden_path.name}",
            tofile="actual",
            lineterm="",
        )
    )
    raise AssertionError(
        f"[{surface}] rendered output diverged from golden {golden_path.name}.\n"
        "Triage (design §19.3): production drift -> fix production, never the "
        "golden; intentional change -> regenerate in the SAME commit per §17 "
        "rule 3; fixture rot -> fix the fixture.\n" + diff
    )
