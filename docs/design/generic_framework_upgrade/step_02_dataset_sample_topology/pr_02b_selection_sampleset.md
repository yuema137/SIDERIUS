# PR 02b — Selection & SampleSet semantics (Step 02, child 2 of 3)

## Status

**DESIGN — READY FOR OPERATOR REVIEW (2026-08-14).
NOT FROZEN. IMPLEMENTATION NOT AUTHORIZED.**

Rewritten against **merged master after 02a** (`47359538`), not carried
over from the pre-02a sketch. The old sketch is superseded: its entire
"source starting point" — three singleton hardcodes in
`sample_set_builder.py` — no longer exists.

Parent: [`../step_02_dataset_sample_topology.md`](../step_02_dataset_sample_topology.md)
(LIVE governance). Predecessor: the merged 02a ledger (immutable).

Position in the DAG: **after 02a**. Semantically independent of 02c, but
the governance order is frozen `02a → 02b → 02c`; 02c is the Step
FINALIZER, so this child runs **no Step-level Gate**.

---

## 0. The finding that rewrote this design

```text
Previous assumption (pre-02a sketch §1):
  "sample_set_builder.py hardcodes the singleton three ways today:
   DataScope.default().resolve(TIDMAD), list(range(TIDMAD.num_files)),
   and SEGMENTS_PER_FILE reached through scoring_utils."
  02b's capability was to migrate those off the constants.

Audit evidence (merged master, 2026-08-14):
  grep for TIDMAD / NUM_FILES / SEGMENTS_PER_FILE / SEGMENT_LENGTH in
  execute_tools/sample_set_builder.py returns NOTHING. 02a's C2 collapsed
  the scoring_utils re-export hop and migrated all three reads while it
  was there. The only TIDMAD-shaped literal left in the file is
  ANCHOR_FILES = [0, 10, 19] — which is 02c's group declaration, not
  02b's to take.

Corrected understanding:
  02b's originally-scoped extraction is ALREADY DONE. Its remaining
  capability is different and narrower, and had to be re-derived from
  source rather than inherited.

Consequence:
  the centre of gravity moves to (i) how the selection path OBTAINS the
  profile, and (ii) the SampleSet serialization contract.
```

### 0.1 What is actually left — three source findings

**F1 — the selection path resolves the profile AMBIENTLY, not explicitly.**
`build_sample_set()` calls `resolve_dataset_profile()` internally. The
tuner's two production call sites
(`nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py`,
the trial/formal pair) pass `scope=` but **no profile**. So a run whose
bound profile differs from the ambient default would silently select
against the wrong topology. 02a deliberately made the accessor the
*Regime-A adapter*, not the general injection mechanism; selection is the
consumer that still relies on it.

**F2 — the JSON key-coercion divergence is real, demonstrable, and latent.**
`SampleSet = dict[int, list[int]]`, serialized at exactly **two**
production sites (`core/sandbox_executor.py`, train and eval), after
which keys are strings. Consumers then re-int independently, and two
disagree:

```text
TIDMADDataset       sorted(sample_set.items())      -> 0, 1, 10, 11, 12, …  LEXICOGRAPHIC
TIDMADEpochDataset  sorted(keys, key=int)           -> 0, 1,  2,  3,  4, …  NUMERIC
```

**Latent, not live**: no production caller passes `sample_set=` to
`TIDMADDataset` — both live constructors use its `fname_list` branch — so
only the numeric loader runs the real training path. 02b's job is to pin
the contract and prevent this becoming live, **not** to fix a live bug and
**not** to invent a typed wrapper because the shape is ugly.

**F3 — strategy definitions are still hardcoded, and are NOT 02b's yet.**
`Literal["snapshot","anchors","target"]` appears in the builder and in
`TrialConfig`. Making strategies declared data would need a second
implementation to justify the seam (roadmap §0 rule 8), and `anchors`
resolves through `ANCHOR_FILES`, which is 02c's. **Deferred**, with the
boundary stated rather than blurred.

---

## 1. Capability and final effect

