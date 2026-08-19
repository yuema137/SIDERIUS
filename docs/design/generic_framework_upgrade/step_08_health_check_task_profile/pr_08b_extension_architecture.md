# PR 08b — extension architecture: task-owned config + plugin binding + TIDMAD family + D18 (child design)

## 0. Status and provenance

**REVISION 3 — FROZEN. Operator ruling 2026-08-19.**

**Implementation state: COMPLETE / MERGED 2026-08-18.** PR **#236**, squash
**`13e28796f1dcf7f61b3bce0b3e0b7559978b6721`**; final PR head `65a3c7d9`,
final EXECUTABLE head `bf6e9e19`; exact-head CI **32217121228 SUCCESS** on
`65a3c7d9` (job "Lint + Type + Unit Tests" — also the pyright evidence).
Landed master verified byte-identical to the reviewed head. Seven commits
C1–C7 (§10), Gate 2 PASS, Gate 1 NOT REQUIRED, plus the operator-directed
cross-task audit (§11). The SEMANTIC design below was frozen and is
unchanged; §4's checkboxes and §10's ledger are the implementation record.

Rev 1 was drafted at the PRE-MERGE 08a head `7ae72ae5` and carried six
`SOURCE-INSPECTION REQUIRED` markers. The operator's first review ruling
returned it **APPROVED IN DIRECTION / NOT READY TO FREEZE** with eighteen
load-bearing items; rev 2 answered all eighteen. The operator's second
ruling returned **APPROVE WITH MINOR FREEZE AMENDMENTS** — four narrow
amendments, no redesign, C1–C7 not reopened. Rev 3 applies them and freezes.

### 0.0 The four final amendments (operator ruling, 2026-08-19)

1. **The public view-transport signature is APPROVED**, and backward
   compatibility is frozen as a DISPATCH rule, not merely a default value:
   a check that does not declare `consumes_view` is invoked as
   `run(ctx, config)` with no gratuitous `view=None` (§3.3). A mechanical
   `*, view=None` on the built-ins for Protocol conformance is an allowed
   behaviour-preserving C3 adaptation.
2. **Plugin load failure semantics refined** — an EXPLICITLY named plugin
   file that is missing/unreadable/unparseable/raising fails closed at
   startup; a configured DIRECTORY keeps the idiom's per-member fail-open
   scan; either way an unresolved declared binding fails closed in Phase B.
   **Scan tolerance ≠ declared-binding tolerance** (§3.2).
3. **Plugin identity is canonical, not host-specific** — the hashed body
   carries `configured_ref` + relative member + `content_sha256`; absolute
   filesystem paths are diagnostics-only header content, so two identical
   task packages at different absolute paths share one semantic identity
   (§3.6).
4. **Legacy omission ≠ explicit no-binding** — three semantic states, with
   explicit no-binding never falling back to TIDMAD, and an explicit C4/C5
   sequencing split that reconciles C4's byte-parity criterion with §3.10
   (§3.10).

Additionally: the run-scoped ledger is recorded as an 08b-INTERNAL
enforcement mechanism, not the permanent public task-package ABI (§3.5).

### 0.0a Freeze state

* Audit anchor re-verified at freeze time: `origin/master` had **not**
  advanced beyond `a226495b`, so no audited surface changed and no re-audit
  was required.
* All four Q-08b questions **RESOLVED** (§0.1).
* **Zero** `SOURCE-INSPECTION REQUIRED` markers remain.
* Every implementation checkbox was `[ ]` at freeze time. They are ticked
  during implementation with recorded evidence; see §10 for the live ledger.

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
| task config names a plugin FILE that is missing / unreadable / unparseable / raises at import | **deterministic startup ERROR** — the user asked for THAT file; silently skipping it is not valid |
| a MEMBER of a configured plugin DIRECTORY is unloadable | per-member fail-open warning (the existing loader idiom), **but** any declared binding that then fails to resolve is a Phase-B fail-closed error |
| declared check/provider id not registered after loading | **deterministic startup ERROR** |
| task declares no health binding at all | regime-legal absence — UNKNOWN-style evidence-absence, NAMED, never a synthesized pass |
| binding VALID, but task facts / round context make the check semantically non-applicable | `CheckVerdict.INAPPLICABLE` (08a semantics, unchanged) |
| provider raises while materializing an applicable view | `CheckVerdict.ERROR` — fail closed, never inapplicable |

**A configuration error is never downgraded to a Health verdict.**

**Scan tolerance ≠ declared-binding tolerance** (operator amendment). The
existing loader idiom is fail-open per scanned file; config is now the
semantic authority, so an EXPLICITLY named file is not a scan candidate —
its failure is fatal. Directory scanning keeps the tolerant idiom, because
an unrelated member is not something the task asked for. Either way, a
check/provider/capability the task config REQUIRES that does not resolve
after loading fails closed in Phase B. Every such error names the configured
ref wherever the source permits.

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
* **Transport to the check — APPROVED (operator ruling 2026-08-19)**:

  ```python
  HealthCheckSkill.run(ctx, config, *, view=None)
  ```

  This is RESOLVED, not an open risk. **Backward compatibility is a
  dispatch rule, not merely a default value:**

  ```text
  check does NOT declare consumes_view
      -> runner calls the LEGACY shape   run(ctx, config)
         and does NOT gratuitously pass view=None

  check DOES declare consumes_view
      -> runner calls                    run(ctx, config, view=resolved_view)
  ```

  So a pre-08b or externally supplied check that never heard of `view` is
  invoked exactly as before, at runtime, not merely by relying on a
  default. If structural typing requires the seven built-in `run()`
  implementations to gain a mechanical `*, view=None` parameter for
  Protocol conformance, that is an ALLOWED C3 behaviour-preserving
  adaptation — it is not a semantic redesign and must not change their
  runtime behaviour.
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

**Status of the ledger (operator amendment).** It is an **08b-internal
enforcement mechanism for the current one-run-per-process lifecycle**, not
the permanent public task-package ABI. Step 10/12 may subsume or replace the
enforcement when the unified composition root lands, provided the semantic
requirement survives: one run must never silently inherit another run's
plugin set.

### 3.6 External plugin identity is part of the pinned run identity

The hashed effective-config body — and therefore the canonical
`health_config_sha256` (§2.4) — **must include the resolved plugin set and
each file's content digest**:

```yaml
resolved_plugins:
  - configured_ref: ./plugins/health.py      # normalized logical ref
    member: ""                                # relative member path; "" for a file ref
    content_sha256: "abc…"
```

**Absolute filesystem paths are deliberately NOT part of the hashed
identity** (operator amendment). Two scientifically identical task packages
checked out at different absolute paths must produce the SAME semantic
plugin identity. The canonical identity is therefore
`configured_ref` + `relative member path` + `content_sha256`; resolved
absolute paths MAY appear in the unhashed header for diagnostics only.

* a configured DIRECTORY contributes its normalized configured ref plus
  deterministically sorted RELATIVE member paths, each with the digest of
  the member actually loaded;
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
narrow, bounded seam. **Three semantic states, never two** (operator
amendment — "argument omitted" and "explicitly no binding" must not collapse
into one state):

```text
A. LEGACY ARGUMENT OMITTED
     the pre-08b production compatibility path.
     May use the frozen Regime-A TIDMAD fallback.
     NOT the extension mechanism.

B. EXPLICIT NO-HEALTH / NO-BINDING
     the caller states that no task Health binding exists.
     -> legal NAMED absence / UNKNOWN-style evidence absence (§3.2).
     MUST NEVER synthesize or fall back to TIDMAD.

C. EXPLICIT TASK-HEALTH-CONFIG BINDING
     load and resolve the named external/task-owned config.
```

A and B are distinguished by a typed sentinel / default-state (or another
source-grounded representation), **never by a task-name branch**. Collapsing
them would mean a task that deliberately declares "no health" silently
inherits TIDMAD's family — the exact synthesized-evidence failure the parent
§6a.5 forbids.

**C4/C5 sequencing (operator amendment — this is what makes C4's byte-parity
criterion and this section mutually consistent):**

```text
C4  introduces the GENERIC explicit binding + composition mechanism.
    For state A (legacy omitted) behaviour remains PRE-08b, and the
    no-task-config artifact stays byte-identical to the captured baseline.
    C4 does NOT yet require state A to consume a task-owned TIDMAD config.

C5  atomically: lands the TIDMAD task-owned Health config; slims the
    framework YAML to policy only; migrates thresholds / roster / prose /
    peek ownership / numerical scale; AND redirects state A to that
    task-owned TIDMAD config.
```

Without that split, C4 would have to both preserve byte-identical output and
already route TIDMAD through a config that does not exist until C5 — a
contradiction. **C5 cannot move TIDMAD's science out of the framework YAML
until this path exists**, which is why the two commits are ordered this way
and not merged.

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
- [x] Re-measure `config.py` at the head and decide whether it has become
      mixed-responsibility. **If not, do not split it**; place new
      responsibilities in new modules and say so here.
      → **514 lines; NOT split.** Its four parts (rev-6 gate schema, cached
      loader, DataScope monitored-file override + scope validation,
      effective-config materialization/pinning) are consecutive stages of ONE
      pipeline — load → override → validate → materialize — not unrelated
      concerns. C1 adds nothing to it: the new schema lands in a NEW module.
      Splitting it would refactor the exact file C4/C5 must touch for
      composition, making their parity diffs harder to review, not easier.
- [x] Produce the exact ownership/migration table from the CURRENT
      `configs/health_checks.yaml`, gate by gate, against §2.3.
      → §10 C1 ledger, "Ownership / migration table". §2.3 re-verified
      verbatim at the implementation head: **exact match, no drift.**
- [x] Define the schema with **authoring validation only** (§3.1 Phase A);
      reuse 08a's `TaskHealthFacts` rather than a second facts vocabulary.
      → `_task_health_config.py` (302 lines): `TaskHealthConfig` embeds 08a's
      `TaskHealthFacts` directly; `HealthDisposition`, `ValueScale`,
      `HealthPluginRef`, `HealthProviderBinding`, `HealthRosterEntry`,
      `FRAMEWORK_OWNED_PARAMETER_KEYS`.
- [x] Define the value-scale declaration (§3.9) as one typed family-level
      value.
      → `ValueScale(unit, units_per_sample)`, family-level and optional.
      `facts.value_scale_unit` is REFUSED as an independent input and filled
      by `resolved_facts()` from `value_scale.unit`, so the axis and the
      number cannot drift apart.

**Validation plan.** Unit: a TIDMAD-shaped document parses; parsed values
equal hardcoded expectations (never read back from the parser). Negative:
empty id, malformed plugin ref, duplicate roster entry, invalid disposition
name, unknown field, contradictory facts. **Positive-negative pair proving
Phase A is not Phase B**: a roster naming a check that is NOT registered
**parses successfully**. Backward-compat: grep-test asserts no production
module imports the schema yet.

