# Step 05a — Tuner data selection & sample-set construction — detailed design

Part of **Step 05** (roadmap §15 step 5, §7b). Step 05's three submodule
designs (`step_05a_*`, `step_05b_*`, `step_05c_*`) **jointly constitute the
Step-05 acceptance entry** per the frozen naming convention (roadmap §19).
The Step-level completion contract lives in roadmap **§15.1a**.

| Field | Value |
|---|---|
| Status | **PR 05A — COMPLETE / MERGED. CONTEXT CLOSED. CHECKPOINT E COMPLETE.** Merged 2026-08-14 as **`cfb3b1c7`** (squash) from PR **#210**, final head **`5ae37180`**, exact-head CI run **`31837316212`** success. Design content frozen at **`425bfac9`**; freeze marker `1cb0119c`; implementation base `2da399eb`. Terminal evidence in §19. |
| Design base | `13b08550` — master after Step 04 Checkpoint E (04a `6458dd95`, 04b `096f2dbb`) |
| Implementation base | **`2da399eb`** — operator-selected; `1cb0119c` plus the docs-only commit recording the base, and `origin/master` at kickoff. See §19's base reconciliation |
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
- [x] `_validate_data_config` accept/reject + **exact diagnostic text** baseline captured — §19.2
- [x] live legacy `single_file` train/eval segment-count baseline captured — §19.2, counts 200/200 off the persisted record
- [x] both captured **BEFORE** any production edit — `git status --porcelain` showed only the new untracked test file
- [x] no duplication of existing Step-02 `DatasetProfile` / `SampleSet` baselines — §19.2

### CHECKPOINT A — TIDMAD / replay parity
- [x] `TrialConfig` serialized form **deep-equal** — existing TC1b golden oracle, green
- [x] train `SampleSet` identity unchanged — existing oracles green
- [x] eval `SampleSet` identity unchanged — existing oracles green
- [x] validation verdict **and** diagnostic text exact — Checkpoint-0 baseline, byte-identical
- [x] full/partial scope invariants unchanged — run-invariants + DataScope suites green
- [x] legacy `single_file` segment counts unchanged — 200/200
- [x] a representative historical serialized TIDMAD configuration loads **without migration** and resolves to the same effective model/loss/train/tuner semantics — §19.6, 17 passed
- [x] `DatasetProfile` / `TrialConfig` / model / loss / train schemas unchanged — proved statically from the diff (§19.6)

### CHECKPOINT B — generic consumption
- [x] B1 legality PASS — §19.7
- [x] B2 scope PASS — §19.7
- [x] B3 accounting PASS — §19.7
- [x] each subcase atomic against its own baseline — atomicity itself asserted, not only stated
- [x] family-level mutation/adversarial evidence reds appropriately (§8.1) — 5 mutations, all RED, none survived
- [x] no ambient TIDMAD read or independent profile resolution remains in any 05a consumer — transport guard + zero-hit grep

### CHECKPOINT C — production path
- [x] real tuner control flow consumes the bound profile — every test drives `run()`
- [x] minimum deterministic scenario set reaches every required semantic family — C1 + C2, one checkpoint
- [x] no helper-only substitution — nothing calls the migrated helpers directly

### CHECKPOINT D — regression / static
- [x] directly affected deterministic tests — 36 passed
- [x] focused tuner integration — 1978 passed, 1 skipped, from a clean tree
- [x] mutations — 5 applied, all RED, none survived
- [x] `ruff check` + `ruff format --check` — clean repo-wide
- [x] required static/type checks — local pyright NOT RUNNABLE (Node v10.19.0); CI strict pyright is the authority (§19.8)
- [x] exact-final-head CI green
- [x] no local full suite by default — not run

### GATES
- [x] **Gate 1 NOT REQUIRED** — re-verified at the final head; no rendered prompt byte and no `LLMBridge` kwarg is in the diff
- [x] **Gate 2 NOT REQUIRED** — re-verified at the final head; no execution/resource/admission semantics change, every surface deterministic

### READY FOR OPERATOR REVIEW
- [x] Checkpoints 0/A/B/C/D complete
- [x] Gate disposition re-verified
- [x] PR opened — #210
- [x] node doc synchronized as the last pre-merge step (CLAUDE.md) — `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md`, every documented parameter quoted against the merged source
- [x] exact-final-head CI green — run `31837316212` on `5ae37180`
- [x] local HEAD == PR `headRefOid` == successful CI `headSha` — all `5ae37180`, each read
- [x] working tree clean — verified immediately before merge

### MERGED (Checkpoint E)
- [x] operator approved the merge — 2026-08-14
- [x] exact-object re-verified before merging: PR OPEN, `mergeable_state=clean`, no new commit, identity still `5ae37180`
- [x] PR **#210 MERGED** (squash) — merge SHA **`cfb3b1c7`**, 2026-08-14T20:43:19Z
- [x] merge SHA reachable from `origin/master`; squashed tree **byte-identical** to the reviewed head (`git diff 5ae37180 cfb3b1c7` empty)
- [x] governance sync applied (this section, §15.1/§15.1a, §14, README)

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
- [x] Re-read `_validate_data_config` in full and identify which raising
      branches are **`DatasetProfile`-dependent** — i.e. whose verdict or
      diagnostic can change when the profile object changes.
- [x] Capture the **minimum representative** legality baseline: at least one
      accepting case, one rejecting case, and the **exact diagnostic text**
      of the rejecting case.
- [x] If inspection identifies **multiple genuinely distinct
      profile-dependent failure classes**, capture one case per distinct
      class — and only those.
- [x] Re-read the legacy `single_file` accounting block and confirm how the
      path is reached from `agent_input.is_trial`.
