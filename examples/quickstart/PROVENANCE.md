# PROVENANCE — `quickstart`

## Data

**Fully synthetic; no external source, no license constraints, no
downloads.** The dataset is DEFINED by the generator in
`plugins/_quickstart_task.py` and the pinned seed:

- generator: `generate_shard(shard)` — features `x ∈ R^4` drawn
  `Uniform(-1, 1)` from `numpy.random.default_rng((20260824, shard))`;
  label `1` iff `x0·x1 + sin(π·x2) > x3`; then 3% of labels flipped
  deterministically by the same stream (so a perfect classifier is
  impossible by construction and accuracy has honest headroom).
- extent: 4 shards × 64 rows × 4 features; roles: shards 0–1 train,
  2 validation, 3 final-eval.
- serialization: CSV, header `sample_id,x0,x1,x2,x3,label`, floats `%.8f`,
  LF endings — fixed formatting is what makes the bytes reproducible.
- identity: `declared/data_manifest.json` pins the per-shard sha256; the
  materializer regenerates and verifies before writing any bundle, and
  `tests/unit/examples/test_quickstart_pack.py::
  test_generator_is_deterministic_and_matches_the_committed_pins` re-derives
  them on every run.

No data files are committed anywhere in this pack.

## Declarations

- `declared/dataset_profile.json` — authored for this pack in the post-B2
  profile form (generic `partition_count` + opaque `topology`); loads
  through `execute_tools.dataset_config.load_dataset_profile` unchanged.
- `declared/metric_accuracy.json` — authored for this pack; same shape as
  `examples/oxford_iiit_pet/declared/metric_accuracy.json`, with this task's
  aggregation identity. The scoreability contract is the framework's
  `deliverable_presence` (the contract vocabulary is closed on this base).
- `declared/task_config.yaml` — authored for this pack (task description +
  structured `model_io` contract). Committed since PR-12d landed: governance
  guard (a) exempts exactly the task configs a shipped
  `configs/task_composition/*.yaml` binds, and
  `configs/task_composition/quickstart.yaml` binds this one. Pre-landing the
  same content was generated into the run bundle instead (pack history in
  the git log).

## Code

All plugin code in `plugins/` was written for this pack against the frozen
contracts it targets (originally base `c991d6f6`, updated for the landed
PR-12d source): `TaskDataPath`/`TaskScopeCapability`
(`execute_tools/task_data_path.py`), `EvaluationMetric`
(`execute_tools/evaluation_metric.py`), and the `PLUGIN_MODEL_TYPE`
model-plugin convention. The metric's calling vocabulary
(`evaluation_payload`/`task_scope`/`data_dir`) is the landed composed
scoring-child convention (`_pets_metrics.py`); the deliverable codec uses
the landed naming keyword (`input_identity`). The module-level naming adapter
used by generic inference reporting and the class-level adapter used by the
task writer delegate to one private naming authority. The deterministic
production-handoff witness exercises generic inference, persistence, decoding,
and the composed metric together and pins its external score to `37/64 =
0.578125`; it does not rewrite or upgrade the historical live-run evidence.

## Tutorial outputs

Every executed cell output in `quickstart.ipynb` was produced by running the
cell's own source on the landed post-PR-12d integration source (CPU only, no
LLM calls, no chain launch) — with four exceptions, three whose outputs come
from the REAL bounded live run and one recording a value that has since gone
stale:

- **§9 (launch)**: verbatim excerpts (trim points marked) of the
  FINAL-WITNESS launch log; **§8 and §10 (first cell)**: produced by
  running those cells' own source against the current pack / the
  final-witness workspace; **§12 (resume)**: verbatim guard refusal and
  the real `manifest_replacement` artifact from the earlier recovery leg.
- Live-run identity, four authorized launches on 2026-08-25, all README §4
  with `--llm_config llm_configs/certify_minimal.json` (sha256
  `db95bf02…`, every role gpt-4o-mini), workspaces + data + generated
  library under a session scratchpad outside the checkout, exit 0 each:
  1. Live-fix head `d9c8bff2` (branch `arxiv/quickstart-live-run`):
     initial arm, wall 1m56s, run_id
     `quickstart_v1-20260825T034146-793953` — ended `no_records` at the
     then-unfixed implementor test-template geometry (since fixed);
  2. same head, `--force_fresh` #258 recovery resume, wall 3m25s — the
     §12 replacement provenance;
  3. FINAL-WITNESS candidate `34907b0e` (branch
     `arxiv/quickstart-final-witness`, implementor fix + P1 landed):
     wall 3m53s, run_id `quickstart_v1-20260825T055108-1072411` —
     validation of generated models PASSED, REAL TRAINING witnessed
     (§9 excerpts), inference refused by this pack's pre-convention codec
     (fixed here, regression-tested), remaining attempts burned on the
     flagged focal-loss probe seam; `no_records`;
  4. the ONE sanctioned corrective relaunch after the codec fix
     (fingerprint moved `ede74e70…` → `9645c218…`), fresh workspace,
     wall 3m54s — every attempt refused pre-training (flagged focal seam
     + weak-model conv geometry on 4 features); `no_records`. No further
     launch taken.
  The §10 inspection cell reads launch 4's workspace; no scored record or
  deliverable exists in any workspace, and none is claimed.

- **FOURTH EXCEPTION — §10's two long hex values are STALE RUN ARTIFACTS,
  and deliberately not corrected.** The first cell of §10 prints, from
  launch 4's `run_invariants_lock.json`:

  ```
  task_composition_fingerprint : 9645c218f5a84b219beb23fba6c9afc2916bf89eea8924c0560e822ce96f5b7b
  model plugin pinned          : quickstart_reference_mlp  sha256 ca5544db561c81c5…
  ```

  Both were true OF LAUNCH 4. Neither matches the pack as committed today,
  for two separate reasons that should not be conflated:

  * the **plugin sha** moved because `plugins/quickstart_reference_mlp.py`
    was changed after launch 4 (Lane E / F10 + F11b: the config now declares
    `model_type`, the module declares `PLUGIN_OUTPUT_TYPE`, and `extra` is
    no longer `forbid`). Recomputed from the committed file it is now
    `60fde910197c…`;
  * the **fingerprint** was ALREADY drifted from `9645c218…` before that
    change — independently reproduced at base `6b123947` — so its staleness
    is not attributable to the plugin edit alone.

  They are **not** hand-corrected here, and that is the point of this entry:
  they are a RECORD OF WHAT A REAL RUN OBSERVED. Editing them to values
  computed on a later tree would assert that launch 4 recorded something it
  did not — falsifying provenance in the opposite direction from the
  staleness it would hide. Re-deriving them honestly requires a NEW witness
  launch against the merged tree, which is tracked separately and is not
  part of this pack change.

  The §8 composition cell, by contrast, IS pure recomputation and has been
  re-derived from the committed pack (`60fde910197c…`, fingerprint
  `1330d3991a98c48b…`). A reader comparing §8 against §10 will therefore
  see them disagree; the disagreement is real, explained here, and the
  §8 values are the ones that describe the pack you have.

`quickstart.html` is a generated static rendering of the same notebook,
labelled as such, and section-heading-synced by test.
