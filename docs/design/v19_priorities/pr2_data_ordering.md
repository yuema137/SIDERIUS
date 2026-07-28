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

## 6. Commit plan (detailed — locked at P2-D approval, 2026-07-28; expanded per operator template same day)

PR 1 tick discipline applies: an item is `[x]` only when implemented
AND its verification evidence is recorded (test names + counts + wall
time in this doc). Stop-and-show before every commit: exact diff
summary, staged file list, tests run, and any deviation from this
design. Each commit is independently reviewable and revertible;
dependencies only in the order listed. Standing rules restated for
the implementer: ordering and loader partitioning remain separate
concerns; `file_order` is a full permutation of the resolved
DataScope; the default remains `shuffle`; planner exposure and
production-default changes are OUTSIDE these commits. If code
inspection during implementation reveals ambiguity or larger scope
than assumed here, STOP and ask before changing the plan.

### P2-CA — genericity seam (baseline §1.3 artifacts)

**Goal.** Make training-loader file-path construction dataset-config-
driven instead of inlined, and create the two §1.3 artifacts
(genericity contract, coupling ledger). This is its own commit
because it is pure refactor + docs with zero behavior change — mixing
it with the ordering feature would make the ordering diff
unreviewable and violate the §1.3 "own commit, skippable for urgent
fixes" rule. It precedes commit B because the ordering code touches
the same constructor.

**Scope.**
- Changes: `docs/design/genericity_contract.md` (NEW),
  `docs/design/tidmad_coupling_ledger.md` (NEW),
  `execute_tools/train_engine_sandbox.py` (four template sites:
  `:159` TIDMADDataset, `:294` TIDMADEpochDataset, `:606` RT2
  file-path list, `:906` legacy single-file main), one new test file.
- The pattern source already exists:
  `DatasetConfig.training_file_pattern` (default
  `"abra_training_{file_index:04d}.h5"`, `dataset_config.py:36-39`) —
  consumption via `pattern.format(file_index=...)`; note the audited
  sites use `{file_index:04d}`-equivalent f-strings, and the field's
  default already carries the format spec, so call sites pass the
  bare int.
- Non-goals / must-not-change: no signature changes; no behavior
  change (resolved TIDMAD paths identical); inference/scoring
  template sites are LEDGER ENTRIES only, not refactored here
  (bounded in-passing rule); the frozen score formula and
  `legacy_baseline_configs.json` untouched.
- Dependencies: none (first commit of the PR).

**Implementation plan.**
- [ ] Write `docs/design/genericity_contract.md`: indexed-dataset
      contract (`file_index → (readable path, segment list)` through
      `DatasetConfig`); task-pack + metric seams as PLACEHOLDER
      sections; §1.3 rule that new abstractions require updating
      this doc first.
- [ ] Write `docs/design/tidmad_coupling_ledger.md`: entries with
      file:line from the P2-A audits (inlined template sites incl.
      the non-training ones left in place, `log_5.27`/`s_max`
      constants, TIDMAD-worded prompt fragments, 20-file/200-segment
      assumptions), each marked decoupled/remaining.
- [ ] Refactor the four `train_engine_sandbox.py` sites to consume
      `TIDMAD.training_file_pattern`.
- [ ] Add `tests/unit/execute_tools/test_dataset_contract.py`:
      synthetic `DatasetConfig` fixture (different pattern, file
      count, segment count) driving dataset path construction.

**Validation plan.**
- Unit: path-resolution parity (per audited site, resolved TIDMAD
  filename before == after); contract test with the synthetic
  fixture (path built from the fixture's pattern, not the TIDMAD
  literal).
- Integration/pseudo: none required (no behavior change).
- Negative: pattern missing the `{file_index}` placeholder →
  `KeyError`/`IndexError` surfaced as a config error (test pins the
  failure mode).
- Backward-compat: targeted regression suites (below) green
  unchanged.
- Gate tests: none (docs + refactor only).

**Acceptance criteria.**
- For every file index in `range(TIDMAD.num_files)`, the refactored
  code resolves the character-identical filename the inlined
  f-strings produced (asserted, not eyeballed).
- The contract test constructs a dataset path from a NON-TIDMAD
  pattern without touching any TIDMAD literal.
