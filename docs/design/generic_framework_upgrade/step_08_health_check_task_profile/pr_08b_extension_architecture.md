# PR 08b — extension architecture: task-owned config + plugin binding + TIDMAD family + D18 (child design)

## 0. Status and provenance

**DRAFT rev 1 — NOT FROZEN. For operator review.** Drafted while the 08a
Gate 2 was executing, at 08a head `7ae72ae5`. Implementation must not begin
until this document is frozen under the normal child-design process.

Child of the FROZEN Step-08 parent (`step_08_health_check_task_profile.md`,
rev 3), which is the semantic authority for everything below — especially
§6a.2 (the two extension levels), §6a.3 (the loading/binding seam), §6a.4
(config ownership), §6a.5 (fail-closed resolution) and §12 08b.

Authority order: the frozen parent > current source (audited in §2) > the
merged 08a implementation and its ledger > roadmap §8/§22.24 >
`docs/design/pluggable_health_checks.md`.

**This design starts from 08a's findings, not from pre-implementation
assumptions.** The parent's "08a implementation status" subsection records
six that constrain this PR; §2.4 restates the three that change what 08b
must do.

**Sections marked `SOURCE-INSPECTION REQUIRED` must be closed before
freeze.** They are places where this draft states an intent that has not
yet been verified against code. Per the operator's standing rule, no commit
plan is finalized on a guessed file path, interface or behaviour.

## 1. Mandate (quoted from the frozen parent, §12 08b)

* **Goal**: "the task owns roster/thresholds/dispositions and names its
  plugin code; the framework config slims to policy only and never learns a
  task identity; external plugin modules load at run scope and register
  providers AND custom checks through the public API; declared-but-
  unresolved bindings fail closed; composition lands DETERMINISTICALLY in
  the SAME pinned artifact; scalar-only metrics reach the context as a
  typed statement (D18), consumed as `inapplicable` by per-file checks —
  never a hollow pass. 08b ends with extension provably requiring zero
  infrastructure edits (§6a.2)."
* **Allowed changes** (parent §12 08b): "`config.py` (watch the god-file
  line, §2.5), effective-config composition, the health plugin loading seam
  (§6a.3 — the existing idiom instantiated; config-named module refs), the
  public …" registration surface, the TIDMAD family's task-owned config,
  and the D18 typed statement.
* **Acceptance** (parent §10, §14.G): the out-of-tree extension proof is
  **UNIT**-owned (integration-style, tmp external fixture package — NOT
  Gate 2, no training), with a negative control proving a broken
  registration fails closed deterministically; task-owned family/threshold
  composition + pinning is UNIT + **GATE 2** (bounded TIDMAD; startup
  composition is lifecycle); D18 is UNIT.

## 2. Source audit (at 08a head `7ae72ae5`)

### 2.1 The plugin-loading idiom that 08b instantiates

Verified against source, matching the parent's §2.6 audit:

| element | location | behaviour |
|---|---|---|
| directory resolution | `ml_models/plugin_loader.py::_resolve_plugin_dirs` (`:96-115`) | `SIDERIUS_PLUGIN_DIRS`, `os.pathsep`-separated; **per-run mode scans exactly those dirs with NO fallback** to `AGENT_GENERATED_DIR` |
| registration contract | module attributes (`PLUGIN_MODEL_TYPE` / `PLUGIN_CONFIG_CLASS` / `PLUGIN_MODEL_CLASS`) | importlib file load, attribute contract |
| per-file API | `register_model_in_memory` (`:230`) | registers one plugin with no rescan |
| second instance | `agent_generated/_loss_loader.py`, `loss_models_sandbox.py` (`register_loss_in_memory:51`, `preload_global_losses:105`) | same idiom, **deliberately separate env var** `SIDERIUS_LOSS_DIRS` |
| subprocess propagation | `core/subprocess_env.py` (`PLUGIN_DIRS_ENV_VAR:39`), `core/sandbox_executor.py:316`, `core/runtime_control/gpu_measurement_runner.py:275` | already load-bearing and tested |
| failure semantics | scan fail-OPEN per file (unparseable file skipped + warning); **name resolution fail-CLOSED** (`UnknownOutputContractError`, `plugin_loader.py:158-189`) | "load what parses, refuse at the name" |
| out-of-tree proof | `scripts/run_pets_gate2.py:40-43` loaded `examples/<pack>/plugins/` through this channel in D14 | out-of-tree loading is an EXISTING exercised fact |

