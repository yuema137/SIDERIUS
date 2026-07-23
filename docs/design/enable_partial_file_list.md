# Design: Enable Partial-File Training via `DataScope` (`enable_partial_file_list`)

**Status**: DS1–DS8 complete (2026-07-23) — implementation + docs +
final suites done. Pending: Checkpoint DS Gates 1 & 2 (operator-approved
real-LLM / real-training validation; Gate 2 needs a GPU + TIDMAD data),
then PR
**Author**: Yue Ma
**Created**: 2026-07-22
**Revised**: 2026-07-22 (round 3: HealthGate enable flag, materialized effective
config, schema/runtime validation split, proposer-channel correction,
behavioral-identity guarantee, atomic lock, functional campaign identity;
round 4: HealthGate policy lock — `data_scope_lock.json` generalized to
`run_invariants_lock.json` pinning scope + `health_gate_enabled` +
effective-config sha256, so resume cannot silently change HealthGate semantics)
**Branch**: `feat/enable-partial-file-list`
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
  - `load_health_gates_config` caches **only the default path** — explicitly
    passed paths are loaded fresh on every call and never cached
    (`config.py:236-244`; corrected during DS4 from the earlier
    "keyed on path" description). Consequence: materializing to a new
    per-workspace path has zero cache-mutation hazard, and every path-based
    reload site picks the effective config up naturally. An in-memory-object
    override would still be silently bypassed at every reload site — the
    materialized-path design stands.
  - **Recording-only checks do not use `peek_file_indices`** (found during
    DS4): `pearson_dispersion` / `spectral_peak_ratio` /
    `per_file_output_std` resolve files via `_resolve_files(ctx)` —
    `ctx.denoised_paths` keys, else a `range(20)` fallback. DS4 (Option A,
    approved 2026-07-22) makes the run-level monitored list universal: the
    shared `peek_file_indices` is written into all six checks and the
    recording checks honor it as their top-priority file source.
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
overrides **all six file-accessing checks uniformly — blocking AND
recording-only** (the recording checks gained `peek_file_indices` as their
top-priority file source in DS4; their `ctx.denoised_paths` /
`range(num_files)` fallbacks remain for full-scope runs without an override).
Per-gate/per-check monitored-file customization is out of scope for v1;
anyone needing it authors a custom YAML. `validate_health_scope` covers every
file-accessing check: a check without an explicit list counts as full-dataset
access and therefore fails validation under a partial scope — the invariant
is airtight independent of call ordering.

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

Commit prefix: **DS** (DataScope). ~~Every commit leaves
`uv run pytest tests/unit/ -q` and `tests/integration/ -q` (pseudo mode)
green, ruff + pyright clean.~~ **Amended (operator decision 2026-07-23,
during DS6):** per-commit verification = targeted/affected suites + ruff +
pyright; the FULL unit + pseudo-integration suites run only at the end of
the DS series (DS8 completion, before Checkpoint DS). Commits DS1–DS6b and
FU-10 predate the amendment and were verified against full suites (all
green; results recorded in their implementation notes). Any schema change
updates the matching `tests/pseudo_data/` files in the same commit
(two-file rule, `tests/pseudo_data/README.md`).

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

**Error-shape contract (decided during implementation, 2026-07-22)**: the
invariant is uniform — **rejection before any file I/O** — while the outward
error shape follows each executor method's established contract. This
difference is intentional:

- `execute_training` / `execute_inference`: reject the out-of-scope SampleSet
  before any subprocess launch and return the structured error dict
  `{"status": "error", "error_type": "scope_violation", "message":
  "error_scope_violation: ..."}` (the `error_type` field is the structured
  classification; the stable prefix follows the `error_training:` convention
  for greppability — consumers access these dicts via `.get(...)`, so the
  extra key is safe). Inference's dict additionally carries its timing keys
  (`per_file_timings_ms: []`, `process_startup_ms/subprocess_wall_ms: None`).
- `score_vector`: raises `ScopeViolationError` (a `ValueError` subclass
  defined next to `DataScope`), consistent with its existing exception
  contract.

**Code**:
- [x] `execute_tools/dataset_config.py` — `ScopeViolationError(ValueError)`
  next to `DataScope` (structured classification without message parsing).
- [x] `execute_tools/scoring_utils.py` — `validate_sample_set(sample_set,
  scope: DataScope | None = None)`; existing `[0, NUM_FILES)` check retained;
  when scope provided, out-of-scope key → `ScopeViolationError` naming key +
  resolved scope.
- [x] `core/sandbox_executor.py` — `TidmadSandbox.__init__` accepts
  `data_scope: DataScope | None` (default full); module-level
  `_scope_violation_result()` helper builds the structured error dict.
- [x] `execute_training` (validate site inside its try; specific
  `except ScopeViolationError` **before** the generic handler) and
  `execute_inference` (validate site is *before* its subprocess try-block —
  wrapped directly at the call site) return the structured error dict.
- [x] `score_vector` — the missing `validate_sample_set` call added (with
  scope) before delegating; `ScopeViolationError` propagates.
- [x] `StubSandbox` — same constructor param + same validation and error
  shapes in all three methods (pseudo-mode tests exercise the invariant,
  not bypass it).

**Tests**:
- [x] `tests/unit/core/test_sandbox_scope.py` (new, 15 tests): out-of-scope
  SampleSet → structured `scope_violation` error dict from training +
  inference **with `subprocess.run` asserted not called** (rejection before
  I/O), `ScopeViolationError` raised from `score_vector`; in-scope training
  proceeds to the (mocked) subprocess; `StubSandbox` mirrors all shapes
- [x] `validate_sample_set` unit tests: scope=None keeps today's behavior
  (out-of-range stays a plain `ValueError`, not `ScopeViolationError`);
  legacy string-key JSON dicts still coerced; `ScopeViolationError`
  is-a `ValueError`
- [x] Regression: existing sandbox/stub/scoring/builder suites green with no
  call-site changes (default = full scope)

**Verification checklist**:
- [x] All six execution methods provably validate:
  `grep -c "validate_sample_set(sample_set, scope=self.data_scope)"
  core/sandbox_executor.py` → 6 (3 production + 3 stub; was 2)
- [x] Relevant suites green: 161 passed (sandbox_scope 15, sandbox_executor,
  stub_sandbox, sandbox_rlimit, scoring_utils, sample_set_builder)
- [x] ruff check + format clean; pyright clean
  (`--pythonpath .venv/bin/python`)

**Test gate**: unit only.

**Implementation notes** (2026-07-22):
- Structure discovery that shaped the fix: training's validate site is inside
  its method-wide `try` (whose generic `except Exception` would have
  swallowed the typed error — the specific except precedes it), while
  inference's validate site runs *before* its subprocess-only `try` (no
  catch-all exists there; the wrap is at the call site). A first
  implementation put inference's handler on the wrong try and the new test
  caught it (`ScopeViolationError` propagated) — fixed before commit.
- `ScopeViolationError` subclasses `ValueError` so `score_vector`'s
  documented "raises ValueError" contract is unchanged.
- Stub `score_vector` now validates its (required) `sample_set` argument —
  pseudo-data sample sets must be structurally valid, which they are.
- **Test results**: 161/161 across the six relevant files (16.1s); ruff +
  pyright clean.

---

### Commit DS4 — HealthGate subsystem input + materialized effective config

