# PR 2 — Expose Data Ordering as a Controlled Optimization Dimension

**Status**: rev 2 — P2-D APPROVED (operator, 2026-07-28) with
corrections applied; LOCKED for implementation. Do not expand the
design.
**Baseline**: `docs/design/v19_priorities.md` §2.0 PR 2 block + §2.9 + §1.3
**Date**: 2026-07-28
**Branch (planned)**: `feat/v19-pr2-data-ordering`

## Development principles

Same as PR 1: design-doc-first; stop-and-show before every commit;
checkboxes tick only with recorded evidence; cold-start for any
real-training gate run (standing rule); no raw LLM/operator input
reaches execution without Pydantic validation; the frozen TIDMAD score
formula is untouched.

## 0. Implementation progress

Tick discipline (baseline §2.0): a stage is ticked `[x]` only after
its implementation commits exist and its verification checklist is
green with recorded evidence.

```text
[x] P2-A  — pre-design code audit (this doc §2; two code-traced audits
            2026-07-28: config-plumbing chain + RT2 workload coupling)
[x] P2-D  — design approved by operator (2026-07-28, rev 2: all five
            §3.0 decisions resolved — D1 order ≠ partitioning
            [operator ruling verbatim], D2 shuffle-within-file, D3
            operator-only, D4a pure permutation / global drop_last,
            D5 file_order = FULL permutation of resolved scope; plus
            parity-wording correction. Doc locked; do not expand.)
[ ] P2-CA — commit A: minimal indexed-dataset seam + genericity
            contract doc + TIDMAD coupling ledger + second-dataset
            contract tests (baseline §1.3 artifacts)
[ ] P2-CB — commit B: ordering implementation (order_strategy +
            file_order schema, engine support, propagation, RT2
            accounting, tests)
[ ] P2-V1 — pre-gate sweep: targeted unit + pseudo integration
            (default-parity + exact-visitation both deterministic)
[ ] P2-V2 — Gate 2: bounded real smoke (cold-start, per the standing
            rule; launch plan requires operator approval)
[ ] P2-S  — stop-and-show; implementation PR merged (default remains
            "shuffle"; no strategy recommendation implied)
[ ] P2-E  — matched-budget empirical strategy evaluation (separate
            operator-approved campaign; top-level PR 2 completion
            requires its review — baseline §2.0 completion semantics)
[ ] P2-ACT — optional planner exposure / production-default change
            (separate evidence-based operator decisions)
```

Scope rule: P2-CA is bounded genericity work (baseline §1.3 —
in-passing, never big-bang). If commit A's audit reveals materially
larger scope than §3.2 describes, STOP and report before changing the
plan.

## 1. Problem statement and goal link

SIDERIUS has two data axes; only one exists as a settable concept.

- **Selection** (which files/segments are in play) — exists and is
  enforced in layers: DataScope, `snapshot`/`anchors`/`target`
  strategies, `train_portion`/`formal_*` subsampling.
- **Ordering** (the sequence in which selected data is visited during
  training) — does NOT exist. The production path hardcodes: per-epoch
  subsample → concatenate ALL scope files → global uniform shuffle.

Because ordering is hardcoded, it is unavailable as an optimization
dimension. The official TIDMAD FCNet procedure (sequential-per-file)
is evidence ordering MAY matter — not a reproduction target (baseline
§1.4). PR 2 exposes ordering as a controlled, comparable search
variable so SIDERIUS can determine **empirically** whether alternative
ordering strategies improve HealthGate-valid formal score. Sequential
ordering may be rejected or abandoned if it does not improve score.

## 2. Audit summary (2026-07-28, code-traced)

### 2.1 Current ordering behavior (first-hand read)

Production training data path, `execute_tools/train_engine_sandbox.py`:

- `TIDMADEpochDataset` (`:255-339`) is rebuilt **every epoch**. Its
  constructor iterates scope files in **sorted ascending** order
  (`sorted(sample_set.keys(), key=int)`, `:292`), subsamples
  `train_portion` of each file's scope segments via `rng.sample`
  (`:304-308`), and concatenates everything into two flat int8 arrays
  (`:325-330`). All scope files are memory-resident simultaneously.
- Ordering is then destroyed by `DataLoader(dataset,
  batch_size=..., shuffle=True, drop_last=True)` (`:593`) — the global
  uniform shuffle. Epoch seed: `base_seed + ep` (or frozen), `:583`.