**08b instantiates this idiom for health. It does not invent a second
plugin system** (parent §6a.3, ruling §2).

### 2.2 The health registry and its one missing seam

`execute_tools/health_checks/registry.py` is already generic and
fail-closed: a flat `name → skill` dict; `register()` raises on duplicates;
`get()` raises listing available checks. It is populated ONLY by
`execute_tools/health_checks/__init__.py::_bootstrap_registry()` — a
central import list, which `registry.py:47-48` even documents as the way to
add a check. **That central import list is the single missing seam.**

08a added a seventh built-in (`sample_dispersion_floor`) through that same
bootstrap and recorded it as predating 08b's external channel.

### 2.3 Config, composition and pinning

* `config.py` (514 lines pre-08a) holds `CheckRef` (`:47`), `ActionConfig`
  (`:116`), `GateConfig` (`:131`), `HealthChecksConfig` (`:256`),
  `load_health_gates_config` (`:300`, module-cached at `:297`),
  `apply_monitored_files` (`:338`), `validate_health_scope` (`:369`),
  `materialize_effective_config` (`:414`).
* **A task-owned-resolution precedent already exists**: `TASK_HEALTH_PEEK`
  (`config.py:39`, `"task_health_peek"`) is a sentinel inside a `CheckRef`
  config that resolves at load time to the bound task's declared
  health-peek file set. 08b generalizes this direction of travel; it must
  also decide the sentinel's fate once the roster itself is task-owned
  (§8 Q-08b-3).
* `materialize_effective_config(source, files, workspace, resolved_scope)`
  → `(path, body_sha256)`: load → monitored-file override → scope
  validation → atomic write of `{workspace}/health_checks_effective.yaml`,
  sha over the canonical YAML body (header excluded). **Workspace-immutable
  on resume**: same body sha is reused, a mismatch RAISES and distinguishes
  "operator inputs changed" from "source YAML drifted".
* `core/run_invariants.py:340-375` materializes and hashes FIRST, then
  builds `RunInvariants`, so the pinned sha always describes the config the
  run will read. Its docstring is explicit: *never duplicate the
  normalization/hashing logic at a call site.*

**Consequence for 08b**: composition must happen INSIDE
`materialize_effective_config` (or a function it calls), never beside it.
Any second composition path would produce a sha that does not describe what
the run reads — exactly the failure the current design prevents.

### 2.4 What 08a leaves for 08b (the three that change the plan)

1. **`value_scale_unit` has no owner.** `_MV_PER_LSB = 40.0 / 128.0` is a
   module literal in `output_std.py`, `per_file_output_std.py` and
   `pearson_dispersion.py`. 08a's regime-A derivation leaves the axis
   ABSENT and **no 08a check requires it**, because requiring it would flip
   TIDMAD's std checks to `inapplicable`. **08b owns moving this scale into
   the TIDMAD family's task config** — and only after that may a check
   declare the axis. This is a real behavioural coupling: the migration
   commit must move the literal AND add the declaration together, or parity
   breaks in between.
2. **`threshold_parameter_names` is populated and asserted** ⊆ the keys each
   check reads. It is 08b's migration input. `peek_file_indices` and
   `aggregation` are deliberately EXCLUDED as framework policy.
3. **One classifier, one call site.** `schemas.classify_verdict` is the
   single verdict mapping; `applicability()` has exactly one production
   call site (`runner.evaluate_gate`), test-pinned. 08b must not add a
   second of either. The two functions 08b redirects for facts are
   `_regime_a_facts.resolve_health_facts()` and
   `runner._resolve_task_facts()` — a call-site change, not a contract
   change.

### 2.5 God-file watch (parent §2.5)

`config.py` is the module 08b grows most: task-config schema, plugin-ref
resolution, composition, and the existing gate/scope machinery would all
land in one file. **The repository's node-local decomposition rule applies
before adding a third responsibility.** §3.6 proposes the split; C1's first
checklist item re-measures the file at the implementation head rather than
trusting this number.

### 2.6 `SOURCE-INSPECTION REQUIRED` before freeze

* D18: the exact shape of the scalar-only metric statement at its producer
  (Step-06 metric handle / `evaluation_metric.py`) and how it would reach
  `HealthCheckContext`. **Not yet inspected.**
* Every caller of `materialize_effective_config` and
  `build_run_invariants`, to size the composition change.
* `configs/health_checks.yaml` current content, gate by gate, to enumerate
  exactly which keys migrate to task ownership and which stay policy.
