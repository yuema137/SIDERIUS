# PR 02b — Selection & SampleSet semantics (Step 02, child 2 of 3)

## Status

**FROZEN / OPERATOR APPROVED FOR IMPLEMENTATION (2026-08-14).**

The operator froze this design at **revision 2**. Everything below — the
capability statement (§1), ownership and explicit non-ownership (§2), the
compatibility contract (§3), the blocking checkpoint ladder (§4), the
Checkpoint-C boundary (§5), the five commits and their acceptance
criteria (§6), the Gate decision (§7), evidence economy (§8) and the stop
conditions (§9) — may not change without a new operator decision.

In particular, these are frozen and must not be re-litigated during
implementation:

- the **live-vs-latent key-coercion distinction** (§6.1): B1 pins the
  LIVE round-trip contract and must NOT assert the latent branch's
  lexicographic ordering;
- **Stage-A / Stage-B separation**: B2 proves the explicit hop is live
  using a TIDMAD-**equivalent** profile with ambient resolution disabled;
  B4 is the only contrast and varies **`num_files` alone**;
- **B3 freezes observable properties, not helper shape**, and may
  legitimately shrink to an evidence/documentation commit;
- **trial packing is OUT**, forward-routed to the Deliverable Contract /
  Step-5 §7c audit.

Revision 2 applied the operator review of 2026-08-14: Q1/Q2/Q3 answered
(§11), and four narrow corrections — B1 pins the live contract instead of
freezing a latent bug, B3 freezes observable properties rather than helper
shape, B2 is Stage A only, and B4 is strictly single-axis.

**IMPLEMENTATION IS NOT YET AUTHORIZED IN THIS SESSION.** Per the
established lifecycle, implementation begins only after a filled
**Implementation Working Rules contract** for this child, in a NEW, fresh
context with its own Context Continuity v2 handoff — never in the design
session, and in an isolated worktree **outside `.claude/`** (an 02a
process lesson, §5).

**Frozen design HEAD**: the commit that carries this status line. Resolve
it mechanically from the repository at kickoff (`git log -1 --format=%H --
<this file>`); never from conversational memory.

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
| trial **packing** read-layout (`local_idx` vs `seg_idx` in the scorer) | not Selection/SampleSet-owned — it interprets a persisted/read layout between inference and scoring. **Forward-routed** (operator decision Q3) to the Deliverable Contract / Step-5 §7c execution-contract audit, which decides final ownership. Not left unowned |
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

- [x] the tuner's trial **and** formal construction sites supply the
      resolved profile explicitly;
- [x] the SampleSet produced is the one serialized to the subprocess
      config (same object, one boundary);
- [x] under a contrast topology the production path yields the contrast
      shape — not TIDMAD's 20 × 200;
- [x] no ambient fallback is reachable on that path;
- [x] exact executable HEAD, artifacts and log recorded.

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

**FROZEN production round-trip contract — pin exactly this:**
- [x] the SampleSet producer uses **integer** keys;
- [x] the JSON boundary emits **string** keys (per JSON), at both
      `core/sandbox_executor.py` sites;
- [x] value lists are unchanged across the round trip;
- [x] the **LIVE** production consumer converts keys **numerically**,
      preserving current selection identity;
- [x] `validate_sample_set`'s existing coercion/validation behaviour at
      the boundary (pin, do not change).

**LATENT finding — record, do NOT freeze:**
- [x] record in the ledger that `TIDMADDataset`'s `sample_set` branch
      sorts post-JSON keys **lexicographically**, that a source audit
      finds **no production caller reaches that branch**, and that 02b
      does not fix it.
- [x] **Do NOT assert its exact ordering** (`0, 1, 10, 11, …`) anywhere.
      Freezing an unreachable bug's output would promote it into a
      compatibility promise nobody can later change — the opposite of
      what a capture-first baseline is for.

**Stop condition:** if the current-source audit finds that branch **is**
production-reachable, **STOP and report** — the classification has
changed and this is a production defect, not a latent one.

- [x] Mutation evidence targets *production round-trip / key-coercion
      drift* — **not** preservation of a dead branch's behaviour.

**4. Validation plan.**
Unit: the new pins.
Integration/pseudo: none.
Negative/invalid: a SampleSet with a non-integer-like key; an empty
SampleSet — pin today's behaviour, whatever it is.
Backward-compat: n/a (no production change).
Gate: none.

**5. Acceptance criteria.**
- `git diff --stat` shows ZERO files outside `tests/`.
- The LIVE contract above is pinned at the production boundary, and the
  pin fails when that behaviour is perturbed (recorded mutation).
- **No test asserts the latent branch's lexicographic ordering.** A
  reviewer can grep the new module for `10, 11` / `"10"` and find nothing
  that enshrines it.
- The latent divergence is recorded in the ledger with its
  production-unreachability evidence.
- No duplicate of anything the five digests already cover.

**6. Failure and edge cases.**
| Case | Handling |
|---|---|
| a pin cannot be written without touching production | STOP — a design finding, not a licence to edit |
| the divergence turns out to be LIVE, not latent | **STOP and report** — a production defect, a different PR, and the design classification has changed |
| a consumer's re-int is unreachable in production | record it as latent; do **not** pin it as live, and do not freeze its output |

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
- [x] Re-read `build_sample_set()` and its production callers on the
      merged head before editing (line numbers in this document are dated
      evidence, not addresses).
- [x] Add an explicit profile parameter; keep `None` → Regime-A
      resolution so un-migrated callers are unaffected (§1a-F).
- [x] Thread the run's resolved profile from the tuner into BOTH the
      trial and the formal/eval construction sites.
- [x] Confirm no new topology authority is introduced — the profile is
      consumed, never re-derived.
- [x] Confirm portions and seeds remain runtime inputs, not config.

**4. Validation plan.**
Unit: the five digests unchanged; first-five indices unchanged; explicit
profile beats ambient when they differ.
Integration/pseudo: none required at this commit.
Negative/invalid: a profile whose `num_files` excludes a requested
`target_file`; normal-mode index outside scope — existing errors must
still fire.
Backward-compat: every §3 EXISTS row green, UNMODIFIED.
Gate: none.

**5. Acceptance criteria — Stage A: SAME semantics, NEW transport.**

B2 answers *"is the explicit hop live?"* It does **not** answer *"does a
different topology work?"* — that is B4's question, and using a
non-TIDMAD contrast here would smuggle Stage B into Stage A.

- An explicit **TIDMAD-equivalent** profile is passed through the real
  tuner selection path.
- **Ambient resolution is disabled / made to fail if consulted**, and the
  production path still succeeds — the sharpest available proof that the
  explicit hop is real rather than decorative, because a decorative
  parameter would fall through to the ambient resolver and pass.
- The five sha16 digests and the first-five indices remain
  **byte-identical**, asserted by the existing module run unmodified.
- No production selection call site relies on ambient resolution.
- Mutation: drop the explicit argument at one tuner site → with ambient
  disabled, a test reds.

