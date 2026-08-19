# Step 08 — Health genericity: task-declared health families on a task-identity-free engine (parent design)

## 0. Status and provenance

**FROZEN — rev 3 APPROVED AND FROZEN by operator ruling, 2026-08-18.**
The freeze ruling also: ratifies the Steps 01–07 audit triage (A-class =
NONE; do not reopen 01–07; B-class owned by Step 10/12); fixes the
three-PR decomposition as final (08a → 08b → 08c, 08b = extension
architecture); enshrines the forward external-extensibility invariant
and the Step-12 out-of-tree task-package acceptance criterion in the
roadmap (§22.24); files issue #234 (model-plugin output-type
fail-closed/vocabulary consistency — NOT Step-08 scope; must be resolved
before Step-10/12 external composition is accepted); and freezes the
task-plugin-semantics vs execution-backend distinction (§6a.1). CLAIM
BOUNDARY (ruling §8): after Step 08 the HEALTH SUBSYSTEM is out-of-tree
extensible; a full external-task one-command workflow is NOT claimable
until Step 10/12 composition and is proved only by the Step-12
acceptance test. Implementation begins only after the 08a child design
is frozen under the normal child-design process.

Rev 3 applied the operator review ruling of 2026-08-18 ("APPROVED IN
CORE DIRECTION, BUT NOT YET FROZEN"): semantic separation and task-name
genericity passed review; the five extensibility gaps that blocked freeze
are closed in this revision — the out-of-tree extension contract (§6a),
the source-audited plugin-loading path (§2.6), the open view-capability
namespace (§6.3), out-of-tree custom-check registration (§6a.2), and the
executable extension proof replacing the fourth-task walkthrough (§12
08b / §14.G). Q1/Q2/Q3 are RESOLVED by the same ruling (§15). Rev 2
(reviewed) supersedes the PREMATURE rev-1 draft (`0b2a7884`, reverted by
`7f650971` — scratch only, never reviewed, never frozen); every rev-1
assumption was re-checked against the MERGED D14 state and §3.4 lists the
ones D14 refuted. Authority order: the operator ruling (2026-08-18) >
current source (audited at `baa77ad1`) > merged D14
implementation/evidence > roadmap (`siderius_generic_framework_upgrade.md`
§8, §8.4/§8.4a, §15.1 §8 row, §22.11a, §22.12) > merged Step-06/07
contracts > the scratch draft.

This is a PARENT design: scope, ownership, acceptance, validation and PR
decomposition. Per-commit implementation plans belong to the child designs
(§11 concludes MULTI-PR, so this document deliberately stops above that
level).

## 1. The core problem

The HealthGate machinery is generic; its HEALTH SEMANTICS are TIDMAD
end-to-end, and its "not applicable" vocabulary is dishonest:

* All six shipped checks assume the TIDMAD deliverable: the peek walk
  hardcodes `timeseries/channel0001/timeseries` + int8
  (`_peek.py`), thresholds are millivolts and int8-vocabulary counts
  inside the FRAMEWORK config (`configs/health_checks.yaml`), and
  `spectral_peak_ratio` is injected-frequency physics.
* The protocol's own docstring defines inapplicability as
  `passed=True, reason="not applicable — …"` (`protocol.py:22-31`) —
  **not-applicable IS pass** today, indistinguishable from a genuine pass
  in every aggregate, record and prompt-rendered count.
* A second task cannot bind health behaviour without editing TIDMAD's
  framework YAML, and the checks could not read its deliverable anyway
  (Pets ships a CSV, DAVIS an npz — no channel0001 exists).

D14 makes this concrete: three materially different tasks now execute for
real, and one of them produced a REAL health event — the Pets bounded run
collapsed to a constant prediction (accuracy 0.027 = 1/37 exactly) while
every execution stage PASSED. Execution correctness ≠ model health, from a
real run. Step 08 must make the framework able to SAY that, for any bound
task, without knowing the task's name.

The review ruling added the second half of the problem, and it is the
stronger half: "zero task-name branches in generic core" is necessary but
NOT sufficient. A future USER task must be able to bind health behaviour
from OUTSIDE the SIDERIUS infrastructure repository — external task
configuration plus externally loaded plugin code — without editing
`core/`, `execute_tools/`, `agent/`, any registry source, any central
import list, the framework health YAML, or `examples/`. A new task must
not require a SIDERIUS PR merely to register health behaviour. In-repo
task bindings (TIDMAD, and Pets/DAVIS in 08c) are REFERENCE packs; their
location is packaging, never the extension mechanism. §6a freezes this
contract; §14.H makes it a completion criterion; §12 08b proves it
executably.

## 2. Current source census (audited at `baa77ad1`, post-D14)

### 2.1 The machinery (generic — keep)

`execute_tools/health_checks/`: `registry.py` (flat name→skill, duplicate
refusal) · `runner.py` (gate selection by position) · `evaluation.py`
(`evaluate_and_persist_health_gates`: per-gate execution status, threshold
provenance, `would_invalidate_under_production_policy`, persistence) ·
`candidate_eligibility.py` (`classify_candidate_health` →
`VALID / INVALID / UNKNOWN`; UNKNOWN is already disciplined as
"evidence incomplete", NOT a soft invalid — `feedback.py:155-165` names
absent evidence instead of counting it as pass) · `launch_policy.py` ·
gate actions + severity `SKIP_ITER > SKIP_TO_FORMAL > INVALIDATE_ROUND >
CONTINUE` (CLAUDE.md-frozen) · `--healthgate_mode` enforce/observe (V20
PR D) · firing point `execution.py:955` at tuner round boundaries, ctx
carries `file_vector`, `denoised_filename_fn`, `target_path_fn`,
`denoising_score`.

### 2.2 The checks (TIDMAD — classify, §4)

Three BLOCKING (`output_diversity` ≥25 unique int8 · `output_std` ≥1.0 mV ·
`amplitude_collapse` dominant fraction <0.95), three RECORDING
(`pearson_dispersion` · `spectral_peak_ratio` · `per_file_output_std`).
All six peek the TIDMAD deliverable directly (a second reader beside the
D14 codec). Group indirection ALREADY landed (02c):
`peek_file_indices: task_health_peek` resolves from
`DatasetProfile.health_peek_files` ([3,10,17]), separate from
`anchor_selection_files`; `spectral_peak_ratio` already reads the profile
for `sampling_frequency` — the partial migration to complete.

### 2.3 Hard boundaries (unchanged by Step 08)

* `core/run_invariants.py:475-488` REFUSES a changed effective-config sha
  against an existing workspace → any content change lands at a
  fresh-workspace boundary between campaigns. Both the sha-pin MECHANISM
  and this refusal are untouched.
* `score_vector` never returns health data (frozen since commit-5a).
* Gate IDs and check IDs are referenced by records and by the
  interpreter's fingerprint prose
  (`result_interpretation_agent.py:171` — `output_diversity_blocking:…`);
  IDs stay stable.

### 2.4 LLM-facing surfaces today (Gate-1 relevance)

Health reaches prompts only as (a) validity COUNTS + named-absence lines in
trial-validity feedback (`feedback.py:145-175`) and (b) interpreter
fingerprints naming check IDs. No raw check metrics are prompt-rendered.
Step 08's default keeps it that way (§10).

### 2.5 God-file check (§17 of the kickoff)

No health god-file today: largest are `config.py` (514) and `schemas.py`
(434), each single-responsibility. `evaluation.py` (279) mixes evaluation
with persistence — acceptable now, RECORDED as the watch item: 08b touches
config composition and must not push `config.py` past one responsibility;
if it would, the child extracts `composition.py` first (the CLAUDE.md
decomposition rule), never as a side effect.

### 2.6 The plugin-loading path (ruling §2 — source-audited, not asserted)

The repository already has ONE plugin-loading idiom, instantiated twice,
production-hardened, and proven out-of-tree by D14:

* **Models** — `ml_models/plugin_loader.py`: `SIDERIUS_PLUGIN_DIRS`
  (os.pathsep-separated directory list, `:32`); per-run mode scans EXACTLY
  the named directories with NO fallback to the legacy
  `agent_generated/models/` default (`_resolve_plugin_dirs`, `:96-115`);
  files are loaded via importlib and register through a module-attribute
  contract (`PLUGIN_MODEL_TYPE` / `PLUGIN_CONFIG_CLASS` /
  `PLUGIN_MODEL_CLASS` (+ `PLUGIN_OUTPUT_TYPE`)); the scan runs at
  `models_sandbox.py:836` (module tail) and a per-file API
  (`register_model_in_memory`, `:230`) registers single plugins without a
  rescan. The D14 gate runners loaded `examples/<pack>/plugins/` through
  exactly this channel (`scripts/run_pets_gate2.py:40-43`) — out-of-tree
  loading from an arbitrary directory is an EXISTING, exercised fact.
* **Losses** — `agent_generated/_loss_loader.py` + `loss_models_sandbox.py`
  (`register_loss_in_memory` `:51`, `preload_global_losses` `:105`): the
  SAME idiom behind a DELIBERATELY separate env var (`SIDERIUS_LOSS_DIRS`;
  the module docstring records why sharing the model channel would be
  unsafe). Precedent: one idiom, one scoping channel per registry family.
* **Subprocess propagation** — `core/subprocess_env.py`
  (`PLUGIN_DIRS_ENV_VAR`, `:39`), `core/sandbox_executor.py:316`,
  `core/runtime_control/gpu_measurement_runner.py:275`: the env channel
  reaches every worker; this plumbing is already load-bearing and tested.
* **Failure semantics of the idiom** — the SCAN is fail-open per file (a
  plugin that does not parse is skipped with a printed warning); NAME
  RESOLUTION is fail-closed with no default
  (`UnknownOutputContractError`, `plugin_loader.py:158-189`; custom-loss
  resolution raises listing the registry,
  `loss_models_sandbox.py:263-268`). "Load what parses, refuse at the
  name" is the repository's established pattern.

**Health today, honestly**: the health registry itself is already generic
and fail-closed — `registry.py` is a flat name→skill dict whose `get()`
raises listing the available checks — but it is populated ONLY by
`execute_tools/health_checks/__init__.py::_bootstrap_registry()`, a
central import list; `registry.py:47-48` even instructs "To add a new
check, import it in execute_tools/health_checks/__init__.py". The only
non-test callers are that `__init__` (register) and `runner.py:24` (get).
**Out-of-tree registration of a health check or view provider is
IMPOSSIBLE today without an infrastructure edit.** That central import
list is the single missing seam; closing it is 08b scope (§6a.3), by
instantiating the existing idiom — not by inventing a second plugin
system.

## 3. The D14 evidence that constrains this design

### 3.1 Three real tasks, three real output semantics

| | TIDMAD | Pets | DAVIS |
|---|---|---|---|
| deliverable | per-file HDF5, int8 stream | ONE CSV `{image_id: class}` | ONE npz `{clip: float32 [3,4,128,224]}` |
| output semantics | **per-sample 256-way categorical** (argmax of `[B,256,T]` logits → int8 symbols) | per-image 37-way categorical | dense continuous tensor |
| real health event | mode collapse observed for years (the gates' raison d'être); D14 gate pair reproduced `failed_mode_collapse` | **constant-prediction collapse observed at D14** (dominant class fraction = 1.0; 10/370 correct = exactly chance) | healthy-ish: beat the last-frame-copy baseline (0.017290 < 0.017392) |

The middle row is the load-bearing discovery: **TIDMAD's blocking checks
are already categorical-collapse checks** — unique-symbol count, dominant-
symbol fraction, dispersion floor — expressed in int8/mV vocabulary. The
same three mechanisms, parameterized differently, describe the OBSERVED
Pets collapse (37 symbols, dominant fraction 1.0, occupancy 1) and the
DAVIS analogue (per-tensor dispersion). The generic family is not invented;
it is extracted.

### 3.2 The three-column reasoning table (kickoff §3), per concept

| concept | TIDMAD | Pets | DAVIS | verdict |
|---|---|---|---|---|
| view materializes + values finite | meaningful (h5 readable, int8) | meaningful (CSV parses, classes in range) | meaningful (npz loads, floats finite) | **GENERIC BASELINE** (block-capable) |
| distinct-symbol count / occupancy | unique int8 ≥25 | distinct predicted classes (collapse ⇒ 1 of 37) | n/a (continuous) | **generic mechanism over a declared CATEGORICAL view**; thresholds task-owned |
| dominant-symbol fraction | ≥0.95 blocking | THE observed collapse (1.0) | n/a | same |
| dispersion floor | std ≥1.0 mV | n/a (no continuous output) | per-tensor / cross-clip std (all-identical predictions ⇒ 0) | **generic mechanism over a declared CONTINUOUS view**; scale+threshold task-owned |
| output↔target correlation dispersion | physics-adjacent, file-structured, recording | not meaningful as-is | conceivable but different structure | **TIDMAD-owned family** (recording) |
| injected-frequency PSD ratio | pure TIDMAD physics | no | no | **TIDMAD-owned family** (recording) |
| per-file std breakdown | TIDMAD file vocabulary | no files | clips, not files | **TIDMAD-owned family** (recording) |

Blocking-vs-recording and every numeric threshold: task-declared, always.

### 3.3 What Pets/DAVIS force (they are inputs, not decorations)

1. **Applicability cannot compare against `DatasetProfile` /
   `DeliverableSpec` for B/C** — D14 pinned both as "NOT representable"
   for those tasks. So the comparison is *check-declared requirements vs
   task-declared health facts*: regime-A (TIDMAD, no declaration) derives
   its facts from profile + deliverable contract; a bound task declares
   its own. Presence-discriminated, never name-discriminated — the exact
   D14 truth-table pattern.
2. **Health must read deliverables through task-owned readers.** The
   generic engine cannot open a CSV, an npz and an h5 with one walk. The
   task's health binding supplies typed VIEWS of its artifacts (a
   categorical-prediction view; a continuous-samples view); TIDMAD's view
   provider is its existing peek plumbing routed through the Deliverable
   Contract (byte-identical reads).