- `git diff` contains no change to `score_vector`, the score
  formula, or `legacy_baseline_configs.json`.
- Both new docs exist and the ledger's "remaining" entries each carry
  a file:line.

**Failure and edge cases.**
- Malformed pattern (no placeholder): config error at first use —
  stop execution (a wrong pattern must never silently produce wrong
  paths).
- Missing file on disk: existing behavior preserved exactly
  (warning + skip, `train_engine_sandbox.py:295-297`) — this commit
  must not change it.

**Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools -q`
      (counts + wall time recorded here after run)
- [ ] `.venv/bin/python -m pytest tests/unit/core/test_sandbox_executor.py -q`
- [ ] `.venv/bin/ruff check` + `.venv/bin/ruff format --check` on
      touched files
- [ ] Any test not run: listed here with the reason — never claimed.

**Commit boundary.** Docs + template consumption + contract test
ONLY. No ordering code, no schema fields, no cleanup beyond the four
sites. Stop-and-show the diff summary + staged list + test evidence
before committing.

### P2-CB1 — ordering schema + validation (no engine change)

**Goal.** Introduce the validated ordering vocabulary
(`order_strategy`, `file_order`) at the schema layer, with the
Decision-5 full-permutation contract enforced before anything can
execute. Separate from the engine commit so schema semantics are
reviewable (and revertible) independently of loader mechanics.

**Scope.**
- Changes: `agent/schemas/hyperparam_tuning.py` —
  `HyperparamTuningInput`, `TrialConfig`, `ExperimentRecord`
  provenance fields, and `validate_runtime_config` (`:1573`);
  `run_config` persistence in the tuner (write-side only).
- Two-layer validation split (mirrors the existing DS8 pattern):
  dataset-INDEPENDENT checks in schema validators (duplicates,
  `file_order` without `sequential` — precedent: the
  `health_gate_files` validators at `hyperparam_tuning.py:1352-1359`);
  resolution-DEPENDENT checks in `validate_runtime_config`
  (full-permutation vs resolved scope — precedent: the partial-scope
  checks at `:1597-1623`; runs at tuner `run()` entry and workflow
  pre-flight, before any LLM call or file I/O).
- Non-goals / must-not-change: no engine behavior; no
  `ExperimentPlan` field (Decision 3); no propagation to CLIs yet;
  defaults leave every existing construction site valid unchanged.
- Dependencies: none strictly, but lands after P2-CA to keep the
  ladder linear.

**Implementation plan.**
- [ ] `order_strategy: Literal["shuffle", "sequential"] = "shuffle"`
      + `file_order: list[int] | None = None` on
      `HyperparamTuningInput`.
- [ ] Same fields on `TrialConfig` (per-round single source of
      truth, mirroring `train_portion`); model-validator: duplicates
      in `file_order` → error; `file_order` present with
      `order_strategy="shuffle"` → error.
- [ ] `validate_runtime_config`: when `order_strategy="sequential"`
      and `file_order` is not None, require
      `sorted(file_order) == resolved_scope` (full permutation —
      same set, no missing, no extra); when `file_order` is None,
      resolve to ascending `resolved_scope` (recorded, see next).
- [ ] `ExperimentRecord` provenance: `order_strategy`,
      `resolved_file_order` (materialized permutation, never None
      for executed rounds), following the `trial_strategy` stamp
      pattern (`:380-435` block).
- [ ] Persist both fields in `run_config_*.json` (P1-C5 A4
      precedent).

**Validation plan.**
- Unit (positive): valid full permutation accepted; `None` +
  `sequential` resolves to ascending scope with provenance recording
  the resolution; defaults (`shuffle`, `None`) accepted everywhere an
  input is constructed today.
- Unit (negative, one test each): subset (`[4,6,5]` under scope
  `[4..9]`); missing file; extra/out-of-scope file; duplicate;
  `file_order` + `shuffle`; empty list.
- DS8 interaction: permutation validated against the RESOLVED scope
  under a partial `--data_scope`.
- Backward-compat: existing suite for the schema module green with
  no fixture edits beyond additive fields.
- Integration/pseudo: none in this commit (fields are inert until
  CB2/CB3).
- Gate tests: none.

**Acceptance criteria.**
- Every input/fixture constructed without the new fields validates
  exactly as before (defaults are non-breaking) — demonstrated by
  the untouched existing suite passing.
- Each of the six invalid `file_order` shapes produces a distinct,
  message-bearing error naming the offending indices, at the layer
  specified above (schema vs `validate_runtime_config`) — asserted
  by layer, not just "raises".
- `resolved_file_order` in a persisted record equals the exact
  permutation execution will use (ascending default resolution
  included), round-tripped through JSON.

**Failure and edge cases.**
- Invalid permutations: stop at startup (operator config is a
  contract — DS8 precedent; no normalization, no warning-and-continue).
- Legacy configuration (records/run_configs without ordering
  fields): read paths must tolerate absence (`.get(default)` /
  optional fields) — pre-PR2 artifacts remain parseable.
- Resume: `order_strategy` is stamped per-iteration in `run_config`
  and provenance, but — mirroring `formal_strategy` treatment — it
  is NOT added to `run_invariants_lock.json` in PR 2. Consequence: a
  mid-chain operator flip of ordering between iterations is
  recordable and visible but not blocked. **Flagged to operator at
  the CB1 stop-and-show** (options: keep as-is like formal_strategy,
  or add to the lock later as a follow-up; not silently decided).

**Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/agent/tune_ml_hyperparam_agent -q`
      (counts + wall time recorded here)