**Goal**: `health_gate_enabled` / `health_gate_files` semantics per the table
above; pure transform + materialized effective config so **no reload site can
bypass the override**; startup validation with no intersection, no fallback,
no silent correction.

**Universality refinement (Option A, approved 2026-07-22)**: the run-level
`health_gate_files` is the shared monitored-file set for **all** six
file-accessing checks, not only the blocking three. The recording-only checks
gained `peek_file_indices` as an explicit config field with top-priority
resolution (config → `ctx.denoised_paths` → full-dataset fallback). Under a
partial scope every check operates exclusively on the explicit list —
attempting all 20 files and counting the missing ones as I/O failures is not
acceptable. Full-scope behavior without an override is unchanged (blocking:
YAML defaults; recording: all-file fallback). Authority stays with the pure
effective-config materialization — never split between YAML and runtime ctx.

**Code**:
- [x] Recording checks (`pearson_dispersion.py`, `spectral_peak_ratio.py`,
  `per_file_output_std.py`) — `_resolve_files(ctx, cfg)` honors
  `cfg["peek_file_indices"]` first (sorted/deduped), then
  `ctx.denoised_paths`, then the existing `range(20)` fallback.
- [x] `execute_tools/health_checks/config.py` — pure function
  `apply_monitored_files(config, files) -> HealthChecksConfig` returning a
  **new** instance with every check's `peek_file_indices` replaced (v1: one
  shared list, all six checks uniformly); never mutates input or cache;
  `files=[]` → `ValueError`.
- [x] Same module — `validate_health_scope(config, resolved_scope) -> None`:
  **every file-accessing check** validated; explicit list must be ⊆ scope; a
  check *without* an explicit list counts as full-dataset access → violation
  under a partial scope; error lists all offending gate/check pairs +
  remediation.
- [x] Same module — `materialize_effective_config(source_path, files,
  workspace, resolved_scope=None) -> tuple[str, str]`: load → apply override
  (no-op when `files is None`) → validate (when scope given) → write
  `{workspace}/health_checks_effective.yaml` **atomically** (same-dir temp +
  rename) with a materialization header (`source`, `health_gate_files`,
  body sha256) → return `(path, body_sha256)` — the sha the run-invariants
  lock pins (DS6). Resume: identical body sha → reuse; mismatch → error
  distinguishing "operator inputs changed" (header files differ) from
  "source YAML content drifted" (same inputs, different body).
- [x] Disabled-mode plumbing hooks: nothing in this package changes for
  disabled mode (the tuner simply never calls it) — confirmed in review.

**Tests** (`tests/unit/execute_tools/health_checks/test_health_scope.py`,
new, 20 tests):
- [x] `apply_monitored_files` replaces the peek list in **all six** checks;
  normalizes sorted/deduped; original config unmodified (dump-compare);
  default-path cached object unmodified (identity + content); `[]` rejected
- [x] `validate_health_scope`: default YAML vs scope `[4..9]` → error naming
  **all six gates** (blocking: `[3,10,17]` outside; recording: missing
  explicit list = full-dataset default); vs full scope → passes
- [x] override `[4,7,9]` + scope `[4..9]` → passes; `[3,7,10]` → error
  naming `[3, 10]`
- [x] `materialize_effective_config`: written file loads through
  `load_health_gates_config` with the override in every check;
  `files=None` materializes source content semantically unchanged
  (loaded-config equality); identical inputs → reuse (same path+sha);
  changed operator files → "operator inputs changed"; edited source YAML →
  "source YAML content drifted"; in-materialize scope validation failure →
  no file written
- [x] **Attempted-open sets (all six checks)**: recording path-fns capture
  every requested file index; under `peek_file_indices=[4,7,9]` each check's
  requested set is non-empty and ⊆ `{4,7,9}`; recording checks with no
  config keep the exact `range(20)` fallback (full-scope behavioral
  identity); `ctx.denoised_paths` still beats the fallback (priority order)

**Verification checklist**:
- [x] `configs/health_checks.yaml` and
  `configs/health_checks_baseline_observe_mode.yaml` **unchanged**
  (git status clean for both)
- [x] Reload-site audit: `get_gates_for_position`, `evaluate_gate`,
  `evaluate_and_persist_health_gates` all load by path → will receive the
  materialized path once DS5 swaps `agent_input.health_checks_config`;
  `required_blocking_gate_ids` + production-policy `_persist` re-verified to
  read only gate IDs/actions (no peek fields)
- [x] Relevant suite green: `tests/unit/execute_tools/health_checks/` —
  **225 passed** (2.4s), including all pre-existing recording-check tests
  (full-scope identity) and the 20 new DS4 tests
- [x] ruff check + format clean; pyright clean
  (`--pythonpath .venv/bin/python`)

**Test gate**: unit only.

**Implementation notes** (2026-07-22):
- **Cache-behavior correction** (audit note updated): the loader caches only
  the *default* path; explicit paths are loaded fresh every call
  (`config.py:236-244`). The materialized per-workspace path therefore has
  zero cache-mutation hazard by construction; purity tests assert it anyway.
- The materialization header doubles as the mismatch diagnostic: sha line
  drives reuse, `health_gate_files` line distinguishes operator-input change
  from source drift; a file with no recognizable header errors as
  corrupted/hand-written.
- `resolved_scope` is an optional param on `materialize_effective_config` so
  DS5 can do load→apply→validate→write in one call while tests can exercise
  the transform standalone.
- Attempted-open tests observe the *requested index set* via recording
  `denoised_filename_fn`/`target_path_fn` wrappers (paths point at
  nonexistent files; the checks' tolerated I/O-failure path absorbs the
  opens) — asserting the request set, which is exactly the invariant.
- **Test results**: 225/225 health_checks suite; ruff + pyright clean.

---

### Commit DS5 — tuner plumbing: schema, startup validation, normalization, stamps

**Goal**: the tuner accepts the three new inputs; schema validates internal
consistency only; `validate_runtime_config` does all dataset-resolved checks at
startup; LLM plans normalize with persisted provenance; resolved scope stamped
into all artifacts; disabled mode wired end-to-end.

*(Implemented as three git commits per the split rule: **DS5a** schema +
runtime validation; **DS5b** tuner wiring; **DS5c** prompt disclosure + CLI +
pseudo-data.)*

**Code**:
- [x] `agent/schemas/hyperparam_tuning.py` — `data_scope: DataScope` (default
  `DataScope.default()`), `health_gate_enabled: bool = True`,
  `health_gate_files: list[int] | None = None` in the *Hard constraints on LLM
  plan output* section. Schema validators: **internal consistency
  only** (`enabled=False` + files set → error; `files == []` → error). No
  dataset-resolved checks in the schema. *(DS5a)*
- [x] New `validate_runtime_config(agent_input, dataset=TIDMAD)` — placed in
  `agent/schemas/hyperparam_tuning.py` right after the input class (pure, no
  I/O; importable by both tuner and workflow without the 3700-line tuner
  module): resolves scope (returns the resolved list); partial +
  `formal_strategy != "snapshot"` → error; enabled + partial +
  `files is None` → error; single-file `file_index ∈ scope` (trial mode
  deliberately ignores `file_index`, matching its documented semantics).
  Health materialization + `validate_health_scope` happen right after it at
  tuner startup (DS5b). *(DS5a)*
