# Example pack — `oxford_iiit_pet` (Track B: 37-way RGB pet-breed classification)

The persistent IMAGE / CLASSIFICATION contrast track (roadmap
`docs/design/siderius_generic_framework_upgrade.md` §22.9 Track B, frozen
specification §22.9a, example-pack governance §22.23). Fixed by the task
immutability policy: not replaced because a Step is difficult, semantics not
modified to make an abstraction pass.

> **New here?** This is one of three example task packages that show what a
> SIDERIUS task looks like. Start with
> [what a task must provide](../../docs/concepts/task-package.md); see
> [supported tasks and current maturity](../../docs/concepts/supported-tasks.md)
> for how the three compare, and
> [your first run](../../docs/getting-started/first-run.md) for the framework
> tour this page assumes.
>
> **Maturity**: 🟡 real data, training, inference and scoring execute, and
> since PR-12d's `G-12d` they execute through the **composed production
> chain**, not only through the direct-execution evidence harness. `STATUS.md`
> is the maturity authority and records the seam-by-seam claim — including
> what that promotion deliberately does *not* claim.
>
> The measured accuracy (0.027 = chance for 37 classes) is a **real,
> reproducible constant-prediction collapse**, kept deliberately as health-gate
> evidence rather than tuned away.

---

## Quickstart

One command runs this task through the normal SIDERIUS production chain. The
steps below are the whole journey; nothing else is required, and no internal
test harness or Gate script is involved.

### 1. What the repository already ships

Everything needed to *understand* and *bind* this task is committed here — no
dataset is:

| shipped | what it is |
|---|---|
| `data/manifests/*.csv` + `SHA256SUMS` | identity manifests: which image belongs to which scope, and their integrity pins |
| `declared/` | this pack's own dataset profile, task config, model-IO contract and metric declarations |
| `plugins/` | the reference CNN, the metric implementations and the health-view provider |
| `../../configs/task_composition/pets.yaml` | the composition manifest that binds all of the above into a run |
| `quickstart.sh` | the thin adapter below |

### 2. What you must supply

The **Oxford-IIIT Pet images** (Parkhi, Vedaldi, Zisserman, Jawahar 2012 —
official VGG distribution, ~792 MB). Cloning SIDERIUS downloads no data, and
the framework never fetches any.

### 3. Prepare the data

```bash
.venv/bin/python -m tools.example_packs.fetch_oxford_iiit_pet \
    --dest /path/to/oxford-iiit-pet --extract
```

`--dest` must be a machine-local directory **outside the repository** — an
in-tree destination is refused. Both archives are verified against SHA-256
pins before anything is extracted; an existing archive is re-verified rather
than re-downloaded, and a mismatch fails closed naming both digests. Add
`--no-download` for offline verify-only. Provenance and the pinned digests:
`PROVENANCE.md`.

### 4. Where the prepared data goes, and which images the run uses

`--extract` produces `/path/to/oxford-iiit-pet/images/` (the JPEGs, named
`<image_id>.jpg`) and `/path/to/oxford-iiit-pet/annotations/`. **The images
directory is what you pass to the run** as `--data_dir`; the annotations are
provenance for the manifests and are not read at runtime.

Which images a run touches is decided by the **manifests, not by a scan of the
directory** (§22.9a: the manifest is the authority, the seed is provenance
only). The shipped composition binds this pack's *nested gate subsets* —
`gate2_train.csv` (370 images) and `gate2_validation.csv` (74) — so the
quickstart is bounded by construction. The frozen 3 669-image final-eval scope
is deliberately not bound by any composition, so no run can contaminate it.

### 5. Run it

```bash
bash examples/oxford_iiit_pet/quickstart.sh \
    --workspace /path/to/pets-quickstart-workspace \
    --data_dir /path/to/oxford-iiit-pet/images
```

That is the entire command. `quickstart.sh` is a thin adapter with no logic of
its own: it resolves the repository from its own location and execs the normal
production launcher, `sdsc_submission_scripts/run_chain.sh`, with
`--task_composition configs/task_composition/pets.yaml` and a set of small
bounded defaults (1 iteration, 1 round, 1 epoch, full portions over the 370/74
gate subsets). Every flag it passes is an ordinary production flag.

Both arguments are required and have no default — a workspace and a data root
are machine-local, and guessing either is how a published command becomes
unrunnable on every machine but one. Omitting one refuses immediately, by
name, instead of failing minutes later inside the composition root.