* Whether any consumer reads `health_checks_effective.yaml` expecting the
  pre-08b key layout (`scripts/v18_wave_summary.py:97` does — its
  expectations must be checked).

## 3. Design (proposed)

### 3.1 Task health config — a task-owned document

A task declares its health behaviour in its OWN config, outside the
framework YAML (parent §6a.4):

```text
task health config
    facts            the declared health facts (08a's TaskHealthFacts axes)
    plugins          module file paths / directory list supplying code
    providers        capability key -> provider id (registered by a plugin)
    family           roster of {check id, parameters, disposition}
```

Framework config keeps gate ROLES, actions, severity, cadence — generic
policy only. **The forbidden shape is named and census-refused**: the
framework YAML must never grow `tidmad:` / `pets:` / `<user task>:` keys.

### 3.2 Run-scoped plugin loading

The task config NAMES its plugin files/directories explicitly
(config-driven, never guessed from the environment). At composition the run
loads them through the same file-based mechanism the model/loss loaders
use, and each plugin registers through the SAME PUBLIC functions the
built-ins use. Registration is run-scoped and happens before family
resolution; the pinned artifact records what was loaded.

Following the §2.1 precedent exactly: a **separate** scoping channel for
health (as losses got their own rather than sharing the model channel), the
same importlib file load, and the same "load what parses, refuse at the
name" failure split.

### 3.3 View providers and capability transport

A provider exposes capability keys; a check declares one
(`consumes_view`, already carried since 08a). The engine's whole job stays
`check requires key X → does the bound provider expose X? yes → transport
the payload; no → inapplicable`. **No `ViewKind` enum, no
`if view_kind == …` dispatch** (parent §6.3, census-refused).

### 3.4 Fail-closed resolution (parent §6a.5)

Two cases that must never be conflated:

| case | behaviour |
|---|---|
| no binding declared | regime-legal absence — UNKNOWN-style evidence-absence, NAMED, never a synthesized pass |
| binding declared but unresolvable (missing plugin file, unregistered provider/check id, capability not exposed) | **deterministic diagnostic startup error** naming the unresolved reference and what IS registered — never a silent fallback, never a downgrade to `inapplicable` |

The second row is the negative control the parent requires as executable
evidence.

### 3.5 Deterministic composition into ONE pinned artifact

`framework policy + task health config → the SAME
{workspace}/health_checks_effective.yaml`, composed deterministically
inside the existing materialization path (§2.3), so the existing sha
pinning, resume immutability and run-invariants lock keep working
unchanged in MECHANISM. Parent §15 R1/Q2 already resolved that byte
identity of the artifact may be impossible under composition; the fallback
is "semantically identical + called-out delta + fresh-workspace boundary",
with the run-invariants refusal asserted rather than weakened.

### 3.6 Decomposition of `config.py` (god-file rule)

Proposed split, applied BEFORE the new responsibilities land:

```text
config.py            framework gate policy schema + loader (unchanged surface)
_task_health_config.py   task-owned document schema + validation
_plugin_binding.py       run-scoped load + registration + fail-closed resolution
_composition.py          framework policy x task config -> effective artifact
```

Public import paths stay where consumers already point (`config.py`
re-exports), following the `schemas.py`/`runner.py` re-export precedent
already used for `severity_of` and `CandidateHealthValidity`.

## 4. Commit decomposition — detailed implementation checklists

### 4.0 Standing rules for every commit (binding during implementation)

* **Inspect before finalizing.** Each commit's first checklist item is a
  bounded read of the exact functions it edits, re-verified at the
  implementation head. If inspection reveals ambiguity or larger scope than
  this design assumes, **STOP and ask** before changing the plan.
* **Checkbox discipline.** `[ ]` = not done; `[x]` only after the change is
  implemented AND its evidence line is filled in — test counts and wall
  time, or the recorded reason a check could not run. **Every box in this
  draft is `[ ]`.**
* **Pytest verdicts come from the full log file**, never a piped tail's
  exit code.
* **Per the operator amendment of 2026-08-18** (recorded in the 08a design
  §4.0a): commits are autonomous and bounded Gates launch autonomously
  after their specification is written into the ledger. The pre-commit
  information set is still established and recorded — it is a
  self-verification checklist, not a blocking checkpoint.
