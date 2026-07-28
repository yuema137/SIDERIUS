# PR 2 — Expose Data Ordering as a Controlled Optimization Dimension

**Status**: rev 3 — P2-D RE-APPROVED (operator, 2026-07-28; manifest
granularity clarification §3.7 applied; both judgment calls — split
[data_order] log, lock-the-override — approved). LOCKED for
implementation. Do not expand or polish further unless
implementation-time inspection reveals a concrete conflict.
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
[x] P2-D  — design RE-APPROVED (operator, 2026-07-28, rev 3).
            History: rev 2 approved 2026-07-28 (D1-D5); superseded
            same day by the proposal/override/resolution revision;
            re-approved with the §3.7 manifest granularity
            clarification (round-keyed provenance, no iteration-level
            collapse) and both judgment calls approved (split
            [data_order] log; lock the override, not the
            resolution). Decision state: D1/D2/D4a unchanged; D3
            replaced (agent-proposable + operator-overridable,
            precedence override > proposal > default); D5 two-stage
            validation. Doc LOCKED.
[x] P2-CA — commit A: minimal indexed-dataset seam + genericity
            contract doc + TIDMAD coupling ledger + second-dataset
            contract tests (baseline §1.3 artifacts)
            (split into CA-1 code 999727a + CA-2 docs; 20 new tests,
            26 + 49 + 75 green; one pre-existing unrelated lilab
            failure documented as FU-P2-4)
[ ] P2-CB — commit B (three sub-commits CB1/CB2/CB3, §6): ordering
            proposal/override/resolution schema + single resolver +
            chain-lock override fields; engine consumes resolved
            values only + [data_order] logs; end-to-end propagation
            incl. interpreter-visible resolved context; tests
[ ] P2-V1 — pre-gate sweep: targeted unit + pseudo integration
            (default-parity + exact-visitation both deterministic)
[ ] P2-V2 — Gate 2: bounded real smoke (cold-start, per the standing
            rule; launch plan requires operator approval)
[ ] P2-DOC — node/skill documentation sync (operator rule,
            2026-07-28): every node and skill touched by this PR has
            its .md updated — CLI arguments, default values, and
            behavior explanations current. Very last step before
            merge; see §6 P2-DOC block.
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

### 3.0 DECISIONS (rev 3 — D3 replaced, D5 clarified; re-approval pending)

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

**Decision 3 — REVISED (operator, 2026-07-28, rev 3; replaces the
rev-2 operator-only decision): agent-proposable + operator-
overridable, resolver-mediated.** Ordering is the first concrete
implementation of the project-wide configuration principle:

> Agents propose configuration. The execution system resolves
> configuration. Only resolved values describe what actually ran.

- The agent MAY propose `shuffle` or `sequential` (plus a file
  order) via `ExperimentPlan`.
- The operator MAY force one strategy for an entire chain via a
  chain-level override.
- The executed value is explicitly resolved with fixed precedence
  **operator override > agent proposal > default (`shuffle`)** by ONE
  resolver (§3.8); precedence logic is never duplicated across
  workflow, tuner, and engine.
- The agent proposal is intent, never execution truth; the engine
  consumes resolved values only; downstream interpretation attributes
  results to resolved values only (§3.9 invariant).
- Two supported chain modes: **forced comparison** (override set →
  every round resolves to the override; proposals recorded but not
  executed) and **agent exploration** (no override → proposal or
  default; may vary across rounds/iterations).
- PR 2 verifies correct information FLOW and RECORDING only. Any
  claim that the agent uses ordering intelligently, or that
  interpreter behavior improves, is an agent-behavior claim under
  the baseline §4 validation standard and is NOT made by this PR.

**Decision 5 (operator correction, 2026-07-28; rev-3 clarification
same day) — any sequential `file_order` must ULTIMATELY resolve to a
FULL PERMUTATION of the resolved DataScope, never a subset.**
Ordering must not change selection. Example: resolved scope
`[4,5,6,7,8,9]` → `[4,6,5,9,7,8]` is valid; `[4,6,5]` is INVALID.
Two-stage validation (rev 3):
- **Structural stage (proposal/override intake, scope-independent)**:
  duplicates, empty list, `file_order` supplied with strategy
  `shuffle` — rejected at the layer that received the value
  (plan validator for proposals; CLI/schema validator for
  overrides). Rule: **every provided value must be structurally
  valid, even if overridden** — a malformed agent proposal is
  rejected (and surfaced) rather than silently hidden by an
  operator override.
- **Resolution stage (scope-dependent, after DataScope resolution
  AND override application)**: the RESOLVED `file_order` must be a
  full permutation of the resolved scope — same set, no missing, no
  extra. Applied to the resolved value only; re-checked at the
  engine boundary (§3.3).

### 3.1 Ordering semantics (commit B)

The vocabulary below describes the RESOLVED execution values — what
the engine actually runs. How they are resolved from agent proposals
and operator overrides is §3.6; provenance naming is §3.7.

```text
resolved_order_strategy: "shuffle" | "sequential"
    default "shuffle" (behavior unchanged from today when nothing is
    proposed or overridden)
resolved_file_order:     list[int] | None
    meaningful ONLY when resolved strategy is "sequential"; then it
    MUST be a FULL PERMUTATION of the resolved DataScope (same set —
    no missing, no extra, no duplicates; Decision 5); when
    "sequential" resolves with no proposed/override file order,
    ascending file index over the resolved scope; when "shuffle"
    resolves, resolved_file_order is None — a proposed sequential
    file order is NOT silently retained under a shuffle resolution.
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
   defines (a) the indexed-dataset contract — `file_index →
   (readable path, segment list)` resolved through `DatasetConfig`
   (`training_file_pattern` already exists at
   `dataset_config.py:36-39`); (b) the **proposal/override/resolution
   configuration principle** (operator, 2026-07-28), stated as:
   *"Configurable options may have a proposed value, an operator
   override, and a resolved execution value. Only the resolved value
   defines what ran. Every override must remain visible in
   provenance and downstream interpretation."* — with ordering
   recorded as its first concrete implementation; (c) a
   **permissions taxonomy** for future options: each option declares
   whether it is agent-settable, operator-overridable, chain-locked,
   or frozen — safety limits and frozen scoring rules do NOT
   automatically become agent-settable because ordering is; (d) the
   task-pack and metric seams as PLACEHOLDER sections (filled by the
   PRs that first touch them; baseline §1.3 rule that inventing a
   new abstraction requires updating this doc first).
2. **Path-template extraction**: loaders consume
   `DatasetConfig.training_file_pattern` instead of inlining
   `abra_training_{i:04d}.h5`. Audited sites:
   `train_engine_sandbox.py:159, :294, :606, :906`. (Other modules'
   inlined templates are LEDGER ENTRIES, not commit-A work — bounded
   in-passing rule.)
3. **Explicit filename-pattern validation** (operator correction):
   `str.format()` does NOT fail when `{file_index}` is absent — a
   pattern like `training_file.h5` would silently map EVERY index to
   the same file. Commit A adds a validator (natural home: a
   `DatasetConfig` model validator — confirm at implementation) that
   parses the pattern's replacement fields (`string.Formatter().parse`)
   and requires a usable `file_index` field; valid forms include
   `training_{file_index}.h5` and `training_{file_index:04d}.h5`.
   The error fires at config construction — BEFORE any training,
   never relying on a later file-not-found (which would not even
   occur in the every-index-same-file case).
4. **Coupling ledger** `docs/design/tidmad_coupling_ledger.md`:
   grep-able inventory (template strings, `log_5.27`/`s_max`
   constants, TIDMAD-worded prompt fragments, 20-file/200-segment
   assumptions), each marked decoupled/remaining. Seeded from the
   audits; updated in-passing by every future PR. PLUS a
   **configuration-migration inventory**: future
   proposal/override/resolution candidates — sampling strategy,
   `train_portion`, learning rate / optimizer settings, DataScope,
   resource budgets, HealthGate policy inputs — each listed with its
   expected permissions class (§ item 1c), and explicitly NOT
   migrated in PR 2.
5. **Second-dataset contract test**: a minimal synthetic
   `DatasetConfig` fixture (different pattern, file count, segment
   count) proving the loader construction path is
   dataset-config-driven. A seam without such a test is "renamed",
   not "generic" (guardrail 3).

Frozen exception (guardrail 4): the TIDMAD score formula and
`legacy_baseline_configs.json` are untouched.

### 3.3 Propagation path (commit B, rev 3 — resolver-mediated)

Ordering follows the established out-of-band data-option pattern
(§2.2), with the single ordering resolver (§3.6) between intake and
execution. Both intake surfaces are Pydantic-validated BEFORE the
resolver runs (Decision 5 structural stage); the resolver output is
scope-validated (Decision 5 resolution stage); the engine re-checks
at its boundary:

```text
agent proposal                       operator override
(ExperimentPlan: order_strategy /    (chain CLI → HyperparamTuningInput
 file_order proposal fields;          override fields; structural
 structural validation in the         validation at schema layer;
 plan validator — reject              override locked per chain in
 file_order+shuffle, duplicates,      run_invariants_lock, §3.8)
 empty list)                          |
        \                             |
         \                            v
          +──────────→  ordering resolver (ONE function, §3.6)
                        precedence: override > proposal > default
                        + full-permutation check vs resolved
                          DataScope on the RESOLVED value
                              |
                              v
              ResolvedOrdering (typed result, §3.6)
                              |
                              v
  TrialConfig / active_params (resolved values + full provenance)
                              |
                              v
  training_skill wrapper → execute_training (resolved values ONLY;
    stub twin mirrors) → subprocess CLI
    (--order_strategy/--file_order_json carry RESOLVED values)
                              |
                              v
  engine boundary re-check: resolved file_order is exactly a
    permutation of sample_set keys (violation terminates,
    non-retryable) → [data_order] runtime log (§3.9)
                              |
                              v
  records / run_config / manifest (proposed + override + resolved +
    source, §3.7) → interpreter-visible execution context
    (resolved values identify what ran, §3.7 invariant)