Exact assertion mechanics (how ambient is disabled) are
implementation-time.

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
- [x] Re-read both `json.dump(sample_set, …)` sites and
      `validate_sample_set` before editing.
- [x] Establish the OBSERVABLE contract: both production serialization
      sites obey the same SampleSet boundary contract, and both emit
      byte-identical TIDMAD JSON.
- [x] Ensure invalid SampleSets are rejected consistently before/at the
      boundary.
- [x] Keep B1's production round-trip pin green **unmodified**.
- [x] Do **not** add a typed wrapper, and do **not** migrate consumers;
      record both as convergence candidates (§12) instead.

**Implementation shape is NOT frozen.** Reuse an existing helper,
introduce one minimal shared helper, or use another source-supported
shape — whichever the re-read supports. **Do not create a new abstraction
merely to satisfy prose about centralization.**

**This commit may legitimately shrink.** If the audit shows both
`json.dump` sites are already simple enough and B1's boundary pin already
prevents drift, B3 becomes a minimal evidence/documentation commit rather
than forced helper construction. 02b's real capability is explicit profile
threading; serialization consolidation is supporting safety work and must
not be over-engineered to look substantial.

**4. Validation plan.**
Unit: B1's round-trip pin green UNMODIFIED; emitted JSON byte-identical
on fixture SampleSets.
Integration/pseudo: none required here.
Negative/invalid: a SampleSet that violates the contract is rejected at
the boundary, not silently written.
Backward-compat: subprocess consumers unchanged; argv unchanged.
Gate: none.

**5. Acceptance criteria — observable properties only.**
- Emitted JSON byte-identical to pre-change for TIDMAD inputs.
- Both serialization sites obey the same observable boundary contract.
- Invalid SampleSets are rejected consistently at/before the boundary.
- B1's production round-trip pin passes **without modification**.
- Mutation: make one site diverge from the contract → a test reds.
- **No new abstraction exists solely to centralize prose.**

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
**Approved axis: `num_files` / file index-space ONLY.**

```text
ambient  profile : TIDMAD, num_files = 20
explicit profile : num_files != 20
held identical   : segments_per_file, geometry, encoding, channel
                   identity, groups, strategy, seed, portion,
                   metric/model semantics
```

- [x] Build the contrast profile varying **only** `num_files`, and assert
      atomicity mechanically against the TIDMAD declaration, as 02a's
      rungs do — a prose promise would not survive a careless edit.
- [x] Drive the **REAL** tuner → `TrialConfig` → `build_sample_set` path
      and assert the selection follows the **explicit** profile rather
      than the ambient TIDMAD one.
- [x] Assert the file population is NOT TIDMAD's 20.
- [x] Confirm the rung reds when a consumer re-hardcodes a TIDMAD count
      (mutation).

**Do NOT vary `num_files` and `segments_per_file` together.** 02a already
proved the profile can represent topology and geometry; 02b's unique
Stage-B question is narrower — does the production SELECTION path consume
the explicit profile. If implementation proves a `num_files`-only fixture
cannot be valid, **STOP and report the source reason**; do not silently
add a second axis.

**4. Validation plan.**
Unit: the rung.
Negative/invalid: a portion that would select zero segments → existing
error, not a silent empty set.
Backward-compat: TIDMAD digests still green.
Gate: none.

**5. Acceptance criteria.**
- The rung varies **exactly one** field (`num_files`), machine-checked
  against the TIDMAD declaration.
- The real tuner path follows the explicit profile, not the ambient one.
- A consumer still assuming 20 files reds it — demonstrated by mutation.
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
- [x] Reconcile every checklist box with recorded evidence.
- [x] Record the Checkpoint-C mechanism actually used.
- [x] Update touched module docs, quote-verifying flags/defaults.
- [x] Record Checkpoint-D evidence actually run.

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

## 10a. Narrow re-review after the operator revision (2026-08-14, 9 questions)

Scoped exactly as directed. No broadened repository audit.

| # | Question | Verdict |
|---|---|---|
| 1 | Is 02b still independently useful? | **YES.** Its capability — the production tuner supplying a run-bound profile to selection — is a correctness property nothing else delivers. 02a made the accessor a Regime-A *adapter*, explicitly not the general injection mechanism, so selection is the consumer still relying on it |
| 2 | Does Stage A avoid non-TIDMAD behaviour changes? | **YES, now.** B2's acceptance was the one place Stage B had leaked in; it now uses a TIDMAD-**equivalent** profile with ambient resolution disabled. Stage A = same semantics, new transport |
| 3 | Is B4 exactly one axis? | **YES.** `num_files` only, with `segments_per_file` moved into the explicitly-held list and a STOP condition if a one-axis fixture proves impossible |
| 4 | Does CP0 pin only LIVE compatibility surfaces? | **YES, now** — this was the sharpest correction. B1 pins int-keys-in / string-keys-out / values-unchanged / live consumer converts numerically, and explicitly forbids asserting the latent branch's ordering. An acceptance criterion makes that greppable |
| 5 | Does B3 avoid speculative abstraction? | **YES.** "Exactly one place" is gone; the frozen properties are observable (same contract, byte-identical TIDMAD JSON, consistent rejection), and B3 may shrink to evidence/docs if no refactor is warranted |
| 6 | Can Checkpoint C still catch ambient fallback? | **YES.** Its pass list requires both trial and formal sites, the SampleSet actually serialized for the subprocess, and "no ambient fallback reachable on the migrated production path". A direct `build_sample_set()` call is explicitly insufficient |
| 7 | Is 02c ownership untouched? | **YES.** `ANCHOR_FILES` stays; strategy-as-data stays deferred; the parent records the 02c implication without editing 02c's document |
| 8 | Is trial packing explicitly routed forward? | **YES, now.** It was "unowned" in revision 1 — a gap. It is now routed to the Deliverable Contract / Step-5 §7c audit in both this document and the parent |
| 9 | Is test scope proportional? | **YES.** No local full suite planned; "affected package" is named as the selection + sandbox-executor tests and explicitly *not* most of `tests/unit/`; mutations are by failure class |

**No new material finding.** The four revisions were corrections to how
the design states its evidence, not to its scope or ownership.

---

## 11. Operator decisions — ANSWERED (2026-08-14)

| # | Question | Decision |
|---|---|---|
| **Q1** | Is 02b still worth its own PR at this reduced scope? | **YES — keep it as its own child.** Explicit profile threading into the REAL tuner selection path carries its own correctness failure class: a bound non-TIDMAD run can otherwise silently select against the ambient/default topology. That is independent of 02c's group/HealthGate capability. Being smaller is fine — the split criterion is semantic and review complexity, not size |
| **Q2** | Fix the latent lexicographic-vs-numeric divergence? | **NO — stays deferred.** And, sharpened by the review: **do not promote the unreachable lexicographic behaviour into a frozen compatibility invariant.** B1 pins the LIVE contract only (§6.1) |
| **Q3** | Does trial packing belong to 02b? | **NO — OUT.** Forward-routed, not left unowned: *not Selection/SampleSet-owned; candidate Deliverable Contract / Step-5 §7c execution-contract ownership, decided by that design's producer-reader source audit* |