* **Out of scope for ALL commits**: planner/prompt exposure of health
  (byte-pinned instead), production-default changes, the generic
  categorical/continuous check families and Pets/DAVIS bindings (08c),
  Step-09 interpretation, Step-10/12 composition-root unification.
* **Ordering-behaviour rule, adapted.** The operator's checklist standard
  asks that ordering acceptance validate the actual visited sequence rather
  than a configuration value. 08b has no `file_order`; its analogue is the
  **executed check sequence and the composed roster**. Every parity
  criterion below is written against the actual executed sequence and the
  actual persisted values, never against the composed config object.

---

### 4.1 C1 — `config.py` decomposition (behaviour-preserving)

**Goal.** Create the module boundaries 08b's new responsibilities will land
in, while changing NO behaviour — so that every later commit's diff is the
feature, not the feature tangled with a move. It is first because the
god-file rule requires establishing the boundary before adding
responsibility, and because a move done later would obscure the migration
diff that most needs review.

**Scope.**
* Changes: `execute_tools/health_checks/config.py` split per §3.6, with
  `config.py` re-exporting every currently-public name.
* Must NOT change: any schema field, any validation message, the module
  cache semantics, `materialize_effective_config`'s signature or output
  bytes, any YAML, any test.
* Depends on: nothing (08a is merged).

**Implementation plan.**
- [ ] Re-measure `config.py` at the implementation head and enumerate every
      symbol imported from it across the repository (production AND tests),
      recording the list here. If the file has not in fact grown into
      mixed responsibility, **say so and skip the split** rather than
      performing a refactor for its own sake.
      Evidence: _(pending)_
- [ ] Extract the task-config/plugin/composition seams as empty-but-typed
      modules only if C2–C4 will genuinely fill them; otherwise defer.
      Evidence: _(pending)_
- [ ] Move code with re-exports; no signature changes.
      Evidence: _(pending)_

**Validation plan.**
* Unit: entire health package green with **zero test edits** — the proof
  that the surface did not move.
* Backward-compat: an import census test asserting every previously public
  name is still importable from `config.py`.
* Static: ruff + (CI) pyright.
* Gate: none.

**Acceptance criteria.**
- [ ] Health package green, zero pre-existing test files modified.
- [ ] `materialize_effective_config` output bytes identical for a fixed
      input (asserted against a captured sha, not recomputed).
- [ ] Import census test green.

**Failure and edge cases.** A circular import between the new modules
(compose imports task config imports framework config) — resolve by keeping
schema modules leaf-level and putting orchestration in `_composition.py`.
If the split cannot be made acyclic without changing a public path, STOP.

**Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ -q > /tmp/08b_c1.log 2>&1`
      Evidence: _(pending)_

**Commit boundary.**
- [ ] Pure move + re-exports; zero behavioural diff.
- [ ] Diff summary + staged list + evidence + deviations recorded.

---

### 4.2 C2 — task health config schema (inert)

**Goal.** The task-owned document exists as a validated Pydantic schema
with fail-closed authoring-time errors, before anything loads or composes
it. Separate from C3/C4 so the CONTENT review (what a task may declare) is
not entangled with loading mechanics.

**Scope.**
* Changes: NEW `_task_health_config.py` — the document schema (facts,
  plugin refs, provider bindings, family roster with parameters and
  dispositions); NEW unit tests.
* Must NOT change: framework config, registry, runner, any check.
  Deliberately UNREACHABLE from production in this commit, asserted by a
  grep-test that C3 removes (the 08a C2 precedent — and note 08a INVERTED
  that guard rather than deleting it, which C3 should do again).
* Depends on: C1.

**Implementation plan.**
- [ ] Inspect `configs/health_checks.yaml` gate by gate and enumerate
      exactly which keys are task-owned vs framework policy, recording the
      table here BEFORE writing the schema. Cross-check against each
      check's `threshold_parameter_names` (08a) and against the exclusion
      of `peek_file_indices` / `aggregation`.
      Evidence: _(pending)_
- [ ] Define the document schema, frozen, with unknown-field rejection.
      Evidence: _(pending)_
- [ ] Reuse 08a's `TaskHealthFacts` for the facts block rather than
      declaring a second facts vocabulary.
      Evidence: _(pending)_

**Validation plan.**
* Unit: a valid TIDMAD-shaped document parses; each field's semantics
  pinned against hardcoded expectations.
* Negative/invalid: unknown check id in a roster; unknown capability key
  shape; missing plugin path; contradictory facts (delegated to 08a's
  validator); duplicate roster entries; empty roster.
* Backward-compat: production untouched — grep-test asserts no production
  module imports the new schema yet.
* Gate: none.

**Acceptance criteria.**
- [ ] Every invalid class above raises at CONSTRUCTION with a message
      naming the offending reference.
- [ ] The TIDMAD-shaped fixture document parses and its parsed values equal
      hardcoded expectations (never read back from the parser).
- [ ] Unreachability grep-test green and **mutation-proven** by adding a
      real import to a production module.

**Failure and edge cases.** A task declaring health but no roster (legal
absence, §3.4 row 1) vs a roster naming an unregistered check (fail closed,
row 2) — both asserted, and asserted to be DIFFERENT outcomes.

**Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ -q > /tmp/08b_c2.log 2>&1`
      Evidence: _(pending)_