3. **B/C health evidence is engine-level, not tuner-level, in Step 08.**
   Gates fire at tuner round boundaries, and Pets/DAVIS do not run through
   the tuner until Steps 10/12. Step 08's real B/C evidence therefore uses
   the D14 bounded-runner pattern over REAL artifacts; TIDMAD keeps the
   production firing-point evidence. Claiming tuner-integrated Pets health
   would be maturity inflation.

### 3.4 Rev-1 scratch assumptions refuted or superseded by D14

* "No real deliverable exists before D14 / L2 is a deferred obligation" →
  real artifacts exist; real-artifact evidence is now REQUIRED milestone
  scope (§14), including the preserved Pets collapse artifact
  (`/home/klz/Data/SIDEREIS_DATA/d14_pets_gate2_20260818b/`).
* "Deliverable facts come from the Deliverable Contract" (as the universal
  comparison surface) → true only for regime-A/TIDMAD; B/C facts come from
  the task's health declaration (§3.3.1).
* The 2-PR split → re-decided as 3 PRs (§11): the contrast-track surface
  became live implementable scope with its own blast radius.

## 4. Classification of the current checks (kickoff §2, derived not assumed)

| check | class | disposition |
|---|---|---|
| `output_diversity` | **B** — generic distinct-symbol mechanism; int8 vocabulary + threshold 25 + peek scale are TIDMAD parameterization | mechanism extracted to the generic categorical family; TIDMAD binds it with current values; verdict parity pinned |
| `output_std` | **B** — generic dispersion-floor mechanism; mV scale + 1.0 threshold TIDMAD | same, continuous family |
| `amplitude_collapse` | **B** — generic dominant-fraction mechanism; 0.95 TIDMAD-declared | same, categorical family; the mechanism that names the Pets collapse |
| `pearson_dispersion` | **C + D** — TIDMAD-owned recording (output↔target correlation dispersion over TIDMAD's file structure) | stays in the TIDMAD family, recording-only, relocated ownership not rewritten |
| `spectral_peak_ratio` | **C + D** — TIDMAD physics | same |
| `per_file_output_std` | **C + D** — TIDMAD file-structure diagnostics | same |
| `passed=True` "not applicable" convention | **E** — superseded | replaced by the `inapplicable` verdict (§7); the rev-6 docstring is amended citing this design |
| `_peek` hardcoded h5 walk | **E** as a generic mechanism | becomes TIDMAD-family plumbing routed through the Deliverable Contract; byte-identical reads |

Nothing current lands in pure class A; the only NEW class-A (generic-by-
semantics) checks Step 08 introduces are the tiny universal baseline —
*declared view materializes* and *values finite* — which every task gets
and which may block.

## 5. Semantic ownership — what Health owns and does not own

```text
Health OWNS      validity/pathology evidence computed FROM produced outputs
                 (deliverable-side), plus its blocking/recording policy and
                 persisted gate evidence.

Health does NOT own
  shape/dtype legality of model I/O ......... ModelIOContract (Step 03)
  whether a deliverable is scoreable ........ ScoreabilityContract (Step 06)
  the golden/secondary metric value ......... EvaluationMetric (Step 06)
  training/validation curves + diagnosis .... TrainingHistory/-Diagnosis (Step 07)
  how bytes become samples/deliverables ..... TaskDataPath (D14)
```

The independent failure class that justifies Health beside the metric,
demonstrated by D14: Pets' metric said "0.027, finite, scoreable" — a
number, not a verdict; Health's job is the *pattern statement* "the
deliverable is a constant prediction", which exists even when no metric is
computable and is NOT derivable from the scalar (a bad-but-varied model
scores low without collapsing). Conversely DAVIS shows a modest metric with
no pathology. Health never reads a metric verdict; a metric never reads a
gate's. `HealthCheckContext`'s existing `denoising_score`/`file_vector`
fields are compatibility inputs for TIDMAD's current checks, not a licence
— **no NEW check may consume the golden metric scalar** (guardrail §13).

## 6. The minimal generic abstraction (proposed)

One sentence: **a task binds a HEALTH FAMILY — a declared roster of checks
with task-owned parameters and dispositions, plus a task-owned VIEW
PROVIDER that turns its real artifacts into a tiny typed view vocabulary —
and the generic engine evaluates, aggregates and persists verdicts without
knowing the task.**

Components, smallest that the three real tasks force:

1. **Check input declaration** (data, on every check): which view
   CAPABILITY KEY it consumes (§6.3 — an opaque identifier, e.g.
   `categorical_predictions`, or a plugin-local key), which declared facts
   it requires (e.g. symbol cardinality, value scale, file group), and
   which parameter names are task thresholds.
2. **Applicability verdict**: requirements compared against the bound
   task's declared health facts BEFORE any I/O →
   `applicable | inapplicable(reason names the mismatched axis)`.
   Regime-A derives TIDMAD's facts from profile + Deliverable Contract
   (presence-discriminated, D14 pattern).
3. **View capabilities — an OPEN namespace, never a closed core enum**
   (ruling §3). A view is identified by a `HealthViewKey`: an opaque
   string the engine NEVER interprets, branches on, or enumerates. The
   framework SHIPS two **standard capabilities** with defined payload
   contracts — `categorical_predictions` (finite symbol stream + declared
   cardinality) and `continuous_samples` (float stream + declared scale)
   — which the built-in generic checks consume. A task or external plugin
   may declare **plugin-local capabilities** (e.g.
   `my_lab.graph_prediction_view`) with provider-owned payload contracts,
   consumed by its own checks; the engine's whole job is
   `check requires key X → does the bound provider expose key X?
   yes → transport the payload; no → inapplicable`. There is NO
   `ViewKind` Literal/union in generic code and NO
   `if view_kind == …` dispatch (census-refused, §13); the transport
   envelope is the minimal common carrier, not a mega-union of scientific
   views. Growth discipline: adding a new STANDARD capability (one with
   framework-shipped checks) still requires a forcing task; adding a
   plugin-local capability requires NOTHING from the framework. TIDMAD's
   six consume TIDMAD-family task views (its peeks); TIDMAD MAY
   additionally expose its int8 stream as a categorical view (it is one),
   but parity, not unification, is the Step-08 obligation.
4. **Task health binding**: family roster + parameters + dispositions
   (blocking/recording) + plugin REFERENCES as task-owned CONFIG DATA that
   lives OUTSIDE the framework config (§6a.4); the view provider (and any
   custom checks) as task-owned CODE, loaded and registered at run scope
   (§6a.3), capability-keyed and fail-closed on a declared-but-unresolved
   binding (regime-A resolves TIDMAD). Framework gate POLICY + the task's
   health config compose DETERMINISTICALLY into the same single pinned
   `health_checks_effective.yaml` — pinning mechanism untouched.
5. **Generic engine** (existing, kept): runner, gate actions, severity,
   enforce/observe mode, persistence, eligibility classification.

What the framework config keeps: gate ROLES, actions, severity, cadence —
generic policy ONLY; it never learns a task identity (§6a.4). What the
task owns: which checks, their thresholds, their views, their
dispositions, and which plugin modules supply the code. No mega-schema:
the declaration carries only what §3.2's table forced, and a task
omitting health entirely is regime-legal (UNKNOWN-style evidence-absence,
§7 — never a synthesized pass). A task whose declaration NAMES a plugin,
provider or check that cannot be resolved is the opposite case and fails
closed (§6a.5).

## 6a. The out-of-tree extension contract (FROZEN — ruling §1/§4/§5)

### 6a.1 The governing principle (operator, 2026-08-18)

> **SIDERIUS infrastructure specifies the plugin protocol, not the
> scientific implementation.** Task-specific scientific semantics are
> supplied by externally loadable plugins and configuration. Multiple
> plugin execution forms — Python, executable/script, skill/agent, and
> future backends — may be supported through adapters, but all must
> satisfy the same subsystem-specific semantic contract.

The framework provides a plugin ABI/protocol, never a growing plugin
catalog. For Step 08 concretely: the health engine owns the check
protocol, the verdict vocabulary, registration, resolution, composition,
persistence and policy; every scientific statement about what "unhealthy"
means for a task arrives as task config + task plugin code. Step 08 ships
the Python-plugin form only (that is what the existing idiom supports);
other execution backends are adapters behind the SAME `HealthCheckSkill`
semantic contract when a real need arrives — never a second semantics.

Frozen distinction (ruling §4, 2026-08-18; roadmap §22.24.2):
**task-specific plugin semantics** (a new check, view capability,
threshold family) must be externally extensible with zero generic-core
edits, while **plugin execution backends** (Python · executable/script ·
skill/agent · container · MCP) are FRAMEWORK capabilities — a genuinely
new backend may legitimately require a framework capability change, is
added only when a real use case requires it, and always normalizes into
the same semantic contract. A new TASK plugin never requires a core
edit; backends are never multiplied speculatively.

### 6a.2 The two levels (both must hold at Step-08 completion)

**Level 1 — a task using existing generic health primitives** integrates
with:

```text
external task health configuration
+
external view-provider plugin
```

**Level 2 — a task with novel health semantics** integrates with:

```text
external task health configuration
+
external view-provider plugin
+
external custom health-check plugin
```

In BOTH cases, ZERO edits to: `core/`, `execute_tools/`, `agent/`, any
registry source, the framework health YAML, any central import list,
`examples/`, or any other SIDERIUS infrastructure source. A new task must
not require a SIDERIUS PR merely to register health behaviour. Custom
checks are first-class: a family roster may reference built-in generic
checks and/or externally registered task-specific checks, and the
registry stays a generic `check id → implementation` map with no
task-name semantics (ruling §4).

### 6a.3 The loading/binding seam (08b scope — the ONE missing piece)

§2.6 establishes the honest baseline: the idiom exists (env/config-named
directories → importlib file load → attribute/registration contract →
generic registry), is subprocess-propagated, and is exercised out-of-tree
by D14; health merely lacks its instance — today only the central
`__init__` import list populates the health registry. 08b closes exactly
that gap:

* The task's health config NAMES its plugin code explicitly (module file
  paths and/or a directory list — config-driven, never guessed from the
  environment); at startup composition, the run loads those files through
  the same file-based mechanism the model/loss loaders use, and the
  plugin registers its provider and checks through the SAME PUBLIC
  registration functions the built-ins use. Registration is run-scoped:
  it happens in the composing process before family resolution, and the
  effective pinned artifact records what was loaded.
