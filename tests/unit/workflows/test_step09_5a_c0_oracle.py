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

* **Lane F2 (campaign-portion authority, 2026-08-26)** — the PROPOSER's run
  input `trial_portion` moved `0.1 -> 0.02` on a bare launch: the launch
  portions are now tri-state, and an UNFROZEN (None) portion resolves at the
  transit boundary to what an unconstrained planner defaults to
  (`UNCONSTRAINED_TRIAL_PORTION`, read from the ExperimentPlan schema) —
  healing the estimation-vs-execution divergence in which the preflight
  priced candidates against 5x the data campaigns actually executed.
  Measured before re-baselining: **exactly one field** — the TUNER input's
  portions are byte-identical (a bare launch restores the input-schema
  defaults), and `train_portion` is unchanged because the unconstrained
  default coincides with the old value (0.1).

* **Step 11 / C3** — the run-invariants lock gained ONE key,
  `execution_calibration`: the per-role subprocess memory ceilings the run
  executed under, plus their provenance (R-11-6). Measured before the golden
  was touched, and the report is quoted rather than paraphrased:

      .artifacts.run_invariants_lock.json.execution_calibration: ADDED

  — **exactly one ADDED key, zero changed, zero removed.** It is RECORDED and
  never equality-enforced, precisely so the same scientific run resumed under
  different host calibration stays legal; `RunInvariants._PROVENANCE` declares
  that classification structurally rather than leaving it to a validator's
  memory. The golden was edited SURGICALLY — the one key inserted into the
  existing document — rather than regenerated, so nothing else could move
  under cover of the re-baseline. That the oracle caught an additive lock key
  is again the point: it is exactly the class of change that should be
  declared here rather than discovered later.

* **Step 11 / C8** — the tuning RESULT and each of its records gained
  `task_composition_fingerprint`. Measured before the golden was touched:

      .results[0].task_composition_fingerprint: ADDED (None)
      .results[0].all_records[0].task_composition_fingerprint: ADDED (None)

  — **exactly two ADDED paths, both `None`, zero changed, zero removed.**
  `None` is the un-composed state, which is what this oracle drives; a
  COMPOSED run stamps its own identity there so a later resume can certify
  the records it restores (R-11-9). Without the stamp the frozen three-case
  rule would have refused every composed run's own evidence, which is the
  finding recorded as F-11-C8-a. The golden was edited SURGICALLY, one key
  per reported path.

* **Step 12 / PR-12a C2** — the TUNER's run input gained
  `task_composition_ref`: the typed composition PROJECTION (D-12a-1, ratified
  at the design approval). Measured before the golden was touched:

      .node_calls.tuner.run_inputs[0].task_composition_ref: ADDED (None)

  — **exactly one ADDED path, `None`, zero changed, zero removed.** `None` is
  the un-composed state this oracle drives, and it is what the tuner's two
  consumers read to take their legacy branches, so no legacy behaviour moved.
  The field reaches NO persisted artifact: it is read at three production
  sites, all in the tuner's main module, and `records.py` never mentions it
  (pinned by
  `test_step12_pr12a_c2_composition_projection.TestTheStampsStillReadTheRunScopedAuthority`).
  Before this, the tuner learned whether its own run was composed by calling
  the ambient `active_task_data_path()` — a subsystem seam used as a
  discriminator — and its per-model run-invariants lock had no composition
  values to record at all. The golden was edited SURGICALLY, the one key
  inserted at the reported path.

* **Step 12 / PR-12a C7-3** — the PROPOSER's run input gained
  `proposal_blocks`: the task-owned proposer guidance (D-12a-6, ratified at
  the design approval). Measured before the golden was touched:

      .node_calls.proposal.run_inputs[0].proposal_blocks: ADDED

  — **exactly one ADDED path, zero changed, zero removed.** Unlike the C2
  delta this one is not `None`: the value is TIDMAD's own declaration, which
  the un-composed workflow resolves through the ONE bounded Regime-A adapter,
  and this oracle drives an un-composed run. That is the point of the change —
  the prose the proposer's prompts used to hardcode is now a VALUE the caller
  supplies, so it becomes visible on the call surface instead of being
  invisible inside a template.

  The prompts themselves did NOT move: substituting these blocks back into
  the tokenized templates reproduces their pre-C7 sha256 byte-exactly, pinned
  by `test_step12_pr12a_c7_proposal_blocks.TestTheRelocationIsBYTE_EXACT`.
  The golden was edited SURGICALLY, one key at the reported path.

