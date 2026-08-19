# PR 08b — extension architecture: task-owned config + plugin binding + TIDMAD family + D18 (child design)

## 0. Status and provenance

**REVISION 2 — READY FOR OPERATOR REVIEW. NOT YET FROZEN.**

Rev 1 was drafted at the PRE-MERGE 08a head `7ae72ae5` and carried six
`SOURCE-INSPECTION REQUIRED` markers. The operator's review ruling
(2026-08-19) returned it **APPROVED IN DIRECTION / NOT READY TO FREEZE**
with eighteen load-bearing items. Rev 2 answers all eighteen.

**Audit anchor.** Every statement below is verified against **master
`a226495b`**, which contains the merged 08a (squash **`7da1e45e`**, PR #235)
plus its doc sync. Rev 1's pre-merge assumptions were re-verified, and two
of 08a's own recorded findings were CORRECTED in the process (§2.7).

**No `SOURCE-INSPECTION REQUIRED` markers remain.** D18, the composition
callers, the framework YAML, the run lifecycle, `TASK_HEALTH_PEEK` and the
numerical value scale were all read at the anchor and are recorded below
with file and line.

Child of the FROZEN Step-08 parent (rev 3). Authority order: frozen parent >
current source (§2) > merged 08a implementation and ledger > roadmap
§8/§22.24 > `pluggable_health_checks.md`.

### 0.1 Operator rulings incorporated (all four questions closed)

| id | ruling |
|---|---|
| **Q-08b-1** | **RESOLVED — config is the semantic authority.** Task config chooses plugin refs. An env var may exist ONLY as framework-generated subprocess transport for the already-resolved set. No ambient user-facing override, no precedence guessing. |
| **Q-08b-2** | **RESOLVED — the composed artifact SHA MAY change.** Do not distort serialization to preserve the old one. Required instead: deterministic composition, semantic TIDMAD parity, exact delta recorded, new pin used, old-workspace mismatch still fail-closed, fresh-workspace boundary. |
| **Q-08b-3** | **RESOLVED as a source-grounded disposition** — see §2.5 and §3.8. Not an architecture question. |
| **Q-08b-4** | **RESOLVED AS PROPOSED.** 08b owns opaque capability keys, the provider protocol, payload transport, external provider/check registration and plugin-local capabilities. 08c owns the framework-standard `categorical_predictions` / `continuous_samples` and the reusable generic checks plus Pets/DAVIS bindings. 08b's synthetic capability is an extension PROOF, not a new scientific primitive. |

### 0.2 The three contracts this revision exists to freeze

```text
schema parse            ≠   plugin resolution
invalid binding         ≠   inapplicable check
external plugin bytes   ∈   pinned run identity
```

Each was open in rev 1 and each would have become Step-10/12 architecture
debt. They are frozen in §3.1, §3.2 and §3.6.

## 1. Mandate (frozen parent, §12 08b)

**Goal.** The task owns roster, thresholds and dispositions and names its
plugin code; the framework config slims to policy only and never learns a
task identity; external plugin modules load at run scope and register
providers AND custom checks through the public API; declared-but-unresolved
bindings fail closed; composition lands deterministically in the SAME pinned
artifact; scalar-only metrics reach the context as a typed statement (D18),
consumed as `inapplicable` by per-file checks rather than a hollow pass. 08b
ends with extension provably requiring zero infrastructure edits.

**Acceptance** (parent §10, §14.G). The out-of-tree extension proof is
**UNIT**-owned — integration-style, temporary external fixture package, NOT
Gate 2, no training — with a negative control proving a broken registration
fails closed. Task-owned composition + pinning is UNIT + **Gate 2**. D18 is
UNIT.

## 2. Source audit (at master `a226495b`, merged 08a `7da1e45e`)

### 2.1 The plugin-loading idiom 08b instantiates

| element | location | behaviour |
|---|---|---|
| directory resolution | `ml_models/plugin_loader.py::_resolve_plugin_dirs` `:96-115` | `SIDERIUS_PLUGIN_DIRS`, `os.pathsep`-separated; per-run mode scans exactly those dirs, **no fallback** |
| registration contract | module attributes (`PLUGIN_MODEL_TYPE` / `_CONFIG_CLASS` / `_MODEL_CLASS`) | importlib file load |
| per-file API | `register_model_in_memory` `:230` | one plugin, no rescan |
| second instance | `agent_generated/_loss_loader.py`, `loss_models_sandbox.py` | same idiom, deliberately **separate** env var `SIDERIUS_LOSS_DIRS` |
| subprocess propagation | `core/subprocess_env.py:39`, `sandbox_executor.py:316` | already load-bearing |
| failure split | `plugin_loader.py:158-189` | scan fail-**open** per file; name resolution fail-**closed** |
| out-of-tree precedent | `scripts/run_pets_gate2.py:40-43` | D14 already loaded `examples/<pack>/plugins/` this way |

08b instantiates this idiom. It does not invent a second plugin system.

### 2.2 The health registry and the one missing seam

`registry.py` is a flat `name → skill` dict; `register()` raises on
duplicates; `get()` raises listing what is available. It is populated ONLY
by `__init__.py::_bootstrap_registry()` (`:68`, invoked `:93`) — a central
import list. **That is the single missing seam.** 08a added a seventh
built-in through the same bootstrap and recorded it as predating 08b.

### 2.3 The framework YAML, gate by gate (the migration table's source)

Read verbatim at the anchor. Both shipped configs
(`configs/health_checks.yaml`, `..._baseline_observe_mode.yaml`) have the
identical six-gate shape:

| gate id | `gate_role` | `after_round` | `short_circuit` | `on_pass` | `on_fail` | check config keys |
|---|---|---|---|---|---|---|
| `output_diversity_blocking` | blocking | every | true | continue | invalidate_round | `min_unique_int8_values: 25`, `peek_samples: 100000`, `peek_file_indices: task_health_peek`, `aggregation: any_pass` |
| `output_std_blocking` | blocking | every | true | continue | invalidate_round | `min_std_mv: 1.0`, `peek_samples`, `peek_file_indices`, `aggregation` |
| `amplitude_collapse_blocking` | blocking | every | true | continue | invalidate_round | `collapse_threshold: 0.95`, `peek_samples`, `peek_file_indices`, `aggregation` |
| `pearson_dispersion_recording` | observational | every | false | continue | continue | `peek_samples: 1000000` |
| `spectral_peak_ratio_recording` | observational | every | false | continue | continue | `peek_samples: 1000000` |
| `per_file_output_std_recording` | observational | every | false | continue | continue | `peek_samples: 100000` |

**The decisive observation for §3.7**: the policy fields are perfectly
correlated with two classes and nothing else. Every blocking gate is
`(blocking, true, continue, invalidate_round)`; every recording gate is
`(observational, false, continue, continue)`. There are exactly **two**
policy shapes in production, which is what makes a disposition-key
composition rule a description of current reality rather than a new
invention.

Each gate also carries a long `reason:` prose block. That prose is TASK
science (empirical margins, band exemplars, the 6.3556 investigation) and
migrates with the task, not with policy.

### 2.4 Composition, pinning and their callers

* `materialize_effective_config(source, files, workspace, resolved_scope)`
  → `(path, body_sha256)`; load → monitored-file override → scope validation
  → atomic write; **sha over the canonical YAML body, header excluded**;
  workspace-immutable on resume (same sha reused; mismatch RAISES and
  distinguishes "operator inputs changed" from "source YAML drifted").
* **The only production caller is `core/run_invariants.py:380`**, inside
  `build_run_invariants`, which materializes and hashes FIRST and then
  builds the lock — its docstring forbids duplicating that logic at a call
  site. `core/resume.py:354` MIRRORS the computation for resume and must be
  kept in step.
* `build_run_invariants` has **four** production callers:
  `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py:576`,
  `scripts/run_comparison.py:1221`,
  `sdsc_submission_scripts/run_one_iteration.py:1446`,
  `workflows/model_exploration.py:1845`.
* `RunInvariants._CANONICAL` (`core/run_invariants.py:134-`) includes
  **`health_config_sha256`**; `validate_run_invariants` (`:264`) raises
  naming every drifted field. **Consequence for §3.6**: anything folded
  into the hashed BODY is automatically part of the pinned run identity and
  automatically fail-closed on resume — no new canonical field, no new
  comparison logic.
* Effective-artifact consumers outside the health package:
  `scripts/v18_wave_summary.py:97` reads it and asserts every check's
  effective config; `core/resume.py:374` locates it. Both must survive the
  composed layout — pinned as a compatibility assertion in C4.

### 2.5 `TASK_HEALTH_PEEK` — full census (closes Q-08b-3)

Defined `config.py:39` (`"task_health_peek"`); documented `:68`; validated
`:104`; and resolved at `:110-112` to
`list(resolve_dataset_profile().health_peek_files)`. Used in BOTH shipped
YAMLs, on the three BLOCKING gates only (6 occurrences). **No Python
consumer outside `config.py`.**

So it is already the "task-owned data reaching the framework config"
pattern, keyed on Step-02c's `DatasetProfile.health_peek_files`. Disposition
in §3.8.

### 2.6 D18 — the producer, read at the anchor (no invention)

**The typed scalar-only statement already exists.**
`execute_tools/evaluation_metric.py:406`:

```python
per_sample: list[float | None] | None = Field(
    default=None,
    description="Optional structured evidence indexed by input identity; None for scalar-only.",
)
```

The Pets `AccuracyMetric` docstring (`:554`) states it explicitly:
*"`per_sample` is `None` — no per-file vector concept exists here."*
TIDMAD's instance returns `(scalar, file_vector, ("anchor_map",))` (`:540`).

**The hollow bridge is at `nodes/ml_hyperparameter_tune_agent/execution.py:894-897`:**

```python
file_vector, final_scalar = (
    list(metric_result.per_sample or []),
    metric_result.scalar,
)
```

with the comment *"a scalar-only instance an empty one"*, and
`file_vector=file_vector` reaches `HealthCheckContext` at `:951`. So a
scalar-only task presents per-file checks with `[]`, which today reads as
"no files" and yields a passing NA — exactly the hollow pass the parent
forbids. **D18 is therefore a transport change, not a new flag**: the
statement exists at the producer and is destroyed at the bridge.

### 2.7 Two corrections to 08a's own recorded findings

Found while re-auditing at the anchor. Both are recorded here rather than
silently fixed, because 08b consumes them:

1. **`_MV_PER_LSB` is duplicated in FOUR check modules, not three.** 08a's
   ledger and the parent's status note say three (`output_std`,
   `per_file_output_std`, `pearson_dispersion`). Source at the anchor shows
   a fourth: `spectral_peak_ratio.py:44`, used at `:116` to scale samples
   to mV before the PSD. C5 must migrate four.