- [x] Capture live legacy `single_file` train/eval segment counts (a
      **separate** baseline, preserved independently of the legality one).
- [x] Confirm by inspection that neither capture restates a Step-02 baseline.

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
- [x] Both baselines pass against production code that is **byte-unchanged**
      (`git status` shows no production file modified in this commit).
- [x] The rejecting legality case pins **exact diagnostic text**, not just the
      exception type.
- [x] At least one accepting and one rejecting legality case are pinned, and
      every **distinct profile-dependent failure class** found by inspection
      has one case.
- [x] No baseline covers a validation branch that cannot move when the
      `DatasetProfile` object changes.
- [x] The accounting baseline is produced through the **live** `single_file`
      path, not by calling the accounting expression directly.

**6. Failure and edge cases.**
- The `single_file` path cannot be reached deterministically in a unit test →
  record the reachability route found; if it genuinely requires the tuner
  loop, that capture belongs in the Checkpoint-C scenario harness instead, and
  the design is updated to say so.
- A diagnostic embeds a machine-specific path → normalize deliberately and
  record the normalization; never pin an absolute path.

**7. Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/agent/tune_ml_hyperparam_agent -q`
      **DEVIATED** — at M0 only the new baseline module was run (3 passed, 3.42 s) — the directory-wide command ran at M1 (1046 passed). §19.2 / §19.3.
- [x] Record: test count, wall time, and explicit confirmation that zero
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
- [x] Re-read the tuner's run-scope prologue and identify the earliest point
      that precedes **both** consumer regions without moving any phase.
- [x] Establish the run-bound profile value there.
- [x] Confirm the loop-scope binding at `≈:4430` resolves to the **same**
      semantic value rather than an independent ambient resolution.
- [x] Confirm no phase, no ordering, and no side effect moved.

**4. Validation plan.**
- Unit: M0 baselines still pass unchanged.
- Integration/pseudo: focused tuner wiring tests still pass.
- Negative: none specific to M1.
- Backward-compat: `TrialConfig` serialization and both `SampleSet`
  identities deep-equal (Checkpoint A subset).
- Gate: **none**.

**5. Acceptance criteria.**
- [x] Zero behavior change: every M0 baseline and every existing tuner test
      passes without modification.
- [x] The startup region and the loop region observe the **same** profile
      value — asserted semantically (same binding), **not** by pinning a
      resolver call count (§10.2).
- [x] Run-phase order is provably unchanged.
- [x] No consumer has been migrated yet — `DATASET_CONFIG` still has five
      readers.

**6. Failure and edge cases.**
- The earliest safe point precedes profile availability → **STOP** rather
  than moving a phase (§16).
- Binding at run scope changes when the profile is first resolved relative to
  a validation that could fail → record and verify the failure ordering is
  preserved; a run that used to fail before resolution must still do so.

**7. Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/agent/tune_ml_hyperparam_agent -q`
- [x] Record counts, wall time, and confirmation that no test needed editing.

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
- [x] Re-read both sites and the `validate_stamped_invariants` /
      `validate_runtime_config` contracts they feed.
- [x] Replace both `DATASET_CONFIG.num_files` reads with the run-bound value.
- [x] Confirm the run-invariants lock content is unchanged under TIDMAD.

**4. Validation plan.**
- Unit: existing scope/invariant tests pass unchanged.
- Integration: run-invariants lock parity under TIDMAD.
- Negative: a partial scope is still detected as partial; a full scope still
  as full.
- Backward-compat: an existing workspace lock still validates — **no
  migration**.
- Gate: **none**.

**5. Acceptance criteria.**
- [x] Stage-B **B2** passes: under a contrast `num_files`, both full-scope
      stamping and partial-scope determination follow the bound profile.
- [x] Under TIDMAD the stamped invariants are **byte-identical** to M0/M1.
- [x] A pre-existing run-invariants lock validates without migration.
- [x] **No startup/scope consumer reads ambient TIDMAD state** — asserted
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
- [x] `.venv/bin/python -m pytest tests/unit/agent/tune_ml_hyperparam_agent tests/unit/execute_tools -q`
      **DEVIATED** — M2 ran a different targeted set (2445 passed, 2 skipped) that did not include `tests/unit/execute_tools`; this exact command ran at Checkpoint D (1978 passed, 1 skipped). §19.4 / §19.8.
- [x] Record counts, wall time, B2 result, and lock-parity evidence.

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
- [x] Re-read `_validate_data_config` and decide how the profile reaches it
      without a new authority — prefer threading the resolved object over a
      module default.
- [x] Migrate the legality site.
- [x] Migrate both legacy accounting sites, preserving the branch.
- [x] Remove the `DATASET_CONFIG` import and confirm zero readers remain.

**4. Validation plan.**
- Unit: M0 legality and accounting baselines pass **unchanged**.
- Integration: focused tuner integration.
- Negative: the rejecting legality case still rejects with the **same**
  diagnostic; whitespace/None-shaped inputs behave as before.
- Backward-compat: legacy `single_file` remains reachable and behaves
  identically under TIDMAD.
- Gate: **none**.

**5. Acceptance criteria.**
- [x] Stage-B **B1** passes: legality follows the bound profile.
- [x] Stage-B **B3** passes: through the **live** legacy path, both segment
      counts follow the bound profile.
- [x] M0 baselines pass **byte-identically** under TIDMAD — same verdicts,
      same diagnostic text, same counts.
- [x] **Terminal semantic property** — no 05a consumer either (a) reads the
      TIDMAD `DatasetConfig` singleton directly, **or** (b) independently
      resolves an ambient `DatasetProfile`.