* **arXiv U1 (#253 / #254)** — run identity: the tuner's run input gained
  the three PASS-THROUGH fields the tuner locks and stamps but never
  consumes, and the tuning RESULT plus each of its records gained the
  opaque `experiment_arm`. Measured before the golden was touched, and the
  report is quoted rather than paraphrased:

      .node_calls.tuner.run_inputs[0].experiment_arm: ADDED (None)
      .node_calls.tuner.run_inputs[0].lit_review_config_sha256: ADDED (None)
      .node_calls.tuner.run_inputs[0].lit_review_enabled: ADDED (False)
      .results[0].all_records[0].experiment_arm: ADDED (None)
      .results[0].experiment_arm: ADDED (None)

  — **exactly five ADDED paths, every value the legacy default, zero
  changed, zero removed.** What did NOT move is the point:
  `artifacts.run_invariants_lock.json` reported no delta at all, because the
  three new CANONICAL lock fields are OMITTED at their defaults rather than
  serialized as `null`/`false` — an unlabelled, lit-review-OFF run's lock is
  byte-identical to its pre-U1 form. `None`/`False` are the unlabelled state
  this oracle drives; a LABELLED run stamps its arm on every record and
  output so a later resume can certify what it restores, under the same
  three-case ingress rule as the composition fingerprint. The golden was
  edited SURGICALLY, one key per reported path.

* **arXiv U3 (#259 / #260)** — the WITHOUT arm's explicit isolation flag
  reached the three node inputs that own an LLM-facing surface or a lock.
  Measured before the golden was touched:

      .node_calls.interpretation.run_inputs[0].baseline_isolation: ADDED (False)
      .node_calls.proposal.run_inputs[0].baseline_isolation: ADDED (False)
      .node_calls.tuner.run_inputs[0].baseline_isolation: ADDED (False)

  — **exactly three ADDED paths, all `False`, zero changed, zero removed.**
  `False` is the non-isolated state this oracle drives, under which every
  prompt render is byte-identical to before the flag existed (pinned by the
  U3 parity tests) and the lock omits the key. The golden was edited
  SURGICALLY, one key per reported path.

* **arXiv-readiness S2 / U6 (#256)** — the implement→validate retry loop
  persists each retry in its own nested `impl_KKK/` instead of overwriting
  within the proposal attempt directory. Measured before the golden was
  touched, exactly five CHANGED paths, zero added, zero removed — the
  implementor's `plugin_dir`, `test_dir`, `loss_dir` and `storage.local.
  workspace`, and the validator's `storage.local.workspace`, each gaining
  the `/impl_001` segment (the oracle's single attempt passes first time,
  so its terminal attempt is `impl_001`). The artifact tree is unchanged:
  the mocked nodes persist nothing, and the new directory holds no file.
  Edited SURGICALLY at those five paths; the deliberate layout decision and
  its falsifiers live in `tests/unit/workflows/test_u6_impl_attempt_layout.py`.

* **arXiv P1 (`agent_generated/` migration)** — the workspace lock gained the
  `generated_library` PROVENANCE key ({root, source}; `_PROVENANCE`, never
  compared). Under the suite's isolation fixture the root is a per-test tmp
  path, so the VALUE is normalised by the volatile list (it joins
  `repo_commit` there) and the golden carries the KEY at the reported path:

      .artifacts.run_invariants_lock.json.generated_library: ADDED ('<VOLATILE>')
      .node_calls.proposal.run_inputs[0].allowed_output_types: ADDED (None)
          — arXiv #259 (2026-08-26): ProposalInput gained the declared
          output-type constraint field; an unconstrained run records None.
          One-line textual insert into the golden, same precedent as above.

  — exactly one ADDED path, zero changed, zero removed. Edited SURGICALLY
  (one inserted line; the differ compares dicts, not order).

* **Integration note (landed-source reconciliation, 84d74280)** — the U1/U3
  and U6 deltas above were measured independently on sibling branches from
  the same base; the merged golden carries the UNION (eight ADDED keys at
  their legacy defaults + five CHANGED `/impl_001` paths). This test run at
  the integrated head is the proof the union is exact.
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
