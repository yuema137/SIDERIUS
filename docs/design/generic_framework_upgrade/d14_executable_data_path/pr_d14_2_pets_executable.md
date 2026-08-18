# PR D14-2 — Track B executable: Oxford-IIIT Pet at L2→L3

**Parent**: `docs/design/generic_framework_upgrade/d14_executable_data_path.md`
(FROZEN rev 3) §4.2 — this child instantiates it and adds nothing beyond it.
**Task authority**: roadmap §22.9a (frozen), mirrored by
`examples/oxford_iiit_pet/README.md` "Task (frozen §22.9a)".
**Status**: **SELF-FROZEN rev 2 (2026-08-18)** — directive §12: the child is
fully inside the frozen parent, so it freezes itself and the operator reviews
the milestone. The adversarial self-review (rev 1 → rev 2) produced three
material amendments, each recorded in place: the engine R3 trigger
generalization (§2.5b — the parent's own Pets validation row is
unsatisfiable without it); the acquisition correction (§2.1 — the PACK's
committed lifecycle wins over a loose reading of parent §4.2: data
machine-local, OUTSIDE the tree, root travels as the seam's existing
`data_dir`); and the fail-closed `train_portion` refusal (§2.3 — no invented
subsampling semantics on a frozen task). The two D14-delegated freedoms are
exercised exactly where the frozen text delegates them: interpolation =
BILINEAR, reference architecture = the §2.4 small CNN.

## 0. Source audit (what exists at the D14-1 head)

| surface | state | evidence |
|---|---|---|
| TaskDataPath seam | LANDED (D14-1): four-method contract, fail-closed registry, run-scoped binding, subprocess transport, no-dual-path census | `execute_tools/task_data_path.py`; `tests/unit/guardrails/test_task_data_path_census.py` |
| engine genericity | PROVEN: a non-TIDMAD task trains through the PRODUCTION `run_experiment_streaming` body under a synthetic binding (own `ModelIOContract`; CE loss; scalar-int target vs vector output) | `tests/unit/execute_tools/test_d14_synthetic_e2e.py` (D14-1 C5) |
| Step-06 metric handle | one ABC (`EvaluationMetric.evaluate` = scoreability → `_compute`), `MetricSpec`, `PresenceScoreabilityContract`, structured `NotScoreableResult`; loss-shaped ids refused | `execute_tools/evaluation_metric.py:480-517,215,115` |
| pack identity (L0/L1) | FROZEN: manifests 2 946 / 734 / 3 669 (`data/manifests/*.csv` + `SHA256SUMS`), declared `ModelIOContract` `[B,3,144,144]f32 → [B,37]f32` (class axis 37), declared `MetricSpec` accuracy(higher, `deliverable_presence` scoreability) + macro_f1; L1 R2/R3/diagnosis fixtures | `examples/oxford_iiit_pet/`; `tests/unit/examples/test_oxford_iiit_pet_pack.py` |
| identity tooling | derivation of the manifests from the official lists (frozen i%5 rule), declaration writers | `tools/example_packs/oxford_iiit_pet.py`, `_common.py`, `declarations.py` |
| provenance | `annotations.tar.gz` SHA-pinned (`52425fb6…`); **`images.tar.gz` (~792 MB) URL listed, NOT yet fetched/pinned** | `examples/oxford_iiit_pet/PROVENANCE.md:9,26-30` |
| plugin mechanism | `MODEL_REGISTRY` + `ml_models/plugin_loader.py` (`PLUGIN_MODEL_TYPE` / `PLUGIN_CONFIG_CLASS` / `PLUGIN_MODEL_CLASS`), dynamic load, never imported | `core/sandbox_executor.py` note; C5 e2e used the registry directly |
| governance pins | `.py` under `examples/` forbidden — **"relaxation owner: D14"** in the pin's own text; production must never import `examples.*` (absolute, stays) | `tests/unit/examples/test_pack_governance.py:155-171` |
| Gate-2 bounds | work-bounded, 1 iter × 1 round default, PASS is functional (plumbing), enforceable BEFORE training | roadmap §17.0.1 |
| composition boundary | D14 = modules separately executable (train → history; infer → deliverable → metric); Step 12 owns full-loop composition; Steps 10-11 own workflow/infra binding | roadmap §22.11a timeline |

## 1. Scope (parent §4.2, instantiated) and non-goals

Everything the parent lists, with these concrete homes:

