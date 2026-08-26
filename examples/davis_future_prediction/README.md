# Example pack — `davis_future_prediction` (Track C: RGB 8→4 future-frame prediction)

The persistent SPATIOTEMPORAL / REGRESSION contrast track (roadmap
`docs/design/siderius_generic_framework_upgrade.md` §22.9 Track C, frozen
specification §22.9a, example-pack governance §22.23). Fixed by the task
immutability policy.

> **New here?** This is one of three example task packages that show what a
> SIDERIUS task looks like. Start with
> [what a task must provide](../../docs/concepts/task-package.md); see
> [supported tasks and current maturity](../../docs/concepts/supported-tasks.md)
> for how the three compare, and
> [your first run](../../docs/getting-started/first-run.md) for the
> framework-level tour this page specializes.
>
> **Maturity**: this pack ships one documented run command — see
> [Run it](#4-run-it) below — and since PR-12d's `G-12d` the composed
> production chain has executed this task end to end. `STATUS.md` is the
> maturity authority and records every seam honestly, including what that
> promotion deliberately does *not* claim; this README is the user journey,
> not the claim.
>
> This pack is also the clearest illustration that one formula can hold three
> lifecycle roles: MAE is the training objective, the validation history *and* a
> declared secondary metric, while MSE is the primary metric.

**Read this if you want the short version**: DAVIS is the pack whose primary
metric goes the other way. `mse` is **lower**-is-better, so "best" is the
*smallest* number you will see — which is exactly why this example exists.

## Task (frozen §22.9a) — a SIDERIUS-defined task on DAVIS frames

| aspect | value |
|---|---|
| dataset | DAVIS 2017 (Pont-Tuset et al. 2017), TrainVal 480p — official distribution, see `PROVENANCE.md` |
| task | **real-RGB FUTURE-FRAME PREDICTION** (NOT DAVIS's official segmentation benchmark): 8 context frames → next 4 frames, stride 1; segmentation masks are NOT used |
| input topology | float32 `[C, T, H, W] = [3, 8, 128, 224]`, values in [0, 1] — deterministic decode → fixed resize/crop to 128×224 (rule frozen by D14), NO augmentation / flip / random crop |
| target | float32 `[C, T, H, W] = [3, 4, 128, 224]` — dense multi-channel continuous tensor |
| training scope | the **60** official train sequences |
| validation scope | **15** of the 30 official val sequences (by sequence identity) |
| final-eval scope | the **other 15** official val sequences |
| identity | SEQUENCE-disjoint (never frame-level random splits: temporal leakage). **Clip identity `(sequence_name, start_frame)` — which windows materialize — is D14's in full** (operator decision, PR0 design review 2026-08-15) |
| training objective (R1) | MAE / L1 over the predicted future tensor |
| validation objective (R3) | mean validation MAE per epoch |
| training history (R2) | mean training MAE per epoch |
| golden metric (R4) | **MSE** over ALL predicted pixels × channels × future frames of the final-eval clips · direction LOWER · terminal — aggregation FROZEN as the global mean over clips × C × T × H × W (never an unequal mean-of-means) |
| optional | validation PSNR (checkpointed, data_range = 1.0); PSNR (higher, data_range = 1.0) and MAE (lower) as terminal secondaries — the same MAE computation is training objective, validation observation and terminal secondary (three lifecycle roles of one computation) |

---

## Quickstart

Six steps, in the order the boundary actually works: what ships in git, what
does not, how to get it, how to run, where the output lands, how to look at it.

### 1. What ships in this repository

Everything needed to **understand and bind** this task — and no data.

```text
declared/model_io_contract.json     this pack's OWN ModelIOContract:
                                    [B, 3, 8, 128, 224] float32 -> [B, 3, 4, 128, 224] float32
declared/metric_mse.json            this pack's OWN MetricSpec instances
declared/metric_psnr.json           (mse ↓ primary; psnr ↑ and mae ↓ observational secondaries)
declared/metric_mae.json
declared/dataset_profile.json       partition_count 60 + an OPAQUE DAVIS topology (clip identity,
                                    the frozen frame transform, temporal extents 8 in / 4 out)
                                    + anchor_selection_files / health_peek_files
declared/task_config.yaml           this pack's OWN task_description + prose forward_contract
declared/task_health.yaml           this pack's OWN Health family (one blocking dispersion gate)
plugins/davis_reference_predictor.py   reference model — Conv3d residual over the last context frame
plugins/davis_exact_l1_loss.py         the frozen exact-MAE objective (PLUGIN_LOSS_TYPE)
plugins/_davis_metrics.py              the pack's mse / psnr / mae implementations
plugins/_davis_health_views.py         the pack's Health view provider
data/manifests/sequences.csv        SEQUENCE identity — 60 train / 15 validation / 15 final
data/manifests/clips.csv            CLIP identity `(sequence_name, start_frame)` — 600 windows
data/manifests/gate2_*.csv          the committed bounded subsets a short run uses
data/manifests/execution.json       the decode/resize rule + 10 window probe hashes
data/manifests/SHA256SUMS           integrity / provenance pin
expected/*.json                     labelled L1 fixtures + real-component fixtures
quickstart.sh                       the ONE run command (step 4)
PROVENANCE.md · STATUS.md · data/README.md
```

`declared/` holds instance DECLARATIONS this pack owns (roadmap §22.23.1),
built through the REAL framework schemas (`agent/schemas/model_io_contract.py`,
`execute_tools/evaluation_metric.py`) and validated by
`tests/unit/examples/test_davis_future_prediction_pack.py`.

### 2. What does NOT ship — the external data dependency

The DAVIS 2017 **TrainVal 480p** archive (~833 MB), from the official
distribution at `https://davischallenge.org/davis2017/code.html`. Cloning
SIDERIUS downloads no dataset, and no raw frame is ever committed to git.

Licence terms were verified from primary sources and are pinned in
`PROVENANCE.md` (verdict: COMPATIBLE — RGB frames only; the CC BY 4.0
segmentation annotations are not consumed by this task).

### 3. Prepare the data

One command. It verifies the archive against the pinned SHA-256 **before**
anything else, extracts it, and then checks that every sequence named by the
frozen manifest is present with frames:

<!-- prepare-command -->
```bash
python -m tools.example_packs.fetch_davis \
    --dest /path/to/DAVIS_2017 --extract --check-layout
```

- `--dest` must be a **machine-local directory outside the checkout** — an
  in-tree destination is refused by name.
- If you already have the archive, add `--no-download`; the SHA-256 pin is
  still verified.

**Expected prepared layout.** After extraction the destination contains the
official tree, and `--dest` is exactly the path you pass as `--data_dir` in
step 4:

```text
/path/to/DAVIS_2017/
└── DAVIS/
    ├── JPEGImages/480p/<sequence_name>/00000.jpg …   ← the only input this task reads
    ├── Annotations/                                   ← segmentation masks, NOT used
    └── ImageSets/
```

**Which frames a run actually reads is selected by manifest, not by
you.** `configs/task_composition/davis.yaml` binds
`data/manifests/gate2_train.csv` as the training scope and
`data/manifests/gate2_validation.csv` as the evaluation scope, so a run reads a
committed, byte-pinned clip subset of what you downloaded. Bound the work
further with the portion knobs in step 4 — never with `--data_scope`, which is
refused by name for a task that does not declare TIDMAD's file topology.

### 4. Run it

<!-- quickstart-command -->
```bash
bash examples/davis_future_prediction/quickstart.sh \
    --workspace /path/to/your/workspace \
    --data_dir /path/to/DAVIS_2017
```

Add `--dry-run` to walk the chain and print the exact child commands with no
side effects. Do that first on an unfamiliar machine.

`quickstart.sh` is a **thin adapter**, not a second way to run anything. It
resolves the repository root from its own location, then invokes the normal
production launcher with this pack's manifest:

```text
examples/davis_future_prediction/quickstart.sh
  → sdsc_submission_scripts/run_chain.sh --task_composition configs/task_composition/davis.yaml
  → sdsc_submission_scripts/run_one_iteration.py
  → the same workflow, declarations and plugins that CI and the Gates exercise
```

That manifest is an **entrypoint POINTER** (Q-12d-1): it carries refs into this
pack and no second copy of any task semantics. Move the pack and the refs move
with it; change a threshold and you change it in exactly one place.

**Required, with no default on purpose.** `--workspace` (where the run writes)
and `--data_dir` (the root from step 3) are refused by name when missing. A
published quickstart must never require a path that exists on one machine.

**Bounded by default, and every bound is an ordinary chain flag.** The script
supplies `--mode lilab --num_iterations 1 --max_rounds 1 --max_epochs 1
--trial_portion 0.1 --formal_portion 0.1 --validation_max_samples 8`. Anything
you append is passed straight through and wins, because the launcher's parser
is last-wins:

*Why 0.1 for this pack.* The manifest already narrows the run to the committed
Gate subsets — 60 training clips and 15 evaluation clips — so `0.1` leaves ~6
training clips, and `--validation_max_samples 8` caps the evaluation leg at 8.
That is enough because this task's primary metric is a **global pixel mean**
over clips × C × T × H × W: eight clips is already ~2.75 M sampled values, so a
10% subset still yields a stable, comparable number. The cost per clip, on the
other hand, is high — twelve decoded RGB frames in and a dense
`[3, 4, 128, 224]` regression target out — which is what makes a small portion
the right default here. Packs bound themselves differently for their own
reasons; a classification pack, for instance, may pin `1.0` because a fraction
of a small image set leaves too few examples per class to mean anything. Raise
it when you want a real run, not a first run.

```bash
bash examples/davis_future_prediction/quickstart.sh \
    --workspace /path/to/your/workspace \
    --data_dir /path/to/DAVIS_2017 \
    --num_iterations 3 --max_rounds 2
```

`--trial_portion` / `--formal_portion` reach this task's own scope capability as
`ScopeBuildRequest.portion`, and `--validation_max_samples` as its `max_samples`
ceiling. They are task-agnostic framework knobs; nothing example-only was added
to make a short run possible.

**Two more flags the script supplies, and they are not bounds.**

`--start_iter 1` is a **correctness pin**. Auto-resume is on by default, and on
a workspace that already exists the launcher computes the starting iteration by
capturing the output of `scripts/inspect_run_state.py --next-iter` — a capture
that plugin-loader output can corrupt. When it does, the chain walks **zero**
iterations and still prints `CHAIN COMPLETE — N iterations` and exits `0`: a
silent no-op reported as success. Pinning `1` bypasses that, and it also turns a
re-run against a *non-empty* workspace into a loud refusal instead. Resuming a
real chain? Append `--start_iter N` — it wins.

`--llm_config llm_configs/openai_tiered_pro.json` pins **per-node LLM routing**.
Without it the chain falls back to one model for every node with no routing at
all, and nothing warns you. `llm_configs/deepseek_tiered_pro.json` ships as an
alternative; append `--llm_config <path>` to use it or your own.

**Prerequisites**: a CUDA GPU, an LLM API key configured as in
[installation](../../docs/getting-started/installation.md), and the prepared
data root from step 3. For the full argument list:

```bash
bash examples/davis_future_prediction/quickstart.sh --help
```

### 5. Where the output lands

Everything is under the `--workspace` you named:

```text
/path/to/your/workspace/
└── iter_001/                                        one directory per iteration
    ├── manifest.json                                this iteration's outcome
    └── iteration_001/<model_name>/
        └── run_output_iter_001.json                 the tuning record
```

`run_output_*.json` is the authoritative record — the training/validation
history, the primary `mse`, the observational `psnr` / `mae`, and the Health
verdicts. Alongside it the run writes, at startup, its invariants lock
(`run_invariants_lock.json`, pinning the resolved scope and health identity so
a later resume cannot silently change them) and the composed, pinned
`health_checks_effective.yaml`.

One honest caveat, recorded in `STATUS.md`: HealthGate evaluation still lives
only on the anchor-normalised scoring route, so a **composed** run fires zero
gates and persists `health_gate_results: []`. This pack's Health family is
demonstrated on a fresh deliverable through the D14 direct-execution runner,
and that claim is a runner claim.

### 6. Inspect the result

<!-- report-command -->
```bash
python -m tools.run_report --workspace /path/to/your/workspace --out /path/to/report
```

This renders the run's history and metric trajectories into a static report from
the persisted records — no re-execution, no server.

> **A caveat about the dashboard, and it matters most for this pack.** The
> Plotly dashboard (`dashboard/main.py`) has historically assumed
> higher-is-better in its client-side charting. This task's primary metric is
> **lower**-is-better, so a cumulative-best curve read there can point the wrong
> way. The static report above reads the run's own declared metric direction;
> prefer it.

### Is my run working?

There is a real reference number to compare against, and a trivial baseline that
tells a working run apart from a broken one. From the bounded direct-execution
evidence recorded in `STATUS.md`:

| | global MSE (lower is better) |
|---|---|
| reference predictor | **0.017290** |
| last-frame-copy baseline (predict frame *t* for every future frame) | 0.017392 |

A modest, real improvement over copying the last frame — that is all it is, and
it is not a benchmark result or a claim of scientific quality. What it is good
for: a number in that neighbourhood means decode, training, inference, scoring
and the metric handle all did their job; a number far above the baseline, or a
degenerate one, means something upstream is wrong.

---

## Launching a composed DAVIS run (Step 12 / PR-12d D6)

The runtime reads these declarations. The operator entrypoint is
`--task_composition configs/task_composition/davis.yaml`, which is what
`quickstart.sh` supplies for you; passing it to `run_chain.sh` yourself is the
same run.

That file is a POINTER (Q-12d-1): it carries refs into this pack and no second
copy of any task semantics. D6 added the two declarations it still needed —

```text
declared/dataset_profile.json   partition_count 60 (the gate2_train clip subset the
                                manifest binds) + an OPAQUE DAVIS topology (clip identity,
                                the frozen frame transform, temporal extents 8 in / 4 out)
                                + anchor_selection_files / health_peek_files
declared/task_config.yaml       this pack's OWN task_description + prose forward_contract
```

— and extended `data/manifests/SHA256SUMS` beyond `sequences.csv` to
`clips.csv` and the three `gate2_*.csv` the Gate actually reads (F-12d-5).

**Declared, and now executed.** This paragraph used to read *"Declared is not
executed. No composed DAVIS run has happened yet; that is `G-12d`'s, and
`STATUS.md` says so rather than claiming L4."* `G-12d` ran, and `STATUS.md`
promoted this pack to **L4** on that evidence — with the three things the
promotion does not claim named there. The stale sentence is superseded here
rather than left to contradict the authority it defers to.

## What the framework can / cannot do with this task today

See `STATUS.md` — it is the seam-by-seam record and the maturity authority.
In one line: every semantic family a composed run needs is declared and bound,
the composed chain has executed the task once, and the open items are the
Health-on-the-composed-route gap above plus the observational-only status of
the `psnr` / `mae` secondaries.

**There IS a launcher now** — see "Launching a composed DAVIS run" above. This
sentence used to read *"there is no launcher for this task yet — this pack
does not claim to run"*, which contradicted the section that documents the
composed entrypoint. Corrected at PR-12d D-FINAL: the launcher landed with
D6/D8a and the stale line survived directly above it. Since PR-12e that
entrypoint also has a published form — `quickstart.sh`, step 4.

## Running the pack's own tests

The pack is also a regression asset. Its guards are ordinary unit tests and
need no data, no GPU and no API key:

```bash
pytest tests/unit/examples -q
```

That is a **developer** check, not the way to use this example — the way to use
it is step 4.