**Commit boundary.**
- [ ] Schema + tests only; no wiring.
- [ ] Diff summary + staged list + evidence + deviations recorded.

---

### 4.3 C3 — run-scoped plugin loading + public registration API

**Goal.** External code can register health providers and checks through a
public API, loaded from config-named files at run scope — closing the ONE
missing seam (§2.2). Separate from C4 so the loading mechanism is reviewed
apart from what gets composed with it.

**Scope.**
* Changes: NEW `_plugin_binding.py` (file load + registration + fail-closed
  resolution); the public registration surface (`registry.register` reused,
  plus a provider registry if §3.3 requires one); `__init__.py` exports.
* Must NOT change: the built-ins' bootstrap behaviour, `registry.get`
  semantics, `evaluate_gate`.
* Depends on: C1, C2.

**Implementation plan.**
- [ ] Re-read `ml_models/plugin_loader.py` and
      `agent_generated/_loss_loader.py` at the implementation head and
      record the exact idiom being instantiated (env var name, scan
      semantics, per-file API, failure split), so health's instance is
      demonstrably the same shape and not a variant.
      Evidence: _(pending)_
- [ ] Decide and record the scoping channel: a health-specific env var
      following the losses precedent, config-named paths, or both. The
      parent says config-named, "never guessed from the environment" — so
      an env var, if added, is a subprocess-propagation detail, not the
      extension contract. **Ambiguity: resolve with the operator if the
      two readings diverge.**
      Evidence: _(pending)_
- [ ] Implement load → register → resolve, with the failure split: scan
      fail-OPEN per file, name resolution fail-CLOSED.
      Evidence: _(pending)_
- [ ] Remove/INVERT C2's unreachability guard into a "registration happens
      through the public API only" guard.
      Evidence: _(pending)_

**Validation plan.**
* Unit (integration-style, `tmp_path` external package): a plugin file
  outside the repo tree registers a provider and a custom check and both
  resolve.
* Negative: missing file; unparseable file; file that registers nothing;
  roster naming an id nothing registered; duplicate registration.
* Backward-compat: with no task plugins declared, the built-ins bootstrap
  exactly as before — asserted on `all_registered()`.
* Gate: none (the parent assigns the extension proof to UNIT, not Gate 2).

**Acceptance criteria.**
- [ ] An out-of-tree file registers a check that `registry.get` resolves,
      **with zero edits to any file under `execute_tools/`** — asserted by
      the test performing the whole flow from a `tmp_path` package.
- [ ] Each negative case raises a DETERMINISTIC error naming the
      unresolved reference AND listing what is registered.
- [ ] A census test asserts no external registration path requires editing
      `execute_tools/health_checks/__init__.py`.

