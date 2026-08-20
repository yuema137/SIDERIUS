# Step 09.5 — Repository Structural-Debt & Test-Topology Audit

**STATUS: REVISION 2 — FROZEN (operator ruling, 2026-08-20).**

**Step-10 entry verdict: STRUCTURAL PREREQUISITE REQUIRED — APPROVED.**
Structural class A = 2 · test-topology class A = 0 · one prerequisite milestone
(**Step 09.5a**) · five operator questions **RESOLVED** · zero open operator
questions.

---

## 0. Status, provenance, audit anchor

| field | value |
|---|---|
| **STEP-09.5 AUDIT ANCHOR** | `85fa4b748b548e9c2a977d342d3cb60cb8d00143` |
| local `master` | `85fa4b74` |
| `origin/master` | `85fa4b74` (verified equal after `git fetch`) |
| working tree at audit start | clean |
| Step 09b PR | **#239, MERGED** 2026-08-20T02:37:43Z |
| Step 09b final PR head | `ce3b971dab70c1dbf7aeb5811388465ecc5e34b6` |
| Step 09b merge (squash) commit | `e9a1f9fbb1c2e882be5b017756e2552a6b9f8d7c` |
| Step 09b exact-head CI | run **32324124087 — SUCCESS**, `full_suite=true`, `10745 passed, 32 skipped … 993.31s (0:16:33)` |
| Step 09a PR | #238, merged, squash `4cf38dec`, CI 32313798097 SUCCESS |

**Every measurement in this document is taken at the audit anchor unless
explicitly labelled otherwise.**

### 0.0 Operator rulings (2026-08-20) — FROZEN

The audit was reviewed and **APPROVED** with three consistency amendments. All
five operator questions are closed; §27 records each ruling in full.

| # | question | ruling |
|---|---|---|
| **Q1** | prerequisite PR vs absorb into Step 10 | **A — land the prerequisite first.** Formalized as the milestone **Step 09.5a — Workflow Run-State Structural Prerequisite**. |
| **Q2** | include the `core/resume.py:61` private registry import | **B — OUT OF SCOPE.** Different semantic owner (plugin/registry lifecycle); a named **Step-12** composition/layering input. |
| **Q3** | health-core census stays always-on | **A — keep it always-on.** The stale `~134` prose may be corrected the next time `manifest.py` is legitimately touched; no dedicated PR. |
| **Q4** | CI-side reproducible runtime baseline | **A — approved**, non-blocking. |
| **Q5** | real-subprocess evidence lane | **A — approved**, unconditionally (no longer gated on Q4). Split into its own parallel CI job; delete/mock/weaken nothing. |

**Three consistency amendments applied at freeze** — §20 amendment A (carriers
are semantic boundaries, **not** a 99-argument parameter bag), §22 amendment B
(the `run_workflow` **Python call signature is allowed to change**; identity and
operator/persisted contracts are what stay stable), §20/§23 amendment C (the
private registry import is out of prerequisite scope and is no longer presented
as evidence the prerequisite resolves).

**Gate disposition for Step 09.5a, frozen by the operator** — Gate 1 **NOT
REQUIRED if exact LLM-facing parity is proven**, otherwise REQUIRED; Gate 2
**REQUIRED, ≥ 2 iterations** (§20).

**Non-blocking follow-up recorded, not implemented:** the CI validation-topology
maintenance item (§20.2) covering Q4 + Q5. It does **not** gate Step 10 and is
**not** part of Step 09.5a.

### 0.1 Roadmap synchronization — verified, no repair needed

The post-Step-09 synchronization required by the kickoff was already present on
master and was **not** modified by this audit:

* `docs/design/siderius_generic_framework_upgrade.md:1540` — §11 Interpretation
  row reads **STEP 09 COMPLETE — MERGED**, naming both PRs and both CI ids, and
  ends `**NEXT = Step 09.5 (§15.1b), NOT Step 10.**`
* `:1541` — a dedicated **Step 09.5** row, `**NEXT — NOT STARTED.**`
* `:1542` — §12 Orchestration binding (Step 10) reads
  `**NOT STARTED — BLOCKED pending the Step 09.5 disposition (§15.1b).**`
* `:1847-1925` — §15.1b, the frozen mandate and the Step-10 entry gate.
* `:2212` — this document's path is already reserved in the document index.

The child designs
(`step_09_interpretation_task_blocks/pr_09a_…md`, `…/pr_09b_…md`) and the parent
(`step_09_interpretation_task_blocks.md`) are present and record the merged
state. **No inconsistency was found; no synchronization repair was performed
before or during the audit.**

**At FREEZE (revision 2), the roadmap was updated forward** to record the
outcome — the quoted line numbers above therefore describe master *at the audit
anchor*, not after the freeze. The freeze commit updates: the Step-09.5 row to
`AUDIT COMPLETE — REVISION 2 FROZEN`; a new **Step 09.5a** row; the Step-10 row
to `BLOCKED until Step 09.5a merges`; a supersession note on §15.1b; a new
**§15.1c** carrying the outcome, the three frozen Step-09.5a rules, the Q2 = B
scope exclusion, the non-blocking CI follow-up and the sequencing; and the
document index.

---

## 1. Mandate and non-goals

**Mandate (roadmap §15.1b).** Measure, at merged master, the repository's
production structure (Workstream A) and test topology (Workstream B); classify
every material finding A / B / C; and return an explicit **Step-10 entry
decision**.

**Non-goals — none of these was performed in this session:**

* no production refactoring, no test deletion or consolidation;
* no Step-10 implementation and no Step-10 child design;
* no implementation of the carried Step-10/12 semantic debt (§8.4 below records
  where it lives and what it would cost; it does not fix it);
* no Gate 1, no Gate 2, no real LLM, no real training or inference. The only
  test execution was read-only measurement: `--collect-only` inventories, a
  bounded 12-case `allow_real_subprocess` timing run (§11.4), and one
  full-suite profile deliberately aborted at 80 % (§11.1);
* no CI change — the §20.2 lane split is **recorded and approved, not
  implemented**;
* no change to any production or test file. The only repository changes made by
  this session are **this document**, the roadmap status synchronization
  (§0.1), and the local Step-09.5 handoff file.

**The audit separates OBSERVATION from RECOMMENDATION from FUTURE
IMPLEMENTATION**, and recommendations are described by ownership, never by line
count.

---

## 2. Authority / binding documents

| doc | role here |
|---|---|
| `docs/design/siderius_generic_framework_upgrade.md` | §15.1 status authority; §15.1b the Step-09.5 mandate and Step-10 entry gate; §22.12 the per-step support matrix; row `:1542` the Step-10 contract |
| `docs/design/generic_framework_upgrade/step_09_interpretation_task_blocks.md` | Step-09 parent, the frozen interpretation contracts this audit must not contradict |
| `.../step_09_interpretation_task_blocks/pr_09a_interpreter_evidence_ordering.md` | merged 09a ledger (MetricSpec transport, MetricOrder consumers, prediction v2) |
| `.../step_09_interpretation_task_blocks/pr_09b_interpretation_prompts_task_blocks.md` | merged 09b ledger (task blocks, explicit renderers) |
| `.../step_01_07_extensibility_debt_audit.md` | the Steps 01–07 extensibility-debt register — its accepted **B** items are NOT reopened here without new Step-10 evidence |
| `CLAUDE.md` | the binding responsibility-decomposition rule (2026-08-01) and validation-economy rule (2026-08-18) that this audit applies |
| `.github/workflows/ci.yml`, `tools/ci_selection/` | the actual, executable CI validation topology |
| `pyproject.toml` `[tool.pytest.ini_options]` | test configuration: `testpaths=["tests"]`, three markers, **no `addopts`, no xdist** — the unit suite runs serially |

---

## 3. Methodology and evidence-quality labels

Every number in this document carries one of:

* **MEASURED** — produced at the anchor by a command run in this session.
* **DERIVED** — computed from MEASURED inputs by a deterministic script
  (AST inventory, selector replay).
* **HISTORICAL** — read from a completed CI run, ledger or design doc; true of
  a *past* head, used only for trend, never as current truth.
* **ESTIMATED** — a projection with its uncertainty stated.

**Method.** A mechanical AST inventory over the entire tracked Python surface
(1,051 files parsed) produced size, class/function counts, largest-function and
branch-node metrics; hotspots were then deep-read for responsibility inventory.
Three read-only sub-agents produced deep dives on non-overlapping areas
(proposer / interpretation / test topology); **every load-bearing claim taken
from a sub-agent was independently re-verified by the main agent against source
before it was written here**, and §26 records two sub-agent claims that
verification *corrected*.

**Branch-node metric calibration (important).** The branch metric used
throughout counts `If/For/While/Try/With/BoolOp/IfExp/ExceptHandler/
comprehension/Assert/Match` AST nodes. It is calibrated against the project's
own established figure: CLAUDE.md records the tuner's `run()` at "branch nodes
198 → 64" after the 07b/C7 decomposition, and this audit's script measures
`nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py:454 run()`
at **exactly 64**. The metric is therefore comparable to every prior SIDERIUS
structural figure. **MEASURED.**

**Metrics are indicators, not verdicts.** No finding in this document is
classified A on size alone; §25 states the ranking dimensions explicitly, and
no composite "debt score" is used.

---

## 4. Repository production inventory

### 4.1 Totals — MEASURED at the anchor

| quantity | value |
|---|---|
| tracked Python files (all) | 1,051 |
| **production** Python files (non-`tests/`) | **333** |
| production physical LOC | **127,402** |
| production non-blank/non-comment LOC | 98,157 |
| test Python files | 718 (580 collected unit test modules) |
| test physical LOC | 210,611 |
| test : production LOC ratio | **1.65 : 1** |

### 4.2 Production LOC by top-level package — MEASURED

| package | LOC | files |
|---|---|---|
| `agent/` | 27,882 | 71 |
| `core/` | 27,182 | 71 |
| `nodes/` | 19,867 | 28 |
| `execute_tools/` | 18,403 | 52 |
| `scripts/` | 17,321 | 57 |
| `tools/` | 4,987 | 23 |
| `workflows/` | 3,915 | 4 |
| `sdsc_submission_scripts/` | 2,738 | 3 |
| `ml_models/` | 2,398 | 5 |
| `dashboard/` | 1,591 | 10 |
| `agent_generated/` | 654 | 4 |
| `examples/` | 331 | 4 |
| `env_validation/` | 123 | 1 |

### 4.3 Largest production files — MEASURED

| LOC | classes | fns | file-branch | largest function | file |
|---:|---:|---:|---:|---|---|
| 3,144 | 0 | 27 | 245 | `run_workflow` (1,572) | `workflows/model_exploration.py` |
| 3,036 | 11 | 17 | 96 | `validate_runtime_config` (83) | `agent/schemas/hyperparam_tuning.py` |
| 2,428 | 5 | 50 | 210 | `execute_training` (356) | `core/sandbox_executor.py` |
| 2,412 | 4 | 42 | 141 | `plan` (227) | `agent/llm_bridge.py` |
| 2,384 | 2 | 35 | 268 | `_run_pipeline` (666) | `nodes/ml_model_proposal_agent/ml_model_proposal_agent.py` |
| 2,238 | 0 | 16 | 162 | `build_parser` (780) | `sdsc_submission_scripts/run_one_iteration.py` |
| 2,059 | 1 | 26 | 149 | `run` (298) | `nodes/ml_model_implementor/ml_model_implementor.py` |
| 2,027 | 3 | 28 | 171 | `run_experiment_streaming` (728) | `execute_tools/train_engine_sandbox.py` |
| 1,648 | 2 | 42 | 139 | `parse_args` (201) | `scripts/c2_prephase_validation.py` |
| 1,645 | 4 | 27 | 171 | `restore_prior_state` (359) | `core/resume.py` |
| 1,603 | 3 | 32 | 110 | `_resolve_time_check_probe_request` (209) | `nodes/ml_hyperparameter_tune_agent/runtime.py` |
| 1,585 | 0 | 10 | 160 | `main` (774) | `scripts/run_comparison.py` |
| 1,505 | 0 | 15 | 125 | `get_planner_user_prompt` (391) | `agent/prompts.py` |
| 1,491 | 1 | 4 | 69 | `run` (1,015) | `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py` |
| 1,281 | 1 | 9 | 117 | `run` (907) | `nodes/result_interpretation_agent/result_interpretation_agent.py` |
| 1,039 | 0 | 15 | 134 | `_build_synthesis_prompt` (229) | `agent/prompt_templates/interpretation/rendering.py` |
| 931 | 0 | 10 | 108 | `generate_discoveries` (176) | `nodes/interpretation_helpers.py` |

### 4.4 Largest functions by decision density — MEASURED

Ranked by branch nodes, the metric calibrated in §3.

| branch | lines | function | location |
|---:|---:|---|---|
| **130** | **1,572** | `run_workflow` | `workflows/model_exploration.py:1370` |
| **88** | 907 | `run` | `nodes/result_interpretation_agent/result_interpretation_agent.py:200` |
| **86** | 666 | `_run_pipeline` | `nodes/ml_model_proposal_agent/ml_model_proposal_agent.py:1575` |
| 79 | 774 | `main` | `scripts/run_comparison.py:807` |
| 67 | 669 | `main` | `execute_tools/inference_single.py:336` |
| **64** | 1,015 | `run` | `nodes/ml_hyperparameter_tune_agent/…:454` *(the post-C7 reference point)* |
| 62 | 728 | `run_experiment_streaming` | `execute_tools/train_engine_sandbox.py:970` |
| 53 | 628 | `main` | `sdsc_submission_scripts/run_one_iteration.py:1606` |
| 47 | 359 | `restore_prior_state` | `core/resume.py:1229` |

**Reading.** The tuner's decomposed `run()` (64 branches / 1,015 lines) is the
project's own accepted shape for a long lifecycle orchestrator. Exactly **three**
production functions are materially denser than it, and all three are
Step-10-relevant or Step-10-adjacent: `run_workflow` (2.0×), the interpreter's
`run` (1.4×), and the proposer's `_run_pipeline` (1.3×).

### 4.5 Churn — MEASURED, and it does NOT support a churn-based argument

Files touched by the last **10 milestone squash commits** (09b, 09a, 08c, 08b,
08a, D14, 07-correction, 07b, 07a, PR0):

| milestones touched | file |
|---:|---|
| 3 / 10 | `agent/schemas/hyperparam_tuning.py`, `execute_tools/health_checks/sample_dispersion_floor.py`, `execute_tools/health_checks/__init__.py` |
| 2 / 10 | `workflows/model_exploration.py`, `nodes/result_interpretation_agent/result_interpretation_agent.py`, `nodes/interpretation_helpers.py`, several tuner and health modules |

**Churn is flat and concentrated in nothing.** This audit therefore does **not**
use churn as evidence for any finding. Recorded because the mandate asks for it,
and because the honest answer is that it discriminates nothing here.

---

## 5. Structural hotspot ranking

Ranked by the explicit dimensions of §25 — **not** by a composite score, and
**not** by LOC.

