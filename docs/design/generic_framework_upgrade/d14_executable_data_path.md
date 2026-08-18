# D14 — Executable data path + the two contrast tracks at executable maturity — acceptance / decomposition design

## 0. Status and provenance

**DRAFT rev 1 — for adversarial self-review, then implementation under the
frozen working rules (operator directive 2026-08-18: "produce the D14
decomposition/design from source truth; adversarially review it; then proceed
autonomously through implementation and validation").**

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
    training_dataset(scope, …)   -> torch Dataset yielding (input, target)
                                    tensors satisfying the bound ModelIOContract
    validation_dataset(scope, …) -> same, over the validation identity scope
    write_deliverable(outputs, …)-> the task's persisted deliverable, at the
                                    path/layout the task's deliverable authority
                                    declares
    read_deliverable_for_metric(…)-> what the Step-06 metric handle scores
```

Binding rules (frozen):

* **Registry-bound, never name-branched.** Implementations register exactly as
  model plugins do (the `MODEL_REGISTRY` precedent); the bound task's config
  names its data-path id. Generic core resolves by id — a new task binds by
  registration + configuration, with zero core edits (§1.1's success
  criterion, made structural).
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
- **Seam admits a second shape:** the synthetic implementation trains a toy
  model end-to-end through `run_experiment_streaming` with zero generic-core
  edits (the delete-the-hop reachability form: bypassing the registry fails
  the test).
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

Residual risks, named rather than hidden: (a) D14-1's parity obligation is the
milestone's real risk — mitigated by per-call-site oracles and the Gate-2
TIDMAD run; (b) DAVIS licence pinning may surface terms requiring operator
judgement — that is a STOP, not a workaround; (c) the reference plugins must
not drift into model research — "known-good baseline" is their frozen role.

## 7. Stop conditions (milestone level)

Stop and return to the operator if: TIDMAD parity cannot be held at any
relocated call site · the seam cannot express a track without reaching into
`DatasetProfile`'s 1-D vocabulary · the DAVIS licence audit finds terms
incompatible with the committed-manifest / fetched-data model · a PB byte or
frozen record surface would move · real training on the bounded subsets cannot
satisfy the 07a validators without weakening them · `examples/` governance
would need a relaxation beyond §5.4.

## 8. Completion

D14 is complete when: all three PRs are merged with their Gate-2 runs PASSED ·
the §1 sentence is demonstrated by committed evidence (execution manifests,
pinned hashes, per-track Gate artifacts) · both packs' STATUS rows read
L2/L3 with the maturity vocabulary edited once · the §15.1 D14 row is updated
in the same commit as the last merge · and the premature Step-08 draft is
re-opened as scratch only, re-compared against the three tracks' actual
executable behaviour before any Step-08 design is written.
