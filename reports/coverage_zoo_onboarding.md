# Coverage zoo — measured onboarding records (issue #273; feeds `tab:coverage`)

**Claim evidenced**: declaration expressiveness + lifecycle execution only —
never discovery. Four task packages, each entirely **out of tree**, each
adding at least one NEW axis value (format / task mode / metric plugin /
direction) over the existing set {TIDMAD HDF5-denoising, LIGO
HDF5-regression, TESS Parquet-classification, Pets images-classification,
DAVIS video-regression}, each with a **measured** lifecycle run (real
training → real inference → real scoring → health disposition) and a
counted onboarding record. **Framework edits required: ZERO for all four**
(verified: `git status --porcelain` on the framework checkout is empty
after the whole campaign).

Also discharges the copyable-instantiation half of issue #283 for the
out-of-tree case: each package is a complete `cp -r`-able artifact
(manifest with all five required sections + optional sections, `file:`
plugins, declared metric with direction, health family or explicit
`none: true`, declared deliverable naming, per-package README walking the
register).

| provenance | value |
|---|---|
| packages + harness | `/home/yuema137/siderius-zoo/` — its own git repo, head `e286eacea08b5f34807de21384b3a4c165fe4f09`; ZERO files under any SIDERIUS checkout |
| framework under test | landed master `23276743` (worktree `arxiv/coverage-zoo` base; every run's evidence JSON records `framework_head 23276743…`) |
| run date | 2026-08-25 |
| environment pin | `PYTHONPATH=<checkout under test>` on every command — the venv's editable install points at a different checkout (verified hazard), so the pin is load-bearing and each evidence JSON records which checkout actually imported |
| LLM calls | **zero**, all four entries (see "Harness" for why the chain's fixed-plan route does not achieve this) |
| compute | CPU only (`--device cpu`); wall times 1.9 s – 16.2 s per entry |

## 1. The `tab:coverage` feed

| entry | format | task mode | metric (direction) | health | NEW axis value(s) admitted | onboarding required (content lines: declarations + plugins) | lifecycle result | wall |
|---|---|---|---|---|---|---|---|---|
| `california_housing_regression` | **CSV** tabular | tabular regression | `mae` (**lower**) | explicit `none` | CSV format; tabular-regression mode; `mae` metric plugin | **85 decl + 375 plugin** (raw 125 + 477) | `mae = 0.4417` (100k USD; train-mean predictor baseline 0.9253) | 6.2 s |
| `wine_classification` | **CSV** tabular | tabular classification | `macro_f1` (**higher**) | **task-owned family: 2 blocking gates** over the standard `categorical_predictions` view | CSV×classification combination; `macro_f1` metric family; out-of-tree Health family | **112 decl + 442 plugin** (raw 169 + 557) | `macro_f1 = 1.0` (majority-class baseline 0.2061); both blocking gates `passed → continue` | 2.3 s |
| `ett_forecasting` | CSV time series | **FORECASTING** (new mode) | `forecast_mse` (**lower**, raw OT units, truth derived from `data_dir`) | explicit `none` | forecasting mode; `forecast_mse` metric plugin consuming the scoring contract's third value | **94 decl + 414 plugin** (raw 123 + 513) | `forecast_mse = 3.8510` (last-value persistence baseline 4.9108 — the 23k-param reference model beats persistence) | 1.9 s |
| `fsdd_audio_classification` | **WAV audio** (8 kHz PCM16) | classification | `accuracy` (**higher**) | explicit `none` | WAV audio format (stdlib-`wave` task codec) | **88 decl + 332 plugin** (raw 117 + 420) | `accuracy = 0.70` (chance 0.10) | 16.2 s |

Line-count methodology: **content** = non-blank, non-comment lines
(docstrings in `.py` count as content); **raw** = `wc -l`. "declarations" =
`composition.yaml` + everything under `declared/` EXCEPT
`fixed_candidate_plan.json` (a chain-route convenience the measured run
does not consume; it is 33–35 lines and counted separately below).
"plugins" = every `plugins/*.py` file. The data prep scripts
(`data/prepare.py` / `data/fetch.py`, 46–95 content lines) are dataset
provenance tooling, not framework onboarding, and are itemized separately.

### Full counts by family (raw / content)

| entry | manifest | dataset profile | metric decl | task config | task health | data path plugin | metric plugin | model plugin | health views plugin | fixed plan | data prep |
|---|---|---|---|---|---|---|---|---|---|---|---|
| housing | 59/24 | 18/18 | 11/11 | 37/32 | — | 350/281 | 71/59 | 56/35 | — | 33/33 | 120/95 |
| wine | 52/24 | 18/18 | 11/11 | 36/33 | 52/26 | 335/273 | 88/73 | 53/34 | 81/62 | 33/33 | 105/82 |
| ett | 50/24 | 22/22 | 11/11 | 40/37 | — | 344/279 | 112/98 | 57/37 | — | 35/35 | 88/69 |
| fsdd | 49/24 | 22/22 | 11/11 | 35/31 | — | 298/241 | 56/45 | 66/46 | — | 35/35 | 59/46 |

The data-path plugin dominates every package (241–281 content lines), and
deliberately so: it carries the frozen four-method `TaskDataPath` codec,
the optional four-method `TaskScopeCapability`, the task's frozen
normalization/window constants, and fail-closed validation — the
`siderius-task-eventseq` one-file discipline (F-12e-C-1: no undeclared
runtime-loaded sibling modules, so the composition fingerprint pins
everything the semantics depend on).

## 2. The harness, and why this shape

`run_zoo_lifecycle.py` (zoo repo root, 340 lines) — ONE shared runner:

1. `workflows.task_composition.compose_run_task_bindings(manifest)` — the
   PRODUCTION composition authority resolves every declared family
   fail-closed (data path with seam-A config, dataset profile, metric
   declaration + implementation with the `IMPLEMENTS` discipline,
   secondaries, health binding, deliverable naming, model plugins with
   `require:` enforcement, objective) and computes the semantic
   fingerprint.
2. `bind_run_task_composition(comp, physical_data_root=--data_dir)` — the
   run-scoped activation the composed chain enters (Step 10 P1 / Step 11).
3. Scopes built by the task's OWN `TaskScopeCapability`
   (`build_training_scope` / `build_eval_scope` with a production
   `ScopeBuildRequest`), plus a serialize→deserialize canonical round-trip
   through the task's own codec.
4. REAL training through the production streaming engine
   (`execute_tools.train_engine_sandbox.run_experiment_streaming` with
   `sample_set=None`, `task_scope`/`task_eval_scope`, the declared
   `model_io`, and the 07a R2+R3 machinery — every run's
   `comparability="established"` and R3 rows exactly equal the eval scope).
5. REAL inference through the production generic inference unit
   (`execute_tools.generic_inference.run_generic_inference`), writing the
   deliverable under the DECLARED naming.
6. REAL scoring: `comp.metric.evaluate({0: deliverable},
   evaluation_payload=…, task_scope=…, data_dir=…)` — byte-for-byte the
   composed scoring child's calling vocabulary
   (`execute_tools/denoising_score_single.py`, task-owned route).
7. Health: the pack's declared family through the shared
   `scripts/_gate2_health_stage.run_health_stage` (state-C explicit
   binding, every selected gate persisted), or the recorded
   `EXPLICIT_NONE`.

**Mechanism decision (the task brief asked this to be argued).** The brief
nominated `--validation_fixed_candidate_plan`
(`sdsc_submission_scripts/run_one_iteration.py:137-230`) as "THE mechanism
for zero-LLM lifecycle runs". Reading the source says otherwise: that seam
bypasses the PROPOSER only — its own help text says "implement, validate,
trial, HealthGate, formal launch … all still run for real"; the
code-validator agent (`MLCodeValidatorAgent`) runs on EVERY implementation
attempt including a Branch-B plugin reuse
(`workflows/model_exploration.py`, the validate stage directly after the
Branch-B short-circuit); and the tuner's planner/reflector are real LLM
stages (07b: `plan(task_render, metric_spec)` fails closed). Empirically,
the quickstart pack's own bounded real-LLM chain runs (2026-08-25,
`examples/quickstart/README.md` §4-§5) burned their attempts without ever
reaching a scored record. So the zoo uses the LANDED zero-LLM
real-lifecycle precedent instead — the D14/08c Gate-2 evidence-harness
shape (`scripts/run_pets_gate2.py`, RETAINED by PR-12d as the
pack-vs-composition discriminator) — upgraded in exactly one way: nothing
is hand-bound; every family resolves through the production composition
authority. Each package still ships a schema-validated
`declared/fixed_candidate_plan.json` (verified against the production
loader: shas `946fad2c…`, `27971462…`, `03ded2f8…`, `aba2a9a1…`), so the
chain route with the proposer bypassed is one flag away — with its
remaining LLM stages recorded honestly.

**What these runs do NOT claim**: subprocess transport of the composed
task into training/inference/scoring children (owned by G-12d / G-12e
evidence on the shipped and eventseq packages), any LLM-facing behaviour,
and any model-quality benchmark.

## 3. Per-entry records

### 3.1 `california_housing_regression` — CSV tabular regression

* Data: California Housing (Pace & Barry 1997) via the ageron mirror CSV,
  upstream sha256 `8a3727f4…2a685e`; committed slice = 640 train / 160 eval
  rows drawn seeded (20260825) from the 20,433 complete rows, per-file
  pinned in `data/SHA256SUMS`; 8 raw numeric features, target in 100k USD.
* Command (from the zoo root, `PYTHONPATH=/home/yuema137/siderius-arxiv-zoo`):

  ```bash
  .venv/bin/python run_zoo_lifecycle.py \
      --manifest california_housing_regression/composition.yaml \
      --data_dir  california_housing_regression/data \
      --workspace runs/housing_v1 --epochs 25 --batch_size 32 --lr 3e-3
  ```

* Results: wall **6.15 s**; composition fingerprint `96126cb8397c…`;
  training 5.1 s (smooth_l1, R2 1.306→0.196, R3 final 0.168, 160/160
  validation rows, comparability established); deliverable
  `housing_predictions_housing_reference_mlp_zoo_zoo_001_0000.json`
  (sha `43e4c724d9b6…`); **`mae = 0.44174817471837996`** (direction
  lower); health `explicit_none`. Context: predicting the train-mean
  scores MAE 0.9253.

### 3.2 `wine_classification` — CSV classification + out-of-tree Health

* Data: UCI Wine (full 178 instances, 13 features, 3 cultivars), upstream
  sha256 `6be6b120…aea659`; committed seeded split 140 train / 38 eval
  (eval class counts 17/11/10), pinned in `data/SHA256SUMS`.
* Command: as above with
  `--manifest wine_classification/composition.yaml --data_dir
  wine_classification/data --workspace runs/wine_v1 --epochs 5
  --batch_size 16 --lr 1e-2`.
* Results: wall **2.28 s**; fingerprint `fd34580e3d0f…`; training 1.24 s
  (ce, R2 1.012→0.045, R3 final 0.072); deliverable
  `wine_predictions_…_0000.json` (sha `bcf914dcf986…`);
  **`macro_f1 = 1.0`** (direction higher — the dataset is famously
  separable; a real score over the 38 held-out rows, majority-class
  baseline 0.2061). **Health: the pack's TWO blocking gates evaluated the
  fresh deliverable through the framework-standard
  `categorical_predictions` view served by the pack's own provider
  (`wine.prediction_views`): `wine_distinct_symbols_blocking` passed,
  `wine_dominant_fraction_blocking` passed, resolved action `continue`;
  pinned effective-config sha `fa8f14bedaf719e0…`.** This is the state-C
  external binding route (explicit config path + `kind: file` plugin ref)
  — the same interface the in-tree Pets pack uses, exercised from outside
  the repository with zero SIDERIUS edits.

### 3.3 `ett_forecasting` — multivariate forecasting (NEW MODE)

* Data: ETTh1 (Zhou et al. 2021), upstream sha256 `f18de3ad…5ee066`;
  committed slice = the first 1200 hourly rows verbatim, pinned. Windows:
  48 h × 7 channels in → next 24 h of OT out; 139 training windows
  (stride 6, rows 0-900) and 10 evaluation windows (stride 24, rows
  900-1200) from disjoint regions, horizons included.
* Command: `--manifest ett_forecasting/composition.yaml --data_dir
  ett_forecasting/data --workspace runs/ett_v1 --epochs 3 --batch_size 16
  --lr 1e-3`.
* Results: wall **1.86 s**; fingerprint `73e252bcedc7…`; training 0.89 s
  (smooth_l1 in normalized space, R3 final 0.064); deliverable
  `ett_forecasts_…_0000.json` (sha `c2c0b6f4a976…`), denormalized to raw
  OT units by the task codec; **`forecast_mse = 3.8509876252304465`**
  (direction lower, raw units) — **better than the last-value persistence
  baseline 4.9108**. The metric derives truth from the corpus through the
  scoring vocabulary's `data_dir` (not the scope, not the deliverable),
  exercising the third value of the composed scoring contract; health
  `explicit_none`. `task_type: "forecasting"` — the free-form field
  carried the new mode with no framework enum to grow.

### 3.4 `fsdd_audio_classification` — WAV audio (NEW FORMAT)

* Data: Free Spoken Digit Dataset (CC BY-SA 4.0), committed subset = 100
  real recordings (`{digit}_jackson_{take}.wav`, 8 kHz mono PCM16,
  2776–6925 frames), per-file pinned in `data/SHA256SUMS` (988 KB;
  `data/fetch.py` re-derives with per-file verification). Takes 0-7 train
  (80 recordings), takes 8-9 evaluate (20).
* Command: `--manifest fsdd_audio_classification/composition.yaml
  --data_dir fsdd_audio_classification/data --workspace runs/fsdd_v1
  --epochs 80 --batch_size 8 --lr 3e-3`.
* Results: wall **16.22 s**; fingerprint `79ccac4da7d9…`; training 15.3 s
  (ce, R2 2.316→0.045 over 80 epochs); deliverable
  `fsdd_predictions_…_0000.json` (sha `0537fd441262…`);
  **`accuracy = 0.70`** vs chance 0.10 (direction higher); health
  `explicit_none`. Shakedown fact worth keeping: at 12 epochs the model
  is still exactly at chance (0.10) with the CE curve barely moving —
  recorded in the package plan's `known_failures`.

## 4. Findings (friction observed; ZERO framework edits made)

None of these blocked onboarding; each was absorbed inside the package or
the harness, and none required touching framework source. They are the
measured "sharp edges" of the current out-of-tree contract:

1. **A plugin model's config class must declare `model_type`.** The
   streaming engine resolves the model class from
   `model_cfg.model_type` (`train_engine_sandbox.py`); a config without
   the field fails with `AttributeError` at run start. The in-tree
   `pets_reference_cnn` and the eventseq plugin both carry it; the
   quickstart's config does NOT (its route always injects the type
   externally), so a copier starting from the quickstart pack hits this.
   One line per package.