> **Sample selection derives its file population and index space from an
> EXPLICITLY supplied Dataset Profile, and the SampleSet that population
> travels in has a pinned serialization contract at its one production
> boundary — while every TIDMAD selection identity stays byte-identical.**

Observable after merge: pointing a run at a valid non-TIDMAD topology
produces a correctly shaped SampleSet through the real tuner path, with no
TIDMAD constant and no ambient fallback involved; and the five existing
sha16 digests are unchanged.

---

## 2. Ownership

**OWNS**

- explicit Dataset-Profile threading into selection: `build_sample_set()`
  and its production callers;
- use of profile topology (`num_files`, index space) and
  `segments_per_file` in selection;
- `TrialConfig → SampleSet` construction semantics at the tuner boundary;
- the **SampleSet serialization / key-coercion contract** at the two
  `core/sandbox_executor.py` `json.dump` sites — pinned, then made
  explicit at that one boundary;
- production tuner consumption of the resolved selection path.

**DOES NOT OWN** — each with the reason:

| Not owned | Why |
|---|---|
| Dataset Profile topology/geometry/encoding/channel authority | **merged 02a.** 02b consumes it; it must not create a second topology authority or re-derive filenames |
| `ANCHOR_FILES` / systematic named groups | **02c.** `anchors` keeps its current literal behind an explicit adapter boundary |
| strategy definitions as declared data | deferred (F3) — no second implementation yet |
| portions, seeds | **runtime inputs**, LLM-planned / operator-clamped. Never config (roadmap §0 rule 4) |
| resolved SampleSets as stored artifacts | runtime state |
| DataLoader ordering / `shuffle` / `file_order` | 02a and the tuner-ordering feature. 02b changes no visited sequence |
| trial **packing** read-layout (`local_idx` vs `seg_idx` in the scorer) | a deliverable-READ layout contract between inference and scoring, not selection. Flagged in §12 as an open boundary, not claimed here |
| model I/O · metric · HealthGate · Deliverable Contract · launcher | Steps 03 / 06 / 08 / ledger / 10 |

---

## 3. Compatibility contract — strongest observable criterion per surface

| Surface | Criterion | Baseline |
|---|---|---|
| Selection identity | the **five sha16 digests** byte-identical: three trial strategies at `seed=42, portion=0.05` full scope, plus normal mode and partial-scope snapshot | **EXISTS** — `tests/unit/execute_tools/test_sample_set_builder.py`, `TestDataScopeBehavioralIdentity.GOLDEN` + `TestStep00SelectionDigests` |
| First-five segment indices | `GOLDEN_FIRST_FILE_SEGS` unchanged | **EXISTS** (same module) |
| Seed derivation | same seed → same `random.Random` draw sequence; algorithm untouched | EXISTS (implied by digests) |
| Strategy identity | `snapshot` / `anchors` / `target` / normal-mode select the same files | EXISTS |
| Partial-scope rules | `anchors`/`target` still rejected under partial scope; normal-mode out-of-scope index still rejected | EXISTS |
| `TrialConfig` resolution | `model_dump(mode="json")` deep-equal | **EXISTS** — Step-00 `tc1_*_resolved.json` goldens |
| **SampleSet JSON round-trip** | keys/values after `json.dump` → `json.load` and each consumer's re-int, at the production boundary | **MISSING → capture first (B1)** |
| Scope equivalence | explicit full-range scope == `None` scope | EXISTS |

The digests bind to CPython's `random.sample`. That is a known, accepted
environment assumption already recorded in the test module. **Do not
"improve" the sampling algorithm** — it would invalidate every historical
experiment identity.

---

## 4. Blocking checkpoint ladder

Every rung blocking. Later evidence never excuses an earlier failure.