```

`freeze_subsample` (dead switch, §2.2) is left as-is — removing it
is out of scope.

### 3.4 RT2 accounting (commit B, minimal under Decisions 1+4a)

- No change to the setup window, reconstruction term, scoped bytes,
  step arithmetic, or verification loop — dataset construction and
  step count are both unchanged (Decision 1 + Decision 4a).
  `workload_resolvers.py` needs no strategy-aware arm (and is NOT in
  the affected-file list; resolver step-count parity is asserted by
  test without a code change there). The only RT2 delta is
  provenance: `resolved_order_strategy` recorded in the workload
  `detail` so observations remain attributable if ordering ever
  affects unit time.
- §12 error-ledger evidence: one entry comparing predicted vs actual
  under `sequential` in P2-V2 confirms the accounting holds (expected
  result: within existing tolerance, since only the visit permutation
  changed).

### 3.5 Docstring drift repair (commit B, in-passing)

`run_experiment_streaming` docstring (`:477-481`) and the `main()`
comment (`:881`) are rewritten to describe reality: per-epoch
concatenated dataset, ordering per the resolved strategy. The
misleading "streaming" name is NOT changed in PR 2 (rename = churn
across call sites and tests; noted in the coupling ledger instead).

### 3.6 Ordering resolver (rev 3 — ONE function, typed result)

Precedence is implemented exactly once. Conceptual behavior:

```text
if operator override is present:
    resolved = operator override;      source = "operator_override"
elif agent proposal is present:
    resolved = agent proposal;         source = "agent_proposal"
else:
    resolved = "shuffle";              source = "default"

then, for file_order on the RESOLVED strategy:
  resolved "sequential" + explicit order (from the winning level) →
      that order, full-permutation-validated vs resolved scope
  resolved "sequential" + no order supplied → ascending resolved scope
  resolved "shuffle" → resolved_file_order = None (a proposed
      sequential file order is dropped, recorded only as proposal)
```

Typed result (conceptual; exact type/location chosen at CB1 after
code inspection — candidate home: `agent/schemas/hyperparam_tuning.py`
beside `TrialConfig`, keeping schema + resolution in one module):

```text
ResolvedOrdering:
    proposed_strategy:   "shuffle" | "sequential" | None
    proposed_file_order: list[int] | None
    override_strategy:   "shuffle" | "sequential" | None
    override_file_order: list[int] | None
    resolved_strategy:   "shuffle" | "sequential"
    resolved_file_order: list[int] | None
    resolution_source:   "operator_override" | "agent_proposal"
                         | "default"
```

Call site: the tuner's per-round config assembly (where
`ExperimentPlan` meets `HyperparamTuningInput`, near
`_resolve_sample_set_cfg` — the same place formal/trial precedence
already lives). Workflow, tuner, and engine never re-derive
precedence; they consume the resolver's output.

Validation split (Decision 5): structural validity is checked at
each intake BEFORE the resolver (a malformed proposal is rejected
and surfaced even when an override would win — malformed agent
output must not be hidden by an override); the full-permutation
check runs on the RESOLVED value inside the resolver.

### 3.7 Provenance schema + attribution invariant (rev 3)

**Invariant (verbatim, governs all downstream use):** *Only resolved
configuration values describe the executed experiment. Proposed
values describe agent intent; override values describe operator
control. Downstream attribution and interpretation must use the
resolved values.*

Persisted per round (in `ExperimentRecord`, `run_config_*.json`, and
the iteration manifest — names below are canonical; if
implementation shortens them, the mapping is documented here):

```text
proposed_order_strategy    | what the agent proposed, REJECTED OR NOT;
                           | None only when it proposed nothing
proposed_file_order        | ditto
ordering_proposal_rejected | True when a proposal arrived but was not
                           | applied (operator requirement, 2026-07-28)
ordering_proposal_rejection_reason
                           | why — distinguishing an invalid ordering
                           | from one discarded because ANOTHER plan
                           | field failed validation
override_order_strategy    | None when no operator override
override_file_order        | None when not overridden
resolved_order_strategy    | always present for executed rounds
resolved_file_order        | None iff resolved strategy is shuffle
ordering_resolution_source | "operator_override" | "agent_proposal"
                           | "default"