**Acceptance criteria.**
- [x] A roster referencing an unregistered external check id **parses**, and
      a test asserts it (this is the operator's item 2 made executable).
      → `TestPhaseAIsNotPhaseB` — three cases, and the check-id case also
      asserts the id is genuinely absent from `registry.all_registered()`, so
      the test cannot pass by naming something that happens to exist.
- [x] Every Phase-A invalid class raises at construction naming the offender.
      → `TestPhaseARejectsIncoherentDocuments`, 19 parametrized classes, each
      asserting a message fragment rather than merely that it raised.
- [x] Unreachability grep-test green and mutation-proven.
      → Mutation: a real `from …_task_health_config import TaskHealthConfig`
      appended to production `runner.py` → guard **RED** naming
      `runner.py:206`. Restored byte-identical (`git diff --quiet` clean),
      caches cleared, baseline re-run **483 passed**.
- [x] The ownership table is recorded in this document before C5 uses it.
      → §10 C1 ledger below.

**Failure and edge cases.** A task declaring health but no roster = legal
absence; a roster naming an unregistered check = legal at Phase A, fatal at
Phase B — asserted as DIFFERENT outcomes.

**Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ -q > /tmp/08b_c1.log 2>&1`
      Evidence: **483 passed, rc=0, 2.02 s** (440 pre-existing + 43 new).
      Verdict read from the complete log file, not a pipe's exit status.
- [x] 08a's 27-case verdict-parity manifest `--check`: *"OK — 27 cases
      reproduce the committed manifest byte-identically."*
- [x] `ruff check` clean; `ruff format --check` clean across
      `execute_tools/health_checks/` and its test package (51 files).
- [x] `pyright` — **CI-owned**, satisfied by exact-head CI 32217121228 (job
      "Lint + Type + Unit Tests", SUCCESS on `65a3c7d9`). Not runnable locally (Node `v10.19.0` too old for the
      vendored bundle, per 08a's ledger). CI-owned; not claimed as a local
      pass.

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
- [x] Re-read both existing loaders at the head and record the exact idiom
      being instantiated, so health's instance is demonstrably the same
      shape.
      → Recorded in the module docstring and in §10 C2 below: same
      `spec_from_file_location` → `sys.modules` before exec → rollback on
      failure → `sorted(os.listdir)` skipping non-`.py` and `_`-prefixed.
- [x] Implement load → register with the AMENDED failure split (§3.2).
      → `_plugin_binding.load_task_health_plugins`. Explicit FILE missing /
      unreadable / unparseable / raising → `HealthPluginError` naming the
      configured ref; configured DIRECTORY keeps per-member `RuntimeWarning`
      tolerance. A missing DIRECTORY is fail-closed — see the decision below.
- [x] Implement the run-scoped ledger: idempotent identical re-load; a
      different resolved set in the same process fails closed naming both.
      → `_RunScope` + `_RUN_SCOPE`, compared on CANONICAL identity so a
      relocated checkout is correctly the same set.
- [x] Env var, if any, is framework-GENERATED subprocess transport for the
      already-resolved set (Q-08b-1) — never a user-facing parallel input.
      → **No Health env var exists, and none is needed.** Source-grounded:
      `SIDERIUS_PLUGIN_DIRS`/`SIDERIUS_LOSS_DIRS` exist as SUBPROCESS
      transport (`core/subprocess_env.py`), and no sandbox subprocess imports
      the health package — `execute_tools/{denoising_score_single,
      inference_single}.py` were grepped and import it nowhere. Health runs
      only in the run process, so an env var would be pure speculative
      machinery and the exact ambient parallel input Q-08b-1 forbids.

**Validation plan.** Unit (integration-style, `tmp_path` package outside the
repo): a plugin registers a provider and a custom check. Negative, and the
pair is the point: an **explicitly named** missing/unparseable/raising file
→ startup FAILS CLOSED; an unloadable **member of a configured directory**
→ warning only, yet a binding that then fails to resolve still fails closed
in Phase B. Also: registers nothing; name colliding with a built-in.
**Two-run counterfactual**: load set A, then attempt set B in the same
process → fail closed; re-load A → idempotent. Backward-compat: with no task
plugins declared, `all_registered()` is exactly the built-ins.

**Acceptance criteria.**
- [x] An out-of-tree file registers a check that `registry.get` resolves.
      → `TestAnOutOfTreeFileRegistersACheck`; the plugin is written under
      `tmp_path` OUTSIDE the repository and imports only the public surface.
- [x] Explicit-file failure and directory-member failure produce DIFFERENT
      outcomes, asserted as a pair (scan tolerance ≠ declared-binding
      tolerance).
      → `TestScanToleranceIsNotDeclaredBindingTolerance`: the SAME broken
      module raises `HealthPluginError` when named as a file and only warns
      when scanned as a directory member, with the surviving sibling still
      registered. Either half alone is satisfied by a uniformly strict or
      uniformly lax loader; the contrast is the evidence.
- [x] The two-run counterfactual is RED without the ledger and green with
      it (mutation-proven).
      → Mutation `if _RUN_SCOPE is not None:` → `if False:` (asserted exactly
      1 site): **5 failed / 14 passed**, including
      `test_a_different_plugin_set_in_the_same_process_fails_closed`.
      Restored, caches cleared, re-baselined green.
- [x] No external registration path requires editing
      `execute_tools/health_checks/__init__.py` — census test.
      → `test_the_fixture_check_name_appears_nowhere_in_the_central_import_list`;
      C7 generalises it.

**Failure and edge cases.** Registration leaking across tests (use
`clean_registry`); a plugin raising at import (fail-open per the idiom, but
its declared ids then fail closed at Phase B); duplicate registration.

**Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ -q > /tmp/08b_c2.log 2>&1`
      Evidence: **503 passed, rc=0, 2.03 s** (483 at C1 + 19 new + 1 new
      allowlist-vacuity guard). Verdict read from the complete log.
- [x] 08a's 27-case verdict-parity manifest `--check`: **byte-identical**.
- [x] `ruff check` + `ruff format --check` clean (53 files).
- [x] `pyright` — CI-owned; **SUCCESS** in exact-head CI 32217121228 on `65a3c7d9` (Node `v10.19.0` too old locally).

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
- [x] Re-read `runner.evaluate_gate`, `HealthCheckSkill` and
      `HealthCheckContext` at the head; record the exact insertion point.
      → Between the applicability `continue` and `skill.run`, INSIDE the
      existing PR #101 Bug-B guard, so a provider failure produces
      `CheckVerdict.ERROR` through exactly the path a raising check does and
      all failure bookkeeping (`first_failure_reason`, `short_circuit`,
      action selection) stays in one place.
- [x] Define `HealthViewProvider` (`provider_id`, `capabilities`,
      `materialize`) and the `HealthView` envelope.
      → NEW `_view_provider.py`; provider registry beside the check registry
      in `registry.py` (one registration surface, separate namespaces).
- [x] Wire materialization strictly AFTER applicability.
      → `runner.evaluate_gate`; mutation-proven below.
- [x] Implement Phase-B resolution: unresolved check/provider/capability →
      deterministic startup error naming the reference and what IS
      registered.
      → `_plugin_binding.resolve_task_health_bindings` + `HealthBindingError`.
      Resolution order is check ids → provider ids → capability exposure, so
      the error names the most specific cause rather than a symptom.
- [x] Invert C1's unreachability guard into "resolution happens through the
      public API only".
      → Done at **C2**, one commit earlier than planned, because
      `_plugin_binding` was the first legitimate consumer. See the C2 ledger.

**Validation plan.** Unit: an external custom check consumes an external
provider's opaque payload and returns a `HealthCheckResult`. **Ordering
test**: an INAPPLICABLE declaring check causes zero `materialize` calls AND
zero `h5py.File` opens (the 08a spy shape). Negative: capability not
advertised → startup ERROR, explicitly asserted **not** `INAPPLICABLE`;
provider raises during materialize → `CheckVerdict.ERROR`. Backward-compat:
all seven built-ins, which pass no `view`, behave byte-identically — C1
manifest replayed.

**Acceptance criteria.**
- [x] Capability-missing raises at startup and the test asserts the verdict
      vocabulary is NOT involved (item 3 made executable).
      → `TestUnresolvedBindingIsAnErrorNotAVerdict`. The evidence is a PAIR:
      the misconfigured cases raise `HealthBindingError` at resolution — no
      `HealthCheckResult` and no `CheckVerdict` is ever produced, and no
      partial binding state is left — while
      `test_a_valid_binding_whose_facts_do_not_match_is_INAPPLICABLE` runs
      the same machinery correctly bound and DOES yield the typed verdict.
- [x] The inapplicable-check-no-materialize test is RED if the
      materialization step is moved before applicability (mutation-proven).
      → Moving it above the applicability decision: **2 failed / 13 passed**,
      and the provider error additionally ESCAPED `evaluate_gate` uncaught —
      a second, worse consequence the correct ordering prevents. Restored,
      caches cleared, re-baselined green.
- [x] **All pre-08b checks execute through the unchanged no-view call
      path** — asserted by a spy on the invocation, not merely by their
      results being unchanged.
      → `TestNoViewMeansTheUnchangedCallPath`. The spy check's `run` has NO
      `view` parameter at all, so a gratuitous `view=None` would raise
      `TypeError` rather than being quietly absorbed.
- [x] **A view-consuming external check receives the keyword-only `view`.**
      → `test_a_view_consuming_check_receives_the_keyword_only_view`, which
      also asserts the payload, `provider_id` and `capability_key` arrive
      intact.
- [x] Pyright (CI) verifies the public Protocol relationship — **SUCCESS** in exact-head CI 32217121228; the seven
      built-ins took the mechanical `*, view=None` (an allowed C3
      adaptation), their runtime behaviour is unchanged, and the manifest
      proves it. **Pyright itself is CI-owned** — not runnable locally.
- [x] 08a's 27-case manifest byte-identical.

**Failure and edge cases.** A provider advertising a capability it cannot
materialize → ERROR at materialize, not at startup (advertisement is a
claim; failure to honour it is a runtime error). A check declaring
`consumes_view` with no provider bound → Phase-B startup error.

**Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ -q > /tmp/08b_c3.log 2>&1`
      Evidence: **518 passed, rc=0, 2.04 s** (503 at C2 + 15 new).
- [x] 08a's 27-case verdict-parity manifest `--check`: **byte-identical** —
      the seven built-ins' mechanical `*, view=None` changed no behaviour.
- [x] Blast-radius census: `grep` for `HealthCheckSkill`, `skill.run(` and
      the check `run` signature outside the health package returns **zero**
      hits, so the Protocol change has no out-of-package implementers.
      Import-sanity confirmed for the tuner node, `core.run_invariants` and
      `workflows.model_exploration`.
- [x] `ruff check` + `ruff format --check` clean (645 files formatted).
- [x] `pyright` — CI-owned; **SUCCESS** in exact-head CI 32217121228 on `65a3c7d9`.

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
- [x] Confirm the caller census at the head (§2.4: one materialize caller,
      four `build_run_invariants` callers, one resume mirror).
      → Confirmed unchanged. The new parameter is keyword-with-default, so
      all four `build_run_invariants` callers and the single materialize
      caller are untouched.
- [x] Compose deterministically (stable key order) from disposition →
      policy (§3.7).
      → `_composition.py`: `_DISPOSITION_POLICY` + `_DISPOSITION_CHECK_POLICY`
      reproduce the six shipped gates' two shapes exactly, including
      `aggregation: any_pass` on blocking gates only.
- [x] Fold `resolved_plugins` into the **hashed body** (§3.6) using the
      CANONICAL identity — `configured_ref` + relative member +
      `content_sha256`. **No absolute filesystem path in the hashed body**;
      resolved absolute paths go in the unhashed header only.
      → `body_markers`; asserted by a test that greps the whole body for the
      `tmp_path` prefix, and mutation-proven.
- [x] Implement the THREE binding states (§3.10) with a typed sentinel and
      no task-name branching. **State A keeps PRE-08b behaviour in C4** —
      redirecting it to the task-owned TIDMAD config is C5's job.
      → `HealthBindingState.LEGACY_OMITTED` (the parameter DEFAULT) /
      `EXPLICIT_NONE` / a path for state C. No task name appears in
      `_composition.py` at all.
- [x] Keep `core/resume.py:354`'s mirrored computation in step.
      → **The mirror was REMOVED, not synchronised** — see the deviation
      below. `read_effective_config_body_sha` is now the one implementation
      and `resume` delegates to it.

**Validation plan.** Determinism across repeated runs and shuffled input
ordering. Default parity: with no task config supplied, the artifact is
byte-identical to pre-08b — captured BEFORE this commit as a frozen sha.
**Plugin-pinning negative test**: same configured ref, mutated plugin bytes
→ different `health_config_sha256` → resume fails closed. **Path-independence
test**: the same package resolved from two different absolute directories
produces the SAME plugin identity and the same body sha. **Three-way binding
test**: legacy-omitted vs explicit-no-binding vs explicit-external-binding
produce three distinct intended behaviours — and explicit-no-binding NEVER
falls back to TIDMAD. Compatibility: `scripts/v18_wave_summary.py`'s reader
still works against the composed artifact.

**Acceptance criteria.**
- [x] The pinned sha describes the file the run reads — asserted by
      re-reading and re-hashing the written artifact, not by trusting the
      return value.
      → `test_the_pinned_sha_describes_the_file_the_run_reads`.
- [x] Mutated-plugin resume raises, naming `health_config_sha256`.
      → Two linked tests, because the chain has two hops: the workspace
      refuses the changed body (`test_mutated_plugin_bytes_change_the_pin_
      and_fail_a_resume_closed`), and the same sha is the field the run
      lock pins and names on drift
      (`test_the_changed_digest_reaches_the_run_identity_by_its_own_name`,
      which also asserts `health_config_sha256 ∈ RunInvariants._CANONICAL`).
- [x] Two checkouts at different absolute paths yield an identical pinned
      identity (host paths are not load-bearing).
      → `test_the_same_package_at_two_absolute_paths_pins_one_identity`,
      which deliberately does NOT reset the run scope — the ledger must
      recognise the relocated package as the same set.
- [x] The three binding states are distinct, and explicit-no-binding yields
      named absence rather than a TIDMAD fallback.
      → Three distinct shas; and `test_explicit_none_never_falls_back_to_a_
      shipped_family` runs against the REAL shipped config, which still
      carries TIDMAD's six gates at C4.
- [x] With no task config supplied (state A), the artifact is byte-identical
      to the captured pre-08b baseline.
      → **`c933bceeb04a06df4c3e06ecbbe3ae4aa9eb5594ecf17e0d9b511e571784855d`**,
      captured at the C3 head BEFORE composition existed and frozen as a
      literal in the test. Re-deriving it would compare the implementation to
      itself. A second test asserts the default body's key set is exactly
      `{health_gates}` — not even an empty `resolved_plugins`.
- [x] Composition is order-independent and repeatable.
      → Repeated materialization byte-identical; author-side parameter key
      order irrelevant; **roster ORDER deliberately preserved**, because the
      executed sequence is the parity criterion.
- [x] No second composition path exists — census test.
      → The seam allowlist in `test_task_health_config.py` grew by exactly
      two entries (`_composition.py`, `config.py`) and its companion asserts
      the allowlist EQUALS the actual consumer set.

**Failure and edge cases.** A task config composing to a roster with an
unresolved reference → fails at startup (Phase B), not at round 1. Directory
plugin refs resolve deterministically and pin the actual loaded file set.

**Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ -q > /tmp/08b_c4.log 2>&1`
      Evidence: **539 passed, rc=0** (518 at C3 + 21 new).
- [x] `tests/unit/core/` (2 950 tests with the health package): **rc=0** after
      the two allowlist entries and one fixture fix; `test_resume.py`,
      `test_resume_incumbent.py`, `test_run_invariants.py` re-run
      focused: **136 passed**.
- [x] 08a's 27-case verdict-parity manifest: **byte-identical**.
- [x] **Mutation-proven pinning**: demoting `resolved_plugins` out of the
      hashed body → **3 failed / 18 passed**, including the mutated-plugin
      resume refusal. Restored, caches cleared, re-baselined green.
- [x] `ruff check` + `ruff format --check` clean (718 files).
- [x] `pyright` — CI-owned; **SUCCESS** in exact-head CI 32217121228 on `65a3c7d9`.

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
- [x] Capture-first: freeze the six checks' verdicts and the composed
      artifact BEFORE migrating, reusing 08a's manifest generator.
      → 08a's 27-case manifest (unchanged), plus a NEW golden
      `goldens/pre_c5_tidmad_executed_semantics.json` capturing all six
      gates field-by-field at the C4 head, plus
      `goldens/pre_08b_shipped_configs.json` freezing the two shipped
      configs verbatim at `be11ec09`.
- [x] Move values with provenance comments intact.
      → `configs/task_health/tidmad.yaml`, GENERATED from the loaded config
      rather than transcribed, so no threshold could be mistyped.
- [x] **Atomically**: the numerical scale, its task-owned declaration, and
      the checks' `value_scale_unit` requirement move in ONE commit.
      → `ValueScale` in the task config; composition injects the factor into
      exactly the checks that DECLARE the axis; the four modules lost their
      literal and gained the requirement in the same change.
- [x] Apply the `TASK_HEALTH_PEEK` disposition after re-confirming its
      consumer census.
      → Census: zero production YAML uses it, no Python consumer outside
      `config.py`. **Retained as a bounded legacy adapter, not removed** —
      see the deviation below; the audit falsified the removal option.
- [x] **Redirect binding state A (legacy omitted) to the task-owned TIDMAD
      config.**
      → `LEGACY_DEFAULT_TASK_HEALTH_CONFIG`, a single unconditional constant.
- [x] Census: framework YAML contains no task identity, threshold, roster,
      peek set or science prose.
      → `test_the_framework_config_carries_no_task_identity` and
      `test_the_shipped_framework_file_is_policy_only`, both asserting on the
      PARSED document so explanatory comments stay free to name the task.

**Validation plan.** 08a's 27-case manifest byte-identical. Default parity on
the **executed sequence**: same gates selected, same executed check order,
same actions, field-by-field persisted equality against a pre-C5 dump.
Negative: a framework YAML carrying a task threshold is REFUSED.

**Acceptance criteria.**
- [x] 27/27 manifest cases byte-identical.
      → `OK — 27 cases reproduce the committed manifest byte-identically`,
      AFTER the value-scale migration. This is the decisive evidence that the
      arithmetic did not move: the same inputs still produce the same
      verdicts, metrics and prose.
- [x] Persisted fields byte-equal on TIDMAD-shaped fixtures; the six gate
      ids unchanged.
      → `TestTidmadOwnershipMigrationPreservesExecutedSemantics`: gate ids
      and ORDER, `gate_role`, `after_round`, `short_circuit`, `on_pass`,
      `on_fail`, check names, and every threshold/parameter — field by field
      against the pre-migration golden. Only the injected scale may be new.
- [x] `value_scale_unit` is DECLARED by the checks that need it AND
      SUPPLIED by the task facts — both directions asserted.
      → `test_exactly_the_scale_consuming_checks_declare_the_value_scale_axis`
      is a BICONDITIONAL (a check that does not scale must NOT declare it, or
      it would be inapplicable for a property it never uses);
      `test_the_scale_reaches_exactly_the_checks_that_declare_it` asserts the
      supply side, by declaration and never by check name.
- [x] Exactly ONE numerical scale value exists in the task config; zero
      `_MV_PER_LSB` literals remain in the health package.
      → `test_no_mv_per_lsb_literal_remains_in_the_health_package` is
      **AST-based**, so the historical mentions these modules keep in their
      docstrings do not trip it while an executable one would;
      `test_the_task_config_declares_the_scale_exactly_once` pins the number.
- [x] TIDMAD runs with its science out of framework YAML and **no
      task-name branch anywhere** — census test.
      → The only task name in generic core is the ONE unconditional
      `LEGACY_DEFAULT_TASK_HEALTH_CONFIG` constant — a default path, not a
      branch. C7's census generalises this.

**Failure and edge cases.** A threshold silently changing (manifest catches
it); the effective sha moving (EXPECTED per Q-08b-2 — record the exact
delta, rely on the fresh-workspace boundary, assert the refusal); a check
declaring the scale axis before facts supply it (the reason both move
together).

**Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ -q`
      Evidence: **547 passed, rc=0**.
- [x] `tests/unit/execute_tools/ tests/unit/core/`: **3 926 passed, 1
      skipped, rc=0, 177.8 s** — the subsystem sweep the changed loader
      semantics required.
- [x] 08a's 27-case verdict-parity manifest: **byte-identical**.
- [x] `ruff check` + `ruff format --check` clean (810 files).
- [x] `pyright` — CI-owned; **SUCCESS** in exact-head CI 32217121228 on `65a3c7d9`.

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
- [x] Re-confirm §2.6 at the head: `MetricResult.per_sample is None` is the
      producer-side statement; the bridge destroys it.
      → Confirmed verbatim. `execution.py` held
      `list(metric_result.per_sample or [])` with the comment "a scalar-only
      instance an empty one", and `file_vector` reached
      `HealthCheckContext` from there.
- [x] Carry the statement into `HealthCheckContext` as a typed value
      distinguishing "no per-sample evidence exists for this task" from
      "per-sample evidence exists and is empty".
      → `PerSampleEvidence` (`AVAILABLE` / `SCALAR_ONLY` / `UNDECLARED`) +
      `HealthCheckContext.per_sample_evidence`, defaulting to `UNDECLARED`
      so every pre-D18 context and every pre-scoring gate keeps its exact
      meaning. The mapping lives in ONE place,
      `PerSampleEvidence.for_per_sample`, so a second site cannot disagree.
- [x] Per-file checks declare the requirement so the engine yields
      `INAPPLICABLE` with the axis named.
      → New `per_sample_evidence` context input; a declaring check yields
      `CheckVerdict.INAPPLICABLE` with `inapplicable_axis =
      "per_sample_evidence"` through the real runner. **No SHIPPED check
      declares it, deliberately** — see the finding below.

**Validation plan.** Unit: scalar-only task → per-file checks
`INAPPLICABLE`, axis named; per-file-capable task → applicable. **Negative
control**: TIDMAD unchanged (per_sample present) — manifest replayed.
Census: no check reads `denoising_score` or the metric scalar.

**Acceptance criteria.**
- [x] The statement is TYPED — an absent/empty field is never the signal.
      → `test_an_empty_file_vector_and_a_scalar_only_metric_are_different_states`
      asserts both states produce the SAME `file_vector` and differ only in
      the typed value, which is the defect stated as an assertion.
- [x] Under a scalar-only metric, a declaring check reports `inapplicable`,
      NOT `passed`.
      → `test_the_gate_records_INAPPLICABLE_rather_than_a_pass`, asserting
      the VERDICT (08a routes inapplicable with `passed=True`, so asserting
      `passed` alone would not distinguish it from health) and that the
      check was never invoked.
- [x] TIDMAD per-file behaviour byte-identical.
      → TIDMAD's metric returns a per-file vector, so it takes the
      `AVAILABLE` branch and nothing moves: the 27-case manifest is
      byte-identical and the health package is green.
- [x] Census: no check reads `denoising_score` or the metric scalar
      (invariant 16), and the context vocabulary grew by exactly one entry.
- [x] **Mutation-proven**: reintroducing the collapse (`for_per_sample(
      per_sample or [])`, which would report a scalar-only metric as
      AVAILABLE) turns the reachability test RED — **1 failed / 15 passed**.
      Restored, caches cleared, re-baselined green.

**Failure and edge cases.** A task declaring nothing about per-sample
capability: absence ≠ scalar-only, must not be inferred.

**Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ -q`
      Evidence: **563 passed, rc=0** (547 at C5 + 16 new).
- [x] `tests/unit/agent/tune_ml_hyperparam_agent/`: see §10 C6 below.
- [x] 08a's 27-case verdict-parity manifest: **byte-identical**.
- [x] `ruff check` + `ruff format --check` clean (765 files).
- [x] `pyright` — CI-owned; **SUCCESS** in exact-head CI 32217121228 on `65a3c7d9`.

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
- [x] Build the fixture package entirely under `tmp_path`: task health
      config + provider plugin + custom check declaring a plugin-local
      capability.
      → `test_out_of_tree_extension.py`: an "acme" sensor task with its own
      capability key, provider, check and threshold — deliberately unlike
      TIDMAD, since a seam that only worked for a TIDMAD-shaped task would
      be a registry wearing a plugin's clothes.
- [x] Assert the full chain: config → loader → registration → resolution →
      provider → custom check → `HealthCheckResult`.
- [x] Assert the fixture's ids/names appear **nowhere in production source**
      (grep census), and that the loader receives only external config/paths.
- [x] Negative control: remove/break the plugin → deterministic fail-closed
      resolution; restore → flow succeeds.
- [x] Census: zero task-name branches; no central task registry; no closed
      view-kind enum; no framework-YAML task identity; no registration path
      requiring a central import edit.
- [x] Docs sync last, quoting each documented behaviour against merged
      source.

**Acceptance criteria.**
- [x] The proof passes without any fixture-specific entry in a registry,
      import list or shipped YAML — asserted by the id-absence census, **not**
      by checking `git diff`.
      → Four fixture identifiers, each grepped across
      `execute_tools/ nodes/ agent/ core/ scripts/ workflows/ configs/`;
      all absent. Guarded against vacuity by a probe asserting the SAME
      search DOES find `output_diversity`.
- [x] Remove-plugin → fail closed; restore → succeed (both directions).
      → Plus a third state the design did not enumerate: a plugin that LOADS
      but registers nothing fails at **resolution**, naming the check the
      config asked for rather than the file — which is §3.2's
      loading-is-not-resolution distinction made executable.

**Failure and edge cases.** The proof passing because the fixture
accidentally imported an in-repo module — assert its provider/check come
only from its own files.

**Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/ -q`
      Evidence: **580 passed, rc=0** (563 at C6 + 17 new).
- [x] With `tests/unit/guardrails/`: **716 passed, rc=0**.
- [x] `ruff check` + `ruff format --check` clean.
- [x] `pyright` — CI-owned; **SUCCESS** in exact-head CI 32217121228 on `65a3c7d9`.

**Docs synchronized** (quoted against merged source):

| doc | what was stale | now |
|---|---|---|
| `docs/design/pluggable_health_checks.md` | §3 described the framework YAML as carrying the roster | NEW §3.0 states the owner split, the three binding states, plugin pinning and that `load_health_gates_config` returns the COMPOSED config; the rev-6 shape is kept as §3.1, relabelled as what composition PRODUCES |
| `CLAUDE.md` HealthGate section | "source of truth for gate POLICY … thresholds … DEFAULT monitored-file placement" | policy-only; thresholds/roster/peek/scale/prose in `configs/task_health/tidmad.yaml`; where to edit WHICH; the skill signature and that the `__init__` import list is not the extension path |
| `nodes/…/ml_hyperparameter_tune_agent.md` | no D18 record | `per_sample_evidence` row: the derivation, the three states, the hollow-pass it removes, and that two of three tracks are scalar-only |
| `examples/{oxford_iiit_pet,davis_future_prediction}/STATUS.md` | claimed the framework YAML is "TIDMAD-shaped policy" | §11's honest current position (see the cross-task audit) |

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

### C1 — task health config schema (authoring validation only)

**Status: IMPLEMENTED, validated, committed.**

Implementation head base: `be11ec09` (branch HEAD == local master ==
`origin/master`, clean tree — verified before any edit).

Files: NEW `execute_tools/health_checks/_task_health_config.py` (302 lines);
NEW `tests/unit/execute_tools/health_checks/test_task_health_config.py`
(43 cases); one line of `schemas.py` (see the deviation below).

#### Ownership / migration table (C5 consumes this)

§2.3 was re-verified verbatim against `configs/health_checks.yaml` at the
implementation head: **exact match, no drift.** The table below is that
reading expressed as the post-08b ownership split, and is what C5 migrates.

| current YAML location | value | owner after 08b | lands as |
|---|---|---|---|
| `health_gates[].id` | the six gate ids | **task** | `HealthRosterEntry.gate_id` |
| `checks[].name` | the six check names | **task** | `HealthRosterEntry.check` |
| `gate_role` | `blocking` ×3 / `observational` ×3 | **framework** | derived from `disposition` |
| `after_round` | `every` ×6 | **framework** | policy |
| `short_circuit` | `true` ×3 / `false` ×3 | **framework** | derived from `disposition` |
| `on_pass.action` | `continue` ×6 | **framework** | derived from `disposition` |
| `on_fail.action` | `invalidate_round` ×3 / `continue` ×3 | **framework** | derived from `disposition` |
| `min_unique_int8_values: 25` | threshold | **task** | `parameters` |
| `min_std_mv: 1.0` | threshold | **task** | `parameters` |
| `collapse_threshold: 0.95` | threshold | **task** | `parameters` |
| `peek_samples: 100000` ×3, `1000000` ×2 | task parameter, NOT a threshold (08a's corrected semantics) | **task** | `parameters` |
| `peek_file_indices: task_health_peek` ×3 | the peek SET | **task**, declared ONCE | `health_peek_files` + `uses_health_peek_files=true` on those three entries |
| `aggregation: any_pass` ×3 | gate policy | **framework** | refused in `parameters` |
| `reason:` prose ×6 | task science | **task** | `HealthRosterEntry.reason` |
| `_MV_PER_LSB = 40.0/128.0` in **four** check modules | the numerical scale | **task**, declared ONCE | `ValueScale(unit="mV", units_per_sample=0.3125)` |

Two dispositions cover all six gates with nothing left over, which is what
makes the disposition rule a description of production rather than a new
invention:

```text
blocking   -> (blocking,      after_round=every, short_circuit=true,
                on_pass=continue, on_fail=invalidate_round)   ×3
recording  -> (observational, after_round=every, short_circuit=false,
                on_pass=continue, on_fail=continue)           ×3
```

**Parity note for C5.** `uses_health_peek_files` defaults to **false**, and
that default is load-bearing rather than conservative: only the three
BLOCKING gates carry `peek_file_indices` today, and `config.py`'s
`_resolve_declared_peek_selection` docstring states that injecting it where
absent would move the three recording gates from every file onto a
three-file triplet — *"a policy change, not an authority change"*. The opt-in
therefore reproduces today's placement exactly, and the schema refuses the
opt-in when no set is declared so it can never silently resolve to nothing.

#### Decisions

* **`config.py` is NOT split** (C1's first checklist item, answered from
  measurement). 514 lines, four consecutive stages of one pipeline; C1 adds
  no responsibility to it.
* **`HealthPluginRef.kind` is DECLARED, not probed.** §3.2 gives a missing
  explicitly-named FILE and an unloadable MEMBER of a configured DIRECTORY
  deliberately different outcomes, and C2's acceptance criterion requires
  them to be *asserted as a pair*. A ref that does not exist cannot be
  classified by looking at the filesystem — the case where the distinction
  matters most is exactly the case where the disk cannot answer. The document
  states which it is, so the loader never guesses and never infers from a
  `.py` suffix.
* **Plugin refs must be RELATIVE.** Absolute paths and `~` are refused at
  Phase A because both resolve against THIS host, which would make the pinned
  plugin identity host-specific and break C4's path-independence criterion
  (§3.6: two identical packages at different absolute paths must pin one
  semantic identity).
* **The peek set is declared once, opted into per entry** — rather than a
  literal list restated in three roster entries, which would be three copies
  of one fact and reintroduce exactly the duplicate-truth failure §3.7
  exists to eliminate. `peek_file_indices` is consequently refused inside
  `parameters`.
* **No `task_id` field.** Nothing in the frozen design needs one, and
  omitting it makes a task-name branch structurally harder to write
  (invariant 19). Diagnostics name the configured ref instead.
* **`invalid disposition name` gets one parametrized row, not its own test.**
  It is enforced by the `HealthDisposition` declaration, and CLAUDE.md
  forbids building a test around what a declaration already guarantees; it
  is present only because the frozen acceptance criterion enumerates the
  class.

#### Deviation — one, recorded because it touches an 08a authority

**Previous assumption:** the C1 document could reuse `TaskHealthFacts`
unchanged.

**Audit evidence:** `schemas.py:741` declared
`model_config = ConfigDict(frozen=True)` with no `extra` policy, so Pydantic's
default `extra="ignore"` silently DROPPED an unknown key. Caught by a C1 test
asserting a second facts vocabulary cannot be smuggled in
(`test_an_axis_outside_08a_vocabulary_is_refused` — it did not raise).

**Corrected understanding:** 08a fail-closes a typo'd axis on the CHECK side
(`FactRequirement._axis_is_known`, whose docstring says a typo would leave the
check *"silently inapplicable for every run"*) but the TASK side was
fail-open. That asymmetry was harmless while facts were only ever DERIVED
in-repo from a resolved profile — `_regime_a_facts.derive_health_facts` passes
five known fields. **08b makes the vocabulary externally AUTHORABLE for the
first time**, where a hand-written `encodng_family` is the expected slip, and
the consequence is the exact failure mode 08a legislated against: the task
declares nothing about the axis, and every check requiring it reports
inapplicable forever while looking like a deliberate opt-out.

**Implementation consequence:** `extra="forbid"` added to `TaskHealthFacts`
— one line, at the vocabulary's own home rather than at this document's
boundary, so every future consumer inherits it. Census first: all 12
construction sites (1 production, 1 new, 10 test) pass explicit known fields,
so nothing relied on the tolerance.

**Validation consequence:** none of 08a's behaviour moves — the change only
affects inputs that were previously discarded. Health package **483 passed**;
the 27-case verdict-parity manifest reproduces **byte-identically**.

#### Validation

* Health package: **483 passed, rc=0, 2.02 s** (440 pre-existing + 43 new),
  verdict read from `/tmp/08b_c1.log`.
* 08a verdict-parity manifest `--check`: **27/27 byte-identical**.
* Unreachability guard **mutation-proven**: a real production import in
  `runner.py` turned it RED naming `runner.py:206`; restored byte-identical,
  caches cleared, baseline re-run green.
* `ruff check` + `ruff format --check` clean.
* `pyright` not runnable locally (Node `v10.19.0`) — **CI-owned**.

#### Remaining risk

None for C1 — the module is inert and the guard proves it. The risk it
carries forward is C5's: the table above is now the migration's source of
truth, and a threshold transcribed wrongly would be caught by the manifest
and the persisted-field parity dump, not by anything in C1.

---

### C2 — run-scoped plugin loading, registration, and lifecycle

**Status: IMPLEMENTED, validated, committed.**

Files: NEW `execute_tools/health_checks/_plugin_binding.py`; NEW
`tests/unit/execute_tools/health_checks/test_plugin_binding.py` (19 cases);
`__init__.py` (six exports + a corrected docstring); C1's guard inverted in
`test_task_health_config.py`.

#### The idiom, re-read at the head and instantiated

Both existing loaders were re-read (`ml_models/plugin_loader.py:49-155`,
`agent_generated/_loss_loader.py`). Health's instance reproduces the same
shape: `spec_from_file_location(<stable name>, path)` → `sys.modules[name]`
registered BEFORE `exec_module` (so the plugin sees its own `__name__` and
`inspect` can resolve its source) → popped on failure so a fixed plugin is
retriable in-process → directory scan via `sorted(os.listdir(...))` skipping
non-`.py` and `_`-prefixed members. Module-name prefix
`siderius_health_plugin_`, distinct from the model and loss prefixes.

**Three deliberate differences**, each source-grounded:

1. **Config, not environment, is the authority** (Q-08b-1) — and therefore
   **no Health env var exists**. `SIDERIUS_PLUGIN_DIRS` / `SIDERIUS_LOSS_DIRS`
   exist as SUBPROCESS transport (`core/subprocess_env.py`, whose docstring
   records the V20 incident that created it). Health checks run only in the
   run process: `execute_tools/denoising_score_single.py` and
   `inference_single.py` import the health package NOWHERE (grepped at the
   head). An env var would be speculative machinery and the exact ambient
   parallel input Q-08b-1 forbids.
2. **Registration is by CALL, not by module attribute.** Parent §6a.3 says the
   plugin registers "through the SAME PUBLIC registration functions the
   built-ins use", so a Health plugin calls `register()` and this module
   learns what it produced by DIFFING the registry across the import. No new
   plugin-attribute vocabulary exists for an external author to get wrong.
3. **An explicitly named FILE that fails is FATAL**, per the §3.2 amendment.

#### Decisions

* **A missing configured DIRECTORY is fail-closed.** §3.2's table names the
  missing FILE case explicitly and gives per-MEMBER tolerance to directories,
  but is silent on a directory that does not exist at all. Resolved from the
  amendment's own principle — *"an unrelated member is not something the task
  asked for"*. The directory itself IS something the task asked for by name,
  and nothing it declares could resolve, so continuing would run a different
  set of gates than the config describes. The model loader's `continue` on a
  missing directory is not a counter-precedent: it scans env-var-supplied
  directories with a legacy fallback, where config is not the authority.
* **Partial registrations are rolled back.** A module that registers check A
  and then raises previously left A in the registry, able to satisfy a
  binding while the code defining its behaviour never finished executing.
  `_import_and_register` removes anything registered before the failure.
* **The run-scope ledger compares CANONICAL identity**, not absolute paths,
  so a relocated checkout is correctly the SAME set rather than a conflicting
  second run. This is the C2-level half of §3.6's path-independence
  requirement; C4 asserts the sha half.
* **`reset_run_scope()` deliberately does not unregister.** Registry
  restoration is `clean_registry`'s job; two mechanisms undoing each other's
  work is how a test starts passing for the wrong reason.

#### Deviation — C1's guard was INVERTED at C2, not C3

**Previous assumption:** §4.1 said C1's unreachability grep-test would be
"INVERTED in C3 rather than deleted".

**Audit evidence:** the health package turned RED at C2 with exactly that
guard failing — `_plugin_binding.py` imports `TaskHealthConfig` to read
`config.plugins`, which is a legitimate production consumer one commit
earlier than the design anticipated.

**Corrected understanding:** the timing was off by one commit; the SEMANTICS
are unchanged. This is the same event 08a recorded ("It fired correctly the
moment C3 landed, which is how the inversion was prompted").

**Implementation consequence:** inverted now, into
`TestTaskHealthConfigIsConsumedOnlyThroughTheBindingSeam` — the task health
config is task-owned truth and may be consumed only through an ALLOWLIST of
seam modules (C2: `_plugin_binding.py`; C4 will add its composition module).
A check, runner or script reading it directly would be a second reader
deciding for itself what a roster or threshold means — invisible to every
behavioural test until the two readings disagree.

**Validation consequence:** a companion `test_the_allowlist_is_not_vacuous`
asserts the allowlist EQUALS the actual consumer set, so deleting the real
consumer cannot leave the guard green describing a relationship that no
longer exists.

#### Deviation — the provider half of C2's validation moves to C3

§4.2's validation plan says "a plugin registers a provider and a custom
check". Providers do not exist until C3 defines the protocol (§4.3 scope), so
C2 proves the CHECK half. This is a forward reference in the prose, not a
missing acceptance criterion: all four of C2's acceptance criteria are stated
in terms of checks, and C3's plan carries the provider case.

#### Validation

* Health package: **503 passed, rc=0, 2.03 s** (483 at C1 + 19 new + 1 new
  allowlist-vacuity guard).
* 08a verdict-parity manifest `--check`: **27/27 byte-identical**.
* **Mutation-proven ledger**: `if _RUN_SCOPE is not None:` → `if False:`
  (exactly 1 site, asserted) gives **5 failed / 14 passed**, including the
  two-run counterfactual. Restored, `__pycache__` cleared, re-baselined green.
* `ruff check` + `ruff format --check` clean (53 files).
* `pyright` not runnable locally — **CI-owned**.

#### Remaining risk

External plugins execute arbitrary Python by design — the same trust model
the model and loss loaders already carry, and a property of the task package
rather than of this seam. Nothing new is introduced: the config naming the
file is already trusted run input.

---

### C3 — provider protocol, binding resolution, payload transport

**Status: IMPLEMENTED, validated, committed.**

Files: NEW `execute_tools/health_checks/_view_provider.py`; NEW
`tests/unit/execute_tools/health_checks/test_view_provider.py` (15 cases);
`registry.py` (provider registry); `_plugin_binding.py` (Phase-B resolution
+ `materialize_view`); `protocol.py` (frozen view signature); `schemas.py`
(`CheckInputDeclaration.requires_view`); `runner.py` (the materialization
step); the seven built-in checks (mechanical `*, view=None`); `conftest.py`
(`clean_registry` now covers providers).

#### Deviation — `requires_view`, and why the frozen dispatch rule needed it

**Previous assumption:** §3.3's dispatch rule reads *"check does NOT declare
`consumes_view` → legacy shape; check DOES declare `consumes_view` → pass
`view=`"*, as though `consumes_view` were optional.

**Audit evidence:** `CheckInputDeclaration.consumes_view` is a REQUIRED field
with no default (`schemas.py`), and **all seven built-ins populate it** —
they name a capability and then read their own artifacts through `_peek`. So
under the literal rule every built-in would take the view path, which
directly contradicts the same commit's acceptance criterion: *"All pre-08b
checks execute through the unchanged no-view call path."*

**Corrected understanding:** the two statements are simultaneously
satisfiable only if the discriminator is *"a view was RESOLVED for this
check"*, not *"this check named a capability"*. And §3.2's startup-ERROR case
(*"family declares a check REQUIRING capability X; bound provider does not
advertise X"*) then needs a trigger, because a check that merely names a key
must not fail a run that binds no provider — TIDMAD binds none, so all six
would fail closed.

**Implementation consequence:** `CheckInputDeclaration` gains
`requires_view: bool = False` — additive, and the default preserves every
existing check exactly. `consumes_view` NAMES the capability; `requires_view`
says whether the check is helpless without it. Only `requires_view=True`
makes the binding mandatory and fail-closed. Dispatch stays as frozen: a view
is passed when one resolved, and never gratuitously.

**Validation consequence:** the 27-case manifest is byte-identical and
`test_all_seven_builtins_declare_a_capability_but_require_no_view` pins the
property as a CONCEPT across every registered check, so a future check
setting `requires_view` cannot do so silently.

#### Decisions

* **Materialization lives INSIDE the existing Bug-B guard.** §3.3 says
  provider errors are "caught by the runner exactly like check exceptions";
  putting the call inside that `try` achieves it with one added branch and
  keeps `first_failure_reason` / `short_circuit` / action selection in one
  place. The reason prose distinguishes the component
  (`"view provider failed"` vs the unchanged `"check raised unexpected"`), so
  a reader is not sent to the wrong module. The mutation showed the
  alternative placement lets the provider error escape `evaluate_gate`
  entirely.
* **The provider registry lives in `registry.py`**, beside the check
  registry: one registration surface for a plugin to import and one place
  for the loader to diff, with separate namespaces so a provider cannot
  shadow a check.
* **Two bound providers advertising one capability are REFUSED**, not
  resolved by binding order. Deterministic resolution is worth more than
  convenience, and the alternative is a run whose checks read whichever
  provider happened to be listed first.
* **`clean_registry` now snapshots the provider registry too.** A leaked
  provider is worse than a leaked check: it would silently satisfy another
  test's capability binding and make a fail-closed test pass.

#### Validation

* Health package: **518 passed, rc=0** (503 at C2 + 15 new).
* 08a verdict-parity manifest: **27/27 byte-identical**.
* **Mutation-proven ordering**: materialization moved above the applicability
  decision → **2 failed / 13 passed**, with the provider error additionally
  escaping `evaluate_gate` uncaught. Restored and re-baselined.
* Blast-radius census: zero out-of-package implementers of the check
  Protocol; import-sanity for the tuner node, `core.run_invariants` and
  `workflows.model_exploration`.
* `ruff check` + `ruff format --check` clean.
* `pyright` — **CI-owned**, and it is the checker that verifies the Protocol
  relationship the seven mechanical `*, view=None` parameters exist for.

#### Remaining risk

A task that bound a provider advertising a built-in's capability key would
hand that check a view it ignores. No such provider exists in 08b (TIDMAD
binds none), and 08c owns the standard payload contracts that would make the
delivery meaningful. Recorded rather than guarded, because guarding it now
would mean interpreting an opaque capability key — exactly what §3.3
forbids.

---

### C4 — deterministic composition, plugin pinning, binding path

**Status: IMPLEMENTED, validated, committed.**

Files: NEW `execute_tools/health_checks/_composition.py`; NEW
`tests/unit/execute_tools/health_checks/test_composition.py` (21 cases);
`config.py` (`task_health_binding` parameter, `_load_task_binding`,
`read_effective_config_body_sha`); `core/resume.py` (delegates instead of
mirroring); the seam allowlist.

#### Capture-first baseline

Captured at the C3 head, BEFORE any composition code existed:

```text
pre-08b default-path body sha256 =
  c933bceeb04a06df4c3e06ecbbe3ae4aa9eb5594ecf17e0d9b511e571784855d
```

Frozen as a literal in the test. State A reproduces it exactly, and the
default body's key set is asserted to be exactly `{health_gates}`.

#### Deviation — the resume mirror was REMOVED, not synchronised

**Previous assumption:** §4.4's plan says *"keep `core/resume.py:354`'s
mirrored computation in step"*.

**Audit evidence:** that function re-derived the body sha by loading the
artifact into `HealthChecksConfig` and re-dumping it. `HealthChecksConfig`
declares only `health_gates`, so **any key it does not know is silently
dropped** — and C4's `resolved_plugins` / `task_health_binding` are exactly
such keys. Kept as a mirror, it would have reported a sha mismatch that was
not there, and every plugin-bound resume would have failed closed for a
reason that did not exist.

**Corrected understanding:** "keep in step" is achievable but fragile; the
duplication is the hazard. The artifact's body sha has one honest
definition — the bytes on disk, which is exactly what
`materialize_effective_config` hashed.

**Implementation consequence:** `config.read_effective_config_body_sha`
becomes the ONE implementation, hashing the file's body directly (header
stripped, still parsed for validity so the `None`-on-unparseable contract is
unchanged). `core/resume.py::_effective_config_body_sha` delegates to it.
This is strictly more faithful than any re-serialization: it verifies the
bytes the run actually reads.

**Validation consequence:** `test_resume.py` / `test_resume_incumbent.py` /
`test_run_invariants.py` — **136 passed**, unchanged.

#### Decisions

* **Two roster authorities are REFUSED, not merged.** A framework YAML with
  gates AND a task config with a roster raises `HealthCompositionError`.
  Reachable only in the C4→C5 window while the shipped YAML still carries
  TIDMAD's gates, and it makes §3.7's "exactly one definition" structural for
  the roster too.
* **State A adds NO keys at all**, not even an empty `resolved_plugins`. The
  effective config is workspace-immutable and fail-closed on mismatch, so an
  empty key would make every existing workspace refuse to resume for a change
  in nothing.
* **The named absence lives in the HASHED body**, so the pin itself records
  that no task family was bound — "no gates ran" must be readable as a
  decision rather than inferred from an empty list, which is also what a
  fully-passing run looks like.
* **Roster order is preserved, parameter key order is not.** The gate
  sequence is the executed sequence and therefore semantic; author-side dict
  ordering is not, and `sort_keys=True` neutralises it.

#### Two test defects found and repaired inside this commit

Both are recorded because each is a failure class the suite is supposed to
own, and each was caught by an existing guard rather than by inspection:

1. **A registration leak.** One C4 test bound a task config without the
   `clean_registry` fixture, so its `packaged_check` leaked into the
   process-wide registry and broke C2's
   `test_with_no_plugins_declared_the_registry_is_exactly_the_builtins`.
   That C2 test exists for exactly this, and it worked.
2. **Two tests reset the run scope where they should not have.** The
   path-independence test must NOT reset — the ledger recognising a relocated
   package as the same set is the property under test — while the
   mutated-plugin test must simulate a fresh PROCESS, clearing the
   registration as well as the ledger. Both now say so in a comment, because
   the correct answer differs between them for a real reason.

#### Out-of-scope finding (not 08b's, recorded not fixed)

`tests/unit/core/test_gpu_measurement_runner.py::TestTheParentEndsThePhase::
test_it_signals_only_after_the_required_samples_land` failed once inside the
2 950-test combined run and passes in isolation **both with and without** the
C4 changes. C4 touches nothing GPU-related. Classified as a load/timing
-sensitive flake in a test whose subject is a timing signal; recorded here
rather than fixed, since expanding 08b to repair it is not this PR's job.

#### Validation

* Health package: **539 passed, rc=0** (518 at C3 + 21 new).
* `tests/unit/core/`: rc=0; the three resume/invariants modules re-run
  focused, **136 passed**.
* 08a verdict-parity manifest: **27/27 byte-identical**.
* **Byte parity**: state A reproduces the captured pre-C4 sha exactly.
* **Mutation-proven pinning**: demoting `resolved_plugins` out of the hashed
  body → **3 failed / 18 passed**, including the resume refusal.
* `ruff check` + `ruff format --check` clean.
* `pyright` — **CI-owned**.

#### Remaining risk

The framework-vs-task roster conflict is refused rather than merged, which is
correct — but it means that between C4 and C5 an explicit TIDMAD binding
cannot coexist with the un-slimmed shipped YAML. That is precisely why §3.10
orders the commits this way, and C5 resolves it atomically.

---

### C5 — TIDMAD ownership migration (the parity commit)

**Status: IMPLEMENTED, validated, committed.**

Files: NEW `configs/task_health/tidmad.yaml`; both shipped framework configs
slimmed to policy; `_composition.py` (`DispositionPolicy`, the policy table,
value-scale injection, `LEGACY_DEFAULT_TASK_HEALTH_CONFIG`); `config.py`
(`health_policy`, `load_composed_health_config`, `_load_raw_health_config`,
the legacy peek adapter); `_plugin_binding.py` (`bound_task_facts`);
`runner.py` (the facts redirect); the four scale-consuming checks; NEW
`tests/helpers/health_task_config.py`; three goldens; and the test
disposition across twelve modules.

#### The authorised sha delta (Q-08b-2)

```text
state A body sha, C4 head : c933bceeb04a06df4c3e06ecbbe3ae4aa9eb5594ecf17e0d9b511e571784855d
state A body sha, C5      : 7a4debd66f65e33fbe830e7f310f401a3184ab2d934d738c04a9d8e4eaf1dc5a
```

Expected and authorised. The body now carries `task_health_binding:
legacy_default`, and the six gates are composed rather than read. Old
workspaces still fail closed on the mismatch, which is the fresh-workspace
boundary working as designed.

#### Parity, measured on executed semantics (invariant 17)

Compared field-by-field against a golden captured at the C4 head:

| property | result |
|---|---|
| gate ids and ORDER | identical |
| `gate_role`, `after_round`, `short_circuit` | identical |
| `on_pass` / `on_fail` actions | identical |
| check names | identical |
| every threshold and parameter | identical |
| `aggregation: any_pass` on the three blocking gates | identical |
| peek set `[3, 10, 17]` on exactly the three blocking gates | identical |
| new keys | ONLY the injected value scale, on exactly the four checks that declare the axis |
| `reason` prose | identical modulo whitespace — YAML folded blocks re-wrap on round-trip, and `reason` is documented as not consumed by the runner |
| 08a's 27-case verdict manifest | **byte-identical** |

The manifest is the decisive one: the same inputs still produce the same
verdicts, metrics and prose *after* the millivolt factor changed owner.

#### Deviation 1 — framework policy had to become DATA, not a constant

**Previous assumption:** C4 held the disposition→policy table as a Python
constant, and C5 would simply slim the YAML.

**Audit evidence:** the two shipped configs are identical apart from
`on_fail` on the blocking gates — observe mode records where production
invalidates. With the table hard-coded, the observe-mode config would have
become **inexpressible**: it carries no roster to differ in, and its one real
difference is a policy field.

**Corrected understanding:** "framework policy" is exactly what differs
between those two files, so it belongs in them. `health_policy` is now a
config block; `DEFAULT_DISPOSITION_POLICY` remains as the fallback so a
pre-08b custom YAML keeps working without acquiring a block it never had.
The observe-mode file went from a duplicated six-gate roster to a two-line
difference — and can no longer drift from production science, because both
policies share one task config.

**Implementation consequence:** `health_policy` is `exclude=True` in
serialization. It is an INPUT to composition, not part of its result: once
gates are composed each carries its resolved policy directly, so emitting it
would state the same facts twice and change the pinned sha for nothing.
`apply_monitored_files` carries it across explicitly, because a "pure
transform" that silently dropped a field would be a worse defect than the one
it fixes.

#### Deviation 2 — `TASK_HEALTH_PEEK` is RETAINED, and the audit is why

**Previous assumption (§3.8):** remove the sentinel in C5, provided no
consumer outside `config.py` remains. The census confirmed exactly that
condition — zero production YAML, no Python consumer elsewhere.

**Audit evidence:** removal was implemented, and it turned the
historical-artifact tests RED. `candidate_eligibility._LEGACY_ROLES_BY_CONFIG_SHA`
recovers the gate roles of a workspace written before `gate_role` existed by
re-reading a pre-08b config and reproducing its recorded
`health_config_sha256` — and that sha is computed over the **resolved**
document. Pre-08b configs carry the marker, so refusing to resolve it makes a
genuine historical artifact unreadable and turns every affected candidate
UNKNOWN.

**Corrected understanding:** §3.8's own fallback branch applies — "if a
bounded legacy Regime-A path still needs it, it may remain strictly as a
legacy compatibility adapter". It does need it. The removal condition was
satisfied on paper and falsified in fact, which is precisely why the design
made the disposition conditional on a C5 audit rather than deciding it up
front.

**Implementation consequence:** the marker still resolves, documented at both
its declaration and its validator as a bounded legacy adapter — explicitly
NOT the extension mechanism, NOT required by any future task, NOT generic
task-package vocabulary. No shipped config uses it; a new task declares
`health_peek_files` in its own config.

#### Decisions

* **The task config was GENERATED from the loaded framework config**, not
  transcribed. On the highest-risk diff in Step 08 (R-08b-1), a hand-copied
  threshold is a real failure mode and mechanical extraction removes it.
* **`load_health_gates_config` now returns the COMPOSED config.** The
  alternative — a new function plus updates at every roster-reading call site
  — would have left `runner`, `candidate_eligibility`, `launch_policy`,
  `evaluation` and three sites in `scripts/run_comparison.py` each able to
  drift. A file that already carries gates is returned untouched, which
  covers a materialized effective config and a custom YAML with one rule.
* **The facts redirect uses the call site 08a prepared.**
  `runner._resolve_task_facts` prefers the bound task's DECLARED facts and
  falls back to the regime-A derivation. Regime A exists because nothing
  declared them; deriving while the task declares would be two answers to one
  question, and the derivation is the one that cannot see `value_scale_unit`.
* **A missing injected scale raises rather than yielding `inapplicable`.**
  Invariant 2: the factor's absence is a COMPOSITION defect, and a
  configuration error must never become a Health verdict. The check's
  declared `value_scale_unit` requirement is the separate, correct route to
  inapplicability when a task declares no scale.
* **In-repo location is `configs/task_health/tidmad.yaml`, not
  `examples/tidmad/`.** D14 established that production must carry **zero
  dependency on `examples/`**, and state A's default path is production. The
  pack governance guards would have permitted it; the D14 invariant is the
  binding one.

#### Test disposition (§5, executed)

The design named two test files; the migration touched **twelve**, because
the framework YAML's roster was read far more widely than the design
anticipated. A mechanical difference in SCALE, not in semantics — every case
below preserves its original defect class:

| module | disposition |
|---|---|
| four check test modules, `_verdict_corpus`, `test_step02c_derived_all_files`, `test_health_scope`, `test_check_verdict` | **UPGRADE** — supply the scale composition now injects. These assert millivolt arithmetic and now have to say what a millivolt is. |
| `test_check_declarations` | **UPGRADE** — the four declarations gained the axis; 08a's "no check declares a value scale" guard is **INVERTED** into a biconditional rather than deleted. |
| `test_config_loader` | **UPGRADE** — a roster-less file is not a statement that there are no gates; the A/B distinction is now asserted directly. |
| `test_scientific_role_consistency`, `test_honest_gate_labels` | **REWRITE** — the historical-artifact invariant is now tested against FROZEN pre-08b bytes instead of reconstructed from today's shipped file. Strictly stronger: the old form broke on any innocuous edit, which is what just happened. A companion test pins that the audited map is not re-keyed. |
| `test_step00_health_config_baseline` | **SPLIT** — it was making two claims at once. The golden is re-captured, and a re-captured baseline proves nothing, so the values claim is now carried separately against a pre-migration capture. |
| `test_step02c_*` live consumers | **UPGRADE** — the contrast declaration moved from the dataset profile to the task config; shared helper `tests/helpers/health_task_config.py` so two modules cannot disagree about what "declared" means. |
| `test_composition` | **UPGRADE** — C4's byte-parity claim is replaced by the executed-semantics claim C5 authorises, with the sha move ASSERTED rather than merely tolerated. |

A new `preserved_registry` fixture was added beside `clean_registry`: since
C5, composing the legacy default resolves its roster against the registry, so
a cleared registry makes state A fail closed for a reason the test is not
about.

#### Validation

* Health package: **547 passed, rc=0**.
* `tests/unit/execute_tools/` + `tests/unit/core/`: **3 926 passed, 1
  skipped, rc=0** (177.8 s).
* 08a verdict-parity manifest: **27/27 byte-identical**.
* `tests/unit/agent/tune_ml_hyperparam_agent/ tests/unit/nodes/
  tests/unit/scripts/ tests/unit/workflows/`: **1 969 passed**, plus ONE
  failure that is a guard working as designed —
  `test_pr3_l2p_preflight::test_preflight_all_invariants` runs
  `git diff --name-only` and refuses an uncommitted production tree
  (CLAUDE.md: *"commit the checkpoint, re-run — NEVER relax the guard"*). It
  passes at the committed head.
* `ruff check` + `ruff format --check` clean (810 files).
* `pyright` — **CI-owned**.

#### Remaining risk

The migration is proven on TIDMAD's own roster and on the frozen corpus. What
neither can show is the real lifecycle — startup composition against real
data, six gates firing in a real run, real persisted values. That is exactly
what the bounded Gate 2 at the C6 head owns (§7).

---

### C6 — D18: scalar-only metrics as a typed statement

**Status: IMPLEMENTED, validated, committed. THE GATE-2 HEAD.**

Files: `schemas.py` (`PerSampleEvidence`, the context field, the context
input); `nodes/ml_hyperparameter_tune_agent/execution.py` (the bridge); NEW
`tests/unit/execute_tools/health_checks/test_per_sample_evidence.py`
(16 cases).

#### What the bridge did, and what it does now

```text
BEFORE   file_vector = list(metric_result.per_sample or [])
         # "a scalar-only instance an empty one" — the comment said it

AFTER    per_sample          = metric_result.per_sample
         file_vector         = list(per_sample or [])          # unchanged
         per_sample_evidence = PerSampleEvidence.for_per_sample(per_sample)
```

The list is still built, because the record's `file_vector` still wants one.
What changed is that the STATEMENT no longer travels inside it. Step 06
already says scalar-only at the producer (`per_sample is None`, and the Pets
`AccuracyMetric` docstring says so in words); D18 is a transport fix, not a
new flag (invariant 16), and Step-06 arithmetic is untouched.

#### Decisions

* **Three values, not a boolean.** `UNDECLARED` is the default so every
  pre-D18 context and every pre-scoring gate keeps its exact meaning, and so
  absence is never inferred as a statement — the failure case §4.6 names.
* **An EMPTY `per_sample` is `AVAILABLE`.** The producer's claim is about
  capability; whether there is anything to read is `file_vector`'s question.
  Collapsing the two would reintroduce D18 one level up.
* **The mapping lives in ONE place** (`PerSampleEvidence.for_per_sample`)
  rather than inline at the bridge. A second spelling could disagree, and
  the disagreement would be invisible because both would produce a valid
  member.
* **The reachability guard reads the file as TEXT.** `execution.py` is a
  PRIVATE module of the tuner node and 08a's public-boundary rule forbids
  importing one from outside the node — the first draft did, and the import
  error caught it. Reading the file asserts the same fact without breaching
  the boundary the rule exists to protect.

#### Finding — no SHIPPED check declares the new input, and that is correct

§4.6 says "per-file checks declare the requirement". Audited at the head:
**no shipped check consumes per-sample evidence at all.** `file_vector` has
a `CONTEXT_INPUT_PREDICATES` entry but zero consumers among the seven
built-ins — the per-file checks (`per_file_output_std`,
`pearson_dispersion`) derive their per-file-ness from `file_group_size` and
read HDF5 files directly, which works regardless of the metric's shape.

Making them declare it would be wrong twice over: they would report
themselves inapplicable for a property they never use, and it would violate
the same biconditional discipline C5 established for `value_scale_unit`. So
C6 delivers the transport, the vocabulary and an executable proof of the
inapplicable path, with a census asserting the shipped checks correctly do
NOT declare it. **The consuming checks arrive with 08c's standard
capabilities** — which is where the design places them anyway.

Stated plainly rather than papered over: under the CURRENT shipped roster
the hollow pass D18 removes was not reachable, because TIDMAD's metric is
per-sample-capable and a scalar-only task's checks are already inapplicable
on `encoding_family`. D18 makes it unreachable by CONSTRUCTION rather than
by coincidence, before 08c adds checks for which the coincidence would not
hold.

#### Validation

* Health package: **563 passed, rc=0** (547 at C5 + 16 new).
* `tests/unit/agent/tune_ml_hyperparam_agent/`: **1 226 passed, rc=0**
  (430 s) — the suite owning the changed bridge.
* 08a verdict-parity manifest: **27/27 byte-identical**.
* **Mutation-proven**: `for_per_sample(per_sample or [])` — which would
  report a scalar-only metric as AVAILABLE — turns the reachability test
  RED (**1 failed / 15 passed**). Restored and re-baselined.
* `ruff check` + `ruff format --check` clean (765 files).
* `pyright` — **CI-owned**.

#### Remaining risk

None specific to D18. The remaining Step-08b risk is the real lifecycle,
which Gate 2 at this head owns.

---

### Gate 2 — specification, written BEFORE launch (§7)

**Claim.** On the REAL TIDMAD production path, after the roster, thresholds,
peek set and millivolt scale moved into a task-owned config: startup
composition produces the pinned effective artifact from framework policy +
`configs/task_health/tidmad.yaml`; all six gates fire at the round boundary
with the executed sequence preserved; every verdict is `passed` or `failed`
and **never `inapplicable`**; the injected value scale reaches the four
scale-consuming checks so their millivolt metrics are real numbers; and the
run completes with the standard record set.

**Why a Gate owns this, and why it is not redundant with 563 unit tests.**
Every unit test above composes the config by calling composition directly, or
hands a check its config by hand. Gate 2 is the only layer where the run
BUILDS the effective artifact at startup, pins it into the invariants lock,
and then evaluates gates against a context the tuner assembled from a real
round. Two C5 failure modes are reachable only here:

* **the four scale-consuming checks flipping to `inapplicable`.** They now
  REQUIRE the `value_scale_unit` axis, which only the task config supplies,
  through a facts redirect that runs on the real startup path. If the
  redirect did not fire, `resolve_health_facts()` would return the regime-A
  facts — where the axis is absent by construction — and four of six gates
  would silently stop judging. Every unit test that could see this supplies
  the facts itself.
* **the composed artifact not being what the run actually reads.** The pin,
  the invariants lock and the tuner's config-path swap are three startup
  steps no fixture exercises together.

**Exact HEAD.** `bf6e9e19` (C6), clean tree — the final executable head.

**Command** — the gate standard's canonical cold-start chain shape, with the
same two deviations 08a recorded, both re-verified at THIS head:

```text
bash sdsc_submission_scripts/<chain launcher> \
    --mode lilab \
    --workspace /tmp/gate2_step08b_1787113504 \
    --run_name gate2_step08b \
    --num_iterations 1 \
    --max_rounds 1 \
    --max_proposal_attempts 3 \
    --max_epochs 1 \
    --data_scope 4-9 \
    --health_gate_files 4,5,6,7,8,9 \
    --validation_max_portion 0.01 \
    --validation_max_train_samples 2000 \
    --no-force_formal_round \
    --trial_vram_budget_gb 16 \
    --formal_vram_budget_gb 16 \
    --llm_config llm_configs/openai_tiered_pro.json
```

No `--seed_paths` — cold-start, per the CLAUDE.md rule. The paired
`--data_scope` / `--health_gate_files` is the DS8 partial-scope requirement
and is also what puts the gates on the scoped files.

**Deviation 1 — `--runtime_watchdog` and `--validation_max_phase_seconds`
OMITTED.** Re-verified in source at this head:
`core/runtime_control/admission.py:148` still documents that the prephase
measurement covers `phase="training"` only, so 07c is still not implemented
and the 07a finding stands — the watchdog killed 3 of 4 attempts inside the
un-priced validation pass. Including a component known to be flaky and
unrelated to the health claim would manufacture INCONCLUSIVE runs. The gate
standard's §85 rule requires dropping `--validation_max_phase_seconds`
alongside it, which is done.

**Deviation 2 — VRAM budgets 24 → 16 GB.** Re-verified: the RTX 5090 is
shared and another user's job currently holds ~5.8 GB at ~80% utilisation.
16 GB leaves clear headroom so this run cannot OOM a colleague's work, and
the bounded workload needs far less. This only LOWERS the ceiling on real
work; it does not substitute a fake for a real one.

**Bounded scope.** 1 iteration · 1 round · 1 epoch · 6 of 20 files · ≤2 000
validation samples · ≤3 proposal attempts. Expected wall time ≤10 min; hard
stop and classify at 20 min (GPU contention could stretch it). Modest LLM
spend on `openai_tiered_pro.json`. Well inside the ≤1 h total envelope, and
the only real-runtime validation this PR spends.

**Launch authorisation.** The repository hook
`.claude/hooks/require_launch_approval.sh` requires that a chain launch be
explicitly attributed. The operator's Implementation Working Rules for this
PR authorise exactly one bounded Gate 2, launched autonomously once its
specification is written into this ledger — which is what this section is —
so the launch is recorded with the hook's explicit approval token rather
than bypassing it.

**Expected PASS evidence** (read from artifacts, never from exit code):

1. `{workspace}/health_checks_effective.yaml` exists and carries
   `task_health_binding: legacy_default` plus the six composed gates — proof
   that composition, not the framework file, produced the roster.
2. The six gate ids appear in the persisted `health_gate_results`, in the
   TIDMAD order.
3. The union of `check_verdicts` values ⊆ `{passed, failed}` — **no
   `inapplicable`**.
4. The three blocking gates carry `peek_file_indices` ⊆ the health-gate
   files, and `aggregation: any_pass`.
5. The four scale-consuming checks report finite millivolt metrics
   (`std_mv`, `std_mv_per_file_json`, pearson / spectral values), proving the
   injected factor arrived — a missing factor would have RAISED and produced
   `error` verdicts instead.
6. A completed `run_output_*.json`.

**Expected FAIL modes.** Any check reporting `inapplicable` (the C5 parity
break this Gate exists to detect); `value_scale_units_per_sample` missing at
a check, surfacing as `CheckVerdict.ERROR` with a `KeyError`; the effective
artifact lacking the composed roster; a gate that fails to fire; a threshold
differing from the pre-migration value.

**INCONCLUSIVE modes.** LLM provider outage; no candidate surviving 3
proposal attempts; a crash before the round boundary; GPU contention
preventing training. Any of these means the health path was not exercised
and the run proves nothing either way.

**Evidence destination.** Workspace records under the run workspace, with the
decisive fields extracted into this ledger and durable artifacts copied to
`/home/klz/Data/SIDEREIS_DATA/step08b_gate2_evidence_20260818/`.

### Gate 2 — RESULT: **PASS**

Executed at HEAD `bf6e9e19`, clean executable tree. Workspace
`/tmp/gate2_step08b_1787113504`; durable evidence copied to
`/home/klz/Data/SIDEREIS_DATA/step08b_gate2_evidence_20260818/` (record JSON,
`health_checks_effective.yaml`, `run_invariants_lock.json`, the TIDMAD task
config, full chain log). `CHAIN_RC=0` — **and the verdict below comes from the
persisted record, not from that exit code.** Wall time ≈ 12 min end to end
(training 1:47, six real inference files, scoring, gates), inside the ≤20 min
hard stop.

**The run was counterfactual-discriminative, which is what makes it
evidence.** The real LLM's candidate (`bidir_spectral_gated_tcn_coldstart`)
trained for real — Epoch 0, avg loss 3.207, validation loss 4.583 over 15 000
ML segments — and then genuinely collapsed: **5 unique int8 values** against a
`>25` threshold, and **0.365 mV std** against a `>=1.0 mV` floor. So the gates
had something real to object to, and they were not uniformly failing either —
`amplitude_collapse` PASSED at 0.715–0.720 dominant fraction against its 0.95
threshold.

**1. Startup composition — the roster came from the task config.**

```text
{workspace}/health_checks_effective.yaml
  top-level keys      : ['health_gates', 'task_health_binding']
  task_health_binding : legacy_default          <-- composed, not read from the framework file
  gate ids            : output_diversity_blocking, output_std_blocking,
                        amplitude_collapse_blocking, pearson_dispersion_recording,
                        spectral_peak_ratio_recording, per_file_output_std_recording
run_invariants_lock.json
  health_config_sha256: abced73458b130968d7b0363fff7f4ad4ca21fb105fae18f8d079e557466629b
                        == the artifact's own header sha
```

**2. The value scale was injected into EXACTLY the four checks that declare
the axis**, and into no others:

| gate | check config keys |
|---|---|
| `output_diversity_blocking` | `aggregation`, `min_unique_int8_values`, `peek_file_indices`, `peek_samples` |
| `output_std_blocking` | … + **`value_scale_unit`, `value_scale_units_per_sample`** |
| `amplitude_collapse_blocking` | `aggregation`, `collapse_threshold`, `peek_file_indices`, `peek_samples` |
| the three recording gates | … + **`value_scale_unit`, `value_scale_units_per_sample`** |

**3. Six gates fired; the verdict union is exactly `{passed, failed}` — NO
`inapplicable`**, which is the decisive C5 parity claim:

| gate | execution_status | resolved_action | check_verdicts |
|---|---|---|---|
| `output_diversity_blocking` | failed | `invalidate_round` | `{output_diversity: failed}` |
| `output_std_blocking` | failed | `invalidate_round` | `{output_std: failed}` |
| `amplitude_collapse_blocking` | passed | `continue` | `{amplitude_collapse: passed}` |
| `pearson_dispersion_recording` | passed | `continue` | `{pearson_dispersion: passed}` |
| `spectral_peak_ratio_recording` | passed | `continue` | `{spectral_peak_ratio: passed}` |
| `per_file_output_std_recording` | passed | `continue` | `{per_file_output_std: passed}` |

Record `bidir_spectral_gated_tcn_coldstart_iter_001_001`,
`status=failed_mode_collapse`, `is_trial=True`,
`denoising_score=-0.5606766386932958`.

**4. The migrated scale is NUMERICALLY correct, not merely present.**
`output_std` persisted `output_std_mv = 0.36498…0.36585` with
`unit: "mV"` across all six files, and `per_file_output_std` the same values.
Cross-check: 5 unique int8 values give a std of ≈1.17 LSB, and
1.17 × (40/128) = **0.365 mV** — the migrated factor exactly. A wrong factor
would have moved these by orders of magnitude; a MISSING one would have
raised `KeyError` and produced `error` verdicts. Thresholds persisted at their
pre-migration values (`25`, `1.0` mV, `0.95`), and all six checks read files
4–9 via `channel0001_prefix_peek` with `aggregation: any_pass` on the three
blocking gates.

Every expected-PASS item in the specification above is satisfied, and no
expected-FAIL or INCONCLUSIVE mode occurred.

---

## 11. Cross-task compatibility audit — Pets / DAVIS

**Operator-directed, 2026-08-18, before C7 / closeout.** Purpose: prove the
Step-08b generic Health refactor did not silently regress the two existing
non-TIDMAD executable tracks D14 established. **NOT authorization to
implement their Step-08c Health families**, and none were implemented.

### The hazard being audited

C5 made an OMITTED `task_health_binding` resolve to the legacy default —
TIDMAD's task-owned config. A pre-existing non-TIDMAD runner that predates
that argument could therefore inherit another task's Health semantics without
saying anything.

### 1. Binding state — VERDICT: **NOT A BLOCKER**, proven structurally

Neither task reaches the fallback, and not because it opts out: **neither
runner enters the Health composition path at all.**

```text
legacy-omitted -> TIDMAD  lives in  materialize_effective_config
                                      ^ ONE production caller:
                                        core/run_invariants.py:380 (build_run_invariants)
                                          ^ FOUR callers:
                                            scripts/run_comparison.py:1221
                                            nodes/ml_hyperparameter_tune_agent/…:576
                                            workflows/model_exploration.py:1845
                                            sdsc_submission_scripts/run_one_iteration.py:1446
```

`scripts/run_pets_gate2.py` and `scripts/run_davis_gate2.py` are
direct-execution harnesses — task data path → training engine → metric. Their
complete SIDERIUS import sets (AST-extracted) are:

```text
agent.schemas.model_io_contract · execute_tools.evaluation_metric
execute_tools.{pets,davis}_data_path · execute_tools.task_data_path
execute_tools.train_engine_sandbox · ml_models.models_format_sandbox
ml_models.models_sandbox
```

None is a `build_run_invariants` caller, and grep confirms **zero**
references to `health_checks`, `materialize_effective_config` or
`build_run_invariants` in either runner — nor in
`train_engine_sandbox.py`, `evaluation_metric.py`, `task_data_path.py`,
`pets_data_path.py` or `davis_data_path.py`. The fallback is therefore
**structurally unreachable** for both.

**No correction was required, and none was made.** Making a change for its
own sake would have been worse than none: it would suggest the runners
participate in a subsystem they do not.

### 2. Existing-task regression evidence — GREEN

Ran the existing D14 owners rather than building a parallel suite:
`tests/unit/examples/` · `test_accuracy_metric.py` ·
`test_global_mse_metric.py` · `test_pets_data_path.py` ·
`test_davis_data_path.py` · `test_davis_clip_rule.py` ·
`tests/unit/guardrails/` — **325 passed, rc=0**. No real training, no Gate.

### 3. D18 against the REAL non-TIDMAD metrics — and a FINDING

Source-inspected rather than assumed, as instructed:

| metric | `_compute` returns | statement |
|---|---|---|
| `AccuracyMetric` (Pets) | `(correct/len(truth), None, ())` | `SCALAR_ONLY` |
| `GlobalMseMetric` (DAVIS) | `(sq_err_sum/element_count, None, ())` | `SCALAR_ONLY` |
| `TidmadDenoisingMetric` | `(scalar, file_vector, ("anchor_map",))` | `AVAILABLE` |

**FINDING: DAVIS is scalar-only too.** The Step-08b design recorded this only
for Pets (§2.6). In fact **two of the three executable tracks carry no
per-sample evidence, and only TIDMAD does** — which makes D18 more
load-bearing than the design claimed, not less. Pinned now against the real
implementations, with TIDMAD's shape as the positive control so a bridge that
reported `SCALAR_ONLY` unconditionally would not pass.

Invariant 16 re-asserted across every registered check: none reads
`denoising_score` or `.scalar`.

### 4. Example synchronization

Both packs' `STATUS.md` carried a now-stale row claiming
`configs/health_checks.yaml` is "TIDMAD-shaped policy". Corrected to state the
honest current position: the framework file is policy-only since 08b; the pack
has **explicitly no Health binding** and cannot inherit TIDMAD's; its metric is
scalar-only; and a task-owned Health family is **Step 08c**. No `.py`, no
Health config and no 08c content added — the D14 invariant that production
carries zero dependency on `examples/` is untouched.

### 5. New regression

ONE narrow file: `tests/unit/guardrails/test_step08b_cross_task_compatibility.py`
(**17 cases**) — binding-state unreachability (with an anti-vacuity probe that
the same AST walk DOES detect a real Health importer), the `EXPLICIT_NONE`
forward guarantee paired against the omitted state so the distinction is not
decoration, D18 against both real metrics with TIDMAD as positive control,
invariant 16, and a no-task-name-branch census.

It does **not** replace C7: C7 proves a NEW external task can EXTEND the seam
with no infra edit; this proves the two EXISTING tasks did not silently
ACQUIRE TIDMAD's semantics. Different failure classes.

### Summary

| item | result |
|---|---|
| Pets binding state | never enters Health composition — cannot inherit TIDMAD |
| DAVIS binding state | same |
| correction required | **no** |
| existing D14 owners | 325 passed, rc=0 |
| D18 real-metric evidence | Pets SCALAR_ONLY, DAVIS SCALAR_ONLY (finding), TIDMAD AVAILABLE |
| example status sync | both packs corrected |
| Step-08c Health semantics implemented | **none** |