* Built-in families (TIDMAD; Pets/DAVIS in 08c) register through the SAME
  public interface. In-repo residence is reference packaging; the
  `__init__` import list loses its status as the extension path (it may
  remain as the built-ins' convenience bootstrap, but the census pins
  that NO external registration requires touching it).
* **Not a second plugin system** (ruling §2): this is the existing idiom
  instantiated for one more registry family — the same loader shape,
  fail-closed resolution, and env/config scoping precedent as models and
  losses. The operator's standing preference is ONE coherent run-scoped
  task/plugin composition mechanism (Step 10/12's composition root)
  consumed by data path, models, objectives, metrics and health alike;
  08b's channel is deliberately a thin instance of the idiom whose config
  surface (plugin refs + family declaration) IS what a future task pack
  feeds the unified mechanism — subsumable without contract change.

### 6a.4 Config ownership (ruling §5)

```text
FRAMEWORK CONFIG (configs/health_checks.yaml, slimmed in 08b)
    gate roles · actions · severity · cadence · generic policy
    — NEVER a task identity, roster, threshold or plugin reference

TASK HEALTH CONFIG (task-owned, external for external users;
                    reference packs carry theirs in-repo)
    health family roster · thresholds · dispositions
    · provider/check plugin references · task health facts

deterministic runtime composition
    → ONE pinned effective artifact ({workspace}/health_checks_effective.yaml)
```

The forbidden failure mode is named: the framework YAML must never become
`tidmad: … / pets: … / davis: … / <user task>: …` — that would move task
branching from Python into framework YAML and still require an infra edit
per task. TIDMAD's thresholds/provenance move OUT of the framework file
into the TIDMAD family's task-owned config in 08b (values unchanged,
provenance comments carried, §8 parity obligations unchanged).