```

**Rejected proposals are recorded, never silently dropped** (operator
clarification, 2026-07-28). Falling back from a malformed LLM ordering
proposal is acceptable — it is the established `with_defaults`
treatment of any bad trial field, so one malformed token cannot kill a
round — but the fallback must not be SILENT. A rejected proposal is
materially different from no proposal: the agent DID try to steer the
round and was overruled. Every rejection therefore exposes: that a
proposal was present; that it was rejected; the reason; the resolved
ordering that actually ran; and whether that came from the override or
the default. `ordering_resolution_source` is never `agent_proposal`
for a rejected proposal, so an override is never attributed to the
agent. Two rejection KINDS are distinguished, because reporting the
second as the first would misattribute the defect:
- the ordering fields were themselves invalid;
- the ordering was well-formed but discarded because a different plan
  field failed validation.

A reviewer must be able to reconstruct, from any round record alone:
"Agent proposed sequential; operator override shuffle; actually
executed shuffle; source operator_override." An overridden proposal
is NEVER described as executed.

**Where each ordering fact is persisted** (three distinct artifacts —
do not conflate them):

| Artifact | Stores | Why |
|---|---|---|
| `run_config_{run}.json` | the run-level operator OVERRIDE policy (`order_strategy_override`, `file_order_override`; null = none) | One control decision for the whole run. The per-round resolved value does NOT belong here — it may differ round to round when no override is in force. |
| `ExperimentRecord` (per round) | that round's full nonet: proposed (rejected or not), rejection flag + reason, override, resolved, resolution source | The per-round source of truth. Ordering can vary between rounds, so each round carries its own. |
| iteration `manifest.json` | round/experiment-KEYED ordering provenance (`exp_id` + the same fields per entry) — **CB3-d, not yet implemented** | The cross-iteration handoff. Keyed per experiment so multiple rounds are never collapsed into one unlabelled iteration-level value. |

**Manifest granularity rule (operator clarification, 2026-07-28):**
ordering may resolve differently across rounds within one workflow
iteration (agent-exploration mode), so the iteration manifest must
NOT store one unlabelled iteration-level septet as though it
describes the whole iteration. Rules:
- `ExperimentRecord` remains the per-round source of truth;
- each experiment's `run_config` records the values actually
  associated with THAT experiment;
- the iteration manifest records ordering provenance as a
  round/experiment-KEYED list (or keyed summary), each entry
  preserving `exp_id` and its proposed/override/resolved/source
  values — multiple round configurations are never collapsed into
  one unlabelled value;
- interpreter-facing summaries associate resolved ordering with the
  correct model/round.
Exact manifest field name and JSON shape are selected during CB3
code inspection; this granularity rule is binding regardless of the
shape chosen, and the CB3 tests assert it (a two-round pseudo
iteration with differing resolved ordering must yield two keyed
manifest entries).

Interpreter exposure: the resolved values surface in the
interpretation input path. Audited seam: `InterpretationInput`
consumes `ModelRunSummary` objects
(`agent/schemas/interpretation.py:175+`) and explicitly NOT raw
records — so the resolved ordering travels via the summary layer
(exact field placement on `ModelRunSummary` decided at CB3 after
inspecting its construction site). The interpreter-facing field
carries RESOLVED values (labeled as what ran); proposal/override may
accompany as context but never replace it.

Legacy artifacts (explicit interpretation, no guessing, no
rewriting): records without ordering fields → treated as
`resolved_order_strategy="shuffle"`, `resolved_file_order=None`,
proposal/override = None, `ordering_resolution_source=
"legacy_default"` (a fourth enum value used ONLY when reading
pre-PR2 artifacts — never written by new runs).

### 3.8 Chain-lock semantics (rev 3 — lock the OVERRIDE, not the resolution)

The operator override is chain-stable control policy; the resolved
value may legitimately vary per round when no override is active.
Therefore:

- `run_invariants_lock.json` (`core/run_invariants.py::RunInvariants`,
  canonical set currently `resolved_data_scope` +
  `health_gate_enabled` + `health_config_sha256`) gains
  `ordering_override_strategy: str | None = None` and
  `ordering_override_file_order: list[int] | None = None`, added to
  `_CANONICAL_FIELDS`. Defaults `None` = "no override recorded" —
  chosen precisely so legacy locks (which lack the keys)
  `model_validate` cleanly to the no-override state instead of
  raising the corruption error (`load_run_invariants` `:90-116`
  audited).
- `resolved_order_strategy` is NOT locked — locking it would forbid
  legitimate per-round variation in agent-exploration mode.
- Resume matrix (all tested):
  - same override on resume → accepted;
  - changed override strategy → `RunInvariantsViolation`;
  - changed override file order → `RunInvariantsViolation`;
  - no override + different agent proposals across iterations →
    allowed, each iteration records its own resolved ordering;
  - legacy workspace (lock without ordering keys) + no override →
    accepted (None == None);
  - legacy workspace + operator now adds an override → rejected
    (None ≠ value; the operator explicitly starts a new workspace to
    change chain control policy — consistent with existing scope/
    gate-flip semantics).

### 3.9 Bounded runtime ordering log (rev 3)

Two-line split, forced by the CB2 rule that the engine receives
resolved values ONLY (it cannot log proposal/override it never sees):

- **Resolution line** — emitted once per round at the resolution
  point (the tuner, which knows all three levels):

  ```text
  [data_order] proposed=sequential override=shuffle resolved=shuffle \
    source=operator_override file_order=none
  ```

- **Engine line** — emitted once per epoch from resolved values:

  ```text
  [data_order] resolved=shuffle file_order=none epoch=0 epoch_seed=42
  ```

Together they show: proposed strategy, operator override, resolved
strategy, resolution source, resolved file order (`none` or the
permutation), epoch + epoch seed. No per-sample dumps in real runs —
deterministic tests own full-sequence verification. P2-V2's Gate
evidence quotes both lines verbatim to prove the expected resolved
strategy and file order were actually selected and logged
(anti-hallucination standard).

## 4. Affected locations

Re-audited for rev 3 (2026-07-28). `workload_resolvers.py` REMOVED
(no code change required — §3.4; resolver step-count parity is
asserted by test only). Additions: `ExperimentPlan` proposal fields
(same module as the other schema work), the ordering resolver,
`core/run_invariants.py` (override lock), and the interpretation
summary seam.

| Area | Files |
|---|---|
| Commit A | `docs/design/genericity_contract.md` (new), `docs/design/tidmad_coupling_ledger.md` (new), `execute_tools/train_engine_sandbox.py` (template consumption), `execute_tools/dataset_config.py` (filename-pattern validator, §3.2 item 3), new contract test |
| Commit B schema + resolver | `agent/schemas/hyperparam_tuning.py` (`ExperimentPlan` proposal fields `:582+`; `HyperparamTuningInput` override fields; `TrialConfig` resolved fields; `ExperimentRecord` provenance septet `:380+` region; `ResolvedOrdering` + the resolver — candidate home this module, confirm at CB1), `core/run_invariants.py` (`RunInvariants` override fields + `_CANONICAL_FIELDS` `:50-81`, `build_run_invariants` `:213+`) |
| Commit B engine | `execute_tools/train_engine_sandbox.py` (sampler + boundary validation + `[data_order]` log + docstrings) |
| Commit B plumbing | `core/sandbox_executor.py` (execute_training + stub), `agent/skills/training_skill/wrapper.py`, `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py` (resolver call site near `_resolve_sample_set_cfg` + TrialConfig build + CLI), `scripts/run_comparison.py`, `sdsc_submission_scripts/run_one_iteration.py`, `sdsc_submission_scripts/_chain_common.sh`, `agent/schemas/interpretation.py` (`ModelRunSummary` resolved-ordering exposure `:175+` seam — exact field at CB3) |
| Tests | new unit suites (resolver/resolution matrix, ordering semantics, validation, parity, lock/resume matrix), pseudo integration (three resolution cases), pattern-validator tests |

## 5. Scope and non-goals

Explicit non-goals (rev 3, operator-enumerated):

- PR 2 does NOT migrate all configuration options to the
  proposal/override/resolved pattern (ordering only; others are
  inventory entries — §3.2 item 4).
- PR 2 does NOT create a universal repository-wide configuration
  framework (one resolver, for ordering).
- PR 2 does NOT change loader partitioning (Decision 1).
- PR 2 does NOT reduce memory usage (FU-P2-1).
- PR 2 does NOT change optimizer-step count (Decision 4a).
- PR 2 does NOT make ordering the production default (`shuffle`
  remains; parity contract §3.1 — same selection, RNG behavior,
  visited sequence, step count).
- PR 2 does NOT claim the agent uses ordering intelligently — it
  verifies information flow and recording only; behavior claims fall
  under baseline §4.
- PR 2 ONLY establishes ordering as the first tested example of the
  proposal/override/resolved pattern.

Also unchanged from rev 2: training loader only (eval/scoring order,
`score_vector`, HealthGates, frozen score formula untouched);
per-file optimizer re-initialization not a V19 commitment; P2-E
empirical campaign designed after merge (not overdesigned now).

## 6. Commit plan (detailed — locked at P2-D approval, 2026-07-28; expanded per operator template same day)

PR 1 tick discipline applies: an item is `[x]` only when implemented
AND its verification evidence is recorded (test names + counts + wall
time in this doc). Stop-and-show before every commit: exact diff
summary, staged file list, tests run, and any deviation from this
design. Each commit is independently reviewable and revertible;
dependencies only in the order listed. Standing rules restated for
the implementer: ordering and loader partitioning remain separate
concerns; `file_order` is a full permutation of the resolved
DataScope; the default remains `shuffle`; the agent's PROPOSAL
fields land in these commits (rev 3) but no intelligent-use claim is
made, and strategy promotion / production-default changes remain
OUTSIDE (P2-E/P2-ACT). If code inspection during implementation
reveals ambiguity or larger scope than assumed here, STOP and ask
before changing the plan.

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
- **Pre-implementation audit (2026-07-28, operator-approved
  stop-and-show)**: all four sites re-verified on disk — `:159` is
  `TIDMADDataset._pull_events_from_sample_set` (confirmed a method
  of that class); `:294` `TIDMADEpochDataset.__init__`; `:606` RT2
  storage-provenance path list; `:906` legacy single-file `main()`
  branch, which uses `str(file_index).zfill(4)` rather than a
  format spec — identical output for the non-negative ints in play;
  the parity test asserts equality across `range(TIDMAD.num_files)`
  regardless. Validator placement confirmed: `DatasetConfig`
  model-validator; the module-level `TIDMAD` instance means an
  invalid default fails at import, the earliest possible point.
  Import seam exists (`train_engine_sandbox.py:19` already imports
  from `dataset_config`).
- Non-goals / must-not-change: no signature changes; no behavior
  change (resolved TIDMAD paths identical); inference/scoring
  template sites are LEDGER ENTRIES only, not refactored here
  (bounded in-passing rule); the frozen score formula and
  `legacy_baseline_configs.json` untouched.
- Dependencies: none (first commit of the PR).

**Implementation plan.**
- [x] Write `docs/design/genericity_contract.md` per §3.2 item 1:
      indexed-dataset contract; the proposal/override/resolution
      configuration principle (operator statement verbatim) with
      ordering named as its first concrete implementation; the
      permissions taxonomy (agent-settable / operator-overridable /
      chain-locked / frozen); task-pack + metric PLACEHOLDER
      sections; the §1.3 update-this-doc-first rule.
      *(4 seams; §1 marked partially-implemented — commit A moved
      the TEMPLATE behind the seam, not the CHOICE of dataset, which
      is recorded as a later ladder step.)*
- [x] Write `docs/design/tidmad_coupling_ledger.md`: entries with
      file:line from the P2-A audits, each marked
      DECOUPLED/REMAINING/PARTIAL/FROZEN; PLUS the
      configuration-migration inventory (§3.2 item 4).
      *(6 sections. Every cited line re-verified by grep before
      writing. Newly surfaced while seeding, beyond the design's
      list: `execute_tools/array2h5.py:25` `create_abra_file` —
      TIDMAD vocabulary in a public function NAME, not just a
      literal; `execute_tools/per_file_best.py:62` — a SECOND
      `LOG_BASE = 5.27` copy; and the denoised-OUTPUT naming family
      (`run_comparison.py:445` etc.), flagged as needing its own
      contract decision since it names artifacts SIDERIUS produces
      rather than files it reads.)*
- [x] Add the filename-pattern validator (§3.2 item 3): parse
      replacement fields via `string.Formatter().parse`, require a
      usable `file_index` field; error at config construction.
      *(Implemented as a `field_validator` over BOTH pattern fields
      rather than a model-validator — the check is per-field and
      needs no cross-field data; `field_validator` was already
      imported. Empirically probed all 11 pattern shapes first: only
      the missing-placeholder case is silent, so the validator does
      TWO checks — presence (the silent case) and a format probe
      with `_PATTERN_PROBE_INDEX = 7` (moves the loud cases from
      training time to construction time). Also added
      `DatasetConfig.training_file_name()` as the single build
      point; deliberately NO `validation_file_name()` — it would be
      dead code, since validation templates live in `scripts/` and
      are ledger entries.)*
- [x] Refactor the four `train_engine_sandbox.py` sites to consume
      `TIDMAD.training_file_pattern` *(via `training_file_name`;
      import added at `:19-20`, ruff re-sorted)*.
- [x] Add `tests/unit/execute_tools/test_dataset_contract.py`:
      synthetic `DatasetConfig` fixture (different pattern, file
      count, segment count) driving dataset path construction.
      *(6 tests. Loader-consumption is probed by monkeypatching the
      pattern and reading the loader's OWN missing-file warning —
      proves the path is config-derived without needing HDF5
      fixtures. Validator/parity tests went into the EXISTING
      `test_dataset_config.py` (14 added) since they test that
      module; the new file holds only the contract-level tests.)*

**Validation plan.**
- Unit: path-resolution parity (per audited site, resolved TIDMAD
  filename before == after); contract test with the synthetic
  fixture (path built from the fixture's pattern, not the TIDMAD
  literal).
- Pattern validator: positive tests for `training_{file_index}.h5`
  and `training_{file_index:04d}.h5` (and the TIDMAD default);
  negative test for `training_file.h5` (no placeholder) → clear
  config-construction error BEFORE training, never a downstream
  file-not-found (which would not occur — every index would map to
  the same existing file).
- Integration/pseudo: none required (no behavior change).
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
- Malformed pattern (no `{file_index}` replacement field): explicit
  validator error at config construction — stop execution. NOT
  detectable via `str.format()` raising (it does not) nor via
  file-not-found (the same-file mapping points at an existing file).
- Missing file on disk: existing behavior preserved exactly
  (warning + skip, `train_engine_sandbox.py:295-297`) — this commit
  must not change it.

**Verification commands and evidence.** *(run 2026-07-28, lilab)*
- [x] `.venv/bin/python -m pytest tests/unit/execute_tools/test_dataset_config.py
      tests/unit/execute_tools/test_dataset_contract.py -q` →
      **26 passed in 0.79s** (14 new in test_dataset_config +
      6 new in test_dataset_contract, on top of the 6 pre-existing).
- [x] `.venv/bin/python -m pytest tests/unit/execute_tools -q` →
      **493 passed, 1 failed in 5.25s**. The single failure is
      PRE-EXISTING and unrelated:
      `test_scoring_helpers.py::TestPostPathAReferenceConsistency::
      test_post_path_a_reference_consistency`. **Proven pre-existing**
      by stashing all P2-CA changes and re-running — byte-identical
      failure (`Obtained: -8.260916269975333`, `Expected:
      -8.260971502899364 ± 8.3e-09`). It compares
      `file_vector_to_log_space` against on-disk ground truth in
      `/home/klz/Data/SIDEREIS_DATA/ground_truth/`; it is
      `pytest.skip`-guarded when that data is absent, so CI skips it
      and only lilab sees it. Either the on-disk ground truth is
      stale or the helper and `compute_ground_truth.py` have drifted
      (~5e-5 relative). **NOT fixed here — out of P2-CA scope;
      flagged to operator** (see FU-P2-4).
- [x] `.venv/bin/python -m pytest tests/unit/core/test_sandbox_executor.py -q`
      → **49 passed in 0.81s**.
- [x] Post-format re-run of all affected suites →
      **75 passed in 0.83s**.
- [x] `.venv/bin/ruff check` → clean on all 4 touched files (one
      `I001` import-sort auto-fixed in `train_engine_sandbox.py`).
      `.venv/bin/ruff format --check` → 4 files formatted
      (`dataset_config.py` + `test_dataset_config.py` reformatted,
      then re-tested green).
- [x] Tests NOT run, with reason: no pseudo/integration or Gate
      tests — this commit has zero behavior change, and the design
      lists none for P2-CA. `pyright` not run (lilab Node < 14,
      PR #123 precedent).

**Commit boundary.** Docs + template consumption + contract test
ONLY. No ordering code, no schema fields, no cleanup beyond the four
sites. Stop-and-show the diff summary + staged list + test evidence
before committing.

### P2-CB1 — schema, proposal, override, and resolution (no engine change)

**Goal.** Introduce the complete ordering-control vocabulary —
agent proposal fields, operator override fields, the single ordering
resolver with its typed `ResolvedOrdering` result, the provenance
septet, and the chain-lock override fields — so that precedence
exists in exactly one place before any engine or propagation code is
written. Separate from the engine commit so resolution semantics are
reviewable (and revertible) independently of loader mechanics.

**Scope.**
- Changes: `agent/schemas/hyperparam_tuning.py` — `ExperimentPlan`
  proposal fields (`:582+` block, `with_defaults` tolerant of
  absence); `HyperparamTuningInput` override fields;
  `TrialConfig` resolved fields; `ExperimentRecord` provenance
  septet (§3.7, near the `trial_strategy` stamps `:380-435`);
  `ResolvedOrdering` + the resolver function (candidate home: this
  module — confirm at implementation); `validate_runtime_config`
  (`:1573`) wiring for the resolution-stage check;
  `core/run_invariants.py` — `RunInvariants` override fields +
  `_CANONICAL_FIELDS` + `build_run_invariants` (§3.8);
  `run_config` persistence in the tuner (write-side only).
- Validation split (Decision 5 rev 3): STRUCTURAL checks at each
  intake (plan validator for proposals — precedent
  `_validate_target_files`; schema validator for overrides —
  precedent the `health_gate_files` validators at
  `hyperparam_tuning.py:1352-1359`); the FULL-PERMUTATION check on
  the RESOLVED value only (inside the resolver, invoked from
  `validate_runtime_config` and the per-round assembly — precedent
  the partial-scope checks at `:1597-1623`).
- Non-goals / must-not-change: no engine behavior; no propagation
  to CLIs yet; defaults leave every existing construction site valid
  unchanged; no migration of any other option to this pattern.
- Dependencies: lands after P2-CA (contract doc defines the
  principle this commit implements).

**Implementation plan.**
- [x] `ExperimentPlan` proposal fields:
      `order_strategy: Literal["shuffle","sequential"] | None = None`,
      `file_order: list[int] | None = None` (proposal semantics —
      intent, not execution truth); plan validator rejects
      internally inconsistent proposals (file_order with proposed
      shuffle; duplicates; empty list). Scope-dependent checks
      deferred to resolution.
      *(Validator `_validate_ordering_proposal` delegates to the
      shared `validate_ordering_shape`, so proposal and override use
      ONE structural rule set. **Interaction found with the
      pre-existing `with_defaults` contract**: a structurally
      invalid ordering proposal makes strict validation fail, so the
      established LLM-robustness fallback drops it with the other
      trial fields and the round proceeds with NO proposal
      (resolving to override/default), warning printed. Kept as-is —
      that is the documented treatment of any bad LLM trial field
      (`trial_portion=5.0` etc.), and making ordering uniquely fatal
      would let one malformed token kill a round. It does not weaken
      D5, which concerns an override masking a proposal that DID
      arrive; every proposal reaching the resolver is validated
      there. Documented in the `with_defaults` docstring.)*
- [x] `HyperparamTuningInput` override fields (conceptually
      `order_strategy_override` / `file_order_override` — exact
      names after auditing nearby CLI conventions); structural
      validation at the schema layer.
      *(Names kept as `order_strategy_override` /
      `file_order_override`.)*
- [x] `ResolvedOrdering` type + ONE resolver function (§3.6):
      precedence override > proposal > default; file_order
      resolution rules incl. shuffle → None (no silent retention of
      a proposed sequential order); full-permutation check vs
      resolved scope on the RESOLVED value.
      *(Landed as a DEDICATED module `agent/schemas/ordering.py`
      (~310 lines) rather than inside the 1600-line
      `hyperparam_tuning.py` — the design left the home to
      implementation choice, and the project rule "each module
      testable individually, pluggable, decoupled" favors a separate
      module. Public API: `OrderStrategy`,
      `OrderingResolutionSource`, `DEFAULT_ORDER_STRATEGY`,
      `OrderingValidationError`, `validate_ordering_shape`,
      `ResolvedOrdering` (frozen, + `.legacy_default()`,
      `.describes_execution()`), `resolve_ordering`.
      `resolve_ordering` re-runs structural validation on both
      levels so a caller that skipped the intake check cannot
      smuggle a malformed value past resolution. 26 tests green.)*
      **Under-specification resolved during implementation** (§3.6
      did not define "override is present" when only
      `file_order_override` is set): a uniform structural rule now
      applies at BOTH levels — a `file_order` may be supplied only
      alongside an explicit `sequential` strategy AT THE SAME LEVEL.
      This follows from the design's own "file_order: sequential
      only" and makes override-presence unambiguous
      (`override_strategy is not None`). Recorded here rather than
      silently chosen.
- [x] `TrialConfig` gains resolved fields only
      (`resolved_order_strategy`, `resolved_file_order`) — the
      engine-facing single source of truth per round.
      *(Plus a cross-field validator: `resolved_file_order` must be
      None under `shuffle`, so a stale order can never misreport
      what ran.)*
- [x] `ExperimentRecord` provenance septet (§3.7):
      proposed/override/resolved strategy + file_order +
      `ordering_resolution_source`.
      *(All seven default to None so pre-PR2 records stay
      constructible and readable; placed beside the existing
      `planned_*` / `strategy_normalization_reason` provenance,
      which is the same proposed-vs-effective idea this
      generalizes.)*
- [x] Resolution-stage wiring in `validate_runtime_config`.
      *(**Placement bug caught by test**: the function early-returns
      for FULL scopes, so an ordering check appended after it would
      silently never run outside partial-scope runs. The override
      validation now precedes that return, with a regression test
      (`test_override_is_validated_under_a_FULL_scope_too`) pinning
      it.)*
- [x] `RunInvariants`: `ordering_override_strategy` /
      `ordering_override_file_order` (defaults None; legacy locks
      load as no-override, §3.8) + canonical-set inclusion +
      `build_run_invariants` plumbing.
      *(Both added to `_CANONICAL`, so drift is reported per-field
      by the existing violation machinery with locked-vs-attempted
      values. `build_run_invariants` gained two defaulted keyword
      params — all four production call sites
      (`run_comparison.py:1186`, `model_exploration.py:1755`,
      `run_one_iteration.py:1000`,
      `ml_hyperparameter_tune_agent.py:1785`) are unchanged and
      produce no-override locks until CB3 wires the operator value
      through. The file order is copied into the lock so it cannot
      alias a caller's mutable list.
      **One pre-existing test updated**:
      `test_run_invariants.py::test_lock_file_is_plain_json` asserted
      an EXACT key set of the pre-PR2 lock schema; extended with the
      two new keys (both asserted None by default). Test-expectation
      change only — no production behavior was altered to make it
      pass.)*
- [ ] Persist the septet in `run_config_*.json` (P1-C5 A4
      precedent).

**Validation plan.**
- Unit (resolution matrix, one test each — §7.1 "Resolution logic"):
  proposal sequential + no override → sequential
  (source=agent_proposal); proposal shuffle + no override → shuffle;
  no proposal + no override → default shuffle (source=default);
  proposal sequential + override shuffle → shuffle
  (source=operator_override), proposed file order NOT retained;
  proposal shuffle + override sequential → sequential;
  override sequential with no file order → ascending resolved
  scope; invalid override permutation → startup failure;
  structurally invalid proposal + valid override → proposal error
  surfaced (not hidden by the override).
- Unit (structural negatives, per intake): duplicates; empty list;
  file_order with shuffle — at plan layer AND at override layer.
- Unit (resolved-value negatives): subset (`[4,6,5]` under scope
  `[4..9]`); missing file; extra/out-of-scope file — on the
  RESOLVED value.
- Lock/resume matrix (§3.8, one test each): same override accepted;
  changed override strategy rejected; changed override file order
  rejected; no-override + varying proposals allowed; legacy lock +
  no override accepted; legacy lock + new override rejected.
- DS8 interaction: resolution validated against the RESOLVED scope
  under a partial `--data_scope`.
- Backward-compat: existing suites for the schema module and
  `tests/unit/core/test_run_invariants.py` green with no fixture
  edits beyond additive fields.
- Integration/pseudo: none in this commit (resolver is exercised
  end-to-end in CB3).
- Gate tests: none.

**Acceptance criteria.**
- Every input/fixture constructed without the new fields validates
  exactly as before (defaults non-breaking) — untouched existing
  suites pass.
- The full resolution matrix above holds, with
  `ordering_resolution_source` asserted per case — not just the
  resolved strategy.
- Precedence logic exists in exactly ONE function (asserted by
  grep-level review at stop-and-show: no second comparison of
  proposal vs override anywhere).
- Each invalid shape produces a distinct, message-bearing error
  naming the offending indices, at the specified layer (plan vs
  override schema vs resolver) — asserted by layer.
- A persisted record's septet fully reconstructs "proposed X,
  override Y, executed Z, source S", round-tripped through JSON.
- Legacy `run_invariants_lock.json` (no ordering keys) loads
  cleanly as no-override; the resume matrix behaves exactly as
  §3.8 specifies.

**Failure and edge cases.**
- Invalid resolved permutations: stop at startup (operator config
  is a contract — DS8 precedent; no normalization).
- Structurally invalid proposal under a winning override: error
  surfaced, run stops — malformed LLM output is never silently
  masked (operator rule, §3.0 D5).
- Legacy configuration (records/run_configs without ordering
  fields): read paths tolerate absence; interpretation per §3.7
  legacy rules (`legacy_default` source; no artifact rewriting).
- Resume: override locked (strategy AND file order); resolved value
  NOT locked; legacy-lock semantics per §3.8. (Supersedes the rev-2
  "mirror formal_strategy, don't lock" flag — the operator resolved
  it: lock the OVERRIDE, never the resolution.)

**Verification commands and evidence.** *(run 2026-07-28, lilab)*
- [x] `tests/unit/agent/schemas/test_ordering.py` (NEW, CB1-a) →
      **26 passed in 0.07s** — full §7.1 resolution matrix.
- [x] `tests/unit/agent/schemas/test_ordering_schema_wiring.py`
      (NEW, CB1-b) → 28 tests; `tests/unit/agent/schemas/` whole
      directory → **134 passed in 0.78s**.
- [x] Regression sweep `.venv/bin/python -m pytest tests/unit/agent
      tests/unit/workflows -q` → **2962 passed in 185.97s** — zero
      regressions from the additive schema fields.
- [x] `ruff check` + `ruff format --check` clean on all CB1-a/CB1-b
      files.
- [x] `tests/unit/core/test_run_invariants_ordering.py` (NEW, CB1-c,
      the §3.8 resume matrix) + `test_run_invariants.py` →
      **41 passed in 0.10s**; full `tests/unit/core` →
      **462 passed in 2.97s**.
- [x] Tests NOT run, with reason: no pseudo/integration yet (the
      resolver is not wired into the tuner until CB3); `pyright` not
      run (lilab Node < 14, PR #123 precedent).

**Commit boundary.** Schema + resolver + lock fields + provenance +
run_config write-side ONLY. No engine code, no CLI flags, no
forwarding. Stop-and-show before commit.

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
- **Rev-3 boundary rule**: the engine receives RESOLVED values only
  (`--order_strategy`/`--file_order_json` carry the resolver
  output). It has no knowledge of proposals, overrides, or how they
  were combined — no proposal/override flags exist at the engine
  CLI. Its `[data_order]` epoch line (§3.9) therefore shows resolved
  values + epoch seed only.
- Dependencies: P2-CB1 not strictly required (engine takes plain CLI
  values and re-validates), but the ladder lands CB1 first so the
  vocabulary is defined once.

**Implementation plan.**
*(Note: sampler mechanics below are the design intent; the
implementer inspects the epoch loop before finalizing the exact
DataLoader wiring — torch requires `shuffle=False` when a sampler is
passed, and the epoch-RNG plumbing must reuse `epoch_rng`/`epoch_seed`
at `:583-584`, not introduce a second seed path.)*
- [x] Build the `sequential` index permutation: per-file index
      blocks in `file_order` order, each block shuffled with the
      epoch RNG (Decision 2), flattened.
      *(**Block offsets are NOT re-derived** — that would have been
      wrong: a file missing on disk is skipped with warn+continue
      and contributes no rows, so any recomputed layout would drift
      from reality. `TIDMADEpochDataset` now records
      `file_row_ranges: {file_index: (start, end)}` as rows are
      appended, and `build_sequential_indices()` addresses those
      spans. A file named in `file_order` that contributed no rows
      is passed over; a LOADED file omitted from `file_order` is a
      hard error, since never visiting it would change selection.
      Ordering uses an independent RNG stream seeded
      `f"order:{epoch_seed}"` — the dataset consumes a variable
      number of draws depending on train_portion and file count, so
      sharing its generator would couple visit order to subsampling
      internals; the prefix also prevents epoch N's ordering stream
      colliding with epoch N+1's subsampling stream.)*
- [x] Pass the permutation to ONE global
      `DataLoader(..., drop_last=True)` via `sampler=`; `shuffle`
      strategy keeps the existing `shuffle=True` call unchanged.
      *(Verified empirically that a plain list is accepted as
      `sampler` (torch 2.10 annotates `Sampler | Iterable | None`),
      that `len(loader)` still applies the global `drop_last` floor,
      and that iteration follows the sampler exactly.)*
- [x] CLI: `--order_strategy` (default `"shuffle"`, `choices=`
      constrained) + `--file_order_json` — RESOLVED values only;
      engine re-validates; no proposal/override flags here.
- [x] Engine boundary validation
      (`validate_ordering_against_scope`): resolved `file_order` is
      exactly a permutation of `sample_set` keys — violation raises
      with missing/extra/duplicated named, non-retryable.
- [x] `[data_order]` engine log line (§3.9): once per epoch,
      `resolved=... file_order=... epoch=N epoch_seed=S`.
- [x] RT2 provenance: `resolved_order_strategy` added to the
      training workload `detail` dict — no arithmetic change.
- [x] Docstring repair: the `run_experiment_streaming` docstring and
      the `main()` call-site comment now describe reality (per-epoch
      concatenated dataset, all scope files resident); the false
      "one file at a time / shuffled file order" claims are gone.
      The misleading *name* is retained deliberately, with the
      rename recorded in the coupling ledger.

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
  `resolved_order_strategy` detail key (asserted on a captured
  sidecar).
- The engine `[data_order]` line appears once per epoch with the
  resolved values and epoch seed (asserted on captured stdout).
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

**Verification commands and evidence.** *(run 2026-07-28, lilab)*
- [x] `tests/unit/execute_tools/test_ordering_engine.py` (NEW) →
      **25 passed in 2.16s**. Includes two REAL engine runs
      (`run_experiment_streaming`, tiny wavenet on CPU) capturing
      the DataLoader kwargs: shuffle path → `shuffle=True`, no
      sampler; sequential path → sampler present, no `shuffle`, same
      `drop_last`, every row visited exactly once, file 6 first
      under `file_order=[6,4,5]`. Both `[data_order]` lines asserted
      on captured stdout.
- [x] RT2 non-regression: `test_rt2b_streaming_preamble.py` +
      `test_rt2c_training_verification.py` +
      `test_workload_resolvers.py` → **21 passed in 2.91s**,
      unchanged (dataset-construction count still 1/epoch; workload
      arithmetic untouched).
- [x] `.venv/bin/python -m pytest tests/unit/execute_tools -q` →
      **518 passed, 1 failed in 6.73s** — the failure is the same
      pre-existing, unrelated FU-P2-4 scoring-ground-truth drift
      documented under P2-CA.
- [x] `ruff check` + `ruff format --check` clean on both files.
- [x] Tests NOT run, with reason: no pseudo/integration yet (the
      resolver is not wired into the tuner until CB3); no Gate
      tests (P2-V2, operator-approved separately); `pyright` not run
      (lilab Node < 14).

**Commit boundary.** Engine + its tests + docstrings ONLY. No
schema, no propagation, no chain scripts, no unrelated engine
cleanup (`freeze_subsample` stays as-is — FU-P2-2). Stop-and-show
before commit.

### P2-CB3 — propagation (proposal + override + resolution end-to-end)

**Goal.** Wire the full rev-3 flow through every surface:

```text
ExperimentPlan proposal + chain override
  → ordering resolver → ResolvedOrdering
  → TrialConfig / active_params
  → engine (resolved only)
  → records / run_config / manifest (full septet)
  → interpreter-visible execution context (resolved = what ran)
