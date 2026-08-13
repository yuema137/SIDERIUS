# PR 02a — Dataset Profile injection (Step 02, child 1 of 3)

## Status

**REVISION 3 — per-commit implementation plan added. NOT FROZEN.
IMPLEMENTATION NOT AUTHORIZED.**

Parent (governance, ownership, DAG, aggregate acceptance):
[`../step_02_dataset_sample_topology.md`](../step_02_dataset_sample_topology.md).

Position in the DAG: **first**. `02b` and `02c` both depend on it.
Governance order is frozen `02a → 02b → 02c`.

Revision 3 adds the §6 per-commit checklists required before
implementation, each grounded in a source inspection recorded in §3.
**It also raises ONE operator question (§3.4) created by that
inspection** — the parent's re-opening clause in action.

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

They are therefore **internal BLOCKING semantic milestones**:

```text
M1  profile / topology resolution      -> parity + rungs A1/A2
M2  geometry + legality                -> parity + rung B
M3  encoding declaration reachability  -> parity + >=1 production load path reads it
M4  channel identity                   -> parity + rung D
M5  production consumption             -> training + inference + scoring
```

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

### 3.4 OPERATOR QUESTION — raised, not silently absorbed

The parent design says "migrate consumers to injection". The inspection
shows that for three of them this means **adding a config-file IPC hop
to three separate subprocess entry points**. That is more mechanism than
"injection" implies, and the parent did not state it.

> **Q02a-1.** Does 02a carry all THREE subprocess boundaries (training,
> inference, scoring), or should the child be split by boundary?
>
> **Recommendation: keep all three in 02a.** They must AGREE — if
> training resolves geometry from the profile while scoring still reads
> `SEGMENT_LENGTH`, the two disagree about how a file decomposes and the
> run is silently wrong. That correctness coupling is an argument for
> one PR, not three. The mechanism is also identical three times over,
> with an exact in-tree precedent (§3.2).
>
> **Answer this before implementation begins.** The commit plan below
> assumes "keep all three"; if the answer is "split", commits C3 and C4
> become separate children and the parent's DAG changes.

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
| **Default shuffle path** | same DataLoader order under a fixed torch seed; `order_strategy` resolution and `file_order` permutation validation unchanged | **MISSING → C1** |
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
- [ ] Pin the **default shuffle path**: DataLoader visit order under a
      fixed torch seed; `order_strategy` resolution; `file_order`
      permutation validation behaviour.
- [ ] Confirm every new pin FAILS if the behaviour it pins is perturbed
      (each pin gets one mutation).

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
- [ ] **Decide the class-default question** (parent §13b A5):
      `DatasetConfig` carries TIDMAD filename patterns as CLASS defaults.
      Keep them as a DOCUMENTED regime-A compatibility adapter, or
      require declaration. Do not inherit silently as "generic
      defaults".
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
- The class-default decision is recorded in this document with its
  reason.
- Mutation: reverting one consumer to the module constant reds a test.

**6. Failure and edge cases.**
| Case | Handling |
|---|---|
| a consumer has no obvious injection point | record it and move it to C3/C4 rather than inventing a global |
| a profile field has no consumer in this PR | STOP — §0 rule 8 dead seam |
| `data_shape_class` changes | STOP — measurement-store keys invalidated |
| legacy caller passes no profile | must fail closed or resolve the documented regime-A default — decide explicitly, never silently |

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
Integration/pseudo: a bounded pseudo training run through the sandbox
proving the subprocess receives and uses the profile.
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
- Under the default shuffle path with a fixed torch seed: identical
  DataLoader visit order, identical selection, identical step count.
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
| legacy launch without the flag | decide explicitly: fail closed (recommended) or documented adapter — never silent |

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

**4. Validation plan.**
Unit: raw validation name == the C1 pin; per-read parity in both
entries.
Integration/pseudo: a bounded pseudo inference + scoring pass.
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

## 9. Stop conditions

- Q02a-1 (§3.4) unanswered when implementation would begin;
- a denoised/deliverable filename template appears in the diff;
- `data_shape_class` string changes;
- a golden outside the declared set changes;
- a profile field lands without a production consumer;
- a subprocess silently falls back to `TIDMAD` when the profile is
  absent;
- the visited sequence, step count or default-shuffle behaviour changes;
- rendered prompt bytes change without taking Gate 1;
- a milestone proves un-reviewable inside one PR → re-open the parent's
  decomposition decision.