**Failure and edge cases.** Registration leaking across tests (the existing
`clean_registry` fixture is the precedent and must be used); a plugin that
raises at import; a plugin registering a name that collides with a built-in
(must raise, per `register`'s existing duplicate rule).

**Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ -q > /tmp/08b_c3.log 2>&1`
      Evidence: _(pending)_

**Commit boundary.**
- [ ] Loading + registration only; no composition, no TIDMAD migration.
- [ ] Diff summary + staged list + evidence + deviations recorded.

---

### 4.4 C4 — deterministic composition into the pinned effective artifact

**Goal.** Framework policy and the task health config compose into the SAME
pinned `health_checks_effective.yaml`, inside the existing materialization
path, so the sha keeps describing what the run reads.

**Scope.**
* Changes: NEW `_composition.py`; `materialize_effective_config` gains the
  task config as an input; `core/run_invariants.py` call-site threading.
* Must NOT change: the sha mechanism, resume immutability semantics, the
  atomic-write behaviour, or the artifact's basename.
* Depends on: C1–C3.

**Implementation plan.**
- [ ] Enumerate every caller of `materialize_effective_config` and
      `build_run_invariants` and record them here before changing the
      signature.
      Evidence: _(pending)_
- [ ] Compose deterministically (stable key order) and record in the
      artifact header what task config and which plugin files were loaded.
      Evidence: _(pending)_
- [ ] Decide and record whether the composed body is byte-identical to
      pre-08b for TIDMAD. If not (parent §15 R1 anticipates this), record
      the exact delta and rely on the fresh-workspace boundary, with the
      run-invariants refusal ASSERTED, not weakened.
      Evidence: _(pending)_

**Validation plan.**
* Unit: composition determinism (same inputs → byte-identical body across
  repeated runs and across dict ordering perturbation).
* Backward-compat / default parity: with no task config supplied, the
  artifact is byte-identical to pre-08b — captured BEFORE this commit as a
  frozen sha, following 08a's capture-first discipline.
* Negative: resume with a changed task config raises the existing mismatch
  error, and the message distinguishes the new cause from the two existing
  ones.
* Gate 2: **required** (parent §10 — startup composition is lifecycle).
  Specified in §7 and launched only after its spec is written.

**Acceptance criteria.**
- [ ] No-task-config artifact byte-identical to the captured pre-08b sha.
- [ ] Composition is order-independent and repeatable (asserted over
      shuffled input orderings).
- [ ] Resume mismatch raises and NAMES which input changed.
- [ ] The pinned sha still describes the file the run reads — asserted by
      re-reading the artifact and re-hashing, not by trusting the return.

**Failure and edge cases.** A second composition path appearing anywhere
(census-refuse it); a task config that composes to a roster referencing an
unregistered check (must fail closed at startup, not at round 1); scope
validation interacting with a task-owned roster.

**Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ tests/unit/core/ -q > /tmp/08b_c4.log 2>&1`
      Evidence: _(pending)_

**Commit boundary.**
- [ ] Composition only; TIDMAD's values still in the framework file.
- [ ] Diff summary + staged list + evidence + deviations recorded.

---

### 4.5 C5 — TIDMAD family ownership migration (the parity commit)

**Goal.** TIDMAD's roster, thresholds, dispositions **and the millivolt
scale** move out of framework-owned code/config into the TIDMAD family's
task-owned config, with values unchanged and provenance comments carried.
This is where the framework YAML stops carrying task science.

**Scope.**
* Changes: `configs/health_checks.yaml` slimmed to policy; NEW TIDMAD task
  health config; `_MV_PER_LSB` migrated out of `output_std.py`,
  `per_file_output_std.py`, `pearson_dispersion.py`; those checks may then
  declare `value_scale_unit` (08a deliberately could not).
* Must NOT change: any threshold VALUE, any gate id, any check id, any
  action/severity, the firing point, or any verdict.
* Depends on: C1–C4.

**Implementation plan.**
- [ ] Capture-first: freeze the six checks' verdicts AND the composed
      effective artifact BEFORE the migration, reusing 08a's manifest
      generator where possible.
      Evidence: _(pending)_
- [ ] Move values with provenance comments; **the mV scale and the
      `value_scale_unit` declaration move in the SAME commit** — 08a
      recorded that separating them breaks parity in between.
      Evidence: _(pending)_
- [ ] Census: framework YAML contains no task identity, no threshold, no
      roster.
      Evidence: _(pending)_

**Validation plan.**
* Parity: 08a's manifest replayed — `passed`/`reason`/`metrics`/`verdict`
  byte-identical for all 27 cases.
* Default parity on the executed sequence: same gates selected, same
  executed check SEQUENCE, same actions, field-by-field equality of every
  persisted `PersistedHealthGateResult` field against a pre-C5 dump.
* Negative: a framework YAML carrying a task threshold is REFUSED.
* Gate 2: **required** — the composed artifact and real verdicts on the
  real path.

**Acceptance criteria.**
- [ ] 27/27 manifest cases byte-identical.
- [ ] Persisted fields byte-equal on TIDMAD-shaped fixtures.
- [ ] Framework-YAML census green.
- [ ] `value_scale_unit` is now DECLARED by the std checks and the derived
      TIDMAD facts SUPPLY it — both directions asserted, so the axis is
      live rather than merely present.

**Failure and edge cases.** A threshold value silently changing during the
move (the manifest catches it); the effective-config sha changing (expected
— handled by the fresh-workspace boundary, asserted); a check declaring the
scale axis before the facts supply it (parity break — the reason both move
together).

**Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ -q > /tmp/08b_c5.log 2>&1`
      Evidence: _(pending)_
- [ ] Manifest parity script output recorded.
      Evidence: _(pending)_

**Commit boundary.**
- [ ] Ownership move only; no new mechanism.
- [ ] Diff summary + staged list + evidence + deviations recorded.

---

### 4.6 C6 — D18: scalar-only metrics as a typed statement

**Goal.** A task whose metric produces only a scalar says so in a TYPED
way, and per-file checks consume that as `inapplicable` — never a hollow
pass.

**Scope.**
* Changes: the typed statement at its producer; `HealthCheckContext`
  transport; per-file checks' declarations.
* Must NOT change: any metric value, any golden-metric arithmetic. **No
  check may consume the metric SCALAR** (parent §5, census-refused).
* Depends on: C1–C5.

**Implementation plan.**
- [ ] **SOURCE-INSPECTION REQUIRED (§2.6)**: inspect the Step-06 metric
      handle and `evaluation_metric.py` to establish where a scalar-only
      statement originates and how it reaches the tuner's context
      construction. Record the real path before designing the transport.
      Evidence: _(pending)_
- [ ] Add the typed statement and thread it; declare it as a context input
      in 08a's `CONTEXT_INPUT_PREDICATES` vocabulary if that is the right
      seam (verify).
      Evidence: _(pending)_

**Validation plan.**
* Unit: a scalar-only task makes per-file checks `inapplicable` with the
  axis named; a per-file-capable task leaves them applicable.
* Negative control: TIDMAD (per-file metric) unchanged — asserted.
* Gate: none.

**Acceptance criteria.**
- [ ] The statement is TYPED (not an absent field read as a signal).
- [ ] Per-file checks report `inapplicable`, not `passed`, under a
      scalar-only task.
- [ ] TIDMAD's per-file behaviour is unchanged.

**Failure and edge cases.** A task that declares nothing about per-file
capability (absence ≠ scalar-only — must not be inferred); a metric that
changes capability mid-run (out of scope; refuse).

**Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ -q > /tmp/08b_c6.log 2>&1`
      Evidence: _(pending)_

**Commit boundary.**
- [ ] D18 only.
- [ ] Diff summary + staged list + evidence + deviations recorded.

---

### 4.7 C7 — out-of-tree extension proof + census + docs sync

**Goal.** The completion criterion (parent §14.G/H) becomes executable: an
external package's config + provider + custom check + plugin-local
capability run end-to-end with ZERO framework edits, and the negative
control fails closed.

**Scope.**
* Changes: NEW integration-style unit test building a `tmp_path` external
  package; census guardrail tests; docs
  (`pluggable_health_checks.md`, this ledger, the parent's status).
* Must NOT change: any production behaviour.
* Depends on: C1–C6.

**Implementation plan.**
- [ ] Build the external fixture package OUTSIDE the repo tree
      (`tmp_path`): task health config + provider plugin + custom check
      plugin declaring a plugin-local capability key.
      Evidence: _(pending)_
- [ ] Assert the full chain: config → loader → registration → family
      resolution → provider → custom check → `HealthCheckResult`.
      Evidence: _(pending)_
- [ ] Negative control: break the registration (missing file / wrong id /
      unexposed capability) → deterministic fail-closed error.
      Evidence: _(pending)_
- [ ] Census: zero task-name branches; no central task registry; no closed
      view-kind enum; no framework-YAML task identity; **no registration
      path requiring a central import edit**.
      Evidence: _(pending)_
- [ ] Docs sync as the last step, quoting each documented flag/behaviour
      against merged source.
      Evidence: _(pending)_

**Validation plan.**
* Unit: the whole extension proof and its negative control.
* Census: the guardrail suite above.
* Gate: none (parent §10 explicitly assigns this to UNIT, not Gate 2).

**Acceptance criteria.**
- [ ] The proof test passes with **zero diffs** to `core/`,
      `execute_tools/`, `agent/`, `configs/` and `examples/` — asserted by
      the test's own construction, and by a census that the fixture package
      lives entirely under `tmp_path`.
- [ ] The negative control fails closed with a message naming the
      unresolved reference.
- [ ] Every census guardrail green.

**Failure and edge cases.** The proof passing because the fixture
accidentally imported an in-repo module (assert the package's files are the
only source of its provider/check); registration leaking into other tests.

**Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ -q > /tmp/08b_c7.log 2>&1`
      Evidence: _(pending)_

**Commit boundary.**
- [ ] Proof + census + docs; no production change.
- [ ] Diff summary + staged list + evidence + deviations recorded.

## 5. Test disposition (existing families)

To be completed at freeze, after the §2.6 inspections. Provisionally: all
08a families KEEP; `test_config_loader.py` and
`test_step00_health_config_baseline.py` need explicit dispositions because
C5 changes the framework YAML they pin — **that disposition must be argued,
not assumed**, since a baseline test that is simply updated to match a new
value proves nothing.

## 6. Evidence economy

Targeted per-commit tests + the health package per commit; NO local full
suite; NO manual dispatch; ONE canonical full CI on the final integrated
Step-08 head (parent §11). Gate 2 twice at most — C4 and C5 share one
bounded run if their heads permit, which §7 decides at implementation time.

## 7. Gates

* **Gate 1: NOT REQUIRED** — parent §10/§15 Q3. 08b makes no prompt/PB
  delta; the 08a byte-pin discipline applies unchanged. Any accidental
  delta re-dispositions Gate 1 with the operator.
* **Gate 2: REQUIRED, bounded** — parent §10 assigns "task-owned
  family/threshold composition + pinning" to UNIT + Gate 2 because startup
  composition is lifecycle. Full specification (HEAD, command, claim,
  expected evidence, bounded scope, wall time, evidence destination) is
  written into §10 BEFORE launch, per the 08a §4.0a amendment.
* **The out-of-tree extension proof is NOT a Gate** — parent §10 assigns it
  to UNIT, integration-style, no training. Do not escalate it.

## 8. Risks / open questions (for operator review)

* **Q-08b-1 — the scoping channel.** Parent §6a.3 says plugin refs are
  config-named and "never guessed from the environment", while the idiom
  being instantiated is env-var-driven. Proposal: config names the files;
  an env var exists only for subprocess propagation of what the config
  already chose. **Needs an explicit ruling.**
* **Q-08b-2 — effective-artifact byte identity.** Parent §15 R1/Q2 already
  allows "semantically identical + called-out delta + fresh-workspace
  boundary". Confirm that fallback is acceptable for TIDMAD at C4/C5, since
  the sha WILL move once composition includes a task document.
* **Q-08b-3 — the `TASK_HEALTH_PEEK` sentinel.** It already resolves
  task-owned data inside the framework config (`config.py:39`). Once the
  roster is task-owned, does the sentinel stay, move, or disappear?
* **Q-08b-4 — provider payload contracts.** How much of the view payload
  contract lands in 08b versus 08c, given 08c owns the STANDARD
  capabilities? Proposal: 08b ships the transport and plugin-local keys
  only; standard capabilities ship in 08c.
* **R-08b-1 — `config.py` growth.** Mitigated by C1, but C1 must be honest:
  if the split is not warranted, skip it rather than refactor for its own
  sake.
* **R-08b-2 — the migration commit (C5) is the highest-risk diff in
  Step 08.** It moves real thresholds and a real physical scale. Capture-
  first parity is mandatory, and the mV scale must move together with its
  declaration.

## 9. Adversarial self-review

1. *Does 08b invent a second plugin system?* No — §2.1 pins the existing
   idiom and C3's first item requires re-reading it so health's instance is
   the same shape.
2. *Could the extension proof pass while a framework edit is still
   required?* The census in C7 asserts no registration path needs the
   central import list, and the proof package lives entirely under
   `tmp_path`.
3. *Could TIDMAD verdicts move during the migration?* C5 is capture-first
   and replays 08a's 27-case manifest; the mV scale moves together with its
   declaration precisely because 08a proved separating them breaks parity.
4. *Could composition produce a sha that lies?* C4 asserts by re-reading
   and re-hashing the written artifact, not by trusting the return value.
5. *Does anything here consume the golden metric?* No — C6 explicitly
   forbids it and the census refuses it.
6. *Is "no binding declared" distinguishable from "binding unresolvable"?*
   Yes — §3.4, asserted as two DIFFERENT outcomes in C2 and C3.
7. *Checkbox honesty?* Every box in this draft is `[ ]`; §2.6 lists what is
   not yet inspected rather than pretending it is.

## 10. Ledger

*(filled per commit during implementation)*
