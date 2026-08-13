# PR 02a — Dataset Profile injection (Step 02, child 1 of 3)

## Status

**FROZEN / OPERATOR APPROVED (2026-08-13).**

The operator froze this design at revision 4. Everything below —
scope and ownership, the blocking checkpoint ladder (§5a), the
Checkpoint-C boundary (§5b), Regime-A semantics (§5c), the ordering
contract (§5d), the encoding claim (§5e), the derived-artifact-indexing
disposition (§5f), the mutation economy (§5g), the seven commits (§6)
and the Gate decision (§7) — may not change without a new operator
decision.

**IMPLEMENTATION AUTHORIZED AND IN PROGRESS (2026-08-14).** The
lifecycle precondition is met: a filled **Implementation Working Rules
contract** for this child was issued, and implementation runs in a NEW,
fresh context with its own Context Continuity v2 handoff — not in the
design session. **From this point this document is the LIVE PR-02a
implementation ledger**, updated continuously rather than at closeout.

Kickoff facts, resolved mechanically from the repository (never from
conversational memory):

| Fact | Value |
|---|---|
| Frozen design HEAD | `cfc83b1e11f4accbe15f8daecdd8bd37846e91d7` — the commit that froze this document |
| Implementation base | `a546aff02d1f96b463d689e20bc9856202ca8111` (`cfc83b1e` + the parent's LIVING-document docs commit) |
| Implementation branch | `feat/generic-framework-step-02a-dataset-profile-injection` |
| Parent state | **LIVE / not frozen, by operator decision** — see the parent's Status and its authority rule |
| Gate plan | Gate 1 NOT planned (§7); Gate 2 NOT run by this child (02c owns it) |

**Parent-vs-child authority (operator decision, 2026-08-14).** The
Step-02 parent is a LIVE governance document and is **not** required to
be frozen for this child to proceed; only *this* child design had to
freeze. Implementation discoveries may flow back into the parent and
into the still-unfrozen 02b/02c designs, but they **may not silently
rewrite this frozen contract's scope or acceptance criteria** while 02a
is in progress — a material conflict requires an explicit operator
decision. The full rule lives in the parent's Status section.

Deliberately left to implementation time (parent §13a): the profile
object's type and field names, YAML layout, the config-flag name, the
injection helper decomposition, test-file placement and assertion form,
and the exact Checkpoint-C command assembled from live source.

Revision 4 applies the operator review of 2026-08-13. **Q02a-1 is
ANSWERED: all three subprocess boundaries stay in ONE PR** (§3.4). No
further implementation detail was added; the four load-bearing
checkpoint/validation gaps were closed instead — a blocking checkpoint
ladder (§5a), a Checkpoint-C boundary that cannot be satisfied by a
stub (§5b), frozen Regime-A semantics (§5c), and a deliberately narrow
shuffle contract (§5d). Encoding claim, derived-artifact indexing and
mutation economy clarified (§5e-§5g).

Parent (governance, ownership, DAG, aggregate acceptance):
[`../step_02_dataset_sample_topology.md`](../step_02_dataset_sample_topology.md).

Position in the DAG: **first**. `02b` and `02c` both depend on it.
Governance order is frozen `02a → 02b → 02c`.

Revision 3 added the §6 per-commit checklists, each grounded in the
source inspection recorded in §3.

---

## 1. Scope

**OWNS** — the dataset declaration and the production DATA PATH that
reads it:

- file topology: families, identity, index space, counts, name patterns;
- sample decomposition geometry (`psd_segment_length`,
  `segments_per_file`) and the sample-shape **legality rule**;
- the dtype + offset **encoding declaration**;
- **channel identity** — which in-file channel is the model INPUT and
  which is the TRUTH;
- derived-artifact **INDEXING** by input identity.

**DOES NOT OWN**: selection/SampleSet semantics (02b), group semantics
(02c), deliverable naming/layout/attrs (Deliverable Contract),
`segmentation_size` itself, model I/O semantics (Step 03), HealthGate
policy (Step 08).

**Boundary that needs care (parent §13b A1).** `scoring_utils.py`
handles BOTH the raw validation filename (Step-02-owned input topology,
inlined at `:389`, `:444`) and denoised deliverable files. This PR
routes ONLY the raw-validation half. **Any diff touching a
denoised/deliverable filename template is a scope leak and a STOP.**

## 2. Why this is a PR, and why not four

After it merges, the production data path — training, inference and
scoring — resolves filenames, geometry, legality, encoding and channel
identity from a **resolved profile** instead of module-level constants.

Its risk class is its own: a changed filename or `data_shape_class`
string invalidates measurement-store keys.

Topology, geometry, encoding and channel identity are four FACETS of one
capability, not four capabilities. §3.1's inspection shows why:
**a single method — `TIDMADEpochDataset._pull_events_from_sample_set`
(`train_engine_sandbox.py:135-201`) — reads all four at once.** Splitting
them would mean touching that one method in four separate PRs, each
leaving the others hardcoded.

They are therefore internal semantic milestones — useful labels for
what each commit migrates:

```text
M1  profile / topology resolution
M2  geometry + legality
M3  encoding declaration reachability
M4  channel identity
M5  production consumption across training + inference + scoring
```

**Their evidence is parity + reachability, NOT contrast.** Revision 3
described M1/M2/M4 as carrying rungs A1/A2, B and D; those rungs
actually land in C6, after every extraction, because each needs the
fully resolved path to exist. The corrected statement: milestones close
on Stage-A parity and live reachability; **Stage-B contrast is a
separate blocking checkpoint (CHECKPOINT B, §5a)**. The blocking ladder
in §5a — not this label list — is authoritative.

**Re-opening clause.** If implementation shows a milestone cannot be
reviewed or rolled back coherently inside one PR, STOP and re-open the
parent's decomposition decision rather than forcing the plan.

---

## 3. Source inspection performed for this plan (2026-08-13, master `c7f4a212`)

No commit below was written from memory. Line numbers are dated
evidence, not addresses to code against.

### 3.1 The concentration point

`execute_tools/train_engine_sandbox.py:135-201`
(`_pull_events_from_sample_set`) reads, in one loop:

| Line | Reads | Milestone |
|---|---|---|
| `:160` | `TIDMAD.training_file_name(file_index)` | M1 topology |
| `:157`, `:178-179` | `PSD_SEGMENT_LENGTH` (module constant) for `ml_segs_per_psd` and slice bounds | M2 geometry |
| `:167-172` | `"timeseries", "channel0001"` / `"channel0002"` | M4 channel |
| `:181-182`, `:196` | `.astype(np.int8/int16)`, `+ 128`, `minlength=256` | M3 encoding |
| `:158` | `sorted(sample_set.items())` | file visit order |
| `:200` | `evlist.append((filename, i))` | **the visited sequence** |
| `:163-165` | missing file → `print("Warning: … not found, skipping.")` + `continue` | failure behaviour |

`:86` sets `self.size = len(self.train_events)` — so **step count derives
from the visited sequence**. `:262-263` documents that cross-file
shuffling comes from the DataLoader's `shuffle=True`, and `:369-378`
validates `order_strategy ∈ {"shuffle","sequential"}` plus the
`file_order` permutation. These are the surfaces §5's ordering criteria
apply to.

### 3.2 The injection boundary is a PROCESS boundary

`train_engine_sandbox.py`, `inference_single.py` and
`denoising_score_single.py` are **subprocess entry points** with their
own `argparse` (`:1112`, `:287`, `:45`). A resolved profile therefore
cannot be "passed as an argument" — it must cross a process boundary.

**Precedent exists and must be reused rather than invented.**
`core/sandbox_executor.py:1236-1304` already writes JSON config files
into `self.dirs["configs"]` and passes their PATHS as argv flags:
`--model_cfg`, `--train_cfg`, `--loss_cfg`, plus `train_sample_set`,
`file_order` and `runtime_policy`. A dataset-profile config file
following exactly this pattern is the bounded, precedented mechanism.

### 3.3 Consumers, split by boundary

**In-process** (ordinary import → injection): `workload_resolvers.py:36`,
`agent/skills/evaluate_time_skill/wrapper.py:65`,
`agent/skills/inference_skill/estimator.py:55`,
`agent/schemas/score_table.py:22`, `nodes/scoring_reference.py:24`,
`execute_tools/scoring_helpers.py:33`,
`execute_tools/health_checks/config.py:25` and
`spectral_peak_ratio.py:31`.

**Across the subprocess boundary**: `train_engine_sandbox.py`,
`inference_single.py`, `denoising_score_single.py`.

**Second re-export hop to collapse**: `sample_set_builder.py:21` reaches
`SEGMENTS_PER_FILE` *through* `scoring_utils`, not the authority.

### 3.4 Q02a-1 — ANSWERED: keep all three subprocess boundaries

> **OPERATOR DECISION, 2026-08-13: 02a carries the training, inference
> AND scoring subprocess boundaries. Do NOT split the child by
> boundary.**
>
> Rationale as recorded: the three entries consume ONE Dataset Profile
> and must agree on topology, geometry, encoding and channel semantics.
> Splitting them into separate child PRs would create a dangerous
> intermediate state in which training interprets the dataset through
> the profile while scoring still interprets it through the old
> constants — the same file decomposed two ways, silently. C3 and C4
> already provide separate semantic review and rollback boundaries
> INSIDE the PR, and the sequence "C3 proves the IPC mechanism on
> training → review → C4 replicates it" is the right granularity.
> Three `argparse` entries is not, by itself, a reason to split a PR.

---

## 4. Compatibility contract (strongest observable criterion per surface)

| Surface | Criterion | Baseline |
|---|---|---|
| Resolved profile | deep-equals today's `TIDMAD` field by field | EXISTS (Step 00) |
| Legality list | exact 36-entry `valid_segmentation_sizes()` | EXISTS |
| Training filename | `training_file_name(0)`/`(19)` byte-identical | EXISTS |
| Validation filename | profile-produced name == the string the scorer/inference inline today | **MISSING → C1** |
| `data_shape_class` | exact `psd10000000_seg200_files20` | EXISTS |
| Encoding | declaration produces byte-identical loaded tensors | **MISSING → C1** |
| Channel identity | resolved channels produce byte-identical input/target tensors | **MISSING → C1** |
| **Visited sequence** | `train_events` identical `(filename, row_idx)` list, same order | **MISSING → C1** |
| **Step count** | `len(train_events)` and derived steps/epoch identical | **MISSING → C1** |
| **Ordering semantics** | shuffle enablement + same seed/generator/kwargs reach the DataLoader; `order_strategy` resolution and `file_order` permutation validation unchanged; the deterministic `sampler` branch's order exact. **Exact `shuffle=True` emitted order deliberately NOT contracted** (§5d) | **MISSING → C1** |
| Rendered prompts | proposer known-constraints + planner divisor list byte-identical | EXISTS |

---

## 5. Commit sequence

| # | Commit | Kind | Milestones |
|---|---|---|---|
| **C1** | capture the missing baselines | test-only | prerequisite for all |
| **C2** | profile declaration + IN-PROCESS consumers | production | M1 (partial) |
| **C3** | subprocess IPC hop + training engine | production | M1-M4 at the concentration point |
| **C4** | inference + scoring subprocess entries | production | M5 |
| **C5** | legality de-duplication + `compute_raw_baseline` | production | M2 closeout |
| **C6** | Stage-B contrast rungs A1 / A2 / B / D | test-only | Checkpoint B |
| **C7** | docs + ledger closeout | docs-only | — |

Rungs land in C6 rather than one per milestone because every rung needs
the fully resolved path to exist. Milestone blocking inside C2-C4 is
therefore on **parity + reachability**; contrast is the gate on C6.

---

## 5a. Blocking checkpoint ladder (FROZEN)

Every rung is blocking. **Later evidence never excuses an earlier failed
invariant.**

```text
C1  baseline capture
  └─ CP0 — BASELINES COMPLETE
        every MISSING row in §4 has a pin, and each pin is shown to fail
        when the behaviour it pins is perturbed
        FAIL => stop; do not begin extraction

C2  profile + in-process consumers
  └─ CP-A1 — in-process parity + reachability
        profile deep-equals TIDMAD; data_shape_class byte-exact;
        the eight in-process consumers read the profile, not constants
        FAIL => stop; do not cross the process boundary

C3  IPC hop + training engine
  └─ CP-A2 — training subprocess consumes the profile
        + visited sequence, step count and ordering semantics preserved
        + no silent singleton fallback
        FAIL => stop; do not replicate the mechanism to C4

C4  inference + scoring entries
  └─ CP-A3 — all three data paths agree on ONE profile
        + validation_file_pattern dead seam closed
        + ZERO Deliverable-Contract leakage
        FAIL => stop

C5  legality de-duplication + compute_raw_baseline
  └─ CHECKPOINT A COMPLETE — all Stage-A/TIDMAD extraction parity closed
        + rendered prompt bytes unchanged
        FAIL => stop; do not start contrast

C6  rungs A1 / A2 / B / D
  └─ CHECKPOINT B COMPLETE — generic contrast, each rung single-axis
        FAIL => the abstraction or the rung is wrong; stop

assembled 02a executable head
  └─ CHECKPOINT C — LIVE INTEGRATION (§5b)
        FAIL => not ready for review

C7  docs + ledger closeout
  └─ CHECKPOINT D — regression / static / exact-head CI
```

## 5b. Checkpoint C — boundary FROZEN, command NOT frozen

Checkpoint C must prove the resolved Dataset Profile is consumed by the
**REAL production data-reading code across the subprocess boundary**.

> **A pseudo mode that replaces or bypasses `train_engine_sandbox`,
> `inference_single` or `denoising_score_single` does NOT establish this
> property and does NOT satisfy Checkpoint C.**

Implementation chooses the cheapest bounded mechanism from live source —
synthetic/minimal HDF5, direct sandbox or subprocess invocation, or an
existing production-entry smoke. **No real LLM is required. No
scientific-quality result is required. GPU is not required** unless
current source makes it unavoidable.

PASS must establish at least:

- [ ] the profile is serialized by the parent process;
- [ ] the profile is loaded inside the child process;
- [ ] the real data-reading code uses the profile's filename, geometry,
      channel and encoding;
- [ ] training, inference and scoring resolve the SAME TIDMAD semantics;
- [ ] no silent singleton fallback anywhere;
- [ ] exact executable HEAD, artifacts and log recorded.

This is live-integration evidence, **not a substitute Gate tier** (§7).

## 5c. Regime-A vs fail-closed — FROZEN (was left to implementation)

Revision 3 left "legacy caller without a profile: fail closed or
adapter — decide explicitly", which is a semantic decision an
implementer must not make alone. Frozen now, consistent with the
roadmap's regime split (regime B is Step 12, not Step 02):

| Situation | Behaviour |
|---|---|
| an explicit profile path IS supplied but the file is **missing, corrupt or schema-invalid** | **FAIL CLOSED** with a diagnostic naming the path. **Never** fall back to the singleton |
| an existing **SUPPORTED legacy TIDMAD caller** omits the newly introduced profile transport entirely | **Regime-A compatibility adapter** — resolve the shipped TIDMAD profile exactly, preserving today's behaviour — UNLESS source audit proves that caller is not a supported surface, in which case fail closed and record the audit |
| a future **explicitly bound task** with missing required semantics | **Regime-B fail-closed — Step 12**, not Step 02 |

The distinction in one line: *"the flag is present but the file is
broken"* must never fall back; *"an old caller has never heard of the
flag"* must not be broken by genericization.

**Consequently the `DatasetConfig` TIDMAD filename-pattern CLASS
defaults are KEPT — as documented Regime-A adapter semantics only.**
They must be described in code and docs as a compatibility adapter, and
must NOT be presented as universal generic defaults. This closes the
open decision revision 3 left in C2.

Exact API shape remains implementation-time.

## 5d. Ordering — pin the real invariant, do NOT invent a stronger one

**Source audit (2026-08-13).** `train_engine_sandbox.py:864-866` builds
`DataLoader(dataset, batch_size=..., shuffle=True, drop_last=True)` with
**no `generator`, no seed, and no `torch.manual_seed` anywhere in the
module**. The `shuffle=True` branch therefore draws from torch's global
RNG, which nothing here pins. The other branch (`:857-862`) passes
`sampler=epoch_indices`, which IS deterministic via `epoch_seed`.

Therefore:

**FROZEN as compatibility surfaces** (exact):
- the pre-shuffle `train_events` ordered `(filename, row_idx)` sequence;
- the step count (`len(train_events)` and derived steps/epoch);
- `order_strategy` resolution semantics (`{"shuffle","sequential"}`);
- `file_order` permutation validation behaviour;
- shuffle ENABLEMENT and the same seed/generator/kwargs reaching the
  DataLoader;
- the `sampler=epoch_indices` branch's emitted order, which is already
  deterministic under `epoch_seed`.

**NOT frozen**: the exact emitted shuffled order under the
`shuffle=True` branch. It is not deterministic today, so pinning it
would **create a new compatibility promise** — and worse, would tempt
an implementer to introduce seeding, which is a behaviour change 02a
must not make. Pin it only if a later audit shows the exact ordering is
already deterministic and already contracted.

## 5e. Encoding — claim frozen narrowly

> 02a proves the encoding declaration is **LIVE and consumed by
> production data loading**, and that the TIDMAD declaration reproduces
> **byte-identical tensors**.
>
> 02a does **NOT** claim arbitrary alternative dtype or model
> compatibility. Step 03 owns model-I/O derivation from the declaration.

A cheap controlled mutation — perturb the profile's offset and confirm
the loader's conversion follows — is allowed and useful as reachability
evidence. It does **not** become another required Stage-B rung.

## 5f. Derived-artifact indexing — DISPOSITION A (parity-only), with evidence

Revision 3 claimed this in scope but never closed it. Re-audited:

- **Indexing already has a clean seam.** `core/sandbox_executor.py:1731,
  1743, 1766` and `denoising_score_single.py:172, 185` pass
  `denoised_filename_fn: Callable (file_index) → denoised filename`.
  Deliverables are already keyed by the INPUT identity (`file_index`),
  which is Step-02-owned topology, through a callable rather than a
  hardcode.
- **What IS hardcoded is the NAMING template**, re-inlined at
  `inference_single.py:563, 828, 833`, `denoising_score_single.py:141,
  144` and `sandbox_executor.py:1652`. That is the **Deliverable
  Contract**, explicitly NOT 02a's (parent §3).

**Disposition: A — already generic; parity-only surface.** No production
change is required. 02a closes it by pinning the existing invariant:
derived artifacts are keyed by `file_index` through
`denoised_filename_fn`, and that keying is unchanged. Assigned to C4,
whose diff already touches this neighbourhood and must be proven not to
leak into naming.

## 5g. Mutation economy — per failure CLASS, not per test

Revision 3 required "each new pin gets one mutation", which conflicts
with the frozen test-economy principle. Corrected:

> **Each DISTINCT failure class must have reachability or mutation
> evidence. One mutation per test is NOT required.**

Minimum distinct classes for 02a:

| Class | Demonstrates |
|---|---|
| filename authority disconnect | a consumer still building names from a constant/inline literal |
| encoding / channel authority disconnect | loader ignoring the declaration (covers §5e's offset probe and the channel swap) |
| ordering / step-count semantics | visited sequence or step count silently changed |
| IPC fail-closed | a subprocess silently falling back to the singleton when the profile is absent or corrupt |

Implementation chooses the minimum mutation set demonstrating those
classes.

## 6. Per-commit checklists

### 6.1 Commit C1 — capture the missing baselines (test-only)

**1. Goal.** Pin the six MISSING surfaces in §4 BEFORE any extraction,
so the later commits have an oracle. Capture-after-edit pins the
already-changed behaviour and proves nothing (the S1-E precedent).

Belongs here because it must precede C2-C5 by construction; folding it
into C2 would let a reviewer see the pin and the change in one diff and
be unable to tell which came first.

**2. Scope.**
Changes: new test module(s) under `tests/unit/execute_tools/` (exact
placement implementation-time); possibly a shared fixture helper.
Unchanged: ALL production code — this commit has zero production diff.
Depends on: nothing.

**3. Implementation plan.**
- [ ] Pin the validation filename: the string `scoring_utils.py:389,444`
      and `inference_single.py` build today == the pattern render.
- [ ] Pin encoding: load a synthetic file and assert the exact tensors
      after `astype`/`+128`, including the `minlength=256` bincount.
- [ ] Pin channel identity: assert input comes from `channel0001` and
      target from `channel0002`, and that swapping them is detectable.
- [ ] Pin the **visited sequence**: `train_events` as an exact ordered
      `(filename, row_idx)` list for a fixed sample_set.
- [ ] Pin the **step count**: `len(train_events)` and steps/epoch for a
      fixed batch size.
- [ ] Pin the **default shuffle path** per §5d — shuffle ENABLEMENT and
      the same seed/generator/kwargs reaching the DataLoader,
      `order_strategy` resolution, `file_order` permutation validation,
      and the deterministic `sampler=epoch_indices` branch's emitted
      order. **Do NOT pin the exact emitted shuffled order** under
      `shuffle=True`: source audit shows no generator/seed is passed, so
      pinning it would create a new guarantee (§5d).
- [ ] Provide mutation/reachability evidence per §5g **failure class**,
      not one mutation per test.

**4. Validation plan.**
Unit: the new pins themselves.
Integration/pseudo: none.
Negative/invalid: `file_order` that is not a permutation; a
non-`{shuffle,sequential}` strategy — both must raise as today.
Backward-compat: not applicable (no production change).
Gate: none.

**5. Acceptance criteria.**
- `git diff --stat` shows ZERO files outside `tests/`.
- Each of the six MISSING rows in §4 has a named test.
- Each new pin has a recorded mutation that reds it.
- The visited-sequence pin asserts the exact ordered list, not a length
  or a set.
- No pin asserts the exact emitted shuffled order under `shuffle=True`
  (§5d).
- Every §5g failure class has evidence; per-test mutations are NOT
  required.

**6. Failure and edge cases.**
| Case | Handling |
|---|---|
| a pin cannot be written without touching production | STOP — that is a design finding, not a licence to edit |
| a pin passes for the wrong reason (e.g. empty sequence) | the mutation requirement catches it |
| synthetic fixture diverges from real HDF5 layout | reuse the existing `synthetic_h5` conftest generator rather than inventing one |

**7. Verification commands and evidence.**
Intended: targeted `pytest` over the new module(s) plus
`tests/unit/execute_tools/`. Record counts and wall time here after
execution. Any test that could not be run is recorded with the reason —
never claimed as passed.

**8. Commit boundary.** Test-only, independently reviewable, no
production diff, no cleanup. Before committing: show diff summary,
staged file list, test output, deviations.

---

### 6.2 Commit C2 — profile declaration + IN-PROCESS consumers

**1. Goal.** Introduce the resolved Dataset Profile and land it WITH its
first consumers — the eight in-process modules in §3.3 — killing their
bare-constant imports.

Belongs here, separate from C3, because these consumers need no IPC:
mixing them with the subprocess hop would put two unrelated mechanisms
in one diff.

**2. Scope.**
Changes: `execute_tools/dataset_config.py` (profile shape —
implementation-time, per parent §13a); the eight in-process consumers in
§3.3; collapse of the `sample_set_builder.py:21` re-export hop.
Unchanged: subprocess entries (C3/C4); `data_shape_class` string;
selection semantics; group literals (02c); prompt bytes.
Depends on: C1.

**3. Implementation plan.**
- [ ] Decide the profile shape and record why (parent §13a leaves it
      open).
- [ ] Implement the FROZEN class-default disposition (§5c): the TIDMAD
      filename-pattern class defaults are **KEPT as documented Regime-A
      adapter semantics** and must be described as a compatibility
      adapter in code and docs — never as universal generic defaults.
- [ ] Migrate the eight in-process consumers to injection.
- [ ] Collapse the `scoring_utils` re-export hop.
- [ ] Confirm `data_shape_class` still derives to the identical string.
- [ ] Confirm no profile field lands without an in-PR consumer.

**4. Validation plan.**
Unit: profile deep-equality; the 36-divisor list; `data_shape_class`
exact string; per-consumer injection tests.
Integration/pseudo: none required at this commit.
Negative/invalid: a profile missing a required field must fail at
construction, not at first read; the existing filename-pattern validator
must still reject a pattern without `{file_index}`.
Backward-compat: every §4 EXISTS row still green, unmodified.
Gate: none.

**5. Acceptance criteria.**
- Zero bare-constant imports remain in the eight modules.
- `data_shape_class` renders `psd10000000_seg200_files20` byte-exactly.
- The Regime-A adapter semantics are documented at the code site, not
  merely implied by a default value.
- Mutation: reverting one consumer to the module constant reds a test.

**6. Failure and edge cases.**
| Case | Handling |
|---|---|
| a consumer has no obvious injection point | record it and move it to C3/C4 rather than inventing a global |
| a profile field has no consumer in this PR | STOP — §0 rule 8 dead seam |
| `data_shape_class` changes | STOP — measurement-store keys invalidated |
| legacy caller passes no profile | **Regime-A adapter** — resolve the shipped TIDMAD profile exactly (§5c), unless source audit proves the caller is not a supported surface |

**7. Verification commands and evidence.** Targeted + affected package
(`tests/unit/execute_tools/`, `tests/unit/agent/`). Counts and wall time
recorded here after execution.

**8. Commit boundary.** Declaration + in-process consumers only. No IPC,
no subprocess entry, no legality de-duplication, no rungs.

---

### 6.3 Commit C3 — subprocess IPC hop + training engine

**1. Goal.** Carry the resolved profile across the process boundary
using the §3.2 precedent, and migrate the concentration point
(`_pull_events_from_sample_set`) so topology, geometry, encoding and
channel identity all resolve from it.

Belongs here because §3.1 shows all four are read in ONE method — they
cannot be migrated separately without leaving that method half-hardcoded.

**2. Scope.**
Changes: `core/sandbox_executor.py` (write the profile config file,
add the argv flag, following the `--model_cfg` pattern);
`execute_tools/train_engine_sandbox.py` (argparse flag, load, and the
`TIDMADEpochDataset` reads at `:157-200`).
Unchanged: the visited sequence, step count, shuffle behaviour,
`file_order` semantics, sample_set semantics (02b), deliverable names.
Depends on: C1, C2. **Blocked on the Q02a-1 answer (§3.4).**

**3. Implementation plan.**
- [ ] Re-read `core/sandbox_executor.py:1236-1304` and follow the
      existing config-file + argv-flag pattern exactly; do not invent a
      new IPC mechanism.
- [ ] Add the profile config write + flag.
- [ ] Add the subprocess-side argparse flag and load.
- [ ] Migrate `:160` filename, `:157/:178-179` geometry,
      `:167-172` channels, `:181-196` encoding to the profile.
- [ ] Verify the missing-file branch at `:163-165` behaves identically.
- [ ] Prove the visited sequence and step count are unchanged.
- [ ] Prove the default shuffle path is unchanged.

**4. Validation plan.**
Unit: profile survives serialization → subprocess load → identical
values; each migrated read produces its pinned value.
Integration/pseudo: a bounded run that executes the **REAL**
`train_engine_sandbox` data-reading code across the process boundary
(§5b). A mode that replaces or bypasses that module does not count.
Negative/invalid: profile config file missing/corrupt → fail closed with
a diagnostic, never a silent TIDMAD fallback; a profile whose geometry
does not divide → the legality error, not a reshape crash.
Backward-compat: the C1 visited-sequence, step-count and shuffle pins
green UNMODIFIED.
Gate: none in this commit (Step-level Gate 2 is 02c's).

**5. Acceptance criteria.**
- The subprocess receives the profile and reads ZERO module constants
  for topology/geometry/channel/encoding.
- `train_events` is the identical ordered `(filename, row_idx)` list —
  asserted as the sequence, not merely the count.
- `len(train_events)` and steps/epoch identical.
- Ordering semantics identical per §5d: shuffle still enabled with the
  same kwargs, `order_strategy` and `file_order` validation unchanged,
  deterministic-sampler order unchanged, step count identical. The exact
  `shuffle=True` emitted order is NOT asserted.
- Mutation: delete the argv flag → subprocess fails closed (does NOT
  fall back to `TIDMAD`); swap input/target channel → the C1 channel pin
  reds.

**6. Failure and edge cases.**
| Case | Handling |
|---|---|
| profile file missing / unreadable / schema-invalid | **fail closed** with a diagnostic naming the path — never fall back to the singleton |
| geometry does not divide `seg_size` | raise the legality error before any reshape |
| missing data file | preserve today's warn-and-skip, and pin it — changing it is out of scope |
| duplicate file indices in a sample_set | preserve today's behaviour; pin it |
| scope mismatch (profile vs DataScope) | existing DS8 validation must still fire |
| legacy launch without the flag | **Regime-A adapter** (§5c) — resolve the shipped TIDMAD profile exactly. Distinct from the row above: a PRESENT-but-broken profile fails closed; an ABSENT flag from a supported legacy caller does not break |

**7. Verification commands and evidence.** Targeted + affected package +
one bounded pseudo run. Counts, wall time and the pseudo-run log
recorded here.

**8. Commit boundary.** IPC hop + training engine only. Inference and
scoring are C4. No rungs, no legality de-duplication.

---

### 6.4 Commit C4 — inference + scoring subprocess entries

**1. Goal.** Migrate the remaining two subprocess entries through the
same hop, so the whole data path agrees on one profile. Closes M5.

Separate from C3 so the IPC mechanism is reviewed once on the training
path before being replicated.

**2. Scope.**
Changes: `execute_tools/inference_single.py`,
`execute_tools/denoising_score_single.py`, and the raw-validation-name
half of `scoring_utils.py` (`:389`, `:444`) — the FIRST production
consumer of `validation_file_pattern`.
Unchanged: **every denoised/deliverable name and layout**; scoring math;
metric semantics.
Depends on: C1, C2, C3.

**3. Implementation plan.**
- [ ] Add the profile flag + load to both entries, mirroring C3.
- [ ] Route the RAW validation filename through the profile.
- [ ] Migrate geometry / channel / encoding reads in both.
- [ ] Re-verify the raw-vs-denoised boundary line by line.
- [ ] Close §5f: pin the existing derived-artifact INDEXING invariant —
      deliverables keyed by `file_index` through `denoised_filename_fn`,
      keying unchanged. Parity-only; no production change.

**4. Validation plan.**
Unit: raw validation name == the C1 pin; per-read parity in both
entries.
Integration/pseudo: a bounded pass executing the **REAL**
`inference_single` and `denoising_score_single` code across the process
boundary (§5b).
Negative/invalid: missing profile → fail closed in both entries.
Backward-compat: scoring outputs byte-identical on fixture inputs; the
frozen scorer is untouched.
Gate: none.

**5. Acceptance criteria.**
- `validation_file_pattern` has a production consumer (dead seam closed).
- Scoring results byte-identical on the fixture corpus.
- `git diff` contains NO denoised/deliverable filename template change.
- Mutation: point the profile at a different validation pattern → the
  scorer reads the new name (proving it is no longer inlined).
- The derived-artifact indexing invariant is pinned and unchanged (§5f).

**6. Failure and edge cases.**
| Case | Handling |
|---|---|
| a denoised name accidentally routed through the profile | **STOP** — Deliverable Contract leak |
| scoring reads a file the profile does not describe | fail closed |
| partial scope (DS8) interaction | existing validation must still fire |

**7. Verification commands and evidence.** Targeted + affected package +
pseudo inference/scoring. Counts and wall time recorded here.

**8. Commit boundary.** Two subprocess entries + the raw-name half only.

---

### 6.5 Commit C5 — legality de-duplication + `compute_raw_baseline`

**1. Goal.** Remove the two restatements of the legality rule and
migrate the one auxiliary script that production depends on.

Separate because it is a refactor with no new capability (parent §6.3) —
bundling it into C2-C4 would blur "new mechanism" with "de-duplication".

**2. Scope.**
Changes: `nodes/ml_hyperparameter_tune_agent:1103` inline
`psd % segmentation_size`; `agent/skills/evaluate_time_skill/wrapper.py:90`
hardcoded "10,000,000" prose; `scripts/compute_raw_baseline.py`.
Unchanged: `agent/schemas/proposal.py` and `agent/prompts.py`, which
already read the authority; **rendered prompt bytes**.
Depends on: C2.

**3. Implementation plan.**
- [ ] Replace the tuner's inline check with the profile authority.
- [ ] Derive the time-skill message from the profile.
- [ ] Migrate `compute_raw_baseline.py` so it and
      `nodes/scoring_reference.py` cannot disagree on file count.
- [ ] Confirm rendered prompt bytes are unchanged.

**4. Validation plan.**
Unit: the tuner rejects the same invalid sizes as before; the time-skill
message renders the profile's value.
Negative/invalid: an invalid `segmentation_size` still rejected with an
equally diagnostic message.
Backward-compat: **prompt goldens byte-identical** — if any prompt byte
changes, this child takes Gate 1 (parent §10.1 flip condition).
Gate: none, unless the prompt-byte check fails.

**5. Acceptance criteria.**
- No numeric `10,000,000` literal remains in the two named sites.
- Proposer and planner prompt goldens byte-identical.
- `compute_raw_baseline.py` and `nodes/scoring_reference.py` derive file
  count from one authority.
- Mutation: reintroduce the inline check → a test reds.

**6. Failure and edge cases.**
| Case | Handling |
|---|---|
| the message change alters a prompt golden | STOP; either keep bytes identical or take Gate 1 |
| the script needs data not in the profile | record it; do not widen the profile speculatively |

**7. Verification commands and evidence.** Targeted + proposer package
(prompt goldens) + tuner package. Counts and wall time recorded here.

**8. Commit boundary.** De-duplication only.

---

### 6.6 Commit C6 — Stage-B contrast rungs A1 / A2 / B / D (test-only)

**1. Goal.** Prove the abstraction actually varies with the declaration.
Without this the PR has parity but no genericity evidence.

Lands after C2-C5 because every rung needs the fully resolved path.

**2. Scope.**
Changes: contrast fixtures under `tests/`. Zero production diff.
Depends on: C2-C5.

**3. Implementation plan.**
- [ ] **A1 — file count / index space only**: `num_files` ≠ 20, family
      structure and geometry UNCHANGED.
- [ ] **A2 — file-family topology only**: family structure varies; count
      and geometry at the A1-established baseline.
- [ ] **B — sample geometry only**: `psd_segment_length` ≠ 10,000,000,
      all other axes fixed; prove the migrated consumers use the profile
      legality/geometry, not the 10M literal.
- [ ] **D — channel identity only**: channels renamed; prove the loaders
      read the declaration.
- [ ] Confirm each fixture varies EXACTLY one axis.

**4. Validation plan.**
Unit: the four rungs.
Negative/invalid: a geometry that divides nothing → legality error, not
a crash.
Backward-compat: TIDMAD parity pins from C1-C5 still green.
Gate: none.

**5. Acceptance criteria.**
- Four rungs, each single-axis, each asserting behaviour follows the
  declaration.
- For B: a consumer still assuming 10M would red at least one rung —
  demonstrated by mutation.
- Zero production diff.

**6. Failure and edge cases.**
| Case | Handling |
|---|---|
| a rung needs two axes to be meaningful | STOP — the abstraction or the rung is wrong |
| a rung passes with a hardcoded consumer still present | strengthen the rung; it is too weak |

**7. Verification commands and evidence.** Targeted + affected package.
Counts and wall time recorded here.

**8. Commit boundary.** Test-only.

---

### 6.7 Commit C7 — docs + ledger closeout (docs-only)

**1. Goal.** Leave this document and the operator-facing docs true.

**2. Scope.** This document (every box resolved with evidence or
explicitly deferred with a reason); any touched node/module `.md` per
the pre-merge doc-sync rule. Docs-only.
Depends on: C1-C6.

**3. Implementation plan.**
- [ ] Reconcile every checklist box with recorded evidence.
- [ ] Record the class-default decision and the Q02a-1 answer.
- [ ] Update touched module docs, quote-verifying flags/defaults.
- [ ] Record the Checkpoint-D evidence actually run.

**4. Validation plan.** `ruff check`, `ruff format --check`; exact-head
CI. A local full unit suite ONLY if this child justifies its blast
radius in writing (parent §9.1) — otherwise CI is the compatibility
gate.

**5. Acceptance criteria.** Every `[ ]` resolved or deferred with a
reason; ruff clean; exact-head CI green; clean tree; **not merged
without operator approval**.

**6. Failure and edge cases.** A stale ledger at the final head is a
defect in its own right.

**7-8.** Recorded at execution; docs-only boundary.

---

## 7. Gates

Per parent §10 and roadmap §17.0, instantiated from
`docs/gates/gate_testing_standard.md`:

- **Gate 1 — NOT REQUIRED.** This child's commit types are "Config
  files, YAML, schema-only" and "New loader/renderer (pure Python)" →
  the assignment table says **Unit only**.
  **Flip condition**: if C5 (or any commit) changes a rendered prompt
  byte, this child takes Gate 1.
- **Gate 2 — not run by this child.** Once at Step level, owned by the
  FINALIZER 02c.
- **Checkpoint C** is this child's production-boundary evidence.

## 8. `scripts/` disposition (parent §3.1)

`scripts/compute_raw_baseline.py` is **IN** (C5): it regenerates the
per-file reference artifacts `nodes/scoring_reference.py` loads, and
that node builds `_FINE_INDICES = tuple(range(NUM_FILES))`. If the node
migrates and its generator does not, they silently disagree about how
many files exist.

`score_tidmad_official_wavenet.py` and `score_tidmad_official_banded.py`
are **OUT** — zero production-graph imports, no launcher reference:
legacy/peripheral compatibility residue.

## 8a. Narrow re-review (revision 4 — 7 questions)

Scoped exactly as directed. No broadened source audit.

| # | Question | Verdict |
|---|---|---|
| 1 | Does every risky transition have a blocking checkpoint? | **YES, now.** §5a gives CP0 → CP-A1 → CP-A2 → CP-A3 → CHECKPOINT A → B → C → D, each with an explicit FAIL⇒stop. Revision 3 had commits and milestones but no blocking rung between them |
| 2 | Does Checkpoint C exercise real data-reading code? | **YES, now enforced.** §5b states that a pseudo mode replacing or bypassing `train_engine_sandbox`, `inference_single` or `denoising_score_single` does NOT satisfy it, and C3/C4's validation plans were rewritten to require the real modules. The boundary is frozen; the command is not |
| 3 | Is Regime-A compatibility accidentally destroyed? | **NO, now that it is frozen.** §5c separates "flag present but file broken" (fail closed) from "supported legacy caller has never heard of the flag" (Regime-A adapter). The TIDMAD class defaults are kept as documented adapter semantics. Regime B stays Step 12 |
| 4 | Was a stronger shuffle contract invented? | **It nearly was; removed.** Revision 3 would have pinned the emitted DataLoader order under a fixed torch seed. Audit shows `:864-866` passes no `generator`/seed and the module never calls `torch.manual_seed`, so that order is not deterministic today. Pinning it would have created a new promise and invited an implementer to add seeding — a behaviour change. §5d pins the real invariants instead |
| 5 | Does encoding leak Step-03 semantics? | **NO.** §5e limits the claim to declaration liveness + TIDMAD tensor parity, explicitly disclaiming arbitrary dtype/model compatibility, with the offset probe kept as reachability evidence rather than promoted to a rung |
| 6 | Does the Deliverable Contract remain untouched? | **YES.** The §1 boundary note stands; C4 lists a denoised filename in the diff as a STOP; and §5f's audit sharpens the line — indexing (`denoised_filename_fn(file_index)`) is already a seam and is 02a's parity-only surface, while the NAMING template re-inlined at six sites is explicitly the Deliverable Contract's |
| 7 | Does every owned 02a surface have observable DoD evidence? | **YES, now.** Topology → CP-A1/A2 + A1/A2; geometry+legality → CP-A2 + B + C5; encoding → CP-A2 + §5e reachability; channel identity → CP-A2 + D; **derived-artifact indexing → §5f parity pin in C4**, which revision 3 claimed in scope but never closed. That gap is the one this re-review actually fixed |

**No new operator question.** Q02a-1 is answered (§3.4); the four
load-bearing gaps are closed; the remaining choices — profile type
shape, flag naming, helper decomposition, test placement — are
implementation-time by design.

## 9. Stop conditions

- a denoised/deliverable filename template appears in the diff;
- `data_shape_class` string changes;
- a golden outside the declared set changes;
- a profile field lands without a production consumer;
- a subprocess silently falls back to `TIDMAD` when the profile is
  absent;
- the visited sequence, step count or ordering semantics change (§5d);
- a supported legacy TIDMAD caller is broken by genericization (§5c);
- Checkpoint C is claimed on evidence that bypassed the real
  data-reading subprocess code (§5b);
- rendered prompt bytes change without taking Gate 1;
- a milestone proves un-reviewable inside one PR → re-open the parent's
  decomposition decision.
