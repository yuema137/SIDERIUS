# Step 02 — Dataset & Sample Topology — detailed design (parent)

## Status

**LIVING PARENT — DELIBERATELY NOT FROZEN (operator decision,
2026-08-13). PR 02a IMPLEMENTATION AUTHORIZED AND IN PROGRESS
(branch `feat/generic-framework-step-02a-dataset-profile-injection`);
02b and 02c NOT AUTHORIZED.**

> **Do not "fix" this by freezing it.** The operator decided this parent
> stays a LIVING document until Step-02 closeout, because it is the
> step's governance and STATUS authority: it carries child status, the
> aggregate checkpoint ladder, the Step-level Gate, the convergence
> ledger and the roadmap-sync obligation, all of which must be updated
> as children land. Freezing it would fight its purpose.
>
> **Children freeze individually; the parent does not.**
>
> | Document | State |
> |---|---|
> | `pr_02a_dataset_profile_injection.md` | **FROZEN / OPERATOR APPROVED** at `cfc83b1e` (2026-08-13) |
> | `pr_02b_selection_sampleset.md` | DRAFT — to be revised AFTER 02a lands |
> | `pr_02c_systematic_groups.md` | DRAFT — to be revised AFTER 02a lands |
> | this parent | LIVING until Step-02 closeout |
>
> Expected update points: after 02a merges (child status, any correction
> its implementation surfaces, and the detailed 02b/02c plans, which are
> deliberately NOT elaborated yet), and again at Checkpoint E when 02c
> closes the Step.

### Authority rule between this parent and a frozen child (FROZEN — operator decision, 2026-08-14)

```text
overall roadmap
  └── Step 02 parent        <- LIVE throughout Step 02
       ├── PR 02a design    <- FROZEN -> implementation -> merge
       ├── PR 02b design    <- may be revised after 02a findings; frozen later
       └── PR 02c design    <- may be revised after 02a/02b findings; frozen later
```

| Document | Authority |
|---|---|
| **PR-02a child design** | the **frozen implementation contract** for 02a — authoritative for its scope, invariants, checkpoints and validation |
| **Step-02 parent (this doc)** | the **live** Step-level governance / integration document — authoritative for ownership, the child DAG, cross-child obligations and aggregate Step acceptance |

Implementation discoveries MAY update this parent, and through it may
refine 02b/02c design, Step-level aggregation, later checkpoints and
convergence findings. They may **NOT** silently rewrite PR-02a's frozen
scope or acceptance criteria while 02a is in progress. **A material
conflict with the frozen 02a contract requires an explicit operator
decision.**

A child PR may begin when — and only when — **its own** design is
frozen, this parent exists and is internally consistent, and the
repository base is verified. This parent's freeze state is **not** a
precondition, and a session must never require it to be frozen. This is
the roadmap's module-by-module philosophy (§0 rule 1) applied to
documents: **freeze the locally executable contract; never freeze a
design that has not yet earned implementation evidence.**

Revision 2 content (below) is the operator-reviewed governance the
children implement against; it changes only by a new operator decision,
even though the document itself stays open for status and for the
child-plan detail still to be written.

Revision 2 applies the operator review of 2026-08-13. The three-child
decomposition is APPROVED IN PRINCIPLE; no fourth behavioural child is
added. Corrections applied: **02c designated Step FINALIZER**;
**4.8-B promoted to REQUIRED** (the deferral was a logical gap — see
§8); **4.8-A split into atomic A1/A2**; the Gate-2 SampleSet criterion
made precise; the per-child local-full-suite requirement removed as an
Evidence-Economy violation; `scripts/` ownership decided by measured
reachability; and the §13/§17.0 documentation contradiction reconciled.

Design branch base: `master` at `2e716dd2` (Step 01 closed — PR #199
`39f89f52`, PR #200 `adbc835d`, PR #201 `fe05f5f7`, all ancestors;
§15.1 marks Step 00 and Step 01 COMPLETE).

Parent authority: `../siderius_generic_framework_upgrade.md` §4 (module),
§2 (compatibility), §3.1 (four contracts), §14 (convergence ledger),
§15.1 (completion matrix), §17 (checkpoint model), §18 (deferred).

**PR decomposition decision: THREE child PRs** (§6). The child documents
live in `step_02_dataset_sample_topology/` and are created only because
the audit below found three independently mergeable behavioural units
with three DIFFERENT parity oracles and three DIFFERENT failure classes.

---

## 0. Precondition — Step 01 is closed (verified, not assumed)

| Check | Evidence |
|---|---|
| PR #201 merged | GitHub: `state=MERGED`, `mergeCommit=fe05f5f7`, 2026-08-13 |
| PR #199 / #200 merged | `39f89f52`, `adbc835d` — both `MERGED` |
| all three on master | `git merge-base --is-ancestor` → YES for all three against `origin/master` |
| §15.1 matrix | Step 0 `COMPLETE — MERGED`; Step 1 `COMPLETE — MERGED`; Step 2 `NOT STARTED` |
| parent status | `STEP 01 STATUS: COMPLETE` |
| tree | clean; `master == origin/master == 2e716dd2` |

---

## 1. Source audit of CURRENT master

Every claim below was re-read from source at `2e716dd2`. Line numbers are
dated evidence, not addresses to code against.

### 1.1 What already exists — and is BETTER than §4 assumes

Three roadmap statements are now STALE in the PR's favour. Recording
them matters, because two of them change what Step 02 must build.

> **Previous assumption (§4.7):** "Default profile deep-equals today's
> singleton (constants pinned — **a NEW pin, none exists**)."
> **Audit evidence:** `tests/unit/execute_tools/test_step00_dataset_baselines.py`
> pins `TIDMAD.model_dump()` field-by-field (`test_all_six_fields_deep_equal`),
> the module constants against the singleton, the exact 36-entry
> `valid_segmentation_sizes()` list, both filename renders, the default
> `DataScope` resolution, and the exact `data_shape_class` string
> `psd10000000_seg200_files20` plus the measurement-identity component
> order.
> **Corrected understanding:** Step 00 already landed the dataset
> baseline. **Checkpoint 0 for Step 02 is largely MET before Step 02
> starts.**
> **Consequence:** Step 02 does NOT need a pre-extraction capture PR for
> the profile constants. It needs to identify only the *gaps* (§8.2).

> **Previous assumption (§4.7):** SampleSet sha16 goldens are a surface
> Step 02 must keep unchanged — implying they exist but unspecified.
> **Audit evidence:** they exist and are stronger than expected —
> `test_sample_set_builder.py` pins five digests: the three trial
> strategies at `seed=42, portion=0.05` under full scope
> (`TestDataScopeBehavioralIdentity.GOLDEN`), plus normal mode and
> partial-scope snapshot (`TestStep00SelectionDigests`, added by
> Step-00 DS-3). It also pins the first five sampled segment indices.
> **Consequence:** child 02b inherits a real parity oracle on day one.
> Its acceptance is "these five digests are byte-identical", not a new
> capture.

> **Previous assumption (§4.2):** `validation_file_pattern` is dead
> (zero consumers).
> **Audit evidence:** still true in PRODUCTION — no production module
> calls it. But it is no longer *unpinned*: Step-00's baseline asserts
> `TIDMAD.validation_file_pattern.format(file_index=7) ==
> "abra_validation_0007.h5"`. There is also no
> `validation_file_name()` counterpart to `training_file_name()`, and
> `dataset_config.py:110-116` says so explicitly in its docstring.
> **Consequence:** the seam-without-consumer is real and is 02a's to
> close — §4.4 already promised it "finally gains its first consumers:
> scorer + inference read paths".

