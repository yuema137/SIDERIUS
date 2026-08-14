# Step 05a — Tuner data selection & sample-set construction — detailed design

Part of **Step 05** (roadmap §15 step 5, §7b). Step 05's three submodule
designs (`step_05a_*`, `step_05b_*`, `step_05c_*`) **jointly constitute the
Step-05 acceptance entry** per the frozen naming convention (roadmap §19).
The Step-level completion contract lives in roadmap **§15.1a**.

| Field | Value |
|---|---|
| Status | **FINAL PR-LEVEL DESIGN — READY FOR OPERATOR FREEZE. Not frozen. Implementation NOT authorized.** |
| Design base | `13b08550` — master after Step 04 Checkpoint E (04a `6458dd95`, 04b `096f2dbb`) |
| Decomposition | **ONE PR** — operator decision 2026-08-14 (§2.1). No `pr_05a_*` child doc |
| Depends on | **Step 02** (Dataset Profile) only |
| Blocks | nothing — see §7 |
| Roadmap row | §15.1 `§7b Tuner data selection` |
| This document is | the detailed PR design → the frozen semantic contract after approval → the live implementation ledger (§19) |
| Frozen on approval | §1 capability · §2 residue census (as design evidence) · §2.1 one-PR decomposition · §6 + §6.1 compatibility · §8 the single rung and its three subcases · §9 Checkpoint-C property · §12 Gate disposition · §16 stop conditions · §17 Definition of Done |
| NOT frozen | exact Git commit count · helper structure · source line numbers · test-file decomposition · exact mutation implementation · resolver call counts |

---

## 0. Why this design is much smaller than the roadmap predicted

The roadmap's §7b entry was written before Step 02 landed. Re-auditing the
production tuner at `13b08550` shows **Step 02b/02c already delivered the
capability §7b was created to deliver.**

```text
Previous assumption (roadmap §7b):
  "Couplings: DATASET_CONFIG import (:76), anchors-required-in-trial
   (:3800-3808), divisibility validation (:1099-1128), legacy single-file
   fallback (:4428-4433). Target: consume §4's resolved profile; zero
   direct singleton reads."

Audit evidence at 13b08550:
  ml_hyperparameter_tune_agent.py:4425-4448 already resolves the run
  profile ONCE and passes it EXPLICITLY to BOTH construction sites:

      run_profile = resolve_dataset_profile()
      train_sample_set = build_sample_set(..., profile=run_profile)
      eval_sample_set  = build_sample_set(..., profile=run_profile)

  with an in-source comment naming this as the Step-02b change and its
  two consequences. `anchor_selection_files=[0, 10, 19]` moved into
  `DatasetProfile` at Step 02c (dataset_config.py:487, :586). Seeds and
  ordering resolve through `ordering.py` (V19 PR 2), not through dataset
  semantics.

Corrected understanding:
  The ambient-singleton defect in SampleSet CONSTRUCTION is closed. What
  survives is a strictly smaller residue: five reads of the module-level
  TIDMAD singleton that sit on the tuner's *validation, scope and
  accounting* path rather than its construction path.

Implementation consequence:
  05a is a residue-closure PR, not the selection redesign §7b described.
  Its honest capability is stated in §1 and deliberately does not claim
  the Step-02b work.
```

**This design does not re-litigate Step 02.** It finishes Step 02's
consumer migration inside the tuner.

## 1. Observable final capability

> Every dataset fact the tuner uses to **validate, scope and account for**
> an attempt comes from the **run-resolved `DatasetProfile`** — the same
> object already threaded into sample-set construction — instead of the
> module-level `TIDMAD` singleton. A run bound to a non-default topology
> can no longer be validated, scoped or accounted against TIDMAD's numbers
> while selecting against its own.

**Deliberately NOT claimed:**

- not that sample-set *construction* becomes profile-driven — Step 02b did
  that, and this PR must not re-assert it as its own;
- not any change to strategy semantics, seeds, ordering, or portions;
- not metric, policy, resource or execution genericity.

## 2. Source census — the complete residue

Every module-level `DatasetConfig` singleton read in the tuner at
`13b08550` (`from execute_tools.dataset_config import TIDMAD as
DATASET_CONFIG`, `:76`):

| Site | Read | Path | Consequence under a contrast profile |
|---|---|---|---|
| `:1090` | `_validate_data_config(dataset_config=DATASET_CONFIG)` default arg | sample-shape **legality** | divisibility validated against TIDMAD's `psd_segment_length`; a legal config for the run's own topology can be rejected, or an illegal one accepted |
| `:2731` | `DATASET_CONFIG.num_files` → `full_scope=list(range(...))` | run-invariant **stamping/validation** | full-scope identity computed from the wrong file count |
| `:3657` | `DATASET_CONFIG.num_files` → `scope_is_partial` | **partial-scope** detection | a full scope can be mis-classified as partial (or vice versa), changing sampling legality |
| `:4465` | `DATASET_CONFIG.segments_per_file` | legacy `single_file` **segment accounting** | record/reflector segment counts wrong |
| `:4470` | same, eval side | legacy `single_file` accounting | same |