### 11.1 Revisions applied after the operator review

1. **B1 no longer freezes a dead branch's bug.** It pins the live
   round-trip contract and records the latent divergence, with a stop
   condition if the branch turns out to be reachable.
2. **B3 freezes observable properties, not helper shape** — and may
   legitimately shrink to an evidence/docs commit if no refactor is
   warranted.
3. **B2 is Stage A only.** Its acceptance moved from a non-TIDMAD
   contrast (which smuggled Stage B in) to: explicit TIDMAD-equivalent
   profile + ambient resolution disabled + digests byte-identical.
4. **B4 is strictly single-axis** — `num_files` only, with
   `segments_per_file` explicitly held.

### 11.2 Remaining operator questions

**None.** Q1-Q3 are answered and the four revisions are applied. The
remaining choices — assertion mechanics, how ambient resolution is
disabled, helper shape, fixture placement — are implementation-time by
design (§13).

## 12. Status

**FROZEN / OPERATOR APPROVED FOR IMPLEMENTATION (revision 2,
2026-08-14). IMPLEMENTATION COMPLETE — READY FOR OPERATOR REVIEW.
NOT MERGED.**

Ladder: CP0 → CP-B1 → Checkpoint A → Checkpoint B → Checkpoint C — all
**PASS**, each with mutation evidence (§13.3, §13.5, §13.7, §13.8,
§13.10). Gate 1 not required; **Gate 2 not run — Step-level, owned by
finalizer 02c** (§7).

> **Reconciliation note (kickoff, 2026-08-14).** The freeze commit
> `dc26bb75` replaced the status block at the head of this document but
> left this trailing §12 asserting the pre-freeze state
> ("NOT YET FROZEN. IMPLEMENTATION NOT AUTHORIZED"). That was stale
> prose, not a competing authority: the freeze commit message, §Status
> at the head of this file, and the parent's child-status table
> (`step_02_dataset_sample_topology.md`, both the header table and the
> child-status row) all agree. Corrected at implementation kickoff with
> **no change to scope, checkpoints, gates, Stage-A/Stage-B semantics or
> the live-vs-latent key-coercion distinction.**

Implementation runs in a fresh context with its own Context Continuity
v2 handoff, in an isolated worktree **outside `.claude/`**.

---

## 13. Implementation ledger (live)

Referenced by §11.2. This section is written DURING implementation and
is the authoritative record of what actually happened.

**Frozen design HEAD**: `dc26bb752eaf6d49c5a553de95401770f0652713`
(resolved mechanically: `git log -1 --format=%H -- <this file>`).
**Implementation base**: master `dc26bb75`.
**Branch**: `feat/generic-framework-step-02b-selection-sampleset`.
**Worktree**: `/home/yuema137/siderius-worktrees/pr02b-impl` — outside
`.claude/`, per §5.

### 13.0 Kickoff source audit (before any production edit)

Line numbers below are dated evidence at base `dc26bb75`.

**F1 CONFIRMED — selection resolves the profile ambiently.**
`execute_tools/sample_set_builder.py` calls `resolve_dataset_profile()`
at **three** points, not one: `:67` (`.dataset` for scope resolution),
`:95` (`segments_per_file` for the trial branch) and `:117`
(normal-mode segment count). There is no profile parameter.

**Production `build_sample_set` callers — the full audit §6.2 asked
for.** The tuner's pair is `ml_hyperparameter_tune_agent.py:4403`
(train) and `:4411` (eval). Both sit inside ONE
`if trial_config.mode in ("trial", "formal")` branch (`:4402`), so the
*same two call sites* serve BOTH trial and formal modes — §5's "trial
and formal construction sites" are these two calls exercised in two
modes, not four distinct call sites. Other production callers found:
`scripts/run_comparison.py:381,388`, `agent/utils/proposer_preflight.py:78`,
and two `scripts/` validation harnesses
(`c2_prephase_validation.py`, `pregate_runtime_control_validation.py`).

**The tuner holds no profile.** Grep for
`resolve_dataset_profile|DatasetProfile|dataset_profile` across
`ml_hyperparameter_tune_agent.py` returns nothing — the run-bound
profile has to be obtained there before it can be threaded.

**Profile mechanism.** `_ACTIVE_PROFILE` is a `ContextVar`
(`dataset_config.py:493`) set by `bind_dataset_profile()` (`:571`);
`resolve_dataset_profile()` (`:498`) returns
`_ACTIVE_PROFILE.get() or TIDMAD_PROFILE` (`:515`). Because
`sample_set_builder` binds the name at import, patching
`execute_tools.sample_set_builder.resolve_dataset_profile` disables
ambient resolution **for the builder only** — which is how B2's
"ambient disabled" acceptance can be asserted without disabling the
tuner's own resolution.

**The two serialization sites CONFIRMED**: `core/sandbox_executor.py:1307`
(train) and `:1639` (eval), each preceded by
`validate_sample_set(sample_set, scope=self.data_scope)` (`:1302`,
`:1627`).

> **Pre-existing asymmetry — pin, do NOT unify.** The train site lets
> `ScopeViolationError` propagate; the eval site catches it and returns
> an error dict (`:1628-1634`). That is error *reporting*, downstream of
> the boundary contract. B3's "rejected consistently" means both sites
> reject through the same validator, not that they report identically.
> Unifying them would be a behaviour change (§9).

**F2 CONFIRMED and the B1 STOP CONDITION DOES NOT FIRE.**
The divergence is real: `train_engine_sandbox.py:179`
`sorted(sample_set.items())` (LEXICOGRAPHIC, `TIDMADDataset.
_pull_events_from_sample_set`) vs `:333`
`sorted(sample_set.keys(), key=int)` (NUMERIC, `TIDMADEpochDataset`).

Reachability audit — every production `TIDMADDataset(...)` construction:

| Site | Branch used | Passes `sample_set=`? |
|---|---|---|
| `train_engine_sandbox.py:1351` | `fname_list` (legacy single-file, the `else` arm of `if sample_set is not None`) | **no** |
| `execute_tools/probe_data.py:29` | `fname_list` (VRAM probe) | **no** |

The live multi-file path constructs `TIDMADEpochDataset`
(`train_engine_sandbox.py:884-891`), the numeric consumer. Therefore
`_pull_events_from_sample_set` is **production-unreachable**, the design's
latent classification holds, and B1 proceeds as written: pin the live
contract, record the latent branch, assert nothing about its ordering.