```

Last because it depends on the vocabulary + resolver (CB1) and the
engine behavior (CB2).

**Scope.**
- Changes: `core/sandbox_executor.py` (`execute_training` `:680-691`
  + append-when-set block `:770-773`; stub twin `:1357-1369`),
  `agent/skills/training_skill/wrapper.py`,
  `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py`
  (resolver call at the per-round assembly near
  `_resolve_sample_set_cfg` `:729-777` / plan intake `:2265-2330`;
  TrialConfig build `:2357-2379`; `active_params` `:2447-2460`; CLI
  + `input_dict` `:4229-4584` region; `[data_order]` resolution log
  line §3.9), `scripts/run_comparison.py` (agent-phase forwarding
  `:722-737`, CLI `:959-972` region),
  `sdsc_submission_scripts/run_one_iteration.py`,
  `sdsc_submission_scripts/_chain_common.sh` (override parse arm +
  forward-when-set — PR 1 pattern),
  `agent/schemas/interpretation.py` (`ModelRunSummary` resolved-
  ordering exposure — exact field placement after inspecting the
  summary construction site), plus tests.
- Non-goals / must-not-change: `run_baseline_trial` baseline
  behavior unchanged (no ordering on the baseline path — frozen
  comparison anchor); defaults preserve today's behavior at every
  hop; no claim of intelligent agent USE of the proposal fields
  (information flow only).
- Dependencies: P2-CB1 (schema + resolver) + P2-CB2 (engine).

**Implementation plan.**
- [x] Tuner: extract the ordering proposal from the validated
      `ExperimentPlan`; combine with the operator override via the
      CB1 resolver at the per-round assembly; emit the
      `[data_order]` resolution line; populate `TrialConfig`
      resolved fields + the record/run_config nonet.
      *(CB3-c. Plan intake switched to `parse_with_fallback` so a
      discarded proposal is reported; the single `resolve_ordering`
      call sits immediately before `TrialConfig` construction.
      **Record stamps are applied for EVERY round, deliberately
      OUTSIDE the `if trial_config.is_trial:` block** — ordering
      applies to all training, unlike the trial-only sampling
      provenance next to it. `run_config` records only the
      OVERRIDE (the run's control policy); per-round resolved values
      live on each record, since they may differ round to round.
      Lock wiring passes the override to `build_run_invariants`.)*
      **Bug caught pre-commit**: the CLI initially parsed
      `--file_order_override` with `DataScope.from_cli`, which SORTS
      and dedupes (verified: `"4,6,5,9,7,8"` → `[4,5,6,7,8,9]`).
      That would have silently rewritten every operator permutation
      into ascending order — the feature would appear to work while
      doing nothing. Replaced with a dedicated order-preserving
      `parse_file_order_cli()` in `agent/schemas/ordering.py`
      (shared by all three CLIs; rejects range syntax, which cannot
      express a permutation), with a regression test that fails
      loudly if anyone "simplifies" it back.
      **Second bug caught pre-commit**: ruff F821 flagged
      `resolved_scope` as undefined at the resolver call — the
      in-scope name is `resolved_data_scope`. Would have been a
      NameError on the first round of any real run.
      **Test-authoring note (not a production issue), recorded so
      the mistake is not repeated**: `execute_training` has TWO
      launch paths — `_run_subprocess_with_watchdog` ONLY when a
      runtime policy with the watchdog enabled is supplied, and
      plain `subprocess.run` otherwise. A propagation test that
      patches the watchdog helper while passing no policy therefore
      launches REAL training (observed: a 316 s hang before being
      killed). **The correct patch point for argv-capture tests is
      `core.sandbox_executor.subprocess.run`.** Documented in the
      `_launch` helper's docstring in
      `tests/unit/core/test_ordering_propagation.py`.
- [x] `execute_training`: named RESOLVED params
      (`order_strategy`/`file_order` at this boundary carry
      resolver output — execution-facing name kept for
      compatibility, mapping documented per §3.7); write the
      file-order JSON next to the sample-set file; append flags
      when non-default; stub twin mirrors.
- [x] `training_skill` wrapper: forward both via `kwargs.get`
      *(`wrapper.py:21-22`; defaults to `"shuffle"` / `None` so a
      caller that knows nothing about ordering is unaffected).*
- [x] Chain scripts + `run_comparison.py` + tuner CLI: OVERRIDE
      surface parse + forward-when-set; override recorded into
      `run_invariants` at chain start (CB1 lock fields).
      *(CB3-d2. Names kept: `--order_strategy_override` /
      `--file_order_override`; shell `ORDER_STRATEGY_OVERRIDE` /
      `FILE_ORDER_OVERRIDE` default `""` ≡ Python `None`, forwarded
      only when set, so an unset override reproduces pre-V19 argv on
      both layers. Both flags added to `CONTRACT_FLAGS` in
      `test_chain_consistency.py`, so the existing shell↔Python
      parity machinery now enforces their defaults and shapes.
      `run_workflow` and the tune protocol gained the override as
      NAMED parameters, same discipline as PR 1's incumbent
      reference. `run_comparison.py` forwards to the AGENT phase
      only — `run_baseline_trial` is deliberately untouched, since
      the baseline is the frozen comparison anchor and must stay on
      the pre-V19 global shuffle; a test asserts no ordering symbol
      appears in that function. Baseline and agent workspaces were
      verified distinct, so the baseline's no-override lock cannot
      collide with the agent phase's.)*
      **Blocker found and fixed during implementation**:
      `workflows/model_exploration.py:1773` also calls
      `ensure_run_invariants`. With CB1-c having added the override
      to the canonical lock set, the workflow would have written a
      NO-override lock into the same workspace the tuner writes an
      override lock into — a guaranteed `RunInvariantsViolation`
      aborting every run that used the feature. All three lock sites
      (tuner, workflow, chain runner) now pass the override, and a
      regression test parses each `build_run_invariants(...)` call
      and fails if any omits it — this class of bug is invisible
      until runtime.
- [x] Manifest (`run_one_iteration.py::write_manifest`): ordering
      provenance as a round/experiment-KEYED list per the §3.7
      granularity rule (each entry: `exp_id` + nonet; never one
      unlabelled iteration-level value).
      *(CB3-d1. Field name chosen after inspection:
      `ordering_by_experiment`, a list built by
      `_ordering_by_experiment()` from `tune_output.all_records`;
      each entry carries `exp_id`, `round_index` (from
      `memory.round_index`), and the full nonet. Best-effort per
      record — the manifest is a handoff aid, so a malformed record
      must not fail an otherwise-successful iteration. Absent
      entirely on `crashed` / `no_records` manifests, which have no
      ordering to report. **The legacy-read rule was factored into
      ONE place** — `ResolvedOrdering.from_record()` (duck-typed, so
      `ordering.py` stays free of a schema import cycle) — and the
      CB3-b interpreter reader was refactored onto it, so the
      manifest and the interpreter cannot drift on "no
      `resolved_order_strategy` means legacy_default".
      8 tests incl. the operator-required two-round
      differing-ordering case (two distinct keyed entries) and a
      guard asserting NO iteration-level ordering key exists.
      `tests/unit/sdsc_submission_scripts` +
      `result_interpretation_agent` + `agent/schemas` →
      **468 passed in 1.57s**; ruff clean.)*
- [x] `ModelRunSummary`: resolved-ordering field(s) exposed to the
      interpreter as the factual execution configuration.
      *(CB3-b. New `RoundOrdering` model in
      `agent/schemas/interpretation.py` + `ModelRunSummary.
      round_ordering: list[RoundOrdering]`, PARALLEL to the existing
      `round_scores` / `round_conclusions` lists — that is how this
      schema already associates per-round facts with rounds, and it
      satisfies the §3.7 granularity rule without inventing a new
      shape. Each entry carries `exp_id`, resolved strategy + file
      order, resolution source, and the rejection pair. Populated by
      a new `_round_ordering()` helper in
      `tuning_output_to_model_run_summary`; records predating the
      option read explicitly as `legacy_default`, never guessed.
      6 tests: per-round distinctness, overridden proposal not
      presented as executed, rejected proposal visible AS rejected,
      silence-vs-rejection distinguishable, legacy read, JSON
      round-trip. `tests/unit/agent/result_interpretation_agent` +
      `protocols` → **313 passed in 1.16s**; ruff clean.)*

**Validation plan.**
- Unit (per-hop forwarding): sandbox call → subprocess argv carries
  RESOLVED values exactly when non-default and never otherwise;
  wrapper passthrough; tuner CLI → input schema values; override →
  lock write.
- Pseudo integration — the three resolution cases (operator-
  required), each asserting record + run_config + manifest +
  interpreter-visible context agree:
  1. **proposal wins**: plan proposes `sequential`, no override →
     sequential executes, source=`agent_proposal`;
  2. **override wins**: plan proposes `sequential`, override
     `shuffle` → shuffle executes, source=`operator_override`, and
     the record still shows the proposal (never described as
     executed);
  3. **default wins**: no proposal, no override → shuffle executes,
     source=`default`, training argv identical to pre-PR2.
- Negative (propagation failure surface): a hop that drops a field
  is caught by the end-to-end assertion (stamped septet must equal
  the known inputs, not defaults).
- Manifest granularity (§3.7 rule): a two-round pseudo iteration
  with DIFFERING resolved ordering across rounds yields two keyed
  manifest entries (exp_id + septet each); no unlabelled
  iteration-level collapse; interpreter-facing summary associates
  each resolved ordering with the correct model/round.
- Resume (chain level, pseudo): override fixed across resume
  (violation cases covered at CB1 unit level); no-override chain
  with different proposals across iterations → each iteration's
  record shows its own resolved ordering.
- Backward-compat: chain shell parity test green; legacy-workspace
  resume read-path (§3.7 legacy rules) exercised; full targeted
  regression on workflows + protocols + tune suites.
- Gate tests: NONE launched from this commit. P2-V2 (real training)
  is listed separately in §0/§7.2 and requires explicit operator
  approval of a shown launch plan.

**Acceptance criteria.**
- With no proposal and no override, the training subprocess argv is
  IDENTICAL to pre-PR2 argv (asserted, not assumed).
- All three resolution cases hold end-to-end with record,
  run_config, manifest, and interpreter-visible context in
  agreement on (proposed, override, resolved, source) — and an
  overridden proposal is never described as executed anywhere in
  those artifacts.
- The engine subprocess receives resolved values ONLY (its argv
  contains no proposal/override material — asserted).
- The interpreter-facing summary identifies the resolved ordering
  as the actual executed setting.
- The stub sandbox accepts the same call signature as the real one
  (pseudo mode cannot drift).
- Shell parity: `_chain_common.sh` override arm round-trips the
  values into `run_one_iteration.py` argv verbatim.

**Failure and edge cases.**
- `file_order` without `sequential` at any intake (plan or
  override): rejected at that intake's structural layer with the
  CB1 error — never silently ignored.
- Structurally invalid proposal + winning override: proposal error
  surfaced (D5 rule) — the chain does not proceed on hidden-invalid
  agent output.
- Chain script arm set but iteration script older (skew): the PR 1
  forward-when-set pattern makes the flag absence a hard argparse
  error, not silent drop — verified by the parity test.
- Legacy resumes (pre-PR2 workspaces): absence of ordering fields in
  old records/manifests must not break resume reads; lock without
  ordering keys = no-override (§3.8) — re-verified at this level in
  the pseudo test.

**Verification commands and evidence.**
*(run 2026-07-28, lilab; split across the CB3-c / d1 / d2 commits)*
- [x] `tests/unit/core` + `tests/unit/agent/schemas` →
      **626 passed** (CB3-c).
- [x] `tests/unit/agent/tune_ml_hyperparam_agent` →
      **690 passed in 164.44s** (CB3-c).
- [x] `tests/unit/sdsc_submission_scripts` +
      `result_interpretation_agent` + `agent/schemas` →
      **468 passed in 1.57s** (CB3-d1).
- [x] `tests/unit/scripts` + `sdsc_submission_scripts` +
      `protocols` + `workflows` → **473 passed in 11.84s** (CB3-d2).
- [x] Pseudo integration:
      `tests/integration/workflows/test_ordering_resolution_pseudo.py`
      → **7 passed in 1.95s** (recorded under P2-V1).
- [x] `ruff check` + `ruff format --check` clean on every touched
      file in all three commits.
- [x] Tests NOT run, with reason: no Gate tests (P2-V2 is separate
      and operator-approved); `pyright` not run (lilab Node < 14,
      PR #123 precedent).

**Commit boundary.** Propagation + its tests ONLY. No engine or
schema changes (fixes discovered here go back to CB1/CB2 as
amendments, shown to operator). Stop-and-show before commit.

### P2-V1 — pre-gate sweep (after CB3)

- [x] Pseudo integration: every resolution case deterministic
      end-to-end.
      *(NEW `tests/integration/workflows/test_ordering_resolution_pseudo.py`,
      **7 passed in 1.95s**. Drives the PRODUCTION path — real
      `run_workflow` (agents mocked at the workflow boundary, no LLM,
      no training) + the real `write_manifest` the chain runner uses,
      reusing the PR 1 P1-V1 harness shape. Cases: proposal wins;
      override wins AND is not attributed to the agent; default
      wins; rejected proposal + no override; rejected proposal +
      override; two-round granularity; manifest block survives to
      disk. Each case asserts record, manifest, and
      interpreter-facing summary tell ONE story via a shared
      `_assert_agree` helper.
      Harness fix during authoring (test-side only): iteration 1
      loads a seed tuning output from
      `{data_dir}/{model}/{source_run}/agent/run_output_*.json`
      before any node runs, so the harness seeds one per test under
      `tmp_path` instead of pointing at a nonexistent `/tmp/data`.)*
- [x] Full unit sweep, one run, counts recorded here.
      *(`.venv/bin/python -m pytest tests/unit -q` →
      **4475 passed, 1 failed, 3 xfailed in 204.10s**. The single
      failure is FU-P2-4
      (`test_scoring_helpers.py::TestPostPathAReferenceConsistency`),
      identified during P2-CA and PROVEN pre-existing by stashing all
      PR-2 changes and reproducing it byte-identically. It is
      skip-guarded on machines without the ground-truth data, so CI
      never sees it. Unrelated to ordering.)*
- [x] Integration sweep.
      *(`pytest tests/integration/workflows -q` →
      **32 passed, 8 skipped, 1 failed in 202.36s**. The failure is
      `test_vocab_accumulation::test_vocab_candidate_promotion_across_three_iterations`
      = **FU-7**, already recorded in
      `docs/design/enable_partial_file_list.md` as pre-existing and
      confirmed broken on master `9e503ea` on 2026-07-23. Root cause
      is a stale test double: `RecordingLLMBridge` lacks
      `emit_marker`, so the interpretation flow degrades and
      `prediction_evaluation` is None. This branch touched neither
      `agent/llm_bridge.py` nor that test.)*
- [x] Evidence recorded in this doc (boxes above ticked with test
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

### P2-DOC — node/skill documentation sync (very last step before merge)

**Goal.** Keep the per-node and per-skill `.md` files truthful for a
large codebase: every CLI argument, default value, and behavior
explanation introduced by this PR is documented where an operator
looks for it. Operator rule (2026-07-28), standing for all future
PRs: every updated skill and every updated node gets its relevant
`.md` updated; done as the final pre-merge step so the docs describe
the code as actually merged, not as designed.

**Scope.** Enumerate touched nodes/skills from the final PR diff (do
not rely on this list alone); known targets from the plan:
- [x] `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md`
      *(three additions: a "Data ordering (V19 PR 2)" Input subsection
      with both override fields and the precedence rule; both CLI
      flags in the arguments table with exact defaults and the
      range-syntax rejection; and a "Data-ordering resolution"
      four-part contract in Key behavioral notes — resolution +
      `[data_order]` lines, file-order semantics, rejected proposals
      recorded not dropped, and the three-artifact persistence
      split — stating the attribution invariant verbatim.)*
- [x] `docs/running_chain_test.md`
      *(new "Data-ordering override (V19 PR 2)" section beside the
      PR 1 coupling one: both flags in a table, the two chain modes
      (forced comparison vs agent exploration), the lock-the-override
      resume rule with its new-workspace requirement, and where to
      look afterwards — the two `[data_order]` log lines and the
      manifest block.)*
- [x] `agent/skills/training_skill/training_skill.md` — CREATED
      *(no skill in the repo had a `.md`; this is the first, so it
      follows the node-doc house style. Documents the full `kwargs`
      contract incl. the resolved ordering pair, and states the two
      load-bearing facts: the values arriving here are ALREADY
      resolved and this layer never re-derives precedence, and the
      stub mirrors the signature so pseudo mode cannot drift from
      production at the call boundary.)*
- [x] `nodes/result_interpretation_agent/result_interpretation_agent.md`
      *(new Key-behavioral-note covering `round_ordering`: the two
      rules for downstream use — resolved-only describes execution,
      and a rejected proposal is not agent silence — plus why it is
      per-round rather than per-run, and the `legacy_default` read.)*
- [ ] Diff sweep: any other touched node/skill `.md` (check
      `nodes/*/`*.md` against the PR's touched-file list); confirm
      or update each — record "no update needed" per file
      explicitly, never silently.

**Acceptance criteria.** For every touched node/skill, its `.md`
states the new arguments with their exact defaults and semantics; a
reader can operate the feature from the docs alone without reading
the argparse source.

**Verification.**
- [ ] Cross-check each documented flag/default against the merged
      argparse/schema source (values quoted, not paraphrased).
- [ ] Evidence recorded here (files updated + one-line summary each).

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
  for both strategies (unchanged global floor; asserted by test —
  NO code change in `workload_resolvers.py`).
- Second-dataset contract test + filename-pattern validation tests
  (commit A).
- **Resolution logic (rev 3, one deterministic test per row)**:
  - proposal `sequential` + no override → `sequential`;
  - proposal `shuffle` + no override → `shuffle`;
  - no proposal + no override → default `shuffle`;
  - proposal `sequential` + override `shuffle` → `shuffle`;
  - proposal `shuffle` + override `sequential` → `sequential`;
  - override `sequential`, no file order → ascending resolved scope;
  - invalid override permutation → startup failure;
  - structurally invalid proposal + valid override → proposal error
    surfaced (D5 rule: every provided value structurally valid even
    if overridden; scope-dependent validation on the resolved value).
- **Attribution and recording (rev 3)**:
  - engine receives resolved values only;
  - record contains proposed, override, resolved, and source;
  - run_config and manifest agree;
  - interpreter-facing data identifies resolved ordering as what
    ran;
  - an overridden proposal is never described as executed.
- **Chain behavior (rev 3)**:
  - fixed override cannot change during resume (strategy or file
    order → `RunInvariantsViolation`);
  - agent proposal may change across iterations when no override
    exists — allowed and recorded per iteration;
  - each iteration records its own resolved ordering;
  - separate chains can force different strategies for controlled
    comparisons (forced-comparison mode);
  - legacy workspaces without override fields → §3.8 explicit
    compatibility behavior.

### 7.2 P2-V2 real smoke (bounded, operator-approved launch)

Cold-start (standing rule), DS8-paired partial scope, smallest
canonical config; one attempt with a forced `sequential` override
proving: the expected resolved strategy and file order actually
selected — both `[data_order]` lines (§3.9) quoted verbatim as
evidence; RT2 §12 ledger entry within tolerance; HealthGate pipeline
unaffected. Launch plan drafted for approval at P2-V1 exit.

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
- **FU-P2-4** ([issue #138](https://github.com/Galileo-Sandbox/SIDERIUS/issues/138); DIAGNOSED and marked
  as a known defect, NOT fixed — operator decision required) — the
  on-disk ground-truth artifacts and the current production formula
  are on different rulers. Root cause proven bit-exactly:

  ```text
  ceiling file_vector[0]           = 1.0892888977496993e-06
  on-disk per-file score           = -8.260916269975333
  log_5.27(file_vector[0])         = -8.260971502899364  [current helper]
  log_5.27(file_vector[0] + 1e-10) = -8.260916269975333  [EXACT match]
  ```

  The artifacts record `computed_at: 2026-05-01` and used the legacy
  `1e-10` soft floor; `file_vector_to_log_space` has since removed it
  ("that was outdated and is removed").

  **The test is NOT stale — it is correctly reporting a real
  inconsistency**, exactly the drift its own docstring says it exists
  to catch (model column vs reference columns on different rulers).
  The assertion and its `rel=1e-9` tolerance are therefore UNCHANGED;
  the test carries `pytest.mark.xfail(strict=False)` with the full
  diagnosis, so the suite is green today and this flips to XPASS the
  moment the mismatch is resolved.

  **Resolution requires a separate operator decision** — either
  regenerate the reference artifacts under the current formula, or
  preserve an explicit legacy-reference conversion path for
  pre-2026-05-01 artifacts. Both touch frozen reference data.
  **No reference-data or scoring-formula change is included in
  PR 2** (operator instruction, 2026-07-28).