`_validate_data_config` already delegates the legal-value enumeration to
`dataset_config.valid_segmentation_sizes()` (`:1114`), so the **rule** is
already owned by Step 02's authority — only the **object it is asked about**
is ambient.

**Reachability of the legacy path.** `mode = "single_file"` is reached when
`trial_allowed` is false (`:4294-4298`), and `trial_allowed =
agent_input.is_trial` (`:3719`) is an operator CLI flag. The path is
**live legacy, not dead** — it must be migrated or explicitly recorded, not
deleted as unreachable.

### 2.1 Decomposition decision — 05a is ONE PR (operator decision, 2026-08-14)

**05a is not split**, and specifically not into child PRs for legality,
startup/full-scope, partial-scope, legacy `single_file` accounting, or profile
threading. There is **no `pr_05a_*` child document**; this file is the
detailed PR design, the frozen semantic contract after approval, and later the
live implementation ledger.

The five residue sites share **everything a split would need to separate**:

| Dimension | Shared value |
|---|---|
| semantic authority | the one run-bound `DatasetProfile` |
| consumer family | tuner validation / scope / accounting |
| compatibility family | TIDMAD `TrialConfig` / `SampleSet` / validation / accounting parity |
| generic capability | no tuner dataset semantic is read from ambient TIDMAD state |
| rollback boundary | the tuner module + directly affected tests |

**No residue group delivers an independently useful capability.** A partial
merge would ship an incoherent state — selection using the run profile while
validation and accounting still use TIDMAD — which is precisely the
half-migrated architecture this PR exists to eliminate.

That the startup sites (`:2731`, `:3657`) and the loop sites (`:1090`,
`:4465`, `:4470`) live in different regions of a large function is **not** a
decomposition argument; it is an implementation-ordering detail (§17 M2/M3).

## 3. Authority map

| Value | Disposition | Why |
|---|---|---|
| `psd_segment_length`, `segments_per_file`, `num_files` | **DERIVE** from the run-resolved `DatasetProfile.dataset` | Step 02 already declares them; the tuner must consume, not re-import |
| the divisibility rule itself | **already DERIVE** (`valid_segmentation_sizes()`) — unchanged | Step 02 owns it |
| strategies, portions, seeds, ordering | **KEEP RUNTIME / POLICY** | framework mechanics, not task semantics |
| `file_index` legacy field | **KEEP RUNTIME (legacy)** — record-only | a §7a/record concern, not a dataset fact |

**No new configuration field is created.** This PR only changes *which
already-declared object* five call sites read.

## 4. Upstream authorities consumed / first production consumer

Consumes **Step 02's `DatasetProfile`**, already resolved at `:4430`.
First production consumer is the **tuner's own validation/scope/accounting
path** — a consumer that exists today and is exercised by every run.

The design's one real structural question: `run_profile` is currently bound
*inside* the round loop (`:4430`), while `:2731` and `:3657` run at
**startup**, before the loop. The frozen contract for resolving that is
**semantic**:

```text
- implementation establishes or reuses ONE run-bound DatasetProfile
  semantic value;
- startup consumers and loop consumers use that SAME run binding;
- no 05a consumer performs an independent ambient
  resolve_dataset_profile() / TIDMAD-singleton resolution.
```

The **number of internal resolver invocations is NOT the frozen contract.**
An implementation that memoizes, re-enters, or re-derives the same bound
value is conforming; one that lets any consumer reach an *independently
resolved* value is not — that is the ambient-resolution defect Step 02b
removed. An exact call-count assertion remains available as an optional
implementation-time test technique (§10.2, §8.1), never as the contract.

## 5. Scope / non-goals

**In scope**: the five sites in §2; threading a single run-scoped profile to
startup and loop regions; deleting the `DATASET_CONFIG` import when the last
read is gone.

**Non-goals**: `build_sample_set` internals; strategy/portion/seed/ordering
semantics; `TrialConfig` field set; anchors; DataScope semantics; anything in
05b or 05c; any planner/policy or metric surface.

## 6. Stage-A compatibility surfaces

| Surface | Criterion | Oracle status |
|---|---|---|
| `trial_config` serialized JSON | **deep-equal** under TIDMAD | EXISTING — Step-00/Step-02 baselines |
| train/eval `SampleSet` identities | **deep-equal** under TIDMAD | EXISTING |
| `_validate_data_config` accept/reject + diagnostic text | **byte-identical** | **MISSING — Checkpoint 0 captures it** |
| `scope_is_partial` / stamped full-scope invariants | **identical** | EXISTING (run-invariants lock) |
| legacy `single_file` segment counts | **identical** | **MISSING — Checkpoint 0 captures it** |