### 1.2 The extraction blast radius, measured

**Bare-constant importers (`SEGMENT_LENGTH` / `SEGMENTS_PER_FILE` /
`NUM_FILES`), production only — 10 modules:**
`execute_tools/train_engine_sandbox.py:19`,
`execute_tools/inference_single.py:16`,
`execute_tools/scoring_helpers.py:33`,
`execute_tools/denoising_score_single.py:159`,
`execute_tools/workload_resolvers.py:36`,
`execute_tools/sample_set_builder.py:21`,
`agent/skills/evaluate_time_skill/wrapper.py:65`,
`agent/skills/inference_skill/estimator.py:55`,
`agent/schemas/score_table.py:22`,
`nodes/scoring_reference.py:24`.
Plus three `scripts/` consumers.

**Singleton (`TIDMAD`) importers, production — 12 sites** including
`agent/schemas/hyperparam_tuning.py:35`,
`agent/schemas/proposal.py:27` (as `DATASET_CONFIG`),
`core/campaign_artifacts.py:88`, `core/resume.py:49`,
`execute_tools/data_paths.py:87`, `health_checks/config.py:25`,
`health_checks/spectral_peak_ratio.py:31`,
`sample_set_builder.py:20`, `train_engine_sandbox.py:20`, the tuner and
proposer nodes.

**A second re-export hop exists**: `scoring_utils.py:63` re-imports from
`dataset_config`, and `sample_set_builder.py:21` reaches the constant
*through scoring_utils*, not from the authority. Any extraction must
collapse this hop rather than preserve it.

### 1.3 Sample geometry and legality — one authority, three restatements

The legality rule already HAS a single authority:
`DatasetConfig.valid_segmentation_sizes()` (`dataset_config.py:118-138`,
sqrt enumeration). Its consumers:

| Site | Form | Disposition |
|---|---|---|
| `agent/schemas/proposal.py:1104,1127` | calls `DATASET_CONFIG.valid_segmentation_sizes()` | already correct — reads the authority |
| `agent/prompts.py:746` | `dataset_config.valid_segmentation_sizes()` for the planner prompt | already correct |
| `nodes/ml_hyperparameter_tune_agent:1103` | **restates the rule inline**: `if psd % segmentation_size != 0` | de-duplicate |
| `agent/skills/evaluate_time_skill/wrapper.py:90` | **hardcoded prose** "next valid divisor of 10,000,000" | derive from the profile |

So "3 enforcement layers" (§4.2) is confirmed, but the fix is small and
is a **refactor with no new capability** — it is a semantic commit inside
02a, NOT a child PR (§6.3).

**`psd_segment_length` vs `segmentation_size` is already separated
correctly** and must stay that way: the former is the dataset's own
decomposition (config), the latter is a proposer-owned model
hyperparameter (finding 17). Step 02 owns only the legality *rule*.

### 1.4 Systematic groups — three informal encodings, three owners

| Literal | Site | Meaning | Consumer |
|---|---|---|---|
| `[0, 10, 19]` | `sample_set_builder.py:24` `ANCHOR_FILES` | "frequency extrema" | anchors selection strategy |
| `[3, 10, 17]` | shipped `configs/health_checks.yaml` `peek_file_indices` | "band triplet" | health gates |
| `[3, 10, 17]` | **`core/campaign_artifacts.py:57`** — `if requested == [3, 10, 17]:` | the same triplet, **compared as a literal in a validator** | campaign-artifact validation |
| `range(20)` ×3 | `health_checks/{pearson_dispersion:34, per_file_output_std:30, spectral_peak_ratio:39}.py` `_DEFAULT_FILE_RANGE` | "all files" | health-check file fallback |

The `campaign_artifacts.py:57` literal comparison is the sharpest
evidence that groups have no owner: a *validator* branches on an exact
list value. The three `range(20)` copies re-hardcode `num_files`
alongside a `TIDMAD.num_files` that already exists.

### 1.5 Encoding declaration — no declaration anywhere

`+128` offset and `int8` are inlined at ~8 production sites
(`train_engine_sandbox.py:95,112,124,126,169,182,196,251,350`;
`inference_single.py:188,189,702,703,842,843`), with `minlength=256`
alongside. There is no declaration object. §4.4 assigns the
dtype+offset **declaration** to Step 02 (derived by §5/§7) — confirmed
as genuinely unowned.

### 1.6 Channel identity — an undeclared dataset fact (audit correction)

