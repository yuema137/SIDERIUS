# Design: Enable Partial-File Training via `DataScope` (`enable_partial_file_list`)

**Status**: Draft — design approved through three audit rounds (2026-07-22),
implementation not started
**Author**: Yue Ma
**Created**: 2026-07-22
**Revised**: 2026-07-22 (round 3: HealthGate enable flag, materialized effective
config, schema/runtime validation split, proposer-channel correction,
behavioral-identity guarantee, atomic lock, functional campaign identity;
round 4: HealthGate policy lock — `data_scope_lock.json` generalized to
`run_invariants_lock.json` pinning scope + `health_gate_enabled` +
effective-config sha256, so resume cannot silently change HealthGate semantics)
**Branch**: (new branch, to be created)
**Depends on**: nothing (builds on committed anchor map from PR #127 and
seedless cold-start from PR #126)
**Unblocks**: scope-restricted exploration campaigns; V18 scope-keyed incumbent
design

---

## Development principles

Same four rules as all SIDERIUS design docs:

1. **Check, don't guess.** Read source before making claims. If the answer isn't
   in the code, ask the user.
2. **Keep design doc and code in lock-step.** Tick `[ ] → [x]` as work lands;
   record test results inline in each commit's *Implementation notes*.
3. **Stop before each commit.** Show progress + implementation details; wait for
   explicit approval before `git commit`. Tests run freely except real-LLM +
   real-training combos.
4. **Split logical commits at clean seams.** Each `Commit DS*` is the logical
   unit; split further if the actual diff is too large.

---

## Background and limitation

SIDERIUS currently always trains, infers, and scores against the **complete**
TIDMAD dataset (validation files 0–19). The sampling strategies (`snapshot`,
`anchors`, `target`) decide *how samples are drawn*, but nothing decides *what
data the run is allowed to access*:

- In **trial rounds**, `trial_strategy` / `target_files` / `eval_strategy` come
  from the **LLM plan** (`_resolve_sample_set_cfg`,
  `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py:721-728`).
  A prompt instruction like "only use files 4–9" is never guaranteed.
- In **formal rounds**, strategy comes from the operator (`formal_strategy`),
  but `target_files` is hardcoded to `[]` for non-trial plans (`:1799`), so
  `formal_strategy="target"` crashes in `build_sample_set` and there is no way
  to run a formal round on a file subset. Formal eval is locked to `snapshot`
  over all 20 files.
- The operator-side input fields `HyperparamTuningInput.trial_strategy` /
  `eval_strategy` / `target_files` are threaded from the chain CLI all the way
  into the input schema **but never read by the tuner loop** (dead fields —
  confirmed by exhaustive grep, 2026-07-22 audit). The protocol
  `local_full_context` also copies them into `ProposalInput.trial_strategy` /
  `target_files` (`workflows/model_exploration.py:1994-2006`,
  `agent/schemas/proposal.py:689,702`), but the round-3 audit confirmed the
  proposer never consumes those two fields either (see *Proposer channel* below)
  — they are dead at **both ends** of that edge.
- `plan_overrides` (`agent/schemas/hyperparam_tuning.py:1146`) can clamp the
  LLM plan (including `trial_strategy` + `target_files`), but it operates only
  on the plan: it misses formal rounds, HealthGate peeks, and baseline
  builders, and it falls back non-fail-fast to the unclamped plan when the
  merged plan fails validation
  (`ml_hyperparameter_tune_agent.py:1723-1727`).

**Consequence**: there is no runtime-enforced way to restrict a run to a file
subset (e.g. files 4–9). Prompt-level restriction is explicitly rejected — the
restriction must be enforced by schema + runtime regardless of what the LLM
proposes.

---

## Goal and expected behavior

Introduce a new layer **above** sampling:

```
DatasetConfig      — defines the complete dataset (execute_tools/dataset_config.py)
      ↓
DataScope          — defines which subset THIS RUN may access          [NEW]
      ↓
Sampling strategy  — decides how to sample within the allowed scope
      ↓
SampleSet          — the concrete realization used by execution
      ↓
Execution          — train / inference / scoring / health checks
```

Expected behavior:

1. **`DataScope`** is a small reusable Pydantic model. For TIDMAD:
   `DataScope(file_indices=[4,5,6,7,8,9])`. `DataScope.default()` = complete
   dataset, resolved from `DatasetConfig` (never hardcoded in generic code).
2. **Workflow-level input**: `run_workflow(data_scope=...)`; the resolved scope
   propagates through every downstream component (tuner, sandbox, executors,
   health checks). Default behavior preserves **behavioral identity** (see the
   dedicated section below).
3. **Runtime invariant**: no component can ever access dataset contents outside
   the resolved scope. One invariant, enforced across all three file-access
   mechanisms (see *Enforcement philosophy*).
4. **Sampling stays orthogonal**: strategies never enlarge the scope.
5. **Partial scopes allow `snapshot` only.** Full scope: all strategies remain
   legal. Partial scope: `anchors` / `target` are rejected for operator config
   and normalized-with-provenance for LLM plans (see *Strategy handling*),
   never handled by prompts alone. This rule is also what makes the HealthGate
   invariant sufficient: snapshot eval covers every scope file each round, so
   every in-scope peek target is guaranteed to have a denoised file.
6. **HealthGate becomes an explicit optional subsystem** with an enable flag
   and a run-level monitored-file list; startup invariant
   `health_gate_files ⊆ data_scope` when enabled. No automatic intersection,
   no fallback, no silent correction (see *HealthGate subsystem* below).
7. **Scalar comparability policy**: aggregate scalar scores are only comparable
   between identical resolved DataScopes. Enforced **structurally** via
   scope-homogeneity at run/workspace boundaries (not via metadata annotations
   at comparison sites). Per-file scores (`file_vector` entries) remain
   comparable across scopes because anchor normalization is per-segment with a
   global `s_max`.

---

## Audit summary (2026-07-22, three rounds)

Key verified facts this design rests on. Line numbers as of commit `9e503ea`.

### File-selection data flow

| Stage | Location | Who decides |
|---|---|---|
| Trial-round strategy + files | `plan.trial_strategy` / `plan.target_files` via `_resolve_sample_set_cfg` (`ml_hyperparameter_tune_agent.py:721-728`) | LLM |
| Formal-round strategy | `agent_input.formal_strategy`; `target_files=[]` hardcoded (`:1799`); eval locked `snapshot` (`:713-719`) | operator (target broken) |
| Plan clamp | `plan_overrides` merge (`:1710-1727`) — non-fail-fast fallback | operator |
| SampleSet construction | `build_sample_set` (`execute_tools/sample_set_builder.py:26`): `snapshot`→`range(NUM_FILES)`, `anchors`→`[0,10,19]` (`:23`), `target`→list | — |
| SampleSet validation | `validate_sample_set` (`scoring_utils.py:248`) — range check `[0, NUM_FILES)`; called from `execute_training` (`sandbox_executor.py:569`) and `execute_inference` (`:735`); **NOT called on the `score_vector` path** (`:800`) | — |
| Execution | train datasets / `inference_single.py:286` / `score_vector:527` iterate exactly the SampleSet keys | — |
| HealthGate peek | `peek_file_indices [3,10,17]` in `configs/health_checks.yaml:34,58,79`; reads denoised HDF5 directly, **bypasses SampleSet** (`_multi_file_peek.py`) | YAML |
| Independent builders | `run_comparison.py` baseline (`:366,:372,:503` hardcode snapshot); reference-generation scripts | scripts |

### Facts that shape the design

- `validate_sample_set` already **is** a DataScope check hardcoded to the full
  scope — this feature generalizes an existing invariant.
- `_multi_file_peek._apply_aggregation` (`:146-149`): `any_pass` with zero
  successful peeks → **fail**. Without the startup invariant, a partial scope
  excluding `[3,10,17]` would deterministically invalidate every round.
- **The health-config plumbing is path-based, with independent reload sites**
  (round-3 audit, drives the *materialized effective config* design):
  - `evaluate_and_persist_health_gates(config_path=...)` reloads the config
    (`evaluation.py:239`) and passes the **path** down into `evaluate_gate`,
    which reloads again (`runner.py:106-108`).
  - `get_gates_for_position(round_index, config_path=...)` reloads
    (`runner.py:77-79`; tuner call at `:2446-2452`).
  - `is_valid_candidate` → `required_blocking_gate_ids()`
    (`candidate_eligibility.py:37-46`) loads the **shipped production**
    `configs/health_checks.yaml` from a hardcoded repo-relative path — it
    ignores `agent_input.health_checks_config` entirely. This is deliberate
    (PR #124: eligibility is judged against production *policy*) and reads
    only gate IDs + `on_fail` actions, never `peek_file_indices` — so the
    monitored-file override is semantically irrelevant at this site.
  - The production-policy config inside `evaluate_and_persist_health_gates`
    is consumed only as `production_by_id.get(gate.id)` → `_persist(...)`
    (`evaluation.py:243,253-265`): it **re-interprets recorded results under
    production actions**; it never re-runs checks, so its peek files are
    never read. The monitored-file override therefore only needs to reach
    the **active** config.
  - `load_health_gates_config` is cached per-process keyed on path
    (`config.py:221`). Any in-memory-object override would be silently
    bypassed at every path-based reload site above.
- The delta-gate anchor `current_run_best_formal_score` defaults to **0.0**
  (V17 fixed reference, `hyperparam_tuning.py:990`; the 5.5763 default was
  removed by PR #124 as the class-127 collapse fingerprint). 0.0 is
  scope-neutral. Cross-iteration propagation happens at
  `workflows/model_exploration.py:2349`.
- `_merge_score_validity_failure` (`ml_hyperparameter_tune_agent.py:616`)
  flags non-finite scores as collapse **independent of configured gates** —
  it is score-validity, not health-gating, and stays active even when the
  HealthGate subsystem is disabled.
- Scalar ingress points (cross-run risk): `--seed_paths`
  (`run_one_iteration.py:427`), `HyperparamTuningInput.seed_records` (`:1241`),
  `core/resume.restore_prior_state`, `run_comparison.seed_agent_memory`,
  Phase-1 baseline reuse + campaign manifest (`core/campaign_artifacts.py` —
  identity is `campaign_run_name` only; no scope field).
- Dead-field compat surfaces: `_chain_common.sh:215,222,304,332` forwards
  `--trial_strategy` / `--target_files`; tuner CLI `--trial_strategy` /
  `--eval_strategy` (`:3469,:3482`) feed only the dead input fields;
  `run_config_{run_name}.json` does **not** serialize them (`:1455-1470`);
  `HyperparamTuningInput` does not set `extra="forbid"`, so removing fields is
  serialization-safe. `ExperimentRecord.trial_strategy` / `target_files`
  (`:2973-2979`) are live per-round provenance — keep.
- **Pre-existing latent bug (out of scope, file as issue in DS8)**: under the
  full scope, an LLM-chosen `eval_strategy="target"` in a trial round leaves
  peek files `[3,10,17]` un-denoised → all peeks I/O-fail → blocking gates
  invalidate the round spuriously. Exists today without DataScope.

### Proposer channel (round-3 re-audit — corrected)

`ProposalInput.trial_strategy` and `ProposalInput.target_files` are consumed by
**nobody**:

- The proposer node reads `inp.is_trial` (budget selection, proposer `:62-63`)
  and `inp.trial_portion` / `inp.train_portion` (pre-flight time gate, `:167`)
  — never `trial_strategy` / `target_files` (exhaustive grep over the node,
  `nodes/proposal_helpers.py`, and all proposal prompt templates: zero hits).
- The pre-flight synthesizes its sample set with a **hardcoded**
  `trial_strategy="snapshot"` (`agent/utils/proposer_preflight.py:61-64`).
- The "Mirrors HyperparamTuningInput..." docstrings (`proposal.py:689-705`)
  describe intent that was never wired.

Migration decision (replaces the earlier "replace fields with DataScope" plan):

1. **Delete** `ProposalInput.trial_strategy` / `target_files` — they have no
   current function to replace. `is_trial` / `trial_portion` / `train_portion`
   are live and stay.
2. **Add** `ProposalInput.data_scope` for a *new* purpose:
   (a) the pre-flight `_synthesise_default_sample_set` builds its synthetic
   snapshot **within scope**, so the wall-time estimate matches what the tuner
   will actually run (this finally delivers what the dead fields' docstrings
   promised); (b) prompt disclosure so the proposer does not design for
   out-of-scope data.
3. **Execution provenance is not lost**: per-round strategy provenance lives in
   `ExperimentRecord.trial_strategy` / `target_files` and flows to the
   interpreter with the records; sampling coverage reaches the proposer via
   the score tables' `sample_size` (`agent/schemas/score_table.py:145`).
   `ModelRunSummary` does not currently summarize per-round strategy — that
   was true before this feature and is unchanged by it. If the proposer ever
   needs per-round strategy provenance, it should come from
   `ExperimentRecord → ModelRunSummary` (tracked as FU-5, not this feature).

### Enforcement philosophy (one invariant, three mechanisms)

| Layer | Mechanism | Role |
|---|---|---|
| Constructive | `build_sample_set(scope=...)` | SampleSets satisfy the scope by construction; single point covering trial train/eval, formal train/eval, single-file |
| Boundary invariant | `validate_sample_set(sample_set, scope)` at the sandbox (train / inference / **score_vector**) | Final safety guarantee before any file I/O; catches callers that build SampleSets themselves |
| Direct-access paths | HealthGate subsystem input + materialized effective config + startup subset validation | Paths that bypass SampleSet become explicitly scope-aware; no silent correction |

---

## `DataScope` — model sketch

Lives in `execute_tools/dataset_config.py` next to `DatasetConfig` (pure
Pydantic, no heavy deps — importable by both the schema layer and executors
without cycles).

```python
class DataScope(BaseModel):
    """Which subset of the dataset this run may access.

    ``file_indices=None`` means the complete dataset. "File" is the dataset's
    partition unit as defined by ``DatasetConfig`` file patterns — future
    datasets map their own partition notion onto integer indices.
    """
    model_config = ConfigDict(frozen=True)

    file_indices: list[int] | None = None   # validator: sorted, deduped, non-empty when provided

    @classmethod
    def default(cls) -> "DataScope": ...                       # complete dataset

    def resolve(self, dataset: DatasetConfig) -> list[int]: ...  # None → list(range(num_files));
                                                                 # validates ⊆ [0, num_files); raises ValueError otherwise

    def is_full(self, dataset: DatasetConfig) -> bool: ...
```

Deliberately thin (per the multi-dataset TODO in `docs/architecture.md`:
"do not design this abstraction speculatively"). When a second dataset lands,
`DataScope` can grow a discriminated union (index / time-range / named-split
scopes) without touching `resolve()` consumers.

**Serialization**: the *resolved* scope (sorted list of ints) is what gets
stamped into records, outputs, manifests, and the workspace lock — never the
unresolved `None`. Records lacking a scope stamp are unambiguously full-scope
(all pre-feature records were produced that way).

---

## Schema vs runtime validation (round-3 split)

Whether a scope is "full" depends on the dataset definition — runtime
information, not schema information. Validation responsibilities are therefore
split:

**Schema validators** (Pydantic, dataset-independent internal consistency
only):
- `DataScope.file_indices` non-empty / deduped / sorted / non-negative.
- `health_gate_enabled=False` + `health_gate_files is not None` →
  `ValidationError`.
- `health_gate_files == []` → `ValidationError` (monitoring nothing must be
  expressed as `health_gate_enabled=False` or an observe/disabled gate config,
  never an empty file list).

**Startup runtime validation** (`validate_runtime_config(agent_input,
dataset)` — new helper, called at tuner `run()` entry and workflow pre-flight,
after schema parse, before any LLM call or file I/O):

```
parse schema  →  resolve DataScope against DatasetConfig  →  validate resolved runtime configuration
```

- `resolve()` bound check (indices ⊆ `[0, num_files)`).
- Partial scope + `formal_strategy != "snapshot"` → error (illegal operator
  configuration).
- Single-file mode: `file_index ∈ scope`.
- HealthGate requirements (next section).
- Ingress scope-homogeneity checks (seeds / resume / baseline).

All startup errors fail before round 1, with remediation text.

---

## Strategy handling (round-3 clarification)

Three situations, three behaviors:

| Situation | Behavior |
|---|---|
| **Operator configuration** (`formal_strategy`, `file_index`, CLI values) | Illegal combination with a partial scope → **startup validation error**. Operators get no normalization — their config is a contract. |
| **LLM-generated plans** (`plan.trial_strategy` / `plan.eval_strategy` under a partial scope) | **Normalize to `snapshot` with explicit provenance** rather than wasting a round. Persist on the round's `ExperimentRecord`: `planned_trial_strategy`, `effective_trial_strategy`, `planned_eval_strategy`, `effective_eval_strategy`, `strategy_normalization_reason` (e.g. `"partial_data_scope"`, `None` when no normalization occurred). Log loudly (`[DATASCOPE] normalized trial_strategy: target → snapshot (partial scope)`). The planner is informed of the rule up front via the fixed-params block (`agent/prompts.py:706`), so normalizations should be rare. |
| **Runtime** | If an illegal SampleSet somehow reaches execution, the sandbox boundary invariant (DS3) **fails hard**. Normalization is a courtesy at the plan layer; the sandbox is the guarantee. |

---

## HealthGate subsystem (round-3 redesign)

### API

```python
health_gate_enabled: bool = True
health_gate_files: list[int] | None = None
```

Semantics:

| `enabled` | `files` | Scope | Behavior |
|---|---|---|---|
| `False` | `None` | any | HealthGate fully disabled: no gate evaluation, no persistence, no monitored files required |
| `False` | provided | — | **schema `ValidationError`** (internally inconsistent input) |
| `True` | `None` | full | YAML default `peek_file_indices` used as-is (current behavior) |
| `True` | `None` | partial | **startup error** — explicit `health_gate_files` is a requirement; there is no automatic default |
| `True` | provided | any | shared list uniformly replaces every gate's `peek_file_indices`; startup invariant `files ⊆ resolved scope`, else **startup error** |
| `True` | `[]` | — | **schema `ValidationError`** |

No automatic intersection, no fallback, no silent correction — ever.

**v1 simplification (intentional, explicit)**: one shared monitored-file list
overrides **all** gates uniformly. Per-gate monitored-file customization is out
of scope for v1; anyone needing it authors a custom YAML.

### Disabled mode — precise semantics

- The tuner skips the entire gate block (`get_gates_for_position` /
  `evaluate_and_persist_health_gates`, `:2446-2485`); round records carry
  `health_gate_results=[]`.
- `_merge_score_validity_failure` **stays active** — non-finite scores are
  still classified as collapse (score-validity, not health-gating).
- **Valid-candidate eligibility**: the three `is_valid_candidate` call sites
  (`:176, :1657, :3188`) pass `required_gate_ids=frozenset()` when disabled.
  Mechanism (verified against `classify_candidate_health`,
  `candidate_eligibility.py:49-91`): an empty required set makes
  `required.issubset(results)` trivially true and the per-gate loop empty, so
  successful finite-score records classify **VALID**. The operator explicitly
  waived health validation; records are eligible on success + finite score
  alone. No change to `candidate_eligibility.py` logic is needed.
- The run output records `health_gate_enabled=False` so downstream consumers
  (interpretation, reports) can see that gate absence was deliberate.

### Override propagation — materialized effective config

Because the plumbing is **path-based with at least four independent reload
sites** (audit above), an in-memory config-object override would be silently
bypassed. Design:

1. At startup (after `validate_runtime_config`), when
   `health_gate_enabled=True`, the tuner **materializes the effective config**:
   load the operator's config (or shipped default), apply
   `apply_monitored_files(config, files)` (pure transform → new
   `HealthChecksConfig`; no-op when `health_gate_files is None`), run
   `validate_health_scope(effective, resolved_scope)`, and write the result to
   `{workspace}/health_checks_effective.yaml`.
2. `agent_input.health_checks_config` is **replaced by the materialized path**
   for the remainder of the run. Every downstream path-based loader
   (`get_gates_for_position`, `evaluate_gate`,
   `evaluate_and_persist_health_gates`, output persistence at `:3227`) then
   picks up the effective config through the existing mechanism and cache
   (new path = new cache entry; the original YAML and its cache entry are
   never touched).
3. Provenance: `run_config_{run_name}.json` records both
   `health_checks_config_source` (operator-supplied path or
   `"(shipped default)"`) and `health_checks_config_effective` (materialized
   path). The materialized file doubles as replay provenance, mirroring
   `task_config_snapshot.yaml`.
4. Configs that participate only as **policy re-interpreters** need no file
   override (verified): the production-policy config inside
   `evaluate_and_persist_health_gates` contributes only gate actions to
   `_persist` (`evaluation.py:243`), and
   `candidate_eligibility.required_blocking_gate_ids` reads only gate IDs +
   `on_fail` actions. Neither ever reads `peek_file_indices`. Both are still
   listed in the DS4 verification checklist so this stays audited, not
   assumed.
5. `run_comparison.py`: same materialization at campaign startup; the
   `v17_pregate_baseline` policy pin (`:908`) compares the **source** config
   and forbids `health_gate_files` overrides for that campaign.

### Policy lock — workspace-immutable HealthGate semantics (round-4 addition)

The materialized effective config is a **workspace-locked artifact**, pinned by
the same lock that protects the DataScope (see *Run-invariants lock* below).
Rationale — a resume that changes gate policy mid-workspace does not merely
affect future rounds, it **retroactively relabels past ones**: candidate
eligibility derives its required-gate set from a config loaded at *selection*
time, not at recording time (`candidate_eligibility.py:37-46`), so a policy
change flips already-persisted records between VALID / INVALID / UNKNOWN, and
best-valid tracking + formal winner inheritance then compare records whose
validity labels were assigned under different laws. Policy-homogeneity is a
precondition for record comparability, exactly like scope-homogeneity.

Semantics:

- First workspace initialization records `health_gate_enabled` and (when
  enabled) `health_config_sha256` = sha256 of the canonical serialized
  effective config, alongside the resolved scope, in the run-invariants lock.
- Every later execution (chain iterations, `--resume`, standalone tuner runs
  against the same workspace) **re-materializes and compares hashes**;
  mismatch → startup failure naming what drifted (operator inputs changed vs.
  upstream YAML content changed, e.g. a mid-campaign `git pull` editing the
  shipped `configs/health_checks.yaml`).
- `health_gate_enabled` is part of the locked identity — flipping
  enabled ↔ disabled on resume is a lock violation (a content hash alone
  cannot catch it: disabled runs have no effective file).
- No escape hatch in v1: a deliberate policy change means a new workspace
  (tracked as FU-6 if an operational need for explicit migration appears).
- Precedent: `_write_diagnostic_metadata` already snapshots the
  HealthGate-config hash for diagnostic runs (PR #117); the v17_pregate
  campaign pins its policy file (`run_comparison.py:908`). The lock
  generalizes both.

---

## Default-behavior guarantee (round-3 narrowing)

The guarantee for `DataScope.default()` + `health_gate_enabled=True` +
`health_gate_files=None` is **behavioral identity**, not byte-identity of
serialized artifacts:

Identical:
- SampleSets (same seeds → same file/segment selections; RNG consumption
  order unchanged),
- training behavior, inference behavior, scoring results,
- HealthGate evaluation behavior (same gates, same peek files, same actions).

Naturally different:
- metadata gains new fields (`resolved_data_scope`, `health_gate_enabled`,
  strategy-provenance fields, effective-config path, lock file, manifest
  entries).

Tests assert the identical list (golden SampleSet values, pseudo-run score
equality), not byte-equality of output JSON.

---

## Scalar comparability — structural enforcement

Policy: *aggregate scalars are only comparable between identical resolved
DataScopes.* Mechanism: **scope-homogeneity at boundaries**, so interior
comparison code (best tracking, delta gates, candidate selection, formal
inheritance) needs zero changes:

1. **Stamp**: resolved scope written into `ExperimentRecord`,
   `HyperparamTuningOutput`, `run_config_{run_name}.json`, iteration manifest,
   campaign manifest.
2. **Run-invariants lock** (round 4: generalized from the earlier
   `data_scope_lock.json` — scope and health policy are the same class of
   invariant, so one artifact locks both): the first entry point to
   initialize the workspace **atomically creates**
   `{workspace}/run_invariants_lock.json` (write to temp file in the same
   directory + `os.rename`; first writer wins — a concurrent second writer's
   losing rename falls through to read-validate). Content:

   ```json
   {
     "resolved_data_scope": [4, 5, 6, 7, 8, 9],
     "health_gate_enabled": true,
     "health_config_sha256": "<sha256 of canonical effective config, null when disabled>",
     "created_at": "..."          // provenance only — excluded from equality
   }
   ```

   Later executions (chain iterations, `--resume`, standalone tuner runs
   against the same workspace) and `core/resume.restore_prior_state` only
   **read and validate**: equality is defined **only** on the three canonical
   fields (`created_at` and any other metadata never participate). Mismatch →
   startup failure. Scope and HealthGate policy are immutable per workspace.
3. **Ingress validation**: the four cross-run entry points (`--seed_paths`,
   `seed_records`, `restore_prior_state`, Phase-1 baseline seeding/reuse)
   verify that incoming records carry the same resolved scope. Missing stamp =
   full scope. Mismatch = startup failure.

**Campaign identity is functional, not metadata** (round 3): the resolved
scope joins `campaign_run_name` in the campaign manifest, and
`decide_phase1_reuse` / `core/campaign_artifacts` validation adds a
`"data_scope mismatch"` error (same pattern as the existing
`"campaign_run_name mismatch"`, `campaign_artifacts.py:80`) — **every artifact
reuse decision explicitly verifies scope equality before reuse**. A mismatch
fails validation; it never silently regenerates over an explicitly given
`--baseline_workspace`.

`target_score` remains operator-supplied and scope-relative (documented, not
validated — the operator sets it knowingly for the scoped run).

---

## Affected locations

| # | File | Change |
|---|---|---|
| 1 | `execute_tools/dataset_config.py` | + `DataScope` |
| 2 | `execute_tools/sample_set_builder.py` | scope param; snapshot-within-scope; partial+`anchors`/`target` → error; `_build_normal` membership check |
| 3 | `execute_tools/scoring_utils.py` | `validate_sample_set(sample_set, scope)` |
| 4 | `core/sandbox_executor.py` | sandbox carries resolved scope; validation in train/inference/`score_vector`; `StubSandbox` parity |
| 5 | `execute_tools/health_checks/config.py` (+ helper) | `apply_monitored_files` pure transform; `validate_health_scope`; effective-config materialization helper |
| 6 | `agent/schemas/hyperparam_tuning.py` | + `data_scope`, + `health_gate_enabled`, + `health_gate_files` (hard-constraints section; schema validators = internal consistency only); delete dead `trial_strategy`/`eval_strategy`/`target_files` input fields; scope stamp + strategy-provenance fields on record/output schemas |
| 7 | `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py` | `validate_runtime_config` at startup; effective-config materialization + path swap; disabled-mode skip + `required_gate_ids=frozenset()` at the three eligibility sites; plan normalization with provenance; formal path scope-aware; fixed-params disclosure; stamp `run_config` (source + effective paths); deprecate CLI flags |
| 8 | `agent/prompts.py` | `_format_fixed_params_block` discloses scope + snapshot-only rule |
| 9 | `workflows/model_exploration.py` | `data_scope`/`health_gate_enabled`/`health_gate_files` params; atomic run-invariants lock; ingress validation; iteration-manifest stamp |
| 10 | `agent/schemas/protocols/ml_model_valid_to_ml_model_tune.py` | thread the three new inputs |
| 11 | `agent/schemas/proposal.py`, `agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py`, `agent/utils/proposer_preflight.py` | delete dead `ProposalInput.trial_strategy`/`target_files`; add `ProposalInput.data_scope`; preflight synthesizes within scope |
| 12 | `sdsc_submission_scripts/run_one_iteration.py`, `_chain_common.sh`, `run_chain.sh` | `--data_scope` / `--health_gate_enabled` / `--health_gate_files`; deprecate `--trial_strategy`/`--target_files` |
| 13 | `scripts/run_comparison.py` | scoped baselines (baseline SampleSet built within scope); effective-config materialization; campaign-manifest scope; v17_pregate override pin |
| 14 | `core/campaign_artifacts.py` | scope in campaign identity + functional reuse check |
| 15 | `core/resume.py` | run-invariants-lock verification on restore |
| 16 | `CLAUDE.md`, `docs/design/v18_priorities.md` | invariant text; scope-keyed incumbent note |

---

## Commit plan

Commit prefix: **DS** (DataScope). Every commit leaves
`uv run pytest tests/unit/ -q` and `tests/integration/ -q` (pseudo mode)
green, ruff + pyright clean. Any schema change updates the matching
`tests/pseudo_data/` files in the same commit (two-file rule,
`tests/pseudo_data/README.md`).

---

### Commit DS1 — `DataScope` model

**Goal**: stand up the abstraction. Self-contained: nothing consumes it yet.

**Code**:
- [x] `execute_tools/dataset_config.py` — add `DataScope` (frozen Pydantic
  model) with `file_indices: list[int] | None`, field validator (non-empty
  when provided, deduped, sorted, all ints ≥ 0), `default()`, `resolve(dataset)
  -> list[int]` (validates ⊆ `[0, dataset.num_files)`), `is_full(dataset)`.
- [x] `from_cli(spec: str) -> DataScope` helper parsing `"4,5,6,7,8,9"` and
  `"4-9"` range shorthand (used by CLI surfaces in DS6). Rejects empty spec.
- [x] Docstring: "file" = partition unit per `DatasetConfig`; future datasets
  map their partitions onto indices; extension path = discriminated union.

**Tests** (`tests/unit/execute_tools/test_data_scope.py`, new file):
- [x] `default().resolve(TIDMAD)` == `list(range(20))`; `is_full` True
- [x] `DataScope(file_indices=[9,4,4,7]).resolve(TIDMAD)` == `[4,7,9]`
- [x] out-of-range index → `ValueError` with file index and bound in message
- [x] `file_indices=[]` → `ValidationError` (empty scope is never legal)
- [x] frozen: assignment raises
- [x] `from_cli("4-9")` == `from_cli("4,5,6,7,8,9")`; bad spec raises
- [x] resolved output JSON-serializable (plain `list[int]`)

**Verification checklist** (after todos complete):
- [x] `pytest tests/unit/execute_tools/test_data_scope.py -q` — 25/25 pass
  (1.24s, after ruff format)
- [x] `pytest tests/unit/ -q` — 3831 passed, 1 skipped, 3 xfailed, and **1
  pre-existing failure unrelated to DS1**:
  `test_chain_consistency.py::test_shell_python_default_parity` expects the
  lilab `data_dir` shell override (`test_chain_consistency.py:167`) that
  PR #127 (`44b2d94`) removed from `_chain_common.sh` — broken on master
  since 2026-07-22, before this branch; DS1 touches neither file. Fix is a
  stale-test update, proposed as a separate tiny commit outside DS scope.
- [x] ruff check clean; ruff format applied (long-line collapses only);
  pyright clean (`--pythonpath .venv/bin/python`; note: bare `pyright` on
  this machine doesn't resolve the venv and needs that flag)
- [x] No other module imports `DataScope` yet (grep: only
  `dataset_config.py` + `tests/unit/execute_tools/test_data_scope.py`)

**Test gate**: unit only.

**Implementation notes** (2026-07-22):
- Placed `DataScope` between the `DatasetConfig` class and the `TIDMAD`
  instance in `execute_tools/dataset_config.py` — it references the type,
  not the instance.
- `from_cli` parses comma-separated tokens where each token is an int or an
  inclusive `a-b` range. This supports exactly the two agreed forms and, as
  a natural superset, mixed forms like `"0-3,7"` (disclosed, tested).
  Descending ranges (`"9-4"`) and empty/malformed tokens raise `ValueError`
  with the offending token and full spec in the message. Range detection
  splits from position 1 so a leading minus (`"-3"`) is not mistaken for a
  range separator — it parses as a negative int and surfaces the validator's
  "non-negative" error instead of a confusing range error (tested).
- Validator normalizes (sorted+deduped) at construction, so equality and
  `model_dump_json` are canonical; round-trip test included. `resolve()`
  returns a fresh copy (mutation-safety test included).
- **Targeted tests**: 25/25 pass in 1.59s
  (`tests/unit/execute_tools/test_data_scope.py`).

---

### Commit DS2 — constructive enforcement in `build_sample_set`

**Goal**: SampleSets satisfy the scope by construction; snapshot-only rule for
partial scopes. Default scope preserves behavioral identity.

**Code**:
- [x] `execute_tools/sample_set_builder.py` — add `scope: DataScope | None = None`
  (None → `DataScope.default()`); resolve once per call.
- [x] `snapshot` → `files = resolved_scope` (replaces `range(NUM_FILES)`).
- [x] partial scope (`not scope.is_full(...)`) + `anchors` or `target` →
  `ValueError` naming the strategy, the scope, and the snapshot-only rule.
  (This is the low-level hard stop; the tuner normalizes LLM plans *before*
  reaching here — DS5 — so this error only fires on operator/programming
  errors.)
- [x] full scope: `anchors` / `target` behavior identical to today.
- [x] `_build_normal(file_index, scope)` — `file_index ∉ scope` → `ValueError`.
- [x] RNG discipline: file iteration order and per-file `rng.sample` calls
  unchanged for full scope so existing seeds reproduce identical SampleSets.

**Tests** (`tests/unit/execute_tools/test_sample_set_builder.py`, extend):
- [x] **behavioral identity**: full scope + fixed seed → SampleSet identical to
  pre-change output for all three strategies (golden sha16 digests captured
  from the pre-change builder at `56a54b8^`, seed=42, portion=0.05;
  parametrized over `scope=None` and `scope=DataScope.default()`)
- [x] partial scope + snapshot → keys == scope exactly; segment counts per
  `trial_portion` unchanged
- [x] partial scope + `anchors` → `ValueError`; + `target` → `ValueError`
  (even when `target_files ⊆ scope` — the rule is strategy-level)
- [x] `_build_normal` in-scope passes; out-of-scope raises
- [x] determinism: same seed + same partial scope → same SampleSet

**Verification checklist**:
- [x] Relevant suites green (per only-relevant-tests rule): builder tests
  35/35 (1.47s); `tests/unit/agent/utils` (preflight caller) — 77 total pass
  incl. builder file. Existing callers unaffected: `scope` is a trailing
  kwarg with a behavior-preserving default (callers audited: tuner,
  run_comparison, proposer_preflight, 2 schema modules).
- [x] `grep -n "range(NUM_FILES)" execute_tools/sample_set_builder.py` → no
  hits (NUM_FILES import dropped)
- [x] ruff check + format clean; pyright clean
  (`--pythonpath .venv/bin/python`)

**Test gate**: unit only.

**Implementation notes** (2026-07-22):
- Scope is resolved against `TIDMAD` inside the builder (consistent with its
  existing `SEGMENTS_PER_FILE` coupling; the multi-dataset backend TODO will
  parameterize both together).
- Full-scope `target` keeps its historical non-validation of out-of-range
  `target_files` (e.g. `[25]`) — constructively unchanged for behavioral
  identity; the DS3 sandbox boundary catches it before I/O.
- Golden capture: all three strategies share the same first-file segments
  (`[6, 26, 28, 35, 57]`) because `rng.sample` consumption is per-file in
  iteration order — this property is what makes full-scope identity
  structural, and the digests pin it.
- Test-class constants annotated `ClassVar` (RUF012).
- **Test results**: 35/35 builder (1.47s) + agent/utils 42 → 77 pass; ruff +
  pyright clean.

---

### Commit DS3 — boundary invariant at the sandbox

**Goal**: the final safety guarantee — no SampleSet outside the scope reaches
file I/O, regardless of who built it. Closes the existing `score_vector`
validation gap.

**Code**:
- [ ] `execute_tools/scoring_utils.py` — `validate_sample_set(sample_set,
  scope: DataScope | None = None)`; existing `[0, NUM_FILES)` check retained;
  when scope provided, out-of-scope key → `ValueError` naming key + scope.
- [ ] `core/sandbox_executor.py` — `TidmadSandbox.__init__` accepts
  `data_scope: DataScope | None` (default full); stores resolved scope.
- [ ] `execute_training` (`:569`) and `execute_inference` (`:735`) pass the
  sandbox scope into `validate_sample_set`.
- [ ] `score_vector` (`:800`) — add the missing `validate_sample_set` call
  (with scope) before delegating to `scoring_utils.score_vector`.
- [ ] `StubSandbox` — same constructor param + same validation (pseudo-mode
  tests must exercise the invariant, not bypass it).

**Tests**:
- [ ] `tests/unit/core/test_sandbox_scope.py` (new): out-of-scope SampleSet →
  `ValueError` from each of the three methods (training / inference /
  score_vector), full-scope passes; `StubSandbox` mirrors behavior
- [ ] `validate_sample_set` unit tests: scope=None keeps today's behavior;
  legacy string-key JSON dicts still coerced
- [ ] Regression: existing sandbox/pseudo integration tests green with no
  call-site changes (default = full scope)

**Verification checklist**:
- [ ] All three execution methods provably validate:
  `grep -n "validate_sample_set" core/sandbox_executor.py` shows **three** call
  sites (was two)
- [ ] Full unit + pseudo integration suites green
- [ ] ruff + pyright clean

**Test gate**: unit only.

**Implementation notes**: *(fill in as work lands)*

---

### Commit DS4 — HealthGate subsystem input + materialized effective config

**Goal**: `health_gate_enabled` / `health_gate_files` semantics per the table
above; pure transform + materialized effective config so **no reload site can
bypass the override**; startup validation with no intersection, no fallback,
no silent correction.

**Code**:
- [ ] `execute_tools/health_checks/config.py` — pure function
  `apply_monitored_files(config: HealthChecksConfig, files: list[int]) ->
  HealthChecksConfig` returning a **new** instance with every check's
  `peek_file_indices` replaced (v1: one shared list, all gates uniformly);
  the per-process cache is never mutated.
- [ ] Same module — `validate_health_scope(config, resolved_scope: list[int])
  -> None`: every gate's effective `peek_file_indices ⊆ scope`, else
  `ValueError` listing offending gate id, files, and remediation
  (`pass --health_gate_files with in-scope files`).
- [ ] Same module — `materialize_effective_config(source_path, files,
  workspace) -> tuple[str, str]`: load → apply override (no-op when
  `files is None`) → validate → write `{workspace}/health_checks_effective.yaml`
  (canonical/deterministic serialization) → return `(path, sha256)`. The
  sha256 is what the run-invariants lock pins (DS6). On resume, an existing
  effective file is compared by hash: equal → reuse; different → **startup
  error** distinguishing "operator inputs changed" from "source YAML content
  drifted" (the two diff cases have different remediation messages).
- [ ] Disabled-mode plumbing hooks: nothing in this package changes for
  disabled mode (the tuner simply never calls it) — assert this in review.

**Tests** (`tests/unit/execute_tools/health_checks/test_health_scope.py`, new):
- [ ] `apply_monitored_files` replaces all gates' peek lists; original config
  object unmodified; cached object unmodified (identity check)
- [ ] `validate_health_scope`: default YAML `[3,10,17]` vs scope `[4..9]` →
  error naming all three gates; vs full scope → passes
- [ ] override `[4,7,9]` + scope `[4..9]` → passes; `[3,7,10]` → error
- [ ] `materialize_effective_config`: written file loads through
  `load_health_gates_config` and shows the override in every gate;
  `files=None` materializes source content unchanged; returned sha256 is
  stable across re-materialization with identical inputs (canonical
  serialization) and changes when the source YAML content changes
- [ ] round-trip: loading the materialized path via the normal cached loader
  returns the overridden peek lists (proves path-based reload sites get the
  override)

**Verification checklist**:
- [ ] `configs/health_checks.yaml` and
  `configs/health_checks_baseline_observe_mode.yaml` **unchanged**
- [ ] Reload-site audit recorded here: `get_gates_for_position`,
  `evaluate_gate`, `evaluate_and_persist_health_gates` all receive the
  materialized path once DS5 swaps `agent_input.health_checks_config`;
  `required_blocking_gate_ids` + production-policy `_persist` confirmed to
  read only IDs/actions (no peek fields) — re-verify against HEAD
- [ ] Full unit suite green; ruff + pyright clean

**Test gate**: unit only.

**Implementation notes**: *(fill in as work lands)*

---

### Commit DS5 — tuner plumbing: schema, startup validation, normalization, stamps

**Goal**: the tuner accepts the three new inputs; schema validates internal
consistency only; `validate_runtime_config` does all dataset-resolved checks at
startup; LLM plans normalize with persisted provenance; resolved scope stamped
into all artifacts; disabled mode wired end-to-end.

**Code**:
- [ ] `agent/schemas/hyperparam_tuning.py` — `data_scope: DataScope` (default
  `DataScope.default()`), `health_gate_enabled: bool = True`,
  `health_gate_files: list[int] | None = None` in the *Hard constraints on LLM
  plan output* section (`:1135`). Schema validators: **internal consistency
  only** (`enabled=False` + files set → error; `files == []` → error). No
  dataset-resolved checks in the schema.
- [ ] New `validate_runtime_config(agent_input, dataset)` (tuner module or
  `core/`): resolve scope; partial + `formal_strategy != "snapshot"` → error;
  single-file `file_index ∈ scope`; enabled + partial + `files is None` →
  error; then health materialization (DS4) + `validate_health_scope`. Called
  at `run()` entry before any LLM call.
- [ ] Effective-config path swap: `agent_input.health_checks_config` replaced
  by the materialized path for the run; `run_config_{run_name}.json` records
  `health_checks_config_source` + `health_checks_config_effective` +
  `resolved_data_scope` + `health_gate_enabled` (`:1455-1470`).
- [ ] Disabled mode: skip the gate block (`:2446-2485`); the three
  `is_valid_candidate` sites (`:176, :1657, :3188`) pass
  `required_gate_ids=frozenset()`; `_merge_score_validity_failure` untouched.
- [ ] Plan boundary (after `plan_overrides` merge and
  `_apply_mode_override_chain`, before `TrialConfig` at `:1792`): under
  partial scope, normalize plan `trial_strategy`/`eval_strategy` → `snapshot`;
  persist `planned_*`/`effective_*`/`strategy_normalization_reason` on the
  round record; loud log line.
- [ ] `_resolve_sample_set_cfg` / `build_sample_set` call sites (`:1820,:1827`)
  pass the resolved scope; sandbox constructed with `data_scope`.
- [ ] `agent/prompts.py` `_format_fixed_params_block` (`:706`) — when scope is
  partial, disclose the allowed files and the snapshot-only rule.
- [ ] Scope stamps: `ExperimentRecord` + `HyperparamTuningOutput` gain
  `resolved_data_scope: list[int]` (+ the strategy-provenance fields above).
- [ ] Tuner CLI: `--data_scope`, `--health_gate_enabled/--no-health_gate_enabled`,
  `--health_gate_files`.
- [ ] `tests/pseudo_data/` — update canned tuner inputs/outputs for the new
  schema fields (two-file rule).

**Tests**:
- [ ] Schema: internal-consistency validators only (disabled+files → error;
  `[]` → error; partial scope + formal target **passes schema**, fails
  `validate_runtime_config` — asserting the split)
- [ ] `validate_runtime_config`: each failure mode (formal target, bad
  file_index, enabled+partial+None files, out-of-scope health files) fails
  with distinct messages before any sandbox/LLM activity
- [ ] Normalization: plan with `target` under partial scope → effective
  snapshot + provenance fields persisted + logged; full scope → no
  normalization, reason `None`
- [ ] Disabled mode (pseudo): full loop with `health_gate_enabled=False` —
  no gate results, successful finite records classify VALID, best-valid
  tracking populated, output records `health_gate_enabled=False`
- [ ] Pseudo-mode integration (`@dual_mode`): full tuner loop with
  `data_scope=[4..9]` + `health_gate_files=[4,7,9]` on `StubSandbox` — every
  built SampleSet ⊆ scope, output stamped, run completes
- [ ] Behavioral-identity regression: default-scope pseudo loop produces the
  same scores/records as before (new metadata fields excepted)

**Verification checklist**:
- [ ] `run_config_{run_name}.json` from a pseudo run contains
  `resolved_data_scope`, `health_gate_enabled`, source + effective config paths
- [ ] Startup failure paths verified fail **before round 1**
- [ ] `grep -n "load_health_gates_config" nodes/ml_hyperparameter_tune_agent/`
  → all call sites reachable in a run use `agent_input.health_checks_config`
  (i.e. the swapped effective path); none hardcodes the shipped config except
  the documented eligibility/production-policy sites
- [ ] Full unit + pseudo integration suites green; ruff + pyright clean

**Test gate**: unit only (prompt change is disclosure-only; Gate 1 deferred to
Checkpoint DS).

**Implementation notes**: *(fill in as work lands)*

---

### Commit DS6 — workflow / protocol / CLI + scope homogeneity

**Goal**: scope enters at the workflow level, propagates via protocols, and the
workspace becomes scope-homogeneous (atomic lock + ingress validation +
functional campaign identity).

**Code**:
- [ ] `workflows/model_exploration.py` — `run_workflow(data_scope=...,
  health_gate_enabled=..., health_gate_files=...)`; resolve once; pre-flight
  `validate_runtime_config` equivalents (fail before iteration 1's LLM calls).
- [ ] **Atomic run-invariants lock**: `{workspace}/run_invariants_lock.json`
  created via same-directory temp file + `os.rename` (first writer wins;
  losing writer re-reads and validates). Content: canonical resolved scope +
  `health_gate_enabled` + `health_config_sha256` (null when disabled) +
  `created_at`. **Equality = the three canonical fields only**; timestamps
  excluded. Later iterations, `--resume` paths, standalone tuner runs against
  the same workspace, and `core/resume.restore_prior_state` read-and-validate,
  fail fast on mismatch (scope change, enabled flip, or policy-content drift
  each produce a distinct error message).
- [ ] **Ingress validation**: seed summaries / seed_records / restored outputs /
  `run_comparison.seed_agent_memory` — compare each record's
  `resolved_data_scope` (missing = full scope) against the run scope; mismatch
  → startup `ValueError` naming the offending record path.
- [ ] `agent/schemas/protocols/ml_model_valid_to_ml_model_tune.py` — thread
  `data_scope` + `health_gate_enabled` + `health_gate_files`.
- [ ] `sdsc_submission_scripts/run_one_iteration.py` + `_chain_common.sh` +
  `run_chain.sh` — `--data_scope "4-9"` / `--health_gate_enabled|--no-...` /
  `--health_gate_files "4,7,9"` (parsed via `DataScope.from_cli`).
- [ ] Iteration manifest + `core/campaign_artifacts.py` — resolved scope in
  manifest; **functional reuse check**: `decide_phase1_reuse` / campaign
  validation adds `"data_scope mismatch"` error (pattern of
  `campaign_artifacts.py:80`); reuse never proceeds on mismatch.
- [ ] `scripts/run_comparison.py` — `--data_scope` forwarded to baseline
  builders (baseline SampleSet built within scope, per round-3 §11) and the
  agent subprocess; effective-config materialization at campaign startup;
  v17_pregate override pin.

**Tests**:
- [ ] Unit: atomic lock (concurrent create race simulated → single winner,
  loser validates; equality ignores timestamps); lock-violation matrix —
  scope change / `health_gate_enabled` flip / `health_config_sha256` drift
  each fail with their distinct message; ingress validation
  (stamped-match, stamped-mismatch, legacy-unstamped=full); protocol
  threading; CLI parsing round-trip
- [ ] Campaign: manifest with mismatched scope → `ValidationReport` error;
  matching scope → reuse allowed
- [ ] Pseudo-mode workflow test: one-iteration `run_workflow` with partial
  scope on stubs — lock written, tuner input carries scope, manifest stamped
- [ ] Pseudo-mode: seeded workflow with full-scope legacy seeds + partial scope
  → fails at ingress with the documented error

**Verification checklist**:
- [ ] Chain smoke in pseudo mode (`run_one_iteration.py` with `--pseudo` +
  `--data_scope 4-9 --health_gate_files 4,7,9`) completes; second invocation
  with a different scope against the same workspace **fails at startup**
- [ ] Full unit + pseudo integration suites green; ruff + pyright clean

**Test gate**: unit only.

**Implementation notes**: *(fill in as work lands)*

---

### Commit DS7 — dead-field removal, deprecations, proposer preflight scope

**Goal**: remove fields that are dead at both ends; give the proposer
`data_scope` for its *actual* need (pre-flight synthesis + disclosure);
deprecate CLI flags per the `--source_paths` precedent
(`run_one_iteration.py:447`).

**Code**:
- [ ] Delete `HyperparamTuningInput.trial_strategy` / `eval_strategy` /
  `target_files` (+ their validator, `:1157-1164`) — serialization-safe (no
  `extra="forbid"`, not in `run_config` dump). `ExperimentRecord` copies stay.
- [ ] Delete `ProposalInput.trial_strategy` / `target_files`
  (`proposal.py:689,702`) — confirmed consumed by nobody (round-3 audit).
  Keep `is_trial` / `trial_portion` / `train_portion` (live).
- [ ] Add `ProposalInput.data_scope`; `local_full_context` maps it from the
  workflow's resolved scope; proposer prompt context renders the allowed-file
  list + snapshot-only note when partial.
- [ ] `agent/utils/proposer_preflight.py` —
  `_synthesise_default_sample_set(trial_portion, scope)` builds the synthetic
  snapshot **within scope** (`:61-64`; delivers what the dead fields'
  docstrings promised: the estimate matches what the tuner will run).
- [ ] `workflows/model_exploration.py` — drop the now-unused
  `trial_strategy`/`target_files`/`eval_strategy` kwargs from the tuner and
  proposer paths; keep accepting them at CLI level as deprecated no-ops.
- [ ] Tuner CLI `--trial_strategy` / `--eval_strategy` and chain CLI
  `--trial_strategy` / `--target_files`: accepted, warn, ignored. Removal
  scheduled after the next stable chain run (FU-2).
- [ ] `_chain_common.sh` — stop forwarding the deprecated flags (`:304,:332`);
  still parse them so existing invocations don't break.
- [ ] `tests/pseudo_data/` — update canned `ProposalInput` payloads.

**Tests**:
- [ ] Old serialized `HyperparamTuningInput` / `ProposalInput` JSON (with
  removed keys) still validates (extras ignored)
- [ ] Preflight: partial scope → synthetic sample set keys ⊆ scope; estimate
  path unchanged for full scope
- [ ] Proposer pseudo test: partial-scope `ProposalInput` renders the file
  list; full-scope renders unchanged framing
- [ ] CLI deprecation: invoking with `--trial_strategy target` warns and does
  not alter behavior

**Verification checklist**:
- [ ] `grep -rn "trial_strategy" agent/schemas/hyperparam_tuning.py` — only
  `ExperimentPlan` / `TrialConfig` / `ExperimentRecord` hits remain
- [ ] `grep -rn "trial_strategy\|target_files" agent/schemas/proposal.py` — no
  hits
- [ ] Full unit + pseudo integration suites green; ruff + pyright clean

**Test gate**: unit only + **Gate 1** (proposer prompt context changed — may be
batched with Checkpoint DS Gate 1).

**Implementation notes**: *(fill in as work lands)*

---

### Commit DS8 — docs, invariants, follow-up filing, connection audit

**Goal**: docs and code in lock-step; graph-level audit before the checkpoint.

**Code / docs**:
- [ ] `CLAUDE.md` — amend the health-YAML invariant wording (YAML = checks /
  thresholds / actions / **default** file placement; per-run enable +
  monitored files = run-level inputs; effective config materialized to the
  workspace); add a *Subsystem Invariants* entry for `DataScope`
  (constructive + boundary + direct-access enforcement; scalar
  scope-homogeneity rule; snapshot-only under partial scope; behavioral
  identity of the default).
- [ ] `README.md` — short section under *Common workflows*: scoped run example
  (`--data_scope 4-9 --health_gate_files 4,7,9`), plus the disabled-gate
  example (`--no-health_gate_enabled`).
- [ ] `docs/design/v18_priorities.md` — note: chain-wide best-valid-formal
  incumbent must be **scope-keyed**.
- [ ] File GitHub issue: pre-existing peek-vs-eval-coverage latent bug (full
  scope + LLM `eval_strategy="target"` → spurious blocking-gate failures);
  reference this doc's audit section.
- [ ] **Connection audit** (step-7 style): every field required by
  `HyperparamTuningInput` / `ProposalInput` present in upstream protocol
  sources; scope + health fields mapped by `local_validated_model` and
  `local_full_context` with no silent defaults; pseudo-data shapes match
  schemas.

**Verification checklist**:
- [ ] `uv run pytest tests/unit/ -q` and `uv run pytest tests/integration/ -q`
  (pseudo) — full green
- [ ] ruff check + ruff format --check + pyright — clean repo-wide
- [ ] Doc cross-references resolve (paths exist)

**Test gate**: unit only.

**Implementation notes**: *(fill in as work lands)*

---

## Checkpoint DS — Gate validation

Per `docs/gates/gate_testing_standard.md`. Both gates need user approval
(real-LLM cost; Gate 2 adds GPU time).

### Gate 1 — Real LLM + pseudo training

**What changed LLM-facing**: fixed-params scope disclosure (DS5), proposer
`data_scope` context (DS7).

- [ ] Run the planner path with a real LLM (`llm_configs/openai_tiered_v1.json`)
  under `data_scope=[4..9]`: plan completes, validates into `ExperimentPlan`,
  and after normalization the effective strategies are `snapshot` (provenance
  fields populated when normalization occurred)
- [ ] Run the proposer with a partial-scope `ProposalInput`: output passes
  schema validation; proposal text does not reference out-of-scope files as
  available data; preflight estimate uses the in-scope synthetic sample set
- [ ] Cost/time: ~$0.05–0.20, ~2–5 min

**Pass criteria**: LLM calls complete; outputs pass Pydantic validation; no
crash in the normalization/disclosure path.

- [ ] Gate 1 result recorded here: *(date, model ids, outcome)*

### Gate 2 — Real LLM + real training (smoke, two scenarios)

**Scenario A — full-scope regression** (canonical command from the gate
standard, unchanged, `--num_iterations 2 --max_rounds 2`, canonical seeds):

- [ ] Chain exits 0; standard Gate 2 pass criteria 1–5 hold (gate_action
  recorded every round; scores finite or gated; no accepted phantom
  5.5762667; ≥1 HealthGate evaluation)
- [ ] `resolved_data_scope` stamp = `[0..19]` in run outputs; behavioral
  identity otherwise (sampling, scores, gate behavior indistinguishable from
  pre-feature runs; new metadata fields expected)

**Scenario B — partial-scope cold start**. Canonical seeds are full-scope, so
scenario B runs **seedless** (PR #126) — ingress validation would correctly
reject full-scope seeds:

```bash
bash sdsc_submission_scripts/run_chain.sh \
    --mode lilab \
    --workspace /tmp/checkpoint_ds_$(date +%s) \
    --run_name checkpoint_ds_scope \
    --num_iterations 2 --max_rounds 2 --max_proposal_attempts 3 \
    --max_epochs 1 \
    --data_scope 4-9 --health_gate_files 4,7,9 \
    --trial_portion 0.02 --train_portion 0.02 --eval_portion 0.02 \
    --trial_time_budget_minutes 5 \
    --no-force_formal_round \
    --formal_time_budget_minutes 30 \
    --llm_config llm_configs/openai_tiered_v1.json
```

(All mandatory constraints from the gate standard apply: `--trial_portion
0.02`, `--trial_time_budget_minutes 5`, `--no-force_formal_round`,
`openai_tiered_v1.json`, no `tee`.)

- [ ] Chain exits 0
- [ ] **Scope invariant**: every `train_sample_set` / `eval_sample_set` in
  round records has keys ⊆ `{4..9}`; the run workspace contains **no**
  denoised output for files outside 4–9 (`ls` check on the denoised dir)
- [ ] HealthGates fire on peek files `{4,7,9}` only (from the materialized
  `health_checks_effective.yaml`); every round records `gate_action`;
  standard criteria 3–5 hold (criterion 5 applies — gates enabled)
- [ ] `run_invariants_lock.json` written at iter 1 (scope + enabled +
  effective-config sha256); iteration manifests + `run_output` stamped
  `resolved_data_scope=[4,...,9]`
- [ ] Any plan normalization is visible in records
  (`planned_*` vs `effective_*` + reason) and logged; planner rounds after
  round 1 do not repeatedly propose `target`/`anchors` (disclosure working)
- [ ] **Negative startup checks** (cheap, before/after the run, no LLM cost):
  - [ ] same command **without** `--health_gate_files` → startup error naming
    gates with default `[3,10,17]` ⊄ scope; exits non-zero before any LLM call
  - [ ] re-invoking the same workspace with `--data_scope 5-9` → lock
    startup error (scope field)
  - [ ] re-invoking the same workspace with `--health_gate_files 5,8` →
    lock startup error (policy sha256 field) — resume cannot silently change
    HealthGate semantics
  - [ ] re-invoking the same workspace with `--no-health_gate_enabled` →
    lock startup error (enabled field)
  - [ ] `--data_scope 4-9` + canonical full-scope `--seed_paths` → ingress
    validation error naming the seed file
  - [ ] `--no-health_gate_enabled --health_gate_files 4,7,9` → schema
    validation error (internally inconsistent input)

**Estimated wall/cost**: Scenario A ~30–60 min / ~$1.50–2.50; Scenario B
similar or less (6-file scope shrinks I/O). Failure handling per the gate
standard.

- [ ] Gate 2 Scenario A result recorded here: *(date, outcome)*
- [ ] Gate 2 Scenario B result recorded here: *(date, outcome)*

---

## Follow-up tracker (NOT blocking DS-series merge)

- **FU-1** — peek-vs-eval-coverage latent bug under full scope (issue filed in
  DS8): general fix is a per-round `peek ⊆ eval coverage` validation.
- **FU-2** — remove deprecated CLI flags (`--trial_strategy`,
  `--eval_strategy`, `--target_files`) after the next stable chain run.
- **FU-3** — V18 chain-wide incumbent: scope-keyed by design (noted in
  `v18_priorities.md`).
- **FU-4** — retire `plan_overrides`-based file clamping guidance anywhere it
  appears in operator docs (superseded by `--data_scope`).
- **FU-5** — per-round strategy provenance in `ModelRunSummary` (from
  `ExperimentRecord`), if the proposer ever needs executed-strategy history;
  never existed before this feature, deliberately not added now.
- **FU-6** — explicit policy-migration path (deliberate mid-campaign
  HealthGate policy change with an operator-acknowledged flag + recorded
  transition). v1 policy: new policy = new workspace; add only if an
  operational need appears.

## Non-goals (explicit out of scope)

- Redefining evaluation/scoring semantics — the scalar formula, anchor map,
  and `s_max` are untouched; partial-scope scalars are a different *population*
  under the same formula, guarded by scope-homogeneity.
- Per-round dynamic scopes, scope unions, or mid-chain scope changes — scope is
  immutable per workspace.
- `anchors`/`target` semantics within partial scopes (rejected by design).
- Per-gate monitored-file customization (v1 uses one shared list; custom YAML
  remains the escape hatch).
- Multi-dataset `DatasetBackend` extraction (`docs/architecture.md` TODO) —
  `DataScope` is designed to survive it, not to trigger it.
- Fixing FU-1 (pre-existing, orthogonal).

## Open questions

1. CLI spelling: `--data_scope 4-9` (range shorthand) vs explicit list only —
   DS1 implements both; confirm preference before DS6 lands.

*(Resolved in round 3: scoped `run_comparison` baselines are supported — DS6;
HealthGate override applies one shared list to all gates — v1 simplification;
schema vs runtime validation split — see the dedicated section.)*
