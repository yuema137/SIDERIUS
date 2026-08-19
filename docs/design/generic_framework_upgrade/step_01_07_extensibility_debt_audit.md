# Steps 01–07 extensibility debt audit (read-only; pre-Step-08)

## 0. Status and mandate

**TRIAGE ACCEPTED — operator ruling 2026-08-18.** The ruling ratifies:
A-class forward blockers = NONE; Steps 01–07 are NOT reopened; Steps
08–12 continue under the forward invariant (now roadmap §22.24); the
B-class items in §7.2 are owned by Step 10/12 composition and re-audited
at Step 12 (§22.24.3); the Step-06 metric disposition is ratified as-is
(semantic layer stands; Step 10/12 supplies declaration + `plugin_ref` +
run-scoped resolution + backend adapter; NO interim metric name branches
or central metric catalog in the meantime); §3.5 findings 1–2 are filed
as **issue #234** (blocks Step 08: NO; blocks Step-09 planning: NO; must
be resolved before Step-10/12 external composition acceptance: YES);
finding 3 stays C-class untracked.

Commissioned by the operator
directive of 2026-08-18, in parallel with the Step-08 parent-design
amendments (rev 3 of `step_08_health_check_task_profile.md`). This is a
READ-ONLY architectural audit of the MERGED Step 01–07 surfaces against
the strong extensibility invariant the Step-08 review established. **It
is not authorization to refactor Steps 01–07**: no implementation was
modified, no correction PR is opened, Step 08 is not broadened. Every
finding receives exactly one disposition:

* **A** — forward blocker: correct BEFORE dependent roadmap work (burden
  of proof is on A; requires that the public contract is genuinely
  closed/wrong AND Steps 08–12 build on it AND deferral materially
  increases cost).
* **B** — forward constraint: extensibility debt behind an OPEN semantic
  boundary; record, do not repair now; Steps 08–12 must not reproduce or
  deepen the pattern.
* **C** — post-Step-12 cleanup: legacy/compatibility detail that
  constrains nothing.

Method: three read-only source sweeps (Steps 01–02, 03–04, 05+07;
Step 06 and the plugin-loader inventory audited directly), every
load-bearing claim re-verified against source by the main auditor.
Source state: master `3bf8c269` (+ rev-3 doc edits only). The
distinction the directive calls load-bearing is applied throughout:
**"contract is closed" ≠ "contract is open but the Step-10/12
composition/loading has not landed yet."**

## 1. The invariant and the audit standard

Target (stronger than "no task-name branches"):

> A future user task provides task-specific semantics through **external
> configuration + externally loaded/run-scoped plugins**, without
> modifying SIDERIUS generic infrastructure source (`core/`,
> `execute_tools/`, `agent/`, central registry source, central import
> lists, framework-owned per-task YAML, closed task-semantic enums).
> Built-in tasks may ship in-repo, but their location must not define
> the extension mechanism.

Audit standard (operator, 2026-08-18 — the governing principle):

> **SIDERIUS infrastructure specifies the plugin protocol, not the
> scientific implementation.** Task-specific scientific semantics are
> supplied by externally loadable plugins and configuration. Multiple
> plugin execution forms — Python, executable/script, skill/agent, and
> future backends — may be supported through adapters, but all must
> satisfy the same subsystem-specific semantic contract.

Corollaries applied here: a registry is not evidence of extensibility
(the loading path was traced each time); implementation-form diversity
must sit behind ONE semantic interface per subsystem (never
`if python / elif command / elif skill` semantics); deterministic
scoring stays Python/executable — an LLM skill is one possible backend,
never the definition of "plugin"; and unresolvable references fail
closed (no default metric, no skip→pass).

## 2. The matrix

Columns: external config possible today? · external plugin possible
today? · central source edit currently required? · closed enum/list? ·
disposition · owner/timing. "Config" means the task-side declaration;
"plugin" means task-side code.