> **Previous assumption (this design's own first draft):** rung 4.8-D
> "truth availability" belongs to Step 03/06, because "is there a truth
> channel" governs what can be scored and what the model must output.
> **This was asserted without auditing, and the source contradicts it.**
> **Audit evidence:** the loaders address the truth channel by a
> hardcoded HDF5 path —
> `_h5_dataset(f, "timeseries", "channel0001", "timeseries")` for the
> INPUT and `"channel0002"` for the TARGET
> (`train_engine_sandbox.py:111,114,168,171,231,232,319,320`;
> `inference_single.py:67,68,602,603,789,790`;
> `scoring_utils.py:158,161`; `health_checks/_peek.py:100`,
> `_multi_file_peek.py:177`, and the three per-file checks;
> `array2h5.py:49,63` on the write side). ~15 production sites, no
> declaration. `core/runtime_control/gpu_measurement_data.py:61-62`
> already names them — `INPUT_CHANNEL = "channel0001"`,
> `TARGET_CHANNEL = "channel0002"`, with the comment "channel0001 is the
> input the training loop feeds the model and channel0002 is the clean
> target" — proving the concept is nameable and that ONE module already
> found it necessary.
> **Corrected understanding:** *which channel is the input and which is
> the truth* is an INPUT DATASET CONTRACT fact — the same class as the
> filename pattern. It is Step-02-owned. What is NOT Step-02-owned is
> truth ABSENCE semantics (an unsupervised task with no clean channel at
> all), which changes what the model must output and what can be scored
> — Step 03 / Step 06.
> **Consequence:** channel identity joins 02a's topology ownership, and
> rung 4.8-D is RE-SELECTED in its channel-identity form (§8).

### 1.7 Production consumers available for Checkpoint C

The §15.1 matrix names "training engine + sample-set builder". The audit
finds that **insufficient as the minimum honest set**: the profile is
read on three production data paths, and the one most likely to break
silently is scoring.

Minimum honest live-consumer set for Step 02: **training engine
(`train_engine_sandbox`), inference (`inference_single`), and the
scoring path (`scoring_helpers` / `denoising_score_single`)** — plus
`sample_set_builder` for 02b and the health checks for 02c. Recorded as
a correction to the matrix (§13).

---

## 2. Step-02 final effect (observable behaviour)

After all three children merge:

> Every dataset-semantic decision under Step-02 ownership — which files
> exist and what they are named, how a file decomposes into addressable
> samples and which sample shapes are legal, how the raw values are
> encoded, which samples a selection strategy picks, and which files a
> named group denotes — is answered by a **resolved Dataset Profile
> passed to the consumer**. No migrated consumer imports a module-level
> dataset constant, restates a legality rule, or branches on a literal
> file list. Pointing a run at a dataset with a different file count,
> naming, decomposition length or group map changes behaviour through
> the profile alone, with no edit to engines, scoring, selection or
> health checks.

Explicitly NOT claimed: launcher/orchestration task binding (Step 10),
sandbox/execution-infrastructure residue and cleanup globs (Step 11),
Deliverable Contract naming/layout/attrs (§3.1, owner TBD), model I/O
semantics (Step 03), metric scoreability (Step 06). Those remain
explicitly deferred rather than falsely claimed clean.

---

## 3. Ownership — and explicit non-ownership

**Step 02 OWNS** (re-verified against source, not inherited):

- file topology: families, index space, counts, name patterns — and the
  first production consumer of `validation_file_pattern`;
- **channel identity**: which in-file channel is the model INPUT and
  which is the TRUTH/target (§1.6). Identity only — truth-ABSENCE
  semantics stay with Steps 03/06;
- sample decomposition geometry (`psd_segment_length`,
  `segments_per_file`) and the sample-shape **legality rule**;
- the data-side **encoding declaration** (dtype + offset + class count
  as a dataset fact);
- selection/split semantics: strategy definitions, per-family selection,
  packing rule, group-aware anchor selection;
- systematic named groups as declared data;
- derived-artifact **INDEXING by input identity**.

**Step 02 does NOT own** — each with the reason it was rejected:

| Not owned | Why, from source |
|---|---|
| Deliverable naming/layout/dtype/attrs | `array2h5.py` writes with its own hardcoded attrs; §3.1 makes this a DISTINCT contract. TIDMAD using HDF5 on both sides is not a reason to collapse them |
| `segmentation_size` itself | proposer-owned model hyperparameter; only its legality rule is dataset-side |
| Model I/O semantics | `ForwardContract` (`agent/schemas/task_config.py`) contains input/output shape, num_classes, task_type — and **zero** file/segment/topology concepts. Step 03 |
| Metric scoreability | Step 06 |
| Portions / seeds | LLM-planned + operator-clamped runtime inputs, not config (§4.4, adversarial finding 1) |
| Resolved SampleSets | runtime state, not config |
| `data_shape_class` VALUE | Step 02 supplies the geometry it is derived FROM; the key mechanism is runtime-control's (§14) |
| Launcher / sandbox residue | Steps 10 / 11 |
| `scripts/` constant consumers | **decided by measured reachability, not by directory** — see §3.1 |

---

### 3.1 `scripts/` ownership — decided by reachability, audited individually

Default: OUT of Step 02. But "it lives under `scripts/`" is not a
reason — reachability is. Each of the three bare-constant consumers was
audited against the production graph (`workflows/`, `nodes/`, `core/`,
`execute_tools/`, `agent/`) and the chain launchers:

| Script | Reachability evidence | Classification | Step-02 disposition |
|---|---|---|---|
| `scripts/score_tidmad_official_wavenet.py` | zero imports from the production graph; not referenced by `sdsc_submission_scripts/` or any chain launcher | **legacy / peripheral compatibility residue** | **OUT.** Step 02 does not clear it |
| `scripts/score_tidmad_official_banded.py` | same — zero production imports, no launcher reference | **legacy / peripheral compatibility residue** | **OUT** |
| `scripts/compute_raw_baseline.py` | **reachable from production**: `nodes/scoring_reference.py:34` names it in the operator-facing regeneration hint for the reference artifacts that node LOADS, and `execute_tools/scoring_helpers.py:62` documents a parity relationship with its `_per_file_log_score` | **supported auxiliary PRODUCER** of a production-consumed artifact | **IN scope for 02a.** `nodes/scoring_reference.py` builds `_FINE_INDICES = tuple(range(NUM_FILES))` to index per-file reference artifacts; if the node migrates to the profile and its generator does not, the two silently disagree about how many files exist |

The rule this establishes, for later steps to reuse: **a script is
Step-02's if production reads what it writes or production points
operators at it; otherwise it is compatibility residue.** Do not assign
`scripts/` to Steps 10/11 wholesale.

## 4. FX-3 / FX-4 disposition — ROUTED TO STEP 03, with evidence

Step 01 deferred FX-3 (preset resolution) and FX-4 (preset-vs-explicit
mismatch failing closed before the LLM boundary) to "the structured
contract owner (step 2 / step 3)". This design resolves the ambiguity.

**Answering the five required questions:**

1. *What structured input semantics does Step 02 genuinely need to own?*
   The dataset-side declaration: file topology, decomposition geometry,
   legality, and the dtype/offset/class-count encoding declaration.
   These are properties of the DATA ON DISK.

2. *What belongs only to Step 03?* The **model I/O contract** —
   named tensors, ranks, ordered axes, dtypes, cross-tensor
   relationships. Source evidence: `ForwardContract` holds exactly
   `input_shape`, `input_description`, `output_shape`,
   `output_description`, `num_classes`, `embedding_note`,
   `output_head_note`, `task_type`, `task_note` — and
   `agent/schemas/task_config.py` mentions no file, segment, PSD or
   dataset concept anywhere. Step 01's landed rungs FX-2 (rank-4 neutral
   axes + unfamiliar `task_type`) and FX-5 (multi-channel) varied THIS
   object. FX-3/FX-4 are about the same object.

3. *Can FX-3/FX-4 honestly land in Step 02?* **No.** A preset resolver
   must normalise into ONE contract; the contract it normalises into is
   the Model I/O contract Step 02 does not own. Building it here would
   force Step 02 to invent Model-I/O semantics speculatively — the exact
   §0 rule 8 anti-pattern, and it would create a second authority beside
   `ForwardContract`.

4. *Do they require a Step-02 child PR?* **No.**

5. *Routing.* FX-3 and FX-4 are hereby assigned to **Step 03
   (§5 Model/Loss Contract)**, tracked as roadmap deferred decision
   **D13**. Step 02 carries one INTERFACE OBLIGATION so the rungs remain
   landable there: Step 02's dataset profile must expose its geometry
   and encoding declaration as a **resolvable, inspectable object**, so
   a Step-03 preset resolver can cross-validate a preset against the
   dataset declaration and fail closed on conflict. That obligation is
   satisfied by 02a's normal work — it adds no Step-02 scope.

**The obligation does not disappear**: it is recorded here, in D13, and
must be re-stated in the Step-03 design's Stage-B ladder.

---

## 5. Compatibility contract — strongest observable criterion per surface

Per §2: name the criterion, never "behaviour unchanged".

| Surface | Strongest observable criterion | Baseline status |
|---|---|---|
| Resolved TIDMAD profile | `resolved.model_dump()` deep-equals today's `TIDMAD.model_dump()`, field by field | **EXISTS** — Step-00 `test_all_six_fields_deep_equal` |
| Legality list | `valid_segmentation_sizes()` returns the exact 36-entry list | **EXISTS** — Step-00 |
| Training filename | `training_file_name(0)`/`(19)` render byte-identical | **EXISTS** — Step-00 |
| Validation filename | pattern formats byte-identical **and** the new production read path produces the same string the scorer/inference inline today | **PARTIAL** — pattern pinned; the inlined scorer/inference literals are NOT pinned against the pattern → **02a must add this pin BEFORE routing reads through the profile** |
| `data_shape_class` | exact string `psd10000000_seg200_files20`; measurement-store keys not invalidated | **EXISTS** — Step-00 |
| SampleSet identity | the five sha16 digests unchanged (3 strategies + normal + partial) and first-five segment indices unchanged | **EXISTS** — `test_sample_set_builder.py` |
| SampleSet JSON round-trip | key coercion behaviour unchanged at every consumer (keys become strings; consumers re-int) | **MISSING** → 02b must pin the round-trip contract at one boundary before changing the builder |
| Encoding | `+128`/int8 declaration produces byte-identical loaded tensors | **MISSING** → 02a adds a loader-level pin |
| Anchors artifact | anchors selection identity unchanged; `segment_anchors.json` untouched | **EXISTS** — Step-00 numeric baselines |
| Health peek behaviour | the shipped `[3,10,17]` peek resolves to the same files; gate verdicts identical on fixture outputs | **PARTIAL** — behaviour tested; the *literal-vs-declaration* equivalence is not → 02c pins it |
| Rendered prompts | proposer known-constraints block + planner divisor list byte-identical under TIDMAD | **EXISTS** — Step-00 PB goldens + Step-01 goldens |

