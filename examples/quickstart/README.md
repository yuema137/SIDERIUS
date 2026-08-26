# `examples/quickstart/` — the minimal new-task onboarding example

The smallest useful first-user experience: a complete SIDERIUS **task
package** for a tiny synthetic problem (binary classification of 4-feature
vectors, 256 rows, seeded generator, CPU-only, no downloads), built to be
read in twenty minutes and adapted in an afternoon. The executable tutorial
is **`quickstart.ipynb`** (rendered read-only as `quickstart.html`); this
README is the boundary statement — what ships, what you prepare, what runs
today, and the one thing still pending.

Governance: this pack lives under the example-pack rules of the roadmap
(`docs/design/siderius_generic_framework_upgrade.md` §22.23; track context
§22.9a) and under `tests/unit/examples/test_pack_governance.py`. Its own
tests are `tests/unit/examples/test_quickstart_pack.py`. The task itself is
demonstration-only — **the tiny model does not need to train well, and no
scientific claim rides on it.**

---

## 1. Repo-shipped assets

| file | what it is |
|---|---|
| `quickstart.ipynb` | the executable tutorial (14 sections; every executed cell shows real output from the landed post-PR-12d source — the launch/artifact-inspection/resume sections carry verbatim excerpts from the 2026-08-25 bounded live run) |
| `quickstart.html` | self-contained static rendering of the notebook (kept in sync by test) |
| `declared/dataset_profile.json` | the dataset's generic identity (4 partitions, anchors `[0]`, health peeks `[0]`) + opaque `topology` (roles, generator identity) |
| `declared/task_config.yaml` | the task description + **structured `model_io` forward contract** (`[B,4] f32 → [B,2] f32`) — legitimate under governance guard (a) exactly because the shipped manifest binds it |
| `declared/metric_accuracy.json` | the primary metric declaration: `accuracy`, **higher** is better, `deliverable_presence` scoreability |
| `declared/data_manifest.json` | identity pins of the generated data (seed `20260824`, per-shard sha256) |
| `plugins/_quickstart_task.py` | the task's executable behaviour: seeded generator, `TaskDataPath` (4 methods), optional `TaskScopeCapability` (4 methods), data materializer |
| `plugins/_quickstart_metrics.py` | `QuickstartAccuracyMetric` — the metric implementation, in the composed scoring child's calling vocabulary |
| `plugins/quickstart_reference_mlp.py` | reference model plugin (`PLUGIN_MODEL_TYPE` / `PLUGIN_CONFIG_CLASS` / `PLUGIN_MODEL_CLASS`), `[B,4] f32 → [B,2] f32`, 114 parameters — routed into composed runs by the manifest's `model_plugins:` section |

**THE manifest ships at `configs/task_composition/quickstart.yaml`** (beside
`tidmad.yaml` / `pets.yaml` / `davis.yaml`): seam-A `config:`
(`train_shards`/`eval_shard` — plain values, so no `{ref: ...}` envelope is
needed; the envelope exists for path-valued config, see `pets.yaml`),
`model_plugins: {dir, require: [quickstart_reference_mlp]}`, health
`none: true` (a NAMED absence), and the declared `deliverable:` naming.

## 2. External data dependency

**None.** The dataset is synthetic and regenerated bit-identically from the
pinned seed; the materializer verifies every shard's sha256 against
`declared/data_manifest.json` and refuses to write a drifted bundle.

## 3. Preparation

From a SIDERIUS checkout, with the project venv — regenerate the DATA (the
only non-committed artifact):

```bash
cd examples/quickstart
../../.venv/bin/python -c "
from pathlib import Path
import importlib.util, sys, os
spec = importlib.util.spec_from_file_location('qs', 'plugins/_quickstart_task.py')
qs = importlib.util.module_from_spec(spec); sys.modules['qs'] = qs
spec.loader.exec_module(qs)
ws = Path(os.environ.get('SIDERIUS_QUICKSTART_WORKSPACE', str(Path.home() / 'siderius_quickstart_workspace')))
print(qs.materialize_run_bundle(Path.cwd(), ws))
"
```

(or just run notebook sections 2–3, which do the same). This writes
`data/shard_000{0..3}.csv` under the workspace.

## 4. Run command