```text
tools/example_packs/fetch_oxford_iiit_pet.py   NEW — fetch BOTH official archives
                                       (images + annotations) with SHA-256
                                       verify-or-record; extract under an
                                       OPERATOR-SUPPLIED machine-local --dest
                                       OUTSIDE the tree (§2.1; pack data/README
                                       lifecycle); idempotent; offline-safe
                                       (verify-only mode when files exist)
tools/example_packs/oxford_iiit_pet.py EXTENDED — derives the EXECUTION manifest
                                       (decode/resize/crop/normalize rule +
                                       frozen interpolation + per-item probe
                                       hashes) and the NESTED GATE SUBSET
                                       manifests from the frozen identity CSVs
examples/oxford_iiit_pet/data/manifests/execution.json      NEW, committed, SHA-pinned
examples/oxford_iiit_pet/data/manifests/gate2_train.csv     NEW, committed (nested ⊂ train)
examples/oxford_iiit_pet/data/manifests/gate2_validation.csv NEW (⊂ validation)
examples/oxford_iiit_pet/data/manifests/gate2_final.csv     NEW (⊂ final)
examples/oxford_iiit_pet/plugins/pets_reference_cnn.py      NEW — the reference CNN
                                       plugin SOURCE (loaded dynamically at gate
                                       runtime through the plugin mechanism;
                                       NEVER imported by production — §5.4)
execute_tools/pets_data_path.py        NEW — the Pets TaskDataPath implementation
                                       (flat, symmetric with tidmad_data_path.py):
                                       manifest-scoped reader, deterministic
                                       transform, classification deliverable
                                       codec; registers id "oxford_iiit_pet"
execute_tools/evaluation_metric.py     EXTENDED — ONE generic classification
                                       accuracy instance (`AccuracyMetric`),
                                       arithmetic only (fraction correct);
                                       Pets binds it with the pack's DECLARED
                                       MetricSpec (the declaration IS the spec)
scripts/run_pets_gate2.py              NEW — the bounded Gate-2 runner: train →
                                       TrainingHistory → infer → deliverable →
                                       accuracy, over the gate subsets, ≤10 min
```

**Non-goals (parent, verbatim obligations):** no macro-F1/log_loss production
path (log_loss stays D16-blocked; the pack test keeps pinning the refusal);
no augmentation; no hyperparameter search (the reference plugin is a
baseline, not a candidate). Additionally out of scope here: no chain/tuner
binding (Step 10/12), no HealthGate applicability work (Step 08), no DAVIS
work (D14-3), no changes to the four-method seam (parent stop condition 1).

## 2. The executable pieces, precisely

### 2.1 Acquisition (C1)

**The pack's committed lifecycle governs (PR0 `data/README.md`, roadmap
§22.23.10): images live in a MACHINE-LOCAL directory OUTSIDE the tree —
never under `examples/`.** The "how the framework is told" decision the
README defers to D14 resolves to the mechanism the seam ALREADY carries:
the machine-local root travels as `EpochSamplingParams.data_dir` /
`EvalMaterializationParams.data_dir` (exactly TIDMAD's `data_dir` pattern —
no new YAML, no new config channel; the gate runner takes `--data_dir`).
On this machine: `/home/klz/Data/OXFORD_IIIT_PET/` (sibling of the TIDMAD
data root — clearly-labelled machine-specific operator documentation, per
the portability policy).

`images.tar.gz` (~792 MB) from the official VGG URL (PROVENANCE.md:9),
SHA-256 recorded at first fetch into `PROVENANCE.md` (same table form as the
annotations entry: URL, fetch date, size, archive SHA, member count) and
into `data/manifests/SHA256SUMS` as the archive pin (the PIN is tracked;
the bytes are not). `tools/example_packs/fetch_oxford_iiit_pet.py
--dest <machine-local dir>` is idempotent (existing + SHA-match →
verify-only), fails closed on mismatch, and extracts to
`<dest>/images/*.jpg`. The annotations archive gets the same
treatment (its SHA is already pinned — the tool VERIFIES it).

Known dataset quirks the reader must survive (recorded now, asserted at C2):
a handful of official JPEGs are CMYK or carry EXIF orientation; the decode
rule is therefore FROZEN as: `PIL.Image.open → .convert("RGB")` (no EXIF
transpose — deterministic across PIL versions), THEN transform. Any image
the rule cannot decode is a HARD ERROR naming the image id (fail closed —
never skip: the manifests are the scope authority and must materialize
exactly, the D14-1 lesson).

### 2.2 Execution manifest + transform (C2)

FROZEN transform (§22.9a row "input topology", parameterized nowhere else):

```text
decode RGB (PIL, .convert("RGB"), no EXIF transpose)
→ aspect-preserving resize, SHORTER side = 160 (PIL BILINEAR — frozen here)
→ center crop 144×144
→ float32 [3,144,144] = pixel/255.0   (CHW, RGB order)
```

`execution.json` records: the rule above (machine-readable fields:
`decode`, `interpolation: "bilinear"`, `resize_shorter: 160`,
`crop: [144,144]`, `normalize: "div255"`, `layout: "CHW-RGB"`), the pack
schema version, and **per-item float32 tensor SHA-256 for a pinned probe
subset** (first image of every class from the train manifest = 37 probes —
class-covering, small). The manifest is committed and SHA-pinned by a test;
determinism is proven by double-run probe hashes in TWO processes
(`PYTHONHASHSEED` lesson, parent methodology).