**Rule**: where a baseline is MISSING, the owning child captures it
BEFORE the change it is meant to pin — the S1-E capture-first precedent.
Never regenerate a baseline after changing the behaviour it pinned.

---

## 6. PR decomposition — THREE children

### 6.1 The decision

Default is one Step = one PR. The audit overrides the default because
three candidate units each have a **distinct capability, distinct
production consumers, a distinct parity oracle and a distinct failure
class**. Two further candidates were REJECTED as children (§6.3) — the
split is not one-PR-per-concept.

### 6.2 The three children

```text
   SEMANTIC dependency          GOVERNANCE / merge order
   -------------------          ------------------------
        02a                            02a
         |                              |
    +----+----+                        02b
    |         |                         |
   02b       02c                       02c  <- Step FINALIZER
```

**Semantic dependency**: 02b and 02c each require only 02a. They do not
depend on each other.

**Governance order is FROZEN as `02a → 02b → 02c`** even so, because
aggregate evidence must have a named owner. 02c is the **Step
FINALIZER** and owns, once all three executable capabilities are
present:

- assembled Step-02 Checkpoint C reconciliation;
- the ONE Step-level Gate 2;
- the single local full unit suite at the assembled head;
- Checkpoint E — §15.1 row, §14 ledger rows, folder README, this parent;
- Step-02 closeout.

This is a governance designation, NOT a claim that 02c technically needs
02b. The alternative — "whichever child merges last does it" — leaves
aggregate evidence dynamically owned and therefore owned by nobody. A
fourth closeout-only PR was considered and rejected as ceremony.

Putting Gate 2 in 02c is also natural on the merits: Gate 2 exercises
HealthGates, and 02c is the child that changes which files those gates
judge.

---

**CHILD 02a — Dataset Profile injection**

```text
CAPABILITY: production data paths resolve topology, geometry, legality
  and encoding from a RESOLVED profile argument instead of module-level
  constants — so a differently-shaped dataset changes behaviour through
  the profile alone.
AUTHORITY IT OWNS: file families/identity/patterns, index space, counts,
  decomposition geometry, the legality rule, the dtype+offset encoding
  declaration, CHANNEL IDENTITY (which in-file channel is input vs
  truth — §1.6), derived-artifact indexing by input identity.
PRODUCTION CONSUMER: train_engine_sandbox, inference_single, the scoring
  path (scoring_helpers / denoising_score_single), workload_resolvers +
  the two estimators — all in the same PR. Includes the FIRST production
  consumer of validation_file_pattern (scorer + inference read paths).
TIDMAD PARITY SURFACE: profile deep-equality; the 36-entry legality
  list; both filename renders; data_shape_class exact string;
  encoding-produces-identical-tensors (new pin); channel resolution
  producing byte-identical input/target tensors; rendered proposer and
  planner prompt bytes.
CONTRAST AXIS: FOUR separate single-axis fixtures, never combined —
  4.8-A1 (file count), 4.8-A2 (family topology), 4.8-B (sample
  geometry), 4.8-D (channel identity).
CHECKPOINT: local A (parity) + local B (A1, A2, B, D) + local C
  (engines/inference/scoring read the resolved profile in production,
  including at least one load path reading the ENCODING declaration).
DEPENDS ON: nothing beyond merged Step 01.
CAN MERGE AND BE USEFUL ALONE?: YES. After 02a the data path is
  profile-driven end to end; selection and groups still hardcode, which
  is honest and visible rather than silently half-done.
WHY A PR AND NOT A SEMANTIC COMMIT: it converts ~13 production modules
  from constant-import to injection, closes a dead seam, and carries its
  own irreversible risk class — a changed filename or shape-class string
  invalidates measurement-store keys. That needs its own review and
  rollback boundary.
WHY NOT SPLIT FURTHER (encoding / channel identity as a 4th PR):
  topology, geometry, encoding and channel identity are not four
  capabilities — they are four facets of ONE capability, "the core data
  path reads its semantics from the Dataset Profile". They share a
  single injection seam and migrate the same consumers in the same
  files; splitting them would mean touching train_engine_sandbox,
  inference_single and the scoring path three more times, each time
  landing a profile field whose siblings are still hardcoded. They are
  therefore internal BLOCKING semantic milestones of 02a, not child PRs
  (§6.3). **Re-opening clause**: if 02a's own source audit shows any one
  of them cannot be reviewed or rolled back coherently inside the PR,
  STOP and re-open this decomposition decision rather than forcing the
  frozen parent plan.
```

**CHILD 02b — Selection & SampleSet semantics**

```text
CAPABILITY: sample selection resolves counts and index space from the
  injected profile, so a different topology produces correct SampleSets
  rather than silently sampling TIDMAD's 200-segment/20-file shape.
AUTHORITY IT OWNS: strategy definitions, per-family selection rules, the
  packing rule (the trial asymmetry made explicit), and the SampleSet
  JSON round-trip contract at one boundary.
PRODUCTION CONSUMER: sample_set_builder + the tuner's formal/trial
  sample-set construction, in the same PR.
TIDMAD PARITY SURFACE: the five sha16 digests + first-five segment
  indices, byte-identical; the JSON round-trip pin it captures first.
CONTRAST AXIS: the ESTABLISHED topology contrast (A1/A2) re-used
  THROUGH the selection path. No new axis.
CHECKPOINT: local A (digests) + **local B = topology contrast
  propagated through the SampleSet selection path** (a contrast topology
  must yield a correctly shaped SampleSet — this IS 02b's Stage-B proof,
  not a formality) + local C (tuner builds a real run's sample set from
  the profile).
DEPENDS ON: 02a (needs a profile to inject).
CAN MERGE AND BE USEFUL ALONE?: YES, given 02a.
WHY A PR AND NOT A SEMANTIC COMMIT: its failure class is unique and
  severe — a changed SampleSet digest shifts every downstream experiment
  identity, invalidating comparability across the whole chain. It has
  its own oracle (five digests) that no other child can red.
```

**CHILD 02c — Systematic groups**

