# D14 — Executable data path + the two contrast tracks at executable maturity — acceptance / decomposition design

## 0. Status and provenance

**FROZEN — rev 3, 2026-08-18.** Operator review verdict: APPROVED WITH
REQUIRED AMENDMENTS (no second review required). Rev 3 applies all of them —
Amendment 1 `model_input` / `supervision_target` semantics (no new
TargetContract; the synthetic task's target representation must differ from
its output representation), Amendment 2 output-codec ownership with the
`read_evaluation_payload` rename, Amendment 3 fail-closed binding (TIDMAD is a
regime-A compatibility default only, with a required negative test), the
D14-1 no-dual-path acceptance tightening (AST census: zero direct
`TIDMADEpochDataset` construction / codec dependency outside the registered
implementation), the full-surface synthetic proof, and the scope-opacity
residual as issue #225 — and records the post-amendment adversarial pass
(§6.1): all five operator threats closed without widening the architecture.

Child designs and implementation now proceed AUTONOMOUSLY (adversarial
self-review per child; routine decisions unescalated), stopping only on the §7
conditions or at each PR-ready operator review. Rev-2 history: §3.1/§3.2 added
for the parent review. Rev-1: initial draft.

**Recorded amendment (Step 12 Q-12-2 = A, operator 2026-08-22).** The
four-method `TaskDataPath` contract remains FROZEN and unmodified. Step 12
adds an OPTIONAL sibling `TaskScopeCapability` protocol beside it
(task-owned scope construction + serialize/deserialize codec; scope
transport = workspace artifact + digest), owned by
`step_12_external_extensibility_graduation.md` §5 and implemented by its
PR-12b. This document's "four methods" wording is therefore read as "four
required methods, plus an optional sibling scope capability an
implementation MAY declare"; the scope-opacity principle (issue #225) is
unchanged — the framework still never inspects a scope's internals.

Drafted 2026-08-18 against `master` @ `7f650971`, from a fresh source audit of:
`execute_tools/train_engine_sandbox.py::TIDMADEpochDataset` (:295-449, plus its
two construction sites :910 and :1448), `execute_tools/inference_single.py`
(deliverable production via `derive_tidmad_deliverable_spec` +
`create_abra_file`), `execute_tools/array2h5.py`, `execute_tools/dataset_config.py`
(`DatasetProfile` and the resolution ContextVar), `execute_tools/deliverable_spec.py`,
`agent/schemas/model_io_contract.py`, `ml_models/models_sandbox.py::MODEL_REGISTRY`
(+ `construct_registered_model`, 07c), `examples/{oxford_iiit_pet,davis_future_prediction}/`
(PR0 packs: STATUS / PROVENANCE / manifests / declared contracts / L1 fixtures),
and `tools/example_packs/` (fetch-free manifest tooling).