- [x] A zero-hit `grep DATASET_CONFIG` over the tuner is recorded as
      **supporting mechanical evidence only**. It is not the property: a
      renamed alias, a re-export, or an `import execute_tools.dataset_config`
      module-attribute access would leave the grep clean while the defect
      survives, so the guard must assert the semantic property above.
- [x] The legacy `single_file` branch still exists and is still reachable.

**6. Failure and edge cases.**
- Threading into `_validate_data_config` tempts a `TrialConfig` field for the
  dataset fact → **forbidden** (§3); that would be a second authority.
- The legacy branch has no bound profile in some call path → **STOP**; do not
  reintroduce an ambient default as a fallback.
- Removing the import breaks an unrelated module-level reference → re-enumerate
  (§17.2) rather than leaving a partial migration.

**7. Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/agent/tune_ml_hyperparam_agent tests/unit/execute_tools -q`
      **SUPERSEDED** — M3 ran a strict SUPERSET — `tests/unit/{agent,execute_tools,core,workflows}` (7415 passed, 3 skipped). The exact command also ran at Checkpoint D (1978 passed, 1 skipped). §19.5 / §19.8.
- [x] Record counts, wall time, B1/B3 results, and the zero-hit grep output.

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
- [x] Add the run-binding guard (§10.2): one run-bound value, no ambient
      independent resolution, startup and loop agreeing — asserted
      semantically.
- [x] Add B1/B2/B3 as subcases of one rung, each against its own baseline.
- [x] Build the minimum Checkpoint-C scenario set (C1, and C2 if control flow
      requires it).
- [x] Run the family-level mutations (§8.1) and record each observed failure.

**4. Validation plan.**
- Unit: guard + three subcases.
- Integration: Checkpoint-C scenarios through real tuner control flow.
- Negative: the guard must **not** fire on the legitimate single run binding.
- Backward-compat: `pb*`-style prompt goldens and `TrialConfig`/`SampleSet`
  parity unchanged by this commit (it adds no production change).
- Gate: **none**.

**5. Acceptance criteria.**
- [x] Reintroducing ambient behavior reds for **each** of legality, scope and
      accounting — three recorded mutations.
- [x] The **transport** mutation (a consumer re-resolving ambiently) reds.
- [x] Every mutation is restored and the tree re-verified green.
- [x] Checkpoint C runs through real tuner control flow, not a helper.
- [x] No production file is modified by this commit.

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
- [x] `.venv/bin/python -m pytest tests/unit/agent/tune_ml_hyperparam_agent tests/unit/execute_tools -q`
      **DEVIATED** — M4 ran the three 05a evidence modules (36 passed) plus `-k`-filtered mutation runs; this exact command ran at Checkpoint D (1978 passed, 1 skipped). §19.7 / §19.8.
- [x] Record counts, wall time, each mutation's expected vs observed result,
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
- [x] Synchronize §19 (implementation ledger) with actual findings, deviations and evidence.
- [x] Run Checkpoint D from a **clean tree**.
- [x] Open/update the PR; drive exact-final-head CI green.
- [x] Verify local HEAD == PR `headRefOid` == successful CI `headSha`.

**4. Validation plan.**
- Checkpoint D as defined in §17. Exact-head CI is the broad regression
  authority. **No local full suite by default.** No Gate.

**5. Acceptance criteria.**
- [x] Checkpoint D fully green, verdict read from the **log file**, not a
      wrapper's exit status.
- [x] The three identities match, each read rather than reconstructed.
- [x] Working tree clean; ledger records every deviation.

**6. Failure and edge cases.**
- Full-suite/preflight guard reds on a dirty tree → commit the checkpoint
  first; never relax the guard.
- CI fails on an environment-only check → diagnose and fix autonomously; it is
  not a stop condition.

**7. Verification commands and evidence.**
- [x] Checkpoint-D command set, with counts and wall time recorded.
- [x] CI run id and exact `headSha`.

**8. Commit boundary.** Documentation and CI-driven fixes only.

## 19. Implementation ledger

**Implementation authorized 2026-08-14.** Branch
`feat/generic-framework-step-05a-tuner-data-selection`, cut from
**`2da399eb`** — the operator-selected implementation base, which is master
HEAD and `origin/master` at kickoff.

> **Base reconciliation (settled).** The authoritative identifiers are:
> frozen design content **`425bfac9`**, freeze marker **`1cb0119c`**,
> implementation base **`2da399eb`** — the operator-selected base, which is
> `1cb0119c` plus one docs-only commit (the commit that records the base) and
> was `origin/master` at kickoff. An earlier revision of this document's
> header named the freeze marker as the base; that is superseded by the value
> above and by the header table.
>
> The load-bearing historical fact is retained:
> `git diff --stat 13b08550..2da399eb` touches only five files, all under
> `docs/design/` — **no production surface moved between the design census
> base and the implementation base**, so the §2 census was still exact when
> implementation began.

### 19.1 Implementation-time source re-enumeration (§17.2)

Method: `grep -n "DATASET_CONFIG\|resolve_dataset_profile\|TIDMAD"` over the
tuner, then a full dataset-fact sweep
(`num_files|segments_per_file|psd_segment_length|SEGMENT_LENGTH|
SEGMENTS_PER_FILE|NUM_FILES|sampling_frequency|*_file_pattern`) over the same
module, then a caller audit of every helper the tuner reaches for
validation/scope/accounting.

**The frozen five-site census is exact — same sites, same line numbers.** The
tuner source has not moved since `13b08550`.

| # | Site | Family | Frozen census? |
|---|---|---|---|
| 1 | `ml_hyperparameter_tune_agent.py:76` import | (the alias itself) | yes |
| 2 | `:1090` `_validate_data_config(dataset_config=DATASET_CONFIG)` | legality (B1) | yes |
| 3 | `:2731` `full_scope=list(range(DATASET_CONFIG.num_files))` | scope (B2) | yes |
| 4 | `:3657` `scope_is_partial` | scope (B2) | yes |
| 5 | `:4465` legacy `single_file` train accounting | accounting (B3) | yes |
| 6 | `:4470` legacy `single_file` eval accounting | accounting (B3) | yes |
| **7** | **`agent/schemas/hyperparam_tuning.py:2162` — `validate_runtime_config(dataset: DatasetConfig = TIDMAD)`, consumed by the tuner at `:3656`** | **scope (B2)** | **NO — INCORPORATED** |

#### Finding 1 — a sixth residue site, incorporated under §17.2

```text
Previous assumption (§2):
  the residue is five module-level DATASET_CONFIG reads inside the tuner.