| # | surface | mixed ownership | Step-10 touch | duplicated authority | change amplification | dependency rigidity | class |
|---|---|---|---|---|---|---|---|
| 1 | `workflows/model_exploration.py` | **high** (4+ owners) | **certain, central** | yes (99-param threading × 3 call sites) | **high** | **high** (`core/resume.py` imports a PRIVATE symbol from it) | **A** |
| 2 | `core/resume.py` carried-state loaders | medium | **certain** | **yes — 4 structurally identical loaders** | **high** (+1 loader per carried item) | low | **A** |
| 3 | `nodes/ml_model_proposal_agent/…py` | **high** (12 owners) | partial (proposer grammar is Step-10 debt) | **yes — legacy/pipeline reader, drifted 3×** | high | medium | **B** |
| 4 | `nodes/result_interpretation_agent/…py` | **high** (17 phase banners) | low (Step 09 just closed it) | yes (3 record ctors, 2 persistence blocks) | medium | low | **B** |
| 5 | `sdsc_submission_scripts/run_one_iteration.py` | medium (parser + policy + manifest) | **certain** (launcher binding) | no | medium (85 args → 89 kwargs) | low | **B** |
| 6 | `nodes/interpretation_helpers.py` | **high** (4 unrelated concerns) | low | yes (5 % band duplicated with `prediction.py`) | low | low | **C** |
| 7 | `agent/prompt_templates/interpretation/rendering.py` | low–medium | low | minor (2 accounting rules) | low | low | **C** |
| 8 | `execute_tools/health_checks/evaluation.py` | low | **certain** (assigned Step-10 debt) | no | low | low | **B** |
| 9 | `agent/schemas/hyperparam_tuning.py` | n/a (schema) | likely | no | low | **CI hub** | **C** |
| 10 | `execute_tools/task_data_path.py` | **none — exemplary** | yes (task binding) | no | low | low | **healthy** |

---

## 6. Detailed semantic-ownership audits

### 6.1 `workflows/model_exploration.py` — 3,144 LOC — **the primary finding**

#### 6.1.1 Shape — MEASURED

* `run_workflow` at `:1370-2941` = **1,572 lines, 130 branch nodes** — the
  largest and densest function in the repository.
* Its signature takes **99 parameters** (`workspace … measurement_capability`).
* Its body is: ~384 lines of run setup (`:1715-2098`), then **one 813-line
  `for iteration in …` loop** (`:2106-2918`), then 21 lines of summary.
* Around it, at module level, sit ~500 further lines of **plugin/loss registry
  lifecycle**: `_register_plugin` (175), `_promote_loss_to_global` (125),
  `_promote_model_to_global` (119), `_add_plugin_to_registries` (44),
  `_cleanup_stale_registry_entries` (35); plus `_validate_construction_memory`
  (121) — a **memory-admission policy**.

#### 6.1.2 Responsibility inventory — at least five independent owners

| owner | evidence (line ranges) | could change independently? |
|---|---|---|
| **O1 Run setup / banner / environment** | `:1735-1808` — `makedirs`, `_snapshot_task_config`, `os.environ.setdefault`, 18 `print` banner lines | yes |
| **O2 Run-scoped binding & invariants** | `:1817-1834` hardware context + VRAM budget; `:1847-1855` `reconcile_metric_spec` + `MetricOrder`; `:1868-1900` DataScope resolve + partial-scope policy + `build_run_invariants`; `:1933-1950` launch self-test + `ensure_run_invariants` | **yes — and this is Step 10's subject** |
| **O3 Chain-state carry** | `:1974-2069` — ~15 mutable accumulators initialised from `restored_*` parameters (`iteration_results`, `best_score_overall`, `chain_formal_incumbent_reference`, `previous_proposal_data`, `current_collapse_fingerprint_history`, `current_prediction_memory`, `model_knowledge_cache`, `recent_tune_outputs`, …), mutated across the 813-line loop, persisted at `:2932` | **yes — and this is Step 10's subject** |
| **O4 Per-iteration node lifecycle** | `:2106-2918` — interpret (42-line `InterpretationInput(...)` at `:2149`) → literature review (`:2217`) → 279-line proposal/implement/validate attempt loop (`:2298-2576`) → plugin registration/promotion → tune (83-line `local_validated_model(...)` at `:2658`) → state accumulation → memory probe/gc | yes |
| **O5 Plugin & loss registry lifecycle** | module-level `:827-1362`, ~500 LOC | **yes — and `core/resume.py` already imports into it** |

#### 6.1.3 Why this is not merely "long"

The disqualifying properties are ownership properties, not length:

1. **A `core` module reaches into this file's private surface.**
   `core/resume.py:61`:
   ```python
   from workflows.model_exploration import _add_plugin_to_registries
   ```
   A lower layer importing a **private** symbol from the highest-layer
   orchestrator. Any decomposition of **O5 (the plugin/loss registry
   lifecycle)** is simultaneously a change to `core`. **MEASURED.**

   **Scope note (Q2 = B, FROZEN):** this is a real finding about *O5*, which
   Step 09.5a does **not** touch — the prerequisite owns O2 and O3. It is
   therefore **out of prerequisite scope** and is carried as a named **Step-12**
   composition/layering input. It is evidence that layering debt exists; it is
   **not** evidence for the prerequisite (§23, amendment C).

2. **The task binding is pulled, not injected.** `:106`
   `from execute_tools.dataset_config import TIDMAD as _DATASET_CONFIG`, used at
   `:1869`, `:1870`, `:1909`. Three further production modules pull the task the
   same way (`nodes/ml_model_implementor:48`,
   `nodes/ml_model_proposal_agent:53`,
   `nodes/ml_hyperparameter_tune_agent:197`, all
   `from workflows.task_config import …`, plus a lazy one at
   `core/sandbox_executor.py:1255`). Step 10's contract is *"Task binding lives
   at the launcher"* — i.e. exactly the inversion of this. **MEASURED.**

3. **Direction literals live inside the loop.** `:2854-2858`
   `or tune_output.best_formal_denoising_score > best_score_overall`, and
   `:2865-2870` for the valid-formal incumbent. These are the roadmap's
   "workflow/resume direction literals → Step 10" (`:3481`), and they sit inside
   the 813-line loop body, next to the state they mutate. **MEASURED.**

4. **Three independent call sites re-thread the 99 parameters.** **MEASURED**:

   | caller | kwargs passed |
   |---|---|
   | `sdsc_submission_scripts/run_one_iteration.py:1945` | **89** |
   | `sdsc_submission_scripts/run_exploration_test.py:151` | 19 |
   | `workflows/model_exploration.py:3122` (own `main`) | 16 |

   Upstream of the 89-kwarg call: `build_parser` with **85 `add_argument` calls**
   (780 lines) and `normalize_args` (137 lines).

5. **The project has already solved this problem once, elsewhere.** CLAUDE.md
   records that the tuner's C7 decomposition introduced `RunBindings` — "carries
   run-scoped authorities ONLY, enforced at construction by
   `FORBIDDEN_BINDING_FIELDS`" — and `AttemptStage` as the single deliberate
   mutable carrier. `run_workflow` has neither: O2 and O3 are 99 positional
   parameters and ~15 bare locals.

#### 6.1.4 What Step 10 would add here

From the roadmap (`:1542`, §22.12 `:3397`), Step 10 owns: launcher-owned task
binding; workflow/resume best-score comparisons via the metric handle; a second
bound task initialising the loop; `campaign_artifacts`; orchestration inputs to
resume; plus the inherited semantic debt (secondary-metric transport,
`vocab_link_confirmations` carry, resume/dashboard direction literals).

Landed directly, that is: **+N parameters on a 99-parameter function**, **+N
locals in the state block**, **+N mutations inside the 813-line loop**, **the
direction literals rewritten in place inside that loop**, and **a task-binding
concept introduced into a function that currently pulls its task from a
module-level import**. Every one of those lands in O2/O3 — the two owners that
are already the least separated.

### 6.2 `core/resume.py` — 1,645 LOC — four structurally identical loaders

**MEASURED.** `RestoredState` (`:106-223`) declares **14 fields**, ~10 of which
are per-iteration accumulators. Five `load_latest_*` functions feed them:

| function | lines | size |
|---|---|---|
| `load_latest_knowledge` | `:789-869` | 81 |
| `load_latest_fingerprint_history` | `:872-949` | 78 |
| `load_latest_prediction_memory` | `:952-1025` | 74 |
| `load_latest_knowledge_cache` | `:1028-1105` | 78 |
| `load_latest_proposal` | `:1161-1221` | 61 |

The **first four** are structurally identical, verified line by line:

* identical signature `(workspace, current_iter, committed_iters)`;
* identical guard `if current_iter <= 1 or not committed_iters:` (`:818`,
  `:900`, `:976`, `:1071`);
* identical loop `for iter_idx in committed_iters:` (`:825`, `:905`, `:981`,
  `:1076`);
* identical `path = _interpretation_path(workspace, iter_idx)` (`:826`, `:906`,
  `:982`, `:1077`) — **all four open and `json.load` the same digest file**;
* identical missing-file `warnings.warn` + `continue`;
* identical `except (OSError, json.JSONDecodeError)` `warn` + `continue`.

They differ **only** in which digest key(s) they read, which Pydantic model
validates the entries, and whether the merge rule is latest-wins or union.

The duplication is self-documented — `:880` *"Latest-wins, matching
``load_latest_knowledge_cache``"*, `:960` *"…in every respect that matters"*,
`:1066` *"Mirrors :func:`load_latest_knowledge`"*. **Four docstrings asserting
that four functions are the same function is the strongest possible evidence of
one authority written four times.**

Consequence today: the same JSON file is opened and parsed **four times per
iteration**, and a change to the soft-fail policy (the documented contract) must
be made in four places or the four carried items silently diverge.

`_pick_best` (`:435-449`) carries a raw direction literal at `:445`
(`if score > best_score …`) — the resume half of the roadmap's Step-10 direction
debt. **MEASURED.**

**Change amplification for ONE new carried item — DERIVED** (traced against the
09a `prediction_memory` carry, which touches exactly three production files):

```
core/resume.py            : +1 ~75-line loader  +1 RestoredState field
                            +restore_prior_state wiring
sdsc_submission_scripts/  : +1 CLI arg (86th)  +normalize_args  +1 kwarg (90th)
workflows/model_exploration.py
                          : +1 run_workflow parameter (100th)
                            +1 local in the state block
                            +1 mutation inside the 813-line loop
```

Step 10 owns **two** such items by name (`vocab_link_confirmations` carry and
production secondary-metric transport), so the amplification is paid twice.

### 6.3 `nodes/ml_model_proposal_agent/ml_model_proposal_agent.py` — 2,383 LOC

**Twelve co-resident responsibilities**; the disqualifying ones are duplication
and absent direction ownership, not the count.

#### 6.3.1 The legacy/pipeline interpretation reader — duplicate authority, three recorded drifts

The protocol collapses the typed upstream object at the edge —
`agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py:171-172`
(`"interpretation": output.model_dump()`) into
`ProposalInput.interpretation: dict[str, Any]`
(`agent/schemas/proposal.py:650`). Downstream, ~40 string-literal `.get()` reads
are split across **four** readers:

| reader | mode | lines |
|---|---|---|
| `_build_reasoning_prompt` | LEGACY only | `:1105-1227` |
| `_run_pipeline` (18-key whitelist + 5 direct) | PIPELINE only | `:1620-1699` |
| `_format_healthgate_evidence_block` | both | `:816-825` |
| `nodes/proposal_helpers.py` | pipeline only | `:50-58`, `:358`, `:366` |

**No typed reader exists on the proposer side.** The source records two drift
incidents *found by a live Gate, not by review* — `:1257-1263` (a block wired to
pipeline only, so "the real proposer call took the legacy branch, so the block
never reached the model") and its mirror at `:1741-1746` (a legacy-only splice
that never reached pipeline). **MEASURED.**

**Which mode does production actually take? — MEASURED, and it matters.**
`ProposalAgent.run` (`:1470-1477`) dispatches on
`has_pipeline = inp.reasoning_pipeline and .stages and any(s.enabled …)`;
`workflows/model_exploration.py:206` returns a 2-stage pipeline **iff**
`isinstance(llm_config.propose, ProposalLLMConfig)`. Executed at the anchor:

```
openai_tiered_pro      propose=ProposalLLMConfig   PIPELINE=True
openai_tiered_v1       propose=ProposalLLMConfig   PIPELINE=True
deepseek_tiered_pro    propose=ProposalLLMConfig   PIPELINE=True
certify_minimal        propose=ProposalLLMConfig   PIPELINE=True
WorkflowLLMConfig()    propose=None            ->  legacy
```

and `workflows/llm_config.py:438` (the `--provider/--model_id` path) also builds
a `ProposalLLMConfig`. **Every documented production launch takes the PIPELINE
path**; legacy is reachable only via the bare default and the node's standalone
CLI.

**Verified consequence — two reads are dead.** `InterpretationOutput` has no
`per_file_comparison` and no `efficiency_comparison` field (executed against the
schema at the anchor: both `False`), yet `_build_reasoning_prompt:1180-1186`
branches on both, and the interpreter's synthesis prompt
(`agent/prompt_templates/interpretation/rendering.py:687-688`) still asks the
LLM to produce them. Paid-for output, dropped, then read by an unreachable
consumer — invisible because both sides are untyped `.get()`.

**A second verified consequence, and the precise Workstream-B lesson.**
Step 09b's version-aware prediction track record is wired into
`_build_reasoning_prompt` **only** (`render_prediction_track_record` is called at
exactly one proposer site, `:1157`, which lies inside `_build_reasoning_prompt`
`:1086-1309` — MEASURED). The pipeline path instead forwards the four versioned
fields as raw JSON into `interpretation_summary` (`:1668-1694`), which the
source documents deliberately as *"Step 09b C4: the four versioned fields ride
ALONGSIDE the legacy trio"*. **This is a deliberate, documented two-transport
design and is NOT a violation of a frozen Step-09 contract** — the version
partition survives on both paths. What *is* a finding is the test that appears
to own it:

```python
# tests/unit/agent/result_interpretation_agent/test_step09b_c4_prediction_rendering.py:169-175
def test_the_proposer_calls_the_same_renderer(self):
    source = (REPO_ROOT / "nodes/ml_model_proposal_agent/ml_model_proposal_agent.py").read_text()
    assert "render_prediction_track_record" in source
    assert "sum(pred_hist.values())" not in source
```

a **substring scan satisfied by the legacy call site alone**, while no test
anywhere under `tests/unit/agent/ml_model_proposal_agent/` references
`prediction_pool_sizes` or `prediction_evaluation_semantics` — i.e. the
production-reachable transport is unpinned. **MEASURED.** See §14.1.

#### 6.3.2 Direction ownership is absent

`MetricOrder`, `MetricSpec` and `metric_spec` occur **zero** times in
`ml_model_proposal_agent.py`, `nodes/proposal_helpers.py` and
`agent/schemas/proposal.py` (MEASURED, exact count 0/0/0). `ProposalInput` has no
`metric_spec` field, in contrast to `InterpretationInput.metric_spec`, which 09a
made fail-closed. `InterpretationOutput.metric_identity` *is* present in the
dumped dict and is never read.

Concrete consequence, `nodes/proposal_helpers.py:84-89`:

```python
if method == "top_n":
    scored = [m for m in all_models if m["best_score"] is not None]
    scored.sort(key=lambda m: m["best_score"], reverse=True)
    return scored[:n]
```

Under a lower-is-better metric this selects the **worst** N models as the
comparison stage's candidates — the exact defect class 09a eliminated across 21
interpreter sites. The proposer was explicitly out of 09a's scope; this records
it, and it belongs to Step 10's assigned "proposer prediction-authoring grammar"
debt. **Not fixed here.**

#### 6.3.3 Dead constant

`_MAX_REASONING_RETRIES = 1` (`:64`) is defined and **never referenced anywhere
in production** (MEASURED: one grep hit, the definition), while the node's public
`ml_model_proposal_agent.md:164` documents it as the live mechanism.

### 6.4 `nodes/result_interpretation_agent/result_interpretation_agent.py` — 1,281 LOC

`run()` = **907 lines / 88 branch nodes** (MEASURED) — 1.4× the decision density
of the tuner's post-C7 `run()`, in a node the project has *just* finished two
milestones on.

Verified ownership evidence:

* **Seventeen `# --- … ---` phase banners** inside one function — the file's own
  declaration of seventeen responsibilities.
* **Three record constructors for one schema**: `InterpretationOutput(...)` with
  9 kwargs at `:210` (cold start), and two `InterpretationOutput.model_validate({…})`
  dict literals — healthy at `:916` and degraded at `:1020` — which overlap
  heavily. **MEASURED** (verified by reading all three).