### 2.3 The Pets `TaskDataPath` (C3)

`execute_tools/pets_data_path.py`, id `"oxford_iiit_pet"`, registered at
import (inert until something resolves it — the D14-1 pattern):

* `PetsScope` (task-owned, opaque to the framework): the manifest rows in
  scope — `(image_id, class_index)` pairs — plus the images root and the
  frozen transform parameters AS READ from `execution.json` (the scope
  carries the already-loaded rule; the implementation never re-reads global
  state).
* `training_dataset(scope, params)` → torch Dataset yielding
  `(float32 [3,144,144], int class_index)` — Amendment 1 live: the target
  is a scalar int, the model output is `[37]` logits. There is NO
  subsampling rule in this task (frozen: no augmentation), so
  `params.train_portion < 1.0` is REFUSED loudly (fail closed — the task
  defines no fractional-epoch semantics; inventing one here would be a task
  mutation); `params.max_samples` is honored as a deterministic
  prefix-after-manifest-order cap (the harness-owned validation-posture
  ceiling, the TIDMAD analog); `params.epoch_seed` is accepted and recorded
  but changes nothing (deterministic full-scope epochs).
* `validation_dataset(scope, params)` → same over the validation rows;
  exact-materialization obligation: `len(dataset) == len(scope.rows)` and
  every id decodable, else a `ValidationScopeError` naming the id (the
  D14-1 task-owned check discipline, Pets vocabulary).
* `write_deliverable(outputs, request)` → the classification deliverable:
  ONE CSV `predictions_{run}_{exp}.csv` with header
  `image_id,predicted_class_index` + one row per final-eval image, sorted
  by image_id (byte-deterministic). Codec only — no correctness knowledge.
* `read_evaluation_payload(request)` → decodes that CSV to
  `{image_id: predicted_class_index}` for the Step-06 authority; missing
  file → `{}`-shaped absence is NOT silently scored — scoreability owns
  the refusal (`deliverable_presence`, exactly as the pack DECLARED at PR0).

### 2.4 Reference CNN plugin (C4)

`examples/oxford_iiit_pet/plugins/pets_reference_cnn.py` — "known-good
executable baseline, architecture chosen by this design" (§22.11a): a small
deterministic CNN sized for a bounded CPU/GPU run —
`Conv3×3(3→16)/ReLU/MaxPool → Conv3×3(16→32)/ReLU/MaxPool →
Conv3×3(32→64)/ReLU/AdaptiveAvgPool(4×4) → Linear(1024→37)` (~0.6 M params).
No pretrained weights (nothing to fetch or license), no augmentation, plain
Adam. It conforms to the plugin contract (`PLUGIN_MODEL_TYPE =
"pets_reference_cnn"`, config class, model class) and is loaded DYNAMICALLY
by the gate runner through the existing plugin mechanism; the governance
guard is RE-SCOPED (its own text names D14 as owner): `.py` under
`examples/` is allowed ONLY at `examples/*/plugins/*.py`; production imports
of `examples.*` stay absolutely forbidden (guard (c) untouched).