**Import provenance (§5 requirement).** The project venv carries an
editable `siderius` install whose finder hardcodes
`/home/yuema137/SIDERIUS` — the *main checkout*, not this worktree.
Empirically, with cwd = worktree, `execute_tools.sample_set_builder` and
`core.sandbox_executor` both resolve under the worktree (cwd precedes
the editable finder). **Binding consequence: every `python`/`pytest`
invocation for this PR must run with cwd = the worktree**, and
Checkpoint C must additionally assert provenance inside any child
process it launches.

### 13.1 Open implementation question — the boundary validator's TIDMAD bounds

**Discovered at kickoff; to be decided during B3, on B2's evidence.**

`execute_tools/scoring_utils.py` still reaches the singletons inside
`validate_sample_set`: `scope.resolve(TIDMAD)` (`:309`),
`0 <= file_index < NUM_FILES` (`:317`), `seg < SEGMENTS_PER_FILE`
(`:328`). 02a migrated `sample_set_builder.py` off the constants but not
this validator.

```text
Consequence once B2 lands:
  producer (selection)  -> profile-driven
  boundary (validator)  -> still TIDMAD-bounded
  => a profile with num_files > 20 selects files the boundary rejects.
```

Relevant precedent: parent §D (OD-02a-1) moved `score_table.py`'s
import-time `NUM_FILES` bounds to profile-resolved `model_validator`s
**because a required contrast rung was otherwise impossible** — and
states explicitly that this is *not* a universal rule and must not be
generalized "without its own source evidence".

Bounded resolution path, in order:
1. choose the B4 contrast on the unblocked side (`num_files < 20`), which
   needs zero production diff;
2. if — and only if — the rung or Checkpoint C is *actually* blocked,
   that is the missing source evidence and the precedent applies;
3. otherwise record the residual here with its owner rather than
   widening 02b.

**RESOLVED at B4 planning — step 1 taken.** The contrast profile varies
`num_files` DOWNWARD (20 → a smaller population). Reasoning:

- §6.4 specifies `num_files != 20`, not `> 20`, so the downward direction
  satisfies the frozen axis exactly;
- selection under it produces file indices strictly inside TIDMAD's
  `[0, 20)`, so `validate_sample_set`'s bound is never consulted as a
  *limit* and the contrast reaches the subprocess config unimpeded —
  the rung is NOT blocked, so the OD-02a-1 precedent's trigger condition
  is not met and generalizing it here would be exactly the unsourced
  widening §D forbids;
- the rung's question ("does the production selection path consume the
  explicit profile?") is answered identically in either direction: a
  consumer still assuming 20 files reds it either way.

**Residual, stated rather than silently absorbed.** After 02b,
`validate_sample_set` remains TIDMAD-bounded, so 02b's capability holds
for `num_files <= 20`. A profile declaring MORE files than TIDMAD would
select legally and then be rejected at the boundary. This is **not** a
regression — the validator is exactly as TIDMAD-bound as before 02b — but
it is the next honest step in the same migration.

**Ownership: UNDETERMINED by this child's audit.** An earlier revision of
this section proposed 02c "because it already owns the boundary's other
TIDMAD literal (`ANCHOR_FILES`)". That reason is **factually wrong** and
is corrected here: `ANCHOR_FILES` lives in
`execute_tools/sample_set_builder.py`, not in
`execute_tools/scoring_utils.py` where `validate_sample_set` is defined.
They are not the same boundary and no shared-module argument supports the
routing. The decision belongs to the parent, from a producer-consumer
audit this child did not perform.

### 13.2 Commit ladder — live status

| Rung | Status | Evidence |
|---|---|---|
| docs reconciliation | landed `73ca1fdd` | this section + §12 + parent §Status |
| B1 → **CP0 PASS** | landed `8d317715` | §13.3 |
| B2 → **CP-B1 PASS** | landed `7cc8c21d` | §13.5 |
| B3 → **Checkpoint A PASS** | landed `09442a6c` | §13.7 |
| B4 → **Checkpoint B PASS** | landed `e2d058ef` | §13.8 |
| **Checkpoint C PASS** | landed `6f14dcdb` | §13.10 |
| B5 → **Checkpoint D PASS** | landed `8c910cf8` + `9e6dd4e7` | §13.13 |

### 13.3 CP0 — BASELINE COMPLETE — **PASS**

Commit `8d317715`, module
`tests/unit/execute_tools/test_step02b_b1_sampleset_roundtrip.py`.

**Zero production diff** — `git status` after the change showed exactly
one added path, under `tests/`.

**Mechanism.** The pin drives the REAL executor methods
(`TidmadSandbox.execute_training` / `.execute_inference`) with all three
launch primitives patched, following
`tests/unit/core/test_ordering_propagation.py`. The asserted file is
therefore the one production wrote, and its path is read out of the real
argv (`--sample_set_json`) rather than from the filename convention — so
deleting the flag reds the pin instead of passing on a conventional path.

**§6.1 frozen contract — all five pinned:**

| Contract item | Where |
|---|---|
| producer uses integer keys | `TestProducerEmitsIntegerKeys` |
| JSON boundary emits string keys, BOTH sites | `test_boundary_emits_string_keys[train\|eval]` |
| value lists unchanged across the round trip | `test_boundary_preserves_value_lists_exactly[train\|eval]` |
| the LIVE consumer converts keys NUMERICALLY | `TestLiveConsumerReintsNumerically` |
| `validate_sample_set`'s boundary behaviour | `test_boundary_rejects_an_invalid_sample_set_before_launch[train\|eval]` + the two uncovered negatives |

Why the first item is not redundant with the digests: they hash
`json.dumps(ss, sort_keys=True)`, and `{0: [1]}` and `{"0": [1]}`
serialize to identical bytes. The digests are structurally **blind** to
producer key type.

**LATENT branch — recorded, NOT frozen.** The module docstring carries
the unreachability evidence; **no test asserts the lexicographic
ordering**. The contrast fixture uses files 4/9/12 (numeric `4,9,12` vs
lexicographic `12,4,9`), and the "not lexicographic" assertion is
**computed from the input**, never hardcoded — so the greppable
acceptance criterion holds: nothing in the module enshrines that output.

**Mutation evidence — four mutations, four CAUGHT, none survived.**
Each verified its exact target line before applying, purged `__pycache__`
before and after, and restored with `git checkout` (harness:
`mutate.sh`, re-runnable).

| # | Mutation | Site | Expected | Observed |
|---|---|---|---|---|
| M1 | live consumer coercion → lexicographic (`, key=int` deleted) | `train_engine_sandbox.py:333` | numeric pin reds | **CAUGHT** — visited `[12, 4, 9]` |
| M2 | train boundary reverses each segment list | `sandbox_executor.py:1307` | value pin reds | **CAUGHT** — "altered the segment list for file 4" |
| M3 | train transport hop deleted (`--sample_set_json` not appended) | `sandbox_executor.py:1308` | path lookup reds | **CAUGHT** — 2 failures |
| M4 | eval validator hop deleted | `sandbox_executor.py:1627` | rejection pin reds | **CAUGHT** — no rejection raised |