Everything up to and including real chain TRAINING executes on the landed
source: the shipped manifest composes fail-closed (model plugins required
and content-pinned), every component crossing (scope construction, dataset
materialization, deliverable codec under the declared naming, metric
scoring) runs for real — notebook sections 5–8 and 10–11 show each with
real output — and the chain launch below (the operator surface from
`docs/guides/define-a-task.md`, step 10; bounded to 1 iteration × 1 round)
**was executed as the operator-authorized bounded live witness on
2026-08-25** (`--llm_config` swapped to `llm_configs/certify_minimal.json`
per §7 step 5 — plumbing, not intelligence). Witnessed live across the
authorized launches (notebook §9/§10/§12 carry the real outputs): the
composition + invariants lock, the cold-start propose→implement→validate
ladder passing a generated model through the contract-aware validator, the
tuner leg with typed structured-failure records, REAL TRAINING on the
pack's data inside the composed training child, the #258 recovery resume,
and the P1 generated-library provenance (`{root, source: env}`, promotion
outside the checkout). **No scored result exists yet**: the training
attempt's inference was refused by this pack's own pre-convention codec
(fixed here since, with a regression test), and the remaining attempts
were burned by a FLAGGED framework seam — the legacy focal-loss family is
geometry-incompatible with a `[B,2]`-logit contract and is not
contract-filtered for composed tasks — plus weak-certify-model
architecture choices. Expect a fresh-model chain on this task to be
budget-hungry until that seam lands. Start with `--dry-run` (prints every
child command, no side effects).

```bash
WS="${SIDERIUS_QUICKSTART_WORKSPACE:-$HOME/siderius_quickstart_workspace}"

bash sdsc_submission_scripts/run_chain.sh \
    --mode lilab \
    --workspace "$WS/chain" \
    --run_name quickstart_v1 \
    --num_iterations 1 \
    --max_rounds 1 \
    --task_composition configs/task_composition/quickstart.yaml \
    --data_dir "$WS/data" \
    --healthgate_mode blocking \
    --result_authority diagnostic \
    --llm_config llm_configs/openai_tiered_pro.json
```

Notes pinned to source: a composed run **requires** `--data_dir`
(`CompositionDataRootMissing` otherwise); omitting `--llm_config` silently
resolves a deprecated all-Gemini default, so never launch without it;
`--result_authority diagnostic` is the honest value for a workflow-mechanics
demo; and composed runs currently fire **zero health gates** (the A1
declared debt on the PR-12d ledger), so a passing run makes no
health-enforcement claim.

## 5. Expected outputs

- **Now (notebook, real):** a composed `RunTaskComposition` from the SHIPPED
  manifest — health `explicit_none`, `model_plugins` requiring
  `quickstart_reference_mlp`, THREE plugin content hashes pinned into the
  semantic fingerprint (task, metric, and the reference model); scopes of
  128 train / 64 eval rows; torch samples `[4] float32 → int64`; a
  deliverable named by the declared template
  (`quickstart_predictions_<model>_<run>_<exp>_0000.json`); metric outcomes
  `MetricResult 1.0` (oracle), `0.0` (all-wrong), and a structured
  `NotScoreableResult(completeness)` for a missing artifact.
- **From the live runs (witnessed 2026-08-25):** a chain workspace with
  `run_invariants_lock.json` carrying that run's composition fingerprint
  (`9645c218…`, pinning the three plugin content hashes; editing the codec
  had moved it `ede74e70…` → `9645c218…`, exactly as the fingerprint
  discipline promises). It is NOT equal to what §8 composes today — the
  pack's model plugin has changed since that run, and the fingerprint had
  already drifted before that; `PROVENANCE.md`'s fourth exception carries
  the attribution. The lock records what the run saw, which is the point of
  a lock. Also the task-owned
  `resolved_data_scope [0,1,2,3]`, the P1 `generated_library
  {root, source: env}` provenance with promoted capabilities landing under
  that root (the repo checkout byte-identical before/after),
  `health_checks_effective.yaml`, `iter_001/task_config_snapshot.yaml`,
  per-attempt proposal/implementor/validation records, a saved training
  checkpoint, the honest `no_records` manifests, and (on the recovery leg)
  the #258 replacement provenance. Still unwitnessed: a SCORED tuner
  record (`metric_result` for `accuracy`) and a persisted deliverable
  under the declared naming — the §4 batch blocked both.

## 6. The landed boundary (pinned by tests)

PR-12d landed and the pack's three pre-12d boundary pins flipped exactly as
designed; each row below is the RE-SCOPED landed pin in
`tests/unit/examples/test_quickstart_pack.py`, with a non-vacuity plant.