Engine-residue note (recorded, not hidden): `run_experiment_streaming` reads
`model_cfg.segmentation_size` (a TIDMAD knob) at run start, so the plugin
config DECLARES `segmentation_size: 144` as an inert engine-compatibility
field — consumed by nothing on the Pets path (the D14-1 C3 residue list
already names the engine's TIDMAD-shaped knobs as later-step seams).

### 2.5 Accuracy through the Step-06 handle (C5)

`AccuracyMetric(EvaluationMetric)` in `execute_tools/evaluation_metric.py` —
instance #2, GENERIC arithmetic: `_compute(deliverables, *, predictions,
truth)` → `scalar = fraction of final-eval ids with predictions[id] ==
truth[id]`, `per_sample = None` (no per-file vector concept),
`references_used = ()`. Direction/aggregation/scoreability come from the
pack's DECLARED `metric_accuracy.json`, validated through
`MetricSpec.model_validate` — the declaration IS the spec; no second
authoring of the metric identity. A missing/short deliverable is refused by
the scoreability contract BEFORE arithmetic (Step-06 order, load-bearing).
The TIDMAD instance, its spec derivation and the frozen score formula are
untouched (parent Amendment 2 / the frozen-formula rule).

### 2.5b Engine R3 trigger generalization (SOURCE-AUDIT FINDING → its own commit)

**FINDING (adversarial self-review, rev 1).** At the D14-1 head the engine's
R3 validation pass is TRIGGER-COUPLED to the TIDMAD-vocabulary argument:
everything runs under `if eval_sample_set is not None:` — the TIDMAD disk
preflight, the 07c clamp, the regime-A eval-scope assembly AND the per-epoch
`_validation_pass` call. An explicit `task_eval_scope` alone yields NO R3.
The parent's own validation row requires "a real bounded training run yields
R2/R3 curves accepted by `TrainingHistory` validators" for PETS — so the
trigger must generalize. This is NOT a seam change (four methods untouched)
and NOT a Step-07 contract change (the 07a invariant's teeth — exact
materialization — moved INTO each implementation at D14-1 C3).

**The change (C5b):** the R3 pass runs when `task_eval_scope is not None`
(the generic condition). Regime-A callers are byte-identical: supplying
`eval_sample_set` still runs the TIDMAD preflight + clamp and ASSEMBLES
`task_eval_scope`, exactly as D14-1 C3 left it. An EXPLICIT
`task_eval_scope` (no `eval_sample_set`) runs R3 with
`validation_requested_rows` from the new optional
`validation_requested_rows: int | None` engine parameter — declared by the
caller in the task's own vocabulary (Pets: `len(gate2_validation rows)`),
enforced by the implementation's exact-materialization check inside
`validation_dataset`, and stamped into `TrainingHistory` exactly as the
preflight's number is today (requested stays independent of materialized:
the caller DECLARES, the implementation MATERIALIZES-or-dies, the validators
compare). Supplying an explicit scope WITHOUT the declared row count is a
loud startup error (never a silently unvalidated R3).

**Parity obligations:** 07a/07c suites pass UNCHANGED (regime-A leg
untouched — same preflight, same clamp, same assembly point); the D14-1
synthetic e2e keeps its no-R3 case (`task_eval_scope=None`) and GAINS the
explicit-R3 case; no prompt/record/schema change anywhere.

### 2.6 The bounded Gate-2 runner (C6)

`scripts/run_pets_gate2.py` — operator-launchable, ≤10 min, work-bounded
BEFORE anything starts (§17.0.1): trains the reference plugin over
`gate2_train.csv` (nested subset: **10 images/class = 370**; 2 epochs,
batch 32 → ~24 optimizer steps/epoch) through the PRODUCTION
`run_experiment_streaming` under `bind_task_data_path(pets)` with the pack's
declared `ModelIOContract` and `eval` scope = `gate2_validation.csv`
(2/class = 74 rows) so **R2+R3 land in `training_history` through the real
07a machinery**; then inference over `gate2_final.csv` (10/class = 370)
through the trained model → `write_deliverable` → `read_evaluation_payload`
→ `AccuracyMetric.evaluate` → PASS evidence printed and persisted. PASS is
FUNCTIONAL (finite CE curves accepted by `TrainingHistory` validators with
`comparability` stamped; a finite accuracy in [0,1] from the real handle on
the real deliverable); model quality is NOT a pass condition — though with
37 classes, `accuracy > 1/37 · 2` after 2 epochs is recorded as an
OBSERVATION, not a gate condition.

The gate subsets are DERIVED deterministically from the frozen identity
manifests (first N per class in the manifests' committed sort order),
committed as CSVs, and pinned — nested Gate-1/Gate-2/persistent manifests in
the §17.0.1 sense (Gate 1 = none for D14-2; the file trio still lands so
later steps have the bounds).

### 2.7 L1 fixtures upgraded, not replaced (C7)

The real bounded run's R2/R3 CE curves are captured as the ADDED
"real-component" variant beside the existing hand-authored L1 fixtures
(`expected/training_history_l1_fixture.json` UNCHANGED — cumulative-corpus
RULE, §22.11a); the rung test gains the variant. STATUS.md moves the
executable rows to L2/L3 with the run's evidence pointers; PROVENANCE.md
gains the images pin; the roadmap §15.1 row is NOT touched (parent: deferred
to the D14-3 milestone close).

## 3. Commit plan (this child freezes it)

| commit | content | validation gate before the next |
|---|---|---|
| **C1** | fetch tool + images archive pinned (PROVENANCE + SHA256SUMS); data extracted locally (gitignored) | tool idempotency + SHA verify-or-fail unit-tested with tmp fixtures; real archive SHA recorded; NO production change |
| **C2** | execution manifest generator + committed `execution.json` (37 probe hashes) + gate subset CSVs | probe determinism: same tensor hashes, twice, TWO processes; subsets ⊂ their parents, class-covering, pinned |
| **C3** | `pets_data_path.py` (scope, datasets, deliverable codec, registration) | unit: transform parity vs `execution.json` probes THROUGH `training_dataset`; exact-materialization negative (missing id → error naming it); deliverable round-trip; census allowlists updated (+ its own registration inertness) |
| **C4** | reference plugin source + governance-guard re-scope | plugin loads through the real loader; forward `[2,3,144,144]→[2,37]`; guard (b) re-scoped test RED on a `.py` outside `plugins/`, GREEN inside; guard (c) unchanged-RED on production import |
| **C5** | `AccuracyMetric` + spec-from-declaration binding | unit: arithmetic on known vectors incl. ties/missing-id refusal; declared-JSON round-trip to `MetricSpec`; TIDMAD suites untouched |
| **C5b** | engine R3 trigger generalization (§2.5b): R3 on `task_eval_scope`, optional `validation_requested_rows`, explicit-scope-without-count fails loudly | 07a/07c suites UNCHANGED (regime-A parity); synthetic e2e gains the explicit-R3 case; both D14-1 parity oracles green |
| **C6** | gate runner + THE bounded real Gate-2 run (spec written into this ledger BEFORE the run; posture + evidence recorded after) | Gate-2 PASS per §2.6; evidence preserved under `/home/klz/Data/SIDEREIS_DATA/` |
| **C7** | fixture upgrade variants + STATUS/README/PROVENANCE sync + this ledger | pack tests green incl. the L1 rung UNCHANGED (B-07a-1 corpus rule); doc-sync rule satisfied |

Per-commit validation is targeted (#221); the full suite runs once via
exact-head CI at the single push of this PR's branch.

## 4. Test-layer ownership (parent §H applied)

UNIT: transform/probe parity, manifest arithmetic, reader materialization,
deliverable round-trip, metric arithmetic + refusal, governance re-scope,
census updates. GATE 1: **none** — no LLM-facing change (directive §12:
Gate 1 is not automatic; nothing here renders into prompts). GATE 2:
REQUIRED bounded once (C6) — real JPEGs, real training with real R2/R3,
real inference, real deliverable, real accuracy. CI: new files route through
the #221 selector (`execute_tools/` + `examples/` AREA_OWNERS rows).

## 5. Adversarial self-check (the parent's five traps + D14-2-specific)

* **Dual configuration authority?** The pets binding is constructed by the
  gate runner from ONE id; the transport argv stays parent-emitted-only
  (census test already forbids launcher carriage; the runner calls
  `bind_task_data_path` in-process — no argv at all).
* **Silent missing-binding → TIDMAD?** Impossible by the D14-1 truth table;
  additionally the Pets scope object is foreign to `TidmadTaskDataPath`
  (loud TypeError) — the C5 e2e negative already pins the class of failure.
* **Self-referential parity?** Probe-hash expectations live in the COMMITTED
  `execution.json`, generated once and pinned; the reader test READS them.
  The generator and the reader share the transform implementation — that is
  ONE authority (deliberate); what keeps it honest is the committed hash
  artifact + two-process double-run, so any drift in PIL/torch/env FAILS
  loudly rather than being regenerated away. `execution.json` is
  BYTE-IMMUTABLE for the life of the PR once committed.
* **Gate evidence before/after confusion?** Pets has no pre-relocation
  baseline (nothing existed); the single C6 gate is the track's FIRST
  executable evidence and says so — no pair claim is made.
* **TIDMAD-shaped abstraction?** The Pets scope is manifest-rows (not
  file→segments); the deliverable is a CSV of ids (not per-file HDF5); the
  metric has no per-file vector. Anything that would force TIDMAD vocabulary
  into the seam is a parent stop, not a workaround.
* **Task immutability**: semantics come verbatim from §22.9a; this design
  adds interpolation=bilinear and the CNN architecture — both EXPLICITLY
  delegated to D14 by the frozen text ("interpolation rule frozen by D14",
  "architecture chosen by the D14 design").

## 6. Ledger

(appended per commit during implementation)

### C1 — acquisition tool + images pin (landed 2026-08-18)

`tools/example_packs/fetch_oxford_iiit_pet.py`: pins as module constants
(the executable authority), verify-before-anything (an existing archive is
NEVER silently re-downloaded; mismatch names both digests and refuses),
`--no-download` offline mode, layout-checked extraction, and a hard refusal
of any `--dest` inside the repository (the pack's committed lifecycle).
7 offline unit tests (`tests/unit/examples/test_fetch_oxford_iiit_pet_tool.py`).

**Real acquisition evidence (this machine):**
`/home/klz/Data/OXFORD_IIIT_PET/` — `images.tar.gz` 791 918 971 bytes,
SHA-256 `67195c5e…` (first fetch 2026-08-18T20:04:03Z), MD5 cross-matches
torchvision's official resource pin (`5c4f3ee8…`) — an independent authority
in place of the second-full-fetch precedent; 7 390 JPEGs extracted.
`annotations.tar.gz` re-fetched THROUGH the tool → byte-identical to the
PR0 pin (`52425fb6…`) — the frozen pin independently re-verified. The tool's
idempotency proven live (second run: `[verified]` + `[skip-extract]`).

**Recorded deviations.** (1) The design's C1 row said the archive pin also
lands in `data/manifests/SHA256SUMS`; NOT done — that file is the identity
manifests' integrity list (dir-relative rows, parsed as such by the pack
test), and mixing archive pins in would overload its contract. Pins live in
the tool constants + `PROVENANCE.md`. (2) **OPERATOR ACTION NEEDED (one `rm`, this machine only):** a stray
IN-TREE partial download
(`examples/oxford_iiit_pet/data/raw/images.tar.gz`, ~102 MB, from the
corrected first acquisition attempt) remains untracked — four removal/move
attempts were denied, so no further deletion is attempted by this session.
While it exists, the pack's own governance guard
(`test_no_image_or_archive_bytes_under_the_pack`) is legitimately RED **on
this machine only** (the file is untracked, so CI and every other checkout
are unaffected). `rm examples/oxford_iiit_pet/data/raw/images.tar.gz`
restores local green; nothing references the file.

### C2 — execution manifest, frozen transform, gate subsets (landed 2026-08-18)

**Boundary shift, recorded:** the frozen transform lives in
`execute_tools/pets_data_path.py` FROM C2 (not C3) — the generator and the
runtime reader must share ONE authority from the first committed hash, so
the production module starts with `decode_and_transform` /
`transform_probe_sha256` + the frozen constants; scope/impl classes join at
C3. The generator is a SIBLING tooling module
(`tools/example_packs/oxford_iiit_pet_execution.py`) rather than an edit of
the frozen-CLI identity tool ("EXTENDED" read at package level).

Committed artifacts (BYTE-IMMUTABLE for the PR; pins hardcoded in
`test_pets_execution_manifest.py`): `execution.json`
(`b26ac875…` — rule fields + 37 class-covering probe hashes, first train
image per class) and `gate2_{train,validation,final}.csv`
(370 / 74 / 370 rows = 10/2/10 per class, first-N-per-class in the
committed manifest order; re-derivation reproduces them EXACTLY, order
included). Regeneration-stability proven live (byte-identical across two
generator runs, before/after a cosmetic `round()` cleanup).

**Validation:** 14 tests — pins; nested/class-covering/size-exact subsets +
exact re-derivation; the frozen transform on SYNTHETIC images (shape/dtype/
range, constant-color value mapping, portrait/landscape/square/extreme
aspect arithmetic, fail-closed missing file, double-hash determinism); and
the REAL-probe parity pair on this machine — committed probes reproduce in
THIS process and in A SECOND process (the two-process rule; skips with a
declared reason where the machine-local dataset is absent —
`SIDERIUS_PETS_DATA_DIR`). Examples suite: 100 passed (the one deselect is
the pre-recorded local-only stray-file guard). ruff clean.

### C3 — the Pets TaskDataPath (landed 2026-08-18)

`PetsItem`/`PetsScope` (rows only — WHICH data), `_PetsManifestDataset`
(lazy per-item decode; EXISTENCE of every named file verified at
construction, `ValidationScopeError` naming the first missing id),
`PetsTaskDataPath` (four methods: `train_portion<1.0` REFUSED;
`max_samples` deterministic prefix; deliverable = ONE sorted CSV via
`deliverable_name` — one naming rule, both directions; absent deliverable
reads as `{}` for scoreability — the TIDMAD C4 rationale), registered under
`"oxford_iiit_pet"` at import (inert until bound). The census token-surface
gains the module.

**Recorded reconciliations.** (1) §2.3's early "scope carries the images
root / transform params" phrasing vs the LATER §2.1 amendment: the
amendment governs — the root travels as `params.data_dir` (the seam's own
channel) and the transform stays CODE pinned by the committed probes; a
params copy in the scope would be a dead second channel. (2) "every id
decodable" at construction is discharged as: existence verified eagerly
(fail closed naming the id), decode errors raise loudly at first read — and
the R3 loop reads EVERY item each pass, so a corrupt file cannot survive a
validation pass silently; full eager decode at construction would double
every epoch's decode work for no additional failure coverage.

**Validation:** 35 passed — C3 suite (explicit-binding resolution to the
registered implementation; foreign-scope refusal; Amendment-1 pair shapes +
manifest-order preservation; portion refusal; prefix cap;
missing-id fail-closed; deliverable round-trip byte-exact + foreign-header
refusal + absent→`{}`; REAL probe hashes reproduced THROUGH
`training_dataset`) + the full census (surface grown) + both D14-1 seam
suites unchanged. ruff clean.

### C4 — reference plugin + governance re-scope (landed 2026-08-18)

`examples/oxford_iiit_pet/plugins/pets_reference_cnn.py`: the §2.4
architecture at default `hidden_channels=16` → **61 509 parameters**
(docstring corrected from the design's ~0.6 M estimate — smaller is better
for a bounded gate; architecture unchanged), forward
`[B,3,144,144]f32 → [B,37]f32` verified through the REAL loader mechanism
(`SIDERIUS_PLUGIN_DIRS` env — the same channel the gate runner uses; the
`extend_registries(models, configs)` argument form gives the tests
pollution-free fresh registries). `segmentation_size=144` carried as the
recorded inert engine-residue field.

**Governance re-scope (both restatement sites, one rule):** guard (b)
(`test_pack_governance`) and the 07b pack-pin restatement
(`test_step07b_pack_pins`) now allow `.py` ONLY at
`examples/<pack>/plugins/*.py` — sanctioned plugin SOURCE, loaded
dynamically; anything else under a pack is still an offender, and guard (c)
(production never imports `examples.*`) is untouched and absolute. Both
negative proofs updated (a `.py` outside `plugins/` is caught; one inside
is detected-and-sanctioned). Both pins' docstrings named D14 as their
relaxation owner — this is that relaxation.

**Validation:** examples suite **103 passed** (deselect = the pre-recorded
local-only stray-file guard) — plugin loader/forward/seeded-construction
tests, both re-scoped guards' positives + negatives, all pack pins. ruff
clean.

### C5 — AccuracyMetric + declared-spec rebinding (landed 2026-08-18)

`AccuracyMetric(EvaluationMetric)` — instance #2, task-agnostic arithmetic:
fraction of TRUTH ids matched (truth-denominated, so a partial deliverable's
missing prediction counts not-correct — exactly the declared aggregation);
`per_sample=None`; empty truth is a loud caller defect. Plus the ONE
sanctioned rebind for pack declarations:
`metric_spec_from_declaration` / `scoreability_contract_from_declaration` —
`MetricSpec.model_validate` cannot instantiate the ABSTRACT scoreability
field from plain JSON (verified: it raises), so the contract is rebuilt by
`contract_id` from the module's declared vocabulary
(`deliverable_presence` / `tidmad_denoised_h5`; unknown → fail closed naming
the vocabulary); everything else passes through the schema unchanged, and
the round-trip test proves the rebound spec re-serializes to the committed
declaration byte-for-byte. **Validation:** 54 passed — the new suite
(arithmetic incl. missing-prediction and empty-truth; scoreability-BEFORE-
arithmetic proven with poison kwargs; declaration round-trip; unknown-id
refusal) + ALL FOUR step06 suites unchanged.

### C5b — engine R3 trigger generalization (landed 2026-08-18)

Exactly §2.5b: the R3 machinery (histories, workload, verifier, per-epoch
pass) now arms on the GENERIC condition — `task_eval_scope is not None` —
via a shared tail after the two declaration legs; regime-A
(`eval_sample_set`) is byte-path-identical (same preflight, same clamp,
same assembly, its preflight OVERWRITES the count exactly as before). The
new `validation_requested_rows` engine parameter is the explicit leg's
caller declaration; both crosswise misuses REFUSE at startup (declared
count under regime-A = two authorities; explicit scope without a count =
silently unvalidated R3). **Validation:** 76 passed across 07a validation
pass / 07c envelope / 07c persistence-timing / workload envelope /
synthetic e2e / manifest parity — zero test edits in the 07a/07c suites;
the synthetic e2e GAINS the explicit-R3 positive (real R3 rows,
`requested == materialized == 3`, `comparability=established`) and the
missing-declaration negative (5/5).

### C6 (part 1) — Gate-2 spec (written BEFORE the run, directive §10)

**Claim.** At this head, the full Track-B loop runs REAL end-to-end through
the generic architecture: real official JPEGs → `PetsTaskDataPath`
(manifest reader, frozen transform) → the PRODUCTION
`run_experiment_streaming` under the Pets binding (real R2+R3 through the
07a machinery, C5b's explicit leg) → inference over the final-eval subset
through the SEAM reader → the classification deliverable (write + payload
read through the codec) → **accuracy through the Step-06 handle** bound to
the pack's DECLARED spec. This is the track's FIRST executable evidence —
no pre-existing baseline pair is claimed.

**Bounds (fixed BEFORE start, §17.0.1):** the COMMITTED `gate2_*.csv`
subsets — 370 train / 74 validation / 370 final (10/2/10 per class);
2 epochs, batch 32 (~24 optimizer steps/epoch); reference CNN 61 509
params; real GPU (cuda if available); ≤10 min with wide margin expected.
Command: `scripts/run_pets_gate2.py --data_dir
/home/klz/Data/OXFORD_IIIT_PET/images --workspace
/home/klz/Data/SIDEREIS_DATA/d14_pets_gate2_20260818`. In-process binding —
no transport argv, no launcher surface.

**PASS (functional, §17.0.1):** finite R2+R3 CE curves of length 2 accepted
by the `TrainingHistory` validators, `requested == materialized == 74`,
`comparability=established` · a deliverable whose payload covers the 370
final ids · a finite accuracy ∈ [0,1] from `AccuracyMetric` on the real
deliverable. Accuracy vs chance (1/37 ≈ 0.027) is recorded as an
OBSERVATION, not a pass condition. **Failure** = any stage absent or a
validator refusal; **inconclusive** = infrastructure-only interruption,
diagnosed before any rerun. Evidence persisted at the workspace
(`gate_evidence.json` + deliverable + model), never deleted.

### C6 (part 2) — Gate-2 post-run record: **PASS** (2026-08-18)

Run at `6cc47cb0` (the spec commit; the subsequent rebase onto d14-1's
pyright-cast fix — runtime no-ops — re-shas the branch without touching
gate-relevant behaviour), cuda, single process, evidence at
`/home/klz/Data/SIDEREIS_DATA/d14_pets_gate2_20260818/`
(`gate_evidence.json`, deliverable CSV + sha `cc847026…`, model, log).

* **Training (REAL, through the production engine under the Pets binding):**
  3.42 s · R2 = [3.6223, 3.6118] · R3 = [3.6109, 3.6107] (74 rows,
  requested == materialized, per-epoch pass ~0.24 s) ·
  `comparability=established` — the C5b explicit leg live in production
  code for the first time.
* **Inference through the seam reader:** 370/370 predictions, 0.70 s;
  deliverable written + payload read back through the codec.
* **Accuracy through the Step-06 handle** (spec = the pack's declaration):
  **0.027027 = EXACTLY 1/37 = chance.** The signature is unambiguous — a
  CONSTANT-prediction collapse (10 of 370 correct = one class's whole
  subset); CE ≈ ln 37 = 3.611 confirms the model is barely off
  initialization at this deliberately tiny budget (~24 steps/epoch × 2).
  The SAME phenomenon class the TIDMAD gate pair recorded
  (`failed_mode_collapse` on the 1-epoch stub arch) — a consistent,
  honest cross-track observation. Functional PASS per the frozen spec;
  quality was never a pass condition.
* **Wall:** ≈ 5 s end-to-end — far inside the ≤10 min bound.

Every stage of the parent's §4.2 required path executed REAL: official
pinned data → deterministic manifests → TaskDataPath → reference plugin →
training → validation → inference → deliverable → Step-06 handle →
accuracy. Track B is EXECUTABLE (L2→L3 evidence; STATUS rows move at C7).

### C7 — cumulative-corpus fixture upgrade + docs sync (landed 2026-08-18)

* **Real-component fixture pair ADDED, L1 pair KEPT verbatim** (§22.11a
  RULE): `expected/training_history_real_component_fixture.json` (the REAL
  gate run's TrainingHistory — real resolved `ce` fingerprint, real curves,
  74/74 rows, provenance block naming the gate commit and evidence path) +
  the hand-computed expected diagnosis (documented §3.6 formulas written
  out; matches the boundary at rel=1e-12 — independent validation of the
  arithmetic). The rung gains two tests: the real history through the SAME
  boundary (new input classes the L1 pair cannot exercise: both trends
  legitimately FLAT, a NEGATIVE final gap, epochs_planned=2) and the
  executable both-labels-present corpus check.
* **STATUS.md → L2/L3 EXECUTABLE** row-by-row (reader/plugin/gate-subsets
  LANDED with evidence pointers; the doc-pin tokens the maturity tests
  require all survive); `data/README.md`'s two deferred-to-D14 paragraphs
  now state the DECIDED mechanism (seam `data_dir`; fetch tool) and the
  landed preparation code.
* **FINDING (the PERMANENT separability guard fired).** The gate runner
  (production `scripts/`) imported `tools.example_packs…parse_manifest_csv`
  — §22.23.9 forbids production importing pack tooling, and the guard
  caught it on the C7 suite run. OWNERSHIP fix, not an exemption: the
  manifests are the task's scope authority, so
  `pets_data_path.load_pets_manifest` (header-checked, fail-closed) is the
  production parser; the runner uses it; a parity test pins production vs
  tooling parsing identical on a committed CSV (74 rows). Guard green.

**Validation:** 117 passed (examples suite incl. the extended rung + both
governance guards + parser parity; deselect = the pre-recorded local-only
stray-file guard). ruff clean.


### FINAL STATE — D14-2 (terminal closeout, 2026-08-18)

**Draft PR #231**, branch `d14-2-pets-executable`, head **`015699b0`**
(the last commit fixes four pyright sites the dispatched stack-head run
surfaced — see #233 for why this PR gets no CI of its own; the fixes are
runtime-neutral, proven by re-running the gate to **the identical
accuracy 0.0270**).

Acceptance, all met: official images SHA-pinned with an independent md5
cross-check, machine-local lifecycle honoured · frozen transform with a
committed 37-probe execution manifest, two-process determinism · reader,
codec and registration behind the seam · reference plugin through the real
plugin mechanism with the governance pins re-scoped exactly as they
assigned to D14 · accuracy as Step-06 instance #2, bound to the pack's OWN
declaration · **Gate-2 PASS** (real R2+R3, 370 predictions, accuracy
through the handle) · L1 fixtures kept, real-component variants added.

**Retained observation (operator ruling):** accuracy = 0.027 = chance, a
constant-prediction collapse at the deliberately tiny gate budget. NOT a
failure of D14 and deliberately NOT tuned away — it is evidence for Step 08
that a task can be fully executable while the candidate is unhealthy.