2. **`output_std.py:43`'s comment — "matches `execute_tools/scoring_utils.py`"
   — is STALE.** `scoring_utils.py` contains no such constant at the anchor
   (verified by grep). The nearest other copies are five one-off scripts
   under `scripts/`. So the health package is the only production owner, and
   there is no scoring-side authority to defer to.

### 2.8 Run lifecycle — is "run-scoped" real? (closes ruling item 6)

Audited because the registry is module-global and "loaded at startup" is not
by itself proof of run scope.

* `run_workflow` (`workflows/model_exploration.py:1340`) is the RUN
  boundary: it calls `build_run_invariants` **once** (`:1845`), then loops
  iterations (`for iteration in range(start_iteration, start_iteration +
  max_iterations)`) and, within an iteration, tunes multiple model types.
  So **one run may contain many iterations and many models — but it is still
  ONE run, one workspace, one invariants lock, one effective health config.**
* **Chain mode runs each iteration as its own subprocess with
  `max_iterations=1`** (comment in `run_workflow`; `run_one_iteration.py`'s
  module docstring: *"Runs ONE iteration of `run_workflow()`
  (max_iterations=1)"*).
* Each of the four `build_run_invariants` call sites is a `main()`/startup
  path. **No production entry point loops over runs.**

**Conclusion — source-proven, with a caveat.** In production one process
hosts at most one run, so plugins loaded at run startup are run-scoped *in
fact*. But that is an emergent invariant, not an enforced one, and tests
already execute many things in one process. **Rev 2 therefore does not rely
on it**: §3.5 makes the invariant executable and fail-closed.

## 3. Design (frozen for rev 2)

### 3.1 Two validation phases — authoring vs resolution

**The contract:** a schema may not require an externally supplied identifier
to exist, because it necessarily does not exist until its plugin loads.

```text
PHASE A — AUTHORING / SCHEMA VALIDATION        (no plugins loaded)
    field shape · non-empty ids · plugin-ref syntax
    duplicate roster entries · valid disposition names
    contradictory facts · unknown schema fields
    ACCEPTS any syntactically valid check/provider/capability id
    NEVER interprets an opaque capability value

           ↓  load declared plugins  ↓

PHASE B — BINDING RESOLUTION                   (plugins loaded)
    resolve check ids · resolve provider ids
    validate capability exposure · validate family references
    UNRESOLVED  →  deterministic fail-closed startup error
```

Phase A rejects: empty id, malformed ref, duplicate roster entry,
contradictory facts, unknown field, invalid disposition.
Phase A must **not** reject: unknown check id, unknown provider id, unknown
capability key.

### 3.2 Unresolvable binding is an ERROR, never `inapplicable`

Rev 1 said both, in §3.3 and §3.4. Frozen resolution:

| situation | outcome |
|---|---|
| family declares a check requiring capability `X`; bound provider does not advertise `X` | **deterministic startup/binding ERROR** |
| declared plugin file missing / unloadable | **deterministic startup ERROR** |
| declared check/provider id not registered after loading | **deterministic startup ERROR** |
| task declares no health binding at all | regime-legal absence — UNKNOWN-style evidence-absence, NAMED, never a synthesized pass |
| binding VALID, but task facts / round context make the check semantically non-applicable | `CheckVerdict.INAPPLICABLE` (08a semantics, unchanged) |
| provider raises while materializing an applicable view | `CheckVerdict.ERROR` — fail closed, never inapplicable |

**A configuration error is never downgraded to a Health verdict.**

### 3.3 The minimal view-provider protocol (two phases, I/O-ordered)

Frozen because 08a's pre-I/O applicability invariant would otherwise be
undermined: a provider must not have to open an artifact to decide whether a
check applies.

```text
PHASE 1 — METADATA ONLY, NO ARTIFACT I/O
    provider_id      : str                 stable identity, config-referenced
    capabilities     : frozenset[str]      opaque keys, never interpreted
  (advertised at registration; composition resolves against these)

PHASE 2 — MATERIALIZATION, I/O PERMITTED
    materialize(capability_key, ctx, config) -> HealthView
  invoked by the RUNNER, only after applicability returned applicable
```

* `HealthView` is a thin frozen envelope: `capability_key`, `provider_id`,
  and an opaque `payload`. The engine never inspects `payload`. Standard
  payload contracts are 08c.
* **Transport to the check**: `HealthCheckSkill.run(ctx, config, *,
  view=None)` — keyword-only with a default, so all seven existing checks
  and any pre-08b/external check keep working untouched. A check that
  declares `consumes_view` and is invoked through a gate receives the
  materialized view; one that does not, does not.
* **Provider errors** are caught by the runner exactly like check
  exceptions (the PR #101 Bug-B guard shape) and produce
  `CheckVerdict.ERROR`.
* Provider config lives in the task health config beside the provider ref.

**Required ordering, executable:**

```text
binding resolution → capability advertisement → applicability
    → (only if applicable) materialize → check.run
```

C3 adds a test that FAILS if an inapplicable check causes
`materialize` to be called or any artifact to be opened.

### 3.4 `evaluate_gate` does change — a rev-1 error corrected

Rev 1's C3 said `evaluate_gate` "must NOT change" while C7 required a
provider→check flow through it. That is not satisfiable. Rev 2 states
plainly: **`evaluate_gate` gains the materialization step** between
applicability and `skill.run`, and nothing else about it moves — check
order, short-circuit, action selection and the exception guard are
unchanged, pinned by the 08a tests.

### 3.5 Run scope, made executable rather than assumed

Given §2.8's emergent one-run-per-process invariant, 08b adds a **run-scoped
registration ledger**:

* at run start, plugin loading records the resolved plugin set (refs +
  digests, §3.6) in a process-level ledger alongside the registrations it
  produced;
* a SECOND load in the same process with a **different** resolved set
  **fails closed** with a diagnostic naming both sets;
* an identical re-load is idempotent (re-entrant startup, resume);
* built-ins remain bootstrapped independently and are never removed by
  external loading.

This converts "one run per process" from an assumption into an enforced,
testable property, and gives a deterministic two-run counterfactual test
(§4.2 validation) rather than relying on the test-only `clean_registry`
fixture as production evidence.

### 3.6 External plugin identity is part of the pinned run identity

The hashed effective-config body — and therefore the canonical
`health_config_sha256` (§2.4) — **must include the resolved plugin set and
each file's content digest**:

```yaml
resolved_plugins:
  - ref: ./plugins/health.py
    resolved_path: /abs/path/plugins/health.py
    sha256: "abc…"
```

* a configured DIRECTORY is resolved deterministically, sorted
  deterministically, and every loaded file is pinned individually;
* because this rides the existing hashed body, **no new canonical field and
  no new comparison logic is needed** — `validate_run_invariants` already
  raises naming the drifted field;
* consequence, and the reason this is required: *same config, same path,
  changed plugin bytes* → different body sha → **resume fails closed**.
  Recording the plugin only in the unhashed header would leave that case
  silently accepted.

Negative test in C4: mutate a plugin file in place, resume, expect refusal.

### 3.7 Task disposition ↔ framework policy (deterministic, no duplicate truth)

Frozen shape, and §2.3 shows it is a description of the current YAML rather
than a new invention (production has exactly two policy shapes):

```text
TASK  chooses WHICH disposition applies, per roster entry
FRAMEWORK  defines WHAT that disposition does operationally
```

| field | owner after 08b |
|---|---|
| gate `id` | **task** roster — they are persisted join keys for `health_gate_results`; TIDMAD keeps its six ids byte-identical |
| check `name` | **task** roster |
| thresholds (`min_unique_int8_values`, `min_std_mv`, `collapse_threshold`) | **task** (08a's `threshold_parameter_names`) |
| `peek_samples` | **task** parameter — read by the check, NOT a threshold (08a's corrected semantics) |
| `peek_file_indices` | **task** (see §3.8) |
| numerical value scale | **task** (§3.9) |
| `reason:` prose | **task** — it is task science |
| `disposition` | **task** selects the key |
| `gate_role`, `on_pass`, `on_fail`, `short_circuit`, severity | **framework** policy, DERIVED from the disposition |
| `after_round` (cadence) | **framework** policy |
| `aggregation` | **framework** policy (08a already excluded it from task thresholds) |

There is exactly ONE definition of each field. A task cannot set
`gate_role`/`action`/`severity`, so the conflicting-copies failure mode is
structurally impossible rather than resolved by precedence.

### 3.8 `TASK_HEALTH_PEEK` disposition (Q-08b-3, source-grounded)

Its only job (§2.5) is to inject `DatasetProfile.health_peek_files` into a
framework-owned check config. Once the roster is task-owned, the task config
states its peek files directly and the sentinel has no remaining purpose.

**Disposition: remove it in C5**, together with the framework YAML entries
that use it — provided the C5 audit confirms no consumer outside
`config.py`. If a bounded legacy Regime-A path still needs it, it may remain
strictly as a **legacy compatibility adapter**, explicitly *not* the future
extension mechanism, *not* required by external tasks, and *not* task-package
protocol vocabulary. Either way it is never promoted into generic Health
vocabulary.

### 3.9 Numerical value-scale ownership (not just the unit)

`value_scale_unit` is an applicability FACT. The arithmetic needs the
NUMBER. Four checks currently hold `_MV_PER_LSB = 40.0/128.0` (§2.7).

Frozen: the task health config declares **one** typed value-scale
declaration — unit plus numerical factor — at family level; the four checks
receive the resolved factor as a parameter. **Not** three or four duplicated
literals. The unit declaration and the numerical factor migrate **atomically
in C5** together with the checks' `value_scale_unit` requirement, because
08a proved that separating a scale declaration from its consumers breaks
parity in between.

### 3.10 How a run selects its task health config (interim binding path)

Step-10/12's unified composition root does not exist yet, so 08b freezes a
narrow, bounded seam:

```text
EXPLICIT PATH (new/external tasks)
    the caller supplies an explicit task-health-config binding, threaded
    through build_run_invariants -> materialize_effective_config

LEGACY REGIME-A PATH (no explicit binding supplied)
    resolve the in-repo TIDMAD reference pack's health config
```

The legacy path is selected by **absence of an explicit binding**, never by
a task name — no `if task == "tidmad"` anywhere. It is a bounded
compatibility seam that Step 10/12 replaces with the unified root, and it is
explicitly NOT the extension mechanism. **C5 cannot move TIDMAD's science
out of the framework YAML until this path exists**, which is why it lands in
C4/C5 and not later.

## 4. Commit decomposition

Restructured from rev 1 per ruling item 17: **no commit exists to preserve a
number, and no empty modules are created.** Rev 1's standalone "`config.py`
decomposition" commit is dissolved — new responsibilities land in new
private modules as they arrive, and `config.py` is split only if the C1
audit shows it has actually become mixed-responsibility.

### 4.0 Standing rules

* Each commit's first item is a bounded read of the exact functions it
  edits, at the implementation head. Ambiguity or larger scope than assumed
  → **STOP and ask**.
* `[ ]` = not done; `[x]` only with recorded evidence. **Every box below is
  `[ ]`.**
* Pytest verdicts from complete log files.
* Commits are autonomous; bounded Gates launch autonomously after their spec
  is written into the ledger (08a §4.0a amendment).
* Out of scope for all commits: prompt/planner exposure, production-default
  changes, the standard categorical/continuous families and Pets/DAVIS
  bindings (08c), Step-09, Step-10/12 composition root.
* **Ordering-behaviour rule, adapted**: 08b has no `file_order`; its
  analogue is the **executed check sequence, the composed roster and the
  persisted values**. Every parity criterion below is written against those,
  never against the composed config object.

---

### 4.1 C1 — task health config schema (authoring validation only)

**Goal.** The task-owned document exists as a validated schema that accepts
externally supplied identifiers, so content review is separate from loading
mechanics — and so the Phase-A/Phase-B split (§3.1) is established before
anything can blur it.

**Scope.** New `_task_health_config.py` (document schema: facts, plugin
refs, provider bindings, roster of `{gate_id, check, disposition,
parameters}`, value-scale declaration). Deliberately unreachable from
production; a grep-test asserts it, INVERTED in C3 rather than deleted (the
08a precedent). Must not change framework config, registry, runner or any
check. Depends on: nothing.

**Implementation plan.**
- [ ] Re-measure `config.py` at the head and decide whether it has become
      mixed-responsibility. **If not, do not split it**; place new
      responsibilities in new modules and say so here.
- [ ] Produce the exact ownership/migration table from the CURRENT
      `configs/health_checks.yaml`, gate by gate, against §2.3.
- [ ] Define the schema with **authoring validation only** (§3.1 Phase A);
      reuse 08a's `TaskHealthFacts` rather than a second facts vocabulary.
- [ ] Define the value-scale declaration (§3.9) as one typed family-level
      value.

**Validation plan.** Unit: a TIDMAD-shaped document parses; parsed values
equal hardcoded expectations (never read back from the parser). Negative:
empty id, malformed plugin ref, duplicate roster entry, invalid disposition
name, unknown field, contradictory facts. **Positive-negative pair proving
Phase A is not Phase B**: a roster naming a check that is NOT registered
**parses successfully**. Backward-compat: grep-test asserts no production
module imports the schema yet.

**Acceptance criteria.**
- [ ] A roster referencing an unregistered external check id **parses**, and
      a test asserts it (this is the operator's item 2 made executable).
- [ ] Every Phase-A invalid class raises at construction naming the offender.
- [ ] Unreachability grep-test green and mutation-proven.
- [ ] The ownership table is recorded in this document before C5 uses it.

**Failure and edge cases.** A task declaring health but no roster = legal
absence; a roster naming an unregistered check = legal at Phase A, fatal at
Phase B — asserted as DIFFERENT outcomes.

**Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ -q > /tmp/08b_c1.log 2>&1`
      Evidence: _(pending)_

**Commit boundary.** Schema + tests only; no wiring; no empty modules.

---

### 4.2 C2 — run-scoped plugin loading, registration, and lifecycle

**Goal.** External code registers health providers and checks from
config-named files at run scope, and "run-scoped" is enforced rather than
asserted.

**Scope.** New `_plugin_binding.py` (file load, registration, the run-scoped
ledger of §3.5); public registration surface; `__init__.py` exports. Must
not change the built-ins' bootstrap or `registry.get` semantics. Depends on
C1.

**Implementation plan.**
- [ ] Re-read both existing loaders at the head and record the exact idiom
      being instantiated, so health's instance is demonstrably the same
      shape.
- [ ] Implement load → register with the idiom's failure split: scan
      fail-OPEN per file, name resolution fail-CLOSED.
- [ ] Implement the run-scoped ledger: idempotent identical re-load; a
      different resolved set in the same process fails closed naming both.
- [ ] Env var, if any, is framework-GENERATED subprocess transport for the
      already-resolved set (Q-08b-1) — never a user-facing parallel input.

**Validation plan.** Unit (integration-style, `tmp_path` package outside the
repo): a plugin registers a provider and a custom check. Negative: missing
file; unparseable file; registers nothing; name colliding with a built-in.
**Two-run counterfactual**: load set A, then attempt set B in the same
process → fail closed; re-load A → idempotent. Backward-compat: with no task
plugins declared, `all_registered()` is exactly the built-ins.

**Acceptance criteria.**
- [ ] An out-of-tree file registers a check that `registry.get` resolves.
- [ ] The two-run counterfactual is RED without the ledger and green with
      it (mutation-proven).
- [ ] No external registration path requires editing
      `execute_tools/health_checks/__init__.py` — census test.

**Failure and edge cases.** Registration leaking across tests (use
`clean_registry`); a plugin raising at import (fail-open per the idiom, but
its declared ids then fail closed at Phase B); duplicate registration.

**Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ -q > /tmp/08b_c2.log 2>&1`
      Evidence: _(pending)_

**Commit boundary.** Loading + registration + lifecycle only; no resolution
policy, no composition.

---

### 4.3 C3 — provider protocol, binding resolution, payload transport

**Goal.** The provider→payload→check path exists end to end, binding
resolution fails closed, and 08a's pre-I/O applicability invariant survives.

**Scope.** Provider protocol (§3.3); `HealthCheckSkill.run(..., *,
view=None)`; `evaluate_gate` gains the materialization step (§3.4);
Phase-B resolution (§3.1) with fail-closed errors (§3.2). Must not change
check order, short-circuit, action selection or the exception guard.
Depends on C1, C2.

**Implementation plan.**
- [ ] Re-read `runner.evaluate_gate`, `HealthCheckSkill` and
      `HealthCheckContext` at the head; record the exact insertion point.
- [ ] Define `HealthViewProvider` (`provider_id`, `capabilities`,
      `materialize`) and the `HealthView` envelope.
- [ ] Wire materialization strictly AFTER applicability.
- [ ] Implement Phase-B resolution: unresolved check/provider/capability →
      deterministic startup error naming the reference and what IS
      registered.
- [ ] Invert C1's unreachability guard into "resolution happens through the
      public API only".

**Validation plan.** Unit: an external custom check consumes an external
provider's opaque payload and returns a `HealthCheckResult`. **Ordering
test**: an INAPPLICABLE declaring check causes zero `materialize` calls AND
zero `h5py.File` opens (the 08a spy shape). Negative: capability not
advertised → startup ERROR, explicitly asserted **not** `INAPPLICABLE`;
provider raises during materialize → `CheckVerdict.ERROR`. Backward-compat:
all seven built-ins, which pass no `view`, behave byte-identically — C1
manifest replayed.

**Acceptance criteria.**
- [ ] Capability-missing raises at startup and the test asserts the verdict
      vocabulary is NOT involved (item 3 made executable).
- [ ] The inapplicable-check-no-materialize test is RED if the
      materialization step is moved before applicability (mutation-proven).
- [ ] 08a's 27-case manifest byte-identical.

**Failure and edge cases.** A provider advertising a capability it cannot
materialize → ERROR at materialize, not at startup (advertisement is a
claim; failure to honour it is a runtime error). A check declaring
`consumes_view` with no provider bound → Phase-B startup error.

**Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ -q > /tmp/08b_c3.log 2>&1`
      Evidence: _(pending)_

**Commit boundary.** Protocol + resolution + transport; no TIDMAD migration.

---

### 4.4 C4 — deterministic composition, plugin pinning, binding path

**Goal.** Framework policy and task config compose deterministically into
the SAME pinned artifact, the resolved plugin identity is part of the pinned
run identity, and a run can actually select its task health config.

**Scope.** New `_composition.py`; `materialize_effective_config` gains the
task-config binding; `core/run_invariants.py` and `core/resume.py` threading;
the §3.10 binding path. Must not change the sha MECHANISM, resume
immutability semantics, atomic write, or the artifact basename.
Depends on C1–C3.

**Implementation plan.**
- [ ] Confirm the caller census at the head (§2.4: one materialize caller,
      four `build_run_invariants` callers, one resume mirror).
- [ ] Compose deterministically (stable key order) from disposition →
      policy (§3.7).
- [ ] Fold `resolved_plugins` with per-file `sha256` into the **hashed
      body** (§3.6), not the header.
- [ ] Implement the explicit / legacy-Regime-A binding path (§3.10) with no
      task-name branching.
- [ ] Keep `core/resume.py:354`'s mirrored computation in step.

**Validation plan.** Determinism across repeated runs and shuffled input
ordering. Default parity: with no task config supplied, the artifact is
byte-identical to pre-08b — captured BEFORE this commit as a frozen sha.
**Plugin-pinning negative test**: same config, same path, mutated plugin
bytes → resume fails closed. Compatibility: `scripts/v18_wave_summary.py`'s
reader still works against the composed artifact.

**Acceptance criteria.**
- [ ] The pinned sha describes the file the run reads — asserted by
      re-reading and re-hashing the written artifact, not by trusting the
      return value.
- [ ] Mutated-plugin resume raises, naming `health_config_sha256`.
- [ ] Composition is order-independent and repeatable.
- [ ] No second composition path exists — census test.

**Failure and edge cases.** A task config composing to a roster with an
unresolved reference → fails at startup (Phase B), not at round 1. Directory
plugin refs resolve deterministically and pin the actual loaded file set.

**Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ tests/unit/core/ -q > /tmp/08b_c4.log 2>&1`
      Evidence: _(pending)_

**Commit boundary.** Composition + pinning + binding path; TIDMAD values
still in the framework file.

---

### 4.5 C5 — TIDMAD ownership migration (the parity commit)

**Goal.** TIDMAD's roster, thresholds, dispositions, peek files, `reason`
prose **and the numerical value scale** move into the TIDMAD task-owned
config; the framework YAML keeps policy only.

**Scope.** `configs/health_checks.yaml` and the observe-mode variant slimmed
to policy; new TIDMAD task health config; `_MV_PER_LSB` removed from **four**
check modules (§2.7); `value_scale_unit` then declared by the checks that
need it; `TASK_HEALTH_PEEK` disposition applied (§3.8). Must not change any
threshold VALUE, gate id, check id, action, severity, firing point or
verdict. Depends on C1–C4.

**Implementation plan.**
- [ ] Capture-first: freeze the six checks' verdicts and the composed
      artifact BEFORE migrating, reusing 08a's manifest generator.
- [ ] Move values with provenance comments intact.
- [ ] **Atomically**: the numerical scale, its task-owned declaration, and
      the checks' `value_scale_unit` requirement move in ONE commit.
- [ ] Apply the `TASK_HEALTH_PEEK` disposition after re-confirming its
      consumer census.
- [ ] Census: framework YAML contains no task identity, threshold, roster,
      peek set or science prose.

**Validation plan.** 08a's 27-case manifest byte-identical. Default parity on
the **executed sequence**: same gates selected, same executed check order,
same actions, field-by-field persisted equality against a pre-C5 dump.
Negative: a framework YAML carrying a task threshold is REFUSED.

**Acceptance criteria.**
- [ ] 27/27 manifest cases byte-identical.
- [ ] Persisted `PersistedHealthGateResult` fields byte-equal on
      TIDMAD-shaped fixtures; the six gate ids unchanged.
- [ ] `value_scale_unit` is DECLARED by the checks that need it AND
      SUPPLIED by the task facts — both directions asserted.
- [ ] Exactly ONE numerical scale value exists in the task config; zero
      `_MV_PER_LSB` literals remain in the health package.
- [ ] TIDMAD runs with its science out of framework YAML and **no
      task-name branch anywhere** — census test.

**Failure and edge cases.** A threshold silently changing (manifest catches
it); the effective sha moving (EXPECTED per Q-08b-2 — record the exact
delta, rely on the fresh-workspace boundary, assert the refusal); a check
declaring the scale axis before facts supply it (the reason both move
together).

**Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ -q > /tmp/08b_c5.log 2>&1`
      Evidence: _(pending)_

**Commit boundary.** Ownership move only; no new mechanism.

---

### 4.6 C6 — D18: scalar-only metrics as a typed statement

**Goal.** A scalar-only metric's absence of per-sample evidence reaches
Health as a TYPED statement, and per-file checks report `inapplicable`
rather than a hollow pass.

**Scope.** Replace the `list(metric_result.per_sample or [])` collapse
(`execution.py:894-897`) with a typed carrier; per-file checks declare the
corresponding requirement. **Health consumes capability metadata only — never
the golden scalar** (parent §5, census-refused). Metric arithmetic ownership
stays in Step 06. Depends on C1–C5.

**Implementation plan.**
- [ ] Re-confirm §2.6 at the head: `MetricResult.per_sample is None` is the
      producer-side statement; the bridge destroys it.
- [ ] Carry the statement into `HealthCheckContext` as a typed value
      distinguishing "no per-sample evidence exists for this task" from
      "per-sample evidence exists and is empty".
- [ ] Per-file checks declare the requirement so the engine yields
      `INAPPLICABLE` with the axis named.

**Validation plan.** Unit: scalar-only task → per-file checks
`INAPPLICABLE`, axis named; per-file-capable task → applicable. **Negative
control**: TIDMAD unchanged (per_sample present) — manifest replayed.
Census: no check reads `denoising_score` or the metric scalar.

**Acceptance criteria.**
- [ ] The statement is TYPED — an absent/empty field is never the signal.
- [ ] Under a scalar-only metric, per-file checks report `inapplicable`,
      NOT `passed`.
- [ ] TIDMAD per-file behaviour byte-identical.

**Failure and edge cases.** A task declaring nothing about per-sample
capability: absence ≠ scalar-only, must not be inferred.

**Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ tests/unit/agent/ -q > /tmp/08b_c6.log 2>&1`
      Evidence: _(pending)_

**Commit boundary.** D18 only. **This is the last production-code commit —
the Gate-2 head (§7).**

---

### 4.7 C7 — out-of-tree extension proof, census, docs

**Goal.** Make the completion criterion executable, with the claim stated
correctly (ruling item 15).

**Scope.** New integration-style unit test building a `tmp_path` external
package; census guardrails; docs. **No production behaviour change.**
Depends on C1–C6.

**The claim, corrected.** 08b necessarily edits `execute_tools/` to CREATE
the seam, so "zero diffs to `execute_tools/`" is the wrong assertion. The
real claim is:

> **After the generic seam exists, adding the synthetic external fourth task
> requires ZERO ADDITIONAL infrastructure-source registration, config or
> import edits.**

**Implementation plan.**
- [ ] Build the fixture package entirely under `tmp_path`: task health
      config + provider plugin + custom check declaring a plugin-local
      capability.
- [ ] Assert the full chain: config → loader → registration → resolution →
      provider → custom check → `HealthCheckResult`.
- [ ] Assert the fixture's ids/names appear **nowhere in production source**
      (grep census), and that the loader receives only external config/paths.
- [ ] Negative control: remove/break the plugin → deterministic fail-closed
      resolution; restore → flow succeeds.
- [ ] Census: zero task-name branches; no central task registry; no closed
      view-kind enum; no framework-YAML task identity; no registration path
      requiring a central import edit.
- [ ] Docs sync last, quoting each documented behaviour against merged
      source.

**Acceptance criteria.**
- [ ] The proof passes without any fixture-specific entry in a registry,
      import list or shipped YAML — asserted by the id-absence census, **not**
      by checking `git diff`.
- [ ] Remove-plugin → fail closed; restore → succeed (both directions).

**Failure and edge cases.** The proof passing because the fixture
accidentally imported an in-repo module — assert its provider/check come
only from its own files.

**Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ -q > /tmp/08b_c7.log 2>&1`
      Evidence: _(pending)_

**Commit boundary.** Proof + census + docs; no production change; **no Gate**.

## 5. Test disposition

`test_config_loader.py` and `test_step00_health_config_baseline.py` pin the
framework YAML that C5 slims. Their disposition is **UPGRADE with an
argued claim**, not "update the expected values": the baseline test must
assert the new POLICY-ONLY shape and, separately, that the migrated task
config carries the same threshold VALUES as before. A baseline test silently
re-pointed at new values proves nothing. All 08a families KEEP.

## 6. Evidence economy

Targeted per-commit tests plus the health package per commit. No local full
suite; no manual dispatch; one canonical full CI on the final head.

## 7. Gates

* **Gate 1 — NOT REQUIRED.** No prompt/PB delta; the 08a byte-pin
  discipline applies unchanged. Any accidental delta re-dispositions it.
* **Gate 2 — ONE bounded TIDMAD run at the final executable head
  (after C6)**, per ruling item 16. C4 and C5 are the same lifecycle failure
  class and the later head subsumes the earlier; C7 is tests/docs and needs
  no Gate. It must prove: startup composition; the pinned task-owned TIDMAD
  config; plugin/binding lifecycle if exercised; six gates fire; the TIDMAD
  executed sequence preserved; verdicts and persisted values semantically
  correct; **no unintended inapplicability**. Spec written into §10 before
  launch. Retry only for a genuine INCONCLUSIVE run or an independent
  failure class.
* **The out-of-tree proof is NOT a Gate** — UNIT, no training.

## 8. Risks

* **R-08b-1 — C5 is the highest-risk diff in Step 08.** It moves real
  thresholds and a real physical constant. Capture-first parity is
  mandatory; the numerical scale and its declaration move atomically.
* **R-08b-2 — provider protocol over-reach.** 08b must ship the opaque
  transport only; any standard payload contract belongs to 08c.
* **R-08b-3 — the legacy binding path becoming the extension mechanism.**
  Bounded by §3.10 and the C7 census.
* **R-08b-4 — plugin pinning cost.** Digesting every resolved plugin file at
  startup is cheap for file-based plugins; if a directory ref ever resolves
  to a large tree this needs revisiting.

## 9. Adversarial self-review (the operator's A–H)

**A. Can a new external plugin ID be parsed before it exists in the
registry?** **Yes.** §3.1 Phase A validates structure only and explicitly
accepts unknown check/provider/capability ids; C1 asserts a roster naming an
unregistered check *parses*. Resolution is Phase B, after loading.

**B. Can a malformed/unresolved binding ever become INAPPLICABLE?** **No.**
§3.2 makes unresolvable binding a deterministic startup ERROR, and C3
asserts the capability-missing case raises at startup with the verdict
vocabulary explicitly not involved. `INAPPLICABLE` is reserved for a validly
bound check whose facts/context make it non-applicable.

**C. Can an inapplicable check cause provider artifact I/O?** **No.** §3.3
splits the provider into advertisement (metadata, no I/O) and materialization
(I/O), and §3.4 places materialization strictly after applicability. C3's
test fails if `materialize` is called or a file opened for an inapplicable
check, and is mutation-proven by moving the step earlier.

**D. Can Run B see Run A's plugin registration?** **Not silently.** §2.8
shows production hosts one run per process, but §3.5 does not rely on that:
a second, different resolved plugin set in the same process fails closed,
with a two-run counterfactual test that is RED without the ledger.

**E. Can `plugin.py` change in place without changing the pinned run
identity?** **No.** §3.6 folds each resolved plugin's `sha256` into the
hashed effective-config body, which is the already-canonical
`health_config_sha256`; a mutated plugin therefore changes the pin and
resume fails closed. C4 asserts it.

**F. Can task disposition contradict framework action/role?** **No.** §3.7
gives each field exactly one owner: the task selects a disposition KEY and
cannot set `gate_role`/`action`/`severity` at all, so there is no second
copy to contradict.

**G. Can TIDMAD run after its science leaves framework YAML, without a
task-name branch?** **Yes.** §3.10's legacy path is selected by ABSENCE of
an explicit binding, never by name, and C5's census asserts zero task-name
branches.

**H. Does the external fourth-task proof require any fixture-specific infra
registration after the seam exists?** **No** — and C7 asserts it by the
fixture's ids being absent from production source plus the remove/restore
negative control, rather than by inspecting `git diff`.

## 10. Ledger

*(filled per commit during implementation)*