```text
B1  capture the SampleSet round-trip baseline        (test-only)
  └─ CP0 — BASELINE COMPLETE
        the round-trip/key-coercion contract is pinned at the production
        boundary BEFORE any production change, and the pin is shown to
        fail when the behaviour it pins is perturbed
        FAIL => stop; do not begin B2

B2  explicit profile threading into selection
  └─ CP-B1 — SELECTION PARITY + EXPLICIT RESOLUTION
        five digests byte-identical; first-five indices unchanged;
        build_sample_set accepts an explicit profile and the tuner
        supplies it; no ambient fallback on the production path
        FAIL => stop

B3  serialization contract made explicit at the ONE boundary
  └─ CHECKPOINT A COMPLETE — Stage-A parity closed
        round-trip pin green UNMODIFIED; digests unchanged;
        TrialConfig goldens unchanged
        FAIL => stop; do not start contrast

B4  Stage-B: topology-through-selection contrast       (test-only)
  └─ CHECKPOINT B — the selection path follows a contrast topology
        FAIL => the abstraction or the rung is wrong; stop

assembled 02b executable head
  └─ CHECKPOINT C — LIVE INTEGRATION (§5)
        FAIL => not ready for review

B5  docs + ledger closeout
  └─ CHECKPOINT D — regression / static / exact-head CI
```

---

## 5. Checkpoint C — boundary frozen, command not frozen

Must prove the **REAL production selection path** consumes the resolved
profile and produces the SampleSet the tuner actually uses.

> A test that constructs the profile and calls `build_sample_set()`
> directly does **NOT** satisfy this. The question is whether the tuner
> path can still bypass the explicit resolution.

PASS must establish:

- [ ] the tuner's trial **and** formal construction sites supply the
      resolved profile explicitly;
- [ ] the SampleSet produced is the one serialized to the subprocess
      config (same object, one boundary);
- [ ] under a contrast topology the production path yields the contrast
      shape — not TIDMAD's 20 × 200;
- [ ] no ambient fallback is reachable on that path;
- [ ] exact executable HEAD, artifacts and log recorded.

Cheapest bounded mechanism, chosen at implementation time. **No real LLM,
no GPU, no scientific result.** A pseudo-LLM production-entry run is
acceptable *provided the selection path itself is real*.

**Implementation-environment requirements carried from 02a** (process
lessons, NOT product features):

- use an isolated worktree **OUTSIDE `.claude/`**;
- if Checkpoint C launches child Python processes, **verify import
  provenance** — assert the child resolves the package under the checkout
  under test;
- take every verdict from the authoritative test log, **never** a wrapper
  exit code.

---

## 6. Commit plan

| # | Commit | Kind |
|---|---|---|
| **B1** | capture the SampleSet round-trip baseline | test-only |
| **B2** | explicit profile threading into selection + tuner | production |
| **B3** | serialization contract explicit at the one boundary | production |
| **B4** | Stage-B topology-through-selection rung | test-only |
| **B5** | docs + ledger closeout | docs-only |

---

### 6.1 Commit B1 — capture the SampleSet round-trip baseline (test-only)

**1. Goal.** Pin the JSON round-trip / key-coercion behaviour at the
production boundary BEFORE anything changes it. It is the one §3 surface
with no oracle, and the §14 ledger's long-standing open issue.