Checkpoint 0 adds only the two missing captures. It must **not** duplicate
Step-02's Dataset Profile baselines.

### 6.1 Configuration / replay compatibility — no change at all

Per the Step-05 cross-cutting invariant (roadmap §15.1a):

| Surface | 05a effect |
|---|---|
| `DatasetProfile` schema | **unchanged** — consumed only |
| `TrialConfig` schema / required keys / defaults | **unchanged** |
| model / loss / train config | **unchanged** — not touched |
| serialization + loading | **unchanged** |
| CLI / argv | **unchanged** |
| replay of a stored run | **preserved — no migration** |

Stage-A property: *a representative historical TIDMAD serialized
configuration loads under post-05a code **without migration** and resolves to
the same effective model/loss/train/tuner semantics.* Provable by
deterministic config resolution — no rerun required.

05a creates **no new config field and no new authority**; it changes only
which already-resolved object five sites read.

## 7. Dependencies

Depends on **Step 02 only**. **Independent of 05b and 05c**: 05b consumes
`SampleSet` *values* (`resolve_training_workload(sample_set, …)`), whose shape
this PR is required to leave byte-identical; 05c consumes execution
transport. Neither reads the five sites above.

`05a → 05b → 05c` is a **preferred implementation order** (lowest risk
first), **not** a dependency. Any order is semantically legal.

## 8. Stage-B — ONE rung, three atomic subcases

**Rung `05a-B` — run-bound `DatasetProfile` consumption.** One capability,
proven by three subcases so that a single large alternate profile cannot hide
a partially-derived site. **The subcases are not separate PRs and not separate
rungs.**

| Subcase | Varies ONLY | Held fixed | Proves |
|---|---|---|---|
| **B1 — legality** | the profile fact governing segmentation legality (`psd_segment_length`) | `num_files`, `segments_per_file`, strategy/policy, ordering, all other task semantics | `_validate_data_config` follows the bound profile |
| **B2 — scope** | `num_files` | legality-relevant topology, `segments_per_file`, strategy/policy, ordering | **both** full-scope stamping/validation **and** partial-scope determination follow the bound profile |
| **B3 — accounting** | `segments_per_file` | `num_files`, legality-relevant topology, strategy/policy, ordering | driving the **live legacy `single_file` path**, train and eval segment counts follow the bound profile |

Why three and not one: a profile that changed all three facts at once would
still pass if *any two* sites were migrated and the third happened to agree —
the classic partial-derivation false green. Each subcase is asserted against
its own baseline.

Reuse Step-02 fixture machinery where it exists. This PR proves the **tuner
consumes** the profile; asserting that a contrast profile is constructible is
Step 02's test, not this one.

**Ordering / `shuffle` acceptance criteria are deliberately NOT applied.**
The general PR-design standard asks for validation of the visited
sample/file sequence and of default-`shuffle` seed behavior. Those criteria
belong to an ordering-semantics change; 05a's frozen scope **excludes**
strategy, portion, seed and ordering changes (§1, §3, §5), and ordering
already resolves through `ordering.py` (V19 PR 2), not through dataset
semantics. Applying them literally would broaden 05a past its own contract
and manufacture work its capability does not need.

What 05a *does* inherit from that standard is the underlying intent —
**assert observable identity, not a configuration value.** Checkpoint A
therefore pins the resulting `SampleSet` identities and the serialized
`TrialConfig`, which is the selection-observable this PR could plausibly
disturb. If implementation finds that any 05a change can move a visited
sequence, that is a **scope contradiction and a MATERIAL STOP** (§16), not a
new test to add.

### 8.1 Mutation / adversarial evidence — by semantic family

Required evidence is **family-level**, not one mutation per physical line.
Minimum: reintroducing ambient behavior must red for each of

```text
legality            (psd_segment_length)
scope               (num_files)
accounting          (segments_per_file)
```

plus the **transport failure** that no per-site mutation catches: *one
consumer independently re-resolves the ambient profile / TIDMAD singleton
instead of consuming the run-bound value.*

Exact mutation implementation is **not frozen**. Three family-level mutations
plus the transport mutation are sufficient if each yields unique evidence;
five separate campaigns are not required. Observed failures are recorded in
the ledger at implementation time.

## 9. Checkpoint C — live integration, minimum scenario set

**Frozen property**: Checkpoint C uses the **minimum deterministic
production-path scenario set** necessary to prove all 05a semantic families
through **real tuner control flow**. A helper-only test cannot discharge it.

One tuner invocation is **not** required to exercise mutually exclusive
branches — `trial`/`formal` and `single_file` are selected by disjoint
control flow (`:4294-4298`), so demanding a single invocation would be a
test-design error, not rigor.