Any extra argument is passed straight through to `run_chain.sh` and, because
the chain's parser is last-wins, overrides the corresponding default:

```text
--dry-run                      print the exact child command; run nothing
--num_iterations 2             go deeper
--max_rounds 3                 more tuning rounds per iteration
--trial_portion 0.5            use half the bound training rows
--validation_max_samples 20    hard ceiling on the evaluation leg
--healthgate_mode observe_only record health verdicts without invalidating
--force_fresh                  reuse a non-empty workspace
--start_iter N                 resume at iteration N
bash examples/oxford_iiit_pet/quickstart.sh --help
```

Those portion and ceiling flags are the task-agnostic way to bound a composed
run: they become this task's own `ScopeBuildRequest`. `--data_scope` and
`--target_files` are **not** — the first is a TIDMAD partition-index concept
that a task declaring no TIDMAD topology refuses by name, and the second is a
chain-level no-op that is parsed and never forwarded.

An LLM key is needed, because a chain run plans and reflects with a real
model — see [installation](../../docs/getting-started/installation.md) for the
`.env` file. The quickstart defaults to `llm_configs/openai_tiered_pro.json`
(`OPENAI_API_KEY`); override with `--llm_config <file>`.

Try `--dry-run` first. It walks the chain and prints the exact child command
without side effects, which is also the fastest way to confirm your paths are
right.

### 6. What you should expect to see — including a failing health gate

**The reference model is an untrained stub, and this pack reproduces a real
constant-prediction collapse on purpose.** Expect:

- an accuracy near **0.027** — that is `1/37`, i.e. chance for 37 classes;
- the two blocking health gates declared in `declared/task_health.yaml` to
  **FAIL**: `pets_distinct_symbols_blocking` (fewer than 5 distinct predicted
  breeds) and `pets_dominant_fraction_blocking` (one breed predicted for more
  than 95 % of images);
- consequently an **invalidated round**.

That is the pack working, not a broken install. The collapse is preserved
Step-08 health evidence — reproduced bit-for-bit across three separate real
gate runs (`STATUS.md`) and pinned as a committed fixture-of-record at
`expected/d14_gate2_collapse_predictions.csv` (n = 370, 2 distinct breeds, one
of them predicted 369 times). It is kept, not tuned away, because a health
system that has never caught anything is not evidence that it works. If you
want to watch the run proceed past it anyway, pass
`--healthgate_mode observe_only`.

One honest caveat, recorded in `STATUS.md` and repeated here because it changes
what you will see: HealthGate evaluation still lives only on the
anchor-normalised scoring route, so a **composed** run fires zero gates and
persists `health_gate_results: []`. The gate verdicts above are what this
pack's Health family produces on a fresh deliverable through the D14
direct-execution runner.

### 7. Where the output lands

Everything is written under the `--workspace` you passed:

```text
<workspace>/iter_001/manifest.json      what this iteration did
<workspace>/iter_001/                   per-node output records, one JSON per node
                                        (the tuner's records carry the metric
                                        result, the health-gate verdicts and the
                                        training/validation history)
<workspace>/health_checks_effective.yaml  the composed health config actually used
<workspace>/run_invariants_lock.json      the pinned run identity
```

The classification deliverable itself is a CSV written by this pack's own
codec — `predictions_<model_type>_pets_quickstart_<exp_id>.csv`, header
`image_id,predicted_class_index` — beside the round that produced it, with a
probability sidecar next to it.

### 8. Inspect the results

```bash
python -m tools.run_report --workspace /path/to/pets-quickstart-workspace \
    --out /path/to/pets-quickstart-report
```

This renders the run's summary, the metric trajectory and the training /
validation history from the records above.

---

## Task (frozen §22.9a)

| aspect | value |
|---|---|
| dataset | Oxford-IIIT Pet (Parkhi, Vedaldi, Zisserman, Jawahar 2012) — official VGG distribution, see `PROVENANCE.md` |
| task | 37-way pet-BREED classification from real RGB JPEG images (~200 images/class); ROI / trimap annotations are NOT inputs |
| input topology | raw RGB JPEG, VARIABLE H/W → deterministic preprocessing: decode RGB (3 channels) → aspect-preserving resize, shorter side 160 px → center crop 144×144 → float32 `[3, 144, 144]` = pixel/255.0; NO augmentation (interpolation rule frozen by D14) |
| target | integer class id 0…36 (scalar categorical); `class_index = official CLASS-ID − 1`; the breed name is the image-id prefix (e.g. `Abyssinian_100` → class 0) |
| training scope | breed-stratified deterministic 80 % of the official trainval list — **2 946 images** |
| validation scope | the disjoint 20 % of the official trainval list — **734 images** |
| final-eval scope | the official test list only — **3 669 images** |
| training objective (R1) | categorical cross entropy |
| validation objective (R3) | mean validation cross entropy per epoch |
| training history (R2) | mean training cross entropy per epoch |
| golden metric (R4) | 37-class **accuracy** on the final-eval scope · direction HIGHER · terminal |
| optional | validation accuracy (checkpointed); **macro-F1** (higher, terminal); `log_loss` (lower, terminal — declarable since D16 closed, and DECLARED since PR-12d D5; not yet computable, see `STATUS.md`) |