- [x] Startup block in `run()` (right after workspace extraction, before any
  LLM/sandbox/hardware work): `validate_runtime_config` → materialization
  (when enabled) → path swap: `agent_input.health_checks_config` replaced by
  the materialized path; `run_config_{run_name}.json` records
  `health_checks_config_source` + `health_checks_config_effective` +
  `health_config_sha256` + `resolved_data_scope` + `health_gate_enabled`.
  **Materialization is uniform when enabled — full-scope runs also get the
  effective file** (uniform provenance + a sha for the DS6 lock). *(DS5b)*
- [x] Disabled mode: gate block wrapped in `if agent_input.health_gate_enabled`
  (disabled branch: no evaluation, `health_gate_results=[]`,
  `gate_action=None`, `resolved_action=CONTINUE`);
  `_merge_score_validity_failure` untouched. **Eligibility mechanism =
  Option B (approved 2026-07-22)**: records self-describe via a
  `health_gate_enabled: false` stamp and `classify_candidate_health` returns
  VALID for successful finite-score disabled records — one change in
  `candidate_eligibility.py`, no parameter threading through
  `_best_trial_winner`'s five call sites, works for every current and future
  call site. *(DS5b)*
- [x] Plan boundary (after `_apply_mode_override_chain`, before the
  `max_epochs` clamp): under partial scope, normalize plan
  `trial_strategy`/`eval_strategy` → `snapshot`; loud `[DATASCOPE]` log.
  **Provenance fields**: the record's existing `trial_strategy` /
  `eval_strategy` hold the EFFECTIVE strategies; new `planned_trial_strategy`
  / `planned_eval_strategy` / `strategy_normalization_reason` record the
  pre-normalization plan (no duplicated `effective_*` fields). *(DS5b)*
- [x] `build_sample_set` call sites pass `scope=agent_input.data_scope`;
  sandbox constructed with `data_scope` (StubSandbox/RecordingSandbox
  factories accept it — DS3 param / `**kwargs`). *(DS5b)*
- [x] **`scope_violation` is non-retryable (DS3 follow-through)**: detection
  at all three surfaces — training error dict, inference error dict, and
  `except ScopeViolationError` ahead of the generic scoring handler — sets a
  flag mirroring the `_gate_aborted` pattern, breaks both loops before any
  retry/fail-round bookkeeping, and `_compute_termination_state` gained
  precedence-0 → `("failed", "scope_violation")`;
  `HyperparamTuningOutput.termination_reason` Literal extended accordingly.
  *(DS5b)*
- [x] `agent/prompts.py` `_format_fixed_params_block` (`:706`) — when scope is
  partial, disclose the allowed files and the snapshot-only rule. *(DS5c)*
- [x] Scope stamps: `ExperimentRecord` + `HyperparamTuningOutput` gain
  `resolved_data_scope` + `health_gate_enabled` (+ record provenance fields;
  output also `health_checks_config_source` + `health_config_sha256`).
  Stamps are written on final records (success / failed_mode_collapse) —
  the only records that participate in eligibility and scalar comparison;
  error records keep their minimal shape. *(DS5b)*
- [x] Tuner CLI: `--data_scope`, `--health_gate_enabled/--no-health_gate_enabled`,
  `--health_gate_files`. *(DS5c)*
- [x] `tests/pseudo_data/` two-file rule evaluated: canned files mirror LLM
  responses and subprocess results only — no file mirrors
  `ExperimentRecord`/`HyperparamTuningOutput`, and all new schema fields
  default to `None`, so no pseudo-data changes are required for DS5b. *(DS5b)*

**Tests**:
- [x] Schema: internal-consistency validators only (disabled+files → error;
  `[]` → error; partial scope + formal target **passes schema**, fails
  `validate_runtime_config` — asserting the split); old serialized inputs
  without the new fields still validate
  *(DS5a — `test_data_scope_input.py`, 16 tests, 16/16 in 1.95s)*