2. **Axis roles are a closed enum** (`batch|temporal|class`): a first
   guess of `role: time` was refused at composition BY NAME with the
   legal values listed — the fail-closed declaration surface working
   exactly as designed (cost: one word).
3. **The Health policy config resolves relative to the CWD**
   (`configs/health_checks.yaml` inside
   `execute_tools/health_checks/config.py`): the in-tree Gate-2 runners
   are always launched from the checkout root, so an external harness
   must `chdir` there (or the stage fails with `FileNotFoundError`).
   Absorbed in the harness; a portability note for any future external
   runner.
4. **`task_declared_deliverable_name` resolves a MODULE-LEVEL
   `deliverable_name(request)` helper** in the data path's defining
   module (`execute_tools/task_data_path.py:974-994`). The quickstart
   implements naming as a class staticmethod with a different signature,
   which that resolver does not find (it silently falls back to returning
   the directory). The zoo packages define the module-level helper (the
   eventseq shape); copiers should too.
5. **The fixed-candidate-plan chain route is proposer-bypass, NOT
   zero-LLM** — the mechanism record in §2. Not a defect; a
   documentation-of-reality item, since the zoo brief described it as the
   zero-LLM mechanism.

## 5. Deliberately not done, with reasons

* **No chain-route (LLM) runs.** The zoo's compute discipline is zero LLM;
  the composed-chain claims are owned by G-12d/G-12e. The validated fixed
  plans make the proposer-bypassed chain launchable later without new
  artifacts.