### 6a.5 Fail-closed resolution (ruling §4/§6 negative control)

Two cases that must never be conflated:

* **No binding declared** (a task says nothing about health): regime-legal
  absence — UNKNOWN-style evidence-absence, named, never a synthesized
  pass (§7).
* **Binding declared but unresolvable** (named plugin file missing or
  unloadable; named provider/check id not registered after loading;
  required capability not exposed by the bound provider): a
  DETERMINISTIC, diagnostic, fail-closed startup error naming the
  unresolved reference and what IS registered — never a silent fallback,
  never a downgrade to `inapplicable`, never "no checks ran = healthy".

### 6a.6 Forward invariant (proposed for Steps 08–12; roadmap enshrinement
at freeze)

From Step 08 onward, every new generic-framework abstraction must admit
future task-specific semantics through external task configuration and
run-scoped plugin loading without generic-infrastructure source edits:
no new task-name branches; no closed task-semantic enum/list whose growth
is required per task; no framework-owned central per-task configuration
table; no central source import/registration edit as the required
extension path; built-in implementations allowed in-repo but exercising
the same semantic binding interface available to external users. (The
Steps 01–07 read-only debt audit —
`step_01_07_extensibility_debt_audit.md` — applies the same invariant
retrospectively and is triaged separately; historical debt does not
license new debt.)