* **Two near-identical persistence blocks** at `:975-1002` and `:1086-1105`,
  differing only in a print prefix and `evolution_stats` vs `degraded_stats`.
  **MEASURED** (verified by reading both).
* **Four LLM call sites in three unrelated conversations** — per-model
  summarization, cache consolidation, cross-model synthesis, vocabulary dedup.

CLAUDE.md's decomposition rule names *"failure/skip record construction"* and
*"artifact persistence"* as extraction targets by name. Both are present here in
duplicate.

**But Step-10 touch probability is LOW.** Step 10's contract (`:1542`) names
workflow binding, `campaign_artifacts`, orchestration inputs to resume and the
launcher — not the interpreter's internals. The interpreter's carried debt
(secondary transport, `vocab_link_confirmations`) touches it at two narrow
sites, not across `run()`. This is why §9 classifies it **B**, not **A**: it is
real debt in a genuinely mixed file, but Step 10 does not materially deepen it.

### 6.5 `nodes/interpretation_helpers.py` — 931 LOC — grab-bag, but low-risk

Four unrelated concerns in 11 functions: vocabulary (×5), discovery generation
(×1), **LLM-cost policy** (`select_active_models`, `should_recall_per_model`,
`promote_candidates`' `min_runs`), prompt-content production
(`compress_model_summary`), and a research-health metric
(`compute_vocab_diversity_ratio`). Its module docstring (`:3-6`) is stale — it
still claims "They evaluate predictions", which moved to
`nodes/result_interpretation_agent/prediction.py` in 09a.

**MEASURED:** it has exactly **one** production importer —
`result_interpretation_agent.py`, via four *lazy imports inside the degradation
try-block* (`:423`, `:629`, `:650`, `:728`). It is not shared infrastructure; it
is `run()`'s off-loaded body, parked at flat `nodes/*.py` where it also escapes
`tests/unit/nodes/test_node_public_boundary.py` (which globs *inside* node
packages).

### 6.5a Long-but-coherent — the contrast cases that are deliberately NOT flagged

The mandate asks explicitly whether a file is "merely long because one coherent
process is long". Three surfaces were examined and cleared, and they define the
boundary this audit is drawing:

* **`agent/schemas/hyperparam_tuning.py` — 3,036 LOC**, the second-largest
  production file and a declared CI hub. It is 11 Pydantic models; its largest
  function is `validate_runtime_config` at 83 lines. Size without mixed
  ownership. **Not flagged.**
* **`core/runtime_control/campaign.py:466 evaluate_campaign` — 201 lines / 54
  branch nodes**, the 9th-densest function in the repository. Its docstring
  states the contract — *"Apply the frozen thresholds. Deterministic and
  order-independent"* — and it is exactly that: typed in, typed out, no I/O, no
  state, many branches because there are many thresholds. **Not flagged.**
* **`sdsc_submission_scripts/run_one_iteration.py:653 build_parser` — 780
  lines**, the single largest non-`run_workflow` function. It is 85
  `add_argument` calls. A CLI parser is a legitimately wide flat surface.
  **Not flagged** (§9 B-4).

The A findings are not the longest things in the repository. They are the two
places where **several owners that can change independently share one scope,
and Step 10 must edit exactly that scope.**

### 6.6 `execute_tools/task_data_path.py` — 364 LOC — the healthy counter-example

A `TaskDataPath` Protocol (4 methods), typed request models, a fail-closed
registry, a run-scoped `bind_task_data_path` context manager, and an explicit
`transport_argv` / `resolve_transported_task_data_path` subprocess boundary. This
is what Step 10's task binding should look like, and it already exists as a
landed D14 seam. **No finding.** Recorded because §29 asks whether any hotspot
forces core edits per task — this one demonstrably does not.

---

## 7. Step-10 touch-risk map

Step-10 surfaces are read from the roadmap contract at `:1542` and §22.12
`:3397`.

| Step-10 responsibility | current source surface | structural health | risk if Step 10 lands directly | class |
|---|---|---|---|---|
| **workflow orchestration** | `workflows/model_exploration.py` `run_workflow` (1,572 / 130 br / 99 params) | mixed, 5 owners | new binding + state + comparisons all land in the two least-separated owners | **PREREQUISITE REFACTOR REQUIRED** |
| **task binding at the launcher** | `run_one_iteration.py` (85 args → 89 kwargs) + a module-level `TIDMAD` pull in 5 production files | inverted (nodes/core pull from `workflows`) | binding introduced *beside* the pull it is meant to replace; two mechanisms coexist | **EXTEND ONLY WITH LOCAL DECOMPOSITION** |
| **resume / state restoration** | `core/resume.py` 4 identical loaders + `RestoredState` (14 fields) | duplicated authority | +2 more copies of a 75-line loader; soft-fail contract now in 6 places | **PREREQUISITE REFACTOR REQUIRED** |
| **metric / direction transport (D1)** | `model_exploration.py:2854-2870`, `core/resume.py:445`, `dashboard/data_sources/local_json.py:245` | 3 literal sites, all small | low — `MetricOrder` already exists and `model_exploration.py:108` already imports it | **SAFE TO EXTEND** |
| **secondary-metric transport** (Q-09-7 = B) | typed carrier `SecondaryMetricEvidence` exists; builder deliberately never populates | receiving side ready; the cache-carry side is asymmetric with `failure_counts` | medium — see §8.3 | **EXTEND ONLY WITH LOCAL DECOMPOSITION** |
| **`vocab_link_confirmations` carry** | schema both ways; **workflow never carries it** | feature inert today (§8.2) | low structurally, but the landing site is segment 20 of 26 inside `run()` | **B** |
| **`evaluation.py` per-check-NAME tables** | `execute_tools/health_checks/evaluation.py:84-131` (309-LOC file) | small, clear boundary | low | **SAFE TO EXTEND** |
| **`campaign_artifacts`** | `core/runtime_control/campaign.py` `evaluate_campaign` (201 / 54 br) | focused | low | **SAFE TO EXTEND** |
| **proposer prediction-authoring grammar** | proposer + `proposal_helpers.py`, zero `MetricOrder` | duplicated reader, direction-blind | medium–high — every field added must be wired **twice** or reach one mode only | **EXTEND ONLY WITH LOCAL DECOMPOSITION** |

---

## 8. Duplicate production-authority audit

Only findings where **one semantic invariant has more than one implementation
that can drift independently** are listed. Thin wrappers and re-exports are
excluded by construction and named in §8.6.

### 8.1 The four `load_latest_*` digest loaders — **REAL, highest-value**
§6.2. Four copies of "read a committed interpretation digest, tolerate
corruption, pick latest-wins". Self-documented as mirrors of each other.

### 8.2 `vocab_link_confirmations` — carried by NOTHING, and the feature is inert
**MEASURED, verified end to end.** `InterpretationInput.vocab_link_confirmations`
(`agent/schemas/interpretation.py:677`) and
`InterpretationOutput.vocab_link_confirmations` (`:1155`, whose description says
*"Carry forward as InterpretationInput.vocab_link_confirmations"*) both exist.
`workflows/model_exploration.py` **never mentions the field** — the production
input constructor at `:2149-2190` threads prediction memory explicitly but omits
this one, so `inp.vocab_link_confirmations` is `{}` on every iteration.

Because one iteration appends at most one `run_name`
(`result_interpretation_agent.py:856` passes `run_name=prev_model_type`) and
`interpretation_helpers.py:657-659` skips any key with
`len(run_names) < min_runs` where `min_runs=3` (`result_interpretation_agent.py:860`),
`newly_promoted` is **empty by construction**. The `related_to` promotion
(`interpretation_helpers.py:660-676`) and the change-log branch
(`result_interpretation_agent.py:862-872`) are **unreachable in production**.

This is the same failure class as 09a's recorded erratum E2 ("carried by
NOTHING"). It is **Step-10-owned semantic debt and is NOT fixed here**; it is
recorded because it sharpens what Step 10 must do: not "add a carry" but
"activate an inert feature and prove reachability".

### 8.3 Secondary metrics — receiving side ready, cache-carry side asymmetric
`failure_counts` is carried **both** ways through the per-model `_stats` cache
(written `result_interpretation_agent.py:526-530`, read back `:353-358`).
`secondary_metrics` has **neither** — `:361-365` projects from `inp.summaries`
only, with no cache fallback, and `new_stats` (`:504-534`) has no
`secondary_metrics` key. The moment Step 10 populates secondaries, a model that
goes quiet for one iteration loses them while keeping its failure counts.
**Recorded, not fixed** (Q-09-7 = B is frozen; the builder must keep not
populating them until Step 10).

### 8.4 The "within 5 %" band — two owners, two frozen constants
`nodes/result_interpretation_agent/prediction.py:198-207` and
`nodes/interpretation_helpers.py:338-358` implement the identical arithmetic
(`band_width = 0.05 * abs(reference)`; `order.is_better(...)` /
`distance <= band_width` / else) from **two independently declared constants**
(`partial_margin=0.05` and `_DISCOVERY_RELATIVE_BAND = 0.05` at
`interpretation_helpers.py:20`). Each site separately documents the Q-09a-5
freeze — two documents of one freeze is the evidence they are two owners.
**MEASURED.** Class **C**: both are correct today and Step 10 does not touch
them.

### 8.5 Layering inversions — 5 sites, one of them private
**MEASURED.**

| site | inversion |
|---|---|
| `core/resume.py:61` | `from workflows.model_exploration import _add_plugin_to_registries` — **core ← workflows, PRIVATE symbol** |
| `core/sandbox_executor.py:1255` | lazy `from workflows.task_config import run_bound_model_io_contract` |
| `nodes/ml_hyperparameter_tune_agent/…:197` | `from workflows.task_config import run_bound_model_io_contract` |
| `nodes/ml_model_proposal_agent/…:53` | `from workflows.task_config import get_task_description, load_task_config, render_forward_contract` |
| `nodes/ml_model_implementor/…:48` | `from workflows.task_config import render_forward_contract` |

The four `task_config` pulls are the *mechanism* Step 10 is chartered to
replace. The `core/resume.py` one is different in kind: it is a private-symbol
dependency that makes O5 of §6.1.2 undecomposable without touching `core`.

**Owner (Q2 = B, FROZEN):** the private registry import belongs to the
**plugin/registry lifecycle** owner, not to the run-state carrier owner. It is
**OUT OF SCOPE for Step 09.5a** and is carried as a named **Step-12**
composition/layering input.

### 8.6 Investigated and found NOT to be duplicate authority
Recorded so they are not re-flagged:

* **`scripts/run_comparison.py` is not a second workflow launcher.** It launches
  the *tuner* as a subprocess (`:791`) for baseline comparison; it never calls
  `run_workflow`. **MEASURED.**
* `render_prediction_track_record` — **one** authority with two consumers
  (`rendering.py:980`, proposer `:1157`). Correct sharing.
* `agent/prompts.py` composes with `agent/prompt_templates/tuner/rendering.py`
  (`prompts.py:9`); the 07b split is a delegation, not a duplication.
* `render_metric_direction_words` is single-authority in
  `execute_tools/metric_order.py`; both prompt families delegate to it. Only the
  one-line *sentence* around it is spelled twice — cosmetic, class C.
* `_COMPATIBILITY_REEXPORTS` in the interpreter is a self-documented shrink-only
  re-export.

---

## 9. Structural A/B/C triage

### Class A — PRE-STEP-10 BLOCKER (2 findings)

> The burden of proof is on A. Each entry states the exact Step-10 interaction
> and why deferring is materially more expensive.

**A-1 — `run_workflow`'s run-scoped binding and chain-state carry have no
carrier.**
*Evidence:* 99 parameters; 130 branch nodes in 1,572 lines; ~15 mutable
accumulators at `:1974-2069` mutated across an 813-line loop; three call sites
re-threading them (89 / 19 / 16 kwargs); a module-level `TIDMAD` pull at `:106`
consumed at `:1869-1909`; direction literals at `:2854-2870` inside the loop.
*Step-10 interaction:* Step 10 adds launcher-owned **task binding**, **resume
orchestration inputs**, and **metric-handle comparisons** — all three land in O2
and O3, the two owners with no boundary between them.
*Why deferring costs more:* every parameter and accumulator Step 10 adds must
later be migrated **out of three call sites and an 85-argument parser** as well
as out of the function. The project already paid this exact cost once, in the
tuner's C7 (`run()` 2,714 → 1,011 lines, 198 → 64 branches), and the rule
written from it — CLAUDE.md, 2026-08-01 — is precisely *"do not add substantial
new branching, record construction, persistence or task logic directly into an
already oversized function"*. `run_workflow` at 130 branches is **twice** the
density of the shape that rule produced.

**A-2 — `core/resume.py`'s carried-state loaders are one authority written four
times, and Step 10 adds two more.**
*Evidence:* §6.2 — four byte-comparable loaders over the same file, three of
which document themselves as mirrors of another.
*Step-10 interaction:* Step 10 owns `vocab_link_confirmations` carry **and**
production secondary-metric transport — two new carried items, each currently
costing a fifth and sixth copy of the loader plus a `RestoredState` field plus a
CLI argument plus a `run_workflow` parameter plus a loop mutation.
*Why deferring costs more:* the soft-fail contract would then live in six
places, and every future carried item pays the same tax. The correct boundary —
*one* digest reader parameterised by key + validator + merge rule — is
mechanical, behaviour-preserving, and strictly cheaper to establish **before**
two more copies exist than after.

**A-1 and A-2 share one semantic boundary** — "run-scoped state that is
restored, carried across iterations, and persisted" — and are therefore **one**
prerequisite milestone, **Step 09.5a**, not two (§20). Neither A finding cites
the `core/resume.py:61` private registry import, which is out of scope under
Q2 = B (§23, amendment C).

### Class B — FORWARD CONSTRAINT (Step-10-owned; no separate prerequisite)

* **B-1** Proposer legacy/pipeline duplicated interpretation reader (§6.3.1).
  Real duplicate authority with three recorded drifts, **but** Step 10's own
  charter includes the proposer prediction-authoring grammar, so the typed
  reader is naturally that work's first move. Constraint for the Step-10 design:
  *any* evidence field Step 10 adds must be wired to both readers or explicitly
  declared pipeline-only.
* **B-2** Proposer direction-blindness (`proposal_helpers.py:88`; zero
  `MetricOrder`). Assigned Step-10 debt; the fix is the same 21-site migration
  09a already performed for the interpreter.
* **B-3** `evaluation.py` per-check-NAME tables (`:84-131`). Small file, clear
  boundary, already assigned to Step 10.
* **B-4** Launcher width (85 CLI args / 780-line `build_parser`). It grows with
  Step 10, but a parser is a legitimately wide, flat surface; decomposing it is
  not a precondition for correct binding.
* **B-5** Interpreter `run()`'s three record constructors and duplicate
  persistence blocks (§6.4). Genuine mixed ownership, **low** Step-10 touch.
* **B-6** Secondary-metric cache-carry asymmetry (§8.3) — a constraint Step 10
  must honour when it activates the transport.

### Class C — LATER CLEANUP (does not affect Step-10 ownership)

* **C-1** `nodes/interpretation_helpers.py` grab-bag + stale docstring (§6.5).
* **C-2** The duplicated 5 % band (§8.4).
* **C-3** `rendering.py`'s two non-rendering owners (round selection at
  `:220-222`; pool-total accounting at `:388-392`).
* **C-4** Dead `_MAX_REASONING_RETRIES` and the node `.md` that documents it as
  live (§6.3.3).
* **C-5** The two dead proposer reads (`per_file_comparison`,
  `efficiency_comparison`) and the interpreter synthesis prompt that still asks
  the LLM for both — a live, small cost paid every iteration.
* **C-6** `tools/ci_selection/resolver.py:5-8` and `manifest.py:8` both state
  *"Nothing here is wired into CI"* / *"This is not wired into CI"*. **It is** —
  `.github/workflows/ci.yml:~90` calls `python -m tools.ci_selection`. Stale
  docstrings on the module that decides what CI runs.