Belongs here because capture-after-edit pins already-changed behaviour and
proves nothing (the S1-E precedent, re-confirmed by 02a's C1).

**2. Scope.**
Changes: new test module under `tests/unit/execute_tools/` (placement
implementation-time).
Unchanged: ALL production code — zero production diff.
Depends on: nothing.

**3. Implementation plan.**
- [ ] Pin what the boundary WRITES: a `SampleSet` with int keys, after
      `json.dump` at the two `core/sandbox_executor.py` sites, is read
      back with **string** keys and unchanged value lists.
- [ ] Pin each production consumer's re-int at its own seam, as it
      behaves TODAY — including the divergence:
      `sorted(items())` (lexicographic) vs `sorted(keys, key=int)`
      (numeric). **Record the divergence as the pinned fact; do not
      "fix" it in this commit.**
- [ ] Pin `validate_sample_set`'s coercion/validation behaviour at the
      boundary (it already exists — pin, do not change).
- [ ] Provide mutation evidence for the ONE failure class this adds:
      *round-trip / key-coercion drift*.

**4. Validation plan.**
Unit: the new pins.
Integration/pseudo: none.
Negative/invalid: a SampleSet with a non-integer-like key; an empty
SampleSet — pin today's behaviour, whatever it is.
Backward-compat: n/a (no production change).
Gate: none.

**5. Acceptance criteria.**
- `git diff --stat` shows ZERO files outside `tests/`.
- The lexicographic-vs-numeric divergence is asserted explicitly, with
  both orders written out, so a later change that silently unifies them
  reds.
- The pin fails when the coercion behaviour is perturbed (recorded
  mutation).
- No duplicate of anything the five digests already cover.

**6. Failure and edge cases.**
| Case | Handling |
|---|---|
| a pin cannot be written without touching production | STOP — a design finding, not a licence to edit |
| the divergence turns out to be LIVE, not latent | STOP and report: that is a production defect and a different PR |
| a consumer's re-int is unreachable in production | record it as latent, do not pin it as live |

**7. Verification commands and evidence.**
Intended: targeted `pytest` over the new module, plus
`tests/unit/execute_tools/test_sample_set_builder.py`. Record counts and
wall time here after execution. Never claim an unrun test.

**8. Commit boundary.** Test-only, independently reviewable, zero
production diff. Before committing: show diff summary, staged files, test
output, deviations.

---

### 6.2 Commit B2 — explicit profile threading into selection (production)

**1. Goal.** Remove the selection path's reliance on ambient profile
resolution (F1): `build_sample_set()` accepts an explicit profile and the
tuner's production call sites supply it.

Belongs here, separate from B3, because it changes WHERE the profile comes
from without touching how the SampleSet is serialized — two different
failure classes in one diff would be unreviewable.

**2. Scope.**
Changes: `execute_tools/sample_set_builder.py` (explicit parameter,
Regime-A default preserved); the tuner's trial/formal construction sites;
any other production caller the audit finds.
Unchanged: the sampling algorithm, seed derivation, strategy semantics,
`ANCHOR_FILES`, partial-scope rules, `TrialConfig` schema, DataLoader
ordering.
Depends on: B1.

**3. Implementation plan.**
- [ ] Re-read `build_sample_set()` and its production callers on the
      merged head before editing (line numbers in this document are dated
      evidence, not addresses).
- [ ] Add an explicit profile parameter; keep `None` → Regime-A
      resolution so un-migrated callers are unaffected (§1a-F).
- [ ] Thread the run's resolved profile from the tuner into BOTH the
      trial and the formal/eval construction sites.
- [ ] Confirm no new topology authority is introduced — the profile is
      consumed, never re-derived.
- [ ] Confirm portions and seeds remain runtime inputs, not config.

**4. Validation plan.**
Unit: the five digests unchanged; first-five indices unchanged; explicit
profile beats ambient when they differ.
Integration/pseudo: none required at this commit.
Negative/invalid: a profile whose `num_files` excludes a requested
`target_file`; normal-mode index outside scope — existing errors must
still fire.
Backward-compat: every §3 EXISTS row green, UNMODIFIED.
Gate: none.

**5. Acceptance criteria.**
- The five sha16 digests are byte-identical, asserted by the existing
  module run unmodified.
- With a contrast profile passed explicitly and a DIFFERENT ambient
  profile bound, selection follows the **explicit** one — proving the
  parameter is real and not decorative.
- No production selection call site relies on ambient resolution.
- Mutation: drop the explicit argument at one tuner site so it falls back
  to ambient → a test reds.

**6. Failure and edge cases.**
| Case | Handling |
|---|---|
| a caller has no natural profile to pass | record it and keep Regime-A there, rather than inventing a global |
| profile and `DataScope` disagree | the existing scope validation must still fire, unchanged |
| legacy caller passes nothing | Regime-A adapter — today's behaviour, must not break |
| a digest changes | **STOP** — experiment identity across the whole chain is invalidated |

**7. Verification commands and evidence.** Targeted + the selection
module + the tuner's selection tests. Counts and wall time recorded here.

**8. Commit boundary.** Threading only. No serialization change, no
strategy change, no rung.

---

### 6.3 Commit B3 — serialization contract explicit at the one boundary (production)

**1. Goal.** Give the SampleSet round-trip a single, stated contract at
the two `core/sandbox_executor.py` `json.dump` sites, so producer and
consumers cannot drift further apart.

Separate from B2 because its failure class is different (transport shape,
not population) and because B1's pin must be green across it.

**2. Scope.**
Changes: the two serialization sites and whatever minimal helper the
contract needs.
Unchanged: **consumer re-int behaviour is NOT rewritten in this PR** —
the divergence is latent (F2) and unifying it would be a behaviour change
with no forcing need. `SampleSet`'s type alias stays; no typed wrapper.
Depends on: B1, B2.

**3. Implementation plan.**
- [ ] Re-read both `json.dump(sample_set, …)` sites and
      `validate_sample_set` before editing.
- [ ] State the contract in ONE place: what key type crosses the
      boundary, and what a reader is entitled to assume.
- [ ] Ensure both sites go through it — two sites, one contract.
- [ ] Confirm the emitted JSON is byte-identical for TIDMAD inputs.
- [ ] Do **not** add a typed wrapper, and do **not** migrate consumers;
      record both as convergence candidates (§12) instead.

**4. Validation plan.**
Unit: B1's round-trip pin green UNMODIFIED; emitted JSON byte-identical
on fixture SampleSets.
Integration/pseudo: none required here.
Negative/invalid: a SampleSet that violates the contract is rejected at
the boundary, not silently written.
Backward-compat: subprocess consumers unchanged; argv unchanged.
Gate: none.

**5. Acceptance criteria.**
- Emitted JSON byte-identical to pre-change for TIDMAD inputs.
- Exactly one place states the key contract; both sites use it.
- B1's pins pass without modification.
- Mutation: bypass the contract at one site → a test reds.

**6. Failure and edge cases.**
| Case | Handling |
|---|---|
| the contract would change emitted bytes | **STOP** — that is a behaviour change, not a pin |
| a consumer depends on the lexicographic order | STOP and report: the divergence is live after all |
| scope validation interacts with coercion | existing DS8 validation must still fire |

**7. Verification commands and evidence.** Targeted + the sandbox-executor
tests + B1's module. Counts and wall time recorded here.

**8. Commit boundary.** Boundary contract only. No consumer migration, no
wrapper, no cleanup.

---

### 6.4 Commit B4 — Stage-B: topology through selection (test-only)

**1. Goal.** Prove the selection path follows a contrast topology. Without
it 02b has parity but no genericity evidence.

Lands after B2/B3 because the rung needs the fully resolved path.

**2. Scope.** Contrast fixtures under `tests/`. Zero production diff.
Depends on: B2, B3.

**3. Implementation plan.**
- [ ] Build a **single-axis** contrast profile: `num_files` and
      `segments_per_file` are the selection-relevant topology; vary the
      minimum needed and hold geometry, encoding, channels and groups at
      TIDMAD. State the atomicity baseline explicitly and assert it
      mechanically, as 02a's rungs do.
- [ ] Drive `TrialConfig → build_sample_set` with that profile and assert
      the file population, index space and per-file segment count all
      follow the declaration.
- [ ] Assert the shape is NOT TIDMAD's 20 × 200.
- [ ] Confirm the rung reds when a consumer re-hardcodes a TIDMAD count
      (mutation).

**4. Validation plan.**
Unit: the rung.
Negative/invalid: a portion that would select zero segments → existing
error, not a silent empty set.
Backward-compat: TIDMAD digests still green.
Gate: none.

**5. Acceptance criteria.**
- The rung varies exactly its named axis, machine-checked against the
  TIDMAD declaration.
- A consumer still assuming 20 files or 200 segments reds it —
  demonstrated by mutation.
- Zero production diff.

**6. Failure and edge cases.**
| Case | Handling |
|---|---|
| the rung needs two axes to be meaningful | STOP — the abstraction or the rung is wrong |
| it passes with a hardcoded consumer present | strengthen it; it is too weak (02a's M9 lesson) |

**7. Verification commands and evidence.** Targeted + selection module.
Counts and wall time recorded here.

**8. Commit boundary.** Test-only.

---

### 6.5 Commit B5 — docs + ledger closeout (docs-only)

**1. Goal.** Leave this document and the operator-facing docs true.

**2. Scope.** This document; the parent's child-status row; any touched
node/skill `.md` per the pre-merge doc-sync rule. Docs-only.
Depends on: B1-B4.

**3. Implementation plan.**
- [ ] Reconcile every checklist box with recorded evidence.
- [ ] Record the Checkpoint-C mechanism actually used.
- [ ] Update touched module docs, quote-verifying flags/defaults.
- [ ] Record Checkpoint-D evidence actually run.

**4. Validation plan.** `ruff check`, `ruff format --check`; exact-head CI.

**5. Acceptance criteria.** Every `[ ]` resolved or deferred with a
reason; ruff clean; exact-head CI green; clean tree; **not merged without
operator approval**.

**6. Failure and edge cases.** A stale ledger at the final head is a
defect in its own right.

**7-8.** Recorded at execution; docs-only boundary.

---

## 7. Gates

Instantiated from `docs/gates/gate_testing_standard.md` (read 2026-08-14),
per roadmap §17.0 — decided separately, quoted not recalled.

- **Gate 1 — NOT REQUIRED.** The standard's assignment table:
  *"New loader/renderer (pure Python) → Unit only"* and *"Config files,
  YAML, schema-only → Unit only"*. 02b changes no LLM-facing system prompt
  and no proposal-affecting schema.
  **Flip condition**: if any commit changes a rendered prompt byte or a
  proposal-affecting schema field, this child takes Gate 1 per the
  *"New LLM-facing system prompt"* row.
- **Gate 2 — NOT RUN by this child.** The table's
  *"Checkpoint (end of feature) → Gate 2"* row applies at **Step** level,
  and the parent assigns that single run to the FINALIZER 02c. Running it
  here would triple cost for one failure class.
- **Checkpoint C** is this child's production-boundary evidence, and is
  explicitly **not** a Gate tier.

---

## 8. Evidence economy

Applying 02a's lesson: its evidence was sound, but "targeted" repeatedly
expanded into most of `tests/unit/`.

```text
directly affected tests
  -> tests/unit/execute_tools/test_sample_set_builder.py + the new modules
true affected package
  -> the selection + sandbox-executor tests ONLY; NOT all of tests/unit/
focused integration / mutation
  -> per failure class
checkpoints
exact-head CI            <- the broad compatibility gate
```

**No local full unit suite is planned.** 02b's blast radius is materially
smaller than 02a's: it touches the selection builder, two serialization
sites and the tuner's two call sites — not ~13 production modules. Run one
only if implementation evidence shows the radius cannot honestly be
bounded, and record why.

**Failure classes** (mutations by class, not per test):

| Class | Demonstrates |
|---|---|
| round-trip / key-coercion drift | the transport shape changed silently |
| ambient-fallback reachability | a call site stopped supplying the profile explicitly |
| selection identity drift | a digest moved |
| topology-hardcode survival | a consumer still assumes 20 × 200 |

Every new test must name a failure class only it can catch. No
repository-wide test cleanup.

---

## 9. Stop conditions

- any of the five sha16 digests changes;
- the sampling algorithm or seed derivation changes;
- portions or seeds migrate into config;
- emitted SampleSet JSON bytes change for TIDMAD inputs;
- the key-coercion divergence proves LIVE rather than latent (that is a
  production defect and a different PR);
- 02b creates a second topology authority, or re-derives filenames;
- `ANCHOR_FILES` / group semantics are migrated here instead of 02c;
- Checkpoint C is claimed while the production tuner can still bypass the
  explicit selection path;
- rendered prompt bytes change without taking Gate 1;
- a rung needs more than its named axis.

---

## 10. Adversarial review (2026-08-14, narrow — 14 questions)

| # | Attack | Verdict |
|---|---|---|
| 1 | Is 02b still ONE coherent PR? | **YES.** B2 (where the population comes from) and B3 (how it travels) are two faces of one contract, share one consumer chain (tuner → sandbox → subprocess) and one oracle (the five digests). Splitting would land profile threading with its serialization contract unpinned. It is also **not too thin**: its failure class — a shifted SampleSet invalidating experiment identity chain-wide — is unique and severe |
| 2 | Any seam without a production consumer? | **NO.** The explicit profile parameter is consumed by the tuner's two sites in the same PR; the serialization contract is used by both `json.dump` sites. Nothing else is added |
| 3 | Portions/seeds misclassified as config? | **NO.** Explicitly listed as runtime inputs in §2 and as a stop condition in §9 |
| 4 | Did 02b steal 02c's group ownership? | **NO.** `ANCHOR_FILES` stays where it is behind an explicit adapter boundary; §0.1-F3 records why strategy-as-data is deferred rather than absorbed |
| 5 | Did 02b duplicate 02a's profile authority? | **NO.** It consumes `resolve_dataset_profile()`/`DatasetProfile` and is forbidden from re-deriving filenames or adding a second authority (§2, §9) |
| 6 | Does Stage A preserve every selection identity? | **YES** — five digests, first-five indices, strategy identity, partial-scope rules, seed derivation, `TrialConfig` goldens, scope equivalence, all named individually rather than as "selection unchanged" |
| 7 | Is the round-trip baseline captured before modification? | **YES** — B1 is test-only with zero production diff and CP0 blocks B2 |
| 8 | Is the Stage-B fixture genuinely single-axis? | **YES, and machine-checked.** B4 must assert atomicity against the TIDMAD declaration, as 02a's rungs do — a prose promise would not survive a careless edit |
| 9 | Can Checkpoint C pass while the tuner bypasses the new path? | **This was the sharpest risk.** §5 answers it explicitly: a direct `build_sample_set()` call does NOT satisfy the checkpoint, and the pass list requires both tuner sites plus "no ambient fallback reachable on that path" |
| 10 | Does Gate 1 add unique evidence? | **NO** — no prompt byte or proposal-affecting schema moves; a byte-equality assertion answers its question more precisely at zero cost. Flip condition recorded |
| 11 | Is Gate 2 still Step-level/finalizer-owned? | **YES** — parent §6.2/§10.2, 02c |
| 12 | Are tests proportional? | **Tightened deliberately.** §8 forbids defining "affected package" as most of `tests/unit/`, and plans no local full suite — a direct correction of 02a's drift |
| 13 | Did an 02a process lesson become an 02b product feature? | **NO.** Worktree location, import provenance and log-not-exit-code are stated in §5 as *implementation-environment requirements*, explicitly not product changes |
| 14 | Did SampleSet convergence happen prematurely? | **NO.** No typed wrapper, no consumer migration. The §14 row stays DO NOT MERGE; 02b only pins the boundary. The convergence bar (≥2 completed designs) is not met |

---

## 11. Remaining operator decisions

1. **Is 02b, at this reduced scope, still worth its own PR** — or should
   the serialization pin fold into 02c and 02b close as "already
   delivered by 02a"? The design argues ONE PR (§10 Q1); the operator
   owns the call.
2. **The latent key-coercion divergence.** 02b pins it. Unifying the two
   orders is a behaviour change with no forcing need today — confirm it
   stays deferred rather than being fixed opportunistically.
3. **Trial packing** (`local_idx` vs `seg_idx`) is currently unowned:
   a deliverable-READ layout between inference and scoring, not selection.
   Recorded in §12 of the parent as an open boundary; it needs an owner
   eventually.

---

## 12. Status

**DESIGN — READY FOR OPERATOR REVIEW. NOT FROZEN. IMPLEMENTATION NOT
AUTHORIZED.** Implementation begins only after operator freeze and a
filled Implementation Working Rules contract, in a fresh context with its
own Context Continuity v2 handoff — in an isolated worktree **outside
`.claude/`**.
