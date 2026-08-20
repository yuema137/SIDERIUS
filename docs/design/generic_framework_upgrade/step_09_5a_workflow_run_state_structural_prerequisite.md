# Step 09.5a — Workflow Run-State Structural Prerequisite

**STATUS: DRAFT — REVISION 1 — READY FOR OPERATOR REVIEW. NOT FROZEN.
IMPLEMENTATION NOT STARTED.**

---

## 0. Status, provenance, design audit anchor

| field | value |
|---|---|
| **STEP-09.5a DESIGN AUDIT ANCHOR** | `eb9f667e943bf386ee32a41f7def21bb5b5c548e` |
| local `master` = `origin/master` | `eb9f667e` (verified equal after `git fetch`) |
| working tree at design start | clean |
| **frozen Step-09.5 semantic authority** | `eb9f667e` — `step_09_5_structural_and_test_topology_audit.md`, **REVISION 2 — FROZEN** |
| Step-09.5 audit anchor (measurement base of the parent) | `85fa4b74` |
| Step 09.5 roadmap row | `AUDIT COMPLETE — REVISION 2 FROZEN` |
| Step 09.5a roadmap row | `NEXT — NOT STARTED` |
| Step 10 roadmap row | `NOT STARTED — semantic implementation BLOCKED until Step 09.5a merges` |
| implementation branch | **not created** (Phase 1 is docs-only) |

The design anchor equals the frozen-authority commit: no commit has landed on
master since the Step-09.5 freeze. **Every source measurement below is MEASURED
at `eb9f667e` by this session**, not inherited from the parent audit. Where a
figure differs from the parent's, §3.6 records the delta.

---

## 1. Mandate, semantic owner, non-goals

**Mandate.** Establish explicit semantic ownership boundaries for the
exploration workflow's run-scoped configuration and its cross-iteration state,
and collapse the duplicated committed-interpretation-digest read path to one
authority — **behaviour-preserving**, before Step 10 adds launcher-owned task
binding, new carried state, secondary transport, metric-handle comparisons and
resume semantics.

**Semantic owner.**

1. workflow run-scoped authorities / bindings;
2. restored / carried / persisted exploration-chain state;
3. the single authoritative read + soft-fail path for committed interpretation
   digests used by resume.

**This PR is not "make `model_exploration.py` smaller".** No LOC target is an
acceptance criterion (§31, §33).

**Non-goals — none of these may be implemented (frozen, parent §20.1):**

* production secondary-metric transport; secondary cache carry;
* `vocab_link_confirmations` carry or activation;
* workflow/resume `MetricOrder` migration; dashboard direction migration;
* `evaluation.py` per-check-NAME table cleanup;
* proposer prediction-authoring grammar; proposer direction-blindness;
  proposer legacy/pipeline reader consolidation;
* `campaign_artifacts` semantics;
* **the `core/resume.py:61` private plugin-registry import (Q2 = B → Step 12)**
  and any movement of `_register_plugin` / promotion / global registry
  lifecycle;
* new task binding, task resolver, external loader, plugin registry, or the
  Step-12 composition root;
* **CI topology** — `.github/workflows/ci.yml`, pytest markers and test
  scheduling are the separate non-blocking follow-up (parent §20.2);
* opportunistic renaming of task-shaped field names (§11 of the kickoff; see
  §5.7 here).

---

## 2. Binding authorities

| doc | role |
|---|---|
| `docs/design/generic_framework_upgrade/step_09_5_structural_and_test_topology_audit.md` | **REVISION 2 FROZEN** — the verdict, A-1/A-2, the three amendments, the gate ruling, and §20.1/§20.1a/§20.3/§22 which this child implements |
| `docs/design/siderius_generic_framework_upgrade.md` §15.1c | the roadmap's frozen record of the same, plus sequencing |
| `CLAUDE.md` | responsibility-oriented decomposition (2026-08-01); validation economy (2026-08-18); node/skill doc sync; "every test must name a defect only it can catch" |
| `docs/gates/gate_testing_standard.md` | `:446-452` assignment by commit type; `:262-267` temporal depth; `:397-415` bounded Gate-2 plans; `:238` mandatory `openai_tiered_pro.json` |
| `docs/design/generic_framework_upgrade/step_01_07_extensibility_debt_audit.md` | item 5 — *"do NOT build a per-subsystem loader now"*; items 1/2/4/12/13 remain Step-10/12 |
| **precedent only** — `nodes/ml_hyperparameter_tune_agent/contracts.py` | `RunBindings` (`:79`), `FORBIDDEN_BINDING_FIELDS` (`:44`), `__post_init__` guard (`:173-178`). Its *shape* is precedent; its fields are not copied. |

---

## 3. Current source census — MEASURED at `eb9f667e`

### 3.1 Structure

| symbol | location | size | branch nodes | params |
|---|---|---:|---:|---:|
| `workflows/model_exploration.py` | — | **3,144 LOC** | — | — |
| `run_workflow` | `:1370-2941` | **1,572 lines** | **130** | **99** |
| iteration loop | `:2106-2918` | 813 lines | — | — |
| `main` | `:2982-3139` | 158 | 5 | 0 |
| `core/resume.py` | — | **1,645 LOC** | — | — |
| `restore_prior_state` | `:1229-1587` | 359 | 47 | 4 |

`run_workflow` takes **99 positional-or-keyword parameters, no `*args`, no
`**kwargs`** (MEASURED by AST).

### 3.2 Where the 99 parameters actually go — the decisive measurement

Every parameter's load-sites were resolved to their innermost enclosing call:

| measurement | params |
|---|---:|
| whose **ONLY** sink is `local_validated_model` (the tuner protocol at `:2658`) | **41** |
| that reach `local_validated_model` at all | **57** |
| that reach **any** node-protocol / pipeline sink (`local_validated_model`, `local_full_context`, `InterpretationInput`, `_get_reasoning_pipeline`) | **63** |
| with **no** call sink — workflow-local control flow only | 24 |

**41 of 99 parameters exist for one purpose only: to be forwarded, unmodified,
into a single downstream protocol call**, and 63 are consumed by some node
protocol. They are not workflow authorities and not workflow state — they are
**caller-supplied execution configuration in transit**. This single fact is what
prevents the naive "one `RunBindings` for everything" answer from being a
decomposition (§5.1).

### 3.3 Cross-iteration mutable accumulators — **11**, MEASURED

Names assigned before the loop *and* mutated inside it:

| accumulator | init | mutated at | seeded from |
|---|---:|---|---|
| `iteration_results` | `:1974` | `:2758` | — (cold) |
| `best_score_overall` | `:1979` | `:2858` | — (cold, deliberately never restored) |
| `chain_formal_incumbent_reference` | `:1988` | `:2870` | `restored_chain_incumbent_score` |
| `previous_proposal_data` | `:1997` | `:2835` | `restored_previous_proposal` |
| `current_runtime_vocab` | `:2007` | `:2837` | `restored_runtime_vocab` / `vocab_seed` |
| `current_collapse_fingerprint_history` | `:2022` | `:2202` | `restored_collapse_fingerprint_history` |
| `current_prediction_memory` | `:2027` | `:2822` | `restored_prediction_memory` |
| `model_knowledge_cache` | `:2035` | `:2805`, `:2806` | `restored_model_knowledge_cache` |
| `latest_new_summary` | `:2046` | `:2798` | — (cold) |
| `recent_tune_outputs` | `:2052` | `:2780` | `accumulated_gate_exhaustions` (synthetic wrappers) |
| `all_model_types` | `:1953` | `:2783` | derived from `tuning_outputs` |

Plus two *accumulated-only* inputs consumed but not re-mutated in the loop:
`accumulated_key_findings` (`:2316-2324`) and `accumulated_physical_rejections`
(`:2261-2273`).

### 3.4 The committed-digest readers — **4 identical + 1 different**, MEASURED

All four are called from `restore_prior_state` with **identical arguments**
`(abs_workspace, current_iter, state.committed_iters)`:

| loader | def | call site | digest path |
|---|---|---|---|
| `load_latest_knowledge` | `:789` | `:1478` | `_interpretation_path` `:826` |
| `load_latest_knowledge_cache` | `:1028` | `:1496` | `_interpretation_path` `:1077` |
| `load_latest_fingerprint_history` | `:872` | `:1504` | `_interpretation_path` `:906` |
| `load_latest_prediction_memory` | `:952` | `:1511` | `_interpretation_path` `:982` |

For **N** committed iterations the same digest file is opened and
`json.load`-ed **4 N times** in one restoration pass.

**`load_latest_proposal` (`:1161`, called `:1545`) is NOT one of them** and must
not be folded in: different path family (`_proposal_path` `:1114`), reverse
iteration (`for iter_idx in reversed(committed_iters)` `:1199`), and
first-parseable-wins early return (`:1217`). Recorded explicitly because
name-similarity is the trap (§34, item 13).

### 3.5 Failure policy — identical at file level, DIFFERENT at value level

| stage | `knowledge` | `knowledge_cache` | `fingerprint_history` | `prediction_memory` |
|---|---|---|---|---|
| `current_iter <= 1` or no committed iters | early return | early return | early return | early return |
| missing file | `warn` + continue `:828` | `:1079` | `:908` | `:984` |
| `OSError` / `JSONDecodeError` | `warn` + continue `:839` | `:1090` | `:920` | `:995` |
| **malformed value** | **`warn` + DROP entry, keep rest** `:860` | **no validator** — `isinstance(raw,dict)` else skip `:1101` | **`raise ValueError`** `:939` | **`raise ValueError`** `:1018` |
| merge rule | vocab **latest-wins**; findings **union, first-occurrence** | latest-wins | latest-wins | latest-wins |