## 7. Blocking / recording / inapplicable / error semantics (frozen here)

* Verdict vocabulary per check execution:
  `passed | failed | inapplicable | error`. `inapplicable` is decided by
  declaration comparison BEFORE I/O and never blocks, never counts as
  pass, and is persisted + aggregable as itself. `error` (a check that
  should run but cannot compute) on a BLOCKING check fails closed — it is
  never converted to pass or silently skipped; on a recording check it is
  persisted as error.
* Disposition (blocking vs recording) and thresholds: task-declared;
  ACTIONS and severity resolution stay the frozen framework set.
* Aggregation: unchanged (per-gate `on_fail` action; severity max across
  fired gates; `short_circuit` honoured). One blocking failure fails
  health for the round, as today.
* Candidate eligibility keeps `VALID / INVALID / UNKNOWN`; a round whose
  REQUIRED blocking set was not fully evaluated stays UNKNOWN with the
  absent evidence NAMED (the existing `feedback.py` discipline extends to
  inapplicability: an inapplicable check is excluded from the required
  set, an errored one is not).
* Health outcome is independent of metric direction and of the metric
  entirely.

## 8. TIDMAD preservation strategy

* **Verdict parity, capture-first**: the six checks' `HealthCheckResult`s
  byte-identical on the committed fixtures at every migration commit
  (goldens exist under `tests/unit/execute_tools/health_checks/goldens/`);
  where any composed-config byte could shift, a pre-change capture
  manifest pins expected values (the D14-1 discipline — expected values
  never recomputed by the new code).
* Gate IDs, check IDs, record fields (`health_gate_results`,
  `PersistedHealthGateResult`), severity, firing point, enforce/observe
  mode: unchanged.
* Thresholds move ownership with VALUES unchanged and empirical provenance
  comments carried along.
* Effective-config sha: mechanism untouched; the content change lands at a
  fresh-workspace boundary (run-invariants refusal is the safety net and
  is itself asserted, not weakened).
* Anything that would change a TIDMAD verdict is a semantic change
  requiring operator review — none is proposed.

## 9. Pets / DAVIS extension strategy (cumulative corpus)

* **L1 (declarations + atomic fixtures)**: each pack declares its health
  family + facts; the roadmap ladder runs as frozen — 8.4-A (two file-set
  declarations observably independent), 8.4-B (declared-float ⇒ int8
  family `inapplicable`, no file opened — spy-proven), 8.4-C (a generic
  check FIRES and can FAIL on that same declared-float output: the
  negative control that inapplicability is not an exemption).
* **L2 (real artifacts)**: the D14 gate artifacts are the first real
  corpus — the preserved Pets collapse CSV becomes a committed-fixture-of-
  record (small, deterministic) whose evaluation by the generic engine
  yields `dominant-fraction = 1.0 → blocking-fail` under Pets' declared
  family; a DAVIS npz evaluates through the continuous family with no
  TIDMAD/classification assumption. Fresh bounded runs (D14 runner
  pattern) provide the live half.
* Later Step-08 PRs INHERIT earlier evidence: TIDMAD parity goldens stay;
  B/C fixtures add beside them; the rung/census style follows D14
  (extend, never replace).
* Unit tests do NOT all run three tasks: each runs the smallest
  discriminating fixtures for the changed boundary; the THREE-task
  demonstration is milestone-level (§14).

## 10. Unit / Gate 1 / Gate 2 ownership

| property | canonical owner | TIDMAD evidence | Pets evidence | DAVIS evidence | when |
|---|---|---|---|---|---|
| declaration schema + applicability comparison (pure) | UNIT | regime-A derivation | declared facts | declared facts | 08a |
| inapplicable ≠ pass ≠ error transport (records/aggregation) | UNIT | goldens unchanged | 8.4-B fixture | continuous fixture | 08a |
| contract-routed TIDMAD peek parity | UNIT (goldens) | byte-identical results | — | — | 08a |
| production firing + persistence through the new path | **GATE 2** (bounded TIDMAD round) | required | — | — | 08a |
| task-owned family/threshold composition + pinning | UNIT + **GATE 2** (bounded TIDMAD, startup composition is lifecycle) | composed artifact semantically identical; verdicts identical | L1 declaration composes | L1 declaration composes | 08b |
| D18 typed no-per-sample statement | UNIT | negative control (per-file metric unchanged) | scalar-only metric real instance | scalar-only metric real instance | 08b |
| **out-of-tree extension proof** (external config + external plugin → loader → registration → family resolution → provider → custom check → `HealthCheckResult`; negative control: broken registration → deterministic fail-closed error) | **UNIT** (integration-style, tmp external fixture package — NOT Gate 2, no training) | — | — | — | 08b |
| generic categorical/continuous checks on views | UNIT (hand-computed) | optional categorical view ≡ int8 parity | collapse arithmetic | dispersion arithmetic | 08c |
| REAL collapse detected / real dense output evaluated | **GATE 2** (bounded real artifact evaluations) | unchanged behaviour re-shown | **D14 collapse artifact → blocking-fail** | real npz → verdicts, no task assumptions | 08c |
| LLM-visible health feedback | — unchanged by default; any prompt delta ⇒ **GATE 1** at that child | counts/absence lines byte-stable | — | — | any child that renders |
| no-name-branch / no-examples-import invariants | UNIT guardrail census (extends the D14 census) | — | — | — | 08c |