| # | Step / surface | Current authority | ext. config? | ext. plugin? | central edit req.? | closed enum? | Disposition | Owner / timing |
|---|---|---|---|---|---|---|---|---|
| 1 | 01 task description + forward contract | `workflows/task_config.py` ← `configs/task_config.yaml` | **NO operator surface** (loader has a `path` param, `task_config.py:86`; no production caller passes it, `:121` CWD default; README documents *editing the tracked YAML* as the task-change path) | n/a (pure config) | **YES** (edit tracked framework YAML) | no (`task_type` free-form, `agent/schemas/task_config.py:89-95`) | **B** | Step 12 composition root (run-scoped task-config binding) |
| 2 | 01 ambient TIDMAD fallback | `task_config.py:74-76` → `resolve_dataset_profile()` → `dataset_config.py:613` `or TIDMAD_PROFILE` | — | — | n/a | no | **B** (silent task default in a generic authority — the pattern 07c/D14 removed elsewhere) | Step 10/12 (explicit binding at the composition root); 08–12 add no new ambient fallbacks |
| 3 | 01 Model-I/O presets | `model_io_resolution.py:117` `PRESETS` (1 entry, no registration fn; unknown → `UnknownPresetError` `:176-179`) | explicit `model_io` declaration works WITHOUT a preset (`preset: str \| None`, `task_config.py:103`) | n/a | only to ADD a preset (optional convenience) | closed dict, but optional | **C** | post-Step-12 (register-or-retire) |
| 4 | 02 DatasetProfile / SampleSet / DataScope | `execute_tools/dataset_config.py` (+`scoring_utils.py`, `sample_set_builder.py`) | YES for its family (`load_dataset_profile(path)` `:616`; `--dataset_profile_json` optional, fail-closed when supplied-but-broken, `denoising_score_single.py:58-66`) | n/a | NO — nothing generic hard-requires it (see §3.2) | zero Literal/Enum in `dataset_config.py`; `trial_strategy` Literal in the builder is framework sampling policy, not task-semantic | **B** (regime-A adapter status is honest and self-labelled, `:565-568`; TIDMAD-bound `validate_sample_set` is family-internal) | Steps 10/12 replace ambient resolution with explicit binding |
| 5 | D14 TaskDataPath (audited because Steps 02/05 route through it now) | `execute_tools/task_data_path.py` | scope objects task-owned, opaque (`:37-41`) | contract OPEN (opaque id `:174-176`, fail-closed `:296-301`, ContextVar binding `:308-318`) — but NO loader: registration is a module-tail import side effect; importers are leaf entry points only; `transport_argv` has **no production caller** (dormant until a non-TIDMAD task spawns subprocesses) | **YES today** (a new impl must live somewhere importable and something in-tree must import it) | no | **B** — the canonical "open contract, missing composition" case | Step 10/12 unified task-pack loading (do NOT build a per-subsystem loader now) |
| 6 | 03 ModelIOContract | `agent/schemas/model_io_contract.py` | YES — external JSON argv-bound (`load_model_io_contract`, consumed at `train_engine_sandbox.py:1875`, `inference_single.py:345`; proven by `examples/*/declared/model_io_contract.json`) | n/a | NO for a new task within {categorical, continuous} | `AxisRole` 3-member "additive"; `OutputSemantic` 2-member DERIVED from tensor structure (`:280-282`); dtypes + `data_shape_class` open strings | **SATISFIES** (model-boundary vocabulary, fixed small universe — does not grow per task; TIDMAD/Pets/DAVIS all fit) | — |
| 7 | 03/04 output-type vocabulary + loader coercion | `plugin_loader.py:82` `("classifier","regressor","hybrid")`; `BUILTIN_OUTPUT_TYPES`; `proposal.py:974` / `implementor.py:191` `Literal["classifier","regressor"]` | — | — | a FOURTH output semantic ≈ 6 declaration sites + ~14 consumer branches across 5 packages | closed, but model-boundary-semantic | **B**, with a named defect: `plugin_loader.py:80-87` **silently coerces** an unknown `PLUGIN_OUTPUT_TYPE` to `"classifier"` (fail-open; violates the repo's own no-default rule at `:206`), and the loader's 3-set disagrees with the validator's 2-set (`ml_code_validator_agent.py:368`). Recommend: file as issue at triage | defect fix = small standalone issue; vocabulary growth = a framework-capability event (Step 10+ if ever), not a per-task cost |
| 8 | 04 model registration / candidacy | `ml_models/plugin_loader.py` + `MODEL_REGISTRY` | YES (config names `model_type`; plugin configs validate against the plugin's own class, `sandbox_executor.py:1164-1170`) | **YES — out-of-tree TODAY** (`SIDERIUS_PLUGIN_DIRS`, per-run replace-not-extend `:112-115`; D14 loaded `examples/<pack>/plugins/` through it) | NO | `ModelConfigUnion` closed for the six builtins but `model_type: str` open + plugin bypass | **SATISFIES** (the strongest surface; the invariant's working precedent) | — |
| 9 | 04 probe realization | `core/runtime_control/probe_wiring.py` + `probe_production.py` | capability passed in, refused if absent (`:225-230`) | loads candidates from the LIVE registry, fail-closed (`:194-203`) | NO | none (zero task/model-name branches in executable code) | **SATISFIES** | — |
| 10 | 04 stale registration docstring | `ml_model_proposal_agent.py:97-99` claims `_promote_model_to_global` registers; real site is `workflows/model_exploration.py:2477`; `MODEL_REGISTRY` also written at `:836` | — | — | — | — | **C** (doc rot, no behavior) | fix in passing whenever that file is next touched |
| 11 | 05 DeliverableSpec | `execute_tools/deliverable_spec.py` | fields open (zero Literals; TIDMAD values are overridable defaults) | n/a | NO for non-TIDMAD tasks (Pets/DAVIS bypass it entirely — zero imports; `task_data_path.py` never imports it) | no | **SATISFIES as a family representation** (TIDMAD-route-only consumer set) | — |
| 12 | 05/06 tuner regime-A hardwiring | `ml_hyperparameter_tune_agent.py:529` `derive_tidmad_deliverable_spec` · `:541` `derive_tidmad_metric` | — | — | **YES — the one true central-edit site on the tuner route**; source self-flags it: "no task declares a metric until Step 12" (`:532-533`) | no | **B** (deliberate, time-bounded regime-A seam; the contract behind it is open) | Step 12 (task-declared metric/deliverable binding at the composition root) |
| 13 | 06 EvaluationMetric / MetricSpec / Scoreability | `execute_tools/evaluation_metric.py` | YES — declaration constructors exist and fail closed (`metric_spec_from_declaration` `:657`, `scoreability_contract_from_declaration` `:641`) | **NO — no metric registry, no plugin_ref, no loader**; binding is direct class construction at call sites (`run_pets_gate2.py:220`, `run_davis_gate2.py:215`, `derive_tidmad_metric` `:712`) | YES for a novel metric implementation today | `MetricDirection = Literal["higher","lower"]` (`:110`) is universal, not per-task; no task enums | **B** — THE canonical example of the operator's two-layer target (§5): the semantic layer (ABC + `MetricResult` normalization + scoreability-before-arithmetic) already matches; the declaration→`plugin_ref`→adapter layer is absent | Step 10/12 unified composition (declaration gains `plugin_ref`; backends as adapters) |
| 14 | 07 TrainingObjective | `models_format_sandbox.py:637` + `loss_models_sandbox.py` | YES (`loss_type="custom"` + open `loss_name` `:651`) | **YES — out-of-tree TODAY** (`SIDERIUS_LOSS_DIRS` two-tier resolution `:253-268`; separate env var by documented design) | NO to RUN; YES only to PROMOTE a kind to first-class (`loss_type` Literal member + `COMPARABILITY_ESTABLISHED_KINDS`, "added by SOURCE AUDIT, never by assumption" — `training_history.py:71-73`) | closed Literal WITH a first-class `custom` escape | **SATISFIES**, with the honest lossy consequence recorded: all external objectives report `objective_kind="custom"` and are stamped `not_established` — distinguishable only by `objective_config_fingerprint` | promotion procedure = audit-gated by design; document it at Step 12 |
| 15 | 07 TrainingHistory / TrainingDiagnosis | `execute_tools/training_history.py`, `agent/schemas/training_diagnosis.py` | — | — | NO | `objective_kind: str` OPEN (`:133`); fingerprint generic (sha256 of the dumped config, `:100-101`, no per-kind table); Diagnosis Literals are framework-policy only (`ok/absent/invalid`, trends); **zero task/objective vocabulary** — "no overfitting/converged labels" is an explicit design commitment | **SATISFIES** | — |
| 16 | 08-subject: health registration | `execute_tools/health_checks/__init__.py` central import list | — | **NO today** | **YES today** | no | being closed by **08b** (Step-08 parent §2.6/§6a — not re-dispositioned here) | 08b |

## 3. Findings that need more than a matrix row

### 3.1 Step 01 — the task description is the least externalizable surface

Two authorities render task content: `workflows/task_config.py`
(prose `task_description` + `forward_contract`, one renderer with two
mirrored node wrappers) and the 07b `TunerTaskRender`
(`agent/prompt_templates/tuner/rendering.py` — built from the
DatasetProfile/ModelIOContract/health authorities, no task file, no
Literals, fail-closed `llm_bridge.py:965-971`). The second is already
clean. The first is the finding: the loader takes a `path` but every
production caller omits it, no CLI/env surface exists, and the
DOCUMENTED way to change tasks is `cp configs/task_config.example.yaml
configs/task_config.yaml` — i.e., **editing tracked framework config is
the current extension path** for task identity. Disposition **B**, not
A: the semantic boundary (a validated YAML any path could supply) is
open; what is missing is precisely the run-scoped binding that
Step 12's composition root owns. Constraint on Steps 08–11: no new
consumer may hardcode the default path; new task-visible semantics
(e.g. Step-08 health facts) bind through task-owned config, never by
adding sections to `configs/task_config.yaml`.

### 3.2 Step 02 — DatasetProfile is an honest adapter, not a required gate

Directly answering the directive's question ("does generic core require
every task to use it?"): **no.** The tuner CLI has no profile flag; the
tuner resolves it ambiently (`resolve_dataset_profile()` "has no
failure mode of its own"); subprocess flags are optional with
fail-closed-when-supplied semantics; the shipped `TIDMAD_PROFILE` is
self-labelled "REGIME-A COMPATIBILITY ADAPTER, not a universal
framework default" (`dataset_config.py:565-568`); Pets/DAVIS verifiably
never import it, binding task-typed opaque scopes through the D14 seam
instead. The debts are (i) the ambient fallback pattern itself (matrix
#2 — a generic accessor that cannot fail and answers TIDMAD), and (ii)
`validate_sample_set` hard-binding TIDMAD constants inside
`scoring_utils.py` — family-internal today because only the TIDMAD
route calls it. Both **B**.

### 3.3 Step 06 — the metric surface against the operator's two-layer target

The operator's target architecture splits declaration
(`EvaluationMetricSpec`: id, direction, primary/secondary, `plugin_ref`,
params, input capability) from implementation (decoded payload + params
→ `MetricResult`), with execution backends (Python / command / skill)
as adapters behind ONE semantic protocol, and Step-06 core never knowing
HOW a metric is computed. Audit verdict: **the semantic half already
complies** — `EvaluationMetric.evaluate` enforces
scoreability-before-arithmetic and normalizes to
`MetricResult`/`NotScoreableResult` for every implementation;
declarations already construct `MetricSpec`/scoreability contracts
fail-closed from external payloads; the metric input is the decoded
payload from `TaskDataPath.read_evaluation_payload` (D14), not
framework internals. **The binding half does not exist**: there is no
metric registry, no `plugin_ref` field, no loader, no adapter layer —
the three implementations are in-repo classes constructed by name at
call sites, and the tuner's construction site is the hardwired
regime-A call (matrix #12). Disposition **B** with a sharp forward
constraint: when Step 10/12 adds the binding layer, it must be the
declaration+`plugin_ref`+adapter shape above — and no interim work may
add a fourth in-repo metric selected by a name branch, which would
deepen the catalog pattern the operator has rejected.

### 3.4 Step 07 — the one surface that fully demonstrates Level-2 extension today

A user's novel scientific objective runs today with zero infra edits:
external plugin file → `SIDERIUS_LOSS_DIRS` → `PLUGIN_LOSS_TYPE` /
`PLUGIN_LOSS_CONFIG_CLASS` / `PLUGIN_LOSS_TARGET_DTYPE` →
`LossConfig(loss_type="custom", loss_name=…)` → two-tier fail-closed
resolution → generic fingerprint → open `TrainingHistory.objective_kind`
→ vocabulary-free `TrainingDiagnosis`. The honest costs are designed,
not accidental: external objectives are mutually indistinguishable at
the `objective_kind` level and permanently `not_established` for
comparability; promotion to a first-class kind is an audit-gated
framework event. This surface is the existence proof that the strong
invariant is achievable in this codebase — Step 08's health design
(§6a) instantiates the same shape.

### 3.5 Named defects (recommend filing as issues at triage; NOT fixed here)

1. **`plugin_loader.py:80-87`** — unknown `PLUGIN_OUTPUT_TYPE` silently
   coerced to `"classifier"` (print warning only). Fail-open at the one
   place a genuinely new output semantic would first appear; converts
   "unsupported" into "silently trained/decoded as a classifier".
   Contradicts the module's own fail-closed doctrine
   (`UnknownOutputContractError`, "there is no default", `:206`). Small,
   standalone, behavior-visible only to plugin authors.
2. **Loader/validator vocabulary disagreement** — the loader accepts 3
   members, `ml_code_validator_agent.py:368` `_LEGAL_OUTPUT_TYPES`
   accepts 2 (`hybrid` legal in one, refused in the other).
3. **Stale registration docstring** (matrix #10).

None is an A-blocker: Step 08 builds on none of these sites, and each
fix is flat-cost whenever scheduled.

## 4. Plugin-loading inventory (one idiom; per-family status)

| registry family | loader today | out-of-tree today? | missing piece | owner |
|---|---|---|---|---|
| models | `SIDERIUS_PLUGIN_DIRS` (+ per-file API) | **YES** (D14-proven) | — (coercion defect §3.5.1 aside) | — |
| losses / objectives | `SIDERIUS_LOSS_DIRS` (two-tier) | **YES** | first-class-kind promotion procedure (documented, audit-gated) | Step 12 docs |
| health checks / views | central `__init__` import list ONLY | NO | run-scoped config-named loading — **08b** (Step-08 parent §6a.3) | 08b |
| task data paths | module-tail registration; leaf-entry-point imports; `transport_argv` dormant | NO | unified task-pack loading + transport emission | **Step 10/12** |
| metrics / scoreability | none (direct construction) | NO | declaration `plugin_ref` + adapter layer | **Step 10/12** |
| task config (identity) | hardcoded default path | NO | run-scoped config binding | **Step 12** |

Per the directive's §7 preference, this audit recommends **no new
per-subsystem loaders now**: the health channel in 08b is the single
operator-mandated exception, deliberately shaped as a thin instance of
the existing idiom that the Step-10/12 composition root subsumes without
contract change (Step-08 parent §6a.3). Task-data-path, metric and
task-config loading all WAIT for that one mechanism.

## 5. Forward roadmap invariant (proposed; binding on Steps 08–12 at Step-08 freeze)

As frozen into the Step-08 parent (§6a.6): new generic-framework
abstractions must admit future task-specific semantics through external
task configuration and run-scoped plugin loading without
generic-infrastructure source edits — no new task-name branches; no
closed task-semantic enum/list whose growth is required per task; no
framework-owned central per-task configuration table; no central source
import/registration edit as the required extension path; built-in
implementations in-repo are allowed but must exercise the same semantic
binding interface available to external users. Historical debt recorded
here does not license new debt. Proposed enshrinement: roadmap §22 at
Step-08 freeze (operator edit; this audit does not touch the frozen
roadmap).

## 6. Step-12 final proof assessment (out-of-tree task pack)

Target demonstration: an external task package (task config + data-path
plugin + model plugin + objective plugin/config + metric plugin/config +
health plugin/config) → SIDERIUS composition root → workflow execution,
with zero infrastructure-source edits. **Recommended: yes — make this an
explicit Step-12 acceptance criterion**, superseding "SIDERIUS supports
three built-in tasks" with "SIDERIUS supports a task-package protocol;
TIDMAD/Pets/DAVIS are three packages using it."

Already able to support that proof (contract-level): `TaskDataPath`
(four methods, opaque scope/id, fail-closed, ContextVar binding);
`ModelIOContract` external JSON; `MetricSpec`/scoreability declaration
constructors; the `LossConfig` custom route; the model-plugin channel;
health after Step 08. Must land before Step 12 can claim it (all
B-class, none blocking Step 08): the unified composition/loading root
(§4 rows 4–6); `transport_argv` production emission; the task-config
run-scoped binding; removal of the ambient TIDMAD fallbacks on the
composed path; the §3.5.1 coercion fix (or its site's replacement).

## 7. Summary for triage

1. **Already satisfy the strong invariant**: Step 04 model
   registration/candidacy + probe realization; Step 07 training
   objectives end-to-end (the Level-2 existence proof); Step 07
   history/diagnosis; Step 03 ModelIOContract as an externally supplied
   declaration; Step 05 DeliverableSpec as a family representation the
   seam already bypasses.
2. **Semantically sound, waiting on Step 10/12 composition**:
   TaskDataPath loading/transport; metric implementation binding
   (declaration layer already open); task-config path binding;
   DatasetProfile explicit-vs-ambient binding; the tuner's regime-A
   `derive_tidmad_*` seam (source-flagged "until Step 12").
3. **Genuine closed-world contracts**: the output-type vocabulary
   (closed but model-boundary-semantic — fixed small universe, does not
   grow per task; its defect is the fail-open coercion, §3.5.1);
   `PRESETS` (closed but optional convenience); `ModelConfigUnion`
   (builtin convenience, plugin-bypassed); `loss_type` (closed WITH a
   first-class escape); `COMPARABILITY_ESTABLISHED_KINDS` (closed by
   deliberate audit-gating — honest). None is task-semantic in the
   forbidden sense.
4. **A-class blockers: NONE.** No Step 01–07 public contract is closed
   in a way Steps 08–12 build on; every gap sits behind an open
   boundary whose natural owner is the Step 10/12 composition root; no
   deferral materially increases migration cost (the seams are already
   shaped for the future binding layer).
5. **RECOMMENDATION: DO NOT REOPEN STEPS 01–07 NOW. CONTINUE STEP 08→12
   UNDER THE NEW FORWARD INVARIANT.**
6. **Re-audit at Step 12** (against the composition root as it lands):
   matrix #1 (task-config binding), #2 (ambient fallbacks gone from the
   composed path), #5 (task-data-path loading + transport emission),
   #12 (regime-A seam replaced by task-declared binding), #13 (metric
   `plugin_ref` + adapters), #14 (first-class-kind promotion procedure
   documented), plus closure of the §3.5 issues.