* **C-7** `dashboard/data_sources/local_json.py:245` direction literal.

---

## 10. Repository test inventory

### 10.1 Totals — MEASURED at the anchor

| quantity | value |
|---|---|
| **collected unit tests** (`pytest tests/unit --collect-only`) | **10,780** in 10.02 s |
| unit test modules (collected) | **580** |
| unit test files on disk | 718 `.py` under `tests/` |
| test physical LOC | 210,611 (1.65 × production) |
| **integration + manual** tests | **341** in 57 files — **not run by CI, by design** |
| conftest files | **5**, 670 LOC total |
| autouse fixtures | **4** (one `scope="session"`, `tests/conftest.py:140`) |
| golden/snapshot files | **108**, **646 KB total** |
| `pytest` config | `testpaths=["tests"]`, 3 markers, **no `addopts`, no xdist — serial** |

### 10.2 Distribution by subsystem — MEASURED

| directory | cases | share |
|---|---:|---:|
| `tests/unit/agent/` | 4,390 | 40.7 % |
| `tests/unit/core/` | 2,451 | 22.7 % |
| `tests/unit/execute_tools/` | 1,626 | 15.1 % |
| `tests/unit/sdsc_submission_scripts/` | 529 | 4.9 % |
| `tests/unit/scripts/` | 469 | 4.4 % |
| `tests/unit/ml_models/` | 276 | 2.6 % |
| `tests/unit/guardrails/` | 264 | 2.4 % |
| `tests/unit/workflows/` | 255 | 2.4 % |
| `tests/unit/examples/` | 204 | 1.9 % |
| `tests/unit/tools/` | 161 | 1.5 % |
| `tests/unit/agent_generated/` | 56 | 0.5 % |
| `tests/unit/dashboard/` | 44 | 0.4 % |
| `tests/unit/nodes/` | 34 | 0.3 % |
| root-level modules | 21 | 0.2 % |

### 10.3 Concentration — MEASURED

The suite is **flat**, not dominated by a few giant files. Largest modules:

| cases | module |
|---:|---|
| 124 | `tests/unit/guardrails/test_health_core_census.py` |
| 105 | `tests/unit/agent/prompt_templates/test_literature_review_prompts.py` |
| 104 | `tests/unit/scripts/test_c2_prephase_validation.py` |
| 91 | `tests/unit/workflows/test_model_exploration.py` |
| 87 | `tests/unit/core/test_failure_attribution.py` |
| 77 | `tests/unit/agent/evaluate_vram_skill/test_isolated_preflight.py` |
| 74 | `tests/unit/sdsc_submission_scripts/test_run_one_iteration.py` |

Median ≈ 18.6 cases/module; the largest module is 1.15 % of the suite. **No
single file is a runtime or ownership hotspot by count.**

### 10.4 Source-census population — DERIVED, upper bound

**90 test modules call `ast.parse`, containing 2,294 collected cases = 21.3 %
of the suite.** This is an **upper bound** on the "source census" population,
not a classification: a module that calls `ast.parse` once may contain many
ordinary behavioural tests. Per the project's own rule against heuristic test
classification, a per-case verdict requires reading each body, which this audit
did only for the specific cases it names (§14).

### 10.5 The always-on block — MEASURED, and it has grown

`manifest.py:22-28` declares five always-on paths, justified as "at ~134 cases
they are cheaper than the logic that would try". At the anchor they are
**294 cases** — 2.7 % of the suite, and **2.2× the documented figure**:

| cases | path |
|---:|---|
| 264 | `tests/unit/guardrails/` |
| 20 | `tests/unit/nodes/test_node_public_boundary.py` |
| 4 | `tests/unit/test_repo_hygiene.py` |
| 4 | `tests/unit/ml_models/test_registry_population_is_self_healing.py` |
| 2 | `tests/unit/agent/llm_bridge/test_all_calls_labeled.py` |

Within `guardrails/`, **`test_health_core_census.py` alone is 124 cases (47 % of
the block)** and runs on every PR regardless of the diff. At 2.7 % of the suite
the absolute cost is small; the observation is recorded because the *stated
justification* is now stale, not because the cost is material.

---

## 11. Runtime / CI topology

### 11.1 The only valid runtime authority is CI — and why

**Local wall-clock timing on this machine is unusable as evidence.** The host is
a shared 24-core box; during this audit `uptime` reported load average
**33.30 / 46.24 / 40.27**, driven mostly by *other users'* unrelated jobs
(a `3d_svm_search.py` at 816 % CPU and two `train_*.py` GPU jobs). A bounded
`pytest tests/unit --durations=100` run was launched, reached 80 % in 31
minutes — roughly **2× slower than the same suite on a 2-core GitHub runner** —
and was **deliberately stopped** rather than allowed to spend a further ~40
minutes producing a number that is neither reproducible nor comparable.

Consequences, stated honestly:

* **Per-file / per-fixture wall times are NOT AVAILABLE in this audit.** The
  `--durations` report prints only on completion, so the aborted run yielded
  none.
* This measurement **cannot change the Step-10 entry verdict** (§23): the
  structural findings are A on ownership grounds, and every test finding is B/C
  on grounds — headroom, fixture leanness, correct fail-closed selection — that
  are established independently below.
* One useful by-product: through 80 % of the suite (~8,600 cases) the local run
  showed **0 failures and 1 skip**, consistent with CI. The suite is green at
  the anchor.
* Note also that the harness reported this aborted run as "exit code 0" — the
  wrapper's status, not pytest's. The verdict above is read from the log.

### 11.2 CI wall time — MEASURED (run 32324124087, the Step-09b exact head)

| step | wall time |
|---|---:|
| Set up job + checkout + uv + Python | 7 s |
| Install dependencies (`uv sync --group dev --frozen`) | 43 s |
| **Lint — `ruff check`** | **1 s** |
| **Lint — `ruff format --check`** | **0 s** |
| **Type check — `pyright`** | **30 s** |
| **Resolve affected test suites** (the selector) | **0 s** |
| **Unit tests — `pytest`** | **999 s** |
| post steps | 2 s |
| **job total** | **1,084 s (18 m 04 s)** |

