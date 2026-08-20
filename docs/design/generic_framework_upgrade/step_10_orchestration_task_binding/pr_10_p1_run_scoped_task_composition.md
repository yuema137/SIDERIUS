# Step 10 / P1 — Run-Scoped Task Composition / Binding

## 0. Status

**REVISION 2 — FROZEN. OPERATOR APPROVED (2026-08-20).
IMPLEMENTATION COMPLETE — MERGED 2026-08-20.
Open operator questions: 0. Material deviations: 0.**

**MERGED**: PR #241, squash **`bcb17e45`** on `master`; final PR head
`ffad7029793e365843ba67e083ccdc2dd84679c4`; exact-head CI **32415952195
SUCCESS** (ruff check · ruff format · pyright · unit). Landed master verified
**byte-identical** to the validated head — `git diff ffad7029 bcb17e45` is
empty. Merge authorized by the operator; performed with the repository's
recorded per-command approval prefix so the transcript names the specific
mutation.

### 0.0 Implementation summary (2026-08-20)

| field | value |
|---|---|
| implementation base | `origin/step10-parent-design` @ `3c5b21f4` (frozen docs NOT merged to master; merge-base with `origin/master` == `2393aacc` exactly, so the production tree is master's) |
| branch | `step10-p1-run-scoped-task-composition` |
| commits | C0 `f783fecb` · C1 `cdb774df` · C2 `63389b89` · C3 `6552cf8d` · C4 `025c6d68` · C5 `821ea469` · C6 (this closure) |
| final EXECUTABLE head | **`821ea469`** (C6 is docs + ledger only) |
| `RunTaskComposition` | `workflows/task_composition.py`; 9 fields — `task_data_path` (the RESOLVED implementation) · `dataset_profile` · `metric` · `task_health_binding` · `interpretation_blocks` · `task_description` · `forward_contract` · `semantic_fingerprint` · `provenance` |
| `WorkflowRunBindings` | 24 → **25** fields (`task_composition`) |
| `run_workflow` | 28 → **21** parameters (−9 restored, +`restored_state`, +`task_composition`) |
| mandatory LLM parity | **PASS, exact** — manifest sha256 `476d5d7c…778a` identical at base and final head, `diff_manifests == []` |
| Gate 1 | **NOT REQUIRED** — deterministic parity PASSED (§0 row, §10 item 5) |
| Gate 2 | **NOT REQUIRED** — P1 owns no unique real-GPU/real-data failure class |
| P1 test modules | 136 tests across six modules (C0 25 · C1 51 · C2 26 · C3 8 · C4 14 · C5 12) |

**Five source findings, all recorded in place**: F-P1-1 (a parent-side
task-data-path consumer already existed — the GPU warmup probe — which
dictated C3's accessor choice) · F-P1-2 (registration is an import
side-effect, no central table) · F-P1-3 (the parity instrument's fixture
reaches only the interpreter and proposer families; stated rather than
overclaimed) · F-P1-4 (a task-name literal had reached a composition error
message; caught by this PR's own test) · F-P1-5 (a merged 09.5a guard whose
oracle was `git diff …HEAD` and which therefore failed for every subsequent
PR; pinned to the range it describes).

---

Revision 2 applies the operator review ruling of 2026-08-20 to DRAFT rev 1:

Revision 2 applies the operator review ruling of 2026-08-20 to DRAFT rev 1:
all three operator questions dispositioned (§0.1), plus seven targeted
refinements — the resolved-once `TaskDataPath` authority (§5.2a), the
canonical path-independent composition fingerprint (§5.9), the explicit
binding-lifetime invariant + consumer-reachability matrix (§5.8), the
narrowed "zero ambient TIDMAD" claim (§3), LLM parity as a REQUIRED
preservation property never substitutable by a Gate (§10), autonomous
semantic commits restored (§9 preamble; per-commit operator approval was a
process error), and the fourth-task proof re-anchored on structural censuses
rather than working-tree `git diff` (§9 C4). The commit count is **seven**
(C0–C6); rev 1 miscounted "six".

| field | value |
|---|---|
| parent | `docs/design/generic_framework_upgrade/step_10_orchestration_task_binding.md` — REVISION 2 FROZEN; post-merge reconciliation PASS (§0.3); targeted corrections R-1/R-2/R-3 applied 2026-08-20 |
| owns (parent §4.1) | **S1** run-scoped composition / launcher binding · **S7** `campaign_artifacts` generic-core task-coupling residue |
| source anchor | merged `master` = **`2393aacc`** (design branch `step10-parent-design`). Line numbers cited here were read at this anchor; they are evidence, and the implementation session re-verifies them before editing (§16). Exact line numbers are NOT frozen as implementation authority |
| depends on | Step 09.5a MERGED incl. C3 closure — both satisfied at the anchor |
| downstream consumers | P2a (consumes the bound `MetricSpec`), P2b (extends the composition schema with secondaries), P4 (demonstrates on a second task via the health binding), P5 (builds on the collapsed `RestoredState` transport), P6 (drives Pets/DAVIS through this composition) |
| Gate 1 | **NOT REQUIRED** — because exact deterministic un-composed LLM-facing byte parity is MANDATORY (§10). A parity delta is a preservation FAILURE, not a Gate trigger |
| Gate 2 | **NOT REQUIRED** — P1 introduces no unique real-GPU/real-data failure class; P6 owns the real multi-task lifecycle |

**What this freeze owns**: semantic scope; the public boundary shape;
binding lifetime; fail-closed semantics; fingerprint semantics; module
ownership; validation strategy; the C0–C6 decomposition; acceptance
criteria. **Not frozen**: exact line numbers as implementation authority;
incidental local names inside private modules.

Checklists start all-`[ ]` and are ticked only with recorded evidence.

### 0.1 Operator rulings — RESOLVED 2026-08-20

| id | question | ruling |
|---|---|---|
| **Q-P1-1** | standalone interpreter node CLI (`result_interpretation_agent.py:1247`) | **YES — stays on the legacy zero-arg loader.** A standalone CLI is not a composed run. P1 guarantees the composed **production workflow** consumers use the composed binding; standalone-node composition unification is Step-12 territory unless a composed production path is found to depend on that CLI (none does at the anchor) |
| **Q-P1-2** | composition identity in `run_invariants_lock.json` | **YES — for COMPOSED runs, ONE canonical semantic fingerprint joins the lock.** It is computed over resolved semantic values/declarations + plugin CONTENT digests + stable binding identities, and **excludes machine-local absolute paths, workspace locations and every relocation-only provenance detail** — equivalent content at a different filesystem location is the SAME scientific run. For an UN-COMPOSED legacy run the new lock key is **ABSENT** (never serialized as `null`), so the legacy lock stays byte-identical. A composed resume whose fingerprint changed **fails closed** at the existing invariant boundary. Deterministic tests required: relocation parity · content-change divergence · composed-resume mismatch refusal · legacy lock byte-identity (§5.9, C2) |
| **Q-P1-3** | composition file format | **One YAML composition MANIFEST with explicit refs.** Small scalar/task-level values may be inline; existing semantic-family declarations/plugins stay referenced through their own files/contracts. No directory/package convention in P1 — Step 12 owns the task-package/composition-root convention |

---

## 1. Parent contract (recovered, binding)

From the frozen parent (incl. the R-1/R-2/R-3 corrections):

* **Mandate (§1.2)**: task/run semantics are bound ONCE at the
  composition/launcher edge; the generic workflow consumes them as typed
  values; nothing downstream rediscovers task identity, metric direction,
  task data semantics, Health semantics or interpretation semantics.
* **Q-10-1**: P1 is ONE child. It must **not** be split into composition
  value / default migration / binding transport — an intermediate head must
  never contain an explicit binding that stops at a process boundary, or a
  run in which some authorities are explicit and others ambient.
* **§3.8 split**: P1 makes **five** of the six implicit TIDMAD defaults
  explicit and fail-closed (task data path · dataset profile · task health ·
  metric · interpretation blocks). The **physical data root is Step-11's**.
  **R-2**: for the metric, P1 owns the COMPOSED-run explicitation via a
  bound-metric seam at the tuner's existing acquisition site;
  `derive_tidmad_metric` remains the bounded UN-COMPOSED legacy adapter
  whose eventual removal is Step 12's.
* **§6.1 shape (frozen)**: the composition produces **values, never
  names**; it is run-scoped and immutable and lands on
  `WorkflowRunBindings`; it fails closed and **never falls back to TIDMAD**
  when explicitly composed; it does not own the semantics it binds.
* **§6.2**: reuse each family's existing resolution authority; no second
  `TaskDataPath`-shaped registry per family; no one giant `TASKS = {…}`
  table.
* **§10**: no fourth run-state carrier; `ChainState` never crosses a
  subprocess boundary; the launcher's nine restored kwargs collapse into one
  `RestoredState` parameter (explicitly assigned to Step 10 by 09.5a C4b).
* **§22.1 (R-1)**: exact un-composed LLM-facing byte parity is REQUIRED
  evidence for P1; a real Gate 1 is not a substitute for broken parity.
* **§24**: Step 12 must be able to supply this exact interface's values from
  an external package **without changing the interface**.

---

## 2. Current source audit (measured at `2393aacc`)

### 2.1 The five implicit defaults P1 owns — mechanism per family

| # | family | default mechanism | existing explicit seam | subprocess transport today |
|---|---|---|---|---|
| 1 | task data path | `resolve_task_data_path(None)` → `_REGISTRY.get(TIDMAD_COMPATIBILITY_ID)` (`execute_tools/task_data_path.py:275-283`) | `bind_task_data_path(impl)` ContextVar (`:314`); registry keyed on the impl's own declared id, duplicate registration refused (`:240-253`) | flag `--task_data_path_id` **parsed** by all three children (`train_engine_sandbox.py:1850` + bind at `:1967-1972`, `inference_single.py:100`, `denoising_score_single.py:107`); `transport_argv` (`:347-354`) has **zero** emitters |
| 2 | dataset profile | `resolve_dataset_profile()` → `_ACTIVE_PROFILE.get() or TIDMAD_PROFILE` (`execute_tools/dataset_config.py:613`) | `bind_dataset_profile(profile)` ContextVar (`:669`); subprocess loader `load_dataset_profile(path)` **fails closed** (`:617-666`) | `--dataset_profile_json` already emitted at `core/sandbox_executor.py:1384`, `:1732`, `:2048` |
| 3 | task health config | `materialize_effective_config(..., task_health_binding=HealthBindingState.LEGACY_OMITTED)` — the keyword **exists** (`execute_tools/health_checks/config.py:585`) and `core/run_invariants.py:380-385` simply omits it | 08b's three binding states (`LEGACY_OMITTED` / `EXPLICIT_NONE` / explicit path) + plugin refs with content-digest pinning | the effective config file (`{workspace}/health_checks_effective.yaml`) already crosses; no new transport needed |
| 4 | metric | `run_metric = derive_tidmad_metric(run_profile, run_deliverable_spec)` — unconditional, `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py:541`; plus the legacy shim `core/sandbox_executor.py:2009` (`metric if metric is not None else derive_tidmad_metric(...)`) and the scoring-subprocess re-derivation `execute_tools/denoising_score_single.py:180` | `metric_spec_from_declaration` (`execute_tools/evaluation_metric.py:658`) — the ONE spec-from-declaration authority; implementations `TidmadDenoisingMetric` `:527`, `AccuracyMetric` `:545`, `GlobalMseMetric` `:576`; the tuner already binds `run_order = MetricOrder(run_metric.spec)` (`:552`) | **none** — the metric deliberately crosses no process boundary; the scoring child re-derives from `--dataset_profile_json` (Step-06 contract). See §5.3 for the composed-run consequence |
| 5 | interpretation blocks | `load_interpretation_task_blocks(path=None)` → `LEGACY_DEFAULT_TASK_INTERPRETATION_CONFIG` (`agent/prompt_templates/interpretation/task_blocks.py:34`, `:62`); both production callers zero-arg: `workflows/model_exploration.py:1978` and `nodes/result_interpretation_agent/result_interpretation_agent.py:1247` | the loader already takes an explicit path and FAILS CLOSED; `InterpretationInput.task_blocks` accepts the typed value directly (09b) | in-process only |

### 2.2 `task_description` / `forward_contract` — TWO consumption mechanisms

`workflows/task_config.py` (302 LOC): `load_task_config(path=None)` resolves
`configs/task_config.yaml` (`_DEFAULT_CONFIG_PATH` `:41`), caches per
absolute path in module-level `_CACHE` (`:46`), validates
`forward_contract` through the `ForwardContract` schema.

Measured consumers (parent §3.2, re-verified):

| mechanism | consumers |
|---|---|
| **direct `{TASK_DESCRIPTION}` placeholder substitution** | planner (`agent/prompts.py:66`, substituted `agent/llm_bridge.py:1001`); interpreter (`rendering.py:48`→`:144`, `:664`→`:754`); literature review (3 templates, substituted in `literature_review/__init__.py:305/:402/:627`) |
| **rendered-block path** | proposer `_render_task_background()` (`ml_model_proposal_agent.py:477`) + `load_task_config()` at `:2346`; implementor (`ml_model_implementor.py:1035`, `:1107`, `:1151`); the one lowercase `{forward_contract}` placeholder (`proposal/proposing_stage.md:131`, filled `:1772`) |

Each consumer calls `load_task_config()` / `get_task_description()` itself,
at its own depth (the bridge, a renderer, a node). **There is no single
injection point** — which rules out a "pass the string down" migration
inside P1 and motivates the run-scoped override seam of §5.5, and it is why
§5.8's reachability matrix names all five consumer families rather than
assuming one placeholder.

### 2.3 The Step-09.5a substrate P1 lands on

* `run_workflow` — 28 keyword-only params (`workflows/model_exploration.py:1372`),
  1,375 lines; `WorkflowRunBindings` constructed ONCE at `:1777-1803`
  (24 frozen fields; ownership guard derives its deny-list from
  `chain_state_field_names()`); `ChainState.from_restored` at `:1813-1821`.
* Production `run_workflow` callers: `sdsc_submission_scripts/run_one_iteration.py:1946`
  (the chain launcher — unpacks `RestoredState` into **nine** kwargs at
  `:2024-2035`), `sdsc_submission_scripts/run_exploration_test.py`, and the
  module's own CLI `main` (`model_exploration.py:2928`). 21 test files call
  it (09.5a census).
* The launcher already imports one task-supplied capability explicitly —
  `resolve_tidmad_measurement_capability` (`run_one_iteration.py:1944`) with
  the contract comment *"Callers that know the task supply those. The
  workflow must not name a task resolver itself."* **This is the composition
  edge's existing precedent, and P1 generalizes exactly this move.**
* The three restored values that are *not* `ChainState` fields are consumed
  at: `accumulated_key_findings` `:2107-2115`; `accumulated_gate_exhaustions`
  `:1842-1843`; `accumulated_physical_rejections` `:2052-2064`.

### 2.4 S7 — the three `campaign_artifacts` residues

`core/campaign_artifacts.py` (174 LOC; sole production consumer
`scripts/run_comparison.py`):

1. `validate_experiment_completeness` requires the `denoising_score` /
   `invalid_score_reason` pair by literal key (`:37-38` region);
2. it resolves the declared health-peek set ambiently:
   `resolve_dataset_profile().health_peek_files` via a call-time local
   import (`:47-52`);
3. `validate_phase1_baseline` imports the `TIDMAD` singleton for the
   full-scope default: `list(range(TIDMAD.num_files))` (`:106-111`).

`campaign_manifest.json` remains write-only provenance (zero readers);
parent §4.2 forbids turning any of this into `ChainState` or giving it a
digest projection.

### 2.5 What is already generic and must not be duplicated

`TaskBindingContext` presence-discrimination + the fail-closed truth table
(`task_data_path.py:260-302`); `load_dataset_profile`'s fail-closed loader;
08b's health plugin loading with content-digest pinning;
`metric_spec_from_declaration`; `InterpretationTaskBlocks` validation;
`ForwardContract` validation. **P1 composes these; it re-implements none of
them.**

---

## 3. Goal / final effect

> A run is handed ONE explicit, typed, fail-closed set of task bindings —
> data path · dataset profile · metric · Health family · interpretation
> blocks · task description/forward contract — resolved at the
> launcher/composition edge from configuration + externally loadable plugin
> references, carried on `WorkflowRunBindings`, consumed through each
> family's existing authority, and emitted over the already-built subprocess
> transport. An un-composed run behaves byte-identically to today.

After P1:

* **zero ambient TIDMAD semantic authorities remain on P1-owned
  run-composition / orchestration surfaces.** Named residual surfaces stay
  explicitly owned elsewhere and are NOT claimed closed here: the
  scoring-subprocess / full-loop closure for contrast tasks (**P6**), and
  the physical data root / sandbox execution infrastructure (**Step 11**).
  P1 must not claim global cleanup its own non-goals defer — and equally,
  every S1/S7 authority P1 owns must be explicit on a composed run;
* the five §3.8 defaults survive only as the **bounded legacy adapters** of
  the un-composed path (each already labelled as such in source);
* `transport_argv` has its first production emitter, and the child side
  that has been waiting (`train_engine_sandbox.py:1967-1972`) becomes
  reachable;
* the launcher passes `RestoredState` as ONE parameter;
* `core/campaign_artifacts.py` takes its task-coupled values as explicit
  parameters.

**P1 does NOT make Pets or DAVIS run the loop** — that is P6. P1 makes the
composition exist, fail closed, reach every in-process consumer and the
subprocess transport, and proves it on synthetic/fixture tasks in unit
tests.

---

## 4. Semantic owner and public boundary

**One semantic owner: run-scoped task composition.**

Public boundary (shape frozen; incidental private names not):

```text
workflows/task_composition.py          (NEW, the one composition authority)
    RunTaskComposition                 frozen dataclass of RESOLVED typed values
    compose_run_task_bindings(path)    YAML manifest → RunTaskComposition, fail-closed
    (plugin-ref loader helper, reusing the 08b file-ref pattern)

run_workflow(task_composition: RunTaskComposition | None = None, ...)
WorkflowRunBindings.task_composition   (new field, 24 → 25)
launcher flag: --task_composition <path>   (absent ⇒ legacy, byte-identical)
```

`RunTaskComposition` holds **bound authorities only** — no mutable services,
no chain state, no launch/transit values. Fields (frozen shape):

| field | type | resolved by |
|---|---|---|
| `task_data_path` | the **RESOLVED `TaskDataPath` implementation** (the registry's own Protocol type — no new schema) | plugin ref loaded + registered at composition time; the impl's own declared `task_data_path_id` remains available FROM this object as transport/provenance identity (§5.2a) |
| `dataset_profile` | `DatasetProfile` | `load_dataset_profile(path)` — existing fail-closed loader |
| `metric` | `EvaluationMetric` (frozen) | declaration JSON → `metric_spec_from_declaration` + implementation plugin ref |
| `task_health_binding` | `TaskHealthBinding` (explicit path or `EXPLICIT_NONE`) | 08b's existing states; **`LEGACY_OMITTED` is not expressible in a composition** |
| `interpretation_blocks` | `InterpretationTaskBlocks \| None` | existing fail-closed loader; `None` = task declares none ⇒ nothing rendered (09b) |
| `task_description` | `str` (non-empty) | task-config values through the existing validator |
| `forward_contract` | `ForwardContract` | same |
| `semantic_fingerprint` | `str` (sha256) | §5.9's canonical, **path-independent** computation — the value the run-invariants lock pins |
| `provenance` | source paths + content digests + plugin origins | **DIAGNOSTIC ONLY.** Never the lock identity — it contains machine-local paths by design (§5.9) |

**Explicitly rejected** (parent §19.1): a `WorkflowContext`; a bag holding
launch/transit values; a `TASKS = {…}` per-task table; mutable services on
the frozen value; duplicating `MetricSpec` / `DatasetProfile` /
`ForwardContract` / `TaskDataPath` shapes inside a new mega-schema — every
field above is an existing subsystem's own type.

---

## 5. Design decisions (the load-bearing ones)

### 5.1 Where composition is RESOLVED: the launcher edge

`compose_run_task_bindings(path)` runs in the launcher (and in
`model_exploration.main` for the CLI), **before** `run_workflow` is called —
the same edge that already supplies `resolve_tidmad_measurement_capability`.
`run_workflow` receives the resolved value, never the path. This keeps
`run_workflow` free of YAML/plugin I/O and satisfies "bound ONCE at the
composition edge" without moving the 09.5a bindings construction (which
stays at `:1777`, where the startup-derived fields require it — the
composition value is one more class-A input to it).

### 5.2 How the composed values reach in-process consumers

Per family, using each family's **existing** seam (parent §6.2):

| family | consumption change |
|---|---|
| task data path | the workflow wraps the per-iteration execution in `bind_task_data_path(composition.task_data_path)` when composed; unbound when not |
| dataset profile | same, via `bind_dataset_profile(composition.dataset_profile)` — the tuner's `resolve_dataset_profile()` at `:494` then returns the bound profile with **no tuner edit** |
| task health | `build_run_invariants` gains a pass-through `task_health_binding` parameter → `materialize_effective_config(:585)`'s existing keyword. Un-composed ⇒ omitted ⇒ `LEGACY_OMITTED`, byte-identical |
| interpretation blocks | `model_exploration.py:1978` passes `composition.interpretation_blocks` when composed (including `None` = render nothing); the zero-arg legacy loader call remains the un-composed branch |
| task description / forward contract | §5.5's run-scoped override seam |

### 5.2a `TaskDataPath` is resolved EXACTLY ONCE (operator correction)

Rev 1 carried an internal contradiction: a "dataclass of RESOLVED typed
values" holding `task_data_path_id: str` while consumption needed
`bind_task_data_path(resolved_impl)` — leaving unanswered who turns the id
back into the implementation. **A second registry lookup inside
`run_workflow` would be a second resolution and is forbidden.** Frozen shape:

```text
composition edge:
    config plugin_ref
        → plugin load / registration (the impl declares its own id;
          duplicate registration refused by the existing registry)
        → RESOLVED TaskDataPath impl
        → RunTaskComposition.task_data_path

workflow:
    bind_task_data_path(composition.task_data_path)     ← the SAME object

subprocess:
    transport_argv(composition.task_data_path)
        → the impl's own declared stable id
        → child resolver (resolve_transported_task_data_path)
```

`task_data_path_id` is **not a composition field**: it is the resolved
object's own declared identity, read from it for transport argv, provenance
and the semantic fingerprint. There is no semantic id→impl lookup anywhere
downstream of the composition edge. (The CHILD process's lookup is the
transport contract's existing child-side half — a transported id resolving
in the child's registry — not a second parent-side semantic resolution; its
out-of-tree availability limit is a named hand-off, §12.)

### 5.3 Metric consumption — one new seam, mirroring the profile idiom

The tuner's `:541` derivation is TIDMAD arithmetic; a composed Pets run must
not execute it. A run-scoped bound-metric ContextVar in
`execute_tools/evaluation_metric.py` (`bind_run_metric` /
`resolve_bound_run_metric`), exactly the `bind_dataset_profile` idiom, and
the tuner's binding line becomes:

```python
run_metric = resolve_bound_run_metric() or derive_tidmad_metric(run_profile, run_deliverable_spec)
```

* composed run ⇒ the workflow binds `composition.metric` ⇒ the tuner
  consumes it; `run_order = MetricOrder(run_metric.spec)` (`:552`) is
  already generic;
* un-composed ⇒ unbound ⇒ the existing derivation, byte-identical;
* this is a **seam**, not a registry — no id lookup, no table, no name.

**R-2 (parent-corrected) ownership**: P1 owns the COMPOSED-run
explicitation, including this acquisition-site edit; `derive_tidmad_metric`
remains the bounded UN-COMPOSED legacy adapter; **its removal is Step 12's**,
together with the composition root. The other two `derive_tidmad_metric`
sites are bounded, not migrated: `sandbox_executor.py:2009` is a
legacy-caller shim already behind `metric if metric is not None`, and
`denoising_score_single.py:180` is the TIDMAD scoring child's Step-06
re-derivation contract — a composed **non-TIDMAD** run never reaches that
child (D14 scored Pets/DAVIS through the seam route), and wiring a composed
metric across that boundary is **P6's closure surface** (§12).

### 5.4 Subprocess transport emission

The sandbox argv builders (beside the existing `--dataset_profile_json`
emissions at `sandbox_executor.py:1384/:1732/:2048`) append
`transport_argv(bound_impl)` **iff a task-data-path binding is active**.
Un-composed runs emit nothing — child argv is byte-identical, and the
children keep regime A through their existing `nullcontext` branch. If this
turns out to require *reshaping* an argv builder rather than appending to
it, the reshaping is Step 11's and P1 records the finding instead of
absorbing it (parent §23).

### 5.5 Task-config override seam (the singleton becomes an adapter)

`workflows/task_config.py` gains a run-scoped ContextVar override
(`bind_task_config(values)` holding the composed
`task_description`/`forward_contract`); `load_task_config()` returns the
bound values when set and falls back to the YAML+cache path when not. All
consumers (§2.2) keep their call sites; the **authority** moves to the
composition on the composed path, and the module global survives exactly as
the parent's "legacy compatibility adapter — a way to obtain the value,
never the authority". Step 12 later supplies the same composition value from
a package without touching any consumer — the §24 freeze-time test passes
by construction.

### 5.6 `RestoredState` as one launcher parameter

`run_workflow`'s nine `restored_*`/`accumulated_*` parameters are replaced
by ONE `restored_state: RestoredState | None = None` (resume's own type —
09.5a §16 allows it across the launcher edge; `ChainState` still never
crosses). Internal unpacking happens once, feeding `ChainState.from_restored`
and the three non-`ChainState` consumers (`:2107`, `:1842`, `:2052`)
unchanged. Atomic migration of all 3 production callers + the calling test
files; **no compatibility wrapper** (09.5a rule 2 applies unchanged).
Signature: 28 − 9 + 1 (`restored_state`) + 1 (`task_composition`) =
**21 parameters**.

### 5.7 S7 repair — parameters, not pulls

`validate_experiment_completeness` gains `declared_health_peek: list[int]`
and the scalar-key expectation as explicit parameters;
`validate_phase1_baseline` gains `full_scope_num_files: int` (or the
resolved scope directly). `scripts/run_comparison.py` supplies today's
values from the profile it already has. Behaviour identical; the ambient
`resolve_dataset_profile()` calls and the `TIDMAD` import leave generic
core. The frozen record key `denoising_score` is **not** renamed (D1 frozen
names).

### 5.8 Binding lifetime — an explicit frozen invariant

For **every** composed binding (data path · profile · metric · task
config):

> **The binding becomes active BEFORE the first production consumer of its
> semantic family, remains active across the complete logical run/iteration
> region containing ALL consumers of that family, and is reset with the
> existing token/`finally`-safe context-manager idiom. Nested or sequential
> runs in one process never observe each other's values.**

The hazard this exists to kill: `task_config` wrapped around the
proposer/tuner while the planner, a literature-review call or the
interpreter reads the default YAML from *outside* the region — a composed
run silently mixing two task descriptions.

**Acceptance is semantic reachability, not call-site enumeration**: a
deterministic **consumer-reachability matrix** proves that in a composed
run every actually-reachable consumer family reads the SAME composed
authority —

| family | consumer proven |
|---|---|
| planner | `{TASK_DESCRIPTION}` substitution (`llm_bridge.py:1001` path) |
| literature review | its 3 template substitutions (when lit-review is enabled in the fixture) |
| proposer | `_render_task_background` + `load_task_config()` reads |
| implementor | its rendered-block reads |
| interpreter | both system-prompt substitutions |

plus a **leak test**: two sequential runs (composed A → un-composed, and
composed A → composed B) observe no cross-contamination. Consumer call
sites are NOT changed where the loader override makes that unnecessary.

### 5.9 Semantic fingerprint vs diagnostic provenance (Q-P1-2)

Two different things, deliberately separated as two fields (§4):

```text
semantic_fingerprint = sha256 over a CANONICAL serialization of:
    resolved semantic values (task_description, forward_contract,
        dataset-profile canonical dump, metric spec, health binding STATE
        + the composed health config's content identity,
        interpretation-blocks value)
  + declaration CONTENTS (not their paths)
  + plugin CONTENT digests (not their locations)
  + stable binding identities (e.g. the data-path impl's declared id)

EXCLUDED: machine-local absolute paths, workspace locations, load order,
          any relocation-only provenance.
```

* Composed run: the fingerprint joins `run_invariants_lock.json` as a new
  key; resume with a changed fingerprint **fails closed** at the existing
  invariant boundary, with a diagnostic naming what class of content moved.
* Un-composed run: the key is **ABSENT** — not `null` — so the legacy lock
  is byte-identical (C0 parity covers it).
* `provenance` (paths, origins) remains available for diagnostics and the
  ledger, and is **never** hashed into the lock identity.

---

## 6. Three-task binding matrix (source-grounded)

| binding | TIDMAD | Pets | DAVIS | generic source/contract |
|---|---|---|---|---|
| task data path | `tidmad` impl (`tidmad_data_path.py`), today via compatibility default | `oxford_iiit_pet` impl (`pets_data_path.py`), today bound only in the Gate runner (`run_pets_gate2.py:144`) | `davis_future_prediction` impl, same (`run_davis_gate2.py:136`) | **resolved impl on the composition** (§5.2a); registry + `bind_task_data_path` + `transport_argv` |
| dataset profile | shipped `TIDMAD_PROFILE` (today the ambient fallback) | pack manifest-backed profile | pack clip-manifest profile | `DatasetProfile` + `load_dataset_profile` (fail-closed) |
| primary metric | `TidmadDenoisingMetric` — today derived at tuner `:541` | `AccuracyMetric` ← `declared/metric_accuracy.json` (**higher**) | `GlobalMseMetric` ← `declared/metric_mse.json` (**LOWER**) | `metric_spec_from_declaration` + implementation plugin ref → `EvaluationMetric` |
| Health family | `configs/task_health/tidmad.yaml` — today via `LEGACY_OMITTED` | pack `declared/task_health.yaml` (state C, today only in the Gate runner) | same | 08b `TaskHealthBinding` states + plugin digest pinning |
| interpretation blocks | `configs/task_interpretation/tidmad.yaml` — today via the default-path constant | none declared ⇒ `None` ⇒ nothing rendered | none declared ⇒ `None` | `InterpretationTaskBlocks` (09b) |
| task description / forward contract | `configs/task_config.yaml` — today the module-global singleton | pack-owned equivalent (composed value) | same | `ForwardContract` schema + §5.5 seam |

Same interface, different supplied values; **zero task-name branches** —
the composition never contains the string "tidmad" as a discriminator, only
ids that implementations declare about themselves.

**Fourth-task adversarial case**: a conforming new task supplies a
composition manifest + a data-path plugin file + a metric implementation
plugin file + (optionally) a task-health YAML with its own plugin refs + an
interpretation YAML + task-config values. Framework files edited: **0**.
Central registry/table entries: **0** (registration happens by loading the
task's own plugin — the 08b out-of-tree pattern). Task-name branches: **0**.
Workflow/resume/prompt-routing edits: **0**. Proven executable by C4's
extension proof + structural census (§9), not by inspection.

---

## 7. Explicit non-goals

1. Pets/DAVIS running the exploration loop (P6), and any change to the
   hand-written Gate runners (Q-10-5 retirement is P6's, after claim
   transfer).
2. Any direction-site migration (P2a) or secondary-metric work (P2b) — the
   composition schema deliberately has **no** `secondary_metrics` field in
   P1; P2b adds it additively.
3. The physical data root / sandbox data-dir behaviour (Step 11, parent
   default 6).
4. The scoring-subprocess metric re-derivation for composed non-TIDMAD runs,
   and child-side availability of OUT-OF-TREE data-path plugins in
   subprocesses (P6 hand-offs, §12).
5. Removing `derive_tidmad_metric`, `TIDMAD_PROFILE`,
   `LEGACY_DEFAULT_TASK_INTERPRETATION_CONFIG`, `LEGACY_OMITTED` or the
   task-config YAML default — they remain the bounded legacy adapters until
   Step 12 externalizes the source of the whole set.
6. Any change to tuner policy, retry/round semantics, HealthGate actions,
   prompts' rendered bytes on the un-composed path, persisted record names,
   or the frozen metric formula.
7. `vocab_link_confirmations` / `accumulated_key_findings` lifecycle (P5) —
   P1 only changes their *transport packaging* via §5.6, not their
   ownership.
8. Launcher width (audit B-4): P1 adds ONE flag and does not decompose the
   780-line parser.

---

## 8. Module / responsibility structure (parent §19.3 preflight)

| file | now (LOC) | P1 change | owners after |
|---|---|---|---|
| `workflows/task_composition.py` | — (new) | schema + loader + plugin-ref resolution + fingerprint, est. 300–450 LOC | ONE: run-scoped task composition |
| `workflows/model_exploration.py` | 2,950 | + `task_composition` param & bindings field; bind-context wiring around the loop; `restored_state` collapse (net **negative** param count); NO new phase in `run_workflow` | unchanged set |
| `workflows/run_bindings.py` | 132 | +1 field | unchanged |
| `workflows/task_config.py` | 302 | + ContextVar override seam (~30 LOC) | unchanged |
| `execute_tools/evaluation_metric.py` | ~760 | + `bind_run_metric`/`resolve_bound_run_metric` (~25 LOC) | unchanged |
| `execute_tools/task_data_path.py` | 364 | **AS BUILT: +1 accessor** (`active_task_data_path()` — the binding WITHOUT the legacy fallback). The design predicted "none (its transport gains a caller elsewhere)"; C3 found no way to ask "is this run explicitly bound?" without falling back, and an emitter written against the falling-back helper would have put the compatibility id into every legacy child's argv (F-P1-1, D-P1-7). A bounded addition to the existing authority, not a second one | unchanged |
| `core/sandbox_executor.py` | large | + conditional `transport_argv` fragment at 3 argv sites | unchanged |
| `core/run_invariants.py` | — | + `task_health_binding` pass-through + the fingerprint lock key (composed runs only) | unchanged |
| `core/campaign_artifacts.py` | 174 | 3 pulls → parameters | unchanged |
| `sdsc_submission_scripts/run_one_iteration.py` | large | + `--task_composition` flag; 9 kwargs → 1 | unchanged |
| `nodes/ml_hyperparameter_tune_agent/…agent.py` | large | **AS BUILT**: the ONE metric-acquisition line becomes `resolve_bound_run_metric() or derive_tidmad_metric(...)` (C2 scope, §5.3) | unchanged |
| `scripts/run_comparison.py` | large | **AS BUILT**: supplies S7's two task-semantic values at its **two** call sites (`validate_phase1_baseline` and `decide_phase1_reuse` — the second was missed at C4 and found by CI, F-P1-6) | unchanged |

No file gains a second independently-changing semantic owner; the only new
module has one owner. `run_workflow` gains binding *wiring*, not a phase.

**Implementation stop (operator-strengthened):** if C2 would require
inserting a substantial composition-resolution or binding-management PHASE
directly into `run_workflow`, **extract that coherent private boundary
first** rather than growing the existing 1,375-line function. No arbitrary
LOC limit — semantic ownership decides.

---

## 9. Commit decomposition — SEVEN semantic commits (C0–C6)

**Semantic commits are autonomous** (Implementation Working Rules). Before
each commit: inspect the diff scope; run the cheapest authoritative targeted
validation; update this ledger; commit if coherent; continue. **No
per-commit operator approval.** Pause only for a genuine material deviation
(§16 stop conditions) or at the terminal READY FOR OPERATOR REVIEW. No
real-training Gate exists in any commit (§10).

---

### C0 — parity baseline + composition-surface census (no production change)

**1. Goal.** Freeze the "before" so every later commit can prove the
un-composed path unchanged: the LLM-facing parity baseline and an executable
census of the five default sites + transport non-emission. First because
every later commit is measured against it.

**2. Scope.** New test helpers/goldens only; zero production files.
Depends on: nothing.

**3. Implementation plan.**
- [x] Capture the LLM-facing parity baseline of the un-composed path with
      the existing 09.5a harness
      (`tests/helpers/step09_5a_llm_parity_capture.py`) on the deterministic
      fixture: call count / labels / order / methods / system bytes / user
      bytes / structured inputs. **DONE** — base worktree at `3c5b21f4`
      (production tree == `2393aacc`), symlinked to the main checkout's
      `agent_generated` and given its `tidmad_data_config.yaml` per the
      harness docstring. Result: **16 calls, `terminated_with=None`, raw
      payload sha256 `d51a1a335abfb65f46cfffc208dde5d505cc9997ed56782eb63ccfcf8dabfac9`.**
      The raw capture is ~5 MB and is NOT committed; it is reduced to a
      6.5 KB canonical manifest preserving all seven dimensions
      (`tests/helpers/step10_p1_parity_manifest.py`), committed as
      `tests/unit/workflows/goldens/step10_p1_c0_llm_parity_baseline.json`,
      **manifest sha256 `476d5d7c1ec69fa2b76cf8072dd89b5286fba2c44429b79daa64fc540b16778a`**.
- [x] Executable census pinning: the five default sites' current mechanisms
      (exact expressions quoted); `transport_argv` production callers == 0;
      un-composed child argv contains no `--task_data_path_id`; the legacy
      `run_invariants_lock.json` key set (for §5.9's absent-key proof).
      **DONE** — `tests/unit/workflows/test_step10_p1_c0_census.py`,
      24 tests, censuses A/B/C/D.
- [x] Plant-and-catch: temporarily emit the flag on the legacy path; census
      goes RED; revert; record. **DONE** — `transport_argv(TidmadTaskDataPath())`
      appended to the training argv in `core/sandbox_executor.py`:
      census B (`test_transport_argv_has_zero_production_callers`) **and**
      census C (`test_no_child_receives_the_transport_flag_today`) both went
      RED (2 failed / 10 passed); reverted with `git checkout`, `__pycache__`
      cleared, 24/24 green.

**3a. C0 source findings — recorded, not assumed.**

*Finding F-P1-1 (census correction).* §2.1 and parent §3.8 describe the
task-data-path binding as untouched in the parent process. **Measured: one
parent-side CONSUMER already exists** —
`agent/skills/evaluate_time_skill/wrapper.py` calls
`resolve_bound_task_data_path()` in the GPU warmup probe (D14-1 C5). What
does NOT exist anywhere in the parent is a `bind_task_data_path` call
(measured: **0** bind sites outside the two Gate runners and the training
child). *Implementation consequence*: C3's emission must be conditional on an
**active binding**, never on `resolve_bound_task_data_path()` — that helper
falls back to the compatibility implementation, so an unconditional parent
emission would put `--task_data_path_id tidmad` into every legacy child argv
and break mandatory parity. There is currently no public "peek the binding
without falling back" accessor; C2/C3 add one bounded read on the existing
authority (not a new registry). *Validation consequence*: pinned by
`test_the_measured_binding_topology_of_the_parent_process` (0 binds, exactly
1 resolve at the named file).

*Finding F-P1-2 (registration mechanism).* `resolve_task_data_path(None)`
raises unless `execute_tools.tidmad_data_path` has been imported —
registration is an import side-effect (`register_task_data_path(...)` at that
module's end), and there is no central table. This is the same mechanism a
composed run's plugin ref will use, which is why C1's loader registers by
loading the task's own plugin file rather than by editing anything.

*Finding F-P1-3 (parity-instrument coverage, honest limitation).* The 09.5a
harness fixture terminates inside the proposer (3 structural attempts against
a recorder returning `{}`), so the 16 captured calls cover the **interpreter**
and **proposer** families only — planner, literature review and implementor
are NOT reached by it. The instrument is kept unchanged for comparability with
09.5a. *Consequence*: the un-composed byte-preservation of the three unreached
families is owned by targeted C2 tests on the `load_task_config()` seam (an
un-composed process must observe the identical values and identical caching),
NOT claimed from this capture. §5.8's composed-run reachability matrix is a
separate obligation and still covers all five families.

**4. Validation plan.** Unit: the census module itself. No integration, no
Gate.

**5. Acceptance criteria.**
- [x] Baseline artifact committed with the recorded payload sha256
      (raw `d51a1a33…fac9`; committed manifest `476d5d7c…778a`).
- [x] Census green at C0; planted-offender evidence recorded (RED → green).
- [x] The parity REDUCER is itself discriminative: all seven dimensions plus
      call count, order and termination mutated in turn, each reported
      (`TestParityManifestIsDiscriminative`, 10 parametrized cases). Without
      this the mandatory parity evidence could pass for the wrong reason.

**6. Failure/edge cases.** Harness worktree path-sensitivity (09.5a C5c's
false positive — run both sides in worktrees sharing one `agent_generated`).
**Observed and handled**: the base capture was run in
`<scratch>/base_wt` with `agent_generated` symlinked to the main checkout and
`tidmad_data_config.yaml` copied in; C6 repeats the same preparation on the
head side.

**7. Verification commands (record counts + wall time after run).**
- [x] `.venv/bin/python -m pytest tests/unit/workflows/test_step10_p1_c0_census.py -q`
      → **24 passed in 2.12s**.
- [x] `.venv/bin/ruff check` + `ruff format --check` on both new files → clean.
- [x] parity capture: `cd <base_wt> && <repo>/.venv/bin/python
      tests/helpers/step09_5a_llm_parity_capture.py <out>.json`
      → `calls=16 terminated=None sha256=d51a1a335abfb65f` (~40 s wall).

**8. Commit boundary.** Test-only; no unrelated cleanup.

---

### C1 — `RunTaskComposition` + `compose_run_task_bindings` (value + loader + fingerprint)

**1. Goal.** The one composition authority exists: typed value, fail-closed
loader, plugin-ref resolution, canonical fingerprint. Separate from
consumption so the contract is reviewable before anything consumes it (the
PR, not the commit, is the coherence unit — C2/C3 land in the same PR).

**2. Scope.** `workflows/task_composition.py` (new); its unit tests.
Depends on: C0.

**3. Implementation plan.**
- [x] `RunTaskComposition` frozen dataclass, fields per §4 — including the
      **resolved `task_data_path` implementation object** (§5.2a), the
      `semantic_fingerprint`, and diagnostic `provenance`; ownership guard
      derived from `chain_state_field_names()` intersection == ∅
      (planted-offender proven). **DONE** — `workflows/task_composition.py`
      (~760 LOC incl. docstrings). `task_data_path_id` is a **property over
      the resolved object**, deliberately not a stored field, so the carried
      id and the carried implementation cannot disagree.
- [x] YAML manifest schema + `compose_run_task_bindings(path)` (Q-P1-3: one
      manifest, explicit refs, small scalars inline): resolve the data-path
      plugin ref → load/register → the RESOLVED impl on the value; profile
      via `load_dataset_profile`; metric via declaration +
      implementation ref; health binding states (explicit path or `none`;
      **omission of the block is a composition error** — `LEGACY_OMITTED`
      unreachable from a composition); interpretation blocks via the
      existing loader or `none`; task description/forward contract via the
      existing validators. **DONE** — six manifest sections, five required;
      refs resolve against the MANIFEST's directory (never the cwd).
- [x] Fail-closed on: missing file, unknown key, unknown/misspelled plugin
      ref, unregistered/duplicate data-path id, spec/impl mismatch
      (declaration id ≠ implementation's spec id), empty task_description.
      Error messages name what was found and what is registered; none
      mentions or falls back to TIDMAD. **DONE** — 20 negative cases.
- [x] `semantic_fingerprint` per §5.9 (canonical serialization; content
      digests; NO absolute paths), `provenance` separate. **DONE.**

**3a. C1 decisions — recorded.**

*D-P1-1: two ref forms, one mechanism.* A symbol is named either as
`file:` + `symbol:` (an out-of-tree plugin executed by path — the 08b /
model / loss loader idiom, and the form whose CONTENT digest joins the
fingerprint) or as `module:` + `symbol:` (an importable dotted module, for
implementations that already ship in-tree). Exactly one of the two, enforced.
Neither form is a table: the framework never maps a task identity to a
symbol; the manifest names its own binding. This is what lets TIDMAD compose
through the *same* loader as the fourth task — if TIDMAD had needed a special
affordance, the zero-edit claim would be untestable.

*D-P1-2: the composed profile is bound while the task config loads.*
`load_task_config` runs Step-03's `resolve_model_io_contract` cross-check
against the AMBIENT profile's class count (`task_config.py:_dataset_num_classes`).
Composing without the profile bound would validate a composed task's contract
against TIDMAD's topology — a wrong answer that looks like a passing check. So
`_compose_task_config` runs under `bind_dataset_profile(profile)`, and the
profile is therefore resolved BEFORE the task config in
`compose_run_task_bindings`. Ordering here is load-bearing, not incidental.

*D-P1-3: re-composition returns the REGISTERED object.* An already-registered
id resolves through the registry rather than registering a second instance of
the same class. Otherwise the parent would bind object A while the child
resolved object B — identical class, different object, and every id-based
assertion would still pass. One id, one object.

*Finding F-P1-4 (caught by C1's own test, fixed in C1).* The
missing-required-section refusal read *"…would silently resolve TIDMAD"* — a
task-name literal on the composition surface, and a message that would name
another task while refusing a fourth task's manifest. Rewritten to name the
framework's legacy compatibility default without naming a task. The test that
caught it now runs over **four** distinct refusal paths and asserts none of
`tidmad`/`pets`/`oxford`/`davis` appears.

*Scope note (honest labelling).* The Pets and DAVIS `dataset_profile.json` /
`task_config.yaml` under `tests/fixtures/step10_p1/` are **composition
fixtures**, not a claim that either task is loop-executable, and they live
under `tests/` rather than in the `examples/` packs for exactly that reason.
P1 proves the composition CONTRACT on three materially different tasks; P6
owns driving them through the exploration loop (§7 non-goal 1).

**4. Validation plan.** Unit: happy-path composition from a synthetic
fixture task (config + tiny plugin files under `tests/`); one test per
fail-closed branch (≥ 8 negative cases); guard planted-offender test;
fingerprint tests — **relocation parity** (same content, different absolute
location ⇒ SAME fingerprint) and **content divergence** (changed
metric/profile/plugin content ⇒ different fingerprint).

**5. Acceptance criteria.**
- [x] A synthetic fourth task composes end-to-end from config + plugin refs
      with **zero** production-source edits. `spectro_segmentation_v0`
      composes from `tests/fixtures/step10_p1/fourth_task/` — two plugin
      FILES, its own declaration/Health/interpretation/task-config — and the
      string never appears in any production source (asserted).
- [x] Every fail-closed branch raises with a named diagnostic; zero
      branches resolve to TIDMAD. **20 negative cases**: missing manifest ·
      non-mapping · invalid YAML · unknown section · each of the five
      required sections missing (parametrized) · misspelled plugin file ·
      misspelled symbol · unimportable module · both file+module · plugin
      raising on import · id cross-check mismatch · broken profile · unknown
      scoreability contract · non-`EvaluationMetric` implementation · missing
      Health config · Health `none`+`config` together · empty
      task_description · forward-contract typo · and the four-path
      "never names another task" family.
- [x] TIDMAD's own values compose through the same loader (a `tidmad`
      composition fixture referencing the shipped configs) — the
      compatibility ids are ordinary ids.
- [x] Fingerprint relocation-parity and content-divergence tests green,
      with hand-constructed fixture pairs. Relocation: two copies of one
      package at different absolute paths ⇒ SAME fingerprint, while
      `provenance.manifest_path` differs. Divergence: **six** parametrized
      content classes (metric declaration · dataset profile · plugin content
      · task description · interpretation prose · Health config content) each
      change it. Plus cosmetic-respelling parity (`./plugins/x.py` ==
      `plugins/x.py`).
- [x] **Mutation-proven load-bearing.** (i) Adding the plugins' absolute
      paths into the hashed payload turned relocation-parity and
      cosmetic-respelling RED (2 failed / 46 passed). (ii) Replacing
      `content_sha256` with a constant in `canonical_identity` turned the
      plugin-content divergence case RED (1 failed / 47 passed). Both
      reverted; caches cleared; 48 → 51 green.
- [x] The ownership guard is proven to RUN and to be DERIVED: monkeypatching
      `chain_state_field_names` to claim a real composition field makes
      construction raise `TypeError`.

**6. Failure/edge cases.** Duplicate plugin registration (existing refusal
surfaces, not bypassed); relative refs (resolved against the manifest's
directory, documented); a plugin file that raises on import (propagate with
the ref named). **All three covered**; the import-failure path also rolls the
module out of `sys.modules` so a corrected plugin can be retried in-process.

**7. Verification commands.**
- [x] `.venv/bin/python -m pytest tests/unit/workflows/test_step10_p1_c1_composition.py -q`
      → **51 passed in 1.17s**.
- [x] Adjacent suites (C0 census + `test_task_config.py` +
      `test_task_data_path.py`) → **111 passed** total, 0 failed.
- [x] `ruff check` + `ruff format --check` on touched files → clean.
- [ ] `pyright` — **NOT RUNNABLE LOCALLY**: the vendored pyright binary fails
      on this host's Node (`SyntaxError: Unexpected token =` in
      `pyright/dist/vendor.js`). Recorded rather than claimed; the exact-head
      CI owns the type check (CLAUDE.md "Environment assumptions").

**7a. C0 census updated in this commit, as its own message demands.** The
composition edge resolves through the registry for the D-P1-3 idempotency
path, so `test_the_measured_binding_topology_of_the_parent_process` now
allows exactly two resolve sites (the pre-existing warmup probe + the
composition edge). The invariant that actually matters was added as its own
test: **`workflows/model_exploration.py` resolves NOTHING** — §5.2a's sharp
edge, stated where it can fail.

**8. Commit boundary.** New module + fixtures + tests; the C0 census update
that the new module's own resolve site requires.

---

### C2 — carrier + workflow consumption + lifetime + lock integration

**1. Goal.** The composed value actually governs a run: `run_workflow`
accepts it, `WorkflowRunBindings` carries it, families 1/2/3/5 + task-config
consume it through their existing seams, the metric seam feeds the tuner,
the fingerprint joins the lock, and the §5.8 lifetime invariant is proven.
One commit because a value carried-but-not-consumed — or consumed by half
the families — is exactly the mixed explicit/ambient intermediate state
Q-10-1 forbids.

**2. Scope.** `model_exploration.py` (param, bindings field, bind-context
wiring, `:1978` interpretation branch), `run_bindings.py` (+1 field),
`run_invariants.py` (pass-through + composed-only lock key),
`task_config.py` (override seam), `evaluation_metric.py` (`bind_run_metric`
seam) + the tuner's one-line acquisition change
(`ml_hyperparameter_tune_agent.py:541`). Depends on: C1.

**3. Implementation plan.**
- [x] `run_workflow(task_composition: RunTaskComposition | None = None)`;
      bindings field; ownership guard still green. **DONE** —
      `WorkflowRunBindings` 24 → **25** fields.
- [x] Composed: bind data path + profile + metric + task-config for the
      complete consumer region (§5.8); pass `task_health_binding` through
      `build_run_invariants` → `materialize_effective_config`; pass
      `interpretation_blocks` at the `InterpretationInput` construction;
      fingerprint into the lock (composed only; key ABSENT otherwise).
      **DONE.**
- [x] Un-composed: every branch takes today's exact path. **DONE** — 2,874
      workflows+core, 1,234 tuner and 1,625 execute_tools tests unchanged.
- [x] Tuner: `resolve_bound_run_metric() or derive_tidmad_metric(...)`.
      **DONE**, and the census now pins the SHAPE (bound first, legacy
      second) rather than the old bare call.

**3a. C2 decisions — recorded.**

*D-P1-4: the binding is entered at the composition EDGE, and the workflow
REFUSES a composition that is not bound.* §5.2 says "the workflow wraps the
per-iteration execution". Implementing it literally inside `run_workflow`
required either reindenting ~1,150 lines into a `with` block, or duplicating
the 21-parameter signature into a private delegate — the first unreviewable,
the second exactly the "same complexity in a different file" 09.5a names as a
non-decomposition. Neither is what §8's implementation stop is asking for.

What is implemented instead: `bind_run_task_composition(composition)` — ONE
`ExitStack` in `workflows/task_composition.py` — is entered by the caller that
CREATED the composition (the launcher, or the module CLI; C5 wires them), and
`run_workflow` calls `verify_composition_is_bound(task_composition)` at entry.
Three properties follow that binding-inside would not have given:

* the binding's lifetime is the composition's lifetime, at the one place §5.1
  already says composition happens;
* the region covers the STARTUP pre-flight as well as the loop, which is
  required — scope resolution and Health materialisation both read the run's
  profile before iteration 1;
* a half-composed run is impossible rather than merely unlikely: the
  workflow refuses, by family name, before any LLM call. The four-way
  partial-bind test (one family withheld at a time) is what pins it.

`run_workflow` therefore gains ONE parameter, one guard call and no phase.

*D-P1-5 (S1 repair): the module-level `TIDMAD` import leaves generic
orchestration.* `model_exploration.py:103` imported
`TIDMAD as _DATASET_CONFIG` and resolved the run's scope against it at three
sites. On a composed run that is simply wrong — a composed 4-file task would
have had `resolved_data_scope` and `scope_is_partial` computed from TIDMAD's
20 files. Replaced by `resolve_dataset_profile().dataset`, read once into
`_run_dataset`. **Byte-identical when un-composed**: `TIDMAD_PROFILE.dataset`
IS the `TIDMAD` singleton (`is`, verified). This is the concrete content of
§3's "zero ambient TIDMAD semantic authorities on P1-owned orchestration
surfaces" — `model_exploration.py` now imports no task singleton at all.

*D-P1-6: `task_config_values()` carries the two validated keys, not the raw
mapping.* `load_task_config` passes extra top-level YAML keys through
verbatim; the composed override reconstructs `task_description` +
`forward_contract` from the frozen fields instead. Measured first: those two
are the only keys any production consumer reads, and the shipped
`configs/task_config.yaml` declares nothing else. Carrying an unvalidated
grab-bag would have made the composition a config bag, which §4 rejects.

*Finding F-P1-5 — a merged guard with a moving oracle (bounded in-passing
repair).* `tests/unit/workflows/test_step09_5a_c5_llm_facing_parity.py`
computed its census as `git diff <09.5a base> HEAD`. That was correct exactly
once — while HEAD was 09.5a's own branch tip. Merged, the oracle silently
became "09.5a plus everything committed after it", so the next PR to add a
production file inherits a red census describing somebody else's footprint.
P1 hit it first (`workflows/task_composition.py`). **Classified**: test
scaffolding, pre-existing, not caused by P1's semantics — verified GREEN at
the merge base `3c5b21f4` and RED on this branch. **Smallest fix**: pin the
range's endpoint to 09.5a's merged head `2393aacc`, so the census keeps
asserting the same historical fact it was written to assert. Verified the
pinned range reproduces the expected production set EXACTLY (11 files, 0
unexpected, 0 missing). This preserves the claim and is the repository's own
frozen-manifest rule (expected evidence is captured and pinned, never
recomputed against a moving tip). **Broader finding tracked, not widened
into**: any other merged guard using `git diff …HEAD` has the same defect —
recorded for the Step-10 parent's follow-up list rather than fixed here.

**4. Validation plan.**
- Unit: a pseudo-mode composed run (synthetic task from C1) reaches the
  tuner with the composed profile/metric/health/interpretation values
  (assert on the actually-consumed objects — `is`-identity where the seam
  guarantees it).
- **Consumer-reachability matrix** (§5.8): planner · literature review ·
  proposer · implementor · interpreter all read the composed
  task-description authority in a composed fixture run.
- **Leak tests**: composed→un-composed and composed-A→composed-B sequential
  runs show no cross-contamination.
- **Lock tests**: composed resume with a changed fingerprint fails closed at
  the existing invariant boundary; legacy lock byte-identical to the C0
  capture.
- Parity: un-composed pseudo-mode run — persisted artifacts + LLM payload
  bytes unchanged vs the C0 baseline.
- The 09.5a structural censuses (single construction site; no bare-local
  reads; single-writer) stay green.

**5. Acceptance criteria.**
- [x] Composed run: consumed profile **IS** the composed object; consumed
      metric **IS** the composed instance (id `band_coverage_error`,
      direction `lower`); the task-health binding reaches
      `materialize_effective_config`'s keyword; interpretation blocks are the
      composed value; prompts render the composed task_description. Asserted
      at the PRODUCTION seams, never against the composition's own fields.
- [x] Reachability matrix: all five families PASS — planner, literature
      review, proposer, implementor, interpreter each read the composed
      description through the expression their own production code uses, and
      the three that render assert the composed text is present AND the
      legacy text ("SQUID") is absent. Anti-vacuity: un-composed, the same
      expressions render the legacy description.
- [x] Leak tests PASS: composed→un-composed, composed-A→composed-B, NESTED
      A(B)→A restoration, and an exception raised inside the region — all
      four ContextVars unbound afterwards in every case.
- [x] Lock: composed-resume mismatch refusal PASS; un-composed→composed
      mismatch refusal PASS; the un-composed lock OMITS the key (never
      `null`) PASS; an omitted key parses back as `None` PASS.
- [x] Un-composed: **26 C2 tests + 2,874 workflows/core + 1,234 tuner +
      1,625 execute_tools all green**, including the 09.5a C0 deep-equal
      input oracle and the structural censuses. LLM payload byte parity
      against the C0 baseline is re-proven at the C2 head — see §5a.
- [x] `run_workflow` gains exactly one parameter in this commit; no new
      phase inside it (see §8's implementation stop) — it gains ONE
      parameter, ONE guard call, and zero phases (D-P1-4).
- [x] **Mutation-proven load-bearing.** (i) Dropping `bind_task_config` from
      the ExitStack — the §5.8 hazard, a region that covers some families and
      not others — turned 3 RED including the reachability matrix. (ii)
      Removing the token reset from `bind_run_metric` turned 4 RED including
      all three leak tests. Both reverted; 102 P1 tests green.
      *Hygiene note*: reverting (ii) with `git checkout` restored the
      COMMITTED file and silently discarded the uncommitted C2 seam — the
      exact hazard the project's mutation-hygiene rule names. Caught
      immediately (16 RED), re-applied, re-verified. Recorded because the
      failure mode is a mutation "revert" that quietly deletes real work.

**5a. Un-composed LLM-facing parity at the C2 head — PASS.**

The first commit that touches existing production code is the first that
could break the mandatory preservation property, so parity was re-proven
here rather than deferred to C6.

```text
base worktree  3c5b21f4  (production tree == master 2393aacc)
head worktree  63389b89  (C2)
both prepared identically: agent_generated symlinked to the main checkout,
tidmad_data_config.yaml copied in (the 09.5a C5c worktree caveat)

base: calls=16 terminated=None raw sha256 d51a1a335abfb65f…fac9
head: calls=16 terminated=None raw sha256 d51a1a335abfb65f…fac9

seven-dimension manifest sha256, BOTH sides:
  476d5d7c1ec69fa2b76cf8072dd89b5286fba2c44429b79daa64fc540b16778a
diff_manifests(base, head) == []   ← call count · order · labels · methods
                                     · system bytes · user bytes
                                     · structured inputs, all exact-equal
```

**Verdict: EXACT PARITY. Gate 1 remains NOT REQUIRED** (§0, §10 item 5).

Coverage limitation restated honestly (F-P1-3): this instrument's fixture
terminates in the proposer, so those 16 calls are the interpreter and
proposer families. Byte-preservation for the planner, literature review and
implementor is owned by `test_step10_p1_c2_consumption.py`'s
`test_the_matrix_is_not_vacuous` plus the un-composed half of the
reachability matrix — the same `load_task_config()` expression each of them
uses, asserted to still return the legacy description when nothing is bound.

**6. Failure/edge cases.** ContextVar leakage (token-reset context
managers); a composed run whose profile disagrees with `data_scope`
(existing DataScope validation fires — asserted); resume of a composed run
re-supplies the composition each iteration (launcher's job, C5).

**7. Verification commands.**
- [ ] `.venv/bin/pytest tests/unit/workflows/ tests/unit/core/test_resume.py -q`
- [ ] `.venv/bin/pytest tests/unit/agent/tune_ml_hyperparam_agent -q -k metric`

**8. Commit boundary.** Consumption only; no transport emission (C3), no
launcher flag (C5).

---

### C3 — subprocess transport emission (+ reachability proof)

**1. Goal.** The binding stops stopping at the process boundary: the sandbox
emits `transport_argv` when a data-path binding is active; the waiting child
side becomes reachable. Separate commit — distinct failure class
(argv/spawn) and census.

**2. Scope.** `core/sandbox_executor.py` (3 argv sites); tests. Depends on:
C2.

**3. Implementation plan.**
- [x] Append `transport_argv(bound_impl)` iff a binding is active; never on
      the legacy path. The id emitted is the resolved impl's OWN declared id
      (§5.2a) — the signature already enforces this. **DONE** — ONE module
      helper `core/sandbox_executor._task_data_path_argv()` unpacked with
      `*` into each of the three argv literals. **Pure addition: 29 lines
      inserted, 0 deleted** (`git diff --stat`), so no argv builder was
      RESHAPED and the Step-11 escape hatch (parent §23) was not triggered.
- [x] Reachability test that FAILS when the parent stops emitting: child
      argv parsed → `resolve_transported_task_data_path` → the same
      registered impl. **DONE**, and asserted as `is`-identity with the
      parent's bound object, not merely a matching id.
- [x] Legacy-argv byte-parity assertion (no `--task_data_path_id` in any
      un-composed child argv). **DONE**, reusing C0's real-argv capture
      helper so both sides are measured by one instrument.

**3a. C3 decision — recorded.**

*D-P1-7: the emitter reads `active_task_data_path()`, never
`resolve_bound_task_data_path()`.* The latter falls back to the compatibility
implementation when nothing is bound — correct for a CONSUMER asking "which
implementation should I use", catastrophic for an EMITTER asking "is this run
explicitly bound". Written the other way, every legacy child's command line
would silently gain `--task_data_path_id tidmad`, changing an argv that
predates task binding for runs that composed nothing. This is finding F-P1-1
(C0) paying off: the accessor did not exist, and C3 added it beside the
existing one with the distinction documented at its definition.

**4. Validation plan.** Unit (argv construction both branches; round-trip
reachability); the C0 census flips from "zero emitters" to "exactly these
emission sites" in the same commit, plant-and-catch re-run.

**5. Acceptance criteria.**
- [x] Composed: all three child argv vectors carry the id, exactly once each;
      round-trip resolves the **same object** (`is`) the parent bound.
- [x] Un-composed: argv byte-identical to the C0 capture — the flag is in no
      training, inference or scoring vector; emission stops the moment the
      binding region ends.
- [x] Removing the emission line turns the reachability test RED (recorded):
      deleting the training site's `*_task_data_path_argv()` turned **4 RED**
      — emission (all three sites), exactly-once, scope-ends, and the
      round-trip reachability proof. Reverted; caches cleared; 8 green.
- [x] **Second mutation, the one that matters more.** Rewriting the helper to
      use `resolve_bound_task_data_path()` (the falling-back accessor) turned
      **6 RED** — including `test_the_un_composed_argv_is_unchanged` and
      C0's censuses B and C. Without this counterfactual, "we used the right
      accessor" would be an assertion about intent rather than evidence.
- [x] Suites green after the emission: **2,475 core**, **2,058
      execute_tools + workflows** (1 skipped), 8 C3, 25 C0.

**6. Failure/edge cases.** A transported id unknown in the child (existing
fail-closed path — pinned, `TaskDataPathResolutionError`); Step-11 escape
hatch: argv-builder reshaping ⇒ STOP and record (parent §23). **Not
triggered** — the change is a 29-line pure insertion; no builder was
restructured.

**7. Verification commands.**
- [x] `.venv/bin/python -m pytest tests/unit/core/test_step10_p1_c3_transport.py -q`
      → **8 passed**.
- [x] `.venv/bin/python -m pytest tests/unit/core -q -p no:randomly`
      → **2,475 passed in 78.65s**.
- [x] `.venv/bin/python -m pytest tests/unit/execute_tools tests/unit/workflows -q -p no:randomly`
      → **2,058 passed, 1 skipped in 144.23s**.
- [x] `ruff check` + `ruff format --check` on touched files → clean.

**8. Commit boundary.** Emission only, plus the census-B update the emission
itself requires (its message demands the same commit).

---

### C4 — S7 `campaign_artifacts` parameterization + fourth-task genericity proof

**1. Goal.** Generic core stops pulling TIDMAD ambiently (S7), and the
zero-edit extension claim becomes executable — anchored on **structural
censuses**, not on working-tree state.

**2. Scope.** `core/campaign_artifacts.py`, `scripts/run_comparison.py`
(supplies the values it already has); the extension-proof tests. Depends
on: C1 (proof), none for S7.

**3. Implementation plan.**
- [x] Three pulls → explicit parameters (§5.7); callers updated; behaviour
      pinned by before/after equality on a fixture record set. **DONE**:
      `validate_experiment_completeness` gains REQUIRED `declared_health_peek`
      and `scalar_score_key` (default = the frozen `denoising_score`, D1 —
      parameterized, never renamed); `validate_phase1_baseline` /
      `decide_phase1_reuse` gain REQUIRED `declared_health_peek` +
      `full_scope_num_files`. The local `resolve_dataset_profile` import and
      the `TIDMAD` singleton import are GONE from generic core.
      `scripts/run_comparison.py` — the caller that knows the task — supplies
      `resolve_dataset_profile().health_peek_files` and `TIDMAD.num_files`,
      the same "callers that know the task supply those" contract the
      launcher already follows for the measurement capability.
- [x] Atomic caller migration: **7 call sites** (1 production script, 3
      internal, 3 test modules), no compatibility default anywhere — a
      default on `declared_health_peek` would let a caller silently fall back
      to somebody's assumption again, which is the defect being removed.
- [x] **Fourth-task genericity proof, primary authority** (operator
      correction — a unit test must NOT depend on mutable git working-tree
      state as its semantic oracle): **DONE**,
      `tests/unit/workflows/test_step10_p1_c4_extension_proof.py`, 14 tests.
      * the synthetic out-of-tree task composes and reaches the C2/C3 seams
        (C1–C3 evidence, re-asserted here at the registry boundary);
      * **AST structural census** over **307** production `.py` files: no
        comparison against a task name, no membership test over task names,
        no mapping keyed on one, no subscript by one, no `match`/`case` on
        one. Two known non-counterexamples are named and excluded
        deliberately (`_SCOREABILITY_CONTRACT_TYPES`, keyed on a CONTRACT id
        with no sibling task key; `pets_data_path.py`'s comparison against
        its OWN named constant) — parent §3.8's two, unchanged;
      * the fourth task's id appears in **zero** production files at all —
        not "no branch on it", no MENTION — and in no import list or
        registry bootstrap;
      * **plant-and-catch, two levels.** The detector: each of the five
        dispatch shapes planted and reported AS that shape, plus two
        anti-false-positive cases (a banner string, a comparison against a
        named constant) that a regex census would wrongly flag. The tree
        census: a real `if run_name == "tidmad":` planted in
        `workflows/model_exploration.py` turned it RED; reverted, green.
- [x] A `git diff` snapshot MAY be recorded in the implementation ledger as
      supporting evidence — never as a test oracle. Recorded: the fourth
      task's entire footprint is
      `tests/fixtures/step10_p1/fourth_task/**` (7 files: 2 plugin `.py`, 1
      manifest, 4 declarations). Framework files edited to admit it: **0**.

**4. Validation plan.** Unit for both halves; existing campaign tests stay
green with explicit arguments only.

**5. Acceptance criteria.**
- [x] `core/campaign_artifacts.py` contains zero `resolve_dataset_profile` /
      `TIDMAD` imports (AST-censused, not grepped); validator outputs
      unchanged on the fixture corpus — **57 campaign tests green** across
      the four modules that exercise it.
- [x] Extension proof green (**14/14**); census plant RED evidence recorded;
      infrastructure source edits for the fourth task == **0**;
      task-name branches == **0**; central table/registry edits == **0**.
- [x] Suites after S7: **2,922 core+workflows**, **1,625 execute_tools**
      (1 skipped), all green.

**5a. A test-strengthening this produced, worth naming.** Three test modules
previously relied on the validator pulling `resolve_dataset_profile()` while
they bound a contrast profile — so what they actually asserted was the
AMBIENT mechanism, and the declared value only implicitly. They now pass the
peek set explicitly (from the same contrast profile, so the case under test
is unchanged), which makes the declaration the contract under test rather
than the resolution order. That is the S7 repair showing up in the tests as
well as in the source.

**6. Failure/edge cases.** Legacy records without scope stamps (existing
None-skip behaviour preserved — pinned by the DS6d cases, which now state
their full scope as `len(_FULL_SCOPE)` instead of inheriting it from a
singleton import inside the validator).

**7. Verification commands.**
- [x] `.venv/bin/python -m pytest tests/unit/core/test_campaign_artifacts.py tests/unit/core/test_step02c_campaign_declared_trigger.py tests/unit/execute_tools/test_step02c_c4_file_set_contrast.py tests/unit/execute_tools/test_step02c_checkpoint_c_live_consumers.py -q`
      → **57 passed**.
- [x] `.venv/bin/python -m pytest tests/unit/workflows/test_step10_p1_c4_extension_proof.py -q`
      → **14 passed**.
- [x] `ruff check` + `ruff format --check` on touched files → clean.

**8. Commit boundary.** S7 + proof only.

---

### C5 — launcher: `--task_composition` flag + `RestoredState` collapse

**1. Goal.** The operator can compose a run, and the launcher's restored
transport becomes one typed parameter (the 09.5a C4b hand-off).

**2. Scope.** `run_one_iteration.py` (flag; 9 kwargs →
`restored_state=state`), `run_exploration_test.py`, `model_exploration.py`
(signature + internal unpack + CLI main), the calling test files. Depends
on: C2.

**3. Implementation plan.**
- [x] `restored_state: RestoredState | None = None` replaces the nine
      params; internal unpack feeds `ChainState.from_restored` + the three
      non-carrier consumers unchanged; **all** callers migrated atomically;
      no wrapper. **DONE** — one unpack block near the top of `run_workflow`;
      every downstream reference in the body is untouched, so the diff shows
      the transport change and nothing else.
- [x] `--task_composition <path>` on the launcher (+ CLI main): parse →
      `compose_run_task_bindings` → pass the value. Absent ⇒ `None`.
      **DONE** on BOTH composition edges.
- [x] Launcher argv census extended: the transport flag remains forbidden
      as an operator flag; the composition flag is operator-facing. **DONE.**

**3a. C5 decisions and source findings — recorded.**

*The binding is entered at the launcher, wrapping the `run_workflow` call*
(D-P1-4's consequence). The call is now inside
`with bind_run_task_composition(run_composition):` at both edges, so the
composed authorities are active for the workflow's startup pre-flight as well
as its loop, and `run_workflow`'s own guard refuses the run if they are not.

*The annotation is QUOTED, deliberately.* `core/resume.py` imports
`workflows.model_exploration._add_plugin_to_registries` at module level, so
importing `RestoredState` back eagerly would be a cycle; and
`model_exploration.py` has no `from __future__ import annotations`, so an
unquoted annotation would be EVALUATED when the function is defined. The name
is therefore resolved under `TYPE_CHECKING` and quoted at the parameter. (The
underlying private import is Step 12's to remove — parent §24.)

*Behaviour-preservation argument, stated because it is not obvious.* The nine
parameters defaulted to `None`; `RestoredState`'s containers default to empty
(`[]` / `{}`). Every consumer of the three non-`ChainState` values tests
TRUTHINESS (`if accumulated_gate_exhaustions:` etc.), and
`ChainState.from_restored` applies `or {}` / `or PredictionMemory()` to the
rest — so cold start and "restored nothing" are indistinguishable to every
one of them. That assumption is now an executable test rather than a comment,
so a future change to `RestoredState`'s defaults (a sentinel, say) fails
loudly instead of quietly enabling three cross-iteration branches on a
cold-start run.

*Four test modules UPGRADED, none weakened, none deleted.* Each owned a real
property that survives the collapse in a different shape:

| module | property | how it moved |
|---|---|---|
| `test_step09a_c5_prediction_transport.py` | the restored prediction memory reaches the workflow | now asserts the launcher forwards the CARRIER and — new — **executes** the carry to `ChainState`, which the old signature-level assertion could not do. Strictly stronger |
| `test_step09_5a_c0_census.py` | every `run_workflow` parameter has exactly one ownership class | class B collapses to `{restored_state}`, `task_composition` joins class A, and the vacuity floor is **re-derived to 21** exactly as that test's own message instructed ("re-derive this floor from the new signature rather than deleting the guard"). A new sibling proves the nine retired kwargs are GONE, mirroring C3's transit-leak check |
| `test_health_feedback_wiring.py` | the locked-policy defaults are unchanged | its docstring already said the fingerprint history "stays explicit **until C4**"; C5 is where it moved, and the assertion followed it into the carrier |
| `test_health_feedback_chain_wiring.py` | the launcher forwards the policy + history | regex updated for the new indentation (the call is now inside the `with`), and the history assertion follows the carrier |

**4. Validation plan.** Unit: the nine `state.*` values reach their
consumers equal to before (fixture `RestoredState` round-trip, observed at
the consumers, not the signature); flag parse → composition invoked; 09.5a
signature censuses updated in the same commit. Chain-level pseudo smoke via
the existing launcher tests.

**5. Acceptance criteria.**
- [x] `run_workflow` parameter count == **21**, pinned by the updated census
      (which now asserts equality, not a floor) and independently by C5's own
      test. Measured: `13 class-A + 1 restored_state + 3 capabilities +
      3 DS7 no-ops + launch = 21`.
- [x] Nine-value equality proof recorded AT THE CONSUMERS: a
      `RestoredState` in which all nine values are distinctive is carried
      through `ChainState.from_restored`, and each of the six chain-state
      seeds is asserted on the resulting `ChainState`; the three
      non-`ChainState` values are covered by the falsiness-equivalence test.
      Plus an AST assertion that the unpack reads **exactly** the nine right
      field names — the typo class (`runtime_vocab` where
      `accumulated_key_findings` was meant) produces a wrong run, never a
      raise.
- [x] Un-composed launcher invocation unchanged — **3,465 tests green**
      across `tests/unit/workflows`, `tests/unit/core` and
      `tests/unit/sdsc_submission_scripts`.
- [x] **Mutation-proven.** (i) Dropping `accumulated_key_findings` from the
      unpack → RED. (ii) Mapping `runtime_vocab` to the wrong carrier field →
      RED. Both reverted; 12 green.
- [x] The transport flag `--task_data_path_id` is declared by NO argparse
      call on either edge (censused), so an operator cannot name a data path
      the composition never resolved.

**6. Failure/edge cases.** `restored_state=None` cold start (behaviourally
identical to nine `None`s today — now executably pinned); partial restored
data (existing `RestoredState` defaults govern; no new semantics).

**7. Verification commands.**
- [x] `.venv/bin/python -m pytest tests/unit/workflows tests/unit/core tests/unit/sdsc_submission_scripts -q -p no:randomly`
      → **3,465 passed in 216.71s**.
- [x] `.venv/bin/python -m pytest tests/unit/workflows/test_step10_p1_c5_launcher.py -q`
      → **12 passed**.
- [x] `ruff check` + `ruff format --check` across `tests/ workflows/ core/
      sdsc_submission_scripts/` → clean.

**8. Commit boundary.** Launcher surface + signature only.

---

### C6 — docs sync, final censuses, mandatory parity re-proof, ledger close

**1. Goal.** Terminal evidence at the final executable head; operator map
stays current (doc-sync-before-merge rule).

**2. Scope.** Docs (touched module `.md`s, this ledger); final census run;
parity re-proof.

*Source finding (stale design anchor, recorded not silently dropped):*
`docs/running_chain_test.md` — named in this section at freeze time — **does
not exist** on the merged tree. No canonical operator flag-reference document
exists either; the repository's precedent is that a subsystem's own design
doc IS its operator surface (`docs/design/enable_partial_file_list.md` for
DataScope). This document therefore documents `--task_composition`, and the
doc-sync obligation is discharged against the ONE touched node `.md`.

**3. Implementation plan.**
- [x] Re-run the C0 parity capture at the final head (both sides in
      worktrees sharing one `agent_generated`); record payload sha equality
      across all seven dimensions. **DONE — see §5.**
- [x] Final structural censuses (composition single-authority; five
      defaults quarantined to legacy branches; transport emission sites;
      task-name AST census still 0). **DONE** — 136 P1 tests across the six
      C0–C5 modules, green at the final head.
- [x] Docs updated quoting each new flag/default against merged source.
      **DONE** — `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md`:
      the run-scope binding row and the Step-06 metric bullet now quote the
      real acquisition expression
      (`resolve_bound_run_metric() or derive_tidmad_metric(...)`), name
      `--task_composition` as what makes the first branch reachable, and
      state that `derive_tidmad_metric` is the bounded legacy adapter whose
      removal is Step 12's. No other node or skill was touched by P1.
- [x] Ledger: every checklist ticked with evidence; ONE exact-head CI on
      the final PR head (validation-economy rule).

**4. Validation plan.** Targeted suites named per commit; **no local full
suite** — the formal PR's automatic CI is the canonical exact-head
evidence.

**5. Acceptance criteria.**
- [x] **Parity: payload sha256 equal, all dimensions exact-equal.**

      ```text
      base worktree  3c5b21f4   (production tree == master 2393aacc)
      final worktree 821ea469   (C5 — the final EXECUTABLE head; C6 is
                                 docs + ledger only and cannot move bytes)
      both prepared identically per the 09.5a C5c worktree recipe

      base:  calls=16  terminated=None  raw sha256 d51a1a335abfb65f…fac9
      final: calls=16  terminated=None  raw sha256 d51a1a335abfb65f…fac9

      seven-dimension manifest sha256, BOTH sides:
        476d5d7c1ec69fa2b76cf8072dd89b5286fba2c44429b79daa64fc540b16778a
      diff_manifests(base, final) == []
      ```

      **VERDICT: EXACT PARITY.** Call count · order · labels · methods ·
      system bytes · user bytes · structured inputs all exact-equal. No
      preservation failure; no MATERIAL DEVIATION; **Gate 1 NOT REQUIRED**
      per §0 and §10 item 5. (Coverage limitation F-P1-3 stands and is not
      papered over: this instrument reaches the interpreter and proposer
      families; the planner, literature review and implementor are covered
      by C2's un-composed seam assertions instead.)
- [x] **CI run 1 — `32413960570` on `c202c953`: FAILURE (pyright, 3 errors).**
      Recorded rather than quietly re-run, because one of the three was a
      REAL production defect and the episode is the reason the local
      limitation matters.

      *F-P1-6 — an incomplete atomic migration, caught by the one check that
      could not run locally.* C4 migrated the S7 callers after grepping for
      `validate_experiment_completeness(` and `validate_phase1_baseline(` —
      a pattern that MISSED `decide_phase1_reuse(` at
      `scripts/run_comparison.py:1297`. That call would have raised
      `TypeError: missing 2 required keyword-only arguments` at runtime, on
      the campaign Phase-1 REUSE path — a path no unit test exercises and
      the one a resumed campaign takes. The true caller census is **11**
      sites, not the 7 the ledger recorded at C4. Fixed by supplying the two
      values the sibling call already supplies.

      *Why the required-keyword choice paid for itself*: had
      `declared_health_peek` carried a default, this caller would have
      silently kept resolving the ambient profile, CI would have been green,
      and the defect would have shipped. Making it required turned a silent
      wrong answer into a static error. The ongoing owner is pyright, not a
      new test — a missing required argument is precisely what a type
      checker exists to find.

      *The other two errors* were type-narrowing in
      `workflows/task_composition.py`: a plugin's resolved symbol is `Any`
      by construction, and `register_task_data_path` wants the protocol. Now
      an explicit `cast` whose obligation is DISCHARGED on the next line by
      the registry's own protocol validation — re-checking the four method
      names here would have put a second copy of the protocol definition in
      this module, which §2.5 forbids.

      *Process note, recorded honestly*: pyright cannot run on this host
      (Node v10.19 vs the vendored binary's requirement), which the C1
      ledger recorded as a limitation rather than claiming a local pass.
      This is that limitation cashing out exactly as predicted — the
      exact-head CI is the type checker's only real environment here.
- [x] Exact-head CI SUCCESS id recorded: **run `32415952195`**, tested SHA
      **`ffad7029793e365843ba67e083ccdc2dd84679c4`** (== the final PR head),
      conclusion **SUCCESS**, every step green. Recorded post-merge in this
      status sync rather than in a trailing docs-only push on the PR branch,
      which would have moved the head and invalidated the very run it
      records (`feedback_no_docs_only_ci_pushes.md`).

**6.–8.** Docs-only risks: none; boundary: docs + evidence only; one push
at the genuine final head (no trailing docs-only pushes).

---

## 10. Validation strategy (child-level summary)

1. **Deterministic composition tests** — resolution + every fail-closed
   branch.
2. **Structural censuses** — single composition authority; planted
   offenders; task-name AST census stays 0; transport emission exactness;
   fourth-task genericity census (C4).
3. **Reachability** — the emitted transport reaches the child resolver and
   FAILS when emission stops; the consumer-reachability matrix (§5.8).
4. **Fingerprint/lock** — relocation parity; content divergence; composed
   resume mismatch fail-closed; legacy lock byte-identity.
5. **LLM-facing byte parity of the un-composed path — REQUIRED
   preservation evidence** (C0 baseline, C2 check, C6 re-proof: call count
   · order · labels · methods · system bytes · user bytes · structured
   inputs). A delta is a preservation FAILURE to diagnose and fix. **Gate 1
   is NOT a substitute for broken byte parity.** Expected posture:
   parity PASS ⇒ **Gate 1 NOT REQUIRED**.
6. **Gate 2 NOT REQUIRED** — no unique real-GPU/real-data failure class in
   P1; P6 owns the real multi-task lifecycle.

## 11. Preservation invariants

Un-composed runs: prompts byte-identical; child argv byte-identical;
persisted artifacts, statuses, ordering, retry, resume unchanged (C0
differential); `run_invariants_lock.json` byte-identical for legacy runs
(the composed-only key is ABSENT, §5.9); frozen record names and metric
formula untouched; HealthGate defaults/actions untouched.

## 12. Hand-offs recorded for later children

* **→ P2a**: the bound `MetricSpec` is available via the composition for
  composed runs; legacy runs keep artifact-stamped/reconciled specs; absent
  ⇒ Q-10-2 refusal (parent §8, R-3 precedence).
* **→ P2b**: the composition schema gains `secondary_metrics` additively;
  P2b owns evaluation/transport.
* **→ P6**: (a) composed-metric transport into the scoring subprocess (or
  the seam-scoring route) for non-TIDMAD loop runs; (b) **child-side
  availability of OUT-OF-TREE data-path plugins** — a transported id
  resolves only if the child process has the plugin registered; today's
  children bootstrap built-ins only. P1's reachability proof covers
  registered implementations; the out-of-tree subprocess closure belongs to
  P6/Step 12; (c) runner retirement (Q-10-5).
* **→ Step 11**: physical data root; any argv-builder reshaping discovered
  in C3.
* **→ Step 12**: the composition *source* (out-of-tree package supplying
  `RunTaskComposition` through one root); removal of the five legacy
  adapters; standalone-node CLI composition unification (Q-P1-1).

## 13. Operator questions

**Open: 0.** Q-P1-1 / Q-P1-2 / Q-P1-3 RESOLVED — rulings recorded in §0.1
and implemented at §5.2a / §5.9 / C1.

## 14. Risk register

| risk | mitigation |
|---|---|
| composition value becomes a context bag | field set = bound authorities only; ownership guard; §8 preflight |
| ContextVar seams leak between runs/tests | token-reset context managers; the §5.8 leak tests |
| parity break on the un-composed path | C0 baseline + C2/C6 byte proofs; any delta = preservation failure; intentional change = operator stop |
| the metric seam becomes a second authority | it stores an `EvaluationMetric` produced by existing authorities; census forbids a second spec-from-declaration path |
| a second id→impl resolution appears downstream | §5.2a stores the resolved impl; adversarial item 3 + census |
| fingerprint accidentally path-sensitive | §5.9 exclusion list + the relocation-parity test |
| P2b/P1 schema contention | `secondary_metrics` declared here as P2b's additive extension point |
| signature migration breaks callers silently | atomic migration + 09.5a census updates in the same commit |

## 15. Adversarial review — 20 attacks (operator §13), all closed

| # | attack | verdict |
|---|---|---|
| 1 | Does `RunTaskComposition` contain only bounded task-run semantic authorities? | **PASS** — §4's fields are each an existing subsystem's own type; launch/transit/chain-state/mutable services rejected; guard derived from `chain_state_field_names()` |
| 2 | Is `TaskDataPath` resolved exactly once? | **PASS** — §5.2a: plugin ref → resolved impl at the composition edge; the id is transport/provenance identity only; no downstream id→impl lookup |
| 3 | Does any downstream consumer re-resolve task identity? | **PASS** — every family consumes through its bind seam or the carried value; the only child-process lookup is the transport contract's existing half, named in §12 |
| 4 | Can an explicit composition fall back to TIDMAD? | **PASS** — every fail-closed branch raises; `LEGACY_OMITTED` unreachable from a composition; C1 negative tests |
| 5 | Does the task-config override reach every LLM consumer family? | **PASS** — §5.8 reachability matrix over planner / lit-review / proposer / implementor / interpreter is C2 acceptance |
| 6 | Can ContextVar state leak across sequential/nested runs? | **PASS** — token-reset idiom + the two leak tests (composed→un-composed, A→B) |
| 7 | Does a resumed composed run reject a changed semantic fingerprint? | **PASS** — §5.9 + C2 lock tests: fail closed at the existing invariant boundary |
| 8 | Is the fingerprint independent of absolute filesystem location? | **PASS** — §5.9 exclusion list; relocation-parity test with hand-built fixture pair |
| 9 | Is the legacy run-invariants lock byte-identical? | **PASS** — the key is ABSENT for un-composed runs (never `null`); C0 captures the legacy key set; C2 asserts byte identity |
| 10 | Does the fourth task require any production registration/table edit? | **PASS** — C4: composition + plugin refs only; AST census + plant-and-catch; required count 0 |
| 11 | Does P1 create a central plugin/task registry? | **PASS** — reuses the existing presence-keyed registry and the 08b file-ref pattern; no `TASKS` table (§4 rejected list) |
| 12 | Does P1 duplicate an existing subsystem loader/schema? | **PASS** — §2.5 enumerates the reused authorities; the composition holds their types |
| 13 | Does P1 create a second metric authority? | **PASS** — `bind_run_metric` stores an instance produced by `metric_spec_from_declaration` + a plugin impl; no second derivation path |
| 14 | Is P2a still the only owner of ordering migration? | **PASS** — §7 non-goal 2; no comparison site touched |
| 15 | Is P2b still the only owner of secondary metrics? | **PASS** — no `secondary_metrics` field in P1; declared additive extension point |
| 16 | Are P6 and Step-11 residual surfaces named rather than falsely claimed closed? | **PASS** — §3's narrowed claim; §12 hand-offs incl. the child-side out-of-tree plugin limit |
| 17 | Can Step 12 supply the SAME `RunTaskComposition` interface without replacing it? | **PASS** — Step 12 replaces the *call site* of `compose_run_task_bindings` with a package root producing the same value (§5.5, §12) |
| 18 | Does `model_exploration.py` receive wiring rather than a new mixed-owner phase? | **PASS** — §8's table + the strengthened implementation stop |
| 19 | Is per-commit operator approval gone? | **PASS** — §9 preamble: autonomous semantic commits; pause only on material deviation or terminal review |
| 20 | Is exact un-composed LLM parity mandatory rather than substitutable by a Gate? | **PASS** — §10 item 5, C6 acceptance, §0 Gate rows |

**Material contradictions: 0. Open operator questions: 0.**

## 16. Implementation-transition protocol

* The implementation session starts from current `origin/master`, on a NEW
  implementation branch (never on `step10-parent-design`), re-verifies §2's
  line anchors before editing, and follows C0–C6 with autonomous semantic
  commits.
* **Material deviation stop conditions**: replacing `RunTaskComposition`'s
  frozen public shape; a second run-state carrier; changed scientific
  metric/Health semantics; changed Step-11/Step-12 ownership; task-name
  control flow; an ordinary fourth task requiring infrastructure edits; an
  incompatible public schema; an intentional LLM-facing behaviour change;
  significant new backend architecture not covered by existing plugin
  capabilities. Ordinary source-mechanical differences are NOT stop
  conditions — record and continue.
* After P1 merges: P2a reconciles its `PROVISIONAL(P1)` items; P2b after
  P1 + P2a.

---

*END — REVISION 2 — FROZEN, operator approved 2026-08-20.
Implementation COMPLETE 2026-08-20 on `step10-p1-run-scoped-task-composition`;
final executable head `821ea469`; C0–C6 all ticked with recorded evidence;
mandatory un-composed LLM parity EXACT; Gate 1 and Gate 2 both NOT REQUIRED
and neither was run; zero material deviations; zero open operator questions.
**MERGED 2026-08-20 — PR #241, squash `bcb17e45`, exact-head CI
32415952195 SUCCESS on `ffad7029`; landed master byte-identical to the
validated head.***