Roadmap authority (the ONE status authority, §15.1): D14 is the **dedicated
executable-data-path milestone between Step 07 and Step 08** — §22.11a
(timeline + content), §22.9a (the two FROZEN task specifications), §22.23.5
(execution-level manifests), §20.5 (the ownership gap this milestone closes),
§20.6 (preservation constraints), §22.11a cumulative-corpus RULE and
no-ad-hoc-composed-tasks RULE, §21.3 item 3 / §16 ("running the two contrast
tasks through a TIDMAD-shaped loader would not be a generic end-to-end run").

## 1. Final observable milestone effect

After D14, this sentence is true and demonstrated by executed evidence, not
declarations:

> **TIDMAD is an executable scientific denoising task; Oxford-IIIT Pet is an
> executable RGB classification task; DAVIS is an executable spatiotemporal
> regression task — on the same generic framework, with no task-identity
> branch in generic core.**

Concretely:

1. **A task-owned executable reader seam exists.** The framework asks a bound
   task for "the training/validation dataset for this SampleSet" and "write
   this model output as the task's deliverable"; TIDMAD's answers are the
   EXISTING `TIDMADEpochDataset` / `create_abra_file` behaviour, byte-for-byte.
2. **Track B executes**: real Pets JPEGs → decode → aspect-preserving resize
   (shorter side 160) → center crop 144×144 → float32 `[3,144,144]` /255 →
   reference CNN → real training with R2/R3 CE curves → inference → a
   classification deliverable → **accuracy (higher)** through the Step-06
   metric handle. L2, then L3 (§22.11a).
3. **Track C executes**: real DAVIS frames → deterministic windows
   (8 context → 4 future, stride 1) → `[3,8,128,224]` → reference predictor →
   real training with R2/R3 MAE curves → inference → a future-frame
   deliverable → **global MSE (lower)**. Clip identities
   `(sequence_name, start_frame)` are materialized HERE (deferred to D14 in
   full by the PR0 review).
4. **EXECUTION-level manifests** (§22.23.5) are committed and SHA-256 pinned:
   decode/interpolation rules, transform parameters, window materialization,
   and input-tensor hashes for pinned probe items. Raw data is NEVER committed.
5. **The already-landed Step-07 L1 fixtures are UPGRADED, not replaced**
   (cumulative-corpus RULE): real-component variants join the atomic fixtures.
6. **No production dependency on `examples/`** — packs remain
   projection-not-authority (§22.23); production binds through configuration
   and registered plugins.

### 1.1 The success criterion, negatively stated (operator, 2026-08-18)

D14 is NOT "configs exist, schemas parse, fixtures pass". Explicitly refused
outcomes: task-identity leakage (`if tidmad / if pets / if davis` in generic
core); a runtime production import of `examples/`; a TIDMAD-shaped abstraction
wearing a generic name; fake execution (fixtures posing as runs); fake metrics
(numbers not computed by the Step-06 handle from a real deliverable); missing
R3 validation; a missing primary golden metric; launcher/runtime residue.
Every one of these is an executable check in §6, not a review vibe.

## 2. Current source census (audited at `7f650971`)

### 2.1 The declared half — complete, and the binding constraint

`DatasetProfile` (`dataset_config.py`) owns topology/geometry/legality —
**but its vocabulary is 1-D-segment, two-channel HDF5** (`DatasetConfig`,
`ChannelIdentity`, `ValueEncoding`). Both contrast packs' STATUS files record
`DatasetProfile: NOT representable` and `DeliverableSpec: NOT representable`.
This is the load-bearing fact of the whole design: **D14 must NOT force Pets
and DAVIS into `DatasetProfile`** — that would be the TIDMAD-shaped
abstraction §21.3 forbids. The profile remains TIDMAD's (and any future
segmented-HDF5 task's) declarative authority; the new seam is keyed on
capability, not on reshaping every task into the profile's vocabulary.
Preservation constraint §20.6 supports this: existing config families stay
distinct and recognizable; additions are additive with compatibility
defaults; **no new top-level configuration hierarchy** — the task binding
rides the existing task-config/plugin seams.

### 2.2 The executable half — TIDMAD by shape (what §20.5 recorded, verified)

| site | TIDMAD shape assumption |
|---|---|
| `train_engine_sandbox.py::TIDMADEpochDataset` :295-449 | HDF5 `timeseries/<ch>/timeseries`; `{file_index: [segment_idx]}` SampleSet; `psd_len // seg_size` decomposition; int-offset encode; two 1-D channels |
| its construction sites :910 (validation family) and :1448 (training) | direct class construction — **no seam**; `file_family` selects abra_training vs abra_validation |
| `inference_single.py` :654-687, :854-863 | per-file lazy slice → `reshape(-1, 1, input_size)`; per-file loop over validation files |
| `array2h5.py::create_abra_file` | two `timeseries` groups; int8 storage; `abra_validation_denoised_XXXX` naming (via `DeliverableSpec`, Step 05c) |

Every literal is profile-driven **by value** (Steps 02/05c) but the *shape* of
the pipeline — files → segments → 1-D windows → per-file HDF5 deliverable —
is the task.

### 2.3 Already generic (bind, do not rebuild)

`ModelIOContract` is rank-agnostic and already DECLARED for both packs
(`[B,3,144,144]→[B,37]` categorical/37; `[B,3,8,128,224]→[B,3,4,128,224]`
continuous). `MetricSpec` + `MetricOrder` + the evaluation handle are
direction-generic (07b), with accuracy/macro-F1 and MSE/PSNR declared in the
packs. `TrainingHistory`/`TrainingDiagnosis` are task-generic (07a) — the L1
fixtures already carry `objective_kind="cross_entropy"` / `"mae"` through the
SAME boundary TIDMAD uses (rung B-07a-1). `MODEL_REGISTRY` +
`construct_registered_model` (07c) constructs by registered type with no name
branches. The runtime-control measurement path is profile/contract-derived
(07c). **D14's job is to give these already-generic consumers real executable
producers for two more tasks.**

### 2.4 The packs (PR0) — identity landed, execution absent

Pets: identity manifests 2,946/734/3,669 committed + SHA-pinned; contracts
declared; `log_loss` intentionally blocked on D16 (documented, test-pinned).
DAVIS: 60/15/15 sequence-identity manifests; **clip identity explicitly
deferred to D14**; **licence terms of the TrainVal-480p artifact must be
verified and pinned by D14** before executable provenance is complete.
`tools/example_packs/` is manifest/projection tooling only — **no fetcher
exists**; raw-data acquisition tooling is new D14 surface. Governance guards
currently enforce "no `.py` under `examples/` until D14" — D14 is the named
relaxation owner, and the relaxation is scoped by this design (§5.4).

## 3. The abstraction (WHAT is frozen here; each PR's design freezes HOW)

One new seam, deliberately small:

```text
TaskDataPath (name final at PR-1 design)  — the EXECUTABLE data-path contract
    training_dataset(scope, …)   -> torch Dataset yielding task-owned samples
                                    (model_input, supervision_target)
    validation_dataset(scope, …) -> same, over the validation identity scope
    write_deliverable(outputs, …)-> the task's persisted deliverable, at the
                                    path/layout the task's deliverable authority
                                    declares
    read_evaluation_payload(…)   -> the DECODED task payload handed to the
                                    Step-06 evaluation authority (codec only,
                                    never scoring)
```

**Sample semantics (Amendment 1, operator 2026-08-18 — FROZEN).**
`model_input` must satisfy the bound `ModelIOContract` **input** boundary.
`supervision_target` is consumed by the already-bound training objective /
validation computation and is **NOT required to share the model output's
shape, dtype, rank or representation** — Pets is the canonical case: model
output `[37]` logits, supervision target a scalar class index. No new
`TargetContract` is introduced; the existing objective binding consumes the
target, and a broader contract appears only if source later proves an
existing frozen contract cannot (minimal-correction rule).

**Output-codec ownership (Amendment 2, operator 2026-08-18 — FROZEN).**

```text
TaskDataPath MAY own      model/task values <-> task-native deliverable bytes
                          <-> decoded evaluation payload        (a CODEC)
TaskDataPath MUST NOT own metric selection · metric direction · scoreability ·
                          scientific thresholds · metric aggregation ·
                          the training objective · scientific interpretation
```

The output path is fixed:
`production output → TaskDataPath codec → decoded payload → Step-06
evaluation/metric authority → score`. The seam is never a bypass around
Step-06 ownership — `read_deliverable_for_metric` was renamed to
`read_evaluation_payload` precisely so the name cannot imply scoring.

### 3.1 The contract, precisely (review section B)

| dimension | decision |
|---|---|
| **semantic owner** | the executable half of "storage → sample → input tensor" and "model output → persisted deliverable → metric input" — exactly the §20.5 gap. It owns HOW bytes become tensors and tensors become the deliverable. It does NOT own what the task means (task config), what shapes are legal (`ModelIOContract`), what the deliverable is named/laid out (the task's deliverable authority), or how it is scored (`MetricSpec` + the Step-06 handle) |
| **lifecycle** | resolved ONCE at run scope and bound the way `DatasetProfile` already is — the `bind_dataset_profile` ContextVar pattern (`dataset_config.py:591-672`) and the tuner's `RunBindings` run-scoped-authority rule. Never re-resolved per phase; subprocesses receive it by explicit transport (the 07c `--dataset_profile_json` precedent), never by ambient re-lookup |
| **registry binding** | a string id → implementation registry, registered exactly as `MODEL_REGISTRY` entries are; the id is ONE additive field on existing task configuration (§20.6: no new hierarchy). **Regime-A absence of a binding resolves to TIDMAD as a COMPATIBILITY default only** — preserving frozen existing behaviour for current campaigns. For an explicitly bound or future task, a missing capability, unknown id, or invalid implementation **FAILS CLOSED** (Amendment 3): never `unknown → TIDMAD` |
| **capability key** | the id names an IMPLEMENTATION, not a task family, and resolution is by lookup only. The framework never inspects the id's spelling — asserting that is part of the leakage guardrail |
| **inputs** | a task-opaque scope (TIDMAD: `{file:[segments]}`; Pets: manifest-row selection; DAVIS: clip-identity selection), the bound `ModelIOContract`, the run's data directory, determinism seed(s), and the task's own declared parameters (from its config/manifests) |
| **outputs** | `training_dataset` / `validation_dataset`: a torch `Dataset` yielding `(model_input, supervision_target)` — the input satisfies the bound contract's INPUT boundary; the target is objective-owned and free of model-output shape (Amendment 1). `write_deliverable`: the persisted artifact at the task's declared layout. `read_evaluation_payload`: the decoded payload for the Step-06 authority — codec only (Amendment 2). Nothing else — no metrics, no health verdicts, no diagnosis |
| **frozen vs mutable** | FROZEN by this parent: the four-method surface, registry binding, run-scoped lifecycle, scope opacity, the §1.1 prohibitions. MUTABLE at child designs: method signatures' exact types, the registry's module home, the TIDMAD relocation order |
| **who may depend on it** | `train_engine_sandbox`, `inference_single`, and the scoring read path — the three §2.2 sites. NOT prompts, NOT the planner/reflector, NOT records (records keep their existing fields; the data path is not evidence), NOT runtime-control (07c already binds through profile/contract and stays as-is) |
| **what it must NOT know** | task names; `examples/`; file-naming conventions of any single task (TIDMAD's live in the TIDMAD implementation, behind the seam); tensor rank beyond what the bound contract declares; metric/objective semantics; anything about which check or metric will consume the deliverable |

### 3.2 Why this is the minimal abstraction (review section C)

| alternative | verdict | reason |
|---|---|---|
| **1. Extend `DatasetProfile`** | REJECTED | its vocabulary (`DatasetConfig`/`ChannelIdentity`/`ValueEncoding`) is 1-D-segment two-channel HDF5; both packs' STATUS rows record it NOT representable for their tasks. Extending it means either (a) unioning three tasks' vocabularies into one schema — the TIDMAD-shaped-abstraction trap §21.3 names, growing per task forever — or (b) making its fields optional-per-task, which destroys the profile's current strength: every field it has is load-bearing for the task that has it. The profile also carries frozen enforcement (DataScope layers, run-invariants pinning) whose semantics are TIDMAD-scope-specific; widening the schema would silently widen those |
| **2. Extend `DeliverableSpec`** | REJECTED | same shape of failure on the output side (per-file HDF5 naming/storage vocabulary), and it addresses only the writer — the dataset/reader half of the §20.5 gap would still need an owner |
| **3. `TaskDataPath` (this design)** | ACCEPTED | one narrow executable contract; existing declarative authorities stay untouched and byte-parity is provable because TIDMAD's code moves *behind* it rather than through a schema rewrite; a new task binds by registration + one config field, which is the operator's stated success criterion verbatim |
| **4. Task-specific execution branches** | REJECTED | `if tidmad / if pets / if davis` in generic core is the explicitly refused outcome (§1.1); it also fails the immutability policy — every future task edits core |

Minimality check: the seam adds **no** new declarative concept. Every input it
consumes exists today (contract, scope, config); every output it produces is
consumed by an existing frozen interface (trainer loop, deliverable authority,
metric handle). It is a *relocation boundary* for TIDMAD and a *binding point*
for everything else.

Binding rules (frozen):

* **Registry-bound, never name-branched.** Implementations register exactly as
  model plugins do (the `MODEL_REGISTRY` precedent); the bound task's config
  names its data-path id. Generic core resolves by id — a new task binds by
  registration + configuration, with zero core edits (§1.1's success
  criterion, made structural).
* **Fail-closed binding (Amendment 3, FROZEN).** The TIDMAD default exists
  ONLY as the regime-A compatibility path for the absence of any explicit
  binding — it preserves frozen behaviour, it is not a generic fallback. An
  explicitly bound task with a missing/unknown/invalid data-path id fails
  closed with a diagnostic naming the registry and the id. D14-1 carries a
  deterministic negative test: the synthetic non-TIDMAD task with a broken
  binding FAILS rather than silently training on TIDMAD's path.
* **TIDMAD's implementation IS the current code**, relocated behind the seam
  with delegation, not rewritten: `TIDMADEpochDataset` and the
  `create_abra_file` path keep their bytes; the two construction sites (:910,
  :1448) and the inference writer become seam calls. Regime A (no explicit
  binding) resolves to the TIDMAD path — current campaigns are untouched.
* **Scope vocabulary is task-owned.** TIDMAD's `{file: [segments]}` SampleSet
  stays TIDMAD's; Pets scopes are manifest-row selections; DAVIS scopes are
  clip-identity selections. The framework passes scopes opaquely and enforces
  only identity/disjointness through each task's manifest authority. (The
  DataScope enforcement layers remain TIDMAD-profile behaviour — they read
  the profile, which Pets/DAVIS do not have.)
* **Contrast-track implementations live in production task-pack modules**
  (e.g. `execute_tools/task_packs/…` — final home at PR-1 design), NOT under
  `examples/`. `examples/` stays projection-not-authority; its D14 relaxation
  admits only reference *plugin source* + execution manifests + fixtures
  (§5.4), never framework-imported code.

## 4. PR decomposition — **THREE PRs** (`D14-1` → `D14-2` → `D14-3`)

Split by blast radius and by evidence independence, mirroring the Step-07
pattern (seam first, then consumers): one PR that touches frozen production
paths under a byte-parity obligation, then one PR per contrast track, each
independently reviewable and each carrying its own track's full
L1→L2/L3 evidence. Not one PR (parity risk and two new datasets in a single
diff); not two (Pets and DAVIS fail differently — image-folder decode vs
video windowing + licence pinning — and the operator reviews them against
different frozen specs).

Per the operator's instruction this parent gives **scope, validation and
methodology per PR — no commit checklists**; each PR's child design freezes
its commits.

### 4.1 D14-1 — the executable data-path seam, TIDMAD rebound at byte parity

**Scope.** Define the `TaskDataPath` contract + registry; relocate TIDMAD's
executable path behind it (`TIDMADEpochDataset` construction sites,
inference's per-file read loop, the deliverable writer); regime-A default
binding = TIDMAD; a minimal in-repo synthetic second implementation (test-only,
registered from tests) proving the seam admits a non-TIDMAD shape without core
edits. No Pets/DAVIS code.

**Non-goals.** No behaviour change on any TIDMAD surface; no new CLI; no
profile schema change; no `examples/` change.

**Methodology.** Contract-first (typed protocol + registry, unit-owned);
then one production call site at a time, each behind a parity oracle before
the next moves. The 07c precedent (`probe_batch` as the ONE builder;
`construct_registered_model`) is the template: delegation with the original
bytes, never reimplementation.

**Validation.**
- **Byte parity (the PR's spine):** epoch batch streams (content + order,
  fixed seed), validation-family selection, deliverable bytes and
  `run_output` records identical pre/post relocation on the committed
  two-family fixture AND on a TIDMAD Gate-2-shaped bounded run. Tensor hashes
  asserted, not eyeballed.
- **Seam admits a second shape, across the WHOLE surface:** the synthetic
  implementation exercises all four methods — `training_dataset`,
  `validation_dataset`, `write_deliverable`, `read_evaluation_payload` —
  end-to-end through `run_experiment_streaming` with zero generic-core edits
  (the delete-the-hop reachability form: bypassing the registry fails the
  test). **Its supervision-target representation is deliberately DIFFERENT
  from its model-output representation** (Amendment 1's strengthening), so a
  regression-shaped `target == output-shape` assumption anywhere in the seam
  fails here first. This is a structural-genericity proof, NOT a fake Gate-2:
  the materially different REAL evidence remains D14-2/3's.
- **Fail-closed negative (Amendment 3):** the synthetic task with a
  missing/unknown data-path id FAILS with the naming diagnostic — never a
  silent fall-through to TIDMAD.
- **The old bypass is REMOVED, structurally proven:** at D14-1's final state,
  generic production call sites contain **zero direct `TIDMADEpochDataset`
  constructions and zero direct TIDMAD deliverable-codec dependencies**
  outside the registered TIDMAD implementation (an AST census in the
  guardrail style, with any documented task-owned compatibility location
  named in the census, not exempted silently). The final dependency direction
  is `generic trainer/validation/inference/scoring → bound TaskDataPath →
  task implementation`; **no permanent dual path**.
- **No-name-branch guard extended:** the existing guardrail pattern
  (`test_no_model_name_branches`) gains the data-path surface with task names
  (`tidmad`, `pet`, `davis`) in its token set.
- UNIT: contract, registry, parity oracles, scope opacity. GATE 1: none.
  GATE 2: REQUIRED bounded once — a real TIDMAD round through the relocated
  path (this is lifecycle). CI: `execute_tools/` + `core/` suites per the
  #221 selector; the parity oracles are the reachability evidence.

### 4.2 D14-2 — Track B executable: Oxford-IIIT Pet at L2→L3

**Scope.** Acquisition tooling (`tools/example_packs/` fetch + verify against
the official VGG URLs; SHA-pinned archives; data under the pack's gitignored
`data/` lifecycle); EXECUTION-level manifest (decode rule, bilinear-or-chosen
interpolation FROZEN in the manifest, resize-160/crop-144 parameters, /255,
per-item input-tensor hashes for a pinned probe subset); the Pets
`TaskDataPath` implementation (manifest-scoped, deterministic, no
augmentation); one reference CNN plugin through `MODEL_REGISTRY` (architecture
chosen by this PR's design; "known-good executable baseline", §22.11a); a
classification deliverable format + its scoreability contract; accuracy
(higher) computed by the Step-06 handle over the final-eval scope; nested
Gate-1/Gate-2/persistent subset manifests (§17.0.1 bounds); L1 fixtures
upgraded with real-component variants (R2/R3 CE curves from a real bounded
run replacing hand-authored values in the ADDED variant only).

**Non-goals.** No macro-F1/log_loss production path (log_loss stays
D16-blocked, the pack test keeps pinning that); no augmentation; no
hyperparameter search — the reference plugin is a baseline, not a candidate.

**Methodology.** Manifest → reader → plugin → metric, in that order, each
stage hash-pinned before the next consumes it (the same capture-first
discipline as the Step-00 goldens). Determinism proven by double-run tensor
hashes, cross-process (the `PYTHONHASHSEED` lesson).

**Validation.** Identity manifests unchanged (already frozen); execution
manifest SHA-pinned; decode/transform determinism (same item → same hash,
twice, two processes); scope disjointness re-verified at the reader; a real
bounded training run yields R2/R3 curves accepted by `TrainingHistory`
validators with `comparability` stamped; accuracy computed by the real metric
handle on the real deliverable; **the L1 rung (B-07a-1) still passes
unchanged** (cumulative corpus). UNIT: manifest/transform/reader arithmetic,
deliverable round-trip. GATE 1: none. GATE 2: REQUIRED bounded once — the
full Pets loop (train→history→infer→deliverable→accuracy) at the Gate subset
size. CI: new pack files enter as literal-path inputs; the selector's
AREA_OWNERS row for `examples/` already routes them.

### 4.3 D14-3 — Track C executable: DAVIS future-frame at L2→L3

**Scope.** As D14-2, plus the Track-C-specific obligations: **licence
verification and pinning** of the TrainVal-480p artifact's applicable terms in
`PROVENANCE.md` (frozen wording; roadmap: executable provenance is incomplete
without it); **clip-identity materialization** — deterministic, even,
per-sequence `(sequence_name, start_frame)` windows within the indicative
caps (≤8/≤4/≤4 per train/validation/final-eval sequence), committed and
SHA-pinned as the clip manifest the PR0 review deferred here; the window
reader (`[3,8,128,224]` → target `[3,4,128,224]`, values [0,1], resize rule
frozen in the execution manifest); one reference predictor plugin; a dense
continuous deliverable + scoreability; **global MSE (lower)** — the FROZEN
aggregation over all pixels × channels × future frames of the final-eval
clips — through the metric handle; nested Gate subsets; L1 fixture upgrades.

**Non-goals.** No segmentation masks as inputs; no optical-flow or
augmentation machinery; no PSNR in the golden path (optional observation
only, as the pack already declares).

**Methodology.** Sequence manifest (frozen) → frame counts → clip manifest →
window reader → plugin → metric; the clip-materialization rule is a pure
function over (sequence, frame_count, caps) unit-proven against hand-computed
expectations BEFORE any real frame is decoded — temporal-leakage guards
(sequence-disjointness across scopes at the CLIP level) are part of that pure
layer.

**Validation.** Clip manifest: deterministic re-derivation equals the
committed artifact; scope disjointness by sequence identity at clip level;
caps respected. Reader: window/tensor-shape/hash determinism. Real bounded
run → R2/R3 MAE curves through the validators → deliverable → MSE via the
handle. Licence: pinned text present, test-asserted non-empty and
artifact-specific. UNIT/GATE/CI: as D14-2, with the addition that the
sequence-vs-clip disjointness guard is UNIT-owned (pure) while the full loop
is the Gate-2 run.

## 5. Cross-cutting invariants (all three PRs)

**5.1 No task-identity branches in generic core** — enforced by the extended
no-name-branch guardrail (D14-1), not by review.

**5.2 No production import of `examples/`** — the existing governance guard
stays; the task-pack production modules live under the production tree and are
themselves example-free.

**5.3 Cumulative corpus** — no L1 fixture or rung is deleted or weakened;
real-component variants are ADDED. `test_pack_governance` continues to pass
throughout, with its D14-owned relaxations applied surgically.

**5.4 The D14 `examples/` relaxation, scoped:** reference plugin *source*
(loaded through the plugin loader in tests, never imported by production),
execution manifests, upgraded fixtures, and updated STATUS/PROVENANCE rows.
Nothing else. The maturity-vocabulary module (`tests/unit/examples/
maturity_vocabulary.py`, #221) is edited ONCE for the L1→L2/L3 transition —
that is the single-edit design working as intended.

**5.5 Raw data lifecycle** — never committed; fetched by tooling into the
packs' gitignored `data/`; every test that needs real data declares it and
skips with the fetch command in the reason (the `SIDERIUS_LEGACY_TIDMAD_ROOT`
pattern); CI never fetches.

**5.6 Frozen-surface parity** — TIDMAD scoring arithmetic, prompts (PB
sha256), record schemas (additive only), `score_vector`'s 2-tuple, severity
resolution: untouched. Any PB delta is a stop condition, not a judgement call.

## 6. Adversarial self-review (operator checklist, applied to this design)

| threat | where this design blocks it |
|---|---|
| task-identity leakage | registry binding (§3); guardrail token-set extension (D14-1); the synthetic second implementation proves zero-core-edit binding *before* any real task uses the seam |
| `examples/` production dependency | §5.2 guard retained; task-path implementations deliberately homed in the production tree (§3), so there is no pressure to import the packs |
| TIDMAD-shaped abstraction | the seam's contract (§3) contains no file/segment/channel vocabulary — those stay in TIDMAD's implementation; **DatasetProfile is explicitly NOT the binding key** (§2.1), which is the exact trap the packs' "NOT representable" rows document |
| fake execution | L2/L3 evidence is defined as *executed* artifacts: real R2/R3 curves through the 07a validators (which fail closed on absent/partial materialization), real deliverables, Gate-2 bounded runs per track |
| fake metrics | the golden numbers are computed by the Step-06 handle over the real deliverable — the same handle TIDMAD uses; a hand-computed accuracy in a fixture stays labelled `l1_fixture` |
| missing training validation | R3 is unconditional for supported tasks (Rev 5.1); both tracks' R3 is in the frozen spec and asserted through `TrainingHistory` |
| missing golden metric | accuracy↑ / MSE↓ are frozen (§22.9a) and each PR's Gate-2 run must produce them or FAIL |
| launcher/runtime residue | no launcher changes anywhere in D14; runtime-control already binds through profile/contract (07c) and D14-1's parity oracle would catch a drive-by |
| the seam becoming a second config hierarchy | §20.6 constraint honoured: binding rides existing task config; the registry id is one additive field |

**Scope-opacity residual → GitHub issue
[#225](https://github.com/Galileo-Sandbox/SIDERIUS/issues/225)** (operator
ruling: keep the asymmetry, do NOT invent a universal scope abstraction in
D14; task-owned disjointness evidence per pack; natural future owner is
Step 12's composition root. Blocks D14: no · Blocks Step 08: no).

Residual risks, named rather than hidden: (a) D14-1's parity obligation is the
milestone's real risk — mitigated by per-call-site oracles and the Gate-2
TIDMAD run; (b) DAVIS licence pinning may surface terms requiring operator
judgement — that is a STOP, not a workaround; (c) the reference plugins must
not drift into model research — "known-good baseline" is their frozen role.

### 6.1 Post-amendment adversarial pass (operator's five threats, 2026-08-18)

| threat | disposition after the amendments |
|---|---|
| 1. regression-shaped target assumptions | CLOSED structurally: the contract separates `model_input` (contract-input-bound) from `supervision_target` (objective-owned, representation-free), and the synthetic task's target representation is REQUIRED to differ from its model-output representation — the assumption now fails in D14-1's own tests before any real task meets it |
| 2. TaskDataPath owning metric semantics | CLOSED by the frozen MAY/MUST-NOT codec split and the rename to `read_evaluation_payload`; the fixed output path terminates at the Step-06 authority, and §3.1's dependency row already barred records/prompts/runtime-control from the seam |
| 3. silent TIDMAD fallback for new tasks | CLOSED: regime-A default reclassified as a compatibility path only; explicit/unknown/invalid bindings fail closed with a naming diagnostic; a deterministic negative test is a D14-1 acceptance item |
| 4. dual old/new execution paths | CLOSED as an acceptance criterion: an AST census proves zero direct `TIDMADEpochDataset` constructions and zero direct deliverable-codec dependencies outside the registered TIDMAD implementation at D14-1's final state — no permanent dual path |
| 5. synthetic proof exercising only the training half | CLOSED: the synthetic implementation must exercise all four methods end-to-end, and it is labelled a structural-genericity proof, not a fake Gate-2 |

None of the five required widening the four-method surface, adding a
declarative concept, or touching a Step-06/07 contract — the amendments are
narrowings and clarifications, not architecture changes. **No new
parent-level contradiction found.**

## 7. Stop conditions (milestone level)

Stop and return to the operator if: TIDMAD parity cannot be held at any
relocated call site · the seam cannot express a track without reaching into
`DatasetProfile`'s 1-D vocabulary · the DAVIS licence audit finds terms
incompatible with the committed-manifest / fetched-data model · a PB byte or
frozen record surface would move · real training on the bounded subsets cannot
satisfy the 07a validators without weakening them · `examples/` governance
would need a relaxation beyond §5.4.

## 7a. Milestone execution record (all three children implemented, 2026-08-18)

| child | branch / head | Gate 2 | evidence |
|---|---|---|---|
| **D14-1** seam + TIDMAD relocation | `d14-1-task-data-path-seam` — **draft PR #230**, exact-head CI **SUCCESS** (run 32184157986) | **PASS ×2** (pre-relocation baseline + relocated path, identical posture) | child ledger §9; `/home/klz/Data/SIDEREIS_DATA/d14_gate2_{baseline,relocated}_20260818/` |
| **D14-2** Pets | `d14-2-pets-executable` (stacked on D14-1) | **PASS** | child ledger §6 C6; `/home/klz/Data/SIDEREIS_DATA/d14_pets_gate2_20260818/` |
| **D14-3** DAVIS | `d14-3-davis-executable` (stacked on D14-2) | **PASS** | child ledger §6 C7; `/home/klz/Data/SIDEREIS_DATA/d14_davis_gate2_20260818b/` |

**The §1 sentence, demonstrated on three tasks through ONE architecture:**

| | TIDMAD | Oxford-IIIT Pet | DAVIS |
|---|---|---|---|
| scope vocabulary | `{file: [segments]}` | manifest rows | clip identities `(sequence, start)` |
| model input | int windows | `[3,144,144]` f32 | `[3,8,128,224]` f32 |
| supervision target | int windows (same shape) | scalar class index | `[3,4,128,224]` dense (≠ input shape) |
| objective | focal / ce | ce | smooth_l1 (MAE-family) |
| deliverable | per-file ABRA HDF5 | one predictions CSV | one npz of dense tensors |
| golden metric | frozen denoising score (higher) | accuracy (higher) | global MSE (lower) |
| real Gate-2 result | score −0.948 (relocated run) | accuracy 0.027 (= chance; constant collapse, honestly recorded) | MSE 0.017290, **better than the last-frame-copy baseline 0.017392** |

Three targets that share neither shape, rank, dtype nor cardinality; three
deliverable formats; three metrics — and **zero task-name branches** in the
generic core, mechanically enforced.

### Cross-task validation (§21 checks, executed at the D14-3 head)

* **No task-name branching on the data-path surface** — the census's
  task-identity guardrail scans all six surface modules for
  `tidmad|pet|pets|davis` literal comparisons: **zero** (5 census tests
  green, including exact construction/codec-call counts, the
  delete-the-hop detector and the parent-only transport flag).
* **No production dependency on `examples/`** — the PERMANENT separability
  guard is green (12 governance tests); it FIRED once during D14-2 C7 (the
  Pets gate runner importing pack tooling) and the fix was ownership, not
  an exemption. Plugin source under `examples/*/plugins/` is loaded
  dynamically, never imported.
* **One registry, three implementations** — importing all three modules
  yields exactly `['davis_future_prediction', 'oxford_iiit_pet', 'tidmad']`.
* **Step-07 training semantics preserved** — 07a/07c suites pass UNCHANGED
  through every relocation; the R3 trigger generalization (D14-2 C5b) left
  the regime-A leg byte-path-identical and added fail-closed refusals for
  the explicit leg.
* **Step-06 metric ownership preserved** — three instances behind ONE
  handle; scoreability still runs before arithmetic (proven per instance
  with poison kwargs); pack declarations rebind through one sanctioned
  function; the frozen TIDMAD formula is untouched.
* **TaskDataPath free of task identity and metric semantics** — the seam
  module names no task, computes no metric; every task's naming, geometry
  and codec live in its own implementation.
* **Cumulative corpus honoured** — both L1 fixture pairs kept verbatim;
  real-component variants ADDED; the 07a rung runs all of them through the
  same boundary.

**FINDING during terminal validation — stacked PRs get NO CI.**
`ci.yml` triggers on `pull_request: branches: [master]`, so #231 and #232
ran nothing; D14-2/D14-3 code was never type-checked. A
`workflow_dispatch` run against the stack head surfaced **17 real pyright
errors** across both children (config classes typed `type | None`, the
seam's `object` payload, `MetricResult.scalar`'s `float | None`, numpy's
`savez_compressed` kwargs binding, one heterogeneous dict annotation) —
all fixed at the boundary, none suppressed, and **both gates re-run to
prove runtime neutrality** (Pets accuracy 0.0270, DAVIS MSE 0.017290,
identical to the recorded PASS evidence). Local pyright cannot substitute
(the pinned runner crashes on this box's Node), so CI is the only type
checker: recorded as **issue #233**, and every future stacked milestone
must either fix the trigger or dispatch runs deliberately.

**Local terminal validation** (parallel chunks, never a serial full suite):
`tests/unit/execute_tools/` **1245 passed / 1 skipped**;
`examples + guardrails + agent + nodes + ml_models + tools` **4830 passed /
1 failed** — the single failure being the documented local-only stray-file
guard (an untracked partial download from a corrected first fetch attempt;
`rm examples/oxford_iiit_pet/data/raw/images.tar.gz` clears it, and no
other checkout or CI is affected).

### 7a.1 Terminal closeout (operator ruling, 2026-08-18)

The operator ACCEPTED the architectural/executable work as complete enough
to enter closeout and fixed the remaining scope:

* **The Pets result — accuracy 0.027, a constant-prediction collapse — is
  NOT a D14 failure and is deliberately NOT tuned away.** D14 proves
  EXECUTABLE GENERICITY, not benchmark quality. The observation is kept
  prominently because it is useful empirical evidence for **Step 08 Health
  design: a task can be fully executable while the candidate is
  unhealthy.** DAVIS beating the last-frame-copy baseline
  (0.017290 < 0.017392) is the complementary evidence that the reference
  path is not vacuous.
* **No new architecture work, no model tuning, no fixing of unrelated
  issues inside D14** (#226–#229 stay separate; the stacked-PR CI trigger
  defect stays with #233 — D14 does not modify CI trigger architecture,
  it only requires ONE manual exact-head dispatch to PASS).
* **Evidence ordering is load-bearing:** final code + final docs → commit →
  that SHA is the final intended head → exact-head CI dispatched on THAT
  SHA. A green run that predates the last docs commit belongs to the
  previous head and is recorded as such, never as the head's evidence.

### 7a.2 Residual risks and deferred issues (none block D14)

| id | what | blocks D14? | blocks Step 08? |
|---|---|---|---|
| **#225** | scope-opacity boundary (framework has no scope-aware checker; each implementation discharges exact materialization) — by design, recorded at the parent | no | no |
| **#226** | chain auto-resume silently runs zero iterations and exits 0 (plugin banners pollute the inspector's stdout) | no (fresh workspaces / `--start_iter` unaffected) | no — but any resumed campaign is affected |
| **#227** | integration-suite rot: 13 pre-existing failures at master (fixture schema drift, a moved patch target) | no | no |
| **#228** | Step-06 two-route divergence on non-finite scores (`-inf` vs `None`) + an unseeded flaky fixture | no | no |
| **#229** | a "pseudo" g2 test escaping to the REAL live probe when `tidmad_data_config.yaml` exists | no | no |
| **#233** | stacked PRs get no CI (`pull_request: branches: [master]`) — found by this milestone; worked around with manual dispatch | no | **practically yes if Step 08 stacks PRs** — fix it before that, or dispatch deliberately |

Known non-blocking residue inside D14's own scope, recorded where it lives:
the engine's remaining TIDMAD-shaped knobs (`segmentation_size`, the legacy
single-file path, sequential ordering reading `file_row_ranges`) and the
fix-mode baseline writer's direct codec call — all census-pinned so they
cannot grow, and all owned by later engine-genericization steps.

### 7a.3 Step-08 readiness

**Yes — the three tracks now provide enough real executable contrast
evidence to begin Step 08.** Step 08 (HealthGate: A/B/C on REAL applicable
artifacts) needs exactly what D14 produced: real deliverables and real
training histories from tasks whose artifacts differ enough to distinguish
"TIDMAD-specific gate is INAPPLICABLE here" from "generic gate RUNS here".
Concretely available now: an ABRA HDF5 denoising deliverable, a
classification CSV, a dense npz tensor set; three real `TrainingHistory`
records (focal, ce, smooth_l1) with R2+R3 and `comparability` stamped; and
**a genuinely unhealthy real candidate** (the Pets constant-prediction
collapse) plus a healthy-ish one (DAVIS beating its trivial baseline) —
i.e. both sides of the health discrimination Step 08 must make, from real
runs rather than synthetic JSON. The premature Step-08 draft on master must
still be re-compared against this actual behaviour before any Step-08
design is written (§8).

## 8. Completion

D14 is complete when: all three PRs are merged with their Gate-2 runs PASSED ·
the §1 sentence is demonstrated by committed evidence (execution manifests,
pinned hashes, per-track Gate artifacts) · both packs' STATUS rows read
L2/L3 with the maturity vocabulary edited once · the §15.1 D14 row is updated
in the same commit as the last merge · and the premature Step-08 draft is
re-opened as scratch only, re-compared against the three tracks' actual
executable behaviour before any Step-08 design is written.