Expected source-grounded shape:

| Scenario | Path | Proves |
|---|---|---|
| **C1 — normal / trial** | bound contrast profile → real tuner startup + validation + scope path | legality and full/partial-scope behavior follow the bound profile |
| **C2 — live legacy `single_file`** | operator-visible non-trial path → real tuner accounting path | train/eval segment counts follow the bound profile |

If current source lets one scenario reach every family, implementation may use
one. If two are required by mutually exclusive control flow, **the two
scenarios still constitute ONE Checkpoint C** — not two checkpoints and not
two PRs.

Deterministic throughout: **no LLM, no training, no GPU, no Gate.**

## 10. Failure classes

1. A site keeps reading the singleton → silent TIDMAD legality under another
   topology (the defect this PR closes).
2. **Ambient re-resolution** — a site calls `resolve_dataset_profile()` or
   reads the `TIDMAD` singleton itself instead of receiving the run-scoped
   object. Passes a naive test while restoring the Step-02b defect.

   **The frozen property is semantic, not a call count:**

   ```text
   - every 05a consumer USES ONE run-bound DatasetProfile semantic value;
   - no 05a consumer performs an independent ambient resolution
     (resolve_dataset_profile() or the TIDMAD singleton);
   - startup consumers and loop consumers agree on the SAME run binding.
   ```

   An exact resolver-invocation count is **not** the contract. Implementation
   may use a call-count assertion if it turns out to be the strongest
   reachability mutation, but it is a test technique, not the invariant —
   freezing the count would pin choreography and forbid a legitimate
   memoized or re-entrant implementation.
3. The legacy `single_file` accounting is "fixed" by deleting the branch →
   silent behavior change on a live operator path.
4. A dataset fact is copied into `TrialConfig` as a new field → a second
   authority.

## 11. Test disposition

| Test family | Verdict |
|---|---|
| Step-02 profile-injection tests | **KEEP** — upstream, untouched |
| tuner `_validate_data_config` tests | **UPGRADE** — parameterize on an injected profile |
| any pin asserting `DATASET_CONFIG` is read | **REWRITE** — it defends the defect |
| SampleSet/TrialConfig baselines | **KEEP** — the parity oracle |

## 12. Gates

| Gate | Decision | Flip condition |
|---|---|---|
| **Gate 1** | **NOT REQUIRED** — no LLM-visible surface changes | any rendered prompt byte or `LLMBridge` kwarg changes |
| **Gate 2** | **NOT REQUIRED** — no execution, training, inference, scoring or resource semantics change; the surfaces are validation/scope/accounting, all deterministic | a real execution or admission behavior becomes unprovable deterministically |

## 13. Validation budget

Checkpoint 0 captures (2) → focused unit tests on the five sites → the
run-binding guard (§10.2) with a mutation → Checkpoint C → ruff/pyright
→ exact-head CI. **No local full suite. No Gate. No real LLM/GPU.**

## 14. Rollback boundary

`nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py` plus its
directly affected tests. Reverting restores the five ambient reads and
nothing else.

## 15. Convergence-ledger implications

Supplies the **second design** the §14 *Sample-shape legality (divisibility)*
row is waiting for (`§4, §6, §7b`, owner `§4`, "≥2 completed designs"). This
design's finding: the rule is **already** owned by Step 02 and delegated to
`valid_segmentation_sizes()`; only the object was ambient. **Disposition:
RECORD ONLY — no shared legality wrapper.** Threshold met ≠ abstraction
justified.

The §14 *SampleSet type + JSON key coercion* row wants "one consumer design".
05a is **not** that evidence — it does not change SampleSet transport. 05b is
the closer candidate (§15 of that design).

## 16. Stop conditions

- Closing a site requires a new dataset field or a second authority → STOP.
- The legacy `single_file` path cannot be migrated without changing operator
  behavior → surface it; do not delete the branch.
- Threading the run-scoped profile to startup requires re-ordering run phases
  → STOP (phase order is frozen; roadmap §7a/CLAUDE.md).

## 17. Definition of Done — the authoritative checkpoint table

**This table governs.** Where any lower-level milestone or checklist wording
in §18 diverges from it, this table wins.

### CHECKPOINT 0 — pre-edit baselines
- [ ] `_validate_data_config` accept/reject + **exact diagnostic text** baseline captured
- [ ] live legacy `single_file` train/eval segment-count baseline captured
- [ ] both captured **BEFORE** any production edit
- [ ] no duplication of existing Step-02 `DatasetProfile` / `SampleSet` baselines

### CHECKPOINT A — TIDMAD / replay parity
- [ ] `TrialConfig` serialized form **deep-equal**
- [ ] train `SampleSet` identity unchanged
- [ ] eval `SampleSet` identity unchanged
- [ ] validation verdict **and** diagnostic text exact
- [ ] full/partial scope invariants unchanged
- [ ] legacy `single_file` segment counts unchanged
- [ ] a representative historical serialized TIDMAD configuration loads **without migration** and resolves to the same effective model/loss/train/tuner semantics
- [ ] `DatasetProfile` / `TrialConfig` / model / loss / train schemas unchanged

