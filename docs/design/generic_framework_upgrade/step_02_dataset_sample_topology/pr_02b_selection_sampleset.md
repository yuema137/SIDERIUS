# PR 02b — Selection & SampleSet semantics (Step 02, child 2 of 3)

## Status

**DESIGN — READY FOR OPERATOR FREEZE (revision 2, 2026-08-14).
NOT YET FROZEN. IMPLEMENTATION NOT AUTHORIZED.**

Revision 2 applies the operator review of 2026-08-14: Q1/Q2/Q3 answered
(§11), and four narrow corrections applied — B1 pins the live contract
instead of freezing a latent bug, B3 freezes observable properties rather
than helper shape, B2 is Stage A only, and B4 is strictly single-axis.

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

**FROZEN production round-trip contract — pin exactly this:**
- [ ] the SampleSet producer uses **integer** keys;
- [ ] the JSON boundary emits **string** keys (per JSON), at both
      `core/sandbox_executor.py` sites;
- [ ] value lists are unchanged across the round trip;
- [ ] the **LIVE** production consumer converts keys **numerically**,
      preserving current selection identity;
- [ ] `validate_sample_set`'s existing coercion/validation behaviour at
      the boundary (pin, do not change).

**LATENT finding — record, do NOT freeze:**
- [ ] record in the ledger that `TIDMADDataset`'s `sample_set` branch
      sorts post-JSON keys **lexicographically**, that a source audit
      finds **no production caller reaches that branch**, and that 02b
      does not fix it.
- [ ] **Do NOT assert its exact ordering** (`0, 1, 10, 11, …`) anywhere.
      Freezing an unreachable bug's output would promote it into a
      compatibility promise nobody can later change — the opposite of
      what a capture-first baseline is for.

**Stop condition:** if the current-source audit finds that branch **is**
production-reachable, **STOP and report** — the classification has
changed and this is a production defect, not a latent one.

- [ ] Mutation evidence targets *production round-trip / key-coercion
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
- [ ] Re-read both `json.dump(sample_set, …)` sites and
      `validate_sample_set` before editing.
- [ ] Establish the OBSERVABLE contract: both production serialization
      sites obey the same SampleSet boundary contract, and both emit
      byte-identical TIDMAD JSON.
- [ ] Ensure invalid SampleSets are rejected consistently before/at the
      boundary.
- [ ] Keep B1's production round-trip pin green **unmodified**.
- [ ] Do **not** add a typed wrapper, and do **not** migrate consumers;
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

- [ ] Build the contrast profile varying **only** `num_files`, and assert
      atomicity mechanically against the TIDMAD declaration, as 02a's
      rungs do — a prose promise would not survive a careless edit.
- [ ] Drive the **REAL** tuner → `TrialConfig` → `build_sample_set` path
      and assert the selection follows the **explicit** profile rather
      than the ambient TIDMAD one.
- [ ] Assert the file population is NOT TIDMAD's 20.
- [ ] Confirm the rung reds when a consumer re-hardcodes a TIDMAD count
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

**DESIGN — READY FOR OPERATOR FREEZE (revision 2, 2026-08-14).
NOT YET FROZEN. IMPLEMENTATION NOT AUTHORIZED.** Implementation begins only after operator freeze and a
filled Implementation Working Rules contract, in a fresh context with its
own Context Continuity v2 handoff — in an isolated worktree **outside
`.claude/`**.