Audit evidence:
  `agent/schemas/hyperparam_tuning.py:2160-2226` — validate_runtime_config
  binds the TIDMAD singleton as a DEFAULT ARGUMENT and resolves the run's
  DataScope against it (`:2186 agent_input.data_scope.resolve(dataset)`,
  `:2201 is_partial = resolved != list(range(dataset.num_files))`).
  The tuner calls it at `:3656` with no dataset argument. A caller audit
  shows the tuner is its ONLY production caller (`workflows/
  model_exploration.py:1826` and `sdsc_submission_scripts/
  run_one_iteration.py:1598` mention it in prose only).

  This is not a newly noticed defect: Step 02b RECORDED AND ROUTED it.
  `tests/unit/agent/tune_ml_hyperparam_agent/
  test_step02b_checkpoint_c_live_integration.py:76-82` says verbatim —
  "validate_runtime_config resolves the DataScope against the TIDMAD
  singleton bound as a DEFAULT ARGUMENT ... a real genericity gap in the
  DataScope/HealthGate startup path — explicitly NOT 02b's to fix".

Corrected understanding:
  Site 4 (`:3657`) and site 7 compute the SAME predicate from the SAME
  fact. Migrating `:3657` alone would make them DISAGREE under a contrast
  topology — validate_runtime_config would early-return believing the scope
  full (skipping every partial-scope legality check) while the tuner printed
  and stamped it as partial. Excluding site 7 does not keep 05a smaller; it
  manufactures a NEW incoherence of exactly the kind §2.1 says a partial
  merge would ship.

§17.2 four-part test:
  same DatasetProfile authority      — yes, it needs profile.dataset
  same validation/scope capability   — yes, B2 scope, identical predicate
  same compatibility contract        — yes, TIDMAD scope-invariant parity
  same rollback boundary             — yes, the tuner is the sole production
                                       caller; reverting the tuner call site
                                       restores the previous behaviour

Implementation consequence:
  the tuner passes `dataset=` explicitly from the run-bound profile (M2).
  The `= TIDMAD` default STAYS on the function — it is the Regime-A
  compatibility adapter for non-tuner callers, exactly like
  `resolve_dataset_profile()`'s documented TIDMAD fallback. Making the
  parameter required would rewrite ~20 unrelated test call sites for no
  capability gain, which is scope creep, not rigour.

Validation consequence:
  B2 must assert on BOTH predicates agreeing under a contrast num_files —
  not just on the tuner's own `scope_is_partial`.
```

#### Finding 2 — one deferred site, different lifecycle

`execute_tools/health_checks/config.py:383` — `validate_health_scope` calls
`resolve_dataset_profile()` ambiently for `num_files`. Reached transitively
from the tuner via `build_run_invariants` → `materialize_effective_config`.

**Deferred to the HealthGate subsystem** (`docs/design/
pluggable_health_checks.md`), per §17.2's "policy / measurement lifecycle"
clause. Two reasons it is safe to defer rather than a MATERIAL STOP:

1. it is an **ambient `ContextVar` read**, not a hard singleton binding, so
   it already follows whatever profile is bound for the run — it can never
   disagree with the run binding the way site 7 can;
2. 05a's terminal property is about **tuner** consumers; this site belongs to
   the HealthGate config lifecycle, which owns its own scope contract.

Recorded so its owner can close it; 05a's semantics do not change either way.

#### Finding 3 — two of `_validate_data_config`'s three guards are unreachable

`:1120-1134`, branches 2 and 3, both compute `max(1, round(...))` and then
test `< 1`. `max(1, x)` is never below 1, so **neither guard can fire for any
input**. They read `segments_per_file`, so they *look* profile-dependent, but
no profile can move their outcome.

Consequence for Checkpoint 0: the legality baseline covers **one** failure
class (divisibility), not three. Baselining a dead guard would pin nothing —
CLAUDE.md's test-economy rule forbids it.

**Not fixed here.** Removing or correcting a legality guard is a behavioural
change to a rule Step 02 owns (§3), and 05a changes only *which object* is
asked. Recorded as follow-up debt.

### 19.2 CHECKPOINT 0 — pre-edit baselines — **COMPLETE**

File: `tests/unit/agent/tune_ml_hyperparam_agent/
test_step05a_checkpoint0_baselines.py` (new, tests only).

| # | Baseline | Captured |
|---|---|---|
| 1 | legality — illegal `segmentation_size` rejected | **exact** full diagnostic string, hardcoded (not re-derived from `valid_segmentation_sizes()`) |
| 2 | legality — legal `segmentation_size` accepted | verdict |
| 3 | live legacy `single_file` train + eval segment counts | `200` / `200`, read off the **persisted record**, with the route confirmed from the persisted `trial_config_*.json` `mode` field |

Reachability of baseline 3 is the **live** operator path, not the arithmetic
expression: `FAKE_PLAN_RESPONSE` carries no `is_trial` key and the input sets
`is_trial=False`, so `:4293-4298` selects `mode="single_file"` on its own. No
patch touches that branch.

```text
Validation:
  command:    .venv/bin/python -m pytest \
                tests/unit/agent/tune_ml_hyperparam_agent/\
                test_step05a_checkpoint0_baselines.py -q
  purpose:    capture the two §6 surfaces with no existing oracle
  runtime:    3.42 s
  result:     3 passed
  production: `git status --porcelain` shows ONLY the new untracked test
              file — zero production files modified