- [ ] New-test file run in isolation (name recorded here)
- [ ] `ruff check` + `ruff format --check` on touched files
- [ ] Any test not run: listed with reason.

**Commit boundary.** Schema + validators + provenance + run_config
write-side ONLY. No engine code, no CLI flags, no forwarding. Stop-
and-show before commit.

### P2-CB2 — engine ordering + boundary validation + docstring repair

**Goal.** Implement the actual visitation-order mechanics in the
training engine, defended by its own boundary validation, and repair
the documented-vs-actual drift. This is the only commit that touches
the training loop, so its diff is exactly reviewable as "does the
loader visit what we said, in the order we said".

**Scope.**
- Changes: `execute_tools/train_engine_sandbox.py` only (ordering
  path in `run_experiment_streaming` around `:577-593`, new CLI args
  in `main()` `:770-826`, boundary validation helper, docstrings
  `:477-481` + `:881`), plus new unit tests.
- Non-goals / must-not-change: `TIDMADEpochDataset` construction
  (selection, subsample RNG, concatenation) — untouched; the
  `shuffle` branch — untouched (`DataLoader(shuffle=True)`, `:593`);
  RT2 setup window, reconstruction term, scoped bytes, step
  arithmetic, verification loop — all untouched (§3.4); ONE global
  loader with global `drop_last` (Decision 4a) — no per-file
  loaders, no partitioning semantics.
- Dependencies: P2-CB1 not strictly required (engine takes plain CLI
  values and re-validates), but the ladder lands CB1 first so the
  vocabulary is defined once.