pytest's own summary line: `10745 passed, 32 skipped, 516 warnings in 993.31s
(0:16:33)`, with `full_suite=true`.

**`pytest` is 92 % of the CI job.** Lint + format + type-check together are
31 s — 2.9 %. Any conversation about CI cost is a conversation about the unit
suite and nothing else.

### 11.3 Trend and headroom — MEASURED + ESTIMATED

| run | head | pytest | job total |
|---|---|---:|---:|
| 32226620524 (08c) | `532035e6` | 900 s | 991 s |
| 32313798097 (09a) | `9d85f67b` | 931 s | 1,051 s |
| 32324124087 (09b) | `ce3b971d` | 999 s | 1,084 s |

*(job totals are not perfectly comparable — the dependency-install step varied
43–80 s between runs. The pytest column is the comparable one.)*

The job cap is `timeout-minutes: 25` = 1,500 s, already raised once from 15
(`ci.yml:20-38`). Headroom at the anchor: **416 s ≈ 27 %**. Growth ≈ **+33 s of
pytest per milestone** across the three measured points, i.e. roughly **12 more
milestones** before the current cap binds — **ESTIMATED**, from three points, and
the cap is itself raisable.

**Finding: CI wall time is not an imminent constraint, and no class-A test
finding can be justified on runtime grounds.**

### 11.4 Cost is extraordinarily concentrated: 12 tests run REAL training

This is the single most actionable runtime finding in the audit, and it was
obtained by a **bounded targeted run** — not a full-suite profile.

**MEASURED.** `pytest tests/unit -m "allow_real_subprocess"` collects
**12 of 10,780 cases (0.11 %)** and takes **382.66 s** on this host:

| seconds | test |
|---:|---|
| 65.43 | `execute_tools/test_pr07c_validation_envelope.py::TestTheClampInARealRun::test_comparability_is_unchanged_by_the_clamp` |
| 65.31 | `core/test_step07a_c2_transport.py::…::test_real_trainer_emits_r2_and_r3_over_the_validation_family` |
| 58.95 | `core/test_pr07c_validation_pricing.py::…::test_the_validation_evidence_reaches_the_runtime_session` |
| 56.64 | `core/test_pr07c_validation_pricing.py::…::test_a_pass_too_short_to_stabilise_yields_no_prediction` |
| 36.93 | `execute_tools/test_pr07c_validation_envelope.py::…::test_a_non_binding_ceiling_records_before_limit_equal_not_greater` |
| 36.05 | `…::test_no_ceiling_is_exact_parity` |
| 30.56 | `…::test_a_binding_ceiling_clamps_and_still_materializes_exactly` |
| 19.61 | `…::test_r3_over_a_partial_final_batch_is_sample_count_weighted` |
| 3.21 · 2.14 | `core/test_step06_c0_two_route_oracle.py` (real scoring child) |
| 1.55 · 1.53 | `execute_tools/test_step06_c3_subprocess_route.py` (real scoring child) |

**These run in CI.** The CI command is `pytest tests/unit/ -m "not real_run"`
(`ci.yml:94`); the marker here is **`allow_real_subprocess`**, a *different*
marker, declared in `pyproject.toml:56` as "this unit test intentionally
launches a real training/inference/scoring script". Nothing deselects them.

**They are a sanctioned exception, not a violation.** The project rule is that
unit tests mock every heavy subsystem; these carry an explicit opt-out marker
and their docstrings state the intent (`test_pr07c_validation_envelope.py:347`
is documented as "The REAL `train_engine_sandbox.py` subprocess, CPU, seconds").
The finding is not that they exist — it is **where they are scheduled**.

**How much of CI do they cost? Bounded honestly.** The 382.66 s figure is from
the contended host of §11.1 and **cannot be converted to a CI number** — a
2-core GitHub runner is slower per core but uncontended. What is solid:

* MEASURED: 0.11 % of the cases consume 382.66 s locally, with 8 tests at
  19–65 s each;
* MEASURED: they are not excluded from the CI lane;
* DERIVED: against a 993 s CI suite averaging 92 ms/test, a dozen tests doing
  real CPU training epochs are a materially concentrated cost;
* **UNKNOWN: their exact CI-side share.** Establishing it needs the CI-side
  `--durations` artifact proposed in §27 Q4. **ESTIMATED** at roughly a fifth to
  a third of the CI suite, stated as a range precisely because it could not be
  measured where it matters.

**This is the single largest available lever on validation cost, and pulling it
removes no evidence** — moving a marked lane into its own CI job is a
*scheduling* change, not a coverage reduction.

> **RESOLVED (operator, 2026-08-20 — Q5 = A).** The split is **approved
> unconditionally**, and the draft's "measure the CI-side share first" condition
> is **removed**: these tests are not ordinary unit tests, and that alone
> justifies the lane. Target topology and constraints are frozen in §20.2; the
> CI-side share remains UNKNOWN and is answered by the same follow-up (Q4), not
> a precondition for it.

---

### 11.5 What actually drives suite cost — the four categories, ranked

The mandate asks this directly. Ranked on the evidence above:

| rank | category | verdict |
|---|---|---|
| **1** | **(D) legitimately expensive evidence** | **Dominant and concentrated.** 12 cases (0.11 %) running real training/scoring = 382.66 s locally (§11.4). Remedy is *scheduling*, never mocking — Q5. |
| 2 | **(B) expensive setup topology** | **Small but real and free to fix.** Zero caching under `tests/` while 18 modules walk the tree uncached (§12.1); ~10–15 s ESTIMATED. The conftest/autouse layer itself is lean (§12). |
| 3 | **(A) duplicate semantic ownership** | **Rank 3 by cost, rank 1 by RISK.** The census overlaps (§14.2a–c, §15) are worth ~seconds; their real cost is divergence — and two have already diverged. |
| 4 | **(C) over-broad selection** | **Correct behaviour, not debt.** 9/10 milestone PRs run everything, but §18.4 shows the hub declarations are justified and must not be narrowed. |

**It is not driven by test COUNT.** 10,780 cases at a 92 ms CI average is not
the problem; a dozen of them doing real epochs is.

---

## 12. Fixture / setup-cost analysis

**MEASURED.** The setup topology is lean, and this is the clearest evidence
against "expensive setup" as a dominant cost:

* **5 conftest files, 670 LOC total** — `tests/conftest.py` (324),
  `tests/unit/conftest.py` (110), and three directory conftests (92 / 78 / 66).
* **4 autouse fixtures in the entire suite**, one of them `scope="session"`
  (`tests/conftest.py:140`, whose docstring states it is session-scoped
  precisely "so the protection does not depend on" per-test setup).
* `tests/unit/conftest.py:64` installs the autouse
  `forbid_real_heavy_subprocess` guard — a *cheap* guard, and the reason
  `tests/unit/conftest.py` is a declared full-suite trigger.
* **The one known expensive-setup defect in this area is already fixed and
  documented in production source**: `tools/ci_selection/resolver.py:160` and `:177-180`
  memoize the edge scan with `@lru_cache(maxsize=1)`, with the comment that the un-cached
  version "turned this module into 100s of the very suite it exists to shrink".
  That is the project catching and fixing this class itself.

**Not measurable in this audit:** per-module fixture cost (torch model
construction, dataset materialization, YAML/JSON parsing inside module-level
fixtures) — see §11.1. The `execute_tools/` band was observably the slowest
region of the aborted local run (the 75–80 % plateau fell in
`tests/unit/execute_tools/test_step02*`, the SampleSet / dataset-profile
family), which is **suggestive, ESTIMATED, and not a basis for any
recommendation here.**

### 12.1 The one measurable setup inefficiency: uncached repeated tree walks

**MEASURED.** `grep` over the whole test tree finds **zero** occurrences of
`lru_cache` or `functools.cache` anywhere under `tests/`, while **18 test
modules** perform a full `rglob("*.py")` walk of the production or test tree —
three of them twice in the same module
(`test_step09a_c2_metric_spec_contract.py`, `test_pr07c_capability_routing.py`,
`test_c2_prephase_validation.py`).

This is *exactly* the pattern production already fixed and documented:
`tools/ci_selection/resolver.py:160` / `:177-180` memoize the identical scan
because "recomputing it per test turned this module into 100s of the very suite
it exists to shrink". The census family under `tests/` never adopted the fix.

A single session-scoped, cached `parsed_production_tree()` /
`parsed_test_corpus()` fixture in `tests/helpers/` would remove every repeat at
**zero evidence loss** — no assertion changes, no coverage changes. The
recoverable wall time is **ESTIMATED at roughly 10–15 s** and could not be
measured cleanly here (§11.1). Class **C**: worth doing, small, and not
Step-10-entry-critical.

### 12.2 Autouse fixtures are cheap but function-scoped

`tests/unit/conftest.py:64 forbid_real_heavy_subprocess` is autouse and
function-scoped, so it constructs a fresh closure and a fresh `_GuardedPopen`
subclass for each of the 10,780 cases. It **cannot** be session-scoped as
written (it reads `request.node` for the marker and the failure message), and
the per-test cost is small. Recorded for completeness, **not** recommended for
change: the guard's correctness is worth more than the microseconds.

---

## 13. Invariant → test-owner map

**Method note.** The counts below are `grep`-based *touch* counts — modules
whose text mentions the concept — and are therefore an **upper bound on
ownership, ESTIMATED**. They locate candidate families for §14; they are not
per-test verdicts. Files overlap between rows.

| invariant | modules touching | cases | primary behavioural owner | independent structural owner | expensive/real owner | assessment |
|---|---:|---:|---|---|---|---|
| Metric direction / `MetricOrder` | 38 | 795 | `tests/unit/execute_tools/test_metric_order.py` | `…/test_step07b_c2_order_consumers.py` (tuner, declared directory-scan) + `…/test_step09a_c3_order_consumers.py` (interpreter) — **AST censuses over disjoint surfaces** | Gate 1 (09b) | **KEEP all three** — the two censuses scan different node families; the behavioural owner tests the authority itself |
| `MetricSpec` single authority | 26 | 470 | `…/test_step09a_c2_metric_spec_contract.py` | 09a's executable census over every production module (zero new `derive_tidmad_metric*` sites) | — | KEEP |
| Health verdict / applicability | 21 | 519 | `tests/unit/execute_tools/health_checks/` | `tests/unit/guardrails/test_health_core_census.py` (124 cases, always-on) | Gate 2 (08a/08b/08c) | KEEP; the always-on placement is worth an operator decision (§27 Q3) |
| Task-free framework prompts | 18 | 334 | `…/test_step09b_c2_task_blocks.py` | the same file's two-directional census (banned in template / required in the TIDMAD-assembled prompt) | Gate 1 (09b PASS) | KEEP |
| Prediction v1 / v2 partition | 8 | 308 | `…/test_step09a_c4_prediction_semantics.py`, `…/test_step09b_c4_prediction_rendering.py` | source-string scan (**weak — see §14.1**) | — | **one member CONSOLIDATE/UPGRADE** |
| Resume / `RestoredState` continuity | 9 | 315 | `tests/unit/core/test_resume.py` (70 cases) | `tests/unit/core/test_step09a_c5_prediction_transport.py` | — | KEEP |
| `ModelIOContract` | 19 | 312 | `tests/unit/agent/schemas/` | `examples/*/declared/model_io_contract.json` round-trip | Gate 2 | KEEP |
| `TaskDataPath` genericity | 9 | 98 | `tests/unit/execute_tools/test_*_data_path.py` | `tests/unit/guardrails/test_task_data_path_census.py` (5 cases) | Gate 2 (D14 ×3 tracks) | KEEP |
| Secondary-never-orders (Q-09-7 = B) | 6 | 97 | 09a/09b builder tests asserting the builder never populates | — | — | KEEP until Step 10 flips it |
| No production dependency on `examples/` | 11 | 175 | `tests/unit/examples/test_pack_governance.py` | maturity-pinned governance guards | — | KEEP |

**Shape assessment.** For every high-fanout framework invariant the repository
already has the target shape: **one cheap behavioural owner + at most one
structural owner catching a genuinely different failure mode + expensive Gate
evidence only where cheaper layers cannot reach.** The two `*_order_consumers`
censuses are *not* duplicates — they scan disjoint node families
(`nodes/ml_hyperparameter_tune_agent/` vs the interpreter), and the tuner one is
explicitly listed in `manifest.py:86-89` as a directory scan because it reaches
its target through a computed `importlib` name that the AST cannot resolve — a
gap found "by the mutation oracle, not by review".

---

## 14. Duplicate test / failure-class analysis

Only findings established by **reading the test body** are listed. No verdict
below is derived from a filename or an AST heuristic.

### 14.1 `test_the_proposer_calls_the_same_renderer` — a scan that pins the path production does not take

`tests/unit/agent/result_interpretation_agent/test_step09b_c4_prediction_rendering.py:169-175`:

```python
def test_the_proposer_calls_the_same_renderer(self):
    source = (REPO_ROOT / "nodes/ml_model_proposal_agent/ml_model_proposal_agent.py").read_text()
    assert "render_prediction_track_record" in source
    assert "sum(pred_hist.values())" not in source
```

*Invariant it appears to own:* the proposer renders the version-aware prediction
track record through the single shared authority.
*What it actually asserts:* that a substring occurs in a file.
*Verified consequence (§6.3.1):* the only proposer call site is at `:1157`,
inside `_build_reasoning_prompt` — the **legacy** path. Every shipped
`llm_configs/*.json` and the `--provider/--model_id` path resolve to
`ProposalLLMConfig`, so **production takes the pipeline path**, where the
versioned fields are forwarded as raw JSON (`:1668-1694`) by deliberate design.
No test under `tests/unit/agent/ml_model_proposal_agent/` references
`prediction_pool_sizes` or `prediction_evaluation_semantics` (MEASURED).

**Verdict: UPGRADE, not delete.** The surviving owner must be a behavioural
test asserting that the versioned prediction evidence reaches the assembled
prompt **in pipeline mode**. The existing scan may remain as the legacy-path
guard. *This is a test-ownership finding; the underlying two-transport design is
deliberate and is NOT a defect (§26, item 7).*

### 14.2 A test pinning an unreachable production branch

`tests/unit/agent/ml_model_proposal_agent/test_proposal_agent.py:424-433` builds
a hand-made dict containing `per_file_comparison` / `efficiency_comparison` and
asserts the proposer renders them. `InterpretationOutput` declares **neither**
field (verified against the schema at the anchor), and production always fills
`ProposalInput.interpretation` from `output.model_dump()`. The test therefore
guards a branch production cannot execute.
**Verdict: SUPERSEDED-pending — it must not be deleted before the dead
production branch is (Step 10, §9 B-1/C-5).** Deleting the test first would
remove the only signal that the branch exists.

### 14.2a The direction censuses — one class, three implementations, one materially weaker

**MEASURED, by reading all three scanners.** Three censuses guard "no bare
extremum / no direction literal over the golden metric":

| file:line | surface | mechanism |
|---|---|---|
| `tests/unit/execute_tools/test_step06_c5_boundary_and_structure.py:113` | 8 production dirs | executed `"higher"`/`"lower"` **string literals**, pinned as exact multisets |
| `…/result_interpretation_agent/test_step09a_c3_order_consumers.py:617` | 6 interpreter files | **AST** `Compare`/`max`/`min`/`sorted` over score tokens |
| `…/tune_ml_hyperparam_agent/test_step07b_c2_order_consumers.py:499` | tuner node source | **line-substring regex** |

`test_step06_c5` owns a genuinely different thing (the *literal*, not the
comparison) — **KEEP**. The other two own the same failure class with very
different strength:

* **09a-C3 is the strong one.** It parses AST, and it is anti-vacuous three
  ways: `assert consumers >= 12` (`:660`) plus **two planted offenders**
  (`:664`, `:669`).
* **07b-C2 is a weaker re-implementation.** Verified at `:508-513`:
  ```python
  offenders = [
      line.strip()
      for line in _TUNER_SOURCE.splitlines()
      if re.search(r"\b(max|min|sorted)\s*\(", line) and "denoising_score" in line
  ]
  ```
  It scans **line by line**, so a `max(` whose `denoising_score` key sits on the
  next line — the shape `ruff format` produces for any long call — **escapes it
  silently**. Its neighbour at `:517` pins an exact source line
  (`assert "sorted_finals = sorted(all_same_loss_finals)" in _TUNER_SOURCE`),
  which goes red on a pure reformat or a variable rename while the defect it
  guards is unchanged.

**Verdict: CONSOLIDATE — surviving owner is 09a-C3's AST scanner, parameterized
over both node surfaces.** This *strengthens* the tuner's coverage rather than
reducing it, and it is the one consolidation in this audit that closes a real
escape rather than merely saving time. Class **B/C** — it is not
Step-10-entry-critical, but Step 10 migrates the workflow/resume direction
literals and will want the stronger scanner pointed at the new surface.

### 14.2b A census with no anti-vacuity guard

`tests/unit/guardrails/test_task_data_path_census.py` scans production for task
identity, but `_production_files()` at `:65-69` **silently skips a root that
does not exist** (`if base.exists():`), and the file contains **no assertion
that the scanned set is non-empty**. Its `assert _count_calls(...) >= 1` guards
(`:122-142`) belong to the separate reachability tests, not to the census.

Compare the guards that *do* exist elsewhere —
`test_no_self_referential_expectations.py:164`
(`assert len(list(TESTS_ROOT.rglob("test_*.py"))) > 100`),
`test_no_test_executes_a_launcher.py:357` (`assert with_spawns >= 10`),
`test_node_public_boundary.py:81`, and 09a-C3's `assert consumers >= 12`. The
repository clearly knows the pattern; this census just does not use it.
**Verdict: KEEP and UPGRADE** — add a non-vacuity count. Class **C**.

### 14.2c The scanned "production surface" is declared three times, with three different answers

**MEASURED:**

| file:line | dirs |
|---|---|
| `tests/unit/execute_tools/test_step06_c5_boundary_and_structure.py:44` | 8 — `nodes, agent, core, execute_tools, ml_models, workflows, scripts, dashboard` |
| `tests/unit/nodes/test_node_public_boundary.py:42` | 7 — the same minus `ml_models` |
| `…/test_step09a_c2_metric_spec_contract.py:435` | 6 — the same minus `ml_models` **and `scripts`** |

The 09a-C2 omission of `scripts` is **deliberate and documented** (`:475-484`
proves the calibration fixture under `scripts/` is unreachable) — which is
precisely why the *undocumented* divergences are the hazard: nothing tells a
reader which list is the real production surface, and a new top-level
production directory joins some censuses and not others.
**Verdict: CONSOLIDATE to one declared constant with per-census documented
subtractions.** Class **C**.

### 14.3 Families investigated and found NOT redundant

Recorded so a later cleanup does not re-open them:

* **`test_step07b_c2_order_consumers.py` vs `test_step09a_c3_order_consumers.py`** —
  disjoint scanned surfaces (tuner vs interpreter). **KEEP both.**
* **Unit + census pairs generally** — the censuses catch a *structural*
  regression (a new literal, a new derivation site, a moved authority) that no
  behavioural test can see, and CLAUDE.md's "test the concept, not the field"
  rule exists precisely because ten cross-schema divergences survived a
  6,900-test suite without them. **KEEP.**
* **The three-task L1 rungs** (TIDMAD higher-is-better · Pets accuracy · DAVIS
  `mse` lower-is-better) — these are *independent adversarial direction
  classes*, not mechanical repetition, and 09b's Gate 1 designated correctly in
  both regimes precisely because they exist. **KEEP.**
* **108 golden files / 646 KB** — small, and byte identity is the contract for
  the prompt families (07b's PB sha, 09b's byte-exact template move). **KEEP.**

### 14.4 What this audit did NOT establish

A repository-wide per-test duplicate-ownership verdict was **not** produced.
Doing it correctly requires reading ~10,780 test bodies, and the project's own
rule forbids the shortcut (AST scan + file-level recipe propagation). The six
findings above (§14.1, §14.2, §14.2a, §14.2b, §14.2c, and §15's V-items) are the
ones this audit read and can defend; the census family was covered
comparatively thoroughly, the behavioural families were not. **Any future test
consolidation must therefore begin with its own per-family reading pass, not
with this document's counts** (§22).

---

## 15. Census / source-scan analysis

**Population:** 90 modules / ≤ 2,294 cases (§10.4).

**Assessed strengths — these are the repository's strongest regression layer,
and Steps 08–09 repeatedly prove it:**

* `manifest.py:84-89` records that the tuner order-consumer census was added to
  `DIRECTORY_SCANS` because the mutation oracle — not review — found that a
  `policy.py` change would otherwise not have run it.
* 09a's single-authority census over every production module is what pins "zero
  new `derive_tidmad_metric*` sites"; 09b's two-directional prompt census is
  what makes a new task-science sentence in `rendering.py` go red.
* 08c's health-core census (124 cases) is the always-on structural owner for the
  check family.

**Assessed weaknesses — two, both narrow:**

1. **Substring scans can be satisfied by the wrong code path** — §14.1 is the
   worked example. A census that asserts `"name" in source` proves presence, not
   reachability. The repository already knows this pattern
   (`tests/unit/guardrails/test_preflight_production_reachability.py` exists
   precisely to prove a guard is called); the prediction-rendering scan simply
   was not built that way.
2. **A moved file can silently escape a census** whose scanned root is a
   literal path. The `nodes/*.py` flat modules (§16) are a live instance of the
   inverse problem: `tests/unit/nodes/test_node_public_boundary.py:44-51` only
   iterates *directories* under `nodes/`, so `interpretation_helpers.py`,
   `proposal_helpers.py`, `scoring_reference.py` and `agent_data_stream.py` are
   outside the node public-boundary rule entirely. **MEASURED.**

3. **The same invariant is scanned by three different mechanisms with three
   different token vocabularies** — "the framework never spells a task name" is
   implemented in `guardrails/test_task_data_path_census.py:62` (AST comparands
   only, tokens `{tidmad, pet, pets, davis}`),
   `guardrails/test_health_core_census.py:72` (names + imports + non-docstring
   strings, tokens `("tidmad","pets","davis","oxford","acme")`) and
   `…/test_step09b_c2_task_blocks.py:390` (string literals only, regex
   `tidmad|pets|davis`). The **rosters** are legitimately different — each owns
   a different surface. The **mechanisms** should not be: the health census's
   `_code_level_names()` (`:106`) is strictly the most complete, and the
   data-path census's comparand-only scan means a `TASK_MAP["tidmad"]` on the
   data-path surface passes there while failing under either of the other two.
   **CONSOLIDATE the scanner into `tests/helpers/`, keep the three rosters.**
   Class **C**.

**Positive finding: no two censuses were found scanning the same surface for
the same invariant** — the overlaps above are same-*concept*, different-surface
or different-mechanism, and the strong ones (09a-C3, `test_health_core_census`)
are the pattern the weaker ones should be migrated to, not removed in favour
of.

---

## 16. Golden / snapshot analysis

**MEASURED:** 108 files, **646 KB**, across 11 `goldens/` directories:

| files | directory |
|---:|---|
| 16 | `tests/unit/agent/ml_model_implementor/goldens` |
| 15 | `tests/unit/agent/result_interpretation_agent/goldens` |
| 14 | `tests/unit/agent/ml_model_proposal_agent/goldens` |
| 13 | `tests/unit/agent/tune_ml_hyperparam_agent/goldens` |
| 10 | `tests/unit/agent/ml_literature_review/goldens` |
| 6 | `tests/unit/agent/llm_bridge/goldens` |
| 5 | `tests/unit/execute_tools/health_checks/goldens` |
| 4 each | `workflows`, `execute_tools`, `ml_code_validator_agent` |

**Assessment: goldens are not a cost problem and mostly not an ownership
problem.** 646 KB of byte comparison is negligible against a 993 s suite, and
byte identity *is* the contract for the prompt families (07b's planner/reflector
PB sha256; 09b's byte-exact template relocation; 09a's C1a differential oracle
proven BYTE-IDENTICAL across a 21-site migration).

**One structural observation, not a recommendation:** the proposer's 14 goldens
pin **both** the legacy and pipeline prompt surfaces (`pb3_*` pipeline
system+user, `pb4_legacy_commit_*`, `s1e_legacy_reasoning_system.txt`). If Step 10
consolidates the duplicated reader (§9 B-1), the golden set is part of that
decision and must be dispositioned explicitly — which of the two surfaces
survives is a design choice, not a regeneration.

---

## 17. Parameterization / matrix analysis

Not separately quantified beyond §10.3 — the suite's flatness means no single
parameterized expansion dominates. The one substantive point is a **preservation
rule, not a consolidation opportunity**: the contrasts this project deliberately
maintains — higher vs lower direction, positive vs negative reference value,
scalar-only vs per-sample metric, task blocks present vs absent, v1 vs v2
semantics, valid vs fail-closed — are *independent adversarial classes*. §14.3
records them as KEEP. Collapsing any of them into one parameterized case would
delete the exact contrast that made 09a's sign-degenerate-band defect and 09b's
two-regime Gate 1 detectable.

---

## 18. Selective-CI analysis

### 18.1 What the selector actually does — read from source, not inferred

`.github/workflows/ci.yml:80-116`: PRs run the selector; **`push` to master,
the nightly `schedule` and `workflow_dispatch` run everything by policy**; every
failure mode in the shell wrapper falls back to the full suite with `exit 0`, so
a broken selector can never fail the build or skip tests.
`tools/ci_selection/resolver.py:218-319` is fail-closed by construction: there is
no code path returning an empty selection for a non-empty diff.

### 18.2 In practice, the selector is inactive for framework work — MEASURED

Replaying the **real diffs of the last 10 milestone squashes** through the
selector at the anchor:

| squash | milestone | outcome | reason |
|---|---|---|---|
| `e9a1f9fb` | 09b | **FULL** | `agent/schemas/interpretation.py`: declared hub |
| `4cf38dec` | 09a | **FULL** | `agent/schemas/hyperparam_tuning.py`: declared hub |
| `3f4effb5` | 08c | **FULL** | an `examples/**/*.csv`: not in `known_production` → failing closed |
| `13e28796` | 08b | **FULL** | `tests/helpers/…`: infrastructure trigger |
| `7da1e45e` | 08a | selective (69 paths) | — |
| `4db414b5` | D14 | **FULL** | `tests/helpers/…`: infrastructure trigger |
| `a15d1366` | 07-correction | **FULL** | `tests/helpers/…`: infrastructure trigger |
| `9ea3755f` | 07b | **FULL** | `agent/schemas/…`: declared hub |
| `65804b3d` | 07a | **FULL** | `agent/schemas/…`: declared hub |
| `79403b44` | PR0 | **FULL** | `.gitignore`: no inbound edge and no manifest rule |

**9 of 10 milestone PRs run the full suite.** Three distinct causes: declared
hub (4), `tests/helpers/` trigger (3), unmapped non-`.py` path (2).

**Method caveat.** This is a replay of *historical diffs* through *today's*
selector and edge graph, so it answers "what would a diff of this shape do
now", not "what happened then". It is validated at one point: for `e9a1f9fb`
(09b) the replay says FULL SUITE for the reason
`agent/schemas/interpretation.py: declared hub`, and the **actual** CI log of
run 32324124087 prints exactly that reason and `full_suite=true`. The CI logs
for the other nine runs have expired and could not be checked. Treat the 9/10
figure as **DERIVED**, with one MEASURED confirmation.

### 18.3 Would it help Step 10? — MEASURED simulation

Hypothetical Step-10 diffs, replayed through the real selector:

| diff | outcome |
|---|---|
| `workflows/model_exploration.py` | selective — **39 / 580** modules |
| `+ core/resume.py` | selective — **53 / 580** |
| `+ sdsc_submission_scripts/run_one_iteration.py` | selective — **73 / 580** |
| `+ agent/schemas/interpretation.py` | **FULL SUITE** |
| `execute_tools/health_checks/evaluation.py` alone | selective — 43 / 580 |

Step 10's *core* surfaces select beautifully (73 of 580 modules). But Step 10
owns secondary-metric transport, orchestration inputs to resume and task
binding — all of which touch `agent/schemas/`. **Step-10 CI should be expected
to run the full suite, ≈ 999 s per push.**

### 18.4 The hub declarations are CORRECT and must not be narrowed — MEASURED

This audit initially suspected the `HUBS` list was over-broad: `manifest.py:33-37`
justifies it with "`agent/schemas/hyperparam_tuning.py` alone selects ~4,059 of
9,697 cases", "`execute_tools/dataset_config.py` ~59 %", "`records.py` ~3,351",
and the **depth-1** reach measured at the anchor is far lower. Measuring both
models settled it:

| file | depth-1 reach | **transitive reach** | manifest's figure |
|---|---:|---:|---|
| `agent/schemas/hyperparam_tuning.py` | 16.9 % | **48.4 %** | ~42 % |
| `execute_tools/dataset_config.py` | 12.9 % | **76.3 %** | ~59 % |
| `core/runtime_control/records.py` | 4.4 % | **50.2 %** | ~35 % |
| `execute_tools/scoring_utils.py` | 3.5 % | **67.6 %** | — |
| `core/runtime_control/estimate_types.py` | 4.5 % | **41.6 %** | — |
| `agent/schemas/interpretation.py` | 7.6 % | **27.4 %** | — |

The selector's edge model is **depth-1** (it does not follow
production→production imports, `resolver.py:274-280`), while a change's real
blast radius is **transitive**. Every declared hub reaches 41–76 % of the suite
transitively, and the manifest's figures are of the right order. **The `HUBS`
list is a correct, deliberate over-approximation compensating for a depth-1
edge model — narrowing it would be exactly the "weaken fail-closed selection for
speed" move this audit is forbidden to recommend.** Recorded as a CORRECTED
adversarial item (§26, item 3).

### 18.5 Consequence for the audit

Because selection is correct and cannot be improved without weakening it,
**selective CI is not a lever on Step-10 iteration cost.** The only legitimate
levers are the unit suite's own composition (§14, where this audit can defend
exactly two findings) and accepting the cost. Given §11.3's 27 % headroom, the
honest recommendation is **accept it**.

---

## 19. Test-topology A / B / C triage

### Class A — PRE-STEP-10 BLOCKER: **NONE** — FROZEN

> **TEST-TOPOLOGY PRE-STEP-10 BLOCKER: NONE.** Confirmed by the operator
> (2026-08-20). No broad duplicate-test cleanup is justified before Step 10, and
> **no prerequisite cleanup may be manufactured** merely because
> `tests = 10,780`, test LOC exceeds production LOC, or CI takes ~16.5 minutes.

No test finding meets the bar. The concrete reasons, each independently
sufficient:

* runtime is 16 m 33 s with **27 % headroom** and grows ~33 s/milestone (§11.3);
* setup topology is lean — 5 conftests, 4 autouse fixtures (§12);
* selection is correct and fail-closed, and its over-approximation is
  **vindicated** by transitive measurement (§18.4);
* goldens total 646 KB (§16);
* the suite is flat — the largest module is 1.15 % of it (§10.3);
* and the audit could defend only **two** duplicate/weak-ownership findings by
  reading test bodies (§14), neither of which Step 10 amplifies.

**"Many tests" is not evidence of debt, and this audit declines to manufacture a
class-A finding from a count.**

**Why §11.4's real-training concentration is still not class A.** It is the
largest runtime lever in the repository and it is MEASURED — but class A
requires that **Step 10 would materially deepen it**, and Step 10 adds workflow,
resume and launcher semantics, not new real-training unit tests. The finding is
a standing validation-economy question (Q5), independent of Step-10 entry, and
its remedy is a CI *scheduling* change that this audit is not authorized to
make and that removes no evidence. Classifying it A would be using the Step-10
gate to force through an unrelated CI decision.

### Class B — STEP-10-OWNED / FORWARD CONSTRAINT

* **TB-1** §14.1 — the prediction-rendering ownership gap. Step 10 owns the
  proposer prediction-authoring grammar; the behavioural pipeline-mode owner
  should land with it.
* **TB-2** §14.2 — the test pinning an unreachable branch. It is retired *by*
  Step 10 removing the branch, in that order.
* **TB-3** §16 — the proposer's 14 goldens pin both duplicated prompt surfaces;
  their disposition is part of any reader consolidation.
* **TB-4** §14.2a — the tuner's line-based direction census (`:508-513`) should
  be replaced by 09a-C3's AST scanner. Step-10-adjacent: Step 10 migrates the
  workflow/resume direction literals and will want the stronger scanner aimed
  at the new surface. **This is a coverage upgrade, not a reduction.**

### Class C — LATER CLEANUP

* **TC-1** §10.5 — `manifest.py:19-21`'s "~134 cases" is now 294; a stale
  justification on a correct rule.
* **TC-2** §15 weakness 2 / §16 — the four flat `nodes/*.py` modules sit outside
  `test_node_public_boundary.py`'s scope.
* **TC-3** §9 C-6 — `resolver.py:5-8` and `manifest.py:8` both claim the selector
  is "not wired into CI". It is.
* **TC-4** §11.1 — the repository has **no reproducible runtime baseline** that
  is independent of a shared, contended host. If runtime ever *does* become the
  question, the answer must come from a CI-side `--durations` artifact, not from
  a developer box.
* **TC-5** §14.2b — `test_task_data_path_census.py` has no anti-vacuity guard
  and silently skips a missing root; a new production top-level directory
  escapes it. UPGRADE with a non-vacuity count.
* **TC-6** §14.2c — three disagreeing `PRODUCTION_DIRS` declarations; only one
  divergence is documented.
* **TC-7** §15 item 3 — three different scanner mechanisms for "the framework
  never spells a task name"; consolidate the mechanism, keep the rosters.
* **TC-8** §12.1 — zero caching under `tests/` while 18 modules walk the tree
  uncached; production already solved this in `resolver.py`.

---

## 20. Required prerequisite work — **Step 09.5a** (FROZEN)

**One prerequisite milestone. It is structural, not test-topology.** Approved by
the operator (Q1 = A).

A-1 and A-2 (§9) share **one** semantic boundary — *run-scoped state that is
restored, carried across iterations, and persisted* — so they are one milestone,
not two. Splitting them would put the producer and the consumer of the same
carrier in different PRs.

> **Milestone identity: `Step 09.5a — Workflow Run-State Structural
> Prerequisite`.** It is deliberately **not** called "Step 10a": it exists
> because Step 09.5 blocks Step 10, and it owns no Step-10 semantics. *PR-X* is
> retained below only as an explanatory alias.

### 20.1 Step 09.5a — semantic contract (frozen at the semantic level ONLY)

| field | content |
|---|---|
| **semantic owner** | workflow run-scoped authorities/bindings **+** restored/carried/persisted exploration-chain state |
| **production surfaces** | `workflows/model_exploration.py` (`run_workflow` signature and its `:1974-2069` state block), `core/resume.py` (the four `load_latest_*` loaders + `RestoredState`), the three `run_workflow` call sites, `sdsc_submission_scripts/run_one_iteration.py` (kwarg assembly only) |
| **shape (A)** | ONE authoritative committed-interpretation-digest read path replacing the four duplicated read/parse/soft-fail implementations. Projections may differ by **digest key · validator · merge rule** and nothing else. **The old loaders must not survive as active wrappers around four copies of the same authority.** |
| **shape (B)** | typed **immutable** run-scoped authority/binding carrier(s) **and** a typed **mutable** exploration-chain state carrier — separate types, following the tuner's landed `RunBindings` / `AttemptStage` precedent |
| **shape (C)** | one obvious `run_workflow` orchestration entrypoint; **atomic migration** of every current repository caller to the new typed boundary |
| **explicit NON-goals** | no secondary-metric production transport · no `vocab_link_confirmations` carry · no direction-literal migration · no `evaluation.py` Health table cleanup · no proposer prediction-authoring repair · **no plugin-registry cleanup (Q2 = B)** · no generic composition root · no task loader/registry · no new registry or loader subsystem · no Step-12 semantics · no prompt bytes |
| **invariants that must not move** | see §22 — operator-facing and persisted contracts. The **Python call signature of `run_workflow` is explicitly EXCLUDED from this list** and is expected to change (amendment B). |
| **required parity evidence** | a differential PRE/POST oracle over the persisted artifacts of a bounded pseudo-mode chain run, deep-equal; an importer/caller census for `run_workflow` and every `load_latest_*`; a reachability test that fails if the production path bypasses the new reader; the executable ownership guard of §20.1a; `pyright` over the extracted units |
| **Step-10 work it unlocks** | launcher-owned task binding lands on a carrier instead of parameter #100; the two new carried items cost one declaration each instead of a fifth and sixth loader; workflow/resume direction literals become a two-site migration against `MetricOrder`, which `model_exploration.py:108` already imports |

**Frozen at the semantic level only.** The Step-09.5a child design must re-read
source and freeze for itself: exact module names, exact class names, the exact
carrier field lists, and the exact number of extracted units. **This audit
freezes none of those.**

### 20.1a AMENDMENT A (operator, FROZEN) — the carrier is a semantic boundary, NOT a parameter bag

The single largest failure mode available to Step 09.5a is to declare victory
after moving 99 arguments into one dataclass. **That is explicitly forbidden:**

```python
@dataclass
class RunBindings:
    # ...all 99 run_workflow arguments copied here...   # <-- NOT a decomposition
```

The child design **MUST** perform a **field-by-field ownership audit** of every
current `run_workflow` input and every loop-carried local, classifying each into
at least:

| class | meaning |
|---|---|
| **A** | immutable run-scoped authorities / bindings |
| **B** | mutable restored / carried / persisted chain state |
| **C** | launch or runtime controls and configuration that belong to their proper owner and must **not** become "bindings" |
| **D** | services / resources whose owner is elsewhere |
| **E** | ordinary local or derived values that must **not** become carrier fields at all |

The tuner's `RunBindings` / `AttemptStage` precedent is **semantic, not
cosmetic**: immutable bindings and mutable state are separate types, and the
separation is enforced at construction. Step 09.5a must carry an **executable
ownership guard** analogous in intent to `FORBIDDEN_BINDING_FIELDS`, so mutable
chain state cannot later leak back into the immutable bindings.

**Acceptance is fewer mixed owners and lower change amplification — never
"99 parameters became one parameter object".**

### 20.2 Non-blocking follow-up — CI validation-topology maintenance (Q4 + Q5)

Recorded here as an approved future item. **Not implemented by this audit, not
part of Step 09.5a, and not a Step-10 gate.** It may proceed independently or in
parallel.

Approved scope, as ONE small CI-only maintenance PR:

* the deterministic unit job **explicitly excludes** `allow_real_subprocess`;
* a **parallel** real-subprocess evidence job runs exactly that marker family;
* both lanes emit a preserved / machine-readable `--durations` artifact, giving
  future runtime audits a reproducible CI-side baseline (§11.1, TC-4);
* **every current real test is preserved** — nothing is deleted, mocked,
  weakened, or relabelled as synthetic evidence;
* fail-closed selective-CI behaviour is unchanged (§18.4).

Its purpose is **scheduling and observability, not coverage reduction.**

### 20.3 Gate disposition for Step 09.5a — FROZEN by operator ruling

The default assignment in `docs/gates/gate_testing_standard.md:446-452` is
*"New agent node or workflow wiring → Gate 1"* and *"Checkpoint (end of
feature) → Gate 2"*, and `manifest.py:120` independently advises
`("gate1", "gate2-at-checkpoint")` for `workflows/`. The operator has tightened
this for Step 09.5a specifically, on validation-economy grounds:

| gate | disposition |
|---|---|
| **Gate 1** | **NOT REQUIRED — *if* Step 09.5a proves exact LLM-facing parity.** Step 09.5a is a behaviour-preserving state/workflow decomposition and owns no prompt or LLM semantics, so a real-LLM run would add no new failure-class evidence. The waiver must be earned by a differential oracle/manifest strong enough to detect movement in: **prompt bytes · LLM call labels · LLM call order and count · LLM-facing structured inputs**. **If that exact parity cannot be proven, Gate 1 automatically becomes REQUIRED.** |
| **Gate 2** | **REQUIRED**, once at the final executable head. Reason: the resume / cross-iteration state lifecycle is materially changed. Temporal depth **≥ 2 iterations**, per the standard's table (`:262-267`, *"cross-iteration behaviour or resume → ≥ 2 iterations"*). The child design defines the exact bounded input and acceptance criteria, preserving cold-start, the DS8-mandatory `--data_scope` + `--health_gate_files` pairing, `--llm_config openai_tiered_pro.json`, and bounded runtime/cost. |

**No Gate was run by this audit session, and none may be run to freeze it.**

**No test-topology prerequisite PR is required** (§19). TB-1…TB-4 travel with
the Step-10 work that owns their production surfaces; TC items go to later
cleanup or to §20.2.

---

## 21. Quantitative baseline

The Step-09.5 baseline, for measuring any future cleanup against. Labels are
per §3.

| metric | value | label |
|---|---|---|
| audit anchor | `85fa4b74` | MEASURED |
| production Python files | 333 | MEASURED |
| production physical LOC | 127,402 | MEASURED |
| production code LOC | 98,157 | DERIVED |
| largest production file | `workflows/model_exploration.py` — 3,144 LOC | MEASURED |
| largest function | `run_workflow` — 1,572 lines / **130 branch nodes** / **99 params** | MEASURED |
| reference decomposed shape | tuner `run()` — 1,015 lines / 64 branch nodes | MEASURED |
| functions denser than the reference | 3 (`run_workflow`, interpreter `run`, proposer `_run_pipeline`) | DERIVED |
| collected unit tests | **10,780** | MEASURED |
| unit test modules | 580 | MEASURED |
| test : production LOC | 1.65 : 1 | DERIVED |
| integration + manual tests (not in CI) | 341 / 57 files | MEASURED |
| golden files / bytes | 108 / 646 KB | MEASURED |
| conftests / autouse fixtures | 5 / 4 | MEASURED |
| census-capable modules / cases | 90 / ≤ 2,294 (upper bound) | DERIVED |
| always-on block | 294 cases (manifest says ~134) | MEASURED vs HISTORICAL |
| **CI pytest wall time** | **993.31 s**, `10745 passed, 32 skipped` | MEASURED (run 32324124087) |
| CI job total / cap | 1,084 s / 1,500 s — **27 % headroom** | MEASURED |
| pytest share of the CI job | **92 %** | DERIVED |
| pytest growth | ≈ +33 s / milestone (3 points) | ESTIMATED |
| milestone PRs running the full suite | **9 / 10** | DERIVED (selector replay; 1 MEASURED confirmation — §18.2) |
| Step-10 core-surface selection | 73 / 580 modules — but full suite once a schema is touched | MEASURED |
| **real-subprocess unit tests** | **12 cases (0.11 %) = 382.66 s locally**; 8 of them 19–65 s; NOT excluded by CI's `-m "not real_run"` | MEASURED (bounded targeted run) |
| their CI-side share | a fifth to a third | ESTIMATED — exact value UNKNOWN (§27 Q4) |
| test modules doing an uncached full tree walk | 18 | MEASURED |
| `lru_cache` / `functools.cache` under `tests/` | **0** | MEASURED |
| disagreeing `PRODUCTION_DIRS` declarations | 3 (8 / 7 / 6 dirs) | MEASURED |
| per-file / per-fixture test durations (whole suite) | **NOT AVAILABLE** — §11.1 | — |

Historical Step-09 figures (proposer ~2,372 LOC, `model_exploration.py` ~3,137)
are **HISTORICAL** and were re-measured here (2,383 and 3,144); they are used
only for trend.

---

## 22. Expected cleanup acceptance criteria

Binding on Step 09.5a, and on any future test consolidation.

### 22.1 AMENDMENT B (operator, FROZEN) — what "stable" means, precisely

Revision 1 asserted both *"`run_workflow` takes carriers instead of 99
parameters"* and *"every public API remains unchanged"*. **Those two statements
are inconsistent, and the operator has resolved the contradiction in favour of
the migration:**

> **The Python CALL SIGNATURE of `run_workflow` IS ALLOWED TO CHANGE.**
> That signature change is part of the prerequisite's purpose.

Every repository production and test caller migrates **atomically** to the new
typed boundary. **A 99-argument compatibility wrapper must NOT be kept merely to
satisfy a "public API unchanged" clause** — doing so would preserve, verbatim,
the exact structural debt Step 09.5a exists to remove.

The distinction the acceptance criteria actually turn on:

| category | stability |
|---|---|
| **external / operator-facing** — CLI flags and launcher behaviour of `run_one_iteration.py` and `scripts/`; the public **entrypoint identity** `run_workflow` (name and role) | **MUST remain stable** |
| **persisted / contractual** — every persisted artifact and serialization contract; persisted key semantics and ordering where contractually relevant; `run_invariants_lock.json` contents; effective-config fingerprint / sha256 semantics | **MUST remain stable** |
| **behavioural** — iteration ordering and count; retry / attempt semantics; workflow output semantics; resume warn-and-skip soft-fail policy; LLM-facing prompt and call semantics unless separately proven otherwise | **MUST remain stable** |
| **repository-internal** — the `run_workflow` Python parameter list and every internal call site | **INTENTIONALLY MIGRATED** to the typed carrier boundary |

### 22.2 Structural acceptance (Step 09.5a)

* every **external/operator-facing, persisted and behavioural** contract in the
  table above is unchanged, and proven so by the differential oracle;
* the `run_workflow` **internal signature** is migrated, with **no** legacy
  99-argument wrapper retained;
* no duplicate authority is left behind — the four digest loaders are
  **removed**, not wrapped, and the surviving read path is one I/O and
  soft-fail authority;
* the immutable/mutable carrier separation holds and is enforced by the
  executable ownership guard of §20.1a;
* no generic `utils` module, no new registry, no new loader subsystem, no
  gratuitous abstraction layer;
* one obvious `run_workflow` entrypoint survives;
* Step 12 can still reach the out-of-tree composition target — Step 09.5a must
  make the composition root *easier* to introduce, never pre-empt it, and must
  not require Step 12 to replace these carrier contracts.

### 22.3 Test acceptance (any future consolidation)

* every named failure class is preserved or strengthened; fail-closed behaviour
  stays covered; independent adversarial contrasts (§17) survive;
* expensive real evidence is never replaced by synthetic unit evidence;
* a duplicate owner is removed only *after* the surviving owner is proven, and
  the surviving owner is named in the PR;
* selective-CI fail-closed behaviour is preserved — §18.4 makes narrowing `HUBS`
  an explicit non-goal;
* **success is not "fewer tests"** — it is the same or stronger failure-class
  coverage, clearer ownership, and materially less redundant execution,
  measured against §21;
* any consolidation begins with its own per-family reading pass (§14.4), never
  from this document's grep counts.

---

## 23. Step-10 entry verdict

> ## **STRUCTURAL PREREQUISITE REQUIRED**
>
> Two class-A structural findings; **zero** class-A test findings.

**Load-bearing evidence:**

1. `run_workflow` is **1,572 lines / 130 branch nodes / 99 parameters**, with
   ~15 mutable accumulators and an 813-line iteration loop, and it carries at
   least five independent semantic owners (§6.1). It is **twice** the decision
   density of the shape the project's own C7 decomposition produced, and
   CLAUDE.md's binding 2026-08-01 rule forbids adding new task logic,
   persistence or branching to exactly such a function.
2. Step 10's three central responsibilities — launcher-owned task binding,
   orchestration inputs to resume, workflow/resume metric-handle comparisons —
   all land in the two owners with no boundary between them (O2 and O3), and in
   the 813-line loop that already holds the direction literals they must
   replace.
3. `core/resume.py` implements one carried-state authority **four times**
   (§6.2), self-documented as mirrors of each other; Step 10 adds **two** more
   carried items by name, and the change amplification for each is traced,
   MEASURED, across three production files.
4. Test topology does **not** block: 27 % CI headroom, lean fixtures, correct
   fail-closed selection whose over-approximation this audit **verified rather
   than assumed** (§18.4), 646 KB of goldens, and a small set of defensible
   ownership findings — all Step-10-owned or later cleanup.

**The verdict stands on items 1–3 alone: A-1 (mixed run-binding / chain-state
ownership in `run_workflow`) and A-2 (duplicated committed-digest restoration
authority). Those are sufficient.**

**AMENDMENT C (operator, FROZEN).** Revision 1 additionally cited
`core/resume.py:61`'s private import of
`workflows.model_exploration._add_plugin_to_registries` as load-bearing verdict
evidence. Under **Q2 = B** that import is **OUT OF SCOPE for Step 09.5a** — it
belongs to the plugin/registry lifecycle owner, not the run-state carrier owner.
It remains a **valid structural finding** and supporting evidence that layering
debt exists (§8.5), and it is a **named Step-12 composition/layering input** —
but it is **not** a problem the prerequisite solves, and it is no longer
presented as one.

**Required prerequisite:** **Step 09.5a** (§20) — one behaviour-preserving
milestone establishing the typed run-scoped binding and chain-state carriers and
the single committed-digest read path. **Step-10 semantic implementation remains
BLOCKED until Step 09.5a merges.**

---

## 24. Step-10 sequencing — FROZEN

```
Step 09.5   audit FROZEN  (this document, REVISION 2)
      ↓
Step 09.5a  Workflow Run-State Structural Prerequisite
      │       typed immutable binding carrier(s) + typed mutable chain-state carrier
      │       + ONE committed-digest read path
      │       Gate 1 NOT REQUIRED if exact LLM-facing parity is proven, else REQUIRED
      │       Gate 2 REQUIRED, >= 2 iterations
      ↓
Step 10     detailed design / children / implementation
```

**Frozen sequencing rules:**

* **Step-10 semantic implementation is BLOCKED until Step 09.5a merges.**
* **Step-10 *parent*-level design MAY be drafted before or in parallel with
  Step 09.5a** — its semantic scope and debt inventory do not depend on exact
  post-refactor signatures.
* **Step-10 implementation-owning *child* designs MUST NOT freeze against the
  pre-09.5a source topology.** A child design names exact functions, signatures
  and line-anchored call paths; freezing one against `run_workflow`'s
  99-parameter signature would freeze it against a signature Step 09.5a is about
  to replace — the same sequencing error the project avoided in 07b, where the
  C7 decomposition became an operator scope amendment *inside* the PR rather
  than a design frozen against the pre-refactor shape.

**Operator's recommended operational sequence** (for context and source-topology
cleanliness — a recommendation, *not* a semantic prohibition on parallel parent
drafting):

```
freeze Step 09.5  →  design Step 09.5a  →  implement / merge Step 09.5a
                  →  Step-10 detailed design / children
```

**PR-decomposition implication:** the Step-10 child split should follow the
carriers Step 09.5a establishes (immutable bindings vs mutable carried state),
not the current file boundaries.

**The §20.2 CI follow-up (Q4 + Q5) is independent of this chain** — it may
proceed in parallel and gates nothing.

---

## 25. Ranking dimensions (no composite score)

Per the mandate, no weighted "debt score" is used. Hotspots in §5 are ranked on
seven explicit, independently-stated dimensions: **semantic mixed ownership ·
Step-10 touch probability · duplicated authority · change amplification ·
dependency rigidity · test cost · validation duplication.** A finding is class A
only when *Step-10 touch probability* is high **and** at least one of
*duplicated authority* or *change amplification* is high; length contributes to
none of them.

---

## 26. Adversarial self-review

| # | challenge | outcome |
|---|---|---|
| 1 | Did I classify a file as a god file only because it is long? | **PASS** — `agent/schemas/hyperparam_tuning.py` (3,036 LOC) and `core/sandbox_executor.py` (2,428) are larger than the interpreter and are **not** flagged; the A findings rest on parameter/state carriers and duplicated loaders |
| 2 | Did I miss mixed ownership inside a smaller file? | **CORRECTED** — `nodes/interpretation_helpers.py` (931) and `execute_tools/health_checks/evaluation.py` (309) were both examined and classified on ownership, not size |
| 3 | Did I mistake breadth for duplicated authority in the CI hub list? | **CORRECTED — the most important correction in this audit.** Depth-1 reach suggested `HUBS` was 2.5–8× over-broad; measuring **transitive** reach (41–76 %) vindicated every hub. §18.4 now recommends **against** narrowing it |
| 4 | Did I recommend a generic utils/common module? | **PASS** — §20 forbids it explicitly, as does §22 |
| 5 | Did I mistake re-exports/wrappers for duplicated authority? | **PASS** — §8.6 lists five investigated-and-cleared cases, including `render_prediction_track_record` (one authority, two consumers) and the `agent/prompts.py` ↔ `prompt_templates/tuner` delegation |
| 6 | Could the prerequisite be done inside Step 10 without extra debt? | **CLOSED by operator ruling Q1 = A.** Reasoned at draft as an open finding — it could, but only by making Step 10's first commit a large behaviour-preserving refactor of a surface its own child design would already be frozen against. §24 explains why separating them is cheaper; the operator may overrule (§27 Q1) |
| 7 | Did I report a deliberate design as a defect? | **CORRECTED** — the proposer's pipeline path was initially read as "the 09b track record never reaches the LLM". Source verification (`:1668-1694`, the explicit "Step 09b C4" comment) shows a deliberate two-transport design preserving the version partition. **No frozen Step-09 contract is violated**, and §47's stop condition was correctly not triggered. The surviving finding is the *test* (§14.1) |
| 8 | Did I reopen accepted Steps 01–07 B debt? | **PASS** — the register was read; items 1, 2, 4, 5, 12, 13 remain assigned to Step 10/12 and are untouched. A-1/A-2 are new findings about state carriers, not extensibility items |
| 9 | Did I absorb Step-10 semantic work into 09.5? | **PASS** — §20's non-goals list every carried semantic debt by name; §8.2 records the inert `vocab_link_confirmations` feature as a finding and explicitly does not fix it |
| 10 | Did I optimize raw test count? | **PASS** — §19 declines to raise any test finding to A, and §22 defines success as coverage + ownership, not count |
| 11 | Did I recommend deleting a test without naming its survivor? | **PASS** — §14.1 is UPGRADE with the survivor specified; §14.2 is explicitly "must not be deleted before the production branch is" |
| 12 | Did I mistake independent adversarial cases for redundancy? | **PASS** — §14.3 and §17 preserve the direction/sign/presence contrasts by name |
| 13 | Did I treat unit + census as duplication? | **PASS** — §13 and §15 keep both, and §15 records the mutation-oracle evidence that a census caught what review did not |
| 14 | Did I keep a golden merely because it exists? | **PASS** — §16 keeps them on the byte-identity contract and flags the proposer's dual-surface set as a Step-10 decision |
| 15 | Did I propose replacing real evidence with fake unit tests? | **PASS** — §22 forbids it; Gate 2 is *required* for Step 09.5a |
| 16 | Did I weaken fail-closed selective CI for runtime? | **PASS** — §18.4/§22 make narrowing `HUBS` an explicit non-goal |
| 17 | Did I measure setup cost separately from assertion cost? | **OPEN FINDING** — only partially. Conftest/autouse topology was measured (§12); per-module fixture cost was not, because §11.1 makes local timing invalid here. Recorded as TC-4 |
| 18 | Did I count parameterized cases as independent owners? | **PASS** — §13's counts are labelled ESTIMATED upper bounds, and §14.4 states the per-test pass was not done |
| 19 | Did I double-count tests through several directory views? | **PASS** — §10.2 sums to 10,780 and partitions the tree; §13's per-invariant counts are explicitly overlapping and labelled |
| 20 | Did I use historical test counts as current truth? | **PASS** — §10.5 and §18.4 both mark the manifest's figures HISTORICAL and re-measure |
| 21 | Did I run an expensive suite CI already measured? | **CORRECTED** — one local full `--durations` run was launched, then **stopped** at 80 % when the host proved contended by other users (§11.1). It was replaced by a **bounded targeted** run of the 12-case `allow_real_subprocess` lane (382.66 s, §11.4) — which CI cannot answer, since CI reports only a total. That is the ladder §12 of the mandate prescribes, in the order it prescribes |
| 22 | Did I inspect CI selector topology? | **PASS** — read from source and replayed against 10 real diffs and 6 hypothetical ones |
| 23 | Did I inspect the Step-10 touch surfaces specifically? | **PASS** — §7, one row per roadmap-named responsibility |
| 24 | Would Step 09.5a actually make Step 10 simpler? | **PASS** — §20's "unlocks" row is concrete: carrier instead of parameter #100; one declaration instead of a fifth loader; two-site direction migration |
| 25 | Would delaying Step 09.5a materially increase cost? | **PASS** — the migration would then also have to unwind two *new* loaders, two new parameters and two new accumulators |
| 26 | Does the prerequisite change public contracts unnecessarily? | **CORRECTED at freeze** — revision 1 claimed "every public API unchanged" while also replacing the 99-parameter signature. Amendment B (§22.1) resolves it: entrypoint **identity**, CLI, artifacts and lock contents are pinned; the **internal Python signature is intentionally migrated**, with no compatibility wrapper |
| 27 | Does the cleanup preserve one obvious entrypoint? | **PASS** — §22 requires it |
| 28 | Does Step 09.5a create new registries/loaders/dependency debt? | **PASS** — forbidden in §20's non-goals, citing the Steps 01–07 register's own "do NOT build a per-subsystem loader now" |
| 29 | Can Step 12 still reach the out-of-tree composition target? | **PASS** — §22 makes it an acceptance criterion; Step 09.5a touches carriers, not binding resolution |
| 30 | Is the verdict actually supported by evidence? | **PASS** — §23 now rests on three MEASURED items (A-1, A-2, and the Step-10 interaction), plus the non-blocking test finding. Amendment C removed the private-import item from the load-bearing list |
| 31 | Did I take the sub-agents' findings on trust? | **PASS — and it mattered.** Every load-bearing sub-agent claim was re-verified by the main agent: the dead `InterpretationOutput` fields were checked against the live schema; the proposer's production mode was resolved by *constructing* all four shipped `llm_configs`; the "13 real-subprocess tests" was re-counted as **12**; the "5 disagreeing `PRODUCTION_DIRS`" was re-counted as **3 verified**; and one sub-agent's headline claim — that 09b's track record "never reaches the LLM" — was **falsified** by reading `:1668-1694` (item 7) |
| 32 | Does any finding contradict a frozen Step-09 contract, triggering the mandate's stop condition? | **PASS — checked explicitly, and NO.** The one candidate (item 7) proved to be a deliberate documented design. The `vocab_link_confirmations` inertness (§8.2) is *carried Step-10 debt behaving exactly as the roadmap already describes it*, not a broken contract. No stop condition was met |

**32 challenges examined. Material contradictions remaining: 0. Corrected: 5
(items 2, 3, 7, 21, 26). Open findings at freeze: 1 (item 17 — per-module
fixture cost, unmeasurable on a contended shared host, carried as TC-4).**
Item 6 is **CLOSED by operator ruling Q1 = A**.

---

### 26.1 Final pre-freeze adversarial re-read (operator-mandated, 18 challenges)

Run at freeze, against the amended document.

| # | challenge | outcome |
|---|---|---|
| 1 | Does Step 09.5a simply move 99 arguments into a bag? | **CORRECTED — this was the single biggest gap in revision 1.** §20.1a now forbids it in so many words, shows the anti-pattern as code, and requires a field-by-field ownership audit into five classes (A–E) before any carrier is declared |
| 2 | Are immutable run authorities and mutable chain state still mixed? | **PASS** — §20.1 shape (B) makes them **separate types**, and §20.1a requires an executable ownership guard analogous to `FORBIDDEN_BINDING_FIELDS` so they cannot re-merge |
| 3 | Is any Step-10 semantic debt accidentally implemented by the prerequisite? | **PASS** — §20.1's NON-goals name every carried item explicitly: secondary transport, `vocab_link_confirmations`, direction literals, `evaluation.py` tables, proposer grammar, composition root |
| 4 | Does "public API stable" accidentally require keeping a 99-argument wrapper? | **CORRECTED** — §22.1 (amendment B) states the signature **is allowed to change** and that a compatibility wrapper **must not** be kept; §22.2 requires atomic caller migration |
| 5 | Does Q2 = B conflict with any remaining prerequisite-scope sentence? | **CORRECTED** — the offending clause ("beyond what removing `core/resume.py:61`'s private import requires") is **deleted** from §20.1's NON-goals, which now reads "no plugin-registry cleanup (Q2 = B)" |
| 6 | Is the private plugin-registry import incorrectly claimed as fixed or unlocked by the prerequisite? | **CORRECTED** — removed from §23's load-bearing evidence (amendment C); §6.1.3 and §8.5 now carry explicit scope notes marking it a **Step-12** input |
| 7 | Do duplicated resume loaders remain active under thin wrappers? | **PASS** — §20.1 shape (A) and §22.2 both state the old loaders are **removed, not wrapped** |
| 8 | Is the committed-digest reader actually ONE I/O and soft-fail authority? | **PASS** — §20.1 (A) permits divergence only in **digest key · validator · merge rule**; §22.2 requires "one I/O and soft-fail authority" |
| 9 | Does Step 09.5a pre-empt the Step-12 composition root? | **PASS** — an explicit NON-goal in §20.1 and an acceptance criterion in §22.2, which additionally requires that Step 12 not have to *replace* these carrier contracts |
| 10 | Is Gate 1 being required despite proven byte/call parity? | **CORRECTED by operator ruling** — §20.3 now waives Gate 1 **conditionally** on proven exact LLM-facing parity (prompt bytes, call labels, call order/count, structured inputs), instead of applying the assignment table mechanically |
| 11 | Is Gate 2 accidentally waived despite resume/cross-iteration changes? | **PASS** — §20.3 keeps Gate 2 **REQUIRED at ≥ 2 iterations**, citing the standard's temporal-depth row for resume |
| 12 | Did Q4/Q5 accidentally become a Step-10 blocker? | **PASS** — §20.2 states three times that the CI item is non-blocking, not part of Step 09.5a, and not implemented here; §24 repeats it |
| 13 | Did the audit recommend deleting or mocking the real-subprocess tests? | **PASS** — §20.2 and §27 Q5 both forbid delete/mock/weaken/relabel; the change is *scheduling* only |
| 14 | Did the audit weaken fail-closed selective CI? | **PASS** — §18.4 recommends **against** narrowing `HUBS`; §20.2 and §22.3 preserve fail-closed behaviour |
| 15 | Does any test finding get promoted to A without Step-10 amplification? | **PASS** — §19 keeps class A empty and explains why §11.4's real-training concentration, despite being the largest lever, is **not** Step-10-amplified |
| 16 | Are B/C structural findings still assigned to the correct future owners? | **PASS** — §9 B-1…B-6 → Step 10; C-1…C-7 → later cleanup; the private import → Step 12; §20.2 absorbs the CI-topology items |
| 17 | Can Step-10 child design wait until the new carrier topology actually lands? | **PASS** — §24 freezes exactly that: parent may draft in parallel, children must not freeze pre-09.5a |
| 18 | Can Step 12 still supply out-of-tree task composition without replacing these carrier contracts? | **PASS** — §22.2 makes it an explicit acceptance criterion; the carriers hold run-scoped *state*, while Step 12 owns *binding resolution*, which §20.1 leaves untouched |

**18 challenges examined. PASS 12 · CORRECTED 6 · OPEN FINDING 0. Material
contradictions before freeze: 0. Open operator questions before freeze: 0.**

---

## 27. Operator questions — ALL RESOLVED (2026-08-20)

Five were raised. **All five are now closed by operator ruling; zero remain
open.** Each entry keeps the evidence and options as put to the operator, and
records the ruling.

### Q1 — Is PR-X worth its migration cost, or should Step 10 absorb it? **(Step 10 IS blocked by this answer)**

*Evidence:* §6.1 (99 params / 130 branches / 5 owners), §6.2 (four identical
loaders), §9 A-1/A-2.
**Option A (recommended):** land PR-X first; Step-10 parent design proceeds in
parallel; child designs freeze after.
**Option B:** Step 10 absorbs the decomposition as its own first commit.
*Consequences:* A costs one extra PR cycle and its Gates, and gives Step 10 a
stable topology to freeze designs against. B saves a cycle but repeats the 07b
situation, where the decomposition became a mid-PR operator scope amendment —
which worked, but only because the operator amended scope rather than because
the design anticipated it.
*Recommendation:* **A.**
> **RULING: A — APPROVED.** Land the structural prerequisite BEFORE Step-10
> semantic implementation, formalized as the milestone **Step 09.5a — Workflow
> Run-State Structural Prerequisite** (deliberately *not* "Step 10a": it exists
> because Step 09.5 blocks Step 10). Step-10 parent-level reasoning **may** be
> drafted in parallel; implementation-owning child designs **must not** freeze
> against the pre-09.5a topology. The operator's recommended operational
> sequence — freeze → design 09.5a → merge 09.5a → Step-10 design — is a
> context-cleanliness preference, not a prohibition on parallel parent drafting
> (§24).

### Q2 — Should PR-X include the `core/resume.py:61` private-import inversion? **(does not block Step 10)**

*Evidence:* §8.5 — `from workflows.model_exploration import _add_plugin_to_registries`.
**Option A:** include it — it is the one dependency that makes the registry
owner (O5) undecomposable, and PR-X is already touching both files.
**Option B:** leave it; PR-X touches only the binding/state carriers.
*Consequences:* A slightly widens PR-X into plugin-registry territory (a
different owner). B leaves a private cross-layer import in place, which Step 12's
composition work will meet again.
*Recommendation:* **B**, with the inversion recorded as a named Step-12 input —
the prerequisite should stay inside one semantic boundary.
> **RULING: B — APPROVED.** Do **not** absorb
> `core/resume.py → workflows.model_exploration._add_plugin_to_registries` into
> the prerequisite. It belongs to the **plugin / registry lifecycle** owner and
> is a named future **Step-12** composition-layering input. The prerequisite
> stays scoped to run-scoped configuration/bindings + restored/carried/persisted
> chain state. Every sentence implying the prerequisite removes this import has
> been repaired (§6.1.3, §8.5, §20.1, §23 amendment C).

### Q3 — Should the 124-case health-core census stay in the always-on block? **(does not block Step 10)**

*Evidence:* §10.5 — always-on is 294 cases against a documented "~134";
`test_health_core_census.py` is 124 of them and runs on every PR.
**Option A:** keep it — it is the structural owner for the whole check family
and 2.7 % of the suite is cheap.
**Option B:** move it to the derived selection, so it runs when
`execute_tools/health_checks/` changes.
*Consequences:* A costs ~2.7 % on every PR. B risks the exact escape the
always-on list exists to prevent, since the census reads a directory.
*Recommendation:* **A**, and update the stale "~134" figure in
`manifest.py:19-21` whenever that file is next touched.
> **RULING: A — APPROVED.** Keep the structural Health census in the always-on
> block; do not weaken a directory-wide structural owner to save a small
> fraction of the suite. The stale "~134" prose may be corrected the next time
> `manifest.py` is legitimately touched — **no dedicated PR is required** for a
> prose-only cleanup.

### Q4 — Should a reproducible runtime baseline be established CI-side? **(does not block Step 10)**

*Evidence:* §11.1 — this audit could not measure per-file durations because the
only available host is shared and contended by other users.
**Option A:** add a `--durations` artifact to the nightly schedule run (which
already runs everything, so it costs nothing extra).
**Option B:** leave it; runtime is not currently a problem (27 % headroom).
*Consequences:* A gives every future audit a clean baseline for the price of one
uploaded artifact on an already-scheduled job. B means the next audit hits the
same wall.
*Recommendation:* **A**, as a small independent change — explicitly **not**
part of the prerequisite, and not a Step-10 dependency.
> **RULING: A — APPROVED.** Future full / nightly CI should produce a
> machine-readable or preserved `--durations` artifact, so runtime audits use
> reproducible CI-side data instead of a shared developer host. It is
> **non-blocking for Step 10**, **not** part of Step 09.5a, and **not** evidence
> for changing semantic coverage. Folded into the §20.2 follow-up.

### Q5 — Should the 12 real-training unit tests keep running in the default CI lane? **(does not block Step 10; largest available runtime lever)**

*Evidence:* §11.4 — `pytest -m "allow_real_subprocess"` = **12 of 10,780 cases
(0.11 %)**, **382.66 s** locally, 8 of them 19–65 s each, running real
`train_engine_sandbox.py` / scoring subprocesses on CPU. CI's
`-m "not real_run"` filter does **not** exclude them (`ci.yml:94` vs
`pyproject.toml:56`).
**Option A (recommended):** keep the tests exactly as they are, but run the
`allow_real_subprocess` lane as its **own CI job**, in parallel with the
deterministic unit job. **No test is deleted, weakened or mocked.**
**Option B:** leave the topology as-is; the suite still fits in the 25-minute
cap with 27 % headroom.
*Consequences:* A shortens the critical path by whatever those 12 tests
actually cost on CI (§11.4: ESTIMATED a fifth to a third, exact share
UNKNOWN), at the price of one more job definition and a second runner. It also
makes the real-evidence lane *visible* as its own signal rather than hidden
inside a 10,780-case dot stream. B costs nothing now and revisits the question
when the cap binds (§11.3: ~12 milestones out).
*Recommendation (revision 1):* **A, but only after Q4 supplies the CI-side
measurement.**
*Explicitly NOT recommended:* mocking these tests, marking them `real_run`, or
deleting any of them. §22 forbids replacing real evidence with synthetic
evidence, and 07a/07c depend on exactly this lane.
> **RULING: A — APPROVED, and the "measure first" condition is REMOVED.** The
> operator ruled that splitting the lane is **already justified on its own
> merits**: these 12 tests are not ordinary unit tests — they run real
> training/scoring subprocesses, and they sit in the default deterministic lane
> only because the marker is named `allow_real_subprocess` rather than
> `real_run`. The target topology is:
>
> ```text
> deterministic unit job     excludes allow_real_subprocess
> real-subprocess job        runs allow_real_subprocess, in parallel
> ```
>
> Nothing is deleted, mocked, weakened, or relabelled as synthetic evidence.
> Q4 and Q5 may land together as **ONE small CI-only maintenance PR** (§20.2),
> which is **not** part of Step 09.5a, **not** a Step-10 blocker, and **not**
> authorized for implementation by this audit session.

---

## 28. Final recommendation

```
STEP 09.5 VERDICT:  STRUCTURAL PREREQUISITE REQUIRED   — APPROVED, FROZEN
                    structural class A = 2 · test-topology class A = 0
                    5 operator questions RESOLVED · 0 open

NEXT     Step 09.5a — Workflow Run-State Structural Prerequisite
         owner: workflow run-scoped authorities + restored/carried/persisted
                exploration-chain state
         shape: typed IMMUTABLE binding carrier(s)
              + typed MUTABLE chain-state carrier   (separate types)
              + ONE committed-digest read path replacing four copies
              + atomic migration of every internal caller
         RULE:  the carrier is a SEMANTIC PARTITION, never a 99-argument bag
                (field-by-field ownership audit into classes A-E,
                 plus an executable FORBIDDEN_BINDING_FIELDS-style guard)
         API:   run_workflow IDENTITY preserved; internal Python signature
                INTENTIONALLY migrated; no compatibility wrapper
         GATES: Gate 1 NOT REQUIRED if exact LLM-facing parity is proven,
                otherwise REQUIRED
                Gate 2 REQUIRED, >= 2 iterations (resume lifecycle changes)
         OUT:   plugin-registry private import (Q2 = B -> Step 12)
                and every carried Step-10/12 semantic debt

THEN     Step 10 PARENT design  — may be drafted in parallel
         Step 10 CHILD designs  — freeze only AFTER Step 09.5a merges
         Step 10 implementation — BLOCKED until Step 09.5a merges

PARALLEL CI validation-topology maintenance (Q4 + Q5), non-blocking:
         deterministic unit job excludes allow_real_subprocess
         + parallel real-subprocess evidence job
         + durations artifacts on both lanes
         no test deleted, mocked, weakened or relabelled

CARRY    B findings -> Step-10 design as named constraints
         C findings -> later cleanup
         private registry import -> Step 12 composition/layering
```

**No test-topology prerequisite PR is required.** The suite is large but its
ownership is, on the evidence this audit could verify, sound; its runtime is
92 % of a CI job with 27 % headroom; and its selective-CI behaviour is correct
in a way this audit set out to challenge and ended up confirming.

**The one thing worth knowing independently of Step 10:** suite cost is not
spread across 10,780 tests — it is concentrated in **12** of them (0.11 %) that
run real training and scoring inside the default CI unit lane (§11.4). That is
the largest available lever on validation runtime, it is a *scheduling*
decision rather than a coverage one, and it is now approved unconditionally as
the §20.2 follow-up.

---

*END — **REVISION 2 — FROZEN** (operator ruling, 2026-08-20). Five operator
questions resolved; zero open. Step 10 remains BLOCKED until Step 09.5a merges.*