### CHECKPOINT B — generic consumption
- [ ] B1 legality PASS
- [ ] B2 scope PASS
- [ ] B3 accounting PASS
- [ ] each subcase atomic against its own baseline
- [ ] family-level mutation/adversarial evidence reds appropriately (§8.1)
- [ ] no ambient TIDMAD read or independent profile resolution remains in any 05a consumer

### CHECKPOINT C — production path
- [ ] real tuner control flow consumes the bound profile
- [ ] minimum deterministic scenario set reaches every required semantic family
- [ ] no helper-only substitution

### CHECKPOINT D — regression / static
- [ ] directly affected deterministic tests
- [ ] focused tuner integration
- [ ] mutations
- [ ] `ruff check` + `ruff format --check`
- [ ] required static/type checks
- [ ] exact-final-head CI green
- [ ] no local full suite by default

### GATES
- [ ] **Gate 1 NOT REQUIRED** — re-verified; flips only if an unexpected LLM-visible surface changes
- [ ] **Gate 2 NOT REQUIRED** — re-verified; flips only if scope unexpectedly expands into a real execution/resource/admission surface that cannot be proven deterministically

### READY FOR OPERATOR REVIEW
- [ ] Checkpoints 0/A/B/C/D complete
- [ ] Gate disposition re-verified
- [ ] PR opened/updated
- [ ] exact-final-head CI green
- [ ] local HEAD == PR `headRefOid` == successful CI `headSha`
- [ ] working tree clean

### 17.1 Checkpoints are NOT operator pause points

Checkpoints 0/A/B/C/D are **semantic evidence milestones inside ONE
autonomous PR implementation**. They are **not** separate PRs, **not**
approval boundaries, **not** context boundaries, and **not** reasons to stop.

After implementation authorization the agent proceeds autonomously:

```text
inspect -> test -> discover source truth -> record findings/deviations in the
live ledger -> fix ordinary defects -> validate -> continue to the next
checkpoint
```

Only a **MATERIAL STOP** condition (§16) may return early. The operator does
not approve movement between checkpoints.

### 17.2 Implementation-time source re-enumeration

The five-site census (§2) is frozen **as design evidence at base
`13b08550`**. At implementation kickoff, re-enumerate every tuner read of
`DATASET_CONFIG`, the TIDMAD `DatasetConfig` singleton, and every ambient
`resolve_dataset_profile()` call relevant to 05a.

A newly discovered site **MAY be incorporated into 05a** — recorded as a
bounded source finding, not a scope change — when it shares *all four* of:
the same `DatasetProfile` authority, the same validation/scope/accounting
capability, the same rollback boundary, and the same compatibility contract.
**Do not stop merely because a sixth equivalent residue site is found.**

A site that instead owns resource semantics, policy, execution, measurement or
metric lifecycle is **recorded and deferred to its owner**. If ownership is
genuinely ambiguous *and* changes 05a's semantic scope → **MATERIAL STOP**.

## 18. Commit plan — per-commit checklists

**Semantic sequence is frozen; exact Git commit count is NOT.** Also not
frozen: helper structure, source line numbers, test-file decomposition.
Implementation may merge or split engineering commits provided the semantic
sequence, the §17 Definition of Done, the Stage-B subcases, the Checkpoint-C
property and the Gate disposition are unchanged.

Line references below are **reading aids captured at `13b08550`**, not
contracts. Re-read the touched source immediately before each commit.

`[ ]` = not done · `[x]` = done **and** verified with recorded evidence.

---

### M0 — pre-edit baseline capture

**1. Goal.** Capture the two compatibility surfaces that no existing oracle
covers, *before* any production edit, so Checkpoint A can prove the migration
moved nothing. Separate commit because a baseline captured after an edit
proves nothing about that edit.

**2. Scope.**
- New/extended tests under `tests/unit/agent/tune_ml_hyperparam_agent/`.
- **Non-goals**: no production file changes at all; no duplication of Step-02
  `DatasetProfile`/`SampleSet` baselines; no new fixtures for facts Step 02
  already pins.
- Depends on: nothing.

**3. Implementation plan.**
- [ ] Re-read `_validate_data_config` in full and identify which raising
      branches are **`DatasetProfile`-dependent** — i.e. whose verdict or
      diagnostic can change when the profile object changes.
- [ ] Capture the **minimum representative** legality baseline: at least one
      accepting case, one rejecting case, and the **exact diagnostic text**
      of the rejecting case.
- [ ] If inspection identifies **multiple genuinely distinct
      profile-dependent failure classes**, capture one case per distinct
      class — and only those.
