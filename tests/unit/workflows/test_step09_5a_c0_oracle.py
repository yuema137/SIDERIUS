"""Step 09.5a C0 — the PRE-refactor differential oracle.

Captured BEFORE any production edit. Its golden is the frozen record of what a
bounded pseudo-mode workflow run looks like at the design base, and every later
commit in this PR must reproduce it exactly.

Defect this file catches that nothing else can: **the run-state migration
changed something observable** — a node received a different input, an artifact
changed, the returned results changed, or a startup side effect moved relative
to the run-invariants lock. Unit tests for the new carriers cannot catch it,
because they test the new shape; only a comparison against the old behaviour can.

Declared deltas to the golden (never a re-baseline to make a test green):

* **Step 10 / P2b C2** — the envelope gained `secondary_metric_specs` (`None`)
  on the result and the three empty `secondary_metric_*` carriers on each
  record. This is the ADDITIVE-field serialization the P2b design audited and
  froze in its §4.7: the output path is `model_dump()` with no exclude flags,
  so default-empty additive fields DO serialize, and the frozen contract there
  is SEMANTIC emptiness rather than persisted-JSON byte identity — explicitly
  so that no omission machinery gets built for cosmetic parity. Every value in
  the delta is the empty state, and nothing pre-existing moved.

* **Step 10 / P3 C1** — the proposer's run input gained
  `interpretation_evidence`: the typed projection of the interpretation the
  protocol now builds through `build_proposer_evidence`, so that production and
  the node's standalone CLI stop being two independent readers of one raw dict
  (parent §11.2; child design §4.2). The delta was measured before
  re-baselining and is **exactly one ADDED key** — no pre-existing value moved,
  nothing was removed, and the raw `interpretation` field is untouched here
  because P3 removes it in C3, not C1. That the oracle caught this at all is
  the point: an additive change to a node's input envelope is exactly the class
  of thing that should be declared rather than discovered.

* **Step 10 / P3 C3** — the promised other half: the proposer's run input LOST
  `interpretation` (the raw upstream dump) and `per_model_score_tables` (a typed
  mirror with zero readers). The typed `interpretation_evidence` added above is
  now the ONE carrier, so nothing left the envelope that is not still there —
  one carrier replaced three. Measured before re-baselining: **exactly two
  REMOVED keys**, zero changed and zero added.

  Worth recording HOW this was found, because the process failed before the
  guard did. C3's own validation ran the proposer, nodes and protocol suites
  only — not `tests/unit/workflows/` — so this file stayed RED on the branch
  through three later commits, and was caught by a broad local sweep and an
  adversarial review rather than by the commit that broke it. A declared delta
  that the breaking commit never declares is indistinguishable from a
  regression until somebody runs the test. Targeted validation must include the
  guards a change is KNOWN to move — and this one is named in the paragraph
  directly above.
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