```

**Deviation (bounded) — how the legality baseline calls the helper.**
The M0 checklist says the baseline must reflect what production does today,
which is the *default-argument* call. Written that way the baseline would
stop compiling the moment M3 removes that default, so it could not serve as
a before/after oracle. It therefore passes `dataset_config=TIDMAD`
explicitly and pins *"under TIDMAD's topology, this verdict and this exact
text"* — an invariant that is byte-identical before and after the migration.
The separate, stronger claim *"production actually supplies the run-bound
object"* is owned by the run-binding guard and Checkpoint C — the same split
Step 02b used (`test_step02b_tuner_supplies_profile.py`'s docstring: "a
parameter with a `None` default is invisible to every caller that never
passes it").

### 19.3 M1 — the run-bound profile — **COMPLETE**

`ml_hyperparameter_tune_agent.py:3664` — `run_profile =
resolve_dataset_profile()`, placed immediately after the `storage.local`
extraction and immediately **before** the DS5 DataScope startup validation,
which is the first startup consumer. That point precedes both consumer
regions.

The loop-scope resolution formerly at `:4430` is **removed**; the two
`build_sample_set` calls now consume the run-scoped binding. Step 02b's
guarantee is unweakened — both sites still receive an explicit profile, still
the same object — and is now additionally shared with the validation, scope
and accounting consumers.

**Failure ordering is provably unchanged.** `resolve_dataset_profile()` reads
a `ContextVar` and falls back to `TIDMAD_PROFILE` when nothing is bound
(`dataset_config.py:596-613`); it has no failure mode of its own, so no run
that used to fail before profile resolution can now fail after it. No phase
moved, and **no branch was added to `run()`** — a single assignment, which
matters because `run()` sits on pyright's strict-mode complexity ceiling
(CLAUDE.md).

Resolver **call count is deliberately not asserted** (§4, §10.2). What M1
establishes is the semantic binding.

```text
Validation:
  command:  .venv/bin/python -m pytest \
              tests/unit/agent/tune_ml_hyperparam_agent -q
  purpose:  zero-behaviour-change proof for the structural commit
  runtime:  230.65 s
  result:   1046 passed  (verdict read from the log file, not a wrapper exit)
  note:     no existing test required editing; the Checkpoint-0 baselines
            pass unchanged.
```

### 19.4 M2 — startup scope consumers — **COMPLETE**

| Site | Before | After |
|---|---|---|
| `:2731` → now `_validate_history_and_lock` | `full_scope=list(range(DATASET_CONFIG.num_files))` | `full_scope=list(range(dataset.num_files))`, `dataset` a **required keyword-only** parameter supplied from `run_profile.dataset` at the call site |
| `:3657` → `:3708` | `scope_is_partial = ... != list(range(DATASET_CONFIG.num_files))` | `... != list(range(run_profile.dataset.num_files))` |
| **`validate_runtime_config`** (site 7) | tuner called it with no `dataset`, so it used the `= TIDMAD` default | tuner passes `run_profile.dataset` explicitly |

`_validate_history_and_lock`'s `dataset` is **required, not defaulted** — a
default would silently restore the ambient read the commit removes.
`validate_runtime_config` keeps its `= TIDMAD` default as the documented
Regime-A adapter for callers that predate the transport (§19.1 Finding 1);
its docstring now records that the tuner supplies the run-bound value and why
it mattered.

Unchanged, and verified by the untouched existing tests: DataScope semantics,
strategy, portions, seeds, ordering, the run-invariants lock **format**, and
the mismatch policy (still fails closed — B2's out-of-range case asserts it).

```text
Validation:
  command:  pytest test_step05a_checkpoint0_baselines.py test_data_scope_input.py
              test_ordering_schema_wiring.py test_step02b_tuner_supplies_profile.py
              tests/unit/core -q
  runtime:  73.82 s
  result:   2445 passed, 2 skipped
```

### 19.5 M3 — legality, legacy accounting, import removal — **COMPLETE**

| Site | Change |
|---|---|
| `_validate_data_config` | `dataset_config` is now a **required** parameter — the `= DATASET_CONFIG` default is gone. The tuner passes `run_profile.dataset`. The RULE is untouched; it still delegates to `valid_segmentation_sizes()`. |
| legacy `single_file` train count | `run_profile.dataset.segments_per_file` |
| legacy `single_file` eval count | `run_profile.dataset.segments_per_file` |
| `:76` import | **removed** |

The legacy branch is **migrated, not deleted**: it is still selected by
`is_trial=False` alone, and B3's TIDMAD control asserts its counts are still
200/200.

**Terminal semantic property.** `grep DATASET_CONFIG` over the tuner returns
zero — recorded as *supporting mechanical evidence only*, exactly as §17 M3
requires. The property that actually carries the weight is asserted by the
transport guard (§19.6): under a resolver that returns the bound profile once
and TIDMAD thereafter, every 05a consumer still produces bound-profile
behaviour. A renamed alias or a module-attribute access would leave the grep
clean and would still red that guard.

Exactly one `resolve_dataset_profile()` call site remains in the tuner — the
run-scope binding at `:3694`. That is the establishment point, not a
consumer's independent resolution.

```text
Validation:
  command:  pytest tests/unit/agent tests/unit/execute_tools tests/unit/core
              tests/unit/workflows -q
  purpose:  broad regression across every subsystem the seven sites touch
  runtime:  411.43 s
  result:   7415 passed, 3 skipped   (verdict read from the log file)
  also:     ruff check + ruff format --check clean on both touched modules
            (one I001 import-order error was fixed, not suppressed)