- [ ] Re-read the legacy `single_file` accounting block and confirm how the
      path is reached from `agent_input.is_trial`.
- [ ] Capture live legacy `single_file` train/eval segment counts (a
      **separate** baseline, preserved independently of the legality one).
- [ ] Confirm by inspection that neither capture restates a Step-02 baseline.

**Explicitly NOT required**: baselining every branch of
`_validate_data_config` merely because it exists. A branch whose behavior
cannot move when the profile object changes is not evidence for this PR — it
is decoration, and CLAUDE.md's test-economy rule forbids it.

**4. Validation plan.**
- Unit: the two new baselines pass on unmodified production code.
- Integration/pseudo: none required at M0.
- Negative: at least one **rejecting** legality case is captured, not only the
  accepting one — a baseline of the happy path alone cannot detect a
  migration that silently stops rejecting.
- Backward-compat / default-parity: this commit *is* the parity instrument.
- Gate: **none**.

**5. Acceptance criteria.**
- [ ] Both baselines pass against production code that is **byte-unchanged**
      (`git status` shows no production file modified in this commit).
- [ ] The rejecting legality case pins **exact diagnostic text**, not just the
      exception type.
- [ ] At least one accepting and one rejecting legality case are pinned, and
      every **distinct profile-dependent failure class** found by inspection
      has one case.
- [ ] No baseline covers a validation branch that cannot move when the
      `DatasetProfile` object changes.
- [ ] The accounting baseline is produced through the **live** `single_file`
      path, not by calling the accounting expression directly.

**6. Failure and edge cases.**
- The `single_file` path cannot be reached deterministically in a unit test →
  record the reachability route found; if it genuinely requires the tuner
  loop, that capture belongs in the Checkpoint-C scenario harness instead, and
  the design is updated to say so.
- A diagnostic embeds a machine-specific path → normalize deliberately and
  record the normalization; never pin an absolute path.

**7. Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/agent/tune_ml_hyperparam_agent -q`
- [ ] Record: test count, wall time, and explicit confirmation that zero
      production files were modified.

**8. Commit boundary.** Tests only. Independently reviewable as "what we
promise not to change". No production edit, no cleanup, no follow-up work.

---

### M1 — establish the run-bound profile at run scope

**1. Goal.** Create the single run-bound `DatasetProfile` value that every
later commit consumes, **without changing phase order** and without changing
any behavior. Separate commit because it is the one structural change; if a
later behavioral commit regresses, this boundary is independently reviewable.

**2. Scope.**
- `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py` — the
  earliest existing run-scope point that already runs before both the startup
  consumers (`≈:2731`, `≈:3657`) and the loop consumers.
- **Non-goals**: no consumer migrated yet; **run-phase order unchanged**; the
  existing Step-02b resolution at `≈:4430` keeps producing the same value;
  no new config field; no `TrialConfig` change.
- Depends on: M0 (baselines must exist first).

**3. Implementation plan.**
- [ ] Re-read the tuner's run-scope prologue and identify the earliest point
      that precedes **both** consumer regions without moving any phase.
- [ ] Establish the run-bound profile value there.
- [ ] Confirm the loop-scope binding at `≈:4430` resolves to the **same**
      semantic value rather than an independent ambient resolution.
- [ ] Confirm no phase, no ordering, and no side effect moved.

**4. Validation plan.**
- Unit: M0 baselines still pass unchanged.
- Integration/pseudo: focused tuner wiring tests still pass.
- Negative: none specific to M1.
- Backward-compat: `TrialConfig` serialization and both `SampleSet`
  identities deep-equal (Checkpoint A subset).
- Gate: **none**.

**5. Acceptance criteria.**
- [ ] Zero behavior change: every M0 baseline and every existing tuner test
      passes without modification.
- [ ] The startup region and the loop region observe the **same** profile
      value — asserted semantically (same binding), **not** by pinning a
      resolver call count (§10.2).
- [ ] Run-phase order is provably unchanged.
- [ ] No consumer has been migrated yet — `DATASET_CONFIG` still has five
      readers.

**6. Failure and edge cases.**
- The earliest safe point precedes profile availability → **STOP** rather
  than moving a phase (§16).
- Binding at run scope changes when the profile is first resolved relative to
  a validation that could fail → record and verify the failure ordering is
  preserved; a run that used to fail before resolution must still do so.

**7. Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/agent/tune_ml_hyperparam_agent -q`
- [ ] Record counts, wall time, and confirmation that no test needed editing.

**8. Commit boundary.** One structural addition, zero behavior change,
independently revertible. No consumer migration bundled in.

---

### M2 — migrate the startup scope consumers

**1. Goal.** Make full-scope stamping/validation and partial-scope detection
read the run-bound profile. Separate from M3 because these two sites run at
**startup**, before the round loop, and their failure mode (wrong run
invariants stamped) differs from the loop sites'.