- [x] `validate_runtime_config`: each failure mode (formal target/anchors,
  out-of-scope `file_index`, enabled+partial+None files, out-of-range scope)
  fails with distinct messages; disabled+partial passes without files;
  trial mode ignores `file_index` *(DS5a; the health-files subset check is
  `validate_health_scope`'s job at materialization — DS5b)*
- [x] Normalization: plan with `target`+`anchors` under partial scope →
  effective snapshot + provenance fields persisted + logged; snapshot plan
  under partial scope → reason `None`
  *(DS5b — `test_data_scope_tuner_pseudo.py`)*
- [x] Disabled mode (pseudo): full loop with `health_gate_enabled=False` —
  `evaluate_and_persist_health_gates` provably never called (monkeypatched
  to raise), records carry `health_gate_enabled=False` +
  `health_gate_results=[]` + `gate_action=None`, best-valid tracking
  populated via Option B, no effective config materialized *(DS5b)*
- [x] Pseudo-mode integration: full tuner loop with `data_scope=[4..9]` +
  `health_gate_files=[4,7,9]` on the Recording stack — normalization
  provenance on every record, output + run_config + records stamped,
  effective config materialized in the workspace, gate machinery reachable
  each round. (SampleSet ⊆ scope is guaranteed by the DS2/DS3 layers'
  unit tests; RecordingSandbox does not capture sample-set kwargs.) *(DS5b)*
- [x] Scope-violation abort (pseudo): canned training scope-violation result
  → `status="failed"`, `termination_reason="scope_violation"`, exactly ONE
  plan call and ONE training call despite `attempts_per_round=3` (no
  retries) *(DS5b)*
- [x] Behavioral-identity regression: default-scope pseudo loop completes
  with full-scope stamps and no normalization; new metadata artifacts
  (effective config) expected *(DS5b; plus eligibility suite 18/18 and
  gate-integration 48/48)*
- [x] Eligibility Option B unit tests (`test_candidate_eligibility.py`, +5):
  disabled-run success → VALID; failed status / non-finite score still
  INVALID; explicit True and legacy None take the normal gate-requirement
  path *(DS5b — 18/18)*

**Verification checklist**:
- [x] `run_config_{run_name}.json` from a pseudo run contains
  `resolved_data_scope`, `health_gate_enabled`, source + effective config paths
  *(asserted on disk by `test_data_scope_tuner_pseudo.py:161-169`)*
- [x] Startup failure paths verified fail **before round 1**
  *(DS5c: `TestStartupFailsBeforeRound1`, 2 tests — `run()` with partial
  scope + missing/out-of-scope `health_gate_files` raises with the LLM
  bridge provably never constructed)*
- [x] `grep -n "load_health_gates_config" nodes/ml_hyperparameter_tune_agent/`
  → all call sites reachable in a run use `agent_input.health_checks_config`
  (i.e. the swapped effective path); none hardcodes the shipped config except
  the documented eligibility/production-policy sites
  *(verified 2026-07-23: zero direct `load_health_gates_config` calls in the
  tuner; every site reads the input field swapped at `:1338`)*
- [x] Full unit + pseudo integration suites green; ruff + pyright clean
  *(2026-07-23: `tests/unit/` 3917 passed / 1 skipped / 3 xfailed;
  `tests/integration/ -m "not real_run"` 123 passed / 1 skipped /
  129 deselected / 2 failed — both failures confirmed pre-existing on
  master `9e503ea` and unrelated to DataScope: `test_vocab_accumulation`
  (FU-7) and `test_gate_coverage_round_7` (FU-9, broken since its
  introducing commit `ed1de46`); ruff check + format clean; pyright clean)*

**Test gate**: unit only (prompt change is disclosure-only; Gate 1 deferred to
Checkpoint DS).

**Implementation notes** (2026-07-22/23, DS5b):
- `termination_reason` Literal extended with `"scope_violation"` — caught by
  the new abort pseudo test (serialization fell into the DEGRADED partial-
  output path until extended).
- **Regression audit of `tests/integration/workflows/` (7 failures)**: 6
  confirmed **pre-existing on master** via a clean master worktree —
  `vocab` (NoneType, degraded interp path), `score_table` +
  `cognitive_alignment` (test-local `RecordingOpenAIBridge` missed the
  `label=` kwarg fix `54412af`; hidden in keyless CI because the tests
  skip), `l_fail`/`k9`/`n_recent` (two-layer: H100-inflated VRAM estimates
  vs 0.1 GB fixture budgets, PLUS the **M9 pseudo-gate gap** — since PR
  #116 made blocking gates fire every round, a pseudo test that neither
  patches the gate fns nor produces denoised HDF5s cannot record a
  `success` round; master with the budget fixed fails the identical
  success-count assertion, 97s run). 1 failure was **DS5b's**:
  `test_healthgate_ten_collapse_continuation` monkeypatched
  `get_gates_for_position` as a single-arg lambda — stale test double
  (production behavior by design); fixed with `**_kwargs` + a DS5 comment.
- Ten-collapse test reduced 10 → `N_ROUNDS = 4` rounds (operator decision
  2026-07-23): 4 = one past `max_fail_rounds=3`, the minimal count proving
  collapsed-but-completed rounds don't increment the failure brake; rounds
  5–10 were ~4 min of repetition per run with no added coverage. Verified
  passing alone: 1/1 in 2:54 (was ~8 min).
- One 10-round verification run flaked via **CPU contention** (concurrent
  pytest → VRAM structural probe exceeded its 60s timeout → an extra
  attempt drained the canned responses). Lesson recorded: verify heavy
  pseudo loops serially on this box.
- **Test results (DS5b)**: `test_data_scope_tuner_pseudo.py` 5/5;
  eligibility 18/18; gate-integration 48/48; ten-collapse 1/1 (4-round);
  ruff + pyright clean.
- **Interlude before DS5c (2026-07-23, commits `91efb07` + `c382733`)** —
  resolving the regression-audit findings before resuming, per operator
  direction:
  - **Production bugfix `91efb07`**: peeling the l_fail layers exposed a
    2-month-old production bug — `KillerReport` hardcoded
    `status="schema_violation"` and the VRAM wrapper's infeasible path
    passed it through, so the tuner's D.4 branch swallowed every
    over-budget verdict as `skipped_schema_violation`, starving
    `skipped_oom_risk`, the B.3 PhysicalRejection buffer, the K.7
    gate-exhaustion triggers, and the Phase-K record fields (full
    status-flow audit in the commit message). Fixed: over-budget →
    `status="success"`, `feasible=False` (the evaluate_time_skill
    sibling convention); `schema_violation` reserved for real
    ValidationErrors. VRAM suite 128/128.
  - **Test-repair `c382733`** (all six failures pre-existing on master):
    label-kwargs bridges (score_table, cognitive_alignment); l_fail/k9
    budgets 0.1→0.3 GB (H100-era estimates) + `health_gate_enabled=False`
    (Option C — choreography tests opt out via the DS5 switch; the flag's
    first production-style consumers); k9 stale K.2.5-8 assertions removed
    (surface retired by A.8 `8b6c4ba`); n_recent fixture epochs 10→1 +
    factor 143.4x→335.1x (estimator-constant drift; real pre-flight chain
    untouched); ten-collapse `N_ROUNDS=4`.
  - Serial verification: ten_collapse, l_fail, k9, n_recent(2),
    score_table green; cognitive_alignment green in a prior run (remaining
    failure = real-LLM output variance, documented). `vocab`'s NoneType
    remains the one confirmed-unrelated defect → issue to file in DS8
    (FU-7).

**Implementation notes** (2026-07-23, DS5c):
- Prompt disclosure: `_format_fixed_params_block` takes
  `resolved_data_scope` (None = full scope → block unchanged); partial
  scope renders the allowed-file line, two forced-snapshot lines, and a
  control-surface bullet without `target_files`. Tuner passes
  `resolved_data_scope if scope_is_partial else None`; `LLMBridge.plan`
  threads the kwarg.
- CLI: `--data_scope` / `--health_gate_files` parse via
  `DataScope.from_cli` (empty-list schema guard unreachable from CLI by
  construction); `--health_gate_enabled` via `BooleanOptionalAction`.
- Tests: `test_data_scope_cli_and_prompt.py` — 4 CLI + 6 prompt +
  2 startup-fails-before-round-1 (LLM bridge provably never
  constructed). 12/12.
- **DS5b regression fixed** (own commit): `materialize_effective_config`
  exists-then-open crashed 19 `test_tuning_agent.py` tests whose
  fixtures patch `os.path.exists` globally; replaced with
  read-then-fallback (`try/except FileNotFoundError`, also removes the
  TOCTOU race). Root cause of the escape: DS5b verified targeted suites
  only — full unit suite must be re-run after any startup-path change.
- **`real_run` opt-in enforced** (own commit, operator-approved
  Option A): bare `pytest tests/integration/` with keys in `.env` ran
  real-LLM + real-training tests, contradicting
  `docs/pseudo_test_infra.md` §4C. New `pytest_collection_modifyitems`
  hook in `tests/conftest.py` skips `real_run` items unless
  `--real-llm` / `--real-training` / `--real-api-call` is passed.
- **Pre-existing broken test found + repaired** (own commit):
  `test_gate_coverage_round_7.py::test_healthy_output_at_round_7_still_passes`
  fails since its introducing commit `ed1de46` (verified on clean
  extracts of `ed1de46` and `9e503ea`): fixture put the healthy file at
  index 12 while the M9 YAML peeks `[3,10,17]` → all peeks unresolved →
  fail-closed `any_pass` correctly fails. Test-side repair: fixture maps
  the healthy file at the configured peek indices.
- **Test results (DS5c)**: `tests/unit/` 3917 passed / 1 skipped /
  3 xfailed; `tests/integration/ -m "not real_run"` 123 passed /
  1 skipped / 2 failed (FU-7 vocab + the gate-coverage test above, both
  pre-existing on master; latter repaired in the follow-up commit);
  ruff check + format clean; pyright clean.

---

### Commit DS6 — workflow / protocol / CLI + scope homogeneity

**Goal**: scope enters at the workflow level, propagates via protocols, and the
workspace becomes scope-homogeneous (atomic lock + ingress validation +
functional campaign identity).

**Code**:
- [x] `workflows/model_exploration.py` — `run_workflow(data_scope=...,
  health_gate_enabled=..., health_gate_files=...)`; resolve once; pre-flight
  `validate_runtime_config` equivalents (fail before iteration 1's LLM calls).
  *(DS6b)*
- [x] **Atomic run-invariants lock**: `{workspace}/run_invariants_lock.json`
  created via same-directory temp file + `os.link` (first writer wins;
  losing writer re-reads and validates. Corrected from the round-4 text's
  `os.rename`, which silently overwrites on POSIX — i.e. LAST writer wins;
  `os.link` is equally atomic and fails with `FileExistsError` on an
  existing lock, which is exactly the intended semantics). Implemented as
  the generic module `core/run_invariants.py` (operator decision
  2026-07-23: run invariants are a distinct responsibility from campaign
  artifacts; generic API `write_run_invariants` / `load_run_invariants` /
  `validate_run_invariants` / `ensure_run_invariants` so future immutable
  run-level fields join without redesign). Content: canonical resolved scope +
  `health_gate_enabled` + `health_config_sha256` (null when disabled) +
  `created_at`. **Equality = the three canonical fields only**; timestamps
  excluded. Later iterations, `--resume` paths, standalone tuner runs against
  the same workspace, and `core/resume.restore_prior_state` read-and-validate,
  fail fast on mismatch (scope change, enabled flip, or policy-content drift
  each produce a distinct error message).
  *(DS6b — workflow startup, standalone tuner, `restore_prior_state`;
  ticked in DS6c: `run_one_iteration.compute_expected_invariants` now
  threads `expected_invariants` into `restore_prior_state` in production,
  computed BEFORE restore so a violation mutates nothing)*
- [x] **Ingress validation**: seed summaries / seed_records / restored outputs /
  `run_comparison.seed_agent_memory` — compare each record's
  `resolved_data_scope` (missing = full scope) against the run scope; mismatch
  → startup `ValueError` naming the offending record path.
  *(DS6b — seed summaries + restored outputs via
  `validate_stamped_invariants` in `run_workflow` pre-flight,
  `restore_prior_state`, and tuner resume-history. DS6d —
  `seed_agent_memory` validated at seeding time (plus re-validated at
  consumption by the tuner). `seed_records` discovered DEAD during DS6d:
  schema-only, zero consumers — actual seeding flows through
  `seed_agent_memory` → summary file → `get_summary()`; nothing to
  validate, field slated for DS7 dead-field removal)*
- [x] `agent/schemas/protocols/ml_model_valid_to_ml_model_tune.py` — thread
  `data_scope` + `health_gate_enabled` + `health_gate_files`. *(DS6b)*
- [x] `sdsc_submission_scripts/run_one_iteration.py` + `_chain_common.sh` +
  `run_chain.sh` — `--data_scope "4-9"` / `--health_gate_enabled|--no-...` /
  `--health_gate_files "4,7,9"` (parsed via `DataScope.from_cli`). *(DS6c —
  both range and list forms per the resolved open question;
  `run_chain.sh` sources `_chain_common.sh`, so the shell change is
  single-sited; the three flags joined the §3.2 CONTRACT_FLAGS parity
  contract)*
- [x] Iteration manifest + `core/campaign_artifacts.py` — resolved scope in
  manifest; **functional reuse check**: `decide_phase1_reuse` / campaign
  validation adds `"data_scope mismatch"` error (pattern of
  `campaign_artifacts.py:80`); reuse never proceeds on mismatch.
  *(DS6c — completed manifests stamp `resolved_data_scope` +
  `health_gate_enabled` + `health_config_sha256`; DS6d —
  `validate_phase1_baseline` / `decide_phase1_reuse` gain
  `expected_resolved_data_scope` (None = legacy skip; unstamped record =
  full scope), the campaign manifest carries the three invariants, and
  reuse-path expected outputs iterate the resolved scope)*
- [x] `scripts/run_comparison.py` — `--data_scope` forwarded to baseline
  builders (baseline SampleSet built within scope, per round-3 §11) and the
  agent subprocess; effective-config materialization at campaign startup;
  v17_pregate override pin. *(DS6d — baseline sample sets + sandbox scoped;
  baseline record stamps invariants; disabled mode mirrors the tuner (no
  gate evaluation, empty results); raw spec strings forwarded verbatim to
  the tuner CLI — one parser, no drift; campaign startup materializes +
  path-swaps and locks the baseline workspace with the deferred
  legacy-history check; v17_pregate additionally forbids
  --health_gate_files / --no-health_gate_enabled)*

**Tests**:
- [x] Unit: atomic lock (concurrent create race simulated → single winner,
  loser validates; equality ignores timestamps); lock-violation matrix —
  scope change / `health_gate_enabled` flip / `health_config_sha256` drift
  each fail with their distinct message; ingress validation
  (stamped-match, stamped-mismatch, legacy-unstamped=full); protocol
  threading; CLI parsing round-trip
  *(DS6b — `test_run_invariants.py` 27,
  `test_resume.py::TestRunInvariantsIngress` 6, protocol
  `TestDataScopeThreading` 3, workflow `test_data_scope_preflight.py` 8.
  DS6c completes the bullet: chain-CLI round-trip + wiring + manifest
  stamps in `test_run_one_iteration.py` (+10: both spec forms
  canonicalize identically, malformed → parser error,
  `compute_expected_invariants` 3 cases, main() wiring 2 incl.
  conflicting-second-invocation crash-before-workflow, manifest stamp
  1); parity contract extended to the three new flags)*
- [x] Campaign: manifest with mismatched scope → `ValidationReport` error;
  matching scope → reuse allowed *(DS6d — `test_campaign_artifacts.py` +5:
  legacy-unstamped vs full/partial, stamped match/mismatch, None-skip
  back-compat)*
- [x] Pseudo-mode workflow test: one-iteration `run_workflow` with partial
  scope on stubs — lock written, tuner input carries scope, manifest stamped
  *(covered by three targeted tests instead of one full pseudo loop:
  lock-written via the pre-flight sentinel test, input-carries-scope via
  the protocol threading test, manifest stamp via
  `TestManifestInvariantStamps`; the full end-to-end chain pseudo smoke
  is the verification-checklist item below, deferred to the DS-series
  end per the amended test policy)*
- [x] Pseudo-mode: seeded workflow with full-scope legacy seeds + partial scope
  → fails at ingress with the documented error *(DS6b —
  `test_data_scope_preflight.py::test_legacy_full_scope_seed_vs_partial_run`;
  fails before the lock is stamped, no LLM stubs needed)*

**Verification checklist**:
- [x] Chain smoke in pseudo mode (`run_one_iteration.py` with `--pseudo` +
  `--data_scope 4-9 --health_gate_files 4,7,9`) completes; second invocation
  with a different scope against the same workspace **fails at startup**
  *(DS8, 2026-07-23 — `--is_pseudo_llm --is_pseudo_training` cold start,
  exit 0 with graceful `no_records` manifest (stub sandbox, no scored
  records on this box); `run_invariants_lock.json` written with
  `[4..9]` + enabled + sha, `health_checks_effective.yaml` materialized
  at the chain root. Negative matrix all exit 1: conflicting
  `--health_gate_files` → materialized-config immutability guard;
  `--no-health_gate_enabled` + files → schema inconsistency; different
  scope with gates disabled → run-invariants lock violation raised from
  `restore_prior_state` (the DS6c `expected_invariants` threading
  proven in production), each with a crashed manifest)*
- [x] Full unit + pseudo integration suites green; ruff + pyright clean
  *(DS8, 2026-07-23 — `tests/unit/` **3998 passed** / 1 skipped /
  3 xfailed (4:29); `tests/integration/ -m "not real_run"` **124
  passed** / 1 failed (only FU-7 vocab, filed as issue #129) / 1
  skipped / 129 deselected (9:28); ruff check + format clean repo-wide;
  pyright clean repo-wide)*

**Test gate**: unit only.

**Implementation notes** (2026-07-23, DS6a — lock module):
- `core/run_invariants.py`: `RunInvariants` (frozen Pydantic;
  `resolved_data_scope` + `health_gate_enabled` + `health_config_sha256`
  canonical, `created_at` provenance-only), `RunInvariantsViolation`,
  `write_run_invariants` (temp + `os.link`; see the corrected bullet
  above), `load_run_invariants` (absent → None; corrupted → violation,
  never silently regenerated), `validate_run_invariants` (drift report
  names each drifted field with locked vs attempted values),
  `ensure_run_invariants` (create-or-validate startup entry, returns
  `"created"` / `"validated"`).
- Tests: `tests/unit/core/test_run_invariants.py` — 14 tests: round-trip,
  timestamp excluded from equality, first-writer-wins + loser-validates,
  violation matrix (scope / enabled flip / sha drift each name only the
  drifted field), corrupted-lock refusal, no stray temp files, flat
  hand-inspectable JSON shape. 14/14 (1.4s); ruff + format + pyright
  clean.
- Wiring into workflow startup / standalone tuner / resume / campaign
  validation lands in the subsequent DS6 commits; bullets stay unticked
  until then.

**Implementation notes** (2026-07-23, DS6b — workflow/tuner/protocol/resume
wiring; operator invariants 1–5 recorded in this session's directions):
- Shared computation (invariants 1/2/5): new
  `core/run_invariants.build_run_invariants` materializes + hashes the
  effective HealthGate config FIRST, then constructs `RunInvariants` —
  the one path both `run_workflow` pre-flight and the tuner startup call;
  `validate_stamped_invariants` is the shared legacy-aware ingress check
  (unstamped scope = full; unstamped enabled = gates-active, compatible
  only with enabled runs; missing sha = pre-policy-lock, skipped).
- Tuner: DS5b's inline materialization replaced by the shared helper. An
  existing lock is validated at startup (before hardware/LLM/sandbox);
  lock CREATION is deferred until `sandbox.get_summary()` history is
  stamp-validated (final records only — error records carry no stamps by
  design), still before the first plan call. Invariant 3: a legacy
  workspace is never silently locked.
- `run_workflow`: three new params; pre-flight after Step-0 seed loading —
  operator-contract checks (partial+formal_strategy, enabled+partial+no
  files), `build_run_invariants` at the CHAIN ROOT (`workspace`, shared
  across iterations — the scalar-comparability boundary; per-iteration
  tuner dirs get their own identical-sha lock), stamp-validation of every
  loaded seed/restored output, THEN `ensure_run_invariants`. The original
  `health_checks_config` (not the chain-root effective path) is still
  forwarded to tuners — each tuner re-materializes into its own workspace
  and pins the identical body sha.
- Protocol `local_validated_model`: threads the three fields;
  `data_scope=None` normalizes to the explicit full scope at the protocol
  layer so the input always carries a concrete `DataScope`.
- `core/resume.restore_prior_state(expected_invariants=None)`: validates
  an existing workspace lock up front and each prior iter's parsed
  run_output stamps BEFORE that iter's plugin registration (zero registry
  mutation on mismatch — invariant 4). Production threading of
  `expected_invariants` from the chain CLI lands in DS6c.
- Guard layering discovered while testing: with gates enabled, changed
  operator inputs on a locked workspace hit the materialized-config
  immutability guard (DS4) before the lock check — both are pre-LLM
  fail-fast; the lock additionally covers what materialization can't see
  (scope drift with identical health inputs, enable flips, disabled
  runs). Pinned by
  `test_data_scope_preflight.py::TestPreflightPass` (both orders).
- Tests: `test_run_invariants.py` 27/27 (+13);
  `test_resume.py::TestRunInvariantsIngress` 6/6; protocol
  `TestDataScopeThreading` 3/3 (file 49/49);
  `test_data_scope_preflight.py` 8/8 (sentinel on
  `ResultInterpretationAgent` proves lock-before-first-agent with no LLM
  stubs); DataScope tuner regression set 33/33.
- **Full-suite results (2026-07-23, pre-commit)**: `tests/unit/` **3963
  passed** / 1 skipped / 3 xfailed (4:23);
  `tests/integration/ -m "not real_run"` **124 passed** / 1 failed
  (FU-7 vocab only — pre-existing on master) / 1 skipped / 129
  deselected (9:42); ruff check + format clean; pyright clean.

**Implementation notes** (2026-07-23, DS6c — chain CLI + restore threading
+ manifest stamps; verified per the amended targeted-suite policy):
- `run_one_iteration.py`: three flags (specs parsed in `normalize_args`
  via `DataScope.from_cli`, malformed → `parser.error`); new
  `compute_expected_invariants(args)` calls the shared
  `build_run_invariants` BEFORE `restore_prior_state` (invariant
  computation failure or `RunInvariantsViolation` → crashed manifest +
  exit 1, zero resume mutation); the three params thread into
  `run_workflow`; completed manifests stamp `resolved_data_scope` /
  `health_gate_enabled` / `health_config_sha256`.
- `_chain_common.sh` (single-sited — `run_chain.sh` sources it):
  `DATA_SCOPE` / `HEALTH_GATE_ENABLED` / `HEALTH_GATE_FILES` defaults,
  case arms (boolean pair mirrors `FORCE_FORMAL_ROUND`), APP_ARGS
  forwarding (only `--no-health_gate_enabled` forwarded, matching the
  Python default), summary echo. Flags added to the §3.2 CONTRACT_FLAGS
  parity contract.
- FU-8 closed with the opposite resolution (see tracker): the attempted
  `n_recent` opt-out was correctly rejected by DS6b ingress (legacy
  unstamped seeds are gates-enabled-only) and reverted — a live
  validation of the ingress rule.
- **Tests (DS6c)**: `test_run_one_iteration.py` 53/53 (+10);
  `test_chain_consistency.py` parity green with the extended contract;
  `n_recent` 2/2 after revert; ruff + format + pyright clean; `bash -n`
  clean on both shell scripts.

**Implementation notes** (2026-07-23, DS6d — run_comparison + campaign
identity; targeted-suite policy):
- `run_comparison.py`: three CLI flags; spec parse + v17_pregate override
  pin (forbids `--health_gate_files` / `--no-health_gate_enabled`) fire at
  `main()` startup, before the source-config policy check and any phase
  work. Campaign startup materializes the effective config into the
  baseline workspace, path-swaps `args.health_checks_config`, validates
  existing baseline summary records (deferred-lock pattern), and
  `ensure_run_invariants`s the baseline workspace. `run_baseline_trial`
  gains `data_scope` / `health_gate_enabled` / `health_config_sha256`:
  sample sets built with `scope=`, sandbox constructed with `data_scope=`,
  disabled mode skips gate evaluation (mirrors the tuner), record stamps
  the three invariants; reuse-path expected outputs iterate the resolved
  scope. `seed_agent_memory` ingress-validated at seeding time. `run_agent`
  forwards the operator's raw spec strings verbatim to the tuner CLI.
- `campaign_artifacts.py`: `expected_resolved_data_scope` param on
  `validate_phase1_baseline` / `decide_phase1_reuse` → `"data_scope
  mismatch"` error; unstamped records = full scope; None = legacy skip.
- `seed_records` found dead (schema-only, zero consumers) → DS7 removal
  list; ingress for it is vacuous.
- **Tests (DS6d)**: `test_campaign_artifacts.py` 12/12 (+5);
  `test_run_comparison_data_scope.py` 6/6 (startup guards ×3, subprocess
  forwarding ×3 — completion verification's `sys.exit(2)` on the empty
  test workspace is the PR #121 partial-exit contract, absorbed by the
  harness); completion + v17_advice suites 16/16 unchanged; ruff +
  format + pyright clean.
- Operator audit rider (2026-07-23): backward-compat audit delivered —
  behavioral identity holds for default configs; deliberate breaks are
  workspace policy immutability, legacy-resume-with-disabled-gates
  refusal, the closed `score_vector` validation gap, and two new
  workspace artifacts. Follow-up approved as a separate commit: FU-10
  `plan_overrides` fail-fast hardening (see tracker).

---

### Commit DS7 — dead-field removal, deprecations, proposer preflight scope

**Goal**: remove fields that are dead at both ends; give the proposer
`data_scope` for its *actual* need (pre-flight synthesis + disclosure);
deprecate CLI flags per the `--source_paths` precedent
(`run_one_iteration.py:447`).

**Code**:
- [x] Delete `HyperparamTuningInput.trial_strategy` / `eval_strategy` /
  `target_files` (+ their validator, `:1157-1164`) — serialization-safe (no
  `extra="forbid"`, not in `run_config` dump). `ExperimentRecord` copies stay.
  *(DS7a)*
- [x] Delete `HyperparamTuningInput.seed_records` — discovered dead during
  DS6d (schema-only, zero consumers anywhere; seeding actually flows
  through `run_comparison.seed_agent_memory` → summary file →
  `sandbox.get_summary()`). Same serialization-safety argument. *(DS7a)*
- [x] Delete `ProposalInput.trial_strategy` / `target_files`
  (`proposal.py:689,702`) — confirmed consumed by nobody (round-3 audit;
  re-verified by fresh grep before deletion). Keep `is_trial` /
  `trial_portion` / `train_portion` (live). *(DS7a)*
- [x] Add `ProposalInput.data_scope`; `local_full_context` maps it from the
  workflow's resolved scope; proposer prompt context renders the allowed-file
  list + snapshot-only note when partial. *(DS7b — `[DATA SCOPE]` block
  rendered in BOTH prompt paths: legacy `_build_reasoning_prompt` and the
  pipeline-mode user prompts incl. the preflight retry path; empty string
  for full scope so pre-DataScope prompts are byte-identical)*
- [x] `agent/utils/proposer_preflight.py` —
  `_synthesise_default_sample_set(trial_portion, scope)` builds the synthetic
  snapshot **within scope** (`:61-64`; delivers what the dead fields'
  docstrings promised: the estimate matches what the tuner will run).
  *(DS7b — `estimate_proposal_time(data_scope=...)` threads it; proposer
  passes `inp.data_scope`)*
- [x] `workflows/model_exploration.py` — drop the now-unused
  `trial_strategy`/`target_files`/`eval_strategy` kwargs from the tuner and
  proposer paths; keep accepting them at CLI level as deprecated no-ops.
  *(DS7a — run_workflow keeps the params as deprecated no-ops that warn on
  non-default values, so in-process callers don't break; both protocol
  forwarding sites dropped)*
- [x] Tuner CLI `--trial_strategy` / `--eval_strategy` and chain CLI
  `--trial_strategy` / `--target_files`: accepted, warn, ignored. Removal
  scheduled after the next stable chain run (FU-2). *(DS7a)*
- [x] `_chain_common.sh` — stop forwarding the deprecated flags (`:304,:332`);
  still parse them so existing invocations don't break. *(DS7a — defaults +
  case arms kept, so the §3.2 parity contract still holds)*
- [x] `tests/pseudo_data/` — update canned `ProposalInput` payloads.
  *(DS7 — no-op verified: canned payloads mirror LLM outputs, not
  ProposalInput; grep found zero pseudo-data references to the removed
  fields, and `data_scope` has a schema default)*

**Tests**:
- [x] Old serialized `HyperparamTuningInput` / `ProposalInput` JSON (with
  removed keys) still validates (extras ignored) *(DS7a —
  `test_hyperparam_schemas.py::TestTrialFieldsInput` rewritten for the
  post-DS7 contract incl. the compat case)*
- [x] Preflight: partial scope → synthetic sample set keys ⊆ scope; estimate
  path unchanged for full scope *(DS7b — plus a strictly-cheaper-estimate
  assertion for a 6-of-20-file scope)*
- [x] Proposer pseudo test: partial-scope `ProposalInput` renders the file
  list; full-scope renders unchanged framing *(DS7b —
  `TestDataScopeBlock` in `test_prompt_context_surfacing.py`)*
- [x] CLI deprecation: invoking with `--trial_strategy target` warns and does
  not alter behavior *(DS7a — runner `TestDeprecatedStrategyFlags` 3, tuner
  CLI `TestDeprecatedStrategyFlagsTunerCLI` 2, workflow
  `TestDeprecatedStrategyParams` 1; deprecated values provably never reach
  `run_workflow` kwargs)*

**Verification checklist**:
- [ ] `grep -rn "trial_strategy" agent/schemas/hyperparam_tuning.py` — only
  `ExperimentPlan` / `TrialConfig` / `ExperimentRecord` hits remain
- [ ] `grep -rn "trial_strategy\|target_files" agent/schemas/proposal.py` — no
  hits
- [ ] Full unit + pseudo integration suites green; ruff + pyright clean

**Test gate**: unit only + **Gate 1** (proposer prompt context changed — may be
batched with Checkpoint DS Gate 1).

**Implementation notes** (2026-07-23, DS7a — dead-field removal +
deprecations; targeted-suite policy):
- Deleted after a fresh zero-consumer grep re-confirmed the audit:
  `HyperparamTuningInput.{trial_strategy,eval_strategy,target_files,
  seed_records}` (+ the `_validate_trial_fields` cross-field validator) and
  `ProposalInput.{trial_strategy,target_files}`. `ExperimentPlan` /
  `TrialConfig` / `ExperimentRecord` copies are live and untouched.
- Threading dropped at both protocols (`local_validated_model`,
  `local_full_context`) and both `run_workflow` call sites;
  `run_workflow` keeps the three params as deprecated no-ops (warn on
  non-default). Runner + tuner CLIs warn-and-ignore; `_chain_common.sh`
  parses but no longer forwards (§3.2 parity intact).
- `tests/pseudo_data/` untouched by design: canned payloads mirror LLM
  plan outputs (`ExperimentPlan`, live), not the deleted input fields —
  two-file rule satisfied vacuously.
- **DS7b (2026-07-23)** — `ProposalInput.data_scope` (schema default =
  full); `local_full_context(data_scope=...)` mapping; workflow passes its
  run scope; `_synthesise_default_sample_set(scope=)` +
  `estimate_proposal_time(data_scope=)` so the pre-flight wall-time gate
  prices exactly the in-scope training cost; `_render_data_scope_block`
  injected beside the hardware block in both prompt paths + the
  pipeline retry path. Tests: prompt-block 3, scoped-synthesis 3,
  protocol pass-through 2; affected sweep (protocols + proposer + utils +
  schemas + workflows) 907/907; ruff + format + pyright clean.
- Tests: 12 pre-rewrite failures repaired across
  `test_hyperparam_schemas.py` (class rewritten for the post-DS7
  contract + serialization-compat case) and both protocol test files
  (dead-field cases dropped, `not hasattr` pins added); +6 new
  deprecation tests (runner 3, tuner CLI 2, workflow 1). Affected
  suites: protocols + schemas 209/209; runner + chain-parity +
  workflows 296/296; broad affected sweep 2942 passed pre-fix with only
  the 12 known failures; ruff + format clean repo-wide.

---

### Commit DS8 — docs, invariants, follow-up filing, connection audit

**Goal**: docs and code in lock-step; graph-level audit before the checkpoint.

**Code / docs**:
- [x] `CLAUDE.md` — amend the health-YAML invariant wording (YAML = checks /
  thresholds / actions / **default** file placement; per-run enable +
  monitored files = run-level inputs; effective config materialized to the
  workspace); add a *Subsystem Invariants* entry for `DataScope`
  (constructive + boundary + direct-access enforcement; scalar
  scope-homogeneity rule; snapshot-only under partial scope; behavioral
  identity of the default). *(DS8 — also refreshed the ephemeral Current
  State section (was 9 days stale) and re-synced the byte-identical
  AGENTS.md)*
- [x] `README.md` — short section under *Common workflows*: scoped run example
  (`--data_scope 4-9 --health_gate_files 4,7,9`), plus the disabled-gate
  example (`--no-health_gate_enabled`). *(DS8)*
- [x] `docs/design/v18_priorities.md` — note: chain-wide best-valid-formal
  incumbent must be **scope-keyed**. *(DS8 — added to §3.4)*
- [x] File GitHub issue: pre-existing peek-vs-eval-coverage latent bug (full
  scope + LLM `eval_strategy="target"` → spurious blocking-gate failures);
  reference this doc's audit section. *(DS8 — filed as
  [#128](https://github.com/Galileo-Sandbox/SIDERIUS/issues/128); FU-7's
  vocab test defect filed as
  [#129](https://github.com/Galileo-Sandbox/SIDERIUS/issues/129))*
- [x] **Connection audit** (step-7 style): every field required by
  `HyperparamTuningInput` / `ProposalInput` present in upstream protocol
  sources; scope + health fields mapped by `local_validated_model` and
  `local_full_context` with no silent defaults; pseudo-data shapes match
  schemas. *(DS8 — scripted audit passed: three DataScope/HealthGate
  fields present on tuner input + protocol; `data_scope` on proposer
  input + protocol with explicit mapping; output/record stamps present;
  dead fields absent from both inputs; pseudo-data untouched by design
  — canned payloads mirror live ExperimentPlan outputs)*

**Verification checklist**:
- [x] `uv run pytest tests/unit/ -q` and `uv run pytest tests/integration/ -q`
  (pseudo) — full green *(DS8 — unit 3998 passed; integration pseudo 124
  passed with only the pre-existing FU-7/issue-#129 failure)*
- [x] ruff check + ruff format --check + pyright — clean repo-wide *(DS8)*
- [x] Doc cross-references resolve (paths exist) *(DS8 — all 23
  referenced paths verified present)*

**Test gate**: unit only.

**Implementation notes**: *(fill in as work lands)*

**Implementation notes** (2026-07-23, DS8 — docs, issues, audits, final
suites; executed under the operator's autonomy grant):
- CLAUDE.md: HealthGate config invariant reworded (YAML = policy +
  default file placement; enable flag + monitored files = run-level
  inputs; effective config materialized per workspace), new DataScope
  Subsystem Invariants entry, ephemeral Current State refreshed
  (was 9 days stale); AGENTS.md re-synced byte-identical.
- README: scoped-run section under Common workflows (both CLI spec
  forms, disabled-gate example, lock semantics).
- v18_priorities §3.4: incumbent must be scope-keyed.
- Issues filed: [#128] FU-1 peek-vs-eval-coverage latent bug;
  [#129] FU-7 vocab-accumulation NoneType test defect.
- Connection audit: scripted — three DataScope/HealthGate fields present
  on tuner input + protocol signature; `data_scope` on proposer input +
  protocol with explicit mapping; output/record stamps present; dead
  fields absent from both inputs. All 23 doc-referenced paths exist.
- Chain pseudo smoke + negative matrix: see the DS6 verification
  checklist entry (positive exit 0 + lock/effective-config artifacts;
  three distinct startup guards each exit 1).
- Final suites: unit 3998 passed / 1 skipped / 3 xfailed; integration
  pseudo 124 passed / 1 failed (FU-7 = #129 only); ruff + format +
  pyright clean repo-wide.

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
- **FU-7** — `test_vocab_accumulation.py:541` NoneType subscript on the
  degraded-interpreter path (pre-existing, unrelated to DataScope; the one
  unrepaired workflows-suite failure). File as issue in DS8.
- **FU-8** — ~~`n_recent` also needs its Option C `health_gate_enabled=False`
  once DS6 plumbs the flag through `run_workflow`.~~ **Closed (DS6c,
  2026-07-23) with the opposite resolution**: applying the flag was tried
  and DS6b's ingress validation correctly REJECTED it — `n_recent` seeds
  legacy unstamped tuning outputs, which are by design compatible only
  with gates-enabled runs. A workflow-level Option C opt-out requires
  seeds stamped `health_gate_enabled=false`. `n_recent` stays
  gates-enabled (its choreography never reaches gate-dependent rounds —
  why it passes today); l_fail/k9 are unaffected (they construct tuner
  inputs directly, no workflow ingress). The failed attempt doubled as a
  live validation of the DS6b ingress rule.
- **FU-10** — `plan_overrides` fail-fast hardening (operator-approved
  2026-07-23, separate small commit after DS6b): unknown keys fail at
  schema validation; overrides merge over every LLM plan and the
  effective plan revalidates; an invalid effective plan is an
  operator-configuration error that terminates the run — the
  warn-and-use-unclamped-plan fallback
  (`ml_hyperparameter_tune_agent.py:1806-1815`) is removed. Alias-vs-
  python-name key normalization included. No new strategy-lock fields —
  `plan_overrides` + the fixed-params disclosure block remain the
  preferred strategy-locking abstraction.
  *Implemented 2026-07-23*: schema `field_validator` on
  `HyperparamTuningInput.plan_overrides` rejects unknown keys at input
  construction and normalizes python names → aliases (`model_cfg` →
  `model_config`; passing both forms of one field is rejected as
  ambiguous — this also fixes a latent alias bug where a python-name
  override merged into the `by_alias` dump ADDED a stray key instead of
  replacing the field, and the natural alias spelling was warned as
  "unknown"). New `PlanOverridesError(ValueError)` raised by the
  extracted `_apply_plan_overrides` helper; re-raised untouched by the
  attempt handler (folded `isinstance` guard — a separate `except`
  clause pushed `run()` past pyright's complexity ceiling; also
  extracted `_validate_history_and_lock` while reducing). Disclosure
  path unchanged (`_format_fixed_params_block`). Tests:
  `test_plan_overrides_failfast.py` — 5 schema-key tests + a pseudo run
  proving an invalid value terminates after exactly ONE plan call with
  no `attempt_failure` record (the lock is never silently released).
  6/6; adjacent suites 123/123; ruff + format + pyright clean.

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

1. ~~CLI spelling: `--data_scope 4-9` (range shorthand) vs explicit list only —
   DS1 implements both; confirm preference before DS6 lands.~~
   **Resolved (operator, 2026-07-23): support both forms** — `4-9` and
   `4,5,6,7,8,9` (and mixed) — canonicalized internally to one sorted,
   deduplicated resolved list (already `DataScope`'s validator behavior).

*(Resolved in round 3: scoped `run_comparison` baselines are supported — DS6;
HealthGate override applies one shared list to all gates — v1 simplification;
schema vs runtime validation split — see the dedicated section.)*