Gate 1 is NOT required by default anywhere in Step 08: no LLM-facing
semantics change (prompt-visible health stays counts + named absence +
stable IDs). If a child elects to render inapplicability or family identity
into prompts, that child's freeze re-dispositions Gate 1 under the 07b
PB-delta rules.

## 11. PR decomposition — THREE PRs (derived, not copied)

Three capabilities, three blast radii, three failure classes:

```text
08a  CHECK INPUT CONTRACT + APPLICABILITY
     what a check declares, what it receives, how it honestly says
     "not for this task"; contract-routed TIDMAD peek; every check touched
08b  EXTENSION ARCHITECTURE: TASK-OWNED CONFIG + PLUGIN BINDING
     + THE TIDMAD FAMILY + D18
     who owns thresholds/roster/disposition; external/run-scoped plugin
     loading + provider + custom-check registration; fail-closed
     resolution; deterministic composition into the pinned effective
     artifact; the six become the first task family; the executable
     out-of-tree extension proof
08c  CONTRAST FAMILIES + GENERIC COLLAPSE CHECKS + THREE-TASK EVIDENCE
     the standard view capabilities with their first consumers;
     Pets/DAVIS bindings (reference packs on the SAME interface);
     real-artifact evaluations incl. the D14 collapse; milestone census
```

08b is the ARCHITECTURE owner (ruling §8): it must prove that health
extension no longer requires an infrastructure-repository edit. Pets and
DAVIS in 08c are real contrast evidence, not the mechanism by which
external users extend SIDERIUS.