## What this pack contains

```text
quickstart.sh                                 the ONE documented run command (§5 above)
data/manifests/{train,validation,final}.csv   IDENTITY manifests — image_id, class_index,
                                              official_class_id, scope (derived from the official
                                              annotation lists by the frozen rule in PROVENANCE.md)
data/manifests/gate2_*.csv                    the NESTED bounded subsets (370 / 74 / 370), first-N
                                              per class, strict subsets by construction
data/manifests/execution.json                 the frozen decode/resize/crop rule + 37 class-covering
                                              tensor probe hashes
data/manifests/SHA256SUMS                     integrity / provenance pins
data/README.md                                how to acquire the official data (nothing fetched here)
declared/dataset_profile.json                 generic dataset identity + this task's opaque topology
declared/task_config.yaml                     task description + forward contract
declared/model_io_contract.json               [B, 3, 144, 144] float32 -> [B, 37] float32
declared/metric_{accuracy,macro_f1,log_loss}.json   this pack's OWN MetricSpec instances
declared/task_health.yaml                     the task-owned Health family (two blocking gates)
plugins/pets_reference_cnn.py                 the reference model (61 509 params)
plugins/_pets_metrics.py                      accuracy / macro-F1 / log-loss implementations
plugins/_pets_health_views.py                 the `pets.prediction_views` provider
expected/                                     committed fixtures-of-record, including the real
                                              collapse predictions and the L1 history/diagnosis pairs
PROVENANCE.md · STATUS.md
```

**The manifests are the authority for which images belong to which scope**
(§22.9a: "the manifest is the authority, the seed is provenance only; the
three scopes are disjoint; runtime resampling is forbidden"). They were
derived by the frozen rule, from official metadata only, and pinned; a
regeneration is an explicit operator act with provenance
(`.venv/bin/python -m tools.example_packs.oxford_iiit_pet --annotations-dir <tmp>/annotations`).

`declared/` holds instance DECLARATIONS this pack owns (roadmap §22.23.1) —
built through the REAL framework schemas (`agent/schemas/model_io_contract.py`,
`execute_tools/evaluation_metric.py`) and validated by
`tests/unit/examples/test_oxford_iiit_pet_pack.py`. They are declarations this
pack authored, not snapshots projected out of a production authority; the
shipped composition manifest is what binds them to a run.

## What the framework can / cannot do with this task today

`STATUS.md` is the seam-by-seam record and the maturity authority. The two
limits that change how you should read a quickstart result:

- **evaluation is in-sample.** `PetsTaskDataPath` serves the composed run's
  evaluation scope from `gate2_validation.csv`, drawn from the same trainval
  pool as the bound training manifest. The frozen final-eval scope is never
  touched, so nothing is contaminated — but a quickstart accuracy is a
  plumbing observation, never a generalization claim.
- **the secondary metrics do not reach a report yet.** `macro_f1` and
  `log_loss` are declared and bound, but the composed scoring route evaluates
  the primary metric only. `STATUS.md` names the blockers.

**There IS a launcher now** — the composed entrypoint is
`--task_composition configs/task_composition/pets.yaml`. This sentence used
to read *"there is no launcher for this task yet — this pack does not claim
to run"*; corrected at PR-12d D-FINAL, where the claim was checked against
the shipped tree rather than carried forward. Since PR-12e that entrypoint
also has a published form: `quickstart.sh` supplies exactly that manifest to
`run_chain.sh` and adds no execution logic of its own.

## Related

- [What a task package must provide](../../docs/concepts/task-package.md)
- [Task composition reference](../../docs/reference/task-composition.md)
- [Entrypoints and CLI](../../docs/reference/entrypoints.md) — every flag
  `quickstart.sh` passes through