**This table is the design's single most important constraint.** The *file*
read/parse/soft-fail contract is genuinely one authority written four times.
The *value* policy is genuinely four different policies — two raise, one drops
and warns, one silently ignores a non-dict. Any "one generic loader" that
flattens the right-hand rows would be a semantic regression.

### 3.6 Deltas from the parent audit's figures — recorded honestly

| quantity | parent (at `85fa4b74`) | this design (at `eb9f667e`) | note |
|---|---|---|---|
| `run_workflow` params | 99 | **99** | unchanged |
| `run_workflow` lines / branches | 1,572 / 130 | **1,572 / 130** | unchanged |
| cross-iteration accumulators | "~15" | **11** | the parent's figure was approximate prose; 11 is the AST-measured count under the stated definition (§3.3). Two further *accumulated-only* inputs bring the "state-ish" total to 13. |
| duplicated digest loaders | 4 | **4** | confirmed |
| `run_workflow` production callers | 3 | **3** | confirmed |

No production commit landed between the two anchors; the parameter and loader
figures are therefore identical by construction, and the accumulator delta is a
measurement-precision correction, not a source change.

### 3.7 Caller census — the atomic migration surface, MEASURED

**Production — 3 call sites, 2 imports:**

| site | kwargs passed |
|---|---:|
| `sdsc_submission_scripts/run_one_iteration.py:1945` (import `:62`) | **89** |
| `sdsc_submission_scripts/run_exploration_test.py:151` (import `:29`) | 19 |
| `workflows/model_exploration.py:3122` (its own `main`) | 16 |

**Tests — 21 files call `run_workflow(`:**
9 unit — `tests/unit/agent/schemas/test_authority_transport_reachable.py`,
`tests/unit/core/test_step09a_c5_prediction_transport.py`,
`tests/unit/core/test_watchdog_admission_split.py`,
`tests/unit/guardrails/test_validation_posture_transport.py`,
`tests/unit/sdsc_submission_scripts/test_gate0_config_propagation.py`,
`…/test_launch_surface_parity.py`, `…/test_run_one_iteration.py`,
`tests/unit/workflows/test_data_scope_preflight.py`,
`tests/unit/workflows/test_model_exploration.py`;
12 integration under `tests/integration/workflows/`.

A further 12 files reference `run_workflow` without calling it, and the
`patch("workflows.model_exploration.<AgentClass>")` targets (5 agent classes,
used in at least 4 modules) are **unaffected** — they patch module attributes,
not the signature.

### 3.8 Startup side-effect order — load-bearing, MEASURED

`:1739` `makedirs(run_dir)` → `:1740` `_snapshot_task_config` → `:1750`
`os.environ.setdefault("SIDERIUS_CHAIN_WORKSPACE")` → `:1765`
`_cleanup_stale_registry_entries` → `:1780` `preload_global_losses` → `:1786`
`preload_global_models` → `:1819` `get_or_create_hardware_context` → `:1838-55`
seed load + `reconcile_metric_spec` → `:1868-76` scope resolve → **`:1884`
`build_run_invariants`** (materializes *and hashes* the effective health config)
→ `:1933` `run_launch_self_test` → **`:1944` `ensure_run_invariants`** (writes /
validates the lock) → `:1957` `_get_reasoning_pipeline` → `:1974-2069` state init
→ `:2106` loop.

Two orderings are contractual and must not move: **materialize-then-hash before
lock** (`:1884` before `:1944`), and **environment + plugin preload before any
agent construction**.

### 3.9 Commit / transaction boundary — OUTSIDE `run_workflow`

`run_workflow` writes **no manifest** (MEASURED: zero `write_manifest` calls in
`workflows/model_exploration.py`). `write_manifest` is defined at
`run_one_iteration.py:457` and called only there — at `:1819`, `:1843`, `:1863`
(early aborts) and `:2090`, `:2103`, `:2114`, i.e. **after** the
`run_workflow(...)` call at `:1945`. `committed_iters` is derived by
`_read_manifest` (`core/resume.py:241`) from `iter_NNN/manifest.json`.

**Therefore the durable commit boundary is owned by the launcher and is not
moved by this PR.** In-process multi-iteration runs write no manifests at all
(`:1985-1987`), so their carried state never crosses a commit boundary. This
removes the largest §20-class risk before it is incurred.

### 3.10 Hash / fingerprint inputs — low risk, MEASURED

`build_run_invariants` (`core/run_invariants.py:325`) takes **explicit scalar
arguments**, not a kwargs dict and not a `model_dump`. `health_config_sha256`
hashes the *materialized effective health-config document*, not any workflow
argument structure. `ensure_run_invariants` serializes `RunInvariants` itself
(`:217 json.dump(stamped.model_dump(), …)`).

**Consequence:** supplying the same values from a carrier field instead of a
parameter is hash-neutral **provided `RunInvariants`' own field set and the
values passed to `build_run_invariants` are unchanged.** That is a small,
checkable invariant (§19), not a broad risk.

---

## 4. Current `run_workflow` responsibility map

| owner | lines | what it does |
|---|---|---|
| **O1** run setup / banner / environment | `:1735-1808` | dirs, task-config snapshot, env, registry prune, plugin preload, 18 banner prints |
| **O2** run-scoped authorities & invariants | `:1817-1950` | hardware context, VRAM budget, seed load + `reconcile_metric_spec`, scope resolve + partial-scope policy, `build_run_invariants`, launch self-test, `ensure_run_invariants` |
| **O2b** reasoning pipeline / vocab seed | `:1953-1971` | `_get_reasoning_pipeline`, `_load_vocab_seed` |
| **O3** chain-state initialization | `:1974-2069` | the 11 accumulators (§3.3) seeded from 9 `restored_*` / `accumulated_*` params |
| **O4** per-iteration node lifecycle | `:2106-2918` | interpret → lit review → 279-line propose/implement/validate attempt loop → plugin register/promote → tune → state accumulation → memory probe / gc |
| **O5** plugin & loss registry lifecycle | module-level `:827-1362` | ~500 LOC — **OUT OF SCOPE** (Q2 = B) |
| **O6** summary / persistence | `:2921-2941` | banner + `_save_workflow_summary` |

**Step 09.5a owns O2 + O3 and the digest read path behind O3's seeds.** It does
not own O1, O4, O5 or O6 except where a carrier must be threaded through them.

---

## 5. Complete field-ownership classification of all 99 parameters

**Every parameter appears in exactly one class. The totals reconcile to 99.**
Classes follow the frozen parent §20.1a taxonomy: **A** immutable run-scoped
authority · **B** mutable cross-iteration state · **C** launch/execution
configuration · **D** services/resources · **E** local/derived (must not become
a carrier field) · **F** legacy/compatibility debt.

### 5.0 Class totals — machine-derived, reconciled exactly to 99

| class | count | proposed owner |
|---|---:|---|
| **A** immutable run-scoped authorities | **12** | `WorkflowRunBindings` (§10) |
| **B** mutable cross-iteration state seeds | **9** | `ChainState` (§11), via `RestoredState` |
| **C** launch / execution configuration | **71** | `WorkflowLaunchConfig` (§10.3) |
| **D** services / resources | **4** | `WorkflowRunBindings` services section (§10.2) |
| **E** local / derived only | **0 parameters** | derived locals stay locals (§5.6) |
| **F** legacy / deprecated no-ops | **3** | remain plain deprecated parameters (§5.7) |
| **total** | **12 + 9 + 71 + 4 + 0 + 3 = 99** | ✔ reconciles to the live signature |

Verified programmatically at `eb9f667e`: **no parameter is double-assigned and
none is unassigned.** §33-A turns this into a permanent executable check so it
cannot rot.

### 5.1 Why class C is a *separate* carrier and not part of the bindings

This is the design's central judgement, and it is what makes the result a
decomposition rather than a rename.

§3.2 measured that **63** parameters are consumed by a node protocol, **41**
of them by `local_validated_model` and nothing else.
They are:

* **not authorities** — the workflow never consults them to make a decision;
* **not state** — they never change;
* **not derived** — they arrive whole from the caller and leave whole.

Their lifecycle is *pure transit*. Placing them in `WorkflowRunBindings`
alongside the metric authority and the run invariants would reproduce exactly
the anti-pattern the parent forbids: one bag whose membership rule is "it was a
parameter". Placing them in a distinct frozen `WorkflowLaunchConfig` gives them
an honest membership rule — **"caller-supplied configuration this run forwards
to its nodes, never interprets"** — and leaves `WorkflowRunBindings` with a rule
strict enough to be enforceable: **"an authority or invariant this run
established at startup, whose identity does not change"**.

### 5.2 Class A — immutable run-scoped authorities → `WorkflowRunBindings` (12)

| parameter | current use | why an authority |
|---|---|---|
| `workspace` | `:1738`, `:1750`, `:1820`, `:1884`, `:1944`, … | run identity / root path; feeds the invariants lock |
| `run_name` | `:1738`, `:2140`, `:2596`, `:2932` | run identity; storage naming |
| `chain_run_name` | `:2087`, `:2092` | chain identity bound into every agent |
| `run_id` | `:2087`, `:2093` | chain identity bound into every agent |
| `data_scope` | `:1868` → resolved `:1869` | resolves to the run's file scope; locked |
| `health_gate_enabled` | `:1877`, `:1886`, `:1948` | locked run invariant |
| `health_gate_files` | `:1877`, `:1887`, `:1949` | locked run invariant |
| `health_checks_config` | `:1888` | locked run invariant (hashed) |
| `order_strategy_override` | `:1892` | locked run invariant |
| `file_order_override` | `:1893` | locked run invariant |
| `enable_structured_health_feedback` | `:1895` | locked run invariant (also read `:2174`, `:2366`, `:2735`) |
| `llm_config` | `:1715`, `:1958`, `:2194`, `:2657` | the run's LLM authority; normalized once at `:1715` |