M1 is the load-bearing one: it is exactly the drift that would make the
latent divergence live, and the pin catches it without ever asserting the
latent branch's own output.

**Post-restore baseline**: tree clean (`git status --porcelain` empty),
`test_step02b_b1_sampleset_roundtrip.py` + `test_sample_set_builder.py` +
`test_sandbox_scope.py` → **63 passed in 0.94s**, rc=0 read from the log.

### 13.4 Source discoveries at B1

> **Previous assumption:** both boundary sites reject an invalid
> SampleSet by propagating `ValueError`, inferred from the absence of a
> local `try/except` around the train site's `validate_sample_set` call.
>
> **Audit evidence:** the first draft of the rejection test failed on
> the train phase only, printing
> `!!! [Executor Internal Error] !!!: SampleSet file_index 999 out of
> range [0, 20).` `execute_training` wraps its whole body in a broad
> `except Exception` (`sandbox_executor.py:1511-1512`) returning
> `{"status": "error", "message": str(e)}`. `execute_inference` catches
> only `ScopeViolationError` (`:1628`), so a plain `ValueError`
> propagates from there.
>
> **Corrected understanding:** the two sites share the invariant that
> matters — **rejection before any launch primitive is called** — but
> differ in outward shape. This generalizes the §13.0 note, which had
> only observed the difference for scope errors.
>
> **Implementation consequence:** B3's "rejected consistently at/before
> the boundary" means *through the same validator, before launch*. It
> does **not** license unifying the two error shapes; that would be a
> behaviour change (§9).
>
> **Validation consequence:** the rejection test is phase-aware and pins
> each shape as measured.

> **Previous assumption:** asserting that the written file equals
> `validate_sample_set(raw)` proves the validator hop runs.
>
> **Audit evidence:** the validator returns segment lists untouched
> (`scoring_utils.py:333`) and only re-keys; `json.dump` stringifies keys
> either way. The comparison therefore holds whether or not the hop ever
> executed — confirmed by M4's design, which would have survived it.
>
> **Corrected understanding:** rejection is the validator's only
> observable effect at this boundary.
>
> **Implementation consequence:** the tautological assertion was replaced
> before commit, not carried into the PR. M4 now has a test that reds.

### 13.5 CP-B1 — SELECTION PARITY + EXPLICIT RESOLUTION — **PASS**

Commit `7cc8c21d`.

**Parity.** The five sha16 digests and `GOLDEN_FIRST_FILE_SEGS` are
byte-identical, asserted by running
`tests/unit/execute_tools/test_sample_set_builder.py` **unmodified** — 82
passed across selection + digests + B1 + 02a-C2 + formal-sample-set.

**Explicit resolution.** `build_sample_set()` takes
`profile: DatasetProfile | None = None`; the tuner resolves the run's
profile ONCE and supplies it to both construction sites.

**Production callers deliberately left on Regime-A** (§6.2 edge table —
"a caller has no natural profile to pass"): `scripts/run_comparison.py:381,388`
and `agent/utils/proposer_preflight.py:78`. Audit basis: neither has any
profile in scope; `run_comparison.py` contains zero `profile` references.
`profile=None` keeps their behaviour bit-identical.

**Resolve-once is load-bearing, not cosmetic.** The pre-B2 function
called `resolve_dataset_profile()` at THREE independent points (`:67`
scope, `:95` trial segments, `:117` normal-mode segments). Resolving once
is what makes train and eval provably select against the same topology; a
per-site resolve could not survive a rebind between the two calls.

**Mutation evidence — three mutations, three CAUGHT.**

| # | Mutation | Site | Observed |
|---|---|---|---|
| M5 | train tuner site drops `profile=` | tuner `:4418` | **CAUGHT** — `KeyError: 'profile'`, run degrades to `partial` |
| M6 | eval tuner site drops `profile=` | tuner `:4427` | **CAUGHT** — same signature at the eval site |
| M7 | builder ignores the supplied profile | `sample_set_builder.py:85` | **CAUGHT** — 11 failed, `_AmbientConsulted` raised |

M7 is the sharpest: with ambient resolution made to RAISE, a decorative
parameter cannot hide. M5/M6 prove the *production* sites supply it —
a `None`-defaulted parameter is invisible to any caller that never passes
it, so builder-level evidence alone would not have established the claim.

### 13.6 Process finding — mutation hygiene (self-inflicted, recorded)

> **What happened.** The first CP-B1 battery was run against
> **uncommitted** B2 production work. Its `git checkout -- <file>`
> restore step therefore reverted the file to HEAD, silently deleting the
> B2 implementation mid-battery.
>
> **Consequences, classified honestly:** M6 and M7 had already executed
> against real B2 code and are VALID evidence. M5 was never validly run —
> by the time it started, the tuner had been reverted, so its target line
> no longer contained `profile=run_profile,`.
>
> **What saved it.** The harness verifies the exact target line *before*
> mutating and aborts on mismatch. M5 reported `INVALID (wrong target
> site)` rather than mutating an unrelated line and reporting a
> meaningless SURVIVED/CAUGHT. Target verification is what turned a
> silent corruption into a loud one.
>
> **Corrected procedure — the B1 order, applied without exception:**
> ```text
> commit the production change
>   -> run the mutation battery against the committed state
>   -> git checkout restores exactly what was committed
> ```
> B1 followed this and was unaffected. B2 did not, and paid for it. The
> battery was re-run in full after committing `7cc8c21d`; the CP-B1 table
> above reports only that clean run.
>
> **Cost:** one wasted battery (~5 min) and a re-application of two
> production edits. No evidence was accepted from the corrupted run.

### 13.7 Checkpoint A — Stage-A parity closed — **PASS**

Commit `09442a6c`.

**B3 shrank, with the audit that licenses it (§6.3 explicitly allows
this).** The re-read found both sites are five lines of
`validate -> path -> dump -> flag`, differing in exactly one respect that
must NOT be unified (§13.4). A shared helper would have to leave that
difference outside itself — removing three lines and adding one
indirection. So the contract is stated **at** the boundary (which is what
the commit is titled) rather than extracted into a new seam. **No new
abstraction exists solely to centralize prose.**

Production diff: **comment-only**, 29 insertions in
`core/sandbox_executor.py`. Emitted JSON is therefore byte-identical for
TIDMAD inputs by construction, not by assertion.

**The gap B3's test closes.** Every B1 assertion goes through
`json.load`. A site that grew an `indent=`, a `sort_keys=` or a different
separator would satisfy all of them while changing what actually crosses
the process boundary. `test_step02b_b3_boundary_byte_parity.py` asserts
raw bytes — both *between* the sites and *against* the expected compact
form — so they can neither drift apart nor drift together.

**Checkpoint A evidence run** — 73 passed in 3.33s, rc=0 from the log:
`test_step00_dataset_baselines.py` + `test_step00_numeric_baselines.py`
(the `tc1_*_resolved.json` TrialConfig goldens) + `test_sample_set_builder.py`
(five digests) + B1's pin **unmodified** + B3's parity.

