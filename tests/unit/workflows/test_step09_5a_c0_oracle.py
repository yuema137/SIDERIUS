"""Step 09.5a C0 — the PRE-refactor differential oracle.

Captured BEFORE any production edit. Its golden is the frozen record of what a
bounded pseudo-mode workflow run looks like at the design base, and every later
commit in this PR must reproduce it exactly.

Defect this file catches that nothing else can: **the run-state migration
changed something observable** — a node received a different input, an artifact
changed, the returned results changed, or a startup side effect moved relative
to the run-invariants lock. Unit tests for the new carriers cannot catch it,
because they test the new shape; only a comparison against the old behaviour can.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.helpers.step09_5a_oracle import capture_workflow_snapshot, load_or_write_golden

GOLDEN = Path(__file__).parent / "goldens" / "step09_5a_pre_refactor_oracle.json"


def _diff(expected: object, actual: object, path: str = "") -> list[str]:
    """First-difference report — a bare `assert a == b` on a nested dict this
    size is unreadable, and an unreadable failure gets re-baselined instead of
    diagnosed."""
    out: list[str] = []
    if type(expected) is not type(actual):
        return [f"{path or '<root>'}: type {type(expected).__name__} -> {type(actual).__name__}"]
    if isinstance(expected, dict):
        assert isinstance(actual, dict)
        for k in sorted(set(expected) | set(actual)):
            if k not in expected:
                out.append(f"{path}.{k}: ADDED ({actual[k]!r:.120})")
            elif k not in actual:
                out.append(f"{path}.{k}: REMOVED")
            else:
                out += _diff(expected[k], actual[k], f"{path}.{k}")
    elif isinstance(expected, list):
        assert isinstance(actual, list)
        if len(expected) != len(actual):
            out.append(f"{path}: length {len(expected)} -> {len(actual)}")
        for i, (e, a) in enumerate(zip(expected, actual, strict=False)):
            out += _diff(e, a, f"{path}[{i}]")
    elif expected != actual:
        out.append(f"{path}: {expected!r:.120} -> {actual!r:.120}")
    return out[:40]


class TestPreRefactorOracle:
    def test_workflow_envelope_matches_the_frozen_baseline(self, tmp_path):
        snapshot = capture_workflow_snapshot(tmp_path)
        golden = load_or_write_golden(GOLDEN, snapshot)
        differences = _diff(golden, snapshot)
        assert not differences, (
            "Step 09.5a is behaviour-preserving; the observable workflow envelope "
            "moved:\n  " + "\n  ".join(differences)
        )

    def test_the_golden_is_not_vacuous(self):
        """A golden that captured an empty run would pass forever."""
        golden = json.loads(GOLDEN.read_text())
        assert golden["node_calls"]["tuner"]["run_count"] >= 1
        assert golden["node_calls"]["interpretation"]["run_count"] >= 1
        assert golden["results"], "the oracle captured no workflow result"
        assert golden["artifacts"], "the oracle captured no persisted artifact"

    def test_the_startup_side_effect_order_is_pinned(self):
        """§3.8/§18: materialize-and-hash must precede the lock.

        A run-state refactor is exactly the change that can move
        `build_run_invariants` after `ensure_run_invariants` without any test
        noticing — the lock would then describe a config the run never read.
        """
        order = json.loads(GOLDEN.read_text())["startup_side_effect_order"]
        assert "build_run_invariants" in order, order
        assert "ensure_run_invariants" in order, order
        assert order.index("build_run_invariants") < order.index("ensure_run_invariants"), order