| landed behaviour | pin |
|---|---|
| `model_plugins:` composes; `require:` is enforced (a missing type REFUSES at composition, by name) | `test_landed_pin_model_plugins_section_composes_and_requires` |
| a composed non-TIDMAD `model_io:` task config composes (F-12d-4 fixed); the contradiction check is still alive | `test_landed_pin_model_io_task_config_composes_f12d4_fixed` |
| unknown SECTION keys refuse by name (`configs:` for `config:`), and the seam-A `config:` mapping REACHES the constructor (counterfactual `train_shards: [0]` → scope over shard 0) | `test_landed_pin_section_keys_refused_and_config_reaches_constructor` |

A fourth landed pin from the live runs:
`test_deliverable_codec_accepts_the_composed_childs_positional_outputs`
regresses the 2026-08-25 batch item A — the codec now accepts the composed
inference child's positional outputs (seam C/B7) and still refuses a
mis-paired length (mutation-proven against the live failure).

Still true and worth knowing: composed runs fire zero health gates (A1
debt), and **the quickstart live chain runs happened on 2026-08-25** —
bounded 1×1 arms: the implementor-test-template debt from the first arm is
FIXED in the landed source (validation now passes generated models), REAL
TRAINING was witnessed on the final arm, and the scoring leg remains
unwitnessed behind the flagged focal-loss seam (§4).

## 7. After PR-12d lands (finalization checklist) — EXECUTED, all steps

Executed on the landed integration source (branch
`arxiv/quickstart-post12d`); evidence in the pack tests and the notebook:

1. ~~Re-run the pack tests; record which pins flipped~~ — all three flipped
   (3 failed / 10 passed on the landed tree), re-scoped as §6.
2. ~~Move the task config into `declared/task_config.yaml` with `model_io:`;
   add `configs/task_composition/quickstart.yaml` binding it; retire config
   generation from the materializer~~ — done; guard (a)'s manifest-bound
   exemption verified (`test_pack_satisfies_the_examples_governance_guards`
   asserts the file IS in the guard's bound set).
3. ~~Promote the post-12d manifest content; drop `SIDERIUS_PLUGIN_DIRS`~~ —
   done (the shipped manifest is THE manifest; §4's command has no export).
4. ~~Drop the `file_index` fallback~~ — done (`deliverable_name` calls the
   landed `input_identity` keyword only).
5. ~~The live bounded run~~ — **EXECUTED 2026-08-25** under explicit
   operator authorization, as bounded 1×1 arms with `--dry-run` first and
   `certify_minimal.json` throughout: the initial arm + the #258 recovery
   resume (first head), then the final-witness arm on the integrated
   candidate (implementor-geometry fix + P1) whose real outputs sections
   9–10 now carry, plus the ONE sanctioned corrective relaunch after this
   pack's codec fix. The `⏳ pending live-run authorization` markers are
   gone. Outcome, honestly: composition / lock / manifest / resume /
   validation-of-generated-models / REAL TRAINING / P1 library provenance
   all witnessed; a SCORED record and a persisted deliverable remain
   unwitnessed (§4 batch: pack codec fixed here; focal-loss seam flagged,
   framework-owned).
6. ~~Re-sync `quickstart.html`; update `STATUS.md` maturity~~ — done.

## 8. Adapt to your own task

Notebook section 14 maps every quickstart file to the corresponding step of
`docs/guides/define-a-task.md`. The short version: copy the pack's shape,
replace the science, commit your `task_config.yaml` (out-of-tree packages
are exempt from the `examples/` governance; in-tree packs bind it from a
shipped manifest), point every manifest section at your files, declare your
model plugins with `require:`, compose (the fail-closed refusals are your
checklist), launch bounded.

**One place where copying this pack's shape is the wrong move.** This pack
declares a `deliverable:` template in its manifest, so its `deliverable_name`
is an ordinary `@staticmethod` that its own codec calls — correct here, and
*not* a demonstration of the other route. If your task names its own artifacts
and you therefore omit `deliverable:`, the framework looks for a callable
`deliverable_name` **on the module**, not on the class
(`execute_tools/deliverable_spec.py::task_names_its_own_deliverables`). A
`@staticmethod` copied from here does not satisfy it. See
[step 7 of the task guide](../../docs/guides/define-a-task.md).