**Implementation plan.**
*(Note: sampler mechanics below are the design intent; the
implementer inspects the epoch loop before finalizing the exact
DataLoader wiring — torch requires `shuffle=False` when a sampler is
passed, and the epoch-RNG plumbing must reuse `epoch_rng`/`epoch_seed`
at `:583-584`, not introduce a second seed path.)*
- [ ] Build the `sequential` index permutation: per-file index
      blocks in `file_order` order (dataset row ranges are derivable
      from the construction order — verify block offsets against the
      constructor's sorted-file iteration at `:292` before coding),
      each block shuffled with the epoch RNG (Decision 2), flattened.
- [ ] Pass the permutation to ONE global
      `DataLoader(..., drop_last=True)` via `sampler=`/`shuffle=False`;
      `shuffle` strategy keeps the existing `shuffle=True` call
      byte-for-byte.
- [ ] CLI: `--order_strategy` (default `"shuffle"`) +
      `--file_order_json` (path, mirroring `--sample_set_json`
      style); engine re-validates, never trusts the caller.
- [ ] Engine boundary validation: `file_order` is exactly a
      permutation of `sample_set` keys — violation prints a
      structured error and terminates non-retryably (DataScope
      layered-enforcement precedent).
- [ ] RT2 provenance: `order_strategy` added to the training
      workload `detail` dict (`:622-629`) — no arithmetic change.
- [ ] Docstring repair: `run_experiment_streaming` docstring and the
      `main()` call-site comment rewritten to describe reality
      (per-epoch concatenated dataset; ordering per
      `order_strategy`; "streaming" name retained, drift noted in
      the coupling ledger).

**Validation plan.**
- Unit (default parity — the four-part proof the operator requires):
  under a fixed seed, `order_strategy` unset/`"shuffle"` vs pre-PR
  code produces (1) the same selection (same subsampled segment
  sets), (2) the same RNG behavior (same `epoch_rng` consumption —
  subsample draws unchanged), (3) the same visited sample sequence,
  (4) the same step count. Implemented by capturing the visited
  index sequence from a small synthetic dataset, both before the
  change (recorded expectation) and after.
- Unit (exact visitation): scope `[4..9]`,
  `file_order=[4,6,5,9,7,8]` → the flattened visited sequence equals
  the concatenation of per-file permutations in exactly that block
  order — asserted on the actual iterated sample indices, not on the
  configuration value.
- Unit (step-count parity): `len(loader)` equal across both
  strategies for the same selection, at `batch_size=1` and at a
  batch size that forces a boundary-mixing batch.
- Unit (epoch reshuffle): within-file permutation differs across
  epochs and is deterministic per seed.
- Negative: each engine boundary-validation violation terminates
  with the structured error (subset/extra/duplicate vs sample_set
  keys); malformed `--file_order_json` (non-list, non-int) fails
  fast.
- Backward-compat: `test_rt2b_streaming_preamble.py` +
  `test_rt2c_training_verification.py` green UNCHANGED
  (dataset-construction count still 1 per epoch; workload
  `unit_count` unchanged).
- Gate tests: none in this commit (P2-V2 covers real training,
  separately approved).

**Acceptance criteria.**
- The visited SAMPLE sequence (not the config echo) is asserted for
  both strategies on synthetic data: sequential matches the
  constructed expectation exactly; shuffle matches the pre-PR
  recorded sequence exactly under the same seed.
- Step count identical across strategies for every tested
  (selection, batch_size) pair.
- Zero diff in RT2 observation content except the added
  `order_strategy` detail key (asserted on a captured sidecar).
- The two repaired docstrings no longer claim one-file-at-a-time
  residency or shuffled file iteration.

**Failure and edge cases.**
- Permutation mismatch vs `sample_set` keys at the engine: stop
  execution, non-retryable (defense in depth even though CB1
  validates upstream — the engine can be invoked directly).
- Missing file on disk (existing warning+skip, `:295-297`): the
  block for a skipped file is empty; the visited sequence is the
  concatenation of the REMAINING blocks in `file_order` order —
  warning, continue (preserves existing selection behavior;
  asserted by test).
- `file_order` given with `--order_strategy shuffle` at the engine
  CLI: error, stop (mirrors schema rule).
- Legacy invocation (no new flags): identical to pre-PR behavior —
  covered by the default-parity proof.

**Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools -q`
      (counts + wall time recorded here)
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools/test_rt2b_streaming_preamble.py tests/unit/execute_tools/test_rt2c_training_verification.py -q`
- [ ] `ruff check` + `ruff format --check` on touched files
- [ ] Any test not run: listed with reason.

**Commit boundary.** Engine + its tests + docstrings ONLY. No
schema, no propagation, no chain scripts, no unrelated engine
cleanup (`freeze_subsample` stays as-is — FU-P2-2). Stop-and-show
before commit.

### P2-CB3 — propagation (operator surface end-to-end)

**Goal.** Thread the two operator fields through every launch
surface (sandbox → skill wrapper → tuner → comparison script → chain
scripts) so a chain operator can actually set ordering, with
provenance stamped end-to-end. Last because it depends on both the
vocabulary (CB1) and the engine behavior (CB2).

**Scope.**
- Changes: `core/sandbox_executor.py` (`execute_training` `:680-691`
  + append-when-set block `:770-773`; stub twin `:1357-1369`),
  `agent/skills/training_skill/wrapper.py`,
  `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py`
  (TrialConfig build `:2357-2379`, `active_params` `:2447-2460`, CLI
  + `input_dict` `:4229-4584` region),
  `scripts/run_comparison.py` (agent-phase forwarding `:722-737`,
  CLI `:959-972` region),
  `sdsc_submission_scripts/run_one_iteration.py`,
  `sdsc_submission_scripts/_chain_common.sh` (parse arm +
  forward-when-set — PR 1 `--enable_chain_incumbent_formal_gates`
  pattern), plus tests.
- Non-goals / must-not-change: no `ExperimentPlan`/planner
  involvement (Decision 3); `run_baseline_trial` baseline behavior
  unchanged (no ordering flag on the baseline path — it is a frozen
  comparison anchor); defaults preserve today's behavior at every
  hop.
- Dependencies: P2-CB1 (schema) + P2-CB2 (engine).

**Implementation plan.**
- [ ] `execute_training`: named `order_strategy`/`file_order`
      params; write `file_order` JSON next to the sample-set file;
      append `--order_strategy`/`--file_order_json` when non-default;
      stub twin mirrors the signature.
- [ ] `training_skill` wrapper: forward both via `kwargs.get`.
- [ ] Tuner: `TrialConfig` build consumes
      `agent_input.order_strategy`/`.file_order` (operator fields —
      formal AND trial rounds use the same operator-set ordering; no
      per-round LLM influence); `active_params` carries them to the
      skill; CLI `--order_strategy`/`--file_order` + `input_dict`
      assembly + `validate_runtime_config` call already in place
      from CB1.
- [ ] `run_comparison.py`: CLI flags, forwarded to the tuner
      subprocess (agent phase only).
- [ ] Chain scripts: `ORDER_STRATEGY`/`FILE_ORDER` env-arg parse arm
      + forward-when-set.

**Validation plan.**
- Unit (per-hop forwarding): sandbox call → subprocess argv
  contains the flags exactly when non-default and never otherwise;
  wrapper passthrough; tuner CLI → input schema values.
- Pseudo integration: one chain iteration with `sequential` + an
  explicit permutation — `order_strategy`/`resolved_file_order`
  stamped in the round record, `run_config_*.json`, and the
  iteration manifest; a second run with defaults shows `shuffle`
  provenance and NO new flags in the training argv.
- Negative (propagation failure surface): a hop that drops the field
  is caught by the end-to-end pseudo assertion (stamped provenance
  must equal the operator input, not the default).
- Backward-compat: chain shell parity test (existing pattern) green;
  full targeted regression on workflows + protocols + tune suites.
- Gate tests: NONE launched from this commit. P2-V2 (real training)
  is listed separately in §0/§7.2 and requires explicit operator
  approval of a shown launch plan.

**Acceptance criteria.**
- With defaults, the training subprocess argv is IDENTICAL to
  pre-PR2 argv (asserted, not assumed) — the flags appear only when
  the operator sets non-default values.
- With `sequential` + explicit permutation, the provenance chain
  (record → run_config → manifest) carries the operator's exact
  permutation at every stage of the pseudo run.
- The stub sandbox accepts the same call signature as the real one
  (pseudo mode cannot drift).
- Shell parity: `_chain_common.sh` arm round-trips the values into
  `run_one_iteration.py` argv verbatim.

**Failure and edge cases.**
- Operator sets `file_order` without `sequential` anywhere on the
  surface: rejected at the earliest validated layer (schema) with
  the CB1 error — never silently ignored.
- Chain script arm set but iteration script older (skew): the PR 1
  forward-when-set pattern makes the flag absence a hard argparse
  error, not silent drop — verified by the parity test.
- Legacy resumes (pre-PR2 workspaces): absence of ordering fields in
  old records/manifests must not break resume reads (CB1 legacy
  rule re-verified at this level in the pseudo test).

**Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/workflows tests/unit/agent -q`
      (counts + wall time recorded here)
- [ ] `.venv/bin/python -m pytest tests/unit/scripts -q`
- [ ] Pseudo integration file run (name + counts recorded here)
- [ ] `ruff check` + `ruff format --check` on touched files
- [ ] Any test not run: listed with reason.

**Commit boundary.** Propagation + its tests ONLY. No engine or
schema changes (fixes discovered here go back to CB1/CB2 as
amendments, shown to operator). Stop-and-show before commit.

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