| Checkpoint-A criterion | Evidence |
|---|---|
| round-trip pin green UNMODIFIED | B1 module untouched by `09442a6c`; green in the run above |
| digests unchanged | `test_sample_set_builder.py` green, unmodified |
| TrialConfig goldens unchanged | Step-00 baseline modules green |

**Mutations — two, both CAUGHT.**

| # | Mutation | Observed |
|---|---|---|
| M8 | eval site diverges (`indent=4`) | **CAUGHT** — byte-parity test reds |
| M9 | one site reorders keys on write | **CAUGHT** — both the parity test AND the wire-format test red |

M9 mutated a single site, so both assertions fired; the wire-format
assertion is the one that would still catch a change applied to **both**
sites together, which parity alone cannot see.

### 13.8 Checkpoint B — the selection path follows a contrast topology — **PASS**

Commit `e2d058ef`. Test-only, zero production diff.

Single axis, **machine-checked**: the rung diffs the contrast profile's
`model_dump()` against TIDMAD's and requires the differing-path list to be
exactly `["dataset.num_files"]`. It fails the moment a second axis
appears, and its message says to STOP and report rather than add one.

Four assertions, each a hop that could independently keep working against
TIDMAD: file population follows the contrast; the index space does NOT
move with it; `DataScope.default()` resolves against the SUPPLIED profile;
and a file that exists under TIDMAD but not under the contrast is
rejected rather than silently selected. Ambient resolution raises
throughout, so nothing can pass by falling back.

**Mutation M10 — the rung's justification, measured.** Re-hardcoding
TIDMAD's count in the scope resolver
(`dataset_config.py:298`, `list(range(dataset.num_files))` →
`list(range(20))`) — precisely the "topology-hardcode survival" failure
class:

| Suite | Result |
|---|---|
| the Stage-B rung | **CAUGHT** — 3 failed, 3 passed |
| the five TIDMAD digests | **BLIND** — 37 passed, rc=0 |

The digests cannot see it, because under TIDMAD `num_files` **is** 20.
That is the whole argument for Stage B in one measurement: parity
evidence and genericity evidence are not substitutes.

### 13.9 FINDING — a contrast topology is misread as a partial DataScope

**Discovered by Checkpoint C, which is exactly what a live-integration
rung is for.** Not a regression, not introduced by 02b, and **not 02b's
to fix.**

The first Checkpoint-C run died at tuner startup:

```text
ValueError: HealthGate monitored files violate the DataScope:
  - gate 'pearson_dispersion_recording' check 'pearson_dispersion':
    no explicit peek_file_indices (defaults to full-dataset access)
    — an explicit in-scope list is required under a partial DataScope
  ... (3 checks)
```

There is no partial DataScope in that run. The scope is the default —
*full* — under a 7-file topology.

**Root cause: two startup validators resolve topology from different
authorities.**

| Validator | Topology source | Result under a 7-file contrast |
|---|---|---|
| `validate_runtime_config` (`agent/schemas/hyperparam_tuning.py:2078-2080`) | `dataset: DatasetConfig = TIDMAD` — the **singleton, bound as a DEFAULT ARGUMENT** at import | resolves the scope to `[0..19]` |
| `validate_health_gate_files_against_scope` (`execute_tools/health_checks/config.py:333-334`) | `resolve_dataset_profile()` — the **ambient profile** | `scope_is_full` computed against `range(7)` |

The tuner calls `validate_runtime_config(agent_input)` positionally
(`ml_hyperparameter_tune_agent.py:3636`), so the default always wins and
the bound profile is never consulted. `{0..19} != {0..6}` → "partial" →
the HealthGate monitored-file rule fires on a run that is not partial.

A default argument evaluated at import is invisible to `bind_dataset_profile`
— which is why 02a's accessor migration did not reach it, and why nothing
before a non-TIDMAD live run could have surfaced it.

**Ownership — recorded and routed, not absorbed.**

- §2 DOES NOT OWN lists **HealthGate** (Steps 03/06/08/10);
- §6.2 lists **partial-scope rules** among the things B2 leaves
  **UNCHANGED**;
- §9 makes "02b creates a second topology authority" a stop condition, and
  fixing this by teaching selection about scope resolution would do
  precisely that.

Changing it here would be an unsourced scope expansion of exactly the kind
§13.1 already declined.

#### Ownership disposition (corrected 2026-08-13, operator-directed)

> **A previous revision of this section routed the finding to "02c as Step
> finalizer, or Step-06". That claim was intuition and is REFUTED by the
> source audit.** It is corrected here rather than carried into merged
> history.

The residue splits across **two** surfaces with different owners:

| Surface | Candidate owner | Source evidence |
|---|---|---|
| `validate_runtime_config(..., dataset=TIDMAD)` + the tuner's full-scope comparison (`ml_hyperparameter_tune_agent.py:3637`, against `DATASET_CONFIG` = TIDMAD) | **Step 10 — §12 Orchestration binding** | The roadmap's Step-02 row explicitly disclaims this class: *"Launcher/orchestration/execution-infrastructure task-binding residue … remains explicitly owned by its later rows (§12 step 10, §9 step 11) — Step 2 does NOT claim loop-wide constant elimination."* The roadmap's audit A already inventories the **identical construct** as orchestration residue at `workflows/model_exploration.py:104,1817,1856` — `_resolved_scope = _run_scope.resolve(_DATASET_CONFIG)` then `_scope_is_partial = _resolved_scope != list(range(_DATASET_CONFIG.num_files))`. |
| `validate_health_gate_files_against_scope` (`execute_tools/health_checks/config.py:333-334`) reading `resolve_dataset_profile()` while its caller supplies a TIDMAD-resolved scope | **Step 08 — §8 HealthGates** | §2's non-ownership row maps the list in order: `model I/O · metric · HealthGate · Deliverable Contract · launcher → Steps 03 / 06 / 08 / ledger / 10`. HealthGate is **Step 08**; Step 06 is *metric*. |

**Explicitly recorded, so no later reader re-derives the wrong answer:**

- **PR 02c is NOT supported** as owner — the Step-02 roadmap row disclaims
  launcher/orchestration task-binding residue outright.
- **Step 06 is NOT supported** as owner — §2's ordered mapping assigns
  Step 06 to *metric*, not HealthGate.