```

### 19.6 CHECKPOINT A — TIDMAD / replay parity — **COMPLETE**

| Surface | Oracle | Result |
|---|---|---|
| `TrialConfig` serialized form deep-equal | **existing** — `test_step00_record_baselines.py::TestTC1bOnDiskTrialConfigArtifact`, golden-backed | green in the 7415-test run |
| train / eval `SampleSet` identity | **existing** — `test_formal_sample_set.py`, `test_step02b_*` | green |
| validation verdict + exact diagnostic | Checkpoint-0 baseline | green, **byte-identical** |
| full / partial scope invariants | **existing** — run-invariants + DataScope suites | green |
| legacy `single_file` counts | Checkpoint-0 baseline + B3's TIDMAD control | 200 / 200, unchanged |
| historical config loads **without migration** | **NEW** — `test_step05a_checkpoint_a_replay.py` | 17 passed |
| `DatasetProfile` / `TrialConfig` / model / loss / train schemas | static: the diff touches no schema module | see below |

**The one genuinely missing oracle was the READING direction.** TC1b compares
a *fresh* run's artifacts against a golden, which proves the form this code
PRODUCES has not moved — it does not prove a document written by an older
build still LOADS. A change that made a field required would keep TC1b green
(fresh runs supply it) while breaking every stored config. The new module
closes exactly that gap, using two genuinely historical committed artifacts:
the Step-00 `tc1b_on_disk_trial_configs.json` golden (3 configs) and
`ml_models/legacy_baseline_configs.json` (6 paper-spec model/loss/train
configs). Each is validated and dumped back **deep-equal**. Both corpora are
size-asserted so a parametrized suite over an empty list cannot pass
vacuously.

**Schemas unchanged — proved statically, not by a test.** The PR's diff
touches three files: the tuner, `agent/schemas/hyperparam_tuning.py`
(a docstring only — `git diff` shows no field, validator or default changed),
and the design doc. `execute_tools/dataset_config.py` is **not in the diff at
all**, so `DatasetProfile`'s schema is untouched by construction. That is
stronger evidence than a field-list test, and CLAUDE.md forbids pytesting
what a static fact already establishes.

CLI / argv unchanged: no `argparse` line is in the diff.

### 19.7 CHECKPOINT B + CHECKPOINT C — **COMPLETE**

`tests/unit/agent/tune_ml_hyperparam_agent/test_step05a_run_bound_profile.py`
— 16 tests. Every one drives the real `HyperparamTuningAgent.run()`; nothing
calls `_validate_data_config`, `validate_runtime_config` or the accounting
expression directly, so Checkpoint C's no-helper-substitution property holds
for the whole module and Stage-B is proven *through* it rather than beside it.

**Checkpoint C scenario set — two scenarios, ONE checkpoint.** `trial`/
`formal` and `single_file` are selected by disjoint control flow, so no single
invocation reaches both; §9 anticipates this exactly.

| Scenario | Route | Families reached |
|---|---|---|
| **C1** | contrast trial run | B1 legality, B2 scope |
| **C2** | contrast `single_file` run | B3 accounting |

**Stage-B subcases — each moves exactly ONE fact.** Atomicity is *asserted*,
not merely stated in prose: `test_each_subcase_moves_exactly_one_fact` fails
if a future edit quietly widened a fixture, which is the only thing that would
notice §8's partial-derivation protection evaporating.

| Subcase | Varies | Observable |
|---|---|---|
| **B1** | `psd_segment_length` 10,000,000 → 1,500,000 | a segmentation size legal under TIDMAD is rejected, with the **bound topology's** exact diagnostic; TIDMAD control still accepts it |
| **B2** | `num_files` 20 → 7 | stamped `resolved_data_scope == range(7)`; a scope of files 0-6 is classified **full**, not partial (both predicates asserted — the verdict *and* the `[DATASCOPE] Partial scope active` line); a genuinely partial scope is still detected; an unstamped legacy record is judged against the bound `full_scope`; an out-of-range index is still rejected |
| **B3** | `segments_per_file` 200 → 57 | live legacy `single_file` train/eval counts are 57/57; TIDMAD control still 200/200 |

**Bounded deviation — the B2 full-vs-partial observable.** The first draft
used "partial scope + HealthGates enabled requires explicit
`--health_gate_files`" as the verdict. Every contrast-topology run with gates
enabled failed earlier and for an unrelated reason: the shipped
`configs/health_checks.yaml` declares monitored files as TIDMAD indices
`[3, 10, 17]`, which `validate_health_scope` rejects as out of a 7-file scope.
That is §19.1 Finding 2's deferred HealthGate/YAML gap, so gates are disabled
in the harness *with the reason recorded in the source* — the same remediation
Step 02b's Checkpoint C used — and the observable switched to
`formal_strategy="anchors"`, which a partial scope forbids and a full scope
never reaches.

#### Mutation / adversarial evidence (§8.1)

Method (CLAUDE.md mutation hygiene): assert the target matches **exactly
once** before writing, clear every `__pycache__`, run, restore from committed
source, re-verify green. The first run **aborted two mutations on the
site-count guard** — a line-based counter miscounted multi-line targets. That
is the guard doing its job; the counter was fixed to count substrings and both
were re-run.

| # | Family | Mutation | Expected | Observed |
|---|---|---|---|---|
| 1 | legality | legality site reads the ambient TIDMAD singleton | RED | **RED** — `B1 rejected_under_bound_topology`, `legality_survives_poisoned` |
| 2 | scope | both scope predicates read the ambient singleton | RED | **RED** — 5 tests incl. out-of-range and the transport guard |
| 3 | scope | only `_validate_history_and_lock`'s `full_scope` reads the singleton | RED | **RED** — `unstamped_legacy_record` |
| 4 | accounting | both legacy counts read the ambient singleton | RED | **RED** — `B3 counts_follow_bound_profile`, `accounting_survives_poisoned` |
| 5 | **transport** | one consumer calls `resolve_dataset_profile()` itself — reads *a* profile, just not the run's | RED | **RED** — `accounting_survives_poisoned` |

Mutation 3 is not redundant with 2: it is the only one that isolates the
stamped-history site, which mutation 2 does not touch.

Mutation 5 is the failure class no per-site mutation can catch. The guard
poisons ambient re-resolution — the first resolution returns the bound
profile, every later one returns TIDMAD — so a consumer resolving on its own
authority silently switches topology mid-run while still "reading a profile".
It is deliberately **not** a call-count assertion (§4, §10.2).

No mutation survived. Tree restored (`git status` clean on the tuner) and
re-verified: **16 passed**.

```text
Validation:
  command:  pytest test_step05a_run_bound_profile.py
              test_step05a_checkpoint_a_replay.py
              test_step05a_checkpoint0_baselines.py -q
  runtime:  33.63 s
  result:   36 passed