Why not 2 (the scratch's split): pre-D14, 08c's content was L1-only and
could ride along; post-D14 it is live production surface (two new task
bindings, new generic checks, real-artifact evaluation paths) whose review
concerns — new science-adjacent arithmetic and real evidence — differ from
both the contract PR and the ownership PR. Why not 1: contract-vocabulary
changes to every existing check + config-ownership migration + new task
families in one diff would mix exactly the concerns the kickoff §15 names.
Why not 4: "generic checks fire cross-task" is not a fourth capability —
8.4-C's minimal case lands with 08a's fixtures, the full family with its
real consumers in 08c.

Dependencies: 08b consumes 08a's declaration contract; 08c consumes both.
Stacked like D14; per the validation-economy rule the children get targeted
tests + their own bounded Gates, and ONE canonical full CI runs on the
final integrated master-targeting head (#233 caveat: stacked PRs get no
automatic CI — evidence via the formal-PR run at the end, exactly the D14
closeout pattern).

## 12. Per-PR scope / goal / validation (parent level — no commit plans)

### 08a — check input contract + applicability
* **Goal**: inapplicability becomes a typed verdict decided before I/O;
  checks declare their inputs as data; TIDMAD reads route through the
  Deliverable Contract byte-identically.
* **Allowed changes**: `protocol.py`, `schemas.py` (additive verdict +
  declaration), `runner.py`/`evaluation.py` (verdict transport), the six
  checks' declarations, `_peek`/`_multi_file_peek` re-plumbing. NO YAML
  layout change, no registry/ownership change, no new checks beyond the
  minimal 8.4-C dispersion fixture-check, no prompt change.
* **Acceptance**: six-check verdict parity on goldens; 8.4-B with the
  no-file-opened spy; 8.4-C negative control; applicability reachability
  from `evaluate_and_persist_health_gates`; Gate 2 = one bounded TIDMAD
  round (gates fire + persist through the new path). Gate 1: none.

#### 08a implementation status (bookkeeping — the architecture above is unchanged)

**IMPLEMENTED, C1–C6, on `step08-pr08a-check-input-contract`** from base
`a37fd15d`: `ac580514` (verdict vocabulary + capture-first parity manifest)
· `2d1c7b61` (declarations + pure applicability engine) · `aac9b3ba`
(wiring + verdict transport — the behavioural commit) · `ab9b5909` (the six
declarations) · `7e25e541` (peek via the Deliverable Contract) · `7ae72ae5`
(8.4-C control + rung pair + docs). Full evidence, deviations and per-commit
checklists live in the child ledger
`step_08_health_check_task_profile/pr_08a_check_input_contract.md` §4/§10.
Gate 1 confirmed NOT REQUIRED — the LLM-facing rendering is byte-identical
to a worktree at `a37fd15d`.

**Findings from 08a that CONSTRAIN 08b** (recorded here because 08b's design
must start from them, not from the pre-implementation assumptions):

1. **`value_scale_unit` is owned by nothing today.** TIDMAD's millivolt
   scale is `_MV_PER_LSB = 40/128`, a module literal inside `output_std`,
   `per_file_output_std` and `pearson_dispersion`. No `DatasetProfile` field
   declares it, so 08a's regime-A derivation leaves the axis ABSENT and no
   08a check may require it — requiring it would flip TIDMAD's std checks to
   `inapplicable`. **08b must move this scale into the TIDMAD family's
   task-owned config alongside the thresholds** (§6a.4), and only then may a
   check declare the axis.
2. **`spectral_peak_ratio` reads only the denoised channel.** It never peeks
   the target; it needs a declared sampling frequency. Any 08b/08c family
   roster that treats it as a target-comparison check is wrong.
3. **The `"timeseries"` in-file group-walk literal still has no owner.**
   `DeliverableStorage` owns channel groups/dtype/offset and
   `DeliverableNaming` owns filenames; nothing owns the in-file group path,
   so 08a left it in place. Whoever introduces a view PROVIDER (08b) either
   gives that path an owner or inherits the literal knowingly.
4. **`threshold_parameter_names` is populated and asserted ⊆ the keys each
   check actually reads.** It is 08b's migration input.
   `peek_file_indices` (run-level DataScope policy) and `aggregation` (gate
   policy) are deliberately EXCLUDED — they are framework policy and must
   not move to task ownership.
5. **One classifier, one call site.** `schemas.classify_verdict` is the
   single spelling of the verdict mapping, and `applicability()` has exactly
   one production call site (`runner.evaluate_gate`), pinned by a test. 08b
   must not add a second of either.
6. **`_regime_a_facts.resolve_health_facts()` and `runner._resolve_task_facts()`
   are the two functions 08b redirects** when a task binding supplies facts
   directly. Neither contains a task name, and the redirect is a call-site
   change, not a contract change.

### 08b — extension architecture: task-owned config + plugin binding + first family + D18
* **Goal**: the task owns roster/thresholds/dispositions and names its
  plugin code; the framework config slims to policy only and never learns
  a task identity; external plugin modules load at run scope and register
  providers AND custom checks through the public API; declared-but-
  unresolved bindings fail closed; composition lands DETERMINISTICALLY in
  the SAME pinned artifact; scalar-only metrics reach the context as a
  typed statement (D18), consumed as `inapplicable` by per-file checks —
  never a hollow pass. 08b ends with extension provably requiring zero
  infrastructure edits (§6a.2).
* **Allowed changes**: `config.py` (watch the god-file line, §2.5),
  effective-config composition, the health plugin loading seam (§6a.3 —
  the existing idiom instantiated; config-named module refs), the public
  registration surface for providers/checks, fail-closed family
  resolution, registry family identity (flat lookup preserved),
  `HealthCheckContext` additive statement, TIDMAD family relocation with
  values unchanged (thresholds/provenance move from the framework YAML to
  TIDMAD's task-owned config, §6a.4).
* **Acceptance**: composed TIDMAD artifact semantically identical under
  the Q2 terms (§15 — roster/thresholds/dispositions/actions identical,
  verdict parity, byte/sha delta recorded, new sha pinned, old workspace
  refused, fresh-workspace boundary; no serialization distortion to
  chase the old sha); run-invariants refusal asserted; 8.4-A; D18
  positive (real scalar-only `MetricSpec` instances now exist: accuracy,
  mse) + negative control; **the executable OUT-OF-TREE EXTENSION
  PROOF** (ruling §6): a tmp/external plugin package created by the test
  OUTSIDE the repository import roots — `health.yaml` (an external task
  health config declaring a family that parameterizes one built-in
  generic mechanism AND one custom check `alternating_pattern_health`,
  referencing a provider that exposes the plugin-local capability
  `synthetic_boolean_pattern`) + `plugin.py` (provider + custom check,
  registering via the public API) — driven end-to-end: external config →
  loader → run-scoped registration → family resolution → provider →
  check → `HealthCheckResult`; asserting zero framework registry/import/
  YAML edits structurally (the package lives outside the tree; the
  census guards the core); **negative control**: with the registration
  broken/removed, resolution fails closed with a deterministic diagnostic
  naming the unresolved reference — not a silent fallback, not
  `inapplicable`. UNIT/integration-owned, no real training. Gate 2 = one
  bounded TIDMAD round (startup composition is lifecycle). Gate 1: none.

### 08c — contrast families + generic checks + three-task evidence
* **Goal**: Pets and DAVIS bind real health families; the generic
  categorical/continuous collapse checks exist with hand-computed
  arithmetic; the framework detects the REAL D14 Pets collapse and
  evaluates a REAL DAVIS artifact with zero task-name knowledge; the
  guardrail census extends to health.
* **Allowed changes**: new task health bindings (production task modules,
  packs declare config), the generic check family, the bounded real-
  artifact evaluation path (runner-pattern), census extension.
* **Acceptance**: collapse fixture-of-record → blocking-fail with the
  dominant-fraction evidence persisted; DAVIS npz → verdicts through the
  continuous family; TIDMAD untouched (goldens); Pets/DAVIS bindings
  register through the SAME public interface external plugins use
  (reference packs, never a privileged path); census per §13 including
  the strengthened structural items (no central task roster/mapping, no
  view-kind dispatch). The fourth-task extensibility claim is NOT
  re-proven here by walkthrough — it was proven EXECUTABLY in 08b and its
  proof test keeps passing. Gate 2 = bounded real Pets + DAVIS artifact
  evaluations (≤10 min each, D14 runner pattern; PASS/FAIL from semantic
  evidence). Gate 1: none unless a prompt delta is elected.

## 13. Genericity / task-identity guardrails (structural acceptance)

Extending the D14 census (`test_task_data_path_census.py` precedent) to
health core: zero `tidmad|pet|davis` comparisons; zero `examples/` imports
in production; no `37`, no int8 vocabulary, no channel/file literals, no
temporal geometry in generic health code; no golden-metric arithmetic and
no `TrainingDiagnosis` logic in any check; new-check-consumes-metric-scalar
is census-refused; STANDARD-capability growth requires a task that forces
it (plugin-local capabilities require nothing, §6.3).

Strengthened structural items (ruling §7) — generic health core contains:
no central task registration list; no central task→provider mapping; no
task-specific check roster; no closed view-kind enum/Literal/union and no
`if view_kind == …` dispatch; no framework-YAML task identities; and no
registration path for which a central import-list edit is REQUIRED (the
built-ins' bootstrap import is convenience, not the contract — the
extension proof registers without touching it). A fourth task enters
entirely through configuration + run-scoped plugin loading + declaration
(binding by presence/capability, never by name).

## 14. Step-08 completion criteria

A. TIDMAD: six verdicts byte-identical on goldens; gate IDs/records/firing
   point/severity/mode unchanged; production Gate-2 evidence at 08a and
   08b heads. B. Pets: the real D14 collapse artifact evaluates to a
   blocking categorical-collapse failure under Pets' declared family — the
   framework can now SAY what D14 could only observe. C. DAVIS: a real
   dense artifact evaluates through the same engine with no TIDMAD or
   classification assumption. D. Generic core: census green (§13,
   including the strengthened structural items). E. Semantics:
   `inapplicable`/`error`/`unknown` distinct, deterministic, persisted;
   required-blocking-uncomputable fails closed. F. Testing: ownership per
   §10, no fake lifecycle Units, evidence cumulative. G. Extensibility,
   EXECUTABLE: the out-of-tree extension proof (§12 08b) passes — an
   external package's config + provider + custom check + plugin-local
   capability run end-to-end with zero framework registry/import/YAML
   edits, and its negative control fails closed. H. THE STRONG CRITERION
   (ruling §10) — BOTH must hold: (i) zero task-name branches in generic
   core, AND (ii) a new task using existing health primitives integrates
   via external task config + external view-provider plugin, and a new
   task with novel health semantics via those plus an external
   custom-check plugin, with ZERO SIDERIUS infrastructure-source edits
   (§6a.2's forbidden-edit list).

## 15. Residual risks / open questions

* **R1 — composed-config sha churn (08b)**: byte-identity of the effective
  artifact may be impossible under composition; fallback is "semantically
  identical + called-out delta + fresh-workspace boundary". **RESOLVED by
  Q2 (below).**
* **R2 — TIDMAD categorical-view unification temptation**: expressing the
  int8 checks THROUGH the new generic family would be elegant and is
  deliberately NOT required — parity first; unification only if verdicts
  stay byte-identical, else it is deferred debt, not scope.
* **R3 — firing-point honesty**: B/C health runs engine-level until
  Steps 10/12 bind their workflows; the design says so everywhere a claim
  could be over-read (§3.3.3).
* **R4 — #233**: stacked children get no automatic CI; the D14 closeout
  pattern (one canonical formal-PR run at the integrated head) is the
  plan of record unless #233 is fixed first.
* **Operator decisions (ruling of 2026-08-18) — all three RESOLVED**:
  * **Q1 — three-PR split: ACCEPTED** (with 08b's responsibility widened
    to extension-architecture owner, §11/§12).
  * **Q2 — R1 composed-config sha fallback: ACCEPTED.** Byte identity of
    the newly COMPOSED effective YAML is not required if composition
    necessarily changes serialization. Required instead: deterministic
    composition; TIDMAD roster identical; thresholds identical;
    dispositions identical; framework actions/policy identical; health
    VERDICT parity; the byte/sha delta explicitly recorded; the new
    effective sha pinned; an old workspace rejects the changed sha
    (run-invariants refusal asserted); fresh-workspace boundary used.
    Serialization must NOT be distorted merely to preserve the old sha.
  * **Q3 — prompt visibility: CONFIRMED.** Step 08 does not expand the
    LLM-facing health surface by default: counts + named absence +
    stable IDs only; raw metrics, family identity, applicability detail
    and any new health narrative stay prompt-invisible (Step 09 owns
    richer interpretation/consumption). Therefore Gate 1 = NOT REQUIRED
    by default in 08a/08b/08c; any actual prompt/PB delta re-dispositions
    Gate 1 for that child.

## 16. Explicitly deferred (none block Step 08)

`collapse_detection_framework_generic.md` machinery stays dead (§8.5
roadmap); #225 scope-opacity, #226 auto-resume, #227 integration rot,
#228 two-route non-finite divergence, #229 pseudo-probe escape — separate
issues; prompt-side health rendering (Step 09's consumption of evidence);
tuner-integrated B/C health (Steps 10/12); any new view kind (needs a
forcing task).

## 17. Adversarial self-review (kickoff §23, applied)

1. *TIDMAD HealthGate with optional fields?* No — the task binding is
   roster+params+provider, not a widened TIDMAD schema; B/C declare
   different families, not TIDMAD's with switches. 2. *Does core now
   "understand classification"?* It understands `categorical_predictions`
   — a view kind TWO real tasks instantiate (Pets, and TIDMAD's own
   argmax-symbol output), with cardinality DECLARED, never inferred; the
   37 lives in Pets' declaration. 3. *Temporal understanding?* None —
   DAVIS reduces to `continuous_samples` through ITS provider; no
   temporal axis exists in core. 4. *Ownership theft?* §5 table;
   scoreability/metric/diagnosis untouched; the D18 statement REPLACES a
   silent bridge rather than adding metric knowledge. 5. *NA→pass?* The
   verdict is the PR-08a headline; 8.4-B asserts the verdict AND the
   absence of I/O. 6. *Silent skips?* `error` fails closed on blocking;
   UNKNOWN names absences (existing discipline, extended). 7.
   *Mega-schema?* Two view kinds, forced by three real tasks; growth
   gated on a forcing task. 8. *Units faking lifecycle?* Firing,
   composition/pinning and real-artifact evaluation are Gate-2-owned
   (§10). 9. *Gate 1 by habit?* Off everywhere by default, with the
   re-disposition rule stated. 10. *B/C decorative?* They reshaped the
   abstraction (§3.3: declaration-based applicability, view providers,
   engine-level evidence) — the design is different BECAUSE of them.
   11. *God file?* §2.5 watch item with a pre-committed extraction rule.
   12. *Fourth task?* §14.G is now an EXECUTABLE out-of-tree proof
   (08b), not a walkthrough.

### 17a. Adversarial re-review — the ruling §11 scenarios (applied to rev 3)

**A. A university user has a graph-prediction task in another repository —
graph-specific health check without a SIDERIUS PR?** YES (Level 2,
§6a.2): their external `health.yaml` declares the family (their check id,
disposition, thresholds) and names their plugin module; the plugin
registers a provider exposing the plugin-local capability
`their_lab.graph_view` and the custom check consuming it, through the
public API (§6a.3); the engine matches the capability key opaquely
(§6.3). No SIDERIUS file changes; the 08b extension proof exercises this
exact shape (custom view + custom check from a tmp external package).

**B. Only built-in dominant-fraction/dispersion checks with custom
thresholds — config + provider plugin only?** YES (Level 1): the built-in
generic checks are parameterized by task-declared thresholds (§6.4); the
task's provider exposes the standard capability
(`categorical_predictions` or `continuous_samples`); no custom check code
and no framework edit.

**C. A view kind neither standard capability represents — enum/branch
edit in generic core?** NO: there is no view-kind enum to grow and no
view dispatch to extend — the namespace is open (§6.3), the engine only
matches declared-required vs provided keys, and the census refuses
`if view_kind ==` dispatch structurally (§13). Standard capabilities are
shipped payload contracts, not a closed universe.

**D. Plugin absent or misspelled — fail closed with a useful
diagnostic?** YES (§6a.5): a DECLARED binding that cannot be resolved
(missing/unloadable module, unregistered id, unexposed capability) is a
deterministic startup error naming the unresolved reference and what IS
registered — never a fallback, never `inapplicable`, never
"no checks ran = healthy". The 08b negative control pins exactly this,
and it is distinct from the regime-legal no-binding case (named absence).

**E. The task never named anywhere in SIDERIUS source — register,
compose, execute?** YES: binding is presence/capability-keyed (the D14
truth-table pattern); ids and capability keys are opaque strings the
framework never spells; composition reads the task's OWN config file; the
census forbids central task rosters/mappings (§13). The extension-proof
task (`synthetic_boolean_pattern` / `alternating_pattern_health`) exists
only inside a test's tmp directory — the strongest form of "never named
in source".

**F. Search generic health core for all registration sites — would a
synthetic fourth task touch any?** Honest answer, from §2.6: TODAY it
would — the only registration path is the central
`health_checks/__init__.py` import list, which is precisely the gap. As
designed (after 08b): registration sites are (i) the public
registration functions, callable by run-scoped loaded plugin code, and
(ii) the built-ins' bootstrap import, which no external task needs. The
extension proof + the strengthened census (§13) make "touches none of
them" an executable, regression-guarded fact rather than a review
opinion.