**Derived authorities also held by the carrier** (constructed at startup, not
parameters): `resolved_data_scope` (`:1869`), `scope_is_partial` (`:1870`),
`run_invariants` (`:1884`), `hardware_context` (`:1819`),
`active_vram_budget_gb` (`:1826`), `seed_metric_spec` (`:1847`),
`reasoning_pipeline` (`:1957`), `vocab_seed` (`:1956`), `run_dir` (`:1738`).

*Note:* `health_feedback_history_window_iterations` and
`health_feedback_history_max_entries_per_model` are **also** locked invariants
(`:1896`, `:1898`) *and* forwarded to two protocols. They are classified **C**
(§5.4) and read by the invariants construction from the launch config —
duplicating them into A would create two sources of truth (§48 of the kickoff).

### 5.3 Class B — mutable chain-state seeds → `ChainState` (9)

| parameter | seeds | line |
|---|---|---|
| `restored_runtime_vocab` | `current_runtime_vocab` | `:2006` |
| `accumulated_key_findings` | key-findings carry | `:2316` |
| `restored_model_knowledge_cache` | `model_knowledge_cache` | `:2036` |
| `accumulated_physical_rejections` | physical-rejection carry | `:2261` |
| `accumulated_gate_exhaustions` | `recent_tune_outputs` synthetic wrappers | `:2061` |
| `restored_previous_proposal` | `previous_proposal_data` | `:1998` |
| `restored_chain_incumbent_score` | `chain_formal_incumbent_reference` | `:1988` |
| `restored_collapse_fingerprint_history` | `current_collapse_fingerprint_history` | `:2022` |
| `restored_prediction_memory` | `current_prediction_memory` | `:2027` |

These nine are exactly the workflow-side face of `RestoredState` (§16).

### 5.4 Class C — launch / execution configuration → `WorkflowLaunchConfig` (71)

Grouped by the sink each parameter is actually consumed by (machine-derived from
the load-site → innermost-enclosing-call map). **All 71 are frozen; the workflow
interprets only the seven noted.**

| # | sink | params |
|---:|---|---|
| **C.1** | **`local_validated_model` ONLY** (tuner protocol, `:2658-2740`) | **41** — `max_rounds` · `file_index` · `healthgate_mode` · `result_authority` · `eval_portion` · `train_validation_align` · `train_base_seed` · `cleanup_denoised` · `max_epochs` · `skip_formal_min_delta` · `bypass_formal_time_budget_min_delta` · `plan_overrides` · `gpu_admission_measurement_source` · `gpu_admission_enforcement` · `gpu_pair_ceiling_gib` · `trial_vram_budget_gb` · `formal_vram_budget_gb` · `formal_strategy` · `formal_portion` · `formal_train_portion` · `formal_eval_portion` · `force_formal_round` · `formal_round_strategy` · `degenerate_penalty_score` · `attempts_per_round` · `attempts_per_formal_round` · `max_fail_rounds` · `max_steps_per_attempt` · `min_formal_batch_size` · `allow_extreme_steps` · `runtime_watchdog_enabled` · `runtime_safety_factor` · `runtime_trial_safety_factor` · `runtime_formal_safety_factor` · `runtime_watchdog_safety_factor` · `runtime_watchdog_floor_seconds` · `validation_max_portion` · `validation_max_train_samples` · `validation_max_samples` · `validation_max_phase_seconds` · `enable_chain_incumbent_formal_gates` |
| **C.2** | workflow-local control flow only | **11** — `max_iterations` · `start_iteration` · `max_proposal_attempts` · `target_score` · `max_impl_attempts` · `debug_dump_prompts` · `lit_review_config_path` · `human_advice_implement` · `human_advice_validate` · `human_advice_tune` · `human_advice_mindset` |
| **C.3** | `local_full_context` **and** `local_validated_model` | **6** — `is_trial` · `trial_portion` · `train_portion` · `sampling_seed` · `trial_time_budget_minutes` · `formal_time_budget_minutes` |
| **C.4** | `_get_reasoning_pipeline` (`:1959-61`) | **3** — `exploration_mode` · `minimum_boldness` · `n_candidates` |
| **C.5** | seed-source loading | **4** — `source_paths` (`load_tuning_outputs_from_paths`) · `model_types`, `source_run_name` (`load_tuning_outputs`) · `data_dir` (all three sinks) |
| **C.6** | `build_run_invariants` + `InterpretationInput` + `local_validated_model` | **2** — `health_feedback_history_window_iterations` · `health_feedback_history_max_entries_per_model` |
| **C.7** | one node each | **2** — `human_advice_interpret` (`InterpretationInput`) · `human_advice_propose` (`local_full_context`) |
| **C.8** | `ProposalOutput.model_validate` (`:2398`) | **1** — `validation_fixed_candidate_plan` |
| **C.9** | `should_run_literature_review` (`:2217`) | **1** — `lit_review_enabled` |
| | | **total 71** |

**Seven class-C values the workflow also reads for itself** — they stay in C
because the workflow *consults* them, it does not *own* them:
`trial_vram_budget_gb` / `formal_vram_budget_gb` (`:1827`, active-budget
derivation), `formal_strategy` (`:1871-74`, partial-scope guard),
`max_iterations` / `start_iteration` (`:2106` loop bounds),
`health_feedback_history_window_iterations` /
`health_feedback_history_max_entries_per_model` (`:1896`, `:1898`, also locked
into the run invariants).

**C.6 deliberately does NOT also appear in class A.** Both values are locked
invariants *and* forwarded configuration; duplicating them into
`WorkflowRunBindings` would create two sources of truth for one value (§48 of
the kickoff). `build_run_invariants` reads them from the launch config.

### 5.5 Class D — services / resources (4)

`bridge_factory` (`:2195`, `:2232`, `:2408`, `:2490`, `:2748`) ·
`sandbox_factory` (`:2750`) · `require_probe_runner` (`:1934`) ·
`measurement_capability` (`:1935`)

Immutable for the run, injected by the caller, consumed as capabilities — the
tuner precedent carries services on the bindings object
(`contracts.py:93-98`) and that reading holds here.

### 5.6 Class E — derived locals that must NOT become carrier fields (0 parameters)

**No parameter falls in class E.** The class exists to name the values the
implementation must *resist* promoting, because they are computed per iteration
and have no cross-iteration lifetime:

`iter_dir` · `loop_pos` · `is_cold_start` · `interp_storage` ·
`tuning_storage` · `tuner_plugin_dir` / `chain_plugin_dir` · `tuner_loss_dir` /
`chain_loss_dir` · `run_metric_spec` (recomputed each iteration at `:2148`) ·
`_launch_report` · `external_channels` · `new_model_summaries`.

Recorded so the implementation does not "tidy" them into `ChainState` (R3).

### 5.7 Class F — legacy / deprecated no-ops (3)

| parameter | evidence | disposition |
|---|---|---|
| `trial_strategy` | `:1720` — DS7 deprecation loop only | **KEEP as a plain deprecated parameter** |
| `target_files` | `:1721` — same | **KEEP** |
| `eval_strategy` | `:1722` — same | **KEEP** |

`:1718-1732` is the DS7 no-op block: these three are **already deprecated and
ignored**, emitting `DeprecationWarning` and nothing else; removal is tracked as
**FU-2**.

**Decision (autonomous, evidence-based): do NOT remove them in Step 09.5a.**
Removal would turn a `DeprecationWarning` into a `TypeError` for any caller
still passing them — a caller-visible behavioural change inside a
behaviour-preserving PR. They stay as explicit deprecated parameters on the
entrypoint and enter **no carrier**, so the carriers stay clean and FU-2 keeps
its own owner. The new boundary makes their eventual removal a one-line change.

**`file_index` is NOT class F.** It is a legacy single-file relic but it is
*live* — forwarded to the tuner at `:2670` — so it sits in C.1 with its name
unchanged, per the no-opportunistic-renaming rule (§11 of the kickoff). Recorded
as inherited debt, not touched.

## 6. Current mutable chain-state inventory

See §3.3 for the 11 measured accumulators. Additional properties the design
must preserve:

* **`best_score_overall` is deliberately NOT restored** (`:1979-1983`): it is a
  *current-execution* RAW-formal tracker for the print banner and the workflow
  summary only, "never seeded from restored chain state and never fed to the
  tuner (V19 PR 1 two-state design)". `chain_formal_incumbent_reference` is the
  restored *decision* state. **Two similarly named values with deliberately
  different lifecycles — `ChainState` must keep both and must not unify them.**
* **`current_runtime_vocab` has a priority rule** (`:2006-2017`): restored vocab
  beats the static seed; without the check "every chain iter resets to the
  21-entry seed".
* **`current_collapse_fingerprint_history` and `current_prediction_memory` are
  one-directional**: the restored value seeds the loop variable and each
  iteration's interpreter output **REPLACES** it (`:2045-2054` comments). No
  merge happens in the workflow.
* **`model_knowledge_cache` is defensively copied** (`:2035-2037`) because the
  workflow mutates it in place at iteration end.
* **`recent_tune_outputs` is a `deque(maxlen=3)`** pre-populated with synthetic
  `HyperparamTuningOutput` wrappers carrying only prior gate exhaustions
  (`:2052-2069`).

---

## 7. Current resume / digest reader audit

§3.4 and §3.5 are the audit. Three further facts the design depends on:

1. **All four calls are in one restoration pass**, consecutive, with identical
   arguments (`:1478`, `:1496`, `:1504`, `:1511`). A single read pass is
   therefore mechanically achievable.