```text
CAPABILITY: named groups are declared data. Anchors, health peeks and
  campaign validation read the declared group map instead of three
  independent literals, so a task can declare its own band structure.
AUTHORITY IT OWNS: named group declarations (bands) and group-aware
  anchor selection.
PRODUCTION CONSUMER: sample_set_builder's anchors strategy, the three
  health checks' file resolution, and core/campaign_artifacts.py's
  validator — all in the same PR.
TIDMAD PARITY SURFACE: anchors selection identity ([0,10,19] resolves
  identically); the shipped [3,10,17] peek resolves identically; the
  three range(20) fallbacks resolve to the same files; gate verdicts
  identical on fixture outputs.
CONTRAST AXIS: 4.8-C group semantics only (TIDMAD shape, DIFFERENT
  declared group map — proves anchors/peeks read groups, not literals).
CHECKPOINT: local A (identity) + local B (4.8-C) + local C (health gates
  evaluate a real round through the declared map).
FINALIZER DUTIES (governance, §6.2): assembled Checkpoint C
  reconciliation; the ONE Step-level Gate 2; the single local full unit
  suite at the assembled head; Checkpoint E; Step-02 closeout.
DEPENDS ON: 02a (declaration lives on the profile). INDEPENDENT of 02b.
CAN MERGE AND BE USEFUL ALONE?: YES.
WHY A PR AND NOT A SEMANTIC COMMIT: different consumers (health +
  campaign validation, not the data path), a different oracle (gate
  verdicts, not tensors or digests), and a different failure class —
  a wrong group map silently changes WHICH files health gates judge,
  which is a scientific-integrity failure rather than a crash.
```

### 6.3 Candidates REJECTED as children — and why

| Rejected candidate | Why it is not a PR |
|---|---|
| **Sample geometry + legality as its own child** | The authority already exists (`valid_segmentation_sizes`) and two of four consumers already read it. The remaining work is de-duplicating the tuner's inline `psd % seg` check and the time-skill's hardcoded "10,000,000" prose. That is a **refactor with no independently observable capability** — SIDERIUS gains nothing a user could name. Folded into 02a as a semantic commit. |
| **Structured input / preset semantics (FX-3/FX-4)** | Routed to Step 03 (§4). Not Step-02-ownable without inventing Model-I/O semantics. |
| **"Stage A" and "Stage B" as separate PRs** | §7 forbids the mechanical version. Each child carries its own extraction AND its own contrast rung, because a contrast fixture with no extraction to prove is vacuous, and an extraction with no contrast is unproven. |

### 6.4 What becomes TRUE only after ALL THREE merge

The §2 final effect. Individually: 02a makes the data path
profile-driven; 02b makes selection profile-driven; 02c makes group
semantics declared. Only together do they satisfy "no migrated consumer
independently restates dataset semantics".

---

## 7. Stage-A / Stage-B discipline

Each child is internally staged: extraction commits first (byte-parity
against the oracles in §5), then its contrast rung. Extraction and
generalisation are not bundled *within a commit*; they are bundled
*within a PR*, because the roadmap's no-dead-seam rule requires a seam
to land with its consumer and the contrast is what proves the seam is
real.

---

## 8. Atomic contrast ladder — REQUIRED set

§4.8 offers four candidate rungs. Revision 2 requires **all four
concerns**, with topology refined into two atomic sub-rungs. Only the
"minimum subset" framing of revision 1 is withdrawn.

> **Previous assumption (revision 1):** 4.8-B (sample geometry) could be
> deferred, because `valid_segmentation_sizes()` already exists as a
> single authority and Step 00 froze its exact 36-divisor output.
> **Operator finding (2026-08-13) — a real logical gap:** those two
> facts prove only that *under TIDMAD's `psd_segment_length =
> 10,000,000` the helper still behaves as before*. They prove **nothing**
> about whether consumers stop assuming 10,000,000 when the profile says
> otherwise. The audit itself found two consumers that do assume it —
> the tuner's inline `psd % segmentation_size` check and the time-skill's
> hardcoded "next valid divisor of 10,000,000" prose (§1.3).
> **Corrected understanding:** Step 02's final effect explicitly claims
> that *"a different decomposition length changes behaviour through the
> profile alone"*. A claim of that form REQUIRES a contrast proof.
> Asserting geometry genericity while only ever testing 10M is exactly
> the gap the atomic ladder exists to close.
> **Consequence:** **4.8-B is REQUIRED**, owned by 02a.

| Rung | Required? | Owner | What it varies / proves |
|---|---|---|---|
| **4.8-A1 — file count / index space only** | **YES** | 02a | `num_files` ≠ 20, the two-family structure UNCHANGED. Isolates count from family shape, so a failure names one cause |
| **4.8-A2 — file-family topology only** | **YES** | 02a | family structure changes; count and geometry held at the A1-established baseline. May build on A1's proven baseline (the "later rung may build on a proven earlier rung" rule) |
| **4.8-B — sample geometry only** | **YES** | 02a | `psd_segment_length` / decomposition geometry ≠ 10,000,000, other axes fixed. Proves the affected consumers read the profile-owned legality and geometry rather than the 10M literal. Uses the EXISTING `DatasetConfig` authority — no new geometry abstraction |
| **4.8-C — group semantics only** | **YES** | 02c | TIDMAD shape, a DIFFERENT declared group map. The only rung that can prove anchors/peeks read a declaration rather than a literal |
| **4.8-D — channel identity only** | **YES** | 02a | TIDMAD shape, channels renamed. Proves the loaders read the channel declaration rather than `channel0001`/`channel0002` (§1.6) |

**Atomicity is binding.** No rung changes more than its named axis. In
particular neither A1 nor A2 may touch geometry, encoding, channel
identity or groups. Exact fixture values are implementation-time.

**02b owns no new axis** — it re-uses the ESTABLISHED topology contrast
**through the SampleSet selection path**, which is its local
Checkpoint-B evidence (§9). Re-using a proven axis through a second
consumer is Stage-B proof, not a new rung.

Nothing is deferred from this ladder.

## 9. Checkpoint model (§17)

| CP | Step-level definition | Owner / closing evidence |
|---|---|---|
| **0 BASELINE AVAILABLE** | the behaviour being extracted is pinned BEFORE extraction | **Largely MET by Step 00** (profile deep-equality, legality list, filenames, `data_shape_class`, five SampleSet digests, anchors identity). Gaps (§5) are captured FIRST by their owning child: 02a — validation-name, encoding-tensor, channel-resolution; 02b — SampleSet JSON round-trip, packing; 02c — the three group-equivalence pins |
| **A EXTRACTION PARITY** | every §5 criterion holds byte-identically under TIDMAD | 02a (profile/geometry/encoding/channel), 02b (five digests), 02c (group identity) |
| **B GENERIC CONTRAST** | the REQUIRED rungs land, each varying exactly one axis: **A1, A2, B, C, D** | 02a owns **A1, A2, B, D**; 02c owns **C**; 02b's local B is the established topology contrast propagated through the SampleSet selection path |
| **C LIVE INTEGRATION** | the RESOLVED profile is consumed in production, not by tests only | 02a — training engine, inference AND the scoring path, with ≥1 load path reading the ENCODING declaration; 02b — tuner sample-set construction; 02c — health gates + campaign validator. **02c reconciles the assembled Step-level Checkpoint C** |
| **D REGRESSION** | see the cadence below | each child locally + **exact-head CI on every child**; the single local full suite is the FINALIZER's |
| **E ROADMAP SYNC** | §15.1 row, §14 ledger rows, folder README, this parent | **02c (finalizer)**, before Step 03 opens |

### 9.1 Checkpoint-D cadence — Evidence Economy is binding

Revision 1 required a local full unit suite at every child's final head.
That was an Evidence-Economy violation: three ~10-minute 8k-test runs
buying compatibility evidence that **CI already provides on every PR**.
Corrected:

```text
per child:
  targeted tests
    -> affected package tests
    -> focused integration / mutation
    -> exact-head CI                      <- broad compatibility, every child

assembled final Step-02 executable head (02c):
  ONE local full unit suite
    -> Gate 2
    -> static (ruff / format)
    -> exact-head CI