**2. Scope.**
- `ml_hyperparameter_tune_agent.py` `≈:2731` (`full_scope=list(range(...))`)
  and `≈:3657` (`scope_is_partial`).
- **Non-goals**: legality and accounting untouched; no DataScope semantic
  change; the run-invariants lock format unchanged.
- Depends on: M1.

**3. Implementation plan.**
- [ ] Re-read both sites and the `validate_stamped_invariants` /
      `validate_runtime_config` contracts they feed.
- [ ] Replace both `DATASET_CONFIG.num_files` reads with the run-bound value.
- [ ] Confirm the run-invariants lock content is unchanged under TIDMAD.

**4. Validation plan.**
- Unit: existing scope/invariant tests pass unchanged.
- Integration: run-invariants lock parity under TIDMAD.
- Negative: a partial scope is still detected as partial; a full scope still
  as full.
- Backward-compat: an existing workspace lock still validates — **no
  migration**.
- Gate: **none**.

**5. Acceptance criteria.**
- [ ] Stage-B **B2** passes: under a contrast `num_files`, both full-scope
      stamping and partial-scope determination follow the bound profile.
- [ ] Under TIDMAD the stamped invariants are **byte-identical** to M0/M1.
- [ ] A pre-existing run-invariants lock validates without migration.
- [ ] **No startup/scope consumer reads ambient TIDMAD state** — asserted
      semantically, not by an exact reader count. Any ambient reads still
      present are confined to the 05a semantic families not yet migrated at
      this point (legality, legacy accounting), per the implementation-time
      census (§17.2). An exact intermediate count is deliberately **not**
      pinned: §17.2 permits absorbing a newly found equivalent site, which
      would make any such number wrong for a legitimate reason.

**6. Failure and edge cases.**
- Scope mismatch between the bound profile and a resumed run's stamped lock →
  must **fail closed** with the existing diagnostic; this PR must not soften
  the mismatch into a warning.
- A scope declared against a larger `num_files` than the bound profile has →
  the existing out-of-range rejection must still fire.

**7. Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/agent/tune_ml_hyperparam_agent tests/unit/execute_tools -q`
- [ ] Record counts, wall time, B2 result, and lock-parity evidence.

**8. Commit boundary.** Two sites, one failure family, independently
revertible. No legality or accounting change bundled in.

---

### M3 — migrate legality + legacy accounting; remove the import

**1. Goal.** Complete the capability: legality validation and legacy
`single_file` accounting read the run-bound profile, and the module-level
TIDMAD singleton import is gone. Separate from M2 because these are loop-scope
consumers with different failure families, and because the import removal is
only legal once the last reader is migrated.

**2. Scope.**
- `ml_hyperparameter_tune_agent.py` `≈:1090` (`_validate_data_config` default
  arg), `≈:4465`, `≈:4470` (legacy accounting), and the `≈:76` import.
- **Non-goals**: the divisibility **rule** is unchanged — it already delegates
  to `valid_segmentation_sizes()`; the legacy branch is **migrated, not
  deleted**; no strategy/portion/seed/ordering change.
- Depends on: M1, M2.

**3. Implementation plan.**
- [ ] Re-read `_validate_data_config` and decide how the profile reaches it
      without a new authority — prefer threading the resolved object over a
      module default.
- [ ] Migrate the legality site.
- [ ] Migrate both legacy accounting sites, preserving the branch.
- [ ] Remove the `DATASET_CONFIG` import and confirm zero readers remain.

**4. Validation plan.**
- Unit: M0 legality and accounting baselines pass **unchanged**.
- Integration: focused tuner integration.
- Negative: the rejecting legality case still rejects with the **same**
  diagnostic; whitespace/None-shaped inputs behave as before.
- Backward-compat: legacy `single_file` remains reachable and behaves
  identically under TIDMAD.
- Gate: **none**.

**5. Acceptance criteria.**
- [ ] Stage-B **B1** passes: legality follows the bound profile.
- [ ] Stage-B **B3** passes: through the **live** legacy path, both segment
      counts follow the bound profile.
- [ ] M0 baselines pass **byte-identically** under TIDMAD — same verdicts,
      same diagnostic text, same counts.
- [ ] **Terminal semantic property** — no 05a consumer either (a) reads the
      TIDMAD `DatasetConfig` singleton directly, **or** (b) independently
      resolves an ambient `DatasetProfile`.
- [ ] A zero-hit `grep DATASET_CONFIG` over the tuner is recorded as
      **supporting mechanical evidence only**. It is not the property: a
      renamed alias, a re-export, or an `import execute_tools.dataset_config`
      module-attribute access would leave the grep clean while the defect
      survives, so the guard must assert the semantic property above.
- [ ] The legacy `single_file` branch still exists and is still reachable.

**6. Failure and edge cases.**
- Threading into `_validate_data_config` tempts a `TrialConfig` field for the
  dataset fact → **forbidden** (§3); that would be a second authority.
- The legacy branch has no bound profile in some call path → **STOP**; do not
  reintroduce an ambient default as a fallback.
- Removing the import breaks an unrelated module-level reference → re-enumerate
  (§17.2) rather than leaving a partial migration.

**7. Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/agent/tune_ml_hyperparam_agent tests/unit/execute_tools -q`
- [ ] Record counts, wall time, B1/B3 results, and the zero-hit grep output.