* **No package-local pytest suites.** The eventseq graduation package
  ships a 64-test suite because it is 12e's Gate artifact; the zoo's claim
  is onboarding cost + lifecycle execution, and the measured lifecycle run
  is each package's witness. Adding suites would also distort the
  onboarding-cost numbers the table exists to report.
* **No in-tree copies of the packages.** The 12e precedent (PR #306)
  commits no external-package files into the repository — the package is
  its own repo and the design doc records its pinned head. Mirrored here:
  this report records the zoo repo head (`e286eace…`) and inlines the
  layout + manifests below.
* **WAV was admitted** (the brief allowed dropping it if the download was
  heavy): the FSDD subset is 100 raw files ≈ 1 MB, fetched in seconds and
  committed with per-file pins — no SpeechCommands-scale archive needed.
* **Larger slices / better models.** Minutes-scale CPU and
  reference-quality models are the brief; every score above is reported
  against an honest context baseline instead.

## 6. Package layout (the zoo repo at `e286eace`)

```text
siderius-zoo/                          (own git repo; zero files under SIDERIUS)
├── README.md                          # register + running instructions
├── run_zoo_lifecycle.py               # the shared zero-LLM harness (§2)
├── california_housing_regression/
│   ├── composition.yaml               # inlined in §7.1
│   ├── README.md
│   ├── declared/{dataset_profile.json, metric_mae.json, task_config.yaml,
│   │             fixed_candidate_plan.json}
│   ├── data/{prepare.py, train.csv, eval.csv, SHA256SUMS}
│   └── plugins/{_housing_task.py, _housing_metrics.py, housing_reference_mlp.py}
├── wine_classification/
│   ├── composition.yaml               # inlined in §7.2
│   ├── README.md
│   ├── declared/{dataset_profile.json, metric_macro_f1.json, task_config.yaml,
│   │             task_health.yaml, fixed_candidate_plan.json}
│   ├── data/{prepare.py, train.csv, eval.csv, SHA256SUMS}
│   └── plugins/{_wine_task.py, _wine_metrics.py, _wine_health_views.py,
│                wine_reference_mlp.py}
├── ett_forecasting/
│   ├── composition.yaml               # inlined in §7.3
│   ├── README.md
│   ├── declared/{dataset_profile.json, metric_forecast_mse.json,
│   │             task_config.yaml, fixed_candidate_plan.json}
│   ├── data/{prepare.py, ett_slice.csv, SHA256SUMS}
│   └── plugins/{_ett_task.py, _ett_metrics.py, ett_reference_forecaster.py}
└── fsdd_audio_classification/
    ├── composition.yaml               # inlined in §7.4
    ├── README.md
    ├── declared/{dataset_profile.json, metric_accuracy.json, task_config.yaml,
    │             fixed_candidate_plan.json}
    ├── data/{fetch.py, SHA256SUMS, recordings/*.wav (100 files)}
    └── plugins/{_fsdd_task.py, _fsdd_metrics.py, fsdd_reference_cnn.py}
```

Run evidence (gitignored `runs/`): each `runs/<entry>_v1/` holds the full
launch log, `zoo_lifecycle_evidence.json`, the deliverable, and the saved
model; wine additionally holds the pinned `health_checks_effective.yaml`.

## 7. The four manifests, verbatim

The manifest is the whole operator surface of a package; inlined so this
record is self-contained.

### 7.1 `california_housing_regression/composition.yaml`

```yaml
# california_housing_regression — the task composition manifest.
#
# THE OPERATOR ENTRYPOINT. Point SIDERIUS at this file and nothing else:
#
#     --task_composition /abs/path/to/california_housing_regression/composition.yaml \
#     --data_dir         /abs/path/to/california_housing_regression/data
#
# This package lives entirely OUTSIDE the SIDERIUS source tree (the
# siderius-task-eventseq / PR-12e graduation shape). Nothing under the
# SIDERIUS checkout names this task; every family below is reached by the
# SAME public mechanism the shipped packs use. Refs resolve against THIS
# file's directory, so the package composes identically wherever it is
# checked out.
#
# Coverage-zoo axis values this entry adds over the existing task set
# (issue #273 admission rule): FORMAT = CSV tabular; MODE = tabular
# regression; METRIC PLUGIN = mae (direction lower).

task_data_path:
  file: plugins/_housing_task.py
  symbol: HousingTaskDataPath
  id: california_housing_tabular
  # No seam-A `config:` mapping — the committed slice IS the corpus and its
  # role split (partition 0 trains, partition 1 evaluates) is a frozen fact
  # of the slice, so there is nothing for a manifest knob to say.

dataset_profile:
  config: declared/dataset_profile.json

metric:
  declaration: declared/metric_mae.json
  implementation:
    file: plugins/_housing_metrics.py
    symbol: HousingMaeMetric

# A NAMED absence (`EXPLICIT_NONE`), not an omission: saying nothing would be
# the LEGACY_OMITTED state that resolves TIDMAD's Health family.
task_health:
  none: true

interpretation_blocks:
  none: true

# Declared explicitly because the omitted state silently resolves the shipped
# TIDMAD naming template (the known hazard the task-package guide records).
deliverable:
  prefix: housing_predictions
  extension: ".json"
  index_width: 4

task_config:
  config: declared/task_config.yaml

# The task's model roster is its OWN plugin; `require:` makes the declaration
# fail closed (an unresolvable plugin is a named refusal at composition, not
# an empty directory).
model_plugins:
  dir: plugins
  require: [housing_reference_mlp]
```

### 7.2 `wine_classification/composition.yaml`

```yaml
# wine_classification — the task composition manifest.
#
# THE OPERATOR ENTRYPOINT. Point SIDERIUS at this file and nothing else:
#
#     --task_composition /abs/path/to/wine_classification/composition.yaml \
#     --data_dir         /abs/path/to/wine_classification/data
#
# This package lives entirely OUTSIDE the SIDERIUS source tree (the
# siderius-task-eventseq / PR-12e graduation shape). Refs resolve against
# THIS file's directory.
#
# Coverage-zoo axis values this entry adds over the existing task set
# (issue #273 admission rule): FORMAT = CSV tabular; the CSV x classification
# combination; METRIC PLUGIN FAMILY = macro_f1 (direction higher); and a
# task-owned out-of-tree HEALTH family over the framework-standard
# categorical_predictions view (state C, never a silently inherited roster).

task_data_path:
  file: plugins/_wine_task.py
  symbol: WineTaskDataPath
  id: uci_wine_tabular

dataset_profile:
  config: declared/dataset_profile.json

metric:
  declaration: declared/metric_macro_f1.json
  implementation:
    file: plugins/_wine_metrics.py
    symbol: WineMacroF1Metric

# The pack's OWN Health family — the EXTERNAL state-C binding (an explicit
# config path, never the omitted state that resolves TIDMAD's roster).
task_health:
  config: declared/task_health.yaml

interpretation_blocks:
  none: true

# Declared explicitly because the omitted state silently resolves the shipped
# TIDMAD naming template (the known hazard the task-package guide records).
deliverable:
  prefix: wine_predictions
  extension: ".json"
  index_width: 4

task_config:
  config: declared/task_config.yaml

model_plugins:
  dir: plugins
  require: [wine_reference_mlp]
```

### 7.3 `ett_forecasting/composition.yaml`

```yaml
# ett_forecasting — the task composition manifest.
#
# THE OPERATOR ENTRYPOINT. Point SIDERIUS at this file and nothing else:
#
#     --task_composition /abs/path/to/ett_forecasting/composition.yaml \
#     --data_dir         /abs/path/to/ett_forecasting/data
#
# This package lives entirely OUTSIDE the SIDERIUS source tree (the
# siderius-task-eventseq / PR-12e graduation shape). Refs resolve against
# THIS file's directory.
#
# Coverage-zoo axis values this entry adds over the existing task set
# (issue #273 admission rule): TASK MODE = multivariate FORECASTING (a new
# mode — every existing task is denoising, classification or single-step
# regression); FORMAT = CSV time series; METRIC PLUGIN = forecast_mse whose
# truth is derived from the corpus through the scoring vocabulary's
# `data_dir` (not from the scope, not from the deliverable).

task_data_path:
  file: plugins/_ett_task.py
  symbol: EttTaskDataPath
  id: ett_multivariate_forecast

dataset_profile:
  config: declared/dataset_profile.json

metric:
  declaration: declared/metric_forecast_mse.json
  implementation:
    file: plugins/_ett_metrics.py
    symbol: EttForecastMseMetric

# A NAMED absence (`EXPLICIT_NONE`), not an omission.
task_health:
  none: true

interpretation_blocks:
  none: true

deliverable:
  prefix: ett_forecasts
  extension: ".json"
  index_width: 4

task_config:
  config: declared/task_config.yaml

model_plugins:
  dir: plugins
  require: [ett_reference_forecaster]
```

### 7.4 `fsdd_audio_classification/composition.yaml`

```yaml
# fsdd_audio_classification — the task composition manifest.
#
# THE OPERATOR ENTRYPOINT. Point SIDERIUS at this file and nothing else:
#
#     --task_composition /abs/path/to/fsdd_audio_classification/composition.yaml \
#     --data_dir         /abs/path/to/fsdd_audio_classification/data
#
# This package lives entirely OUTSIDE the SIDERIUS source tree (the
# siderius-task-eventseq / PR-12e graduation shape). Refs resolve against
# THIS file's directory.
#
# Coverage-zoo axis value this entry adds over the existing task set
# (issue #273 admission rule): FORMAT = WAV audio (8 kHz 16-bit PCM,
# decoded by the task's own stdlib-`wave` codec) — no existing task reads
# audio. Mode (classification) and metric family (accuracy) already exist
# in the set; the format is the admission.

task_data_path:
  file: plugins/_fsdd_task.py
  symbol: FsddTaskDataPath
  id: fsdd_spoken_digits

dataset_profile:
  config: declared/dataset_profile.json

metric:
  declaration: declared/metric_accuracy.json
  implementation:
    file: plugins/_fsdd_metrics.py
    symbol: FsddAccuracyMetric

# A NAMED absence (`EXPLICIT_NONE`), not an omission.
task_health:
  none: true

interpretation_blocks:
  none: true

deliverable:
  prefix: fsdd_predictions
  extension: ".json"
  index_width: 4

task_config:
  config: declared/task_config.yaml

model_plugins:
  dir: plugins
  require: [fsdd_reference_cnn]
```