2. **The per-loader warning *messages* differ** — "for knowledge carry-over",
   "fingerprint-history", "prediction-memory carry-over" — and existing tests
   match those substrings (`tests/unit/core/test_resume.py:702`, `:717`,
   `:734`, `:933`, `:949`; `test_resume_fingerprint_history.py:67`;
   `test_step09a_c5_prediction_transport.py:154`, `:164`).
3. **No test pins a warning COUNT.** Every site uses
   `pytest.warns(UserWarning, match=…)`, which asserts *at least one* match.
   MEASURED across all resume test modules.

---

## 8. Exact A-1 / A-2 problem statement

**A-1.** `run_workflow` co-locates four owners that change for different
reasons — startup authorities (O2), cross-iteration state (O3), forwarded node
configuration (§3.2), and the iteration lifecycle (O4) — with **no typed
boundary between any of them**. Step 10 adds launcher-owned task binding
(→ O2), resume orchestration inputs (→ O3) and metric-handle comparisons
(→ the direction literals at `:2854-2870`, inside O4's loop). Every Step-10
change therefore lands in the two owners with the least separation.

**A-2.** One contract — *read the committed interpretation digests of
`committed_iters`, tolerate missing/corrupt files, project one carried value* —
is implemented four times (§3.4). Step 10 adds two more carried items
(`vocab_link_confirmations`, secondary transport), which under the current shape
means a fifth and sixth copy.

---

## 9. Proposed module and dependency architecture

### 9.1 Current graph (relevant edges only, MEASURED)

```
sdsc_submission_scripts/run_one_iteration.py ──imports──▶ workflows/model_exploration.run_workflow
                     │                                              │
                     └──imports──▶ core/resume.restore_prior_state   │
                                        │                            │
core/resume.py ──▶ agent/schemas/{health_feedback,hyperparam_tuning,interpretation,proposal}
core/resume.py ──▶ core/{run_invariants,sandbox_executor,scientific_authority}
core/resume.py ──▶ execute_tools/{dataset_config,health_checks/*}
core/resume.py ──▶ workflows/model_exploration._add_plugin_to_registries   ◀── OUT OF SCOPE (Q2=B)
                                                     │
workflows/model_exploration.py ──▶ core/*, agent/*, execute_tools/*, nodes/*
```

### 9.2 Proposed graph

```
run_one_iteration.py / run_exploration_test.py / model_exploration.main
        │  construct
        ├────────────────▶ WorkflowLaunchConfig      (workflows/run_config.py, frozen)
        │                            │
core/resume.restore_prior_state ─▶ RestoredState ─▶ ChainState  (core/chain_state.py, mutable)
        │                                                │
        │        core/committed_digests.py               │
        │        (ONE read/parse/soft-fail authority)    │
        │                    ▲                           │
        │                    └── resume projections ─────┘
        │
        └────────────────▶ run_workflow(bindings-inputs, launch_config, chain_state, services)
                                     │ constructs at startup
                                     ▼
                             WorkflowRunBindings   (workflows/run_bindings.py, frozen)
```

**No new edge is added into `core` from `workflows`.** `ChainState` and the
digest authority live in `core/` precisely so that `core/resume.py` can consume
them without importing `workflows` — the inversion this PR must not deepen.
`WorkflowLaunchConfig` and `WorkflowRunBindings` live in `workflows/` because
their only consumers are the workflow and its callers, and
`sdsc_submission_scripts → workflows` already exists (`run_one_iteration.py:62`).

### 9.3 Placement rationale, per candidate

| candidate home | verdict |
|---|---|
| `core/chain_state.py` for `ChainState` | **CHOSEN** — it is the in-process continuation of `RestoredState` (`core/resume.py:106`); `core` already imports `agent.schemas` and `execute_tools`, so its type dependencies are legal; and it avoids `core → workflows`. |
| `core/committed_digests.py` for the read authority | **CHOSEN** — its only consumer is `core/resume.py`; keeping it in `core` keeps resume's public API and adds no cross-package edge. Placing it inside `resume.py` itself is the alternative; a sibling module is preferred so the authority is nameable and censusable (§33-A). |
| `workflows/run_bindings.py`, `workflows/run_config.py` | **CHOSEN** — consumers are the workflow and its three callers; follows the tuner precedent of a carrier living with its owner. |
| `agent/schemas/` for any carrier | **REJECTED** — it is an LLM-schema package, not a runtime-state owner, and a declared CI hub (parent §18.4): every touch would force the full suite. |
| a single `workflows/context.py` holding everything | **REJECTED** — §50 anti-pattern. |
| `core/` for the bindings carrier | **REJECTED** — no `core` module needs it; placing it there would invent a dependency. |

---

## 10. Immutable run-binding contract

### 10.1 `WorkflowRunBindings` — frozen dataclass, `workflows/run_bindings.py`

**Membership rule (the only one):** *an authority or invariant established
during run startup, whose identity does not change for the rest of the run.*
A value that varies per iteration does not belong here even if passing it would
be convenient.

Proposed fields — the 12 class-A parameters (§5.2) plus the nine startup-derived
authorities. Exact field list is frozen by the C2 implementation after the C0
census, not here (§20.1 of the parent: the carrier field set is deliberately
**not** pre-frozen).

**Type choice: `@dataclass(frozen=True, slots=True)`.** Justified in §21.

### 10.2 Services

`bridge_factory`, `sandbox_factory`, `require_probe_runner`,
`measurement_capability` are carried on the bindings (class D), matching the
tuner's "input and services" section (`contracts.py:93-98`). They are immutable
for the run and are capabilities, not configuration.

### 10.3 `WorkflowLaunchConfig` — frozen dataclass, `workflows/run_config.py`

**Membership rule:** *caller-supplied configuration this run forwards to its
nodes and never interprets as an authority.* 71 fields (§5.4), preserving every
current name, type and default **exactly** — this carrier is the honest home for
the pass-through surface, and its size is a measurement of the real problem, not
a design failure.

It is **not** a bag: it has one membership rule, one construction site per
caller, and a censusable boundary. Its fields are grouped by destination
protocol in source, mirroring §5.4.

---

## 11. Mutable chain-state contract

### 11.1 `ChainState` — mutable dataclass, `core/chain_state.py`

Holds the 11 accumulators of §3.3. Construction:

* `ChainState.cold_start(vocab_seed=…)` — the first-iteration / in-process path;
* `ChainState.from_restored(restored: RestoredState, *, vocab_seed, …)` — the
  chain path, implementing the priority rules of §6 verbatim (restored vocab
  beats seed; defensive copy of the cache; synthetic wrappers for
  `recent_tune_outputs`).

**One authority for cold-start defaults**: `cold_start` is the single site, and
`from_restored` delegates to it for every field the restored state does not
supply. There is no second default expression anywhere.

### 11.2 Mutation authority

`run_workflow`'s iteration loop remains the only mutator. Mutation is **direct
typed field assignment**, not `state.set_x(...)` accessors — adding methods
without semantic value is explicitly rejected (§19 of the kickoff). Two
exceptions earn a method because they encode a rule rather than an assignment:
the vocab priority rule and the `recent_tune_outputs` bounded append.

### 11.3 What must NOT unify

`best_score_overall` (current-execution, never restored) and
`chain_formal_incumbent_reference` (restored decision state) stay **two
fields**, with the `:1979-1990` comments carried onto them. This is the single
most likely accidental-semantic-merge in the whole PR.

---

## 12. Executable ownership guard

**Design (stronger and less brittle than a hand-authored name list):**

```text
FORBIDDEN on WorkflowRunBindings  =  every field name declared by ChainState
                                     ∪  a small explicit set for names that
                                        are mutable-by-nature but not yet
                                        ChainState fields
```

The forbidden set is **derived** from `ChainState.__dataclass_fields__` at
import time, so it cannot go stale when `ChainState` grows — the failure mode
of a hand-maintained list. Enforcement in `WorkflowRunBindings.__post_init__`,
mirroring `contracts.py:173-178`, plus two structural assertions:

1. no `WorkflowRunBindings` field is annotated `ChainState` (or contains one);
2. `set(WorkflowRunBindings fields) ∩ set(ChainState fields) == ∅`.

**Anti-vacuity is proven in implementation** by a planted offender: a test that
constructs a subclass/variant carrying a `ChainState` field name and asserts
`TypeError`. Without that, the guard is decoration.

---

## 13. `run_workflow` signature and caller migration

**Frozen by the parent (amendment B): the Python call signature changes; the
entrypoint identity `run_workflow` is preserved; NO compatibility wrapper.**

Target shape:

```python
def run_workflow(
    *,
    launch: WorkflowLaunchConfig,
    chain_state: ChainState,
    services: WorkflowServices,        # or carried on bindings — C2 decides
    # class-A inputs the workflow needs to BUILD its bindings:
    workspace: str, run_name: str, chain_run_name: str | None, run_id: str | None,
    data_scope: DataScope | None, health_gate_enabled: bool,
    health_gate_files: list[int] | None, health_checks_config: str | None,
    order_strategy_override: OrderStrategy | None,
    file_order_override: list[int] | None,
    enable_structured_health_feedback: bool,
    llm_config: WorkflowLLMConfig | None,
    # class-F deprecated no-ops, preserved verbatim:
    trial_strategy=..., target_files=..., eval_strategy=...,
) -> list[HyperparamTuningOutput]:
```

`WorkflowRunBindings` is **constructed inside `run_workflow`** from the class-A
inputs, because the derived authorities (invariants, hardware context, resolved
scope) can only be built after the startup side-effects of §3.8. Moving
construction to the launcher is Step 10/12 work (§22). The class-A inputs stay
explicit rather than becoming a third carrier: a "bindings input" bag would be a
bag.

**Atomic migration surface (§3.7): 3 production call sites + 21 test files.**
All migrate in C3. `patch("workflows.model_exploration.<AgentClass>")` targets
are unaffected.

---

## 14. Committed-digest I/O authority

### 14.1 Shape

```python
# core/committed_digests.py
@dataclass(frozen=True)
class DigestRead:
    iter_idx: int
    status: Literal["ok", "missing", "unreadable"]
    payload: dict | None          # parsed JSON when status == "ok"
    detail: str | None            # the OSError/JSONDecodeError text

def read_committed_digests(workspace, current_iter, committed_iters) -> list[DigestRead]
```

**One open, one `json.load`, one `try/except` per committed iteration per
restoration pass** — the strong shape the parent §15 asks for, and §3.4 proves
it is reachable because all four calls already share one pass with identical
arguments.

### 14.2 Projections stay separate and keep their own failure policy

Each of the four carried values becomes a **pure projector** over
`list[DigestRead]`, preserving §3.5 exactly: `knowledge` drops-and-warns a
malformed vocab entry; `fingerprint_history` and `prediction_memory` **raise**;
`knowledge_cache` silently ignores a non-dict. **No generic merge helper is
introduced** — three latest-wins rules and one union rule that differ in their
failure policy are not one rule.

### 14.3 Diagnostics — §16 disposition, DECIDED

The projections, not the reader, emit the `warnings.warn` calls. Each projector
maps a non-`ok` `DigestRead` to **its own current message text**.

**Consequence: message text is preserved verbatim, warning multiplicity is
preserved exactly (4 warnings for one corrupt digest), and no existing test
changes** — while the file is still read and parsed once.

This is the disposition the parent §16 asked to be frozen, and it needs **no
operator question**: the evidence (§7.2/§7.3 — messages pinned, counts not) is
unambiguous, and preserving both is strictly cheaper than choosing between them.

### 14.4 `load_latest_proposal` is untouched

Different path family, reverse iteration, first-parseable-wins (§3.4). It keeps
its own read. Folding it in would be a semantic regression, and a test in C1
pins that it is *not* routed through the new authority.

---

## 15. Carried-state projection contracts

| carried state | current loader | digest key(s) | validator | merge rule | malformed-value policy | missing key |
|---|---|---|---|---|---|---|
| `runtime_vocab` | `load_latest_knowledge` | `runtime_vocab` | `VocabEntry.model_validate` | **latest-wins** (only if non-empty) | **warn + drop that entry** `:860` | keep running value |
| `accumulated_key_findings` | same loader | `key_findings` | `isinstance(str)` + non-empty | **union, first-occurrence, dedup** | skipped silently | skip |
| `model_knowledge_cache` | `load_latest_knowledge_cache` | `model_knowledge_cache` | `isinstance(raw, dict)` | latest-wins (empty dict IS a valid snapshot) | non-dict → ignore, keep running | keep running value |
| `collapse_fingerprint_history` | `load_latest_fingerprint_history` | `collapse_fingerprint_history` | `CollapseFingerprintHistoryEntry.model_validate` | latest-wins (skip if falsy) | **`raise ValueError`** `:939` | skip |
| `prediction_memory` | `load_latest_prediction_memory` | 4 keys: `prediction_outcomes_history`, `prediction_outcomes_by_semantics`, `cumulative_information_gain`, `cumulative_information_gain_by_semantics` | `PredictionMemory.model_validate` | latest-wins (skip if all falsy) | **`raise ValueError`** `:1018` | default 0.0 / `{}` |
| `previous_proposal_data` | `load_latest_proposal` | whole proposal file | JSON only | **first parseable in REVERSE order**, early return | warn + continue | — |

Each row maps one-to-one onto a projector in C1. Parity for every row is pinned
by the C1 tests (§23).

---

## 16. Cold-start / restoration / persistence lifecycle

**`RestoredState` remains the transport value; `ChainState` is the in-process
carrier constructed from it.** Rationale: `RestoredState` is produced by
`restore_prior_state` and consumed by the *launcher*, which forwards a subset as
`restored_*` kwargs; making `ChainState` itself the restored value would push a
workflow-lifecycle type into the launcher's resume API and widen this PR into
Step-10 territory. Two value types, two lifecycles, stated explicitly:

| type | lifecycle |
|---|---|
| `RestoredState` (`core/resume.py:106`) | produced once by `restore_prior_state` from disk; read-only; crosses the launcher boundary |
| `ChainState` (new) | constructed from `RestoredState` **or** cold; mutated across iterations inside one `run_workflow` call; never crosses a subprocess boundary |

**No resume-only state may reach `WorkflowRunBindings`** — enforced by §12.
**No field of `RestoredState` gains or loses meaning** in this PR.

---

## 17. Warning / soft-fail semantics

Frozen in §14.3: **option A of the parent's §16 — exact diagnostic multiplicity
and message text are preserved deliberately**, achieved without paying for four
reads. The resume soft-fail policy (warn-and-skip at file level; per-projection
policy at value level) is unchanged in every one of its eight current sites.

---

## 18. Transaction / commit ordering

**Unchanged, and structurally out of reach of this PR** (§3.9): `run_workflow`
writes no manifest; the launcher's `write_manifest` after `run_workflow` returns
is the durable commit; `committed_iters` derives from those manifests.

The startup side-effect order of §3.8 **is** in reach and is frozen: the C3
migration must not move `_snapshot_task_config`, the `SIDERIUS_CHAIN_WORKSPACE`
env set, the plugin preloads, or — most importantly —
`build_run_invariants` (materialize + hash) **before** `ensure_run_invariants`
(lock). The C0 oracle records this order and C3 re-asserts it.

---

## 19. Serialization / hash invariants

Per §3.10 the risk is narrow and checkable. Frozen invariants:

1. `RunInvariants`' field set and field order are **unchanged**;
2. the values passed to `build_run_invariants` are **unchanged** (same 10
   arguments, same types);
3. `health_config_sha256` is computed from the same materialized document;
4. `run_invariants_lock.json` bytes for an identical run are **identical**
   pre/post;
5. **no carrier object is ever serialized into a hash, artifact or lock** —
   `WorkflowLaunchConfig` / `WorkflowRunBindings` / `ChainState` have no
   persistence contract in this PR.

Invariant 5 is what makes the `dataclass`-vs-Pydantic choice hash-neutral.

---

## 20. LLM-facing parity contract

The Gate-1 waiver (§25) rests on this being executable, not rhetorical.

**Compared PRE vs POST over one bounded pseudo-mode run:**

| dimension | source |
|---|---|
| call labels | `LLMBridge` call-label capture (the `test_all_calls_labeled` infrastructure) |
| call order and count | ordered list of (label, node) |
| system prompt bytes | exact `str` equality |
| user prompt bytes | exact `str` equality |
| structured payloads / schema inputs | deep-equal on the kwargs reaching the bridge |
| task blocks / metric identity / Health evidence / memory evidence reaching prompts | included by construction, since they are prompt bytes |

**Not** "number of calls" alone. Any intentional LLM-facing delta ⇒ Gate 1
becomes REQUIRED and, in a behaviour-preserving PR, is itself a scope-creep
signal.

---

## 21. Type / mutability choice

| carrier | choice | why |
|---|---|---|
| `WorkflowRunBindings` | `@dataclass(frozen=True, slots=True)` | immutability must be *structural*; matches the tuner precedent (`contracts.py`); no runtime validation needed because every field is already validated by its own authority; never serialized (§19.5) |
| `WorkflowLaunchConfig` | `@dataclass(frozen=True, slots=True)` | pure transit; a Pydantic model would add validation that the receiving schemas (`HyperparamTuningInput` etc.) already perform, duplicating the authority |
| `ChainState` | plain mutable `@dataclass` | mutation across iterations is the point; `frozen=True` would force a rebuild per mutation and obscure ownership |
| `DigestRead` | `@dataclass(frozen=True)` | a small immutable read result |

**Pydantic is deliberately NOT chosen** for the carriers. The repository's rule
is that *LLM output* must pass a Pydantic schema before execution; these
carriers hold already-validated internal values and are never parsed from
untrusted input. Choosing Pydantic here would also risk §19 by giving carriers a
serialization shape they must not have.

---

## 22. Step-12 / extensibility compatibility

* **Zero task-name branches, zero central task tables, zero per-task registry
  growth, zero new TIDMAD-only authority.** Pinned by a census (§33-F).
* The carriers **hold values produced by existing authorities** — `DataScope`,
  `RunInvariants`, `MetricSpec`, `TaskDataPath` binding, Health config — and
  never re-implement their discovery. No `WorkflowMetricRegistry`,
  `WorkflowHealthRegistry` or equivalent is created (§46 of the kickoff).
* **Forward test (§29 of the kickoff).** A fourth out-of-tree task bound by the
  future Step-12 composition root would need: a task package, a data-path
  implementation, and model/objective/metric/Health/interpretation semantics.
  It would need **no** task-name field, **no** central table edit, **no** new
  carrier class, and **no** change to the committed-digest reader — because the
  carriers hold *values*, and the digest reader is keyed on iteration indices
  and digest keys, neither of which is task-shaped. **Answer: NO source edit to
  the workflow-state architecture.**
  *This is not a claim that Step 09.5a enables out-of-tree execution — that
  graduation remains Step 12.* What it claims is that Step 09.5a does not add a
  new obstacle.
* `WorkflowRunBindings` gives Step 10 a typed place for launcher-supplied task
  binding to land, and Step 12 a place for externally composed values — without
  Step 09.5a implementing either.

---

## 23. Implementation commit sequence

Seven semantic commits. Each owns a distinct failure class.

| commit | scope | distinct failure class it owns |
|---|---|---|
| **C0** | **PRE-refactor differential oracle + the executable parameter census.** Tests/evidence only. **Must land before any production edit.** | "the baseline was reconstructed after the fact" — the one failure no later commit can detect |
| **C1** | `core/committed_digests.py` + migrate the four projections in `core/resume.py`. `load_latest_proposal` untouched. | "the four read/parse/soft-fail copies became one *code* path but not one *I/O* path", and "a projection's merge or malformed-value policy drifted" |
| **C2** | `WorkflowRunBindings`, `WorkflowLaunchConfig`, `ChainState`, `WorkflowServices` + the derived ownership guard. Types and tests only; not yet wired. | "mutable state can live in the immutable carrier" |
| **C3** | `run_workflow` signature migration + **all 3 production callers and 21 test files, atomically**. Bindings constructed at startup; launch config threaded. | "a caller or patch target was missed", "a compatibility wrapper survived", "startup side-effect order moved" |
| **C4** | The 11 accumulators become `ChainState` fields inside the loop; `from_restored` / `cold_start` adopted. | "an accumulator's seeding priority, defensive copy or one-directional replace semantics changed" |
| **C5** | Structural censuses (§33), `pyright`, docs sync (`model_exploration.md` if present, `run_one_iteration.md`), **LLM-facing parity proof + Gate-1 disposition**. | "a duplicate authority survived behind a wrapper"; "prompts moved" |
| **C6** | Gate 2 (≥ 2 iterations), PR, exact-head CI. | "the real cross-iteration lifecycle broke in a way no unit test models" |

**C3 and C4 are deliberately separate**: caller migration and in-loop state
adoption are different failure classes, and merging them would make a bisect
useless on the largest diff in the PR.

**Not split into 09.5b.** C1 (producer of restored values) and C4 (consumer)
touch the same state authority; separating them into two PRs would put the
producer and consumer of one carrier in different review units — the exact
error the parent §20 warns against.

---

## 24. Differential pre-refactor oracle (C0)

Captured at the C0 head, **before any production edit**.

**Scope:**

| surface | comparison |
|---|---|
| workflow call envelope | the resolved kwargs actually passed to each node protocol (`local_full_context`, `local_validated_model`, `InterpretationInput`), deep-equal |
| run-level authority resolution | `RunInvariants` fields; `health_config_sha256`; resolved scope; active VRAM budget |
| initial chain state | all 11 accumulators after initialization, deep-equal |
| one representative iteration | node call order; the per-iteration values above after the iteration |
| persisted artifacts | every file under the run dir: path set + content (deep-equal JSON where JSON, byte-equal otherwise) |
| final state | the 11 accumulators + `_save_workflow_summary` payload |
| LLM-facing envelope | §20's six dimensions |
| resume projection | the four carried values for a fixture workspace |
| **startup side-effect order** | the ordered trace of §3.8 |

**Mode:** pseudo-mode, mocked agents (the existing
`patch("workflows.model_exploration.<AgentClass>")` topology), deterministic
seeds. **No real LLM, no training.**

**Disposition:** the *iteration/artifact* oracle is a **one-time refactor
oracle** recorded in the ledger, not kept permanently — its failure class is
"this refactor moved something", which expires. The **resume projection** and
**parameter census** parts become **permanent** owners (§33-A, §23-C1), because
their failure class ("a projection drifted", "a parameter lost its owner")
persists.

**Also in C0: the executable parameter census** whose row count must equal
`len(inspect.signature(run_workflow).parameters)` — this is what keeps §5.0
exact rather than hand-counted.

---

## 25. Gate-1 disposition

> **PLANNED: Gate 1 NOT REQUIRED.**

**Justification.** Step 09.5a introduces **zero** LLM-facing semantic delta: it
moves configuration and state between carriers, changes no prompt template, no
renderer, no evidence projection, no node input *value*. The parity oracle of
§20 compares prompt bytes, call labels, call order/count and structured payloads
exactly, over the same bounded pseudo-mode run, PRE vs POST.

**Waiver condition (binding):** if the C5 parity proof shows **any** difference
in any of the six dimensions, **Gate 1 becomes REQUIRED** and the difference is
first investigated as scope creep.

This follows the 08a/08b precedent, where Gate 1 was dispositioned NOT REQUIRED
on proven byte-identical LLM-facing rendering.

---

## 26. Gate 2 — exact design

> **REQUIRED. Exactly one launch, at the final executable head.**

| field | value |
|---|---|
| **claim** | After the structural migration, a bounded real two-iteration chain commits iteration 1, **restores and consumes that state in iteration 2**, and completes with persisted artifacts and invariants equivalent to the pre-refactor lifecycle contract. |
| **NOT the claim** | any score, model quality or benchmark improvement (§25 of the kickoff) |
| **temporal depth** | **2 iterations** (`docs/gates/gate_testing_standard.md:262-267` — "cross-iteration behaviour or resume → ≥ 2 iterations") |
| **base plan** | the standard's **Regular Plan** (`:397-415`), which is already the 2-iteration bounded configuration — no new benchmark is invented |
| **entry** | **`sdsc_submission_scripts/run_chain.sh --num_iterations 2`** — MEASURED: `_chain_common.sh:787` runs `for ITER in $(seq "$first" "$NUM_ITERATIONS")`, launching `run_one_iteration.py` **once per iteration** with `--start_iteration "$iter"` (`:431`). This is the only path that exercises `restore_prior_state` → `RestoredState` → `ChainState`. |
| **⚠ the trap this avoids** | an **in-process** `run_workflow(max_iterations=2)` also "runs two iterations" and would look like a passing Gate — but §3.9 shows in-process mode writes **no manifests**, so `committed_iters` is empty and `restore_prior_state` never runs. **A 2-iteration in-process run proves nothing about restoration** and is an invalid Gate-2 configuration for this PR. |
| **LLM** | real, `--llm_config openai_tiered_pro.json` (mandatory, `:238`) |
| **scope / Health** | `--data_scope 4-9` with `--health_gate_files 4,5,6,7,8,9` (DS8-mandatory pairing) |
| **seeds** | **NONE — cold-start** (operator rule 2026-07-27) |
| **bounds** | `--max_rounds 2`, `--max_epochs 1`, portions per the Regular Plan, `--trial_time_budget_minutes 5`, `--formal_time_budget_minutes 45`, VRAM 24/24 |
| **expected runtime** | ~45–90 min for the two iterations (the standard's own Regular-Plan estimate). If the C6 pre-flight projects materially beyond that, fall back to the Lite Plan ×2 and record why. |
| **resources** | 1 GPU; real training + inference + scoring subprocesses; ~2 real LLM call groups per iteration |

**PASS criteria — must prove consumption, not merely completion (§41):**

1. both iterations complete; iteration 1's `manifest.json` has
   `status == "completed"`;
2. iteration 2's resume log shows `committed_iters == [1]`;
3. **two structurally different projection rules are both exercised and
   consumed**:
   * **latest-wins** — iteration 2's `prediction_memory` (or
     `collapse_fingerprint_history`) equals iteration 1's committed digest value,
     and is non-empty;
   * **union / accumulative** — iteration 2's `accumulated_key_findings`
     contains iteration 1's findings;
4. the digest file for iteration 1 is opened **once** per restoration pass
   (asserted from the C1 instrumentation, not by eyeball);
5. `run_invariants_lock.json` is written once and validates on iteration 2;
6. no `DeprecationWarning`/`UserWarning` regression beyond the pre-refactor set.

**FAIL:** any of 1–5 false.
**INCONCLUSIVE:** infrastructure abort (GPU unavailable, quota, watchdog kill)
before iteration 2 begins — re-run once, per the standard, without changing the
tested SHA.

**No Gate is run during Phase 1.**

---

## 27. Test / evidence economy

| stage | validation |
|---|---|
| C0 | the oracle itself + the parameter census |
| C1 | targeted `core/resume.py` + digest-authority tests; the six projection rows of §15; `load_latest_proposal` isolation |
| C2 | carrier schema + ownership-guard tests **incl. a planted offender** |
| C3 | targeted workflow + caller + launcher tests; startup-order assertion |
| C4 | targeted chain-state tests: cold start, restored priority, one-directional replace, defensive copy, deque bound |
| C5 | ONE consolidated deterministic closure: censuses + parity proof + `pyright` + `ruff` |
| C6 | ONE Gate 2; then the formal PR's **single** exact-final-head CI |

**Explicitly NOT planned:** a local full suite at any commit; Gate 2 twice;
Gate 1 "for reassurance"; a manual `workflow_dispatch` CI; broad integration
repeats after C5. Repository-wide regression is owned by the one formal
exact-head PR CI (parent §22.3, CLAUDE.md validation economy).

---

## 28. Changed-file scope

Every file, with its justifying owner. **A file not tied to A-1, A-2 or atomic
caller migration is out of scope.**

| file | owner | structural / semantic |
|---|---|---|
| `core/committed_digests.py` *(new)* | A-2 | structural |
| `core/chain_state.py` *(new)* | A-1 (O3) | structural |
| `workflows/run_bindings.py` *(new)* | A-1 (O2) | structural |
| `workflows/run_config.py` *(new)* | A-1 (§5.1) | structural |
| `core/resume.py` | A-2 — four projections migrate; `RestoredState` untouched | structural |
| `workflows/model_exploration.py` | A-1 — signature, startup bindings, state block, loop mutation sites | structural |
| `sdsc_submission_scripts/run_one_iteration.py` | atomic caller migration (89 kwargs) | structural |
| `sdsc_submission_scripts/run_exploration_test.py` | atomic caller migration (19 kwargs) | structural |
| 21 test files (§3.7) | atomic caller migration | structural |
| new tests: digest authority, projections, carriers, guard, census, oracle | validation | — |
| docs: `docs/design/…/step_09_5a_….md` (this file), `sdsc_submission_scripts` / workflow operator docs if they quote the signature | doc-sync rule | — |

**Explicitly NOT touched:** `.github/workflows/ci.yml`, `pyproject.toml`
markers, `nodes/**`, `agent/prompt_templates/**`, `execute_tools/health_checks/**`,
`dashboard/**`, and every `_register_plugin` / promotion / registry symbol.

---

## 29. Risks

| # | risk | prevention | detection | stop condition |
|---|---|---|---|---|
| R1 | parameter bag masquerading as decomposition | §5's six-class taxonomy + §5.1's separate `WorkflowLaunchConfig` | C0 census: every parameter has exactly one owner; review of the membership rules | if a carrier cannot state a one-sentence membership rule, STOP |
| R2 | mutable state inside immutable bindings | §12 derived guard | planted-offender test | guard cannot be made to bite ⇒ STOP |
| R3 | `ChainState` becomes a god object | membership = the 11 measured accumulators only; §5.6 lists the locals that must stay local | field-count review vs §3.3 | a field with no cross-iteration lifetime ⇒ reject |
| R4 | "one reader" still reads the file 4× | §14.1 returns `list[DigestRead]` for the whole pass | C1 test asserting **one** `open`/`json.load` per committed iteration per pass; Gate-2 criterion 4 | more than one read ⇒ redesign, do not ship |
| R5 | warning multiplicity changes | §14.3 keeps emission in the projections | existing `pytest.warns` tests unchanged + an explicit multiplicity test added in C1 | any existing warn test needing edits ⇒ re-examine |
| R6 | corrupt/missing digest semantics drift | §15's six-row table is the spec | one test per row per failure mode | any row without a test ⇒ C1 incomplete |
| R7 | persistence transaction boundary shifts | §3.9 — the boundary is in the launcher, untouched | C0 artifact comparison | a manifest write appears in `run_workflow` ⇒ STOP |
| R8 | hidden caller / patch target missed | §3.7 census, re-run in C3 | `pyright` + full-tree grep census in C5; CI | any unmigrated caller at C5 ⇒ fix before Gate 2 |
| R9 | hash/fingerprint change from serialization shape | §19 invariants 1–5; carriers never serialized | C0 compares `run_invariants_lock.json` bytes | any hash delta ⇒ **STOP** (frozen contract) |
| R10 | LLM call/prompt movement | §20 six-dimension oracle | C5 parity proof | any delta ⇒ Gate 1 REQUIRED **and** scope review |
| R11 | temporary compatibility wrapper survives | C3 migrates atomically; §33-C census | census test: no function re-exposing the old parameter list | wrapper present at C5 ⇒ blocker |
| R12 | task-specific fields frozen into generic infra | §22 + §33-F census | census + review of every carrier field name | a task name in a carrier ⇒ reject the field |
| R13 | Step-10 semantics leak into a carrier | §1 non-goals; "no field without a current production value" | field review vs §5 | a field with no current producer ⇒ remove |
| R14 | private registry debt pulled in | §1, §9.3; `core/resume.py:61` untouched | diff review; census that the import is unchanged | if no legal placement exists without touching registry ownership ⇒ **STOP and report** (§13 of the kickoff) |
| R15 | Gate 2 passes without exercising restoration | §26: the entry is `run_chain.sh --num_iterations 2` (one process per iteration, MEASURED `_chain_common.sh:787`), **never** an in-process 2-iteration run, which writes no manifests and never calls `restore_prior_state`; PASS criteria 2–4 name consumed values across two projection rules | criterion 2 asserts `committed_iters == [1]` — empty ⇒ the Gate did not test resume | criterion 2 or 3 unprovable ⇒ redesign the Gate **before** spending the run |
| R16 | oracle captured after the refactor | C0 lands first, enforced by commit order | commit graph review | any production edit before C0 ⇒ revert |
| R17 | duplicated authorities survive behind wrappers | §33-B census | planted offender | old loader skeleton present ⇒ blocker |
| R18 | over-testing with duplicate expensive evidence | §27 economy table | per-commit validation review | a second Gate or a full local suite proposed ⇒ reject |

---

## 30. A/B/C debt disposition

**Solved by Step 09.5a:** parent **A-1** and **A-2**. Nothing else.

**NOT solved — carried forward unchanged**, with owners:
proposer legacy/pipeline reader duplication (B-1 → Step 10) · proposer
direction-blindness (B-2 → Step 10) · `evaluation.py` per-check-NAME tables
(B-3 → Step 10) · launcher width (B-4) · interpreter `run()` structure
(B-5) · secondary-metric cache-carry asymmetry (B-6 → Step 10) ·
`interpretation_helpers.py` grab-bag (C-1) · duplicated 5 % band (C-2) ·
`rendering.py`'s non-rendering owners (C-3) · dead `_MAX_REASONING_RETRIES`
(C-4) · dead proposer reads (C-5) · stale `ci_selection` docstrings (C-6) ·
dashboard direction literal (C-7) · **`core/resume.py:61` private registry
import (→ Step 12)** · the CI validation-topology follow-up (parent §20.2) ·
FU-2 (DS7 no-op parameter removal).

**Step 09.5a does not make repository structural debt "fixed". It removes the
Step-10 blocker.**

---

## 31. Acceptance criteria — structural

1. one immutable run-binding authority exists, with a stated membership rule;
2. one mutable chain-state authority exists;
3. **every** parameter of the pre-refactor signature is explicitly owned by the
   C0 census, row count reconciled to the live signature;
4. no parameter-bag anti-pattern — each carrier's membership rule is a sentence,
   and §5.1's authority/transit split holds;
5. all 3 production callers + 21 test files migrated;
6. **no** compatibility wrapper re-exposing the old parameter list;
7. one committed-digest I/O + soft-fail authority; **one read and one parse per
   committed digest per restoration pass**;
8. the four old loader implementations are **removed**, not wrapped;
9. all six projection rows of §15 preserved exactly, incl. failure policy;
10. cold-start, latest-wins, union and every failure case preserved;
11. external CLI / artifact / hash contracts preserved (§19);
12. exact LLM-facing parity proven (§20);
13. Gate 1 waived only on that proof (§25);
14. Gate 2 ≥ 2 iterations PASS with consumption proven (§26);
15. no Step-10/12 semantic debt implemented;
16. Step-12 composition path remains open (§22).

---

## 32. Before / after change-amplification proof

**Adding one carried state item of an existing kind.**

| | today | after 09.5a |
|---|---|---|
| digest reader | **+1 copy of a ~75-line read/parse/soft-fail loader** | **0** — one projector over `list[DigestRead]` |
| `RestoredState` | +1 field | +1 field |
| launcher | +1 CLI arg, +1 kwarg | +1 CLI arg, +1 `WorkflowLaunchConfig` field |
| `run_workflow` | **+1 parameter (#100)** | **0 signature change** |
| state block | +1 local, +1 loop mutation | +1 `ChainState` field |
| **duplicated authorities touched** | **1 new copy of the read contract** | **0** |

**Threading a run-scoped authority.**

| | today | after 09.5a |
|---|---|---|
| sites re-threading it | 3 call sites + an 85-argument parser + the signature | 1 carrier field; callers already construct the carrier |

**Success is measured as reduced semantic edit sites for the same future
change** — not as a smaller function or fewer parameters (§33 records size only
as engineering evidence).

---

## 33. Structural censuses (executable, with anti-vacuity)

| id | census | anti-vacuity |
|---|---|---|
| **A** | every `run_workflow` parameter (pre-refactor list, recorded in C0) has exactly one owner row; row count == live signature length | asserts a non-zero, exact count; fails if a parameter is added without an owner |
| **B** | exactly **one** committed-digest I/O authority; no module besides it opens `_interpretation_path` | planted offender: a second `open(_interpretation_path(...))` ⇒ RED |
| **C** | no function re-exposes the old parameter list (no wrapper with > N legacy kwargs) | planted offender: a wrapper ⇒ RED |
| **D** | all production `run_workflow` callers use the typed boundary | asserts caller count ≥ 3 |
| **E** | `set(WorkflowRunBindings fields) ∩ set(ChainState fields) == ∅`, derived not hand-listed | planted offender: a `ChainState`-named field ⇒ `TypeError` |
| **F** | no task-name literal (`tidmad`/`pets`/`davis`) in any new carrier or the digest authority | asserts a non-zero scanned-file count |

Each census names the defect only it can catch, per CLAUDE.md.

---

## 34. Adversarial self-review

| # | challenge | outcome |
|---|---|---|
| 1 | Did I just move 99 arguments into one object? | **PASS** — §5.1 splits transit config (71) from authorities (12) and services (4) on a lifecycle rule; §5.6 keeps derived locals out entirely; §5.7 keeps the three DS7 no-ops out of every carrier |
| 2 | Can I explain why every binding field is immutable? | **PASS** — §10.1's membership rule; each class-A entry in §5.2 names the invariant or authority it represents |
| 3 | Can I explain why every chain-state field is cross-iteration? | **PASS** — §3.3 measures init-before-loop + mutated-inside for all 11 |
| 4 | Is any value classified into two owners? | **CORRECTED.** Revision-1's hand-built grouping double-counted `is_trial` and summed to 100. The classification was rebuilt **programmatically** from the load-site map: **no parameter is double-assigned, none unassigned**, and A+B+C+D+E+F = 12+9+71+4+0+3 = **99** exactly. §33-A keeps it exact permanently |
| 5 | Are any parameters unclassified? | **PASS** — verified programmatically: the unassigned set is empty |
| 6 | Did my field totals reconcile to source? | **CORRECTED, now YES** — 99/99 against the live signature, checked by script at `eb9f667e`. The earlier 100 was a hand-counting error in the draft, found by this review and fixed at source rather than annotated |
| 7 | Did I create a global `WorkflowContext` dumping ground? | **PASS** — three narrow carriers with three stated membership rules; §9.3 rejects the single-context option by name |
| 8 | Did I create a new central task/config registry? | **PASS** — §22; carriers hold values from existing authorities |
| 9 | Did I add future Step-10 fields now? | **PASS** — R13: no field without a current production producer |
| 10 | Did I rename scientific semantics? | **PASS** — §5.7 keeps `file_index` and every `best_*denoising_score` name; §11.3 refuses to unify the two incumbent-ish fields |
| 11 | Does one "helper" still read the file 4×? | **PASS** — §14.1 returns the whole pass; R4 + Gate-2 criterion 4 detect a regression |
| 12 | Are I/O/parse/soft-fail truly single-authority? | **PASS** — §14.1/§14.2 split *file* policy (one) from *value* policy (four) |
| 13 | Did I fold `load_latest_proposal` in? | **PASS — explicitly not.** §3.4 and §14.4 record its three structural differences and pin the isolation with a test |
| 14 | Did warning multiplicity change without disposition? | **PASS** — §14.3 preserves both text and multiplicity; §7.2/§7.3 supply the evidence; no operator question needed |
| 15 | Are latest-wins/union preserved independently? | **PASS** — §15's six rows, one test per row |
| 16 | Is cold-start state still single-authority? | **PASS** — §11.1: `cold_start` is the one default site and `from_restored` delegates to it |
| 17 | Can mutable state leak into immutable bindings? | **PASS** — §12 derived guard + planted offender |
| 18 | Does the ownership guard actually bite? | **PASS** — anti-vacuity is a named C2 deliverable, not an aspiration |
| 19 | Does the module placement create an inversion? | **PASS** — §9.2/§9.3: `ChainState` and the digest authority in `core/` precisely to avoid `core → workflows` |
| 20 | Did I accidentally fix the private registry import? | **PASS** — §1, §9.3, §28, R14; `core/resume.py:61` is untouched and a census pins that |
| 21 | Did I create a compatibility wrapper? | **PASS** — forbidden in §13, censused in §33-C |
| 22 | Did I miss a hidden caller / patch target? | **PASS** — §3.7 censuses 3 production + 21 test callers, and records that the 5 agent-class patch targets are unaffected; re-censused in C3/C5 |
| 23 | Could serialization change a frozen hash? | **PASS** — §3.10/§19: `build_run_invariants` takes scalars; carriers are never serialized; R9 is a STOP |
| 24 | Could mutation move across the commit boundary? | **PASS** — §3.9: the boundary is the launcher's `write_manifest`, outside `run_workflow` |
| 25 | Could retry/attempt semantics change? | **PASS** — the attempt loop (`:2298-2576`) is untouched; only the values it reads change carrier |
| 26 | Could LLM call order/count/bytes change? | **PASS** — §20 compares all six dimensions; R10 is a Gate-1 trigger |
| 27 | Is the Gate-1 waiver backed by exact evidence? | **PASS** — §25's waiver is conditional on the §20 oracle, with an automatic revert to REQUIRED |
| 28 | Does Gate 2 truly consume iteration-1 state? | **PASS** — §26 criteria 2–4 assert consumed values across **two different projection rules** |
| 29 | Is ≥ 2 temporal depth explicit? | **PASS** — §26, citing the standard's row |
| 30 | Did I add a real-LLM Gate unnecessarily? | **PASS** — Gate 1 planned NOT REQUIRED |
| 31 | Did I absorb CI scheduling maintenance? | **PASS** — §1 and §28 exclude `ci.yml` and markers |
| 32 | Duplicate tests for one failure class? | **PASS** — §27 assigns one owner per stage; §24 splits the one-time oracle from the permanent owners |
| 33 | Did I weaken a resume failure-mode test? | **PASS** — §14.3 was chosen *because* it requires zero edits to existing warn tests |
| 34 | Is Step-12 composition freedom preserved? | **PASS** — §22; acceptance criterion 16 |
| 35 | Would a fourth out-of-tree task need a carrier edit? | **PASS — NO** (§22 forward test), with the honest caveat that out-of-tree execution itself remains Step 12 |
| 36 | Does this actually reduce Step-10 amplification? | **PASS** — §32's two concrete tables |
| 37 | Is every changed file tied to A-1/A-2 or caller migration? | **PASS** — §28 gives a justifying owner per file |
| 38 | Could the PR be smaller? | **PASS, reasoned** — C1 alone would leave A-1 open; C3 alone would leave A-2 open and Step 10 still pays the loader tax |
| 39 | Would splitting into two PRs separate producer/consumer? | **PASS** — §23 explains why C1 and C4 must ship together |
| 40 | Can the operator approve implementation directly from this document? | **PASS** — scope, boundaries, the exact 99/99 census, module ownership, commit sequence, validation owners, gate disposition, stop conditions and cost projection are all explicit, with zero open questions |

**40 challenges. PASS 37 · CORRECTED 3 (items 1, 4, 6) · OPEN FINDING 0.
Material contradictions: 0.** The review's most useful catch was its own:
the revision-1 parameter table did not reconcile, and rather than annotate the
gap it was rebuilt programmatically and the section rewritten.

---

## 35. Open operator questions

**ZERO.**

The one question the parent anticipated — warning multiplicity (§16 of the
kickoff) — is **resolved from source evidence** in §14.3: message text is pinned
by existing tests, counts are not, and the chosen design preserves *both* while
still reading each digest once. No policy decision is required.

The parameter classification reconciles exactly (99/99, §5.0) and is re-checked
executably in C0 (§33-A), so it raises no question either.

---

## 36. Implementation-transition protocol

On an explicit operator `APPROVED / FREEZE + START`:

1. apply only the operator-requested amendments;
2. run the final adversarial re-read;
3. update this document to **REVISION 2 — FROZEN**;
4. commit + push the docs-only freeze; verify `master == origin/master`;
5. record the exact frozen-design SHA as the implementation base;
6. transition **this same PR context** from `DESIGN` to `IMPLEMENTATION` in
   `before_end_memory.md` (no context clear);
7. create branch `step09-5a-workflow-run-state-prerequisite` from that SHA;
8. initialize the filled Implementation Working Rules / live ledger;
9. re-verify branch, HEAD, tree fingerprint;
10. begin **C0** — and no production file may be edited before C0 lands.

### 36.1 Deviation policy for the implementation

| kind | examples | action |
|---|---|---|
| **LOCAL MECHANICAL** | a source line/function moved; a carrier file placement adjusts within the chosen package; a test owner relocates; the exact field list differs from §5's intent while every parameter still has exactly one owner | the implementation adapts **autonomously** and records it in the ledger |
| **MATERIAL SEMANTIC** | carrier ownership changes (a class-A value becomes class-B or vice versa); the immutable/mutable boundary moves; persisted semantics change; a resume merge rule or failure policy changes; a hash changes; an LLM-facing delta appears; the Gate claim weakens; Step-10/12 scope is touched; no legal module placement exists without touching plugin-registry ownership | **STOP** and report with source evidence |

---

## 37. Implementation ledger scaffold

**EMPTY — Phase 1. Nothing below is started.**

### 37.1 Commit milestones

- [ ] **C0** — pre-refactor differential oracle + executable parameter census
- [ ] **C1** — `core/committed_digests.py`; four projections migrated; `load_latest_proposal` isolated
- [ ] **C2** — `WorkflowRunBindings` · `WorkflowLaunchConfig` · `ChainState` · ownership guard (+ planted offender)
- [ ] **C3** — `run_workflow` signature migration + 3 production callers + 21 test files, atomic
- [ ] **C4** — the 11 accumulators adopt `ChainState`
- [ ] **C5** — censuses · `pyright` · docs sync · LLM-facing parity proof · Gate-1 disposition
- [ ] **C6** — Gate 2 · PR · exact-head CI

### 37.2 Evidence to record

- [ ] source findings and any correction to §3–§5
- [ ] field-ownership census output (row count == live signature length)
- [ ] caller census (production + tests), re-measured at C3 and C5
- [ ] committed-digest projection parity table (six rows of §15)
- [ ] read/parse count per committed digest per restoration pass
- [ ] differential oracle results (call envelope · artifacts · state · order)
- [ ] structural guard mutation/planted-offender evidence (§33-B, C, E)
- [ ] Gate-1 waiver evidence (six dimensions of §20) or Gate-1 result
- [ ] Gate-2 evidence: command, SHA, runtime, criteria 1–6
- [ ] final executable HEAD · final PR HEAD · exact-head CI id
- [ ] final metrics: `model_exploration.py` LOC · `run_workflow` LOC / branch nodes / parameters · `core/resume.py` LOC · digest I/O authorities · duplicated loader skeletons
- [ ] carried debt confirmed unchanged (§30)

### 37.3 Baseline metrics (MEASURED at `eb9f667e`, for the after-comparison)

| metric | before |
|---|---:|
| `workflows/model_exploration.py` LOC | 3,144 |
| `run_workflow` lines / branch nodes / parameters | 1,572 / 130 / 99 |
| `core/resume.py` LOC | 1,645 |
| `restore_prior_state` lines / branch nodes | 359 / 47 |
| committed-digest I/O authorities | **4** |
| duplicated carried-state reader skeletons | **4** |
| cross-iteration accumulators | 11 |
| production `run_workflow` callers | 3 |
| test files calling `run_workflow` | 21 |

*Recorded as engineering evidence. **No target value is an acceptance
criterion.***

---

*END — DRAFT REVISION 1. Not frozen. Implementation not started.*