- **Docstring drift (worse than §2.9 recorded)**: the
  `run_experiment_streaming` docstring (`:477-481`) claims "process
  one file at a time, never hold multiple files in RAM ... iterate
  through files in shuffled order" — false on BOTH counts (all files
  resident; construction iteration is sorted, not shuffled). Same
  drift at the `main()` call-site comment `:881` ("Streaming mode: one
  file at a time, memory-efficient"). PR 2 fixes this drift.
- `__getitem__` (`:335-339`) widens int8 → int16 (+128) per item; the
  per-batch H2D copy and dtype dispatch live in the epoch loop
  (`:687-694`).

### 2.2 Plumbing chain (agent-traced, verified signatures)

- `run_experiment_streaming` has exactly ONE production call site:
  `train_engine_sandbox.py:882-894` inside the subprocess `main()`,
  selected by `--sample_set_json`. Data-loading knobs at the
  subprocess boundary: `--train_portion`, `--freeze_subsample`
  (plumbed by NO caller — dead switch), `--train_base_seed`.
- `TrainConfig` (`ml_models/models_format_sandbox.py:451-466`)
  carries **no data-loading fields**. All data options travel
  out-of-band: CLI flags + the sample-set JSON. Ordering will follow
  the same out-of-band pattern (see §3.3) — it is a data-pipeline
  option, not a hyperparameter of the optimizer.
- Launcher: `core/sandbox_executor.py::TidmadSandbox.execute_training`
  (`:680-691`) writes validated config JSONs, validates the sample set
  at the boundary (`validate_sample_set(sample_set,
  scope=self.data_scope)`, `:763`), and appends `--train_portion` /
  `--train_base_seed` when not None (`:770-773`). The stub twin
  (`:1357-1369`) mirrors the signature for pseudo mode.
- Tuner: the LLM plan (`ExperimentPlan.with_defaults`,
  `ml_hyperparameter_tune_agent.py:2265`) → mode/strategy resolution
  (`_resolve_sample_set_cfg` `:729-777`; partial-scope snapshot
  normalization `:2289-2311`) → Pydantic `TrialConfig` (`:2357-2379`,
  persisted as `trial_config_{exp_id}.json` `:2431-2436`) →
  `active_params` (`:2447-2460`) → `training_skill` wrapper →
  `execute_training`. On formal rounds the planner's data fields are
  overridden by operator `formal_*` inputs (`:756-762`).
- Baseline: `scripts/run_comparison.py::run_baseline_trial`
  (`:307-410`) builds full-portion snapshot sample sets and calls
  `execute_training(..., train_portion=0.1, train_base_seed=42)`.
  The legacy `run_baseline` path (`:213-220`) bypasses streaming
  entirely (single-file `TIDMADDataset`).
- Sampling-strategy authority: `execute_tools/sample_set_builder.py`
  (`build_sample_set`, `:27-104`; `anchors`/`target` are hard errors
  under partial scope `:78-84`). Boundary validation:
  `execute_tools/scoring_utils.py::validate_sample_set` (`:276`).
- **Pre-existing seam, directly relevant to commit A**:
  `execute_tools/dataset_config.py::DatasetConfig` ALREADY declares
  `training_file_pattern` (`:37`) and `validation_file_pattern`
  (`:41`), but the loaders inline `f"abra_training_{i:04d}.h5"`
  anyway (`train_engine_sandbox.py:159, :294, :606, :906`). Commit A
  is largely "make the loaders consume the field that already exists".

### 2.3 RT2 runtime-control coupling (agent-traced, verified)

The coupling is **much deeper than baseline §2.9 point 3 recorded**,
and almost all of it attaches to the *memory model* (per-file
streaming), not to *ordering* itself:

1. Setup is modeled as ONE indivisible pass whose measurement IS its
   prediction (`core/runtime_control/session.py:263-288`,
   `unit="setup_pass"`, prediction error 0 by construction). The
   window closes on the epoch-0 dataset+loader build
   (`train_engine_sandbox.py:594-632`).
2. Training `unit_count` comes from the MATERIALIZED epoch-0 loader:
   `steps_per_epoch = len(loader)` × epochs (`:604`, `:621`). The
   pre-launch resolver mirrors this with a single GLOBAL
   `// batch_size` floor over the concatenated pool
   (`workload_resolvers.py:80-82`). Per-file loaders with
   `drop_last=True` change the floor to `Σ_f (n_f // batch_size)` —
   both producers would need the per-file form.
3. Per-epoch reconstruction is priced by an explicit additive term
   `(epochs-1) × epoch0_dataset_seconds`
   (`train_engine_sandbox.py:567`). **With `epochs=1` — the
   paper-spec default — this term is exactly 0**; per-file streaming
   would introduce `(n_files-1)` unpriced constructions with no
   signal. Correct per-file form: `(epochs × n_files − 1) ×
   mean_per_file_construction_seconds`.
4. Storage provenance assumes the setup read the whole scope
   (`scoped_bytes = n_psd_scoped × PSD_SEGMENT_LENGTH × 3`, `:611-616`).
   Under one-file setup reads, `classify_cache_state`
   (`provenance.py:178-186`, threshold 0.5) systematically reports
   `warm_page_cache` for genuinely cold reads — the exact failure
   mode pre-Gate finding F2 was written to avoid.
5. Verification timing brackets ONLY the optimizer step with CUDA
   sync (`train_engine_sandbox.py:682-706`); mid-epoch file loads
   would fall between timed steps — inside the recorded ACTUAL
   (`:736-740`) but invisible to unit-time measurement. The stored
   prior (`observation_store.py:155-174`, `actual_seconds ÷
   unit_count`) then conflates reconstruction into ms/step, and the
   calibration key (`observation_store.py:78-110`) has NO
   loader-mode field — post-change priors would silently collide with
   pre-change observations and push verifications into
   `verified_drift`.
6. The watchdog deadline is the live sum of component
   `predicted_seconds × safety` (`core/sandbox_executor.py:408-440`);
   any unpriced reconstruction cost tightens the deadline mid-flight
   → spurious kills.
7. The epoch-0-exhausted admission guard `decide_admission =
   epochs > 1` (`train_engine_sandbox.py:713-721`) is wrong when
   files remain within epoch 0; `verifier.feed()` after terminal
   raises (`adaptive.py:213-214`) so a per-file inner loop must not
   re-arm it.
8. Tests lock "exactly one dataset construction"
   (`test_rt2b_streaming_preamble.py:105, :119, :146, :165`).
9. Precedent for the fix shape if streaming is ever done: inference
   already amortizes per-file fixed costs into
   `extra_predicted_seconds` and records the workload via
   `record_phase_workload` before verification
   (`inference_single.py:328-386`; `session.py:363-371`).

**Audit conclusion**: visitation ORDER over the existing concatenated
dataset is RT2-neutral (same construction cost, same step count, same
setup window). The MEMORY model (true per-file streaming) is where all
nine coupling points live. This drives the central design decision
below.

## 3. Design

### 3.0 OPEN DECISIONS (operator must resolve before P2-D)

**Decision 1 — RESOLVED (operator, 2026-07-28): ordering semantics
and loader partitioning are independent concerns.** Operator ruling,
recorded verbatim as the governing principle for this PR:

> PR 2 changes only the order in which selected samples are visited.
> It does not require changing whether the data are materialized in
> one global loader or multiple per-file loaders. Any
> loader-partitioning or memory-streaming optimization is a separate
> follow-up and must be evaluated independently.

- Commit B therefore implements `sequential` as a deterministic index
  ordering over the EXISTING concatenated per-epoch dataset (custom
  `Sampler`/index permutation instead of `shuffle=True`). This is
  supported by the audit: visitation order alone touches none of the
  ≥9 RT2 assumption sites (§2.3), which all attach to partitioning.
- Peak-RAM reduction via true streaming is FU-P2-1 — a separate
  follow-up, evaluated independently on its own evidence; it is NOT
  contingent on the ordering study's outcome (independence cuts both
  ways).