```

**Escape hatch, per child, justified in writing**: a child MAY run a
local full suite if its own detailed design argues its blast radius
makes narrower evidence insufficient — 02a, which migrates ~13
production modules, is the plausible case. The parent does not mandate
it; the child justifies it or does without.

Blocking rule unchanged: no child proceeds to its contrast rungs before
its parity checkpoint passes, and **later evidence never excuses a
failed earlier invariant**.

## 10. Gate ladder — instantiated from the standard's assignment table

`docs/gates/gate_testing_standard.md` defines the tiers by **real vs
pseudo LLM**: Gate 1 = real LLM + pseudo training; Gate 2 = real LLM +
real training. Its "Gate assignment by commit type" table is the
authority, and it is quoted rather than reasoned around.

> **Correction to this design's first draft (2026-08-13).** The draft
> proposed a reduced "pseudo LLM + REAL training" tier *instead of*
> Gate 2, arguing it targeted Step 02's failure class more cheaply.
> That was wrong on the standard's own terms: `--is_pseudo_llm` /
> `--is_pseudo_training` are the **dual-mode convenience mechanism**,
> not a gate tier, and inventing a third tier would let any future step
> argue its way out of Gate 2. The assignment table settles Step 02
> directly. The pseudo-LLM production-entry run is retained — but as the
> **Checkpoint C instantiation** it actually is (§10.3), which is
> precisely how Step 01 used it (OD-S1-4).

### 10.1 Gate 1 — **NOT REQUIRED** at Step level

Table rows that match Step 02's commit types:

| Commit type (from the table) | Typical gate | Applies to Step 02? |
|---|---|---|
| Config files, YAML, schema-only | **Unit only** | yes — the Dataset Profile declaration |
| New loader/renderer (pure Python) | **Unit only** | yes — profile resolution, selection, group resolution |
| New LLM-facing system prompt | Gate 1 | **no** — Step 02 changes no prompt |
| Prompt placeholder substitution | Unit only + optional Gate 1 | **no** |
| New agent node or workflow wiring | Gate 1 | **no** — no new node, no new workflow edge |

Step 02 is squarely the first two rows. Its compatibility contract
additionally *requires* rendered prompt bytes to be unchanged under
TIDMAD, and that is already golden-pinned by Step 00 and Step 01 — a
byte-equality assertion answers Gate 1's question more precisely and at
zero cost.

**Flip condition (per-child stop condition, not a global waiver):** any
child whose implementation changes rendered prompt bytes or a
proposal-affecting schema takes Gate 1 per the table's "New LLM-facing
system prompt" row.

### 10.2 Gate 2 — **REQUIRED** at the Step-02 checkpoint

The table's `Checkpoint (end of feature) → Gate 2` row applies: Step 02
is a feature with an end-of-feature checkpoint. Gate 2 is **not waived
and not substituted**.

It also earns its place on its own merits — its failure class is real
here and reachable nowhere cheaper: Step 02 changes how production
resolves files, loads tensors and selects samples. Unit tests use
synthetic HDF5 fixtures, so a wrong resolved profile fails only when
real files are opened. Gate 2 runs real training on real files, so it
exercises exactly that path.

| Field | Value |
|---|---|
| Unique failure class over Checkpoint C | Checkpoint C proves the profile REACHES production with a stub bridge; Gate 2 proves the real multi-round training/inference/scoring loop still consumes it correctly on real files across iterations — wrong filename resolving to the WRONG file, truncated/over-read tensors from a wrong segment count, shifted class indices from a wrong encoding declaration, or a SampleSet that scores a different sample population |
| Boundary | production entry → real workflow → real LLM → real training → real inference → real scoring |
| Real LLM / real training | **YES / YES** — per the standard's definition of the tier |
| Shape | the standard's **trial-only smoke**: `--no-force_formal_round` (Step 02 touches no formal-admission logic), partial scope with matching `--health_gate_files`, cold start (no `--seed_paths`), `--trial_portion 0.02`, `--trial_time_budget_minutes 5`, `--formal_time_budget_minutes` as a safety net, and **`--llm_config llm_configs/openai_tiered_pro.json`** under standing production-validation policy (never `openai_tiered_v1`, never a substituted config) |
| Budget | ~30-45 min, ~$1-1.5 (Step-01 precedent measured 33m35s) |
| PASS | the standard's HealthGate-framework criteria verbatim (chain exits 0; every round records a `gate_action`; every `denoising_score` finite or accounted; no phantom `5.5762667`; ≥1 HealthGate evaluation) **plus two Step-02 criteria**: (1) the resolved profile recorded in the run artifacts deep-equals TIDMAD; (2) **for Gate 2's ACTUAL inputs** — its profile, scope, seed, portion and strategy — the production-generated SampleSet equals the deterministic reference resolution computed for that same input tuple. A pinned Step-00 digest is compared ONLY when its input tuple matches exactly. **Never compare a hash across different arguments**: Gate 2 runs a partial scope at `trial_portion=0.02`, which need not correspond to any of the five existing digests (captured at `seed=42, portion=0.05`) |
| NOT pass/fail | denoising quality, beating a baseline, any score threshold. **No new scientific-quality threshold is introduced by Step 02** |
| FAIL/STOP | any file resolved by a different name; any SampleSet digest drift; any encoding shift; chain incompletion traceable to profile resolution |
| Artifacts | chain log, per-round records, resolved-profile artifact, exact executable HEAD |
| Position | after Checkpoint C, on the assembled Step-02 head — ONE chain, once |

**Owned by the FINALIZER, 02c (§6.2).** Running it three times would
triple cost for the same failure class. Children 02a and 02b close their
own Checkpoints A/B/C/D; 02c closes its own AND runs the one Step-level
Gate 2 on the assembled head. Ownership is named, never "whoever merges
last".

### 10.3 Checkpoint C instantiation — pseudo-LLM production-entry run

This is where the pseudo-LLM run belongs — as live-integration evidence,
not as a gate.

Source-grounded mechanics: `run_one_iteration.py` swaps the bridge and
the sandbox through two INDEPENDENT flags (`--is_pseudo_llm` →
`StubLLMBridge`; `--is_pseudo_training` → `StubSandbox`). Which
combination Checkpoint C uses is an implementation-time choice for the
owning child, with one design-level constraint: **the profile must be
observed being consumed by the real production data path**, so at least
the data-reading half must be real.

| Field | Value |
|---|---|
| Cost class | no real LLM, no API cost |
| Question | does the RESOLVED profile reach and get consumed by the production training/inference/scoring path — as opposed to a profile that only tests construct? |
| PASS | the run completes and the resolved profile recorded in the run artifacts deep-equals TIDMAD, with the loaded tensors and produced SampleSet matching the pinned identities |
| Relationship to Gate 2 | strictly weaker and strictly cheaper. Checkpoint C is the blocking prerequisite; Gate 2 is the real-LLM, multi-round confirmation. Neither replaces the other |

## 11. Evidence economy

Binding: test by RISK and UNIQUE EVIDENCE VALUE, not by code surface.

Per child: directly affected tests → affected package
(`tests/unit/execute_tools/`, plus the tuner/health package for 02b/02c)
→ focused integration / mutation → **exact-head CI**. CI is the broad
compatibility gate on every PR, so compatibility evidence is never lost.

At the assembled final head, owned by the finalizer 02c: **ONE** local
full unit suite → Gate 2 → static → exact-head CI.

The >8k suite is a terminal compatibility gate, never an inner-loop
default and never a per-child ritual (§9.1). A child may add one only
by justifying its blast radius in its own design.

### 11.1 New test families — each with its unique failure class

| Family | Owner | Unique failure class |
|---|---|---|
| Validation-name production pin | 02a | the scorer/inference inlined literal and the pattern diverge — today nothing compares them |
| Encoding-declaration tensor pin | 02a | a changed offset/dtype declaration silently shifts class indices; no current test loads through the declaration |
| Injection reachability | 02a | a consumer keeps importing the module constant while a profile argument sits unused — the "beautiful profile consumed only by tests" failure |
| SampleSet JSON round-trip boundary | 02b | key-coercion divergence between producer and consumer; today every consumer re-ints differently with no shared pin |
| Group declaration equivalence | 02c | a declared map that does not reproduce `[0,10,19]` / `[3,10,17]` / `range(20)` |
| Contrast rungs A1 / A2 / B / D | 02a | the abstraction does not actually vary with the declaration — topology (count, family), geometry (`psd_segment_length` ≠ 10M) and channel identity |
| Contrast rung C | 02c | anchors/peeks read a literal rather than the declared group map |
| Topology contrast through selection | 02b | selection keeps TIDMAD's 20×200 shape under a contrast topology |

### 11.2 Retirement candidates — recorded, NOT pre-approved

Only within the directly affected surface, and only if implementation
naturally reaches them:

- the three `_DEFAULT_FILE_RANGE` health-check fallbacks become one
  declaration — their per-module tests may collapse to one concept test
  IF each original input class is preserved;
- `test_dataset_config.py`'s `valid_segmentation_sizes` cases overlap
  Step-00's exact-list pin; the *窗口* (lo/hi) cases are NOT duplicates
  and stay.

Default is KEEP. No repository-wide test cleanup. Any retirement must
state which non-equivalent input classes the originals covered and how
the replacement preserves each.

---

## 12. Cross-module convergence ledger (§14) — DO NOT MERGE YET

| Concept | Step-02 meaning | Other module meaning | Match? | Disposition |
|---|---|---|---|---|
| **SampleSet type** | produced by selection | consumed by ~15 families (engines, scoring, estimators, resolvers, tuner) with independent key-coercion | lifecycle matches; **serialization does not** | 02b pins the round-trip at ONE boundary. Ownership merge still needs ≥2 completed designs — **DO NOT MERGE** |
| **Systematic groups** | declared bands | health peeks, anchors, scripts band tables, campaign validation | semantics match; **no shared source of truth** | 02c declares and consumes. Whether §8 HealthGates should own its own group view is Step-08's call — **DO NOT MERGE** |
| **Sample-shape legality** | dataset-side rule | proposer validator + tuner restatement + prompt rendering | match | one authority already exists; 02a de-duplicates. **No merge needed** — this row can close |
| **Value encoding** | dataset declaration (dtype/offset) | §5 derives model input semantics; §7c/§7e/§8 consume | declaration vs derivation — **complementary, not duplicate** | 02a declares; Step 03 derives. **DO NOT MERGE** |
| **data_shape_class** | geometry Step 02 owns | runtime-control interchangeability key | Step 02 supplies inputs; runtime-control owns the key format | **DO NOT MERGE** — 02a must not change the string |
| **Deliverable Contract** | Step 02 owns INDEXING only | naming/layout/dtype/attrs re-inlined ≥6 sites | **explicitly distinct** (§3.1) | stays a §14 ledger row with owner TBD. Step 02 must NOT absorb it |

---

## 13. Corrections this design proposes to the overall roadmap

Recorded here; ordinary Step-02 status and correction sync waits until
**Checkpoint E**, owned by the finalizer 02c.

**Explicit exception, operator-approved 2026-08-13.** Two CROSS-CUTTING
governance rules were added to the overall roadmap at DESIGN time rather
than at Checkpoint E — §17.0's gate-authority rule and its companion
source-grounded-ownership rule. They are not Step-02 status; they govern
every future step's design, so deferring them to this Step's closeout
would let the next design repeat the mistake that produced them. The
operator approved both amendments explicitly. Everything else in this
section still waits for Checkpoint E.

1. **§4.7's "a NEW pin, none exists"** is stale — Step 00 landed the
   profile pin. Checkpoint 0 is largely MET.
2. **§15.1's Checkpoint-C consumer set** ("training engine + sample-set
   builder") is insufficient: inference and the scoring path also read
   the profile, and scoring is where a wrong resolution fails silently.
3. **§4.2's `validation_file_pattern` dead-seam** remains true in
   production and is 02a's to close.

---

## 13a. What this design does NOT freeze (implementation-time)

Per the roadmap's governance discipline: the Step design freezes
observable behaviour, ownership, boundaries, compatibility surfaces,
child DAG, contrast axes, checkpoints, gates and stop conditions. It
deliberately does NOT freeze, and a child design must decide these from
source at implementation time:

- the profile object's exact type, field names and nesting (whether the
  resolved profile extends `DatasetConfig`, wraps it, or is a new type);
- exact YAML layout and whether the dataset profile lives in
  `configs/task_config.yaml` or its own module-owned file;
- the injection mechanism (constructor argument vs resolver call vs
  context object) and helper decomposition;
- the group-map representation (named lists, ranges, a band table);
- the encoding declaration's shape;
- exact test-file placement, assertion form and fixture construction;
- exact command syntax for Checkpoint C and Gate 2 — assembled from
  CURRENT source immediately before each run;
- incidental line numbers cited anywhere in this document.

## 13b. Adversarial design review (2026-08-13)

Run against this document's first draft. Five confirmed findings; each
correction is folded in above.

| # | Attack | Finding | Correction |
|---|---|---|---|
| **A1** | Did we claim Deliverable Contract semantics by accident? | **YES — a sharp boundary sits INSIDE one file.** `scoring_utils.py` inlines the RAW VALIDATION filename (:389, :444) *and* the scorer also handles DENOISED deliverable files. The raw name is Step-02-owned input topology; the denoised name is the Deliverable Contract's | 02a routes ONLY the raw-validation half through the profile and must leave every denoised/deliverable name untouched. Any diff touching a denoised filename template is a scope leak and a STOP |
| **A2** | Conflated dataset geometry with `segmentation_size`? | NO — §1.3 keeps `psd_segment_length` (dataset) separate from `segmentation_size` (proposer-owned), with only the legality rule dataset-side | none |
| **A4 / A12** | A config field with no live consumer? | **YES — the encoding declaration is at risk.** If 02a declares dtype/offset but the engines keep their ~8 inline `+128` sites, the declaration is a dead seam — the exact §0 rule 8 failure | 02a's Checkpoint C is not closable until **at least one production load path reads the encoding declaration**. Promoted from "a test family" to a checkpoint condition |
| **A5** | A TIDMAD default moved into a "generic default"? | **YES — latent.** `DatasetConfig` today carries TIDMAD filename patterns as CLASS defaults (`training_file_pattern`, `validation_file_pattern`). Carrying those into a generic profile makes TIDMAD the framework's default rather than a bound task's declaration | 02a must decide explicitly: keep them as a regime-A compatibility adapter (documented as such) or require declaration. Recorded as a child-level decision, NOT silently inherited |
| **A9** | Is any contrast fixture multi-axis? | **PARTIALLY** — §4.8-A as the roadmap words it ("3 files, single family") varies file COUNT and family CARDINALITY together | Accepted as ONE topology axis, matching the roadmap, but the two sub-axes are now named so implementation cannot silently add a third (e.g. also changing the name pattern's format spec) |
| **A17** | Froze code/schema detail that should wait? | **YES in the first draft** — it implied a profile shape | §13a added, listing what stays implementation-time |
| **A-NEW** | Did we DEFER a rung on an unaudited assumption? | **YES — the most serious finding.** The first draft deferred 4.8-D to Steps 03/06 by reasoning about what "truth availability" means, without opening the loaders. The source shows the truth channel is addressed by a hardcoded in-file path at ~15 production sites — a dataset fact, not a model fact | 4.8-D re-selected in its channel-identity form; channel identity added to 02a's ownership; §1.6 records the correction. **Process consequence: every ownership and every rung decision in this document must cite source, not reasoning about a concept name** |
| A3, A6, A7, A8, A10, A11, A13-A16, A18 | portions/seed leakage · refactor-only child · unlanded-sibling dependency · Stage A/B bundling · hash invalidation · launcher claims · gate necessity · gate cost · duplicate tests · FX routing | no confirmed finding | §3 excludes runtime state; §6.3 rejects the refactor-only candidates; the DAG is acyclic with 02b ∥ 02c; §7 states the staging rule; `data_shape_class` and the five digests are pinned; Steps 10/11 residue explicitly deferred; §10 is table-grounded; Gate 2 runs once at Step level; §11.2 defaults to KEEP; FX-3/FX-4 routed to Step 03 + D13 |

## 13c. Adversarial RE-review (revision 2, narrow — 7 questions)

Scoped exactly as the operator directed. No new repository audit.

| # | Question | Verdict |
|---|---|---|
| 1 | Is 02a still a coherent single PR after gaining rung B? | **YES.** A1/A2, B and D all exercise the SAME injection seam through the SAME migrated consumers; B adds a fixture, not a second migration. The §6.2 note now states why encoding and channel identity are internal milestones, and a **re-opening clause** commits the child to STOP and re-open the decomposition if its own audit shows one cannot be reviewed or rolled back coherently inside the PR |
| 2 | Is each contrast truly one-axis? | **YES, and this improved.** Revision 1's 4.8-A conflated file count with family cardinality; it is now A1 (count) and A2 (family), with A2 permitted to build on A1's proven baseline. B, C and D were already single-axis. Atomicity is stated as binding, with the explicit prohibition on touching geometry/encoding/channel/groups inside A1 or A2 |
| 3 | Does any final-effect claim lack a contrast proof? | **NO — this was the revision's most important fix.** §2 claims topology, geometry, encoding, channel identity and groups all resolve from the profile. Mapping: topology → A1/A2; geometry → **B (was missing)**; groups → C; channel identity → D. Encoding remains proved by a *parity* pin plus the Checkpoint-C reachability condition rather than a contrast rung — recorded as the one deliberate asymmetry, justified because a wrong encoding declaration is caught byte-exactly by the tensor pin, and an encoding contrast would require a fixture dataset in a different dtype, which is Step-03 territory |
| 4 | Does Gate 2 have unique evidence over Checkpoint C? | **YES.** Checkpoint C proves the profile REACHES production with a stub bridge. Gate 2 proves the real multi-round training → inference → scoring loop consumes it correctly on real files. The §10.2 table names four failure modes reachable only there |
| 5 | Is aggregate Gate/E ownership unambiguous? | **YES, now.** Revision 1 left it to "whichever child merges last". 02c is named FINALIZER, governance order is frozen `02a → 02b → 02c`, and its duties are enumerated in both §6.2 and its child design |
| 6 | Does the test cadence violate Evidence Economy? | **It did; fixed.** Revision 1 required a local full suite per child — three ~10-minute runs duplicating what CI already does per PR. §9.1 now runs targeted → package → integration/mutation → exact-head CI per child, ONE local full suite at the assembled head, with a written-justification escape hatch |
| 7 | Did Step-03 / Deliverable / Step-10/11 ownership leak back in? | **NO.** Deliverable: §1.7 A1's raw-vs-denoised boundary inside `scoring_utils.py` stands, and 02a lists a denoised filename in the diff as a STOP. Step 03: FX-3/FX-4 routed out; truth ABSENCE explicitly excluded while channel IDENTITY is kept; encoding DERIVATION stays Step 03's. Steps 10/11: `scripts/` is now classified by measured reachability (§3.1) rather than assigned wholesale — which moved ONE script INTO 02a on evidence, and that is a correction, not a leak |

**Residual risk accepted and named**: the encoding declaration has a
parity pin and a reachability condition but no contrast rung (row 3
above). If the operator wants symmetry, the rung would be an
encoding-only fixture in a different dtype — but that fixture's
consumer semantics belong to Step 03, so it is recorded as a Step-03
candidate rather than added here.

## 14. Operator decisions — RECORDED (2026-08-13)

| # | Question | Decision |
|---|---|---|
| **Q1** | Three-child split? | **ACCEPTED, with 02c designated FINALIZER.** No fourth behavioural child. 02a stays one PR with internal blocking milestones |
| **Q2** | Gate ladder? | **ACCEPTED.** Gate 1 NOT REQUIRED by default (flip condition: any child changing LLM-facing prompt bytes or proposal-affecting schema takes Gate 1 per the standard). Gate 2 REQUIRED ONCE at Step level, `--llm_config llm_configs/openai_tiered_pro.json`. Checkpoint C is pseudo-LLM production-entry evidence, never presented as a Gate. No invented intermediate tier |
| **Q3** | Contrast rungs? | **REVISED.** Required set is **A1 / A2 (topology, atomic) + B (geometry) + C (groups) + D (channel identity)**. 4.8-B's deferral was a logical gap and is withdrawn (§8) |
| **Q4** | FX-3 / FX-4 → Step 03? | **ACCEPTED.** Step 02 keeps only the interface obligation: its geometry/encoding declaration must be resolvable and inspectable so Step 03 can cross-validate a preset against it |
| **Q5** | `scripts/` ownership? | **DECIDED BY REACHABILITY** (§3.1). The two `score_tidmad_official_*` scripts are legacy/peripheral — OUT. `compute_raw_baseline.py` is a supported auxiliary producer of a production-consumed artifact — IN scope for 02a |

**No operator question remains open.** The design is ready to freeze.

## 15. Definition of Done (Step level)

- [ ] 02a, 02b, 02c merged in the frozen governance order `02a → 02b → 02c`, with 02c closing the Step as FINALIZER
- [ ] §2 final effect observably true
- [ ] Checkpoints 0/A/B/C/D/E closed at Step level
- [ ] Rungs **A1, A2, B, C, D** green, each varying exactly one axis
- [ ] Checkpoint C PASS, then **Gate 2 PASS** (real LLM + real training,
      trial-only smoke) — once, on the assembled head
- [ ] Every §5 criterion holds byte-identically under TIDMAD
- [ ] No new module-level dataset constant; no consumer restating a
      legality rule or branching on a literal file list
- [ ] §14 rows updated with evidence; nothing merged prematurely
- [ ] FX-3/FX-4 restated in the Step-03 design before Step 02 closes
- [ ] Roadmap §15.1, §14, folder README and this parent synchronized

**NOT MERGED.** A child's implementation is authorized when **that
child's own** design is frozen and it receives its own Implementation
Working Rules contract — **never** by this parent being frozen, which it
deliberately is not (see Status). Current state: **02a AUTHORIZED and in
progress**; 02b and 02c unauthorized.