**Do not treat the table above as final.** It is the strongest reading the
current source supports, not a settled assignment: `validate_runtime_config`
lives in `agent/schemas/hyperparam_tuning.py`, which Step 10's row does not
name verbatim (it names "workflow binding, campaign_artifacts, orchestration
inputs to resume"). **The detailed Step-08 and Step-10 designs must confirm
exact ownership from their own producer-consumer audits.**

**The PR-02b selection capability itself is COMPLETE and is not blocked by
this residue** — see §13.10-F: `build_sample_set` receives the raw
`DataScope` object and resolves it against the explicitly supplied profile;
the mis-resolved `resolved_data_scope` is consumed only by startup
invariants, HealthGate config materialization, logging and records.

**Consequence for Checkpoint C:** the run sets `health_gate_enabled=False`
— the remediation the error message itself names, and a legitimate
run-level INPUT (per CLAUDE.md, `health_gate_enabled` is a run-level input,
not YAML policy). This is disclosed in the test's own docstring so no
future reader mistakes it for an incidental convenience flag.

**Selection is unaffected.** The mismatch is confined to startup
validation: the tuner passes the `DataScope` *object* to
`build_sample_set`, which resolves it against the SUPPLIED profile
(`[0..6]`), and the sandbox's `validate_sample_set` checks
`{0..6} ⊆ [0..19]`, which holds. No selected index is wrong; only the
startup partial-scope *classification* is.

### 13.10 Checkpoint C — LIVE INTEGRATION — **PASS**

Commit `6f14dcdb`. Test-only, zero production diff.
Module: `tests/unit/agent/tune_ml_hyperparam_agent/
test_step02b_checkpoint_c_live_integration.py`.

**Mechanism chosen (§5 leaves the command open, the boundary frozen).**
The real `HyperparamTuningAgent.run()` is driven with a **real**
`TidmadSandbox`, under a contrast profile bound with
`bind_dataset_profile`. Nothing in the module calls `build_sample_set` —
§5 rules that out explicitly.

```text
REAL:  resolve_dataset_profile -> build_sample_set(profile=)
       -> _run_skill -> skill wrapper
       -> execute_training / execute_inference
       -> validate_sample_set -> json.dump -> --sample_set_json
```

Stubbed, each strictly downstream of the property: the LLM bridge; the
subprocess launch primitives (stubbed **after** the SampleSet is
validated and written); post-inference scoring; anchor/reference inputs.
`score_vector` is replaced by **subclassing** the real sandbox, so
`execute_training` / `execute_inference` remain inherited production code
that no patch can hollow out.

**§5 PASS list:**

| Requirement | Evidence |
|---|---|
| trial **and** formal sites supply the resolved profile | `test_both_rounds_reached_the_boundary` — ≥2 distinct `exp_id`s reached the boundary; round 2 is formal by the tuner invariant pinned in `test_final_round_always_formal` |
| the SampleSet produced is the one serialized to the subprocess config | `test_the_serialized_set_is_the_one_handed_to_the_subprocess` — path read from real argv, contents re-asserted |
| under a contrast topology the path yields the contrast shape | `test_the_real_path_serialized_the_contrast_shape` — every written config has 7 files, not 20 |
| no ambient fallback reachable | `test_no_ambient_fallback_was_reachable` — the builder's resolver RAISES for the whole run and is asserted un-called |
| exact head, artifacts, log recorded | this section; head `6f14dcdb` |

**Import provenance (§5).** No child Python process is launched — the
launch primitives are stubbed — so there is no child interpreter to
audit, and the test says so rather than performing a ceremonial check.
What it does assert is that `sample_set_builder` and `sandbox_executor`
resolve **under the checkout under test**, which is a real risk here:
the venv carries an editable install pointing at a different clone
(§13.0).

**Result: 6 passed in 22.04s, rc=0 read from the log.**

**Mutation M11 — the checkpoint is not vacuous.** The tuner is made to
bind `TIDMAD_PROFILE` instead of the run's resolved profile
(`ml_hyperparameter_tune_agent.py:4410`) — the exact defect this
checkpoint exists to catch, and one that leaves the code *running
normally* rather than raising:

```text
Round 2/2 Complete. Score: 1.5      <- the run still succeeds
2 failed, 4 passed                  <- Checkpoint C reds anyway
  test_the_real_path_serialized_the_contrast_shape
    "train_sample_set_punet_test_run_002.json carries 20 files"
  test_the_serialized_set_is_the_one_handed_to_the_subprocess
```

**CAUGHT.** Note what this rules out: the mutated run completes both
rounds and reports a score, so a checkpoint that merely asserted "the run
finished" would have passed. Only reading the serialized artifact catches
it.

### 13.11 Three harness defects Checkpoint C found in itself

Recorded because each would have produced a green checkpoint that proved
less than claimed.

> **1. Unbounded cost.** The first pass left `attempts_per_round` /
> `max_fail_rounds` at their defaults — 9 attempts, each running a **real
> RTX 5090 VRAM probe** — 854s for a unit-tier checkpoint, and real
> hardware work that was never intended. Bounded to one attempt per round
> with the VRAM/config/scoring skills canned; training and inference stay
> real because only they reach the boundary. **854s → 22s.**
>
> **2. The launch stub never wrote the `_OK_<exp_id>` sentinel.**
> `execute_training` treats "returncode 0, no sentinel" as a silent
> crash, so inference never ran and the **eval SampleSet was never
> serialized**. The checkpoint was asserting half the boundary while
> reporting 4 passed.
>
> **3. "5 passed" did not mean both modes ran — and this is the one that
> matters.** §5 requires the trial AND formal construction sites. The
> suite was green *without any assertion that both rounds occurred*.
> Adding `test_both_rounds_reached_the_boundary` turned it **red**: only
> `punet_test_run_001` had reached the boundary.
>
> Root cause: `_handle_prephase_gpu_measurement` launches a real
> runtime-control GPU measurement worker on a host that has a device
> identity; with the launch primitives stubbed it read a `MagicMock`
> `returncode` and raised
> `TypeError: '<' not supported between MagicMock and int`
> (`gpu_measurement_runner.py:420`), aborting the run after round 1. It is
> now stubbed to the function's **own documented `PROCEED` early return**
> — the path a host without a device identity takes.
>
> **Consequence:** without defect 3 being found, Checkpoint C would have
> been claimed PASS on trial-mode-only evidence. A checkpoint that does
> not assert its own coverage is not evidence of coverage.

### 13.11a CI caught a portability defect the local run could not

> **Symptom.** Exact-head CI on `8c910cf8` (run 31672711999): **8638
> passed, 23 skipped, 5 errors** — all five errors in the Checkpoint-C
> module, all the same:
>
> ```text
> FileNotFoundError: Trial mode requires segment_anchors.json at
>   /path/to/TIDMAD/segment_anchors.json
> ```
>
> **Root cause.** A real `TidmadSandbox` resolves `dirs["data"]` to the
> **machine's configured TIDMAD data directory**, and the tuner refuses to
> start a trial-capable run without `segment_anchors.json` there
> (`ml_hyperparameter_tune_agent.py:3806-3814`). This developer box has
> the real dataset; CI has no gitignored `tidmad_data_config.yaml` and
> falls back to the tracked template's placeholder `/path/to/TIDMAD/`.
>
> **Classification.** Test scaffolding, not production. Exactly the
> failure CLAUDE.md's portability rule names: *a green local result that
> said nothing about the code under test.*
>
> **Fix.** The anchor data is redirected into the test's own `tmp_path`,
> so the run depends on no machine-specific resource. `load_anchor_map`
> was already patched, so only the file's EXISTENCE was ever load-bearing.
> No production change, and no broad `os.path.exists` patch — which would
> have hollowed out this module's real file-existence assertions.
>
> **Portability VERIFIED, not assumed.** CLAUDE.md: "local success is not
> sufficient evidence of portability". The local `tidmad_data_config.yaml`
> was moved aside to reproduce CI's fallback exactly, the module re-run,
> and the config restored:
>
> ```text
> UserWarning: tidmad_data_config.yaml not found ...
>   falling back to template at tidmad_data_config.example.yaml
> 6 passed, 1 warning in 22.32s     rc=0
> ```
>
> The warning is the proof the run used the placeholder path — the exact
> condition that failed CI.

### 13.12 Checklist reconciliation — one bounded deviation

All 31 checklist boxes in §5 and §6 are resolved. One was discharged at a
different rung than §6.4 literally specifies, and is recorded rather than
quietly ticked.

```text
Deviation:
  §6.4's B4 plan says "Drive the REAL tuner -> TrialConfig ->
  build_sample_set path and assert the selection follows the explicit
  profile". B4 as committed (e2d058ef) exercises the contrast at the
  BUILDER level; the real-tuner contrast drive lives in Checkpoint C
  (6f14dcdb).

Reason:
  Checkpoint C already drives the real tuner under the SAME contrast
  profile (num_files = 7) and asserts something strictly stronger — that
  the contrast shape reaches the JSON config actually handed to the
  subprocess, not merely that the builder returned it. Duplicating a full
  real-tuner run inside B4 would add ~22s and no new failure class.

Source evidence:
  §5 requires the real-tuner evidence at Checkpoint C regardless, and
  explicitly rules out a direct build_sample_set() call for THAT rung.
  B4's own frozen acceptance criteria (§6.4 §5) are "exactly one axis,
  machine-checked", "the real tuner path follows the explicit profile",
  "a consumer still assuming 20 files reds it", "zero production diff" —
  the second is met by Checkpoint C within the same PR.

Impact:
  None on coverage. Both the builder-level rung and the real-tuner
  integration exist; only their commit boundary differs from the literal
  plan.

Validation:
  B4: 8 passed. Checkpoint C: 6 passed, plus mutation M11 CAUGHT, which
  is precisely "the real tuner path follows the explicit profile"
  demonstrated by breaking it.
```

---

### 13.13 Checkpoint D — regression / static / exact-head CI — **PASS**

**Local regression** (affected package per §8 — the selection +
sandbox-executor + tuner tests, explicitly *not* most of `tests/unit/`):

```text
tests/unit/execute_tools/  tests/unit/core/
tests/unit/agent/tune_ml_hyperparam_agent/
  -> 4192 passed, 3 skipped, rc=0, 325.28s
```

Verdict read from the log file, never a wrapper exit status.

**No local full unit suite was run.** §8 plans none, and the blast radius
is three production files — one of which (`core/sandbox_executor.py`) is
comment-only. CI runs the full suite and did so on the exact head.

**Static:** `ruff check` and `ruff format --check` clean repo-wide (830
files).

**Exact-head CI — verified on the code head:**

| | |
|---|---|
| PR | **#203** |
| run | `31673670764` |
| `headSha` | `9e6dd4e707510cb826b4c81fb3c9bbfcaab7ca77` |
| PR `headRefOid` | `9e6dd4e707510cb826b4c81fb3c9bbfcaab7ca77` |
| local `HEAD` | `9e6dd4e707510cb826b4c81fb3c9bbfcaab7ca77` |
| conclusion | **success** (13m29s) |

Three-way identity confirmed; every SHA read from `git rev-parse` or the
GitHub API, never hand-extended from a short form.

**The first attempt failed and is preserved, not overwritten.** Run
`31672711999` on `8c910cf8`: 8638 passed, 23 skipped, **5 errors** — the
portability defect in §13.11a. It is recorded because a PR whose history
shows only the green run hides the fact that the local evidence was
insufficient.

This closing docs commit takes its own CI pass; that verification is
reported to the operator rather than embedded here, since a commit cannot
contain its own SHA.

---

## 14. Final status

**PR 02b — IMPLEMENTATION COMPLETE / READY FOR OPERATOR REVIEW.
NOT MERGED.**

Ladder: **CP0 → CP-B1 → Checkpoint A → Checkpoint B → Checkpoint C →
Checkpoint D — all PASS.** Eleven mutations attempted across the five
evidence rungs; **eleven caught, none survived.**

**The selection capability is COMPLETE.** Neither item below blocks it;
both are pre-existing residue outside the migrated SampleSet data flow.

Carried forward for the parent to route:

1. **§13.9** — a contrast topology is misread as a partial DataScope.
   `validate_runtime_config(..., dataset=TIDMAD)` binds the singleton at
   function-definition time (so no profile binding can reach it), and the
   HealthGate validator reads the ambient profile, so the two disagree.
   **Outside the migrated SampleSet data flow**: selection receives the raw
   `DataScope` and resolves it against the explicit profile. Under the
   default `health_gate_enabled=True` this pre-existing residue can block a
   non-TIDMAD run at startup.
   - runtime/task-binding + full-scope comparison → candidate **Step 10**
     (orchestration/task-binding);
   - `validate_health_gate_files_against_scope` → **Step 08** consumer-side;
   - exact ownership must be confirmed by those detailed designs from their
     own source audits.
   - **NOT PR 02c. NOT Step 06.** Both were proposed by an earlier revision
     and are refuted by the source audit (§13.9 ownership disposition).
2. **§13.1** — `validate_sample_set` remains TIDMAD-bounded, so 02b's
   capability holds for `num_files <= 20`. No worse than before 02b.
   **Ownership UNDETERMINED**; the earlier "02c" rationale was factually
   wrong and is corrected in §13.1.

### 14.1 Operator disposition of the §13.12 sequencing deviation

**ACCEPTED — operator decision, 2026-08-13.**

- Checkpoint B was declared PASS before its frozen real-tuner contrast
  criterion had evidence;
- that criterion was subsequently proven at Checkpoint C;
- **zero production-code change** occurred between the B4 executable state
  (`e2d058ef`) and the Checkpoint-C executable state (`6f14dcdb`) —
  mechanically verified: `git diff e2d058ef 6f14dcdb` excluding
  `tests/` and `docs/` is empty;
- the real-tuner + `num_files`-only contrast property was therefore
  ultimately proven on the **same** production implementation.

Classified as an **evidence-ordering deviation**, not a substantive
frozen-contract violation. No re-run was required or performed.

> **This is not a precedent.** It does not create permission to declare a
> checkpoint before its evidence exists. The deviation was accepted only
> because the production tree was provably identical across the gap.

Gate 1 not required (§7). **Gate 2 NOT RUN — Step-level, owned by
finalizer 02c.**