- Consequence: the §2.9 "restore the streaming name / cut peak RAM
  from Σ files to max(file)" promise moves out of PR 2's scope. The
  docstring drift is fixed by making the docs match reality
  (concatenated), not by making reality match the docs.
- Corollary (supersedes this draft's rev-0 batch-boundary rule): PR 2
  must NOT introduce partitioning semantics through the back door.
  See Decision 4 — the earlier "batches never straddle file blocks /
  per-block drop_last floor" rule was motivated by equivalence with a
  future per-file loader, a motivation this ruling removes; the rule
  itself would change the step count, which IS a partitioning
  semantic.

**Decision 4 — RESOLVED (operator, 2026-07-28): option (a), pure
permutation.** One global loader; global `drop_last` behavior
preserved; batches may cross adjacent file boundaries. Acceptable
because PR 2 changes sample visitation order only and must not
introduce loader-partitioning semantics or change optimizer-step
count. The two candidate semantics considered:

- **(a) Pure permutation (proposed)**: one global
  `DataLoader(drop_last=True)` over the permuted index sequence;
  batches at a file boundary may contain samples from two adjacent
  files. Step count is IDENTICAL to `shuffle` for the same selection
  — the matched-budget comparison is exactly matched in optimizer
  steps, and ordering remains purely "the order in which selected
  samples are visited". Boundary mixing affects at most
  `(batch_size−1)` samples per file transition (zero when
  `batch_size=1`, the `TrainConfig` default).
- **(b) Per-block floor (REJECTED)**: batches never straddle file
  blocks; `drop_last` applied per block. Keeps every gradient step
  single-file (closer to the FCNet prior art) but changes the step
  count vs `shuffle` (`Σ_f (n_f // batch_size)` ≤ global floor),
  which weakens step-matched comparison AND constitutes a
  partitioning semantic inside an ordering PR.

**Decision 2 — RESOLVED (operator, 2026-07-28): shuffle within
file.** Under `sequential`, file order is fixed while samples within
each file are shuffled per epoch using the existing seed discipline
(`base_seed + ep`). A strict within-file mode is NOT offered in PR 2
(one variable at a time; addable later if evidence motivates it).

**Decision 3 — RESOLVED (operator, 2026-07-28): operator-only.**
Ordering is settable via `HyperparamTuningInput` + chain/CLI flags
only. It is NOT added to `ExperimentPlan`; the agent must not choose
it before the empirical study. Planner exposure, if later approved,
is a separate post-evidence decision per the §2.0 lifecycle and
follows the DataScope precedent (plan field + normalization +
recorded provenance).

**Decision 5 (operator correction, 2026-07-28) — `file_order` is a
FULL PERMUTATION of the resolved DataScope, never a subset.**
Ordering must not change selection. Example: resolved scope
`[4,5,6,7,8,9]` → `[4,6,5,9,7,8]` is valid; `[4,6,5]` is INVALID.
Validation requires: exactly the same file set as the resolved scope —
no missing files, no extra files, no duplicates; only the order may
differ. Enforced at the schema layer (startup error) and re-checked
at the engine boundary (§3.3).

### 3.1 Ordering semantics (commit B)

```text
order_strategy: "shuffle" | "sequential"   default "shuffle"
                                           (behavior unchanged from
                                           today)
file_order:     list[int] | None           sequential only; default
                                           None = ascending file
                                           index over the resolved
                                           scope; when given, MUST be
                                           a FULL PERMUTATION of the
                                           resolved scope (same set —
                                           no missing, no extra, no
                                           duplicates; Decision 5);
                                           illegal with
                                           order_strategy="shuffle"
```

- `shuffle` (default): existing behavior, unchanged —
  `DataLoader(shuffle=True)` over the concatenated dataset.
  **Default parity contract (operator wording, 2026-07-28)**: the
  default path preserves the same data selection, RNG behavior, and
  visited sample sequence as before the PR (verified by test). New
  provenance fields may make output artifacts differ — unrelated JSON
  files are NOT required to be byte-identical.
- `sequential`: the concatenated dataset is built exactly as today
  (same construction, same subsample RNG — selection is untouched);
  the DataLoader receives a deterministic index permutation that
  visits file blocks in `file_order` (or ascending) with segments
  shuffled within each file block per epoch (Decision 2), seeded by
  the same epoch-seed discipline (`base_seed + ep`).
- Batch boundary rule: per Decision 4 proposal (a) — one global
  `DataLoader(drop_last=True)` over the permuted sequence; boundary
  batches may mix two adjacent files. **Step count is identical to
  `shuffle` for the same selection**, so RT2's materialized workload
  (`len(loader)`) and the pre-launch resolver need NO strategy-aware
  arithmetic, and the matched-budget study compares equal optimizer
  steps by construction.
- Provenance: `order_strategy` + resolved `file_order` are stamped in
  the per-round record, `run_config_*.json`, and the trial config —
  same discipline as `trial_strategy`/`train_portion`.

### 3.2 Genericity seam (commit A — baseline §1.3 artifacts)

Bounded scope, defined here ONCE (guardrail 1):

1. **Genericity contract doc** `docs/design/genericity_contract.md`:
   defines the indexed-dataset contract — `file_index → (readable
   path, segment list)` resolved through `DatasetConfig`
   (`training_file_pattern` already exists at `dataset_config.py:37`)
   — plus the task-pack and metric seams as PLACEHOLDER sections
   (filled by the PRs that first touch them; baseline §1.3 rule that
   inventing a new abstraction requires updating this doc first).
2. **Path-template extraction**: loaders consume
   `DatasetConfig.training_file_pattern` instead of inlining
   `abra_training_{i:04d}.h5`. Audited sites:
   `train_engine_sandbox.py:159, :294, :606, :906`. (Other modules'
   inlined templates are LEDGER ENTRIES, not commit-A work — bounded
   in-passing rule.)
3. **Coupling ledger** `docs/design/tidmad_coupling_ledger.md`:
   grep-able inventory (template strings, `log_5.27`/`s_max`
   constants, TIDMAD-worded prompt fragments, 20-file/200-segment
   assumptions), each marked decoupled/remaining. Seeded from the
   audits; updated in-passing by every future PR.
4. **Second-dataset contract test**: a minimal synthetic
   `DatasetConfig` fixture (different pattern, file count, segment
   count) proving the loader construction path is
   dataset-config-driven. A seam without such a test is "renamed",
   not "generic" (guardrail 3).

Frozen exception (guardrail 4): the TIDMAD score formula and
`legacy_baseline_configs.json` are untouched.

### 3.3 Propagation path (commit B)

Ordering follows the established out-of-band data-option pattern
(§2.2), validated by Pydantic BEFORE execution at every entry:

```text
operator CLI (--order_strategy/--file_order; chain _chain_common.sh,
  run_one_iteration.py, run_comparison.py, tuner CLI)
  → HyperparamTuningInput (new validated fields; file_order must be a
    FULL PERMUTATION of the resolved DataScope — same file set, no
    missing, no extra, no duplicates (Decision 5) — enforced by
    validator at startup, same layer that validates
    health_gate_files ⊆ scope)
  → TrialConfig (new fields; single source of truth per round)
  → active_params → training_skill wrapper → execute_training
    (named params; stub twin mirrors)
  → subprocess CLI (--order_strategy/--file_order_json)
  → boundary validation in the engine: file_order is exactly a
    permutation of sample_set keys (constructive check next to
    validate_sample_set — DataScope layered-enforcement precedent;
    violation terminates, non-retryable)
```

No `ExperimentPlan` field in PR 2 (Decision 3). `freeze_subsample`
(dead switch, §2.2) is left as-is — removing it is out of scope.

### 3.4 RT2 accounting (commit B, minimal under Decisions 1+4a)

- No change to the setup window, reconstruction term, scoped bytes,
  step arithmetic, or verification loop — dataset construction and
  step count are both unchanged (Decision 1 + Decision 4a).
  `workload_resolvers.py` needs no strategy-aware arm. The only RT2
  delta is provenance: `order_strategy` recorded in the workload
  `detail` so observations remain attributable if ordering ever
  affects unit time.
- §12 error-ledger evidence: one entry comparing predicted vs actual
  under `sequential` in P2-V2 confirms the accounting holds (expected
  result: within existing tolerance, since only the visit permutation
  changed).

### 3.5 Docstring drift repair (commit B, in-passing)

`run_experiment_streaming` docstring (`:477-481`) and the `main()`
comment (`:881`) are rewritten to describe reality: per-epoch
concatenated dataset, ordering per `order_strategy`. The misleading
"streaming" name is NOT changed in PR 2 (rename = churn across
call sites and tests; noted in the coupling ledger instead).

## 4. Affected locations

| Area | Files |
|---|---|
| Commit A | `docs/design/genericity_contract.md` (new), `docs/design/tidmad_coupling_ledger.md` (new), `execute_tools/train_engine_sandbox.py` (template consumption), `execute_tools/dataset_config.py` (no schema change expected), new contract test |
| Commit B schema | `agent/schemas/hyperparam_tuning.py` (`HyperparamTuningInput`, `TrialConfig`, record provenance fields) |
| Commit B engine | `execute_tools/train_engine_sandbox.py` (sampler + boundary validation + docstrings), `execute_tools/workload_resolvers.py` |
| Commit B plumbing | `core/sandbox_executor.py` (execute_training + stub), `agent/skills/training_skill/wrapper.py`, `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py` (TrialConfig build + CLI), `scripts/run_comparison.py`, `sdsc_submission_scripts/run_one_iteration.py`, `sdsc_submission_scripts/_chain_common.sh` |
| Tests | new unit suites (ordering semantics, validation, parity), pseudo integration, resolver tests |

## 5. Scope and non-goals

- Training loader only. Eval/scoring order, `score_vector`,
  HealthGates, and the frozen score formula are untouched.
- Per-file optimizer re-initialization: NOT a V19 commitment
  (baseline §2.9).
- True per-file streaming / peak-RAM reduction: FU-P2-1, outside
  PR 2 (Decision 1, pending operator).
- Planner-selectable ordering: outside PR 2 (Decision 3, pending
  operator); lifecycle gate lives in the baseline §2.0 Delivery block.
- No change to the default: `shuffle` remains; parity contract (§3.1)
  verified — same selection, RNG behavior, and visited sequence.
- The empirical strategy evaluation (P2-E) is designed AFTER the
  implementation merges — its matched-budget campaign plan will be a
  separate section (§7.3) locked with operator approval.

## 6. Commit plan (detailed — locked at P2-D approval, 2026-07-28)

PR 1 tick discipline applies: an item is `[x]` only when implemented
AND its verification evidence is recorded (test names + counts in this
doc). Stop-and-show before every commit. Each commit is independently
revertible; later commits depend on earlier ones only in the order
listed.

### P2-CA — genericity seam (baseline §1.3 artifacts; zero behavior change)

*Plan*

- [ ] `docs/design/genericity_contract.md` (NEW): indexed-dataset
      contract — `file_index → (readable path, segment list)`
      resolved through `DatasetConfig` (`training_file_pattern`,
      `dataset_config.py:37`); task-pack and metric seams as
      PLACEHOLDER sections (filled by the PR that first touches
      them); the §1.3 rule that new abstractions require updating
      this doc first.
- [ ] `docs/design/tidmad_coupling_ledger.md` (NEW): grep-able
      inventory seeded from the P2-A audits (inlined
      `abra_training_{i:04d}.h5` sites, `log_5.27`/`s_max`
      constants, TIDMAD-worded prompt fragments,
      20-file/200-segment assumptions), each entry marked
      decoupled/remaining with file:line.
- [ ] `train_engine_sandbox.py` — replace the four inlined template
      sites (`:159`, `:294`, `:606`, `:906`) with
      `DatasetConfig.training_file_pattern` consumption (TIDMAD
      instance; no signature changes).
- [ ] Second-dataset contract test (NEW,
      `tests/unit/execute_tools/test_dataset_contract.py`): a
      synthetic `DatasetConfig` fixture (different pattern, file
      count, segment count) proving path construction is
      config-driven — guardrail 3 ("a seam without such a test is
      renamed, not generic").

*Validation*

- [ ] Path-resolution parity test: for every audited site, the
      resolved TIDMAD filename before == after (default behavior
      unchanged).
- [ ] Contract test green with the synthetic fixture.
- [ ] Targeted regression: existing `tests/unit/execute_tools` +
      `tests/unit/core/test_sandbox_executor.py` suites green.
- [ ] `ruff check` + `ruff format --check` clean on touched files.
- [ ] Frozen-exception audit: no diff in the score formula or
      `legacy_baseline_configs.json`.

### P2-CB1 — schema + validation (ordering fields, no engine change)

*Plan*

- [ ] `agent/schemas/hyperparam_tuning.py`:
      `order_strategy: Literal["shuffle", "sequential"] = "shuffle"`
      and `file_order: list[int] | None = None` on
      `HyperparamTuningInput` and `TrialConfig` (TrialConfig is the
      per-round single source of truth, mirroring
      `train_portion`).
- [ ] Full-permutation validator (Decision 5): `file_order` must
      equal the resolved DataScope as a SET (no missing, no extra,
      no duplicates; order free). Startup error at the
      `HyperparamTuningInput` layer — same layer as
      `health_gate_files ⊆ scope`. `file_order` without
      `order_strategy="sequential"` → schema error. `None` +
      `sequential` → resolved to ascending scope order, resolution
      recorded in provenance.
- [ ] `ExperimentRecord` provenance fields: `order_strategy`,
      `resolved_file_order` (the materialized permutation, never
      `None`), following the `trial_strategy` stamp pattern.
- [ ] `run_config_*.json` persistence of both fields (P1-C5 A4
      precedent).

*Validation*

- [ ] Unit tests (schema): valid full permutation accepted; subset
      rejected; missing-file rejected; extra/out-of-scope rejected;
      duplicate rejected; `file_order`+`shuffle` rejected; `None`+
      `sequential` → ascending default with provenance; DS8 partial
      scope — permutation validated against the RESOLVED scope.
- [ ] Provenance round-trip test (record → JSON → record).
- [ ] Targeted regression: `tests/unit/agent/tune_ml_hyperparam_agent`
      suite green.
- [ ] `ruff` clean.

### P2-CB2 — engine ordering + boundary validation + docstring repair

*Plan*

- [ ] `train_engine_sandbox.py`: `sequential` index permutation —
      per-file index blocks assembled in `file_order`, each block
      shuffled with the epoch RNG (`base_seed + ep` discipline,
      Decision 2), flattened, and passed to ONE global
      `DataLoader(sampler=..., drop_last=True)` (Decision 4a —
      global drop_last preserved, batches may cross file
      boundaries, step count unchanged). `shuffle` path untouched
      (`DataLoader(shuffle=True)`).
- [ ] Subprocess CLI: `--order_strategy` + `--file_order_json`
      (engine re-validates; never trusts the caller).
- [ ] Engine boundary validation: `file_order` is exactly a
      permutation of `sample_set` keys — violation terminates,
      non-retryable (DataScope layered-enforcement precedent).
- [ ] RT2 provenance: `order_strategy` added to the training
      workload `detail` (no arithmetic change — §3.4).
- [ ] Docstring drift repair: `run_experiment_streaming` docstring
      (`:477-481`) and `main()` comment (`:881`) rewritten to
      describe the per-epoch concatenated dataset + ordering per
      `order_strategy`.

*Validation*

- [ ] Default-parity test: unset / `"shuffle"` → same selection,
      same RNG behavior, same visited sample sequence as pre-PR
      code under a fixed seed (§3.1 parity contract).
- [ ] Exact-visitation test: scope `[4..9]`,
      `file_order=[4,6,5,9,7,8]` → flattened sequence equals the
      concatenation of per-file permutations in exactly that order.
- [ ] Step-count parity test: `len(loader)` equal across strategies
      for the same selection, across batch sizes (incl.
      `batch_size=1` and a boundary-mixing batch size).
- [ ] Epoch-reshuffle test: within-file permutation differs between
      epochs, deterministic per seed (`freeze` semantics untouched).
- [ ] Boundary-validation negative tests: permutation violations at
      the engine terminate non-retryably.
- [ ] RT2 non-regression: `test_rt2b_streaming_preamble.py` +
      `test_rt2c_training_verification.py` green unchanged
      (dataset-construction count still 1 per epoch; workload
      unit_count unchanged).
- [ ] `ruff` clean.

### P2-CB3 — propagation (operator surface end-to-end)

*Plan*

- [ ] `core/sandbox_executor.py::execute_training` — named
      `order_strategy`/`file_order` params, forwarded as CLI args;
      stub twin (`StubSandbox`) mirrors the signature.
- [ ] `agent/skills/training_skill/wrapper.py` — forward both fields.
- [ ] Tuner (`ml_hyperparameter_tune_agent.py`): TrialConfig build
      reads the operator fields (no `ExperimentPlan` involvement —
      Decision 3); CLI `--order_strategy`/`--file_order`;
      `input_dict` assembly.
- [ ] `scripts/run_comparison.py`: flags + forwarding to the tuner
      subprocess.
- [ ] `sdsc_submission_scripts/run_one_iteration.py` +
      `_chain_common.sh`: parse arm + forward-when-set (PR 1
      `--enable_chain_incumbent_formal_gates` pattern).

*Validation*

- [ ] Per-hop forwarding unit tests (sandbox call → CLI args; wrapper
      passthrough; tuner CLI → input schema).
- [ ] Pseudo integration test: a chain iteration with
      `sequential` + explicit permutation stamps
      `order_strategy`/`resolved_file_order` provenance end-to-end
      (records + run_config + manifest).
- [ ] Shell parity check for the chain-script arm (existing parity
      test pattern).
- [ ] Targeted regression: workflows + protocols + tune suites green.
- [ ] `ruff` clean.

### P2-V1 — pre-gate sweep (after CB3)

- [ ] Full targeted unit sweep across all four commits' suites, one
      run, counts recorded here.
- [ ] Pseudo integration: BOTH strategies deterministic end-to-end.
- [ ] Evidence recorded in this doc (§7.1 boxes ticked with test
      names + counts).

### P2-V2 — Gate 2 real smoke (operator-approved launch)

- [ ] Launch plan drafted at P2-V1 exit (cold-start standing rule;
      DS8-paired partial scope; smallest canonical config; explicit
      command shown for approval).
- [ ] One `sequential` attempt: visited order verified from the
      training log; RT2 §12 ledger entry within tolerance;
      HealthGate pipeline unaffected.
- [ ] Result + limitations recorded here (PASS/FAIL verbatim
      evidence, PR 1 §7 style).

## 7. Validation plan (maps to baseline §2.0 checkpoints)

### 7.1 Deterministic (blocking for P2-S)

- Default-parity: `order_strategy="shuffle"` (and unset) preserves
  the same data selection, RNG behavior, and visited sample sequence
  as pre-PR code under a fixed seed (parity contract, §3.1 — no
  byte-identity requirement on unrelated artifacts).
- Exact visitation: resolved scope `[4,5,6,7,8,9]` with
  `file_order=[4,6,5,9,7,8]` visits file blocks exactly in that
  order; within-file permutation matches the seeded expectation; the
  flattened index sequence is exactly the concatenation of the
  per-file permutations (Decision 4a: boundary batches may mix files;
  the SEQUENCE is what is asserted, not batch composition).
- Step-count parity: `sequential` and `shuffle` produce the same
  `len(loader)` for the same selection, across batch sizes.
- Permutation validation (Decision 5), each a distinct negative test:
  subset (`[4,6,5]` under scope `[4..9]`) → error; missing file →
  error; extra file (out-of-scope index) → error; duplicate → error;
  `file_order` with `order_strategy="shuffle"` → schema error; valid
  full permutation → accepted; `None` + `sequential` → ascending
  default resolution recorded in provenance. Partial-scope (DS8)
  interaction covered: the permutation is validated against the
  RESOLVED scope, whatever it is.
- Resolver parity: predicted step count == materialized `len(loader)`
  for both strategies (unchanged global floor).
- Resume/provenance: stamps round-trip through records,
  `run_config_*.json`, and the run-invariants lock unchanged.
- Second-dataset contract test (commit A).

### 7.2 P2-V2 real smoke (bounded, operator-approved launch)

Cold-start (standing rule), DS8-paired partial scope, smallest
canonical config; one `sequential` attempt proving: correct visited
order in the log, RT2 §12 ledger entry within tolerance, HealthGate
pipeline unaffected. Launch plan drafted for approval at P2-V1 exit.

### 7.3 P2-E empirical strategy evaluation (post-merge, separate)

Matched-budget `shuffle` vs `sequential` comparison on
HealthGate-valid formal score, valid-round rate, wall time, peak host
memory, runtime-prediction accuracy, and run-to-run stability —
designed and costed in a dedicated section after P2-S, per the
baseline's merge-vs-strategy-selection separation. No superiority
claim without score evidence; sequential may be rejected.

## 8. Follow-ups filed by this design

- **FU-P2-1** — loader partitioning / memory-streaming optimization
  (peak RAM Σ files → max(file)): the full §2.3 RT2 change surface,
  including a loader-mode calibration-key component and
  observation-store migration. Per the Decision-1 ruling this is an
  independent concern, evaluated on its own evidence — not gated on
  the ordering study's outcome.
- **FU-P2-2** — `freeze_subsample` dead switch: plumb or remove.
- **FU-P2-3** — "streaming" naming cleanup once (if) FU-P2-1 lands.