**8. Commit boundary.** Completes the capability; independently revertible
back to M2. No guard/contrast infrastructure bundled in.

---

### M4 — run-binding guard, Stage-B subcases, Checkpoint C

**1. Goal.** Prove the capability holds and cannot silently regress. Separate
from M1-M3 so a reviewer reads the behavior change and the "what must never
regress" decision independently.

**2. Scope.**
- New/extended tests: the B1/B2/B3 subcases, the run-binding guard, and the
  Checkpoint-C scenario set.
- **Non-goals**: no production behavior change in this commit.
- Depends on: M3.

**3. Implementation plan.**
- [ ] Add the run-binding guard (§10.2): one run-bound value, no ambient
      independent resolution, startup and loop agreeing — asserted
      semantically.
- [ ] Add B1/B2/B3 as subcases of one rung, each against its own baseline.
- [ ] Build the minimum Checkpoint-C scenario set (C1, and C2 if control flow
      requires it).
- [ ] Run the family-level mutations (§8.1) and record each observed failure.

**4. Validation plan.**
- Unit: guard + three subcases.
- Integration: Checkpoint-C scenarios through real tuner control flow.
- Negative: the guard must **not** fire on the legitimate single run binding.
- Backward-compat: `pb*`-style prompt goldens and `TrialConfig`/`SampleSet`
  parity unchanged by this commit (it adds no production change).
- Gate: **none**.

**5. Acceptance criteria.**
- [ ] Reintroducing ambient behavior reds for **each** of legality, scope and
      accounting — three recorded mutations.
- [ ] The **transport** mutation (a consumer re-resolving ambiently) reds.
- [ ] Every mutation is restored and the tree re-verified green.
- [ ] Checkpoint C runs through real tuner control flow, not a helper.
- [ ] No production file is modified by this commit.

**6. Failure and edge cases.**
- A mutation **survives** → inspect the test architecture before adding an
  assertion; record the classification (real gap / equivalent / unreachable /
  wrong fixture).
- The mutation target is matched at more than one site → assert the site count
  before mutating; a wrong-site mutation proves nothing (the Step-04b
  precedent).
- C1 alone reaches every family → use one scenario and record why C2 is
  unnecessary.

**7. Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/agent/tune_ml_hyperparam_agent tests/unit/execute_tools -q`
- [ ] Record counts, wall time, each mutation's expected vs observed result,
      and the restored-green re-run.

**8. Commit boundary.** Evidence only. Reviewable as "what must never
regress". No production change, no unrelated cleanup.

---

### M5 — terminal regression, CI, ledger closeout

**1. Goal.** Establish the terminal evidence and leave the PR reviewable.

**2. Scope.** Design-doc ledger (§19), directly affected docs, CI iteration.
**Non-goals**: no new capability; no scope expansion.
Depends on: M4.

**3. Implementation plan.**
- [ ] Synchronize §19 (implementation ledger) with actual findings, deviations and evidence.
- [ ] Run Checkpoint D from a **clean tree**.
- [ ] Open/update the PR; drive exact-final-head CI green.
- [ ] Verify local HEAD == PR `headRefOid` == successful CI `headSha`.

**4. Validation plan.**
- Checkpoint D as defined in §17. Exact-head CI is the broad regression
  authority. **No local full suite by default.** No Gate.

**5. Acceptance criteria.**
- [ ] Checkpoint D fully green, verdict read from the **log file**, not a
      wrapper's exit status.
- [ ] The three identities match, each read rather than reconstructed.
- [ ] Working tree clean; ledger records every deviation.

**6. Failure and edge cases.**
- Full-suite/preflight guard reds on a dirty tree → commit the checkpoint
  first; never relax the guard.
- CI fails on an environment-only check → diagnose and fix autonomously; it is
  not a stop condition.

**7. Verification commands and evidence.**
- [ ] Checkpoint-D command set, with counts and wall time recorded.
- [ ] CI run id and exact `headSha`.

**8. Commit boundary.** Documentation and CI-driven fixes only.

## 19. Implementation ledger

*(empty — populated at implementation kickoff)*

## 20. Remaining operator decisions

**None.** The only judgement call — whether the live legacy `single_file`
accounting is migrated or recorded — is resolved from source in §2
(live, therefore migrated).