```

### 19.8 CHECKPOINT D — regression / static / CI

| Check | Result |
|---|---|
| directly affected deterministic tests | 05a modules — **36 passed**, 33.63 s |
| focused tuner integration | `tests/unit/agent/tune_ml_hyperparam_agent` + `tests/unit/execute_tools`, from a **clean tree** — **1978 passed, 1 skipped**, 288.90 s |
| broad subsystem regression (at M3) | `tests/unit/{agent,execute_tools,core,workflows}` — **7415 passed, 3 skipped**, 411.43 s |
| mutation evidence | 5 mutations, all RED, none survived; restored tree re-verified **16 passed** |
| `ruff check .` | **clean** repo-wide |
| `ruff format --check .` | **clean** repo-wide |
| strict pyright | **NOT RUNNABLE LOCALLY — see below** |
| local full suite | **not run**, per §13 / §17 |
| exact-final-head CI | run `31835207229` on `2b65a6bc` |

**Local pyright limitation, recorded rather than papered over.** This host's
Node is **v10.19.0**; pyright's bundled runtime fails to parse its own vendor
bundle (`SyntaxError: Unexpected token =`). Per CLAUDE.md's environment-
assumptions rule, **no local type claim is made** — CI's strict pyright step
is the authority, and it is a blocking step in `.github/workflows/ci.yml`.

Every verdict above was read from the **log file**, never from a wrapper's
exit status.

### 19.9 PR — TERMINAL RECORD

| | |
|---|---|
| PR | **#210 — MERGED** |
| branch | `feat/generic-framework-step-05a-tuner-data-selection` |
| base | `2da399eb` |
| implementation commits | `a2060fba` (M0/CP0) · `ad05ed95` (M1) · `885ab4d7` (M2+M3) · `2b65a6bc` (M4/CP A+B+C) · `4e4773a9` (CP D ledger) · `ab68fe36` (node-doc sync) · `5ae37180` (ledger provenance) |
| **final PR head** | **`5ae3718049035000a708b52170b8f47077cf0f9a`** |
| **exact-head CI (terminal authority)** | **run `31837316212` — success on the final PR head**, every step green including strict pyright |
| **merge SHA** | **`cfb3b1c7e3d656767c23a1818a9741157821decb`** (squash, the repository's normal strategy) |
| merged at | 2026-08-14T20:43:19Z |
| pre-merge identity | local HEAD == PR `headRefOid` == successful CI `headSha` == `5ae37180`, each read rather than reconstructed; working tree clean |
| post-merge verification | merge SHA reachable from `origin/master`; `git diff 5ae37180 cfb3b1c7` **empty** — the squashed tree is byte-identical to the reviewed head |

*Chronology, not terminal authority:* run `31835304729` was green (including
strict pyright) on the intermediate head `4e4773a9`. It is retained because it
establishes that the **code** was pyright-clean before the documentation-only
commits that followed — `git diff --name-only 4e4773a9..5ae37180` matches no
`.py` file. The terminal CI authority is run `31837316212` above.

**Actual footprint** (the rollback boundary, as landed):

| Surface | Change |
|---|---|
| `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py` | the production migration |
| `agent/schemas/hyperparam_tuning.py` | **docstring only** — `git diff` over the PR shows no field, validator, default or required key changed |
| `tests/unit/agent/tune_ml_hyperparam_agent/test_step05a_*.py` | three new evidence modules |
| `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md` | node doc sync |
| this document | PR design + live ledger |

**No schema field changed anywhere in this PR.**

**Gate disposition re-verified at the final head.** Gate 1 **NOT REQUIRED** —
no rendered prompt byte and no `LLMBridge` kwarg is in the diff. Gate 2 **NOT
REQUIRED** — no execution, training, inference, scoring, resource or admission
semantics change; every migrated surface is deterministic. Neither was run. No
real LLM, training, inference or GPU was used at any point.

### 19.10 CHECKPOINT E — final landed capability

**As merged**, in the tuner:

- ONE run-bound `DatasetProfile` semantic value is established at **run
  scope**, before every consumer;
- startup consumers and loop consumers use **that same binding**;
- both `build_sample_set` sites continue to receive it explicitly (Step 02b's
  guarantee, unweakened);
- **legality validation** consumes it (`_validate_data_config`);
- **full-scope stamping/validation** consumes it
  (`_validate_history_and_lock`);
- **partial-scope determination** consumes it (`scope_is_partial`);
- **`validate_runtime_config` is explicitly supplied the same dataset** by its
  sole production caller, the tuner;
- **live legacy `single_file` train/eval segment accounting** consumes it;
- the tuner **no longer imports or reads** the module-level TIDMAD
  `DatasetConfig` singleton;
- **no 05a consumer independently re-resolves an ambient `DatasetProfile`.**

**Bounded implementation-time finding, recorded as such.** The frozen §2
census — five direct tuner reads — was correct *as design evidence at
`13b08550`* and is preserved unedited above. Implementation-time
re-enumeration (§17.2) found a **sixth semantic residue** that no direct-read
grep of the tuner could surface, because it is a *defaulted parameter of a
callee*: `validate_runtime_config(dataset: DatasetConfig = TIDMAD)`, consumed
at the tuner's startup call site.

Its incorporation was **required, not optional**: it computes the same
full/partial-scope predicate, from the same fact, as the tuner's own
`scope_is_partial`. Migrating the tuner predicate while leaving this one
ambient would produce **contradictory startup validation under a contrast
topology** — the validator early-returning "full" and skipping every
partial-scope legality check, while the tuner classified and stamped the same
run as partial. That is the half-migrated state §2.1 exists to prevent.

**Compatibility decision.** The tuner passes `run_profile.dataset` explicitly;
the `= TIDMAD` default **remains** on `validate_runtime_config` as the
Regime-A adapter for non-tuner callers, exactly like
`resolve_dataset_profile()`'s documented fallback. **No schema change and no
required-key migration was introduced.**

#### Terminal checkpoint evidence

| Checkpoint | Verdict | Evidence |
|---|---|---|
| **0** | **PASS** | minimum `DatasetProfile`-dependent legality accept/reject baseline; exact rejecting diagnostic; live legacy `single_file` train/eval baseline **200/200** — all captured **before** any production edit (§19.2) |
| **A** | **PASS** | `TrialConfig` serialized form deep-equal; `SampleSet` identities unchanged; legality verdict and diagnostic exact; full/partial scope invariants unchanged; legacy counts unchanged; **3** historical `TrialConfig`s load without migration; **6** historical paper-spec model/loss/train configurations load and round-trip deep-equal; `DatasetProfile` / `TrialConfig` / model / loss / train schemas unchanged; CLI / argv unchanged (§19.6) |
| **B** | **PASS** | B1 legality · B2 scope · B3 accounting; each changes **exactly one** profile fact; atomicity **machine-checked**, not asserted in prose (§19.7) |
| **C** | **PASS** | C1 normal/trial reaches legality + scope; C2 live legacy `single_file` reaches accounting; every test drives the real `HyperparamTuningAgent.run()`; **no helper-only substitution** (§19.7) |
| **Mutations** | **PASS** | five mutations, all **RED**, none survived, restored tree re-verified green (§19.7) |
| **D** | **PASS** | 36 directly affected · 1978 focused (1 skipped) from a clean tree · 7415 broader subsystem (3 skipped) · `ruff check` clean · `ruff format --check` clean · **local pyright unavailable (host Node v10.19.0) — no local pyright success is claimed** · exact-head CI strict pyright passed · local full repository suite **not** run (§19.8) |
| **Gates** | **NOT REQUIRED** | Gate 1 and Gate 2 both NOT REQUIRED, re-verified at the final head; neither run. No LLM, training, inference or GPU used. |

### 19.11 Deferred findings — routed debt, NOT incomplete 05a acceptance

Both were found by implementation-time audit, both are outside 05a's frozen
authority, and **neither blocked or blocks PR 05a acceptance.** They are
recorded here so their owners can act, not carried as 05a debt.

**A. HealthGate lifecycle.** `execute_tools/health_checks/config.py:383` —
`validate_health_scope` reads `num_files` through an ambient
`resolve_dataset_profile()`. It is a **ContextVar read**, so it already
follows the bound run profile and can never disagree with 05a's run binding.
Separately, the shipped `configs/health_checks.yaml` still declares monitored
files as **TIDMAD-indexed** literals (`[3, 10, 17]`), which
`validate_health_scope` rejects as out of scope under any smaller topology —
the reason 05a's contrast-topology harness disables gates, with that reason
recorded in the test source. **Owner: the HealthGate subsystem**
(`docs/design/pluggable_health_checks.md`).

**B. Dataset legality guards.** Two of `_validate_data_config`'s three
raising branches compute `max(1, x)` and then test `< 1`, so **neither can
fire for any input**. They read `segments_per_file` and therefore *look*
profile-dependent, but no profile can move their outcome. Correcting a
legality guard is a behavioural change to a rule **Step 02 owns**; 05a
changes only which `DatasetProfile` object is supplied, so it deliberately
left them untouched. **Owner: Step 02.**

Neither item is routed into 05b or 05c: no source evidence places either in a
resource/time or execution/deliverable lifecycle.

## 20. Remaining operator decisions

**None.** The only judgement call — whether the live legacy `single_file`
accounting is migrated or recorded — is resolved from source in §2
(live, therefore migrated).
