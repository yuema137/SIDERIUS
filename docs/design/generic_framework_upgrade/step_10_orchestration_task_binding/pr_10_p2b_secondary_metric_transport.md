# Step 10 / P2b — Secondary Metric Production Transport

## 0. Status

**REVISION 3 — FROZEN. OPERATOR APPROVED (2026-08-21).
Open operator questions: 0. Material contradictions: 0.**

**IMPLEMENTATION COMPLETE — C0-C4 landed; READY FOR OPERATOR REVIEW, DO NOT
MERGE.** The frozen semantic rulings below are UNCHANGED; the live
implementation ledger is **§15**, which records the source preflight, the
guard-disposition closure, per-commit evidence, four IR-P2b rulings, two
bounded deviations, four findings and the CI provenance. Gate 1 and Gate 2
were NOT REQUIRED and were NOT RUN; no real LLM, training or GPU work was
performed.

Revision 3 is rev 2 (the post-P2a/P4 reconciliation, architecture review
verdict **PASS**) plus the operator's freeze rulings and two bounded
boundary corrections — no child redesign:

* **Q-P2b-1 = WHEREVER_PRIMARY_EVALUATES**, **Q-P2b-2 RESOLVED with the
  scope-violation exception-order correction**, **Q-P2b-3 =
  _STATS_SUFFICIENT with the ownership-wording correction** — full rulings
  in §14;
* **C-P2b-1**: the zero-secondary serialization contract is now
  SOURCE-GROUNDED (§4.7) — semantic emptiness is frozen, not persisted-JSON
  byte identity, because the measured output path (`model_dump()` with no
  exclude flags, `records.py:957`) serializes default-empty fields;
* the false default-ownership claim "digest widening is P5 territory" is
  removed (§14 Q-P2b-3 carries the corrected wording).

Rev 2's own summary, preserved: every `PROVISIONAL(P1)` / `PROVISIONAL(P2a)`
marker resolved against MERGED source, all line anchors re-measured, the §6
commit decomposition in full eight-section per-commit plans with all-`[ ]`
checklists, and the Q-P2b-2 taxonomy audit performed (§2.6).

| field | value |
|---|---|
| parent | Step-10 parent REVISION 2 (frozen), §3.4 / §9 / §9.4; owns scope item **S3** |
| source anchor | merged `master` = **`96dc1327`** (production tree identical to the P2a squash `e094fa26`). Contains P1 `bcb17e45` + P4 `79833db8` + P2a `e094fa26`. Line anchors are evidence, not implementation authority |
| depends on | **P1 MERGED** (the composition edge C1 extends), **P2a MERGED** (ordering is closed, so nothing here migrates or duplicates it — parent §9.4 item 8). **P4 MERGED with ZERO production-file overlap with P2b's touch set** (measured §2.7) — a sequencing fact, not a dependency edge |
| Gate disposition | **FROZEN (operator ruling 2026-08-21): Gate 1 NOT REQUIRED · Gate 2 NOT REQUIRED.** Deterministic composition/evaluation/transport/projection; the 09b renderer's semantics are reused unchanged (Gate-1-validated in 09b); TIDMAD prompt bytes have a deterministic parity owner (§5); `StubSandbox` exercises the real evaluation call shape. No real LLM/training/GPU may be run for P2b; a newly discovered non-deterministic failure class is a MATERIAL DEVIATION, never an autonomously invented Gate |
| open operator questions | **0** — Q-P2b-1 / Q-P2b-2 / Q-P2b-3 all RESOLVED by operator ruling 2026-08-21 (§14) |

**Frozen in this draft regardless of upstream shape** (operator §15,
unchanged from rev 1): the declaration/binding concept, the result/refusal
lifecycle, persistence, interpretation availability, the observational-only
rule, and the three-task behaviour.

### 0.1 Rev-2 reconciliation deltas (every change from rev 1, so review is a diff of intents)

| # | rev 1 said | rev 2 says | why (source) |
|---|---|---|---|
| D1 | §4.3: record carrier = ONE list of typed entries each holding spec + result-or-refusal; output stamp `PROVISIONAL(P1)` | **THREE additive fields, exactly the names the receiving side itself reserves**: `ExperimentRecord.secondary_metric_results`, `ExperimentRecord.secondary_metric_refusals`, `HyperparamTuningOutput.secondary_metric_specs` | `agent/schemas/interpretation.py:129-134` (the 09a `SecondaryMetricEvidence` docstring) names all three verbatim as "Step 10's". Rev 1 had only found the `evidence.py` comment naming the first. The receiving side's own reservation outranks rev 1's invented single-list shape, and the pair mirrors the primary's `metric_result`/`metric_refusal` split (`hyperparam_tuning.py:659/:674`) |
| D2 | §4.1 binding mechanism unspecified (`PROVISIONAL(P1)`) | secondaries ride `RunTaskComposition` additively and are activated by a `bind_run_secondary_metrics` ContextVar entered in `bind_run_task_composition`'s existing `ExitStack`, resolved in the tuner beside `resolve_bound_run_metric()` | the primary's own idiom, measured: `task_composition.py:931-936` binds four families by ContextVar; the tuner acquires at `ml_hyperparameter_tune_agent.py:548`. Consumed at the same site ⇒ same idiom (the module's own rule at `:915-920`: explicit-path values stay explicit; tuner-acquired values are ContextVar-bound) |
| D3 | fingerprint impact unaddressed | **additive-when-nonempty fingerprint rule**: the `secondary_metric_declarations` key joins the `compute_semantic_fingerprint` payload ONLY when at least one secondary is declared | `task_composition.py:712-764`; adding an always-present key would move EVERY existing composed run's sha and fail their resumes for a non-scientific reason — exactly what Q-P1-2's path-exclusion rule exists to prevent, and the same idiom as the run-invariants "key ABSENT for legacy" |
| D4 | Q-P2b-2 wholly open; taxonomy audit owed | audit PERFORMED (§2.6): the existing taxonomy already distinguishes *scientific refusal* (`failure_type="not_scoreable"`) from *scoring crash* (generic narrative) at `records.py:592-623`; §12 proposes the per-secondary mirror | operator ruling 2026-08-20 required the audit before freeze; done at this anchor |
| D5 | C0's disposition table named "the 09a-C6 emptiness tests" loosely | the table's subjects are now NAMED: `TestQ097StaysBinding`'s three guards (`test_step09a_c6_evidence_projection.py:509/:514/:518`) plus the builder-emptiness assertions and the fabricated-`secondary_metric_results` ignore-test at `:372-379` | measured; the three Q097 guards are DESIGNED to turn red when Step 10 lands and must be retired by INVERSION in the same commits that trip them, per the repository's census-retirement convention |
| D6 | §2 anchors at `2393aacc` | all anchors re-measured at `96dc1327` | three merges landed in between |
| D7 | commit plans were terse bullet lists | full eight-section per-commit plans, all-`[ ]` | the Step-10 standard (P2a rev 2 set the precedent) |

None of D1–D7 changes a frozen rev-1 concept; D1–D3 make rev-1 intents
concrete against source that now exists, D4 discharges an operator-imposed
pre-freeze obligation, D5–D7 are measurement and form.

---

## 1. Parent contract (recovered, binding)

* **§9.1 (frozen ordering rule)**: secondaries are observational and NEVER
  select the primary winner — not incumbent, not active-model selection, not
  cache capping, not prediction default/evaluation. Step 09a's executable
  invariant (no ordering expression takes a secondary as operand) stays green
  **after** values become real.
* **§9.2 lifecycle**: declaration → run-scoped binding → evaluation → record
  transport → persistence/cache carry (symmetric with `failure_counts` from
  the first commit — audit B-6) → interpretation availability → named
  absence/refusal.
* **§9.4 item 8**: P2b introduces **no second metric-order authority** and
  re-migrates **no** P2a site.
* **Q-10-4 = A**: `_is_loss_shaped` unchanged; Pets contributes `macro_f1`
  and only `macro_f1`; `log_loss` stays D16 (Step-06-owned), documented, not
  deleted.
* Q-09-7 = B history: the receiving side was deliberately built empty —
  activation must not reinterpret it.

---

## 2. Current source audit (RE-MEASURED at merged `96dc1327`)

### 2.1 The receiving side — complete, frozen, empty (anchors moved, shape unchanged)

* `SecondaryMetricEvidence` (`agent/schemas/interpretation.py:114-165`):
  `spec` (its OWN direction, `MetricSpecField`) + mutually exclusive
  `result`/`refusal` (validator `:149-156`), `status` property
  `∈ {scored, refused, unavailable}` (`:158-165`).
  **Its docstring `:129-134` reserves the three Step-10 field names verbatim**:
  `ExperimentRecord.secondary_metric_results`, `secondary_metric_refusals`,
  `HyperparamTuningOutput.secondary_metric_specs` (delta D1).
* Transport: `ModelRunSummary.secondary_metrics` (`:561`),
  `InterpretationOutput.per_model_secondary_metrics` (`:1272`).
* Rendering: `render_secondary_metrics`
  (`agent/prompt_templates/interpretation/rendering.py:298`, sole caller
  `:539`) — handles all three states, landed and Gate-1-validated in 09b.
* Producer hardcode: `nodes/result_interpretation_agent/evidence.py:479`
  `secondary_metrics=[]` (moved from `:486` — P2a's reconciliation
  promotion shrank the file by 7 lines).

### 2.2 The cache-carry asymmetry (audit B-6) — re-located, unchanged

`nodes/result_interpretation_agent/result_interpretation_agent.py`:
`per_model_failure_counts` is built from `inp.summaries` (`:348-352`) **and**
back-filled from the `_stats` cache (`:354-358`) because `failure_counts` is
written into `_stats` at `:526-528`. `per_model_secondary_metrics`
(`:361-364`) still has **neither half**. The Stability-Filter reuse path (no
LLM call) is the path that loses them. P2a and P4 did not touch this file;
the B-6 finding stands byte-for-byte.

### 2.3 The composition edge (P1, MERGED — C1's exact surface)

`workflows/task_composition.py` (982 lines):

* `RunTaskComposition` (`:166`) — frozen slotted dataclass; fields incl.
  `metric: EvaluationMetric`, `semantic_fingerprint`, `provenance`; the
  `__post_init__` guard refuses ChainState-named fields by derived name set.
* Manifest reader `_read_manifest` (`:249`): **unknown keys are REFUSED**
  against `_MANIFEST_KEYS` (`:93-102`) — so `secondary_metrics:` cannot be
  smuggled today, and C1 must extend `_MANIFEST_KEYS` (NOT `_REQUIRED_KEYS`
  `:109-111`: a task with no secondaries states nothing, like rev 1 froze).
* `_compose_metric(section, manifest_dir)` (`:537-592`) is the complete
  declaration-ref + implementation-ref → validated `EvaluationMetric`
  pipeline (spec via `metric_spec_from_declaration`, the ONE authority;
  instantiation; `EvaluationMetric` isinstance check; spec-id identity
  check). **It is reusable per secondary entry as-is** — C1 calls it in a
  loop rather than duplicating any of its five fail-closed branches.
* `compute_semantic_fingerprint` (`:712-764`) — payload includes
  `metric_declaration` (the raw declaration dict) and plugin content
  digests; machine-local paths excluded (Q-P1-2). Delta D3's
  additive-when-nonempty rule lives here.
* `compose_run_task_bindings` (`:772-874`) — assembles sections, collects
  `plugins` and `source_paths` provenance; C1 inserts the secondary loop
  beside the `metric` section handling (`:820-826`).
* `bind_run_task_composition` (`:895-936`) — the run-scoped `ExitStack`
  entering `bind_task_data_path` / `bind_dataset_profile` /
  `bind_run_metric` / `bind_task_config` (`:931-936`); `None` composition =
  no-op. The module's own placement rule (`:915-920`): ContextVar only for
  values without an explicit path. Delta D2's `bind_run_secondary_metrics`
  enters this stack.
* Fixture manifests exist for all four tasks
  (`tests/fixtures/step10_p1/{tidmad,pets,davis,fourth_task}/composition.yaml`)
  — C1's three-task composition fixtures extend these, not new worlds.

### 2.4 The evaluation point and the record (C2's exact surface)

* The tuner acquires its metric ONCE:
  `run_metric: EvaluationMetric = resolve_bound_run_metric() or
  derive_tidmad_metric(...)` (`ml_hyperparameter_tune_agent.py:548`);
  `run_order = MetricOrder(run_metric.spec)` (`:561`); `RunBindings` carries
  `run_metric` (`contracts.py:116`).
* The ONE scoring route: `sandbox.evaluate_metric(run_metric, sample_set,
  anchor_map, s_max, denoised_filename_fn)` at `execution.py:882-888`,
  inside the V8-Domain-2a `try` (`:843`) whose handlers are
  `ScopeViolationError` → end round (`:1016-1022`) and generic `Exception` →
  `_build_scoring_failure_record` → `error_scoring` record → next attempt
  (`:1023-1049`). The block runs for **both trial and formal** modes
  (`:845-846`) — the measured fact behind the Q-P2b-1 ruling
  (`WHEREVER_PRIMARY_EVALUATES`, §14.1).
* The `_denoised_fn` closure (`:860-874`) resolves deliverable paths; a
  secondary evaluates the SAME deliverables through the SAME closure.
* `TidmadSandbox.evaluate_metric` (`core/sandbox_executor.py:1940`) runs
  DataScope validation → scoreability → arithmetic; `StubSandbox
  .evaluate_metric` (`:2366`) mirrors it in pseudo mode, synthesising values
  under the handle's REAL identity — so C2's pseudo tests exercise the real
  call shape with zero GPU.
* `ExperimentRecord` (`hyperparam_tuning.py:298`) carries the primary pair
  `metric_result` (`:659`) / `metric_refusal` (`:674`) with the frozen-name
  consistency validator; `HyperparamTuningOutput.metric_spec` stamp at
  `:3023` (09a) — the precedent D1's output stamp mirrors.

### 2.5 What P2a landed that P2b consumes (and must not duplicate)

* The ordering surface is **0 sites / 308 production files**; P2a's scanner
  (`tests/unit/execute_tools/test_step10_p2a_c0_ordering_scanner.py`) is the
  standing guard over GOLDEN-score names. Secondary ids (`macro_f1`, `psnr`,
  `mae`) are not golden names, so the scanner ignores them **by
  construction**; the guard on the secondary side is the 09a
  ordering-operand invariant (§2.8), NOT a scanner extension. P2b's
  standing-guard obligation to the scanner is only: introduce **no new
  golden-score carrier shape** (it doesn't — secondaries never carry
  `denoising_score`).
* `reconcile_metric_specs` / `reconcile_metric_identity` /
  `MetricIdentityKey` / `metric_identity_from_mapping` and the canonical
  `METRIC_IDENTITY_UNAVAILABLE` formatter live in
  `execute_tools/evaluation_metric.py`. **P2b needs none of them for
  ordering** (secondaries are never ranked); the projection reads each
  entry's own spec. P2b must NOT add a second reconciliation or a secondary
  "order".
* `bind_run_metric` / `resolve_bound_run_metric`
  (`evaluation_metric.py:1080/:1102` — P2a's additions moved them) — the
  ContextVar pair
  `bind_run_secondary_metrics` mirrors, in the same module, beside the
  primary's.

### 2.6 The Q-P2b-2 taxonomy audit (operator-required before freeze) — PERFORMED

The existing scorer/error taxonomy at the scoring point, measured:

| class | primary's existing handling | source |
|---|---|---|
| **scientific refusal** — deliverable fails the scoreability contract | `NotScoreableError` raised by the handle → caught by the scoring `except` → `error_scoring` record with `failure_type="not_scoreable"` + the structured `metric_refusal`, requirements named one by one | `evaluation_metric.py:453-475`; `records.py:592-615` |
| **implementation/runtime crash** — anything else raised during scoring | same `except Exception` → `error_scoring` record with a "Scoring crashed: {type}: {msg}" narrative; NO structured metric payload, NOT coerced into a refusal | `records.py:616-623`; `execution.py:1023-1049` |
| **scope violation** | `ScopeViolationError` → terminate the run (non-retryable) | `execution.py:1016-1022` |

**Conclusion the audit supports**: the taxonomy ALREADY keeps *scientific
refusal* and *implementation crash* distinct for the primary, at the record
level, without inventing a third metric-payload state. The per-secondary
mirror is now RULED (operator 2026-08-21, §14 Q-P2b-2): a secondary
`NotScoreableError` → that secondary's typed `refusal` entry; a secondary
CRASH → an additive `secondary_metric_errors: dict[metric_id, str]` on the
record (non-silent: persisted + emitted on the diagnostic surface), which
the interpreter projects as `unavailable` — the frozen three-state carrier
is untouched, and no crash is ever dressed as a scientific refusal.

**Scope-violation correction (operator, superseding a wrong rev-2
sentence).** Rev 2 claimed the SampleSet "is validated once, before the
primary" — the measured route says otherwise: DataScope validation runs
INSIDE every `evaluate_metric` call (`sandbox_executor.py:1940`, step 1), so
a secondary call CAN raise `ScopeViolationError`. In practice the secondary
receives the same SampleSet the primary just passed, but the CONTRACT must
still be pinned: `ScopeViolationError` is **RE-RAISED** out of the secondary
loop so the existing outer scope-violation handler (`execution.py:1016-1022`,
terminate-run, non-retryable) retains ownership. A framework-integrity
failure is NEVER downgraded into a harmless secondary error entry.

### 2.7 P4 — merged in parallel; measured relationship to P2b

`git diff --name-only 64446b2b 79833db8` ∩ P2b's planned touch set
(`task_composition.py`, `evaluation_metric.py`, `execution.py`,
`ml_hyperparameter_tune_agent.py`, `contracts.py`, `hyperparam_tuning.py`,
`interpretation.py`, `evidence.py`, `result_interpretation_agent.py`,
`rendering.py`, `sandbox_executor.py`) = **∅**. P4's surface is Health
declarations (`execute_tools/health_checks/*`, `agent/schemas/
health_feedback.py`, `evaluation.py`); P2b touches none of it and consumes
none of its new API. P4 is a **sequencing fact recorded for the rebase
base**, not a dependency edge — exactly as P4's own design predicted for its
P2a adjacency.

### 2.8 The guards P2b must deliberately turn red (and how they retire)

`tests/unit/agent/result_interpretation_agent/test_step09a_c6_evidence_projection.py`:

| guard | what it pins today | P2b disposition (C0 table finalizes) |
|---|---|---|
| `TestQ097StaysBinding::test_no_secondary_field_was_added_to_the_record_schema` (`:509`) | `ExperimentRecord` has no `secondary_*` field | INVERT in the commit that adds the fields (C2): the record MUST now carry exactly the reserved names |
| `::test_no_secondary_field_was_added_to_the_tuning_output` (`:514`) | `HyperparamTuningOutput` has no `secondary_*` field | INVERT in C2 for `secondary_metric_specs` |
| `::test_no_production_module_evaluates_a_secondary_metric` (`:518-531`, regex over evaluator/loader/binder names) | no production secondary evaluator exists | INVERT in C1 (binder) / C2 (evaluator): the named functions MUST exist, in the named owners, and nowhere else |
| builder-emptiness assertions + the fabricated-`secondary_metric_results` ignore-test (`:372-379`) | the builder leaves `secondary_metrics=[]` and reads no undeclared record keys | REWRITE emptiness into projection-correctness (C3); **KEEP** the ignore-undeclared-keys mutation with the fabricated payload updated to a key that remains undeclared |
| ordering-operand invariant (`:440-475`) + flip test (`:476`) | no ordering expression takes a secondary operand; flipping secondary values changes no ordering output | KEEP, scope EXTENDED to P2b's new production surfaces (C0 declares, C4 proves) |

### 2.9 What the tasks declare (verified on disk)

| task | declared secondary files | note |
|---|---|---|
| TIDMAD | none | absence is a supported, first-class state |
| Pets | `examples/oxford_iiit_pet/declared/metric_macro_f1.json` (**higher**) | `log_loss` intentionally NOT declarable (D16) |
| DAVIS | `declared/metric_psnr.json` (**higher**, `transform: psnr_db`, `data_range: 1.0`), `declared/metric_mae.json` (**lower**) | the mixed-direction control beside the `lower` `mse` primary; both use `deliverable_presence` scoreability |

Nothing in a pack marks primary vs secondary — the **manifest** names the
relation (§4.1), exactly as it already names the primary.

---

## 3. Goal / semantic owner / scope

**One semantic owner: observational secondary-metric evidence, production
lifecycle end-to-end.** After P2b: a task's composition manifest declares its
secondaries; the run binds them beside the primary; the tuner evaluates them
at the same scoring point; records carry typed results/refusals under the
receiving side's reserved names; the interpreter projects them, carries them
across quiet iterations symmetrically with `failure_counts`, and renders
them; a declared-but-unevaluated secondary is a **named absence**; and none
of it can influence any ordering decision.

**Non-goals**: any ordering semantics (P2a closed them; nothing here re-opens
or duplicates a site); any new rendering design (09b's renderer reused
as-is); D16/`log_loss`; secondary-metric *history* beyond the existing
cache-carry shape; dashboards (secondaries are interpreter evidence — adding
dashboard rows is future scope); P3's typed reader; P4's Health surface;
un-composed (legacy TIDMAD) runs, whose behaviour stays byte-identical.

### 3.1 Structure preflight (parent §19.3 — BINDING, frozen with this revision)

Measured sizes of every file P2b grows, with the boundary each change must
respect (the operator's standing rule: no few-hundred-line functions, no
few-thousand-line files, no test redundancy on top of the deterministic
owners):

| file | today | P2b delta | boundary |
|---|---|---|---|
| `workflows/task_composition.py` | 982 lines | `_compose_secondary_metrics` loop (~40 lines) reusing `_compose_metric` verbatim; +1 manifest key; fingerprint payload branch | NO duplicated fail-closed branches — the loop CALLS `_compose_metric`; if reuse proves impossible, STOP (that is a seam defect, not a copy-paste license) |
| `nodes/ml_hyperparameter_tune_agent/execution.py` | 1,172 lines | ONE extracted helper `_evaluate_secondary_metrics(...)` called after the primary result inside the existing `try` (~30-40 lines incl. its own narrow exception capture), NOT inline growth of the 300-line scoring block | the helper is a typed, independently testable boundary (responsibility rule); `run()`/attempt control flow untouched |
| `agent/schemas/hyperparam_tuning.py` | — | 3 additive fields + 1 cross-field validator | frozen names untouched; validators additive |
| `nodes/result_interpretation_agent/evidence.py` | 481 lines | one projection function replacing the `[]` hardcode (~35 lines) | node-private; no new public export beyond what the node's `__init__` policy requires |
| `nodes/result_interpretation_agent/result_interpretation_agent.py` | — | the `_stats` write + read-back mirroring `failure_counts` (~10 lines at the two measured sites) | NO third carry representation |
| tests | — | one new module per commit family, upgrades in place for §2.8's guards | no re-testing of Pydantic declarations; no duplicate of what the invariant already owns |

### 3.2 Evidence-economy / test-ownership declaration (rule §26)

* **Static (ruff/pyright/Pydantic)** owns: field types, `extra="forbid"`,
  Literal vocabularies, the additive defaults being optional.
* **Unit** owns: composition constraints (dup-id, primary-collision,
  unknown-key), fingerprint additive-when-nonempty, evaluation capture
  semantics (refusal/crash/attempt-parity), record round-trip, projection
  four-state matrix, carry symmetry, rendering state fixtures, TIDMAD prompt
  byte-parity, the ordering-operand invariant + plants.
* **Gate 1 / Gate 2**: NOT REQUIRED — **FROZEN, §14.5** — no new LLM-facing semantics
  (renderer landed in 09b and Gate-1-validated there; TIDMAD bytes pinned);
  no new real-lifecycle timing/arrival property (transport is deterministic;
  the StubSandbox route exercises the real call shape). If implementation
  surfaces a genuinely non-deterministic failure class, that is a MATERIAL
  DEVIATION, not an autonomously invented Gate.
* **CI**: ONE automatic exact-final-head run at the true final PR head.

---

## 4. Design (PROVISIONALs resolved)

### 4.1 Declaration + binding — RESOLVED against P1's merged seam

The manifest gains an OPTIONAL `secondary_metrics` section — a **list** of
entries, each the same `{declaration, implementation}` shape the `metric`
section already uses:

```yaml
metric:
  declaration: .../metric_mse.json
  implementation: {module: execute_tools.evaluation_metric, symbol: GlobalMseMetric}
secondary_metrics:
  - declaration: .../metric_psnr.json
    implementation: {module: execute_tools.evaluation_metric, symbol: GlobalMseMetric}
  - declaration: .../metric_mae.json
    implementation: {module: execute_tools.evaluation_metric, symbol: GlobalMseMetric}
```

* `_MANIFEST_KEYS` gains `secondary_metrics`; `_REQUIRED_KEYS` does NOT — a
  task with none states nothing (TIDMAD's manifests are untouched).
* Each entry resolves through **`_compose_metric` itself**, so every
  fail-closed branch (invalid declaration, non-`EvaluationMetric`
  implementation, spec-id mismatch) is inherited, not re-implemented.
* `RunTaskComposition` gains `secondary_metrics: tuple[EvaluationMetric, ...]`
  (default `()` — legacy manifests compose to the empty state byte-identically).
* Constraints, frozen in rev 1 and kept: a secondary whose spec id equals
  the primary's fails composition; duplicate secondary ids fail composition;
  each carries its OWN direction; un-composed runs have no secondaries.
* Fingerprint (delta D3): declarations join the
  `compute_semantic_fingerprint` payload under
  `secondary_metric_declarations` **only when the tuple is non-empty**, in
  manifest order; secondary implementation plugins join `plugins` (content
  digests) exactly as the primary's does. A zero-secondary manifest's
  fingerprint is BYTE-IDENTICAL to its pre-P2b value — pinned by test.
* Binding (delta D2): `bind_run_secondary_metrics` /
  `resolve_bound_run_secondary_metrics` ContextVar pair in
  `execute_tools/evaluation_metric.py` beside the primary's pair; entered in
  `bind_run_task_composition`'s `ExitStack`; resolves to `()` when unbound.
  The tuner acquires at its existing acquisition site (`:548` region):
  `run_secondary_metrics = resolve_bound_run_secondary_metrics()` — legacy
  runs get `()`, and NOTHING derives a secondary from task identity.

### 4.2 Evaluation — beside the primary, never gating it

At the tuner's scoring point, AFTER the primary `metric_result` is produced
(inside the same `try`, via the extracted `_evaluate_secondary_metrics`
helper — §3.1):

* each bound secondary evaluates the SAME deliverables through the SAME
  `sandbox.evaluate_metric(secondary, ...)` route and the SAME
  `_denoised_fn` (scoreability contract first, then arithmetic);
* **the per-secondary exception order is FROZEN** (operator ruling
  2026-08-21, §14 Q-P2b-2 — the catch around EACH secondary call, in this
  order):

  ```text
  NotScoreableError    -> scientific refusal -> secondary_metric_refusals
                          -> attempt remains successful
  ScopeViolationError  -> RE-RAISE -> the existing OUTER handler owns it
                          (terminate run, non-retryable) -> never downgraded
                          into a secondary error
  any other Exception  -> secondary_metric_errors[metric_id] = concise
                          diagnostic -> persisted + emitted on the
                          diagnostic surface -> attempt remains successful
  ```

* crash diagnostics go to the tuner's **existing diagnostic/logging/stderr
  surface** — NEVER any stdout that carries a machine-readable contract
  (the P2a `persisted_ranking` stderr rule), and NEVER a planner/reflector
  prompt payload;
* **"observational" is a bounded claim**: ordinary secondary
  scientific/refusal/runtime outcomes cannot affect primary selection or
  the retry lifecycle; **framework-integrity failures
  (`ScopeViolationError`) retain their existing STRONGER semantics** —
  observational never means swallowed;
* the primary's own error semantics (`ScopeViolationError` → end round;
  primary exception → `error_scoring` record) are byte-untouched — the
  secondary loop runs only after a SUCCESSFUL primary result, so an
  `error_scoring` attempt carries no secondary entries by construction;
* evaluation happens **wherever the primary evaluates** — **RULED**,
  Q-P2b-1 = WHEREVER_PRIMARY_EVALUATES (§14): the scoring block already
  runs for both trial and formal modes (`execution.py:845-846`), and no
  round-type branch is added. A future secondary needing an independent
  cadence is a NEW metric-evaluation policy capability, not P2b.

### 4.3 Record + output transport — the reserved names (delta D1)

Additive, defaults empty, frozen names untouched:

* `ExperimentRecord.secondary_metric_results: list[MetricResult]` — one
  entry per scored secondary;
* `ExperimentRecord.secondary_metric_refusals: list[NotScoreableResult]` —
  one entry per refused secondary;
* `ExperimentRecord.secondary_metric_errors: dict[str, str]` (id → concise
  one-line diagnostic) — **APPROVED as ruled (§14 Q-P2b-2): diagnostic
  PROVENANCE, not scientific evidence.** It is deliberately a plain dict —
  **no `SecondaryMetricError` Pydantic model is invented** unless source
  truth during implementation PROVES the dict cannot satisfy the frozen
  contract (a material deviation, not a preference). It never becomes a
  fourth `SecondaryMetricEvidence` state; the interpreter projects a
  crashed-but-declared secondary as `unavailable`;
* a cross-field validator: no `metric_id` appears in more than one of the
  three carriers, and none duplicates within a carrier (per-secondary
  result/refusal exclusivity — the primary pair's validator idiom, per id);
* `HyperparamTuningOutput.secondary_metric_specs: list[MetricSpecField] | None`
  — the run's DECLARED set, stamped by the tuner from the bound tuple
  exactly as the 09a `metric_spec` stamp is (`:3023` precedent). `None` on
  legacy outputs and zero-secondary runs; **absent, `null` and `[]` are
  EQUIVALENT on read** (§4.7). This is §4.5's absence-detection source:
  artifact-borne, so it survives chain-subprocess restore and mixed
  legacy/new corpora — the same "consumers read what is persisted, never
  re-derive" rule P2a enforced for the primary.

### 4.4 Interpreter projection + cache-carry symmetry (B-6, same child)

* `evidence.py` replaces the `[]` hardcode (`:479`) with a projection: for
  each declared spec on the output's stamp, find its result (→ `scored`) or
  refusal (→ `refused`) on the record, else emit the spec-only evidence
  (→ `unavailable`, which also covers the crash case). Records under an
  output with NO stamp project `[]` exactly as today — degraded/legacy
  inputs have no declared set and therefore no absence rows (rev-1 rule,
  kept).
* `_stats` gains `"secondary_metrics"` written beside `failure_counts`
  (`result_interpretation_agent.py:526-528` site) and read back beside it
  (`:354-358` pattern applied at `:361-364`), so the Stability-Filter reuse
  path preserves them. One authority shape: the same typed
  model_dump/validated read-back `failure_counts` uses — explicitly NOT a
  third representation.

### 4.5 Named absence

A secondary that is **declared for the run** (present on the output's
`secondary_metric_specs` stamp) but has no evaluation for a record projects
as `status="unavailable"` with its spec — rendered as the named absence
09b's renderer already supports. No stamp ⇒ no absence rows ⇒ zero rendered
bytes (TIDMAD parity).

### 4.6 The observational invariant, kept executable

The 09a ordering-operand AST invariant (§2.8) must stay green after
activation, and its scanned-surface declaration extends to the production
files P2b touches (the tuner evaluation helper, the `_stats` carry site, the
projection). P2a's golden-score scanner is NOT extended (§2.5 — secondaries
are not golden carriers; extending it would dilute its precision contract).
Plant-and-catch: a synthetic `sorted(models, key=...secondary...)` planted
in a NEWLY-SCANNED scope must turn the invariant RED — proving the scope
extension is real, not declared.

### 4.7 Zero-secondary serialization semantics (C-P2b-1 — SOURCE-GROUNDED, FROZEN)

Rev 2 used three phrasings for the zero-secondary state ("no record field
populated / no output stamp", "additive fields with empty defaults", "empty
carriers, no stamp write difference"). The operator required the ACTUAL
persistence path to be audited before freeze, and it was:

| surface | measured behaviour | consequence |
|---|---|---|
| per-record detail + summary JSON | `LocalRecorder.save_record` is a **dict pass-through** (`json.dump(safe_record)`, `sandbox_executor.py:344-354`); the record dict is BUILT by hand in `records.py` (e.g. `"metric_result": metric_payload` at `:1122`) | a key exists iff the builder writes it — the builder writes the three secondary carriers **only when non-empty**, no serializer machinery needed |
| tuning-output artifact | the healthy path is `HyperparamTuningOutput.model_validate(dict)` then **`model_dump()` with NO exclude flags** (`records.py:957`), and the embedded `all_records` re-serialize through `ExperimentRecord` the same way | **default-empty fields WILL serialize** (`null` / `[]`) on every post-P2b output, including the records embedded in it |

**Therefore the frozen contract is SEMANTIC EMPTINESS, not persisted-JSON
byte identity** (the operator's ELSE branch): additive empty fields MAY
serialize, and are semantically equivalent to absence. **No custom
omission/serializer machinery is built to obtain cosmetic byte identity** —
no existing public byte contract requires it (the manifest's
`run_output_sha256` pins each artifact at ITS OWN commit time and old
artifacts are never rewritten; the only byte-exact stdout contract in reach,
`rebuild_per_file_best --print-only`, reads the per-file table, not
outputs).

The frozen zero-secondary / TIDMAD invariant:

```text
no secondary scientific evidence exists
secondary carriers are semantically empty
secondary_metric_specs absent, null and [] are EQUIVALENT on read
no _stats secondary key is created
the renderer emits zero secondary bytes
planner/reflector prompt bytes are unchanged
primary result / status / retry semantics are unchanged
the zero-secondary composition fingerprint is unchanged (byte-identical sha)
```

Byte-parity claims elsewhere in this design bind exactly the surfaces listed
above (prompts, fingerprint, attempt lifecycle) — never the full persisted
JSON of new artifacts.

---

## 5. Three-task acceptance

| task | required behaviour |
|---|---|
| TIDMAD | absence path per the §4.7 frozen invariant: no secondary bound, carriers semantically empty (record keys unwritten on the dict path; output stamp `None`/absent — equivalent by contract), no `_stats` key, renderer emits **zero bytes** for the section, prompts byte-identical to pre-P2b (parity sha), fingerprint byte-identical |
| Pets | `macro_f1` (higher) scored beside `accuracy`: composed → bound → evaluated → record → stamp → summary → rendered block; carry survives a quiet iteration (cache test); D16 note untouched |
| DAVIS | the discriminating case: `psnr` (**higher**) scored beside the `mse` (**lower**) primary — the carrier's own direction words rendered, proven NOT inherited from the primary (explicit assertion on rendered direction text); `mae` exercised in the **unavailable** state on at least one fixture record; a refusal fixture (contract-failing deliverable) exercises `refused` |

All three lifecycles are proven by deterministic fixtures (L1-style), not by
Gates; the DAVIS L1 fixture shape (psnr scored, mae declared-but-unavailable)
already exists and the production path must produce what it asserts (parent
§9.3).

---

## 6. Commit decomposition — FIVE commits, full plans

**Per-commit rules**: semantic commits are autonomous — inspect the diff
scope, run the cheapest authoritative targeted validation, update this
ledger, commit if coherent; pause only for a genuine material deviation or at
the terminal READY FOR OPERATOR REVIEW. Targeted suites only; ONE exact-head
CI at the final head. **Checklists start all-`[ ]`**; a `[x]` is written only
after implementation AND verification, with the evidence beside it.

**Lifecycle-evidence rule, binding for every commit below** (the analogue of
P2a's visited-sequence rule): a transport claim is validated on the **actual
projected/rendered STATE SEQUENCE** a fixture drives — which entries landed
in which carrier, which status each projected to, which bytes rendered —
never on "the field is populated" alone. And every attempt-lifecycle claim is
validated by BYTE-PARITY of the attempt's outcome (status, retry count,
record set) against the same fixture run without secondaries.

---

### C0 — guard dispositions + invariant scope baseline

**1. Goal.** Freeze, BEFORE any behaviour changes, (a) the disposition of
every test that today pins "secondaries do not exist in production" — three
of which are DESIGNED to turn red during P2b — and (b) the ordering-operand
invariant's current green state plus the declaration of the surfaces it must
grow to cover. Both belong first because every later commit is measured
against them: a guard flipped ad-hoc mid-implementation is
indistinguishable from a guard silenced, and an invariant extended after the
code exists cannot prove the extension found anything.

**2. Scope.**
* NEW: the P2b ledger's disposition table (in THIS document, §13 when it
  opens) — no test file changes yet beyond scope DECLARATION.
* `tests/unit/agent/result_interpretation_agent/test_step09a_c6_evidence_projection.py`:
  extend the invariant's scanned-surface list to name the three production
  files P2b will touch (tuner execution helper site, `_stats` carry site,
  projection site) — the files exist today, so the extension is green at
  base and the plant proves it is live.
* UNCHANGED: every production file. Zero production diff in this commit.
* Non-goal: retiring/inverting ANY §2.8 guard — each is flipped by the
  commit that trips it, citing this table.
* Depends on: nothing (first commit).

**3. Implementation plan.**
- [x] Record the §2.8 disposition table in the ledger with each guard's
      current line anchor re-verified and its flipping commit named
      (C1/C2/C3 per §2.8).
- [x] Extend the invariant's scanned-file declaration to the three P2b
      surfaces; run it green at base over the extended surface.
- [x] Plant-and-catch on the EXTENDED scope: a synthetic secondary-operand
      ordering expression planted in one newly-scanned production file turns
      the invariant RED; revert; record verbatim output.
- [x] Record the three Q097 guards green at base (they must be green NOW —
      if any is already red, STOP: the baseline is not what this design
      measured).
- [x] Record TIDMAD prompt-parity baseline: the rendered-prompt sha256 of
      the existing interpretation golden(s) that C3 must reproduce
      byte-identically.

**4. Validation plan.**
* Unit: the extended invariant module green at base; the plant RED then
  green after revert.
* Integration/pseudo: none (no behaviour change).
* Negative/invalid: the plant IS the negative case.
* Backward-compat: `git diff --stat` over production = empty, recorded.
* Real-training Gate: **NONE. Not required and must not be launched.**

**5. Acceptance criteria.**
- [x] Disposition table lists EVERY §2.8 guard with a named flipping commit;
      zero guards unaccounted.
- [x] Invariant green over the extended surface at base; plant transcript
      (RED → revert → green) recorded verbatim.
- [x] Q097 guards measured green at base. (32 passed, 1.25 s, pre-edit)
- [x] TIDMAD prompt-parity sha recorded. (§15.3 — both goldens)
- [x] Zero production files changed (`git diff --stat` recorded).

**6. Failure and edge cases.**
| case | required behaviour |
|---|---|
| a §2.8 guard is already red at base | STOP — the design's baseline is stale; re-audit before proceeding |
| the extended invariant flags an EXISTING expression | STOP and audit: either a real latent offender (a finding, filed) or a precision defect in the extension (fix the extension, never allowlist silently) |
| the plant is caught but names two sites | fix the plant to name exactly one; a multi-hit plant proves less |

**7. Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest .../test_step09a_c6_evidence_projection.py -q` — **25 passed, 1.31 s** over the extended surface (32 passed / 1.25 s with the C1a oracle at base; 33 passed / 1.36 s with the oracle after).
- [x] Plant transcript — recorded verbatim in §15.3.
- [x] `git status --porcelain` — exactly `M tests/unit/agent/result_interpretation_agent/test_step09a_c6_evidence_projection.py` plus this doc. Zero production paths.
- [x] `ruff check` + `ruff format --check` on touched files — clean.

**8. Commit boundary.** Test/docs-only; independently reviewable as "the
dispositions and the baseline". No production change, no guard flips, no
unrelated cleanup. Before committing: diff summary, staged file list, test
counts, deviations recorded here.

---

### C1 — declaration + binding (composition schema extension)

**1. Goal.** A task can DECLARE its secondaries and a run can BIND them —
the §9.2 lifecycle's first two stages — with the empty state proven
byte-identical. This is one commit because declaration without binding is
unreachable dead schema, and binding without the manifest key has nothing to
bind; splitting them would leave an intermediate head where a manifest key
exists that no run can activate.

**2. Scope.**
* `workflows/task_composition.py`: `_MANIFEST_KEYS` + a
  `_compose_secondary_metrics` loop reusing `_compose_metric`; the §4.1
  constraints; `RunTaskComposition.secondary_metrics` (default `()`);
  fingerprint additive-when-nonempty; provenance `source_paths` entries;
  `bind_run_task_composition` enters the new binding.
* `execute_tools/evaluation_metric.py`: `bind_run_secondary_metrics` /
  `resolve_bound_run_secondary_metrics` beside the primary pair.
* Fixture manifests: `tests/fixtures/step10_p1/pets/composition.yaml` gains
  its one secondary; `davis/...` gains its two; `tidmad/...` untouched.
* UNCHANGED: every consumer of `RunTaskComposition`'s existing fields; the
  tuner (C2's); `_REQUIRED_KEYS`; all legacy/un-composed behaviour.
* Depends on: C0 (dispositions; this commit flips the BINDER third of the
  Q097 evaluator/binder guard — §2.8 row 3 names it).

**3. Implementation plan.**
- [x] Re-read `_compose_metric` and `_read_manifest` at head before
      editing; extended `_MANIFEST_KEYS` (7 keys). `_REQUIRED_KEYS`
      unchanged, with the reason recorded at its declaration.
- [x] Implement `_compose_secondary_metrics`: list-shaped section
      validation, per-entry `_compose_metric` call, duplicate-id and
      primary-id-collision refusals (`TaskCompositionError`, message naming
      the colliding id and both roles), plugin + source-path collection.
- [x] `RunTaskComposition.secondary_metrics: tuple[EvaluationMetric, ...] = ()`
      (verify the `__post_init__` derived-name guard needs no change).
- [x] Fingerprint: append `secondary_metric_declarations` (manifest-order
      list of raw declaration dicts) to the payload ONLY when non-empty;
      secondary plugins join `plugins`.
- [x] ContextVar pair in `evaluation_metric.py`, mirroring
      `bind_run_metric`'s shape; enter it in `bind_run_task_composition`'s
      `ExitStack`; `resolve_...` returns `()` when unbound.
- [x] Update the Pets/DAVIS fixture manifests; TIDMAD untouched (and
      `fourth_task` untouched — a second zero-secondary control).
- [x] Flip the Q097 binder guard per the C0 table: the binder now EXISTS in
      its named owner and nowhere else (inverted assertion), citing this
      commit.

**4. Validation plan.**
* Unit: composition of all four fixture manifests — TIDMAD `()` /
  Pets 1 / DAVIS 2 with per-entry spec ids + directions asserted as
  literals; duplicate-id refusal; primary-collision refusal; a list entry
  missing `implementation` refuses via the inherited `_compose_metric`
  branch (proving reuse, not reimplementation).
* Unit: fingerprint — zero-secondary manifest sha BYTE-IDENTICAL to its
  recorded pre-P2b value; adding one secondary CHANGES it; reordering two
  secondaries changes it (manifest order is semantic); same manifest at two
  absolute paths yields ONE sha (Q-P1-2 held).
* Unit: binding — inside `bind_run_task_composition`, `resolve_bound_run_
  secondary_metrics()` returns the composed tuple; outside, `()`;
  `None`-composition no-op unchanged; nested-run leak test mirrors the
  existing pair's.
* Negative/invalid: unknown manifest key still refused; `secondary_metrics:`
  as a mapping (not a list) refused with a shape-naming message.
* Backward-compat: the P1 composition test suite green unchanged; TIDMAD
  manifest composes to a `RunTaskComposition` equal to pre-P2b on every
  pre-existing field.
* Real-training Gate: **NONE.**

**5. Acceptance criteria.**
- [x] DAVIS composition carries exactly `("psnr", "mae")` with directions
      `("higher", "lower")` — opposite each other AND the `lower` primary —
      asserted as literals.
- [x] TIDMAD/zero-secondary fingerprint byte-identical to the recorded
      pre-P2b sha; the identity is asserted against the FROZEN recorded
      value, not recomputed on both sides of one run.
- [x] Both refusal constraints fire with messages naming the offending id.
- [x] The Q097 binder guard is inverted and green; the other two Q097
      guards remain green (record schema and evaluator untouched here).
- [x] `run_workflow` and the tuner are untouched — the C1 diff is exactly
      `workflows/task_composition.py`, `execute_tools/evaluation_metric.py`,
      the two fixture manifests and two test modules.

**6. Failure and edge cases.**
| case | required behaviour |
|---|---|
| secondary implementation import failure | fail composition closed (inherited `_load_symbol` branch) — the run does not start |
| secondary declaration id equals primary id | `TaskCompositionError` naming the id and both roles |
| duplicate secondary ids | `TaskCompositionError` naming the id |
| empty list (`secondary_metrics: []`) | composes to `()` — equivalent to the section being absent, fingerprint unchanged |
| legacy manifest (no key) | byte-identical composition and fingerprint |
| un-composed run | no binding entered; `resolve_...` yields `()` |

**7. Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/workflows tests/unit/agent/result_interpretation_agent -q` — **1,034 passed, 28.48 s** (the whole owning area, not a `-k` slice); the new module alone **28 passed, 1.07 s**.
- [x] The fingerprint identity/change/reorder literals — recorded in §15.4.
- [x] `ruff check` clean; `ruff format` applied to `task_composition.py`.
      pyright is NOT runnable locally (Node v10.19.0) — CI-owned, not claimed.

**8. Commit boundary.** Composition + binding + their fixtures + the ONE
guard flip this commit causes. No tuner change, no schema-record change, no
interpreter change. Diff summary, staged files, counts, deviations recorded
before committing.

---

### C2 — evaluation + record/output transport

**1. Goal.** Bound secondaries actually evaluate, and their outcomes land on
the record/output under the reserved names — the §9.2 lifecycle's stages
three and four — with the attempt lifecycle provably untouched. One commit
because an evaluator without a carrier loses evidence and a carrier without
an evaluator is dead schema; the attempt-parity claim is only falsifiable
when both exist.

**2. Scope.**
* `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py`
  (`:548` region): acquire `run_secondary_metrics` beside `run_metric`;
  thread via `RunBindings` (`contracts.py`).
* `nodes/ml_hyperparameter_tune_agent/execution.py`: the extracted
  `_evaluate_secondary_metrics` helper called after the primary result
  (§3.1 boundary); population of the record payload; output stamping at the
  output-build site.
* `agent/schemas/hyperparam_tuning.py`: the three reserved fields + the
  crash carrier per the ratified Q-P2b-2 disposition + the per-id
  exclusivity validator (§4.3).
* UNCHANGED: primary scoring call, its `try/except` semantics, retry/round
  control flow, every frozen record name, HealthGate evaluation, prompts
  (the planner/reflector serializations must not gain the new keys — same
  hidden-keys mechanism the primary payload uses, verified not assumed).
* Depends on: C1 (the bound tuple); C0 (disposition table — this commit
  flips the two schema guards and the evaluator third of the Q097 guard).

**3. Implementation plan.**
- [x] Re-read the scoring block and the record/output build sites at head;
      verify where `metric_payload` enters the record and where
      `metric_spec` is stamped, and mirror both.
- [x] Schema first: the three additive fields + crash carrier + per-id
      exclusivity validator; round-trip verified before any tuner change.
- [x] `_evaluate_secondary_metrics(sandbox, secondaries, sample_set,
      anchor_map, s_max, denoised_fn) -> (results, refusals, errors)` —
      per-secondary catch in the FROZEN §4.2 order: `NotScoreableError` →
      refusal entry; `ScopeViolationError` → RE-RAISE (the outer handler
      owns it); any other `Exception` → error entry, emitted on the
      diagnostic surface, never raised onward. Returns typed lists.
- [x] Call it ONLY on the primary-success path; populate the record payload
      beside `metric_payload`; stamp `secondary_metric_specs` from the bound
      tuple beside the `metric_spec` stamp.
- [x] Verify the planner/reflector prompt serializations exclude the new
      keys (inspect the actual hidden-keys mechanism; add the keys to it if
      it is enumerated, and TEST the exclusion either way).
- [x] StubSandbox route: confirmed `StubSandbox.evaluate_metric` synthesises
      per-secondary results under each secondary's identity (it takes the
      metric argument — verify, and extend the stub minimally ONLY if
      measurement shows it collapses identities).
- [x] Flip the two Q097 schema guards + the evaluator guard per the C0
      table, citing this commit. G5 was also re-pointed here rather than in
      C3 — see the deviation note in §15.9.

**4. Validation plan.**
* Unit: schema round-trip (record with results+refusals+errors persists and
  re-validates); per-id exclusivity validator (same id in two carriers
  refused; duplicate within one carrier refused).
* Integration/pseudo: a pseudo-mode tuner round with DAVIS-shaped bindings —
  the record carries psnr scored / mae per its fixture state; the output
  carries the two-spec stamp; state sequence asserted per the
  lifecycle-evidence rule.
* Negative/invalid: a secondary whose contract refuses (fixture deliverable
  missing) → typed refusal entry, primary untouched; a secondary whose
  evaluation raises → error entry, printed, attempt outcome unchanged.
* Backward-compat / attempt-parity: the SAME fixture run with `()`
  secondaries — attempt status, retry count, record count, primary payload
  and prompt bytes ALL byte-identical to the secondaries-present run apart
  from the three new fields; and byte-identical to the pre-P2b baseline.
* Real-training Gate: **NONE.**

**5. Acceptance criteria.**
- [x] Primary result/status/retry byte-identical with and without
      secondaries on the same fixture (asserted on the attempt outcome
      tuple, not on prints).
- [x] A refused secondary yields exactly one `secondary_metric_refusals`
      entry and zero attempt-lifecycle deltas; a crashing secondary yields
      exactly one error entry and zero attempt-lifecycle deltas.
- [x] A `ScopeViolationError` raised from INSIDE a secondary call terminates
      the run through the existing outer handler (asserted on the run
      outcome), and no `secondary_metric_errors` entry exists for it.
- [x] The output stamp equals the bound declared set, in order; legacy
      outputs re-validate with the fields absent.
- [x] Planner/reflector serializations proven not to carry the new keys
      (test asserts on the serialized text, not the mechanism's docstring).
- [x] All three Q097 guards now inverted and green.

**6. Failure and edge cases.**
| case | required behaviour |
|---|---|
| primary raises (scoring crash / not-scoreable) | `error_scoring` path byte-unchanged; NO secondary evaluation runs; no secondary fields on the error record |
| scope violation raised by the PRIMARY | run termination byte-unchanged; secondaries never evaluated |
| scope violation raised INSIDE a secondary call | RE-RAISED per the frozen §4.2 order — the existing outer handler terminates the run; NEVER downgraded to a `secondary_metric_errors` entry (asserted by a fixture whose stub raises it from the secondary call) |
| every declared secondary refuses | all-refusals record; attempt success unchanged |
| secondary evaluation crash (ordinary `Exception`) | `secondary_metric_errors` entry per the §14 ruling; NEVER coerced into `NotScoreableResult`; never silent; never on a contract stdout; attempt unchanged |
| zero bound secondaries | the §4.7 frozen invariant holds: carriers semantically empty, no `_stats` key, prompts/fingerprint byte-identical; persisted default-empty fields MAY serialize and are equivalent to absence |

**7. Verification commands and evidence.**
- [x] `tests/unit/agent/tune_ml_hyperparam_agent` **1,230 passed + 4 declared-delta baseline failures, since fixed** (458 s — the tuner suite is expensive; run once). New module **21 passed, 2.6 s**. `tests/unit/agent/{schemas,prompt_templates,llm_bridge}` + planner-prompt + `tests/unit/workflows` **1,222 passed, 27.5 s**. `tests/unit/agent/result_interpretation_agent` **572 passed, 4.9 s**.
- [x] Attempt-parity byte-comparison output — recorded in §15.5.
- [x] `ruff check` + `ruff format --check` clean over the whole tree. pyright NOT runnable locally (Node v10.19.0) — CI-owned, never claimed.

**8. Commit boundary.** Evaluation + transport + the guard flips they cause.
No interpreter change, no `_stats` change, no rendering change. Diff
summary, staged files, counts, deviations recorded before committing.

---

### C3 — interpreter projection + cache-carry symmetry + rendering

**1. Goal.** The persisted evidence becomes interpreter evidence: the `[]`
hardcode is replaced by the projection, the B-6 carry asymmetry closes
symmetrically with `failure_counts`, and the four states render. One commit
because projection, carry and rendering share one consumer contract
(`SecondaryMetricEvidence`) and the quiet-iteration claim is only testable
with all three present.

**2. Scope.**
* `nodes/result_interpretation_agent/evidence.py:479`: the projection
  (§4.4) replacing `secondary_metrics=[]`.
* `nodes/result_interpretation_agent/result_interpretation_agent.py`:
  `_stats` write beside `failure_counts` (`:526-528` site) and read-back
  beside it (`:354-358` idiom at `:361-364`).
* `tests/.../test_step09a_c6_evidence_projection.py`: the C0-dispositioned
  REWRITE of the builder-emptiness assertions into projection-correctness;
  KEEP the ignore-undeclared-keys mutation (fabricated key updated to one
  that remains undeclared).
* UNCHANGED: `SecondaryMetricEvidence` itself, the renderer
  (`rendering.py:298` — reused, not modified), every ordering site, P3's
  reader surfaces.
* Depends on: C2 (real fields to project); C0 (disposition table).

**3. Implementation plan.**
- [x] Re-read the summary-build path in `evidence.py` and both `_stats`
      sites at head before editing.
- [x] Implement the projection: declared stamp × record carriers →
      scored/refused/unavailable per §4.4/§4.5; no stamp → `[]`.
- [x] `_stats["secondary_metrics"]`: typed model_dump on write, validated
      read-back on the quiet path — the `failure_counts` idiom, asserted
      to be the SAME mechanism (one test touches both keys).
- [x] Apply the C0 test dispositions; the upgraded tests land HERE, in the
      same commit as the behaviour they now assert.
- [x] TIDMAD prompt parity: the C1a oracle re-rendered green with NO golden
      regeneration; both shas byte-identical to the C0 baseline.

**4. Validation plan.**
* Unit: projection matrix — scored / refused / unavailable / no-stamp-`[]`,
  each asserted on the projected STATE SEQUENCE per model (the
  lifecycle-evidence rule), with DAVIS's mixed directions carried per-spec.
* Unit: the B-6 symmetry test — ONE fixture where a model goes quiet for an
  iteration asserts `failure_counts` AND `secondary_metrics` both survive
  the Stability-Filter reuse path, in the same assertion block.
* Integration/pseudo: an interpretation over C2-produced outputs renders
  the DAVIS block with per-metric direction words asserted (psnr "higher"
  wording beside the `lower` primary — inheritance disproven textually).
* Negative/invalid: cache entries predating the `_stats` key → read-back
  treats missing as absent, never fabricates; a corrupt `_stats` secondary
  payload → validated read-back rejects it into absence with a printed
  warning, never a crash.
* Backward-compat: TIDMAD parity sha equals the C0 baseline; the
  ignore-undeclared-keys mutation still RED-capable.
* Real-training Gate: **NONE.**

**5. Acceptance criteria.**
- [x] The quiet-iteration fixture shows secondaries surviving EXACTLY as
      long as failure counts — one fixture, both keys, one assertion block.
- [x] All four projection states asserted with hand-written expected
      literals (spec ids + statuses per model), not values read back from
      the projection.
- [x] Rendered DAVIS text contains each secondary's OWN direction words;
      an explicit assertion shows the primary's direction words absent from
      the secondary lines.
- [x] TIDMAD prompt sha byte-identical to the C0 baseline (`376f289e…` / `aa676b69…`).
- [x] The rewritten C6 tests fail if the projection is reverted to `[]` —
      mutation M7, 10 failures. Recorded in §15.6.

**6. Failure and edge cases.**
| case | required behaviour |
|---|---|
| records predating the fields under a stamped output | project as `unavailable` per declared spec (named absence) |
| output without a stamp (legacy) | `[]` — zero absence rows, zero rendered bytes |
| all declared secondaries refused | refusals rendered as refusals, never absence |
| `_stats` missing the key (pre-P2b cache) | absent, never fabricated |
| corrupt cached payload | validated read-back → absence + warning, no crash |

**7. Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/agent/result_interpretation_agent tests/unit/workflows -q` — **1,058 passed, 28.3 s**; the new module alone 18 passed / 1.2 s.
- [x] Quiet-iteration symmetry output — recorded in §15.6.
- [x] TIDMAD parity shas (C0 baseline vs C3) — IDENTICAL, both recorded in §15.6.

**8. Commit boundary.** Projection + carry + upgraded tests + parity. No
tuner change, no schema change, no renderer modification. Diff summary,
staged files, counts, deviations recorded before committing.

---

### C4 — invariant closure + three-task fixtures + docs + ledger + PR

**1. Goal.** Prove the whole §9.2 lifecycle on all three tasks at the final
head, re-prove the observational invariant over the finished surface, and
close the ledger. Separate because closure evidence at any earlier head
validates a tree that later commits change.

**2. Scope.** Three-task L1-style end-to-end fixtures (composition →
rendering); the §4.6 final plant; docs sync (any touched node/skill `.md` —
measure which exist before planning edits, per the P2a C5 precedent:
`ml_hyperparameter_tune_agent.md` documents tuner behaviour and likely needs
the secondary-evaluation paragraph; `result_interpretation_agent.md`
likewise for projection); this ledger; PR; ONE exact-head CI. No production
source beyond doc-driven comment corrections.

**3. Implementation plan.**
- [x] Three-task lifecycle fixtures per §5, each asserting the full state
      sequence (composed set → bound set → record carriers → stamp →
      projection statuses → rendered bytes/zero-bytes).
- [x] Re-run the ordering-operand invariant over the final surface; the C4
      plant is EXECUTABLE (five parametrised files P2b actually changed)
      rather than a manual transcript — recorded in §15.7.
- [x] Confirm all §2.8 guards reached their dispositioned end-state; any
      row without a citing commit ⇒ STOP (a lifecycle stage was skipped).
- [x] Docs sync with each documented behaviour quoted against merged
      source; tick every checklist item in this doc with evidence or an
      explicit not-run reason.
- [x] Push ONCE at the final head; open/update the PR; ONE automatic
      exact-final-head CI; record run id + tested SHA (in the PR body if a
      trailing docs commit would otherwise chase its own SHA — the P2a
      precedent).

**4. Validation plan.**
* Unit/integration: the three-task fixtures; the invariant + plant.
* Negative: the plant.
* Backward-compat: TIDMAD zero-byte + prompt-parity re-asserted at the
  final head.
* Real-training Gate: **NONE.**

**5. Acceptance criteria.**
- [x] All three §5 rows green with state-sequence evidence.
- [x] Invariant green over the final surface; the plant is caught in every
      one of the five files P2b changed, and the un-planted source is
      asserted clean in the same test.
- [x] Every §2.8 row closed with its citing commit (§15.2 — six of six).
- [x] Exact-head CI SUCCESS with tested SHA == final PR head, both
      recorded — run **32439134908**, tested `f6a73afd…`, PR head identical
      (§15.11).
- [x] Working tree clean; READY FOR OPERATOR REVIEW; **DO NOT MERGE**.

**6. Failure and edge cases.** A guard row with no citing commit ⇒ STOP. CI
failure ⇒ diagnose from the log, fix autonomously, push, let CI re-run
(routine, not an operator stop).

**7. Verification commands and evidence.**
- [x] The fixture + invariant modules — **10 passed, 2.4 s**; consolidated targeted run **1,871 passed, 33.9 s**.
- [x] CI run id + `headSha` — both in §15.11 and in the PR's CI-provenance
      comment.

**8. Commit boundary.** Fixtures + docs + ledger close. The last commit
before READY FOR OPERATOR REVIEW.

---

## 7. Preservation invariants

Primary scoring arithmetic, ordering, retry/round semantics, record frozen
names, prompts on secondary-less runs: byte-identical. The 09a carrier and
renderer: shape-unchanged. `_is_loss_shaped`: untouched. P2a's ordering
closure: zero sites re-opened (its scanner stays green over P2b's diff).
P4's Health surface: untouched. Zero-secondary composed manifests: same
semantic fingerprint as pre-P2b (byte-identical sha).
`ScopeViolationError`: its existing terminate-run semantics are preserved
from EVERY raise site, secondary calls included (§4.2). Byte-parity claims
bind the §4.7-listed surfaces (prompts, fingerprint, attempt lifecycle) —
zero-secondary persisted artifacts are governed by SEMANTIC emptiness, not
persisted-JSON byte identity.

## 8. Failure / edge cases (cross-commit view)

Secondary impl import failure at composition (fail closed, inherited);
secondary refusal on every record (all-refused renders refusals, not
absence); records predating the fields (absence rows only under a stamped
output); a task declaring zero secondaries (TIDMAD path — first-class);
cache entries predating the `_stats` key (missing = absent, never
fabricated); a secondary crash (typed error carrier, attempt untouched,
never dressed as scientific refusal); primary failure (no secondary
evaluation at all).

## 9. Upstream-sensitive assumptions — RESOLVED at `96dc1327`

| rev-1 assumption | resolution |
|---|---|
| `PROVISIONAL(P1)` composition schema shape / bindings spelling | measured §2.3; extension points named per site (D2, D3) |
| `PROVISIONAL(P1)` whether the output stamps the declared set | YES — `HyperparamTuningOutput.secondary_metric_specs`, the receiving side's OWN reserved name (D1), mirroring the 09a `metric_spec` stamp |
| `PROVISIONAL(P2a)` scoring call-site signature | measured §2.4 — unchanged by P2a; `evaluate_metric(metric, sample_set, anchor_map, s_max, denoised_filename_fn)` |
| `PROVISIONAL(P2a)` refusal-notice helper reuse | NOT reused — P2a's formatter is for UNRANKABLE states; a secondary refusal is a typed `NotScoreableResult`, already self-describing. No new dependency |
| §2 line anchors | all re-measured (§2.1–§2.9) |

## 10. Cross-child ownership statements

* P2b introduces **no** metric-order authority, ranks nothing, and
  re-migrates **no** P2a site (P2a's scanner green over P2b's diff; the
  ordering-operand invariant green over P2b's new surfaces).
* P2b extends P1's composition **additively** — no competing
  `WorkflowRunBindings` field (secondaries ride `task_composition`).
* P2b touches `evidence.py` / `result_interpretation_agent.py` for
  projection/carry only; **P3's reader architecture untouched** (P3 lands
  after, consuming the typed output).
* P2b touches **nothing P4 owns** (§2.7, measured ∅ overlap).

## 11. Risk register

| risk | mitigation |
|---|---|
| secondaries acquire a vote via a "helpful" ordering line | §4.6 invariant + scope extension + plant; review trigger |
| a third carry representation appears | §4.4 names the `failure_counts` idiom as THE shape; one test asserts both keys ride the same write |
| C6/Q097 guards deleted instead of dispositioned | C0 table first; every flip cites its commit; C4 stops on an uncited row |
| secondary exception breaks an attempt | §4.2 per-call capture + the attempt-parity byte test |
| TIDMAD prompt drift | C0 baseline sha, re-asserted C3 and C4 |
| fingerprint churn fails existing composed resumes | D3's additive-when-nonempty rule + the byte-identity test against the FROZEN pre-P2b sha |
| the new keys leak into planner/reflector prompts | C2 asserts on serialized text, not on the mechanism's description |

## 12. Operator questions — ALL RESOLVED (rulings 2026-08-21; full text §14)

**Open: 0.**

| id | question | RULING |
|---|---|---|
| **Q-P2b-1** | Evaluate secondaries on trial rounds too, or formal-scored records only? | **RESOLVED: `WHEREVER_PRIMARY_EVALUATES`** — trial primary scoring → secondary scoring; formal primary scoring → secondary scoring; no round-type branch. A future secondary needing an independent cadence is a NEW metric-evaluation policy capability, not P2b |
| **Q-P2b-2** | Classification of a secondary evaluation EXCEPTION | **RESOLVED, with the scope-violation exception-order correction**: `NotScoreableError` → typed refusal (attempt successful); `ScopeViolationError` → **RE-RAISE**, the existing outer handler retains ownership, never downgraded; any other `Exception` → `secondary_metric_errors[metric_id]` (plain dict — no new Pydantic model unless source truth proves the dict insufficient), persisted, emitted on the diagnostic/logging/stderr surface, never a contract stdout, never a prompt payload, attempt successful. "Observational" = ordinary secondary outcomes cannot affect primary selection/retry; framework-integrity failures retain their existing STRONGER semantics. The interpreter's frozen three-state carrier is untouched (crash projects `unavailable`) |
| **Q-P2b-3** | Interpreter digest carry vs `_stats` cache-carry? | **RESOLVED: `_STATS_SUFFICIENT`** — durable evidence is already artifact-borne (record carriers + the output's `secondary_metric_specs` stamp); `_stats` owns only the existing quiet-iteration / Stability-Filter reuse continuity, mirroring `failure_counts` exactly. **No current P2b consumer requires digest persistence, so digest widening is unnecessary and outside P2b.** A future requirement for secondary evidence in a cross-iteration semantic digest would require its own explicit ownership decision — P5 is NOT a generic owner for arbitrary future digest fields |

## 13. Adversarial self-review (rev-2 additions marked ★)

| attack | answer |
|---|---|
| Can a secondary select a winner? | no production read feeds an ordering expression; invariant + extended scope + plant prove it |
| Does the DAVIS secondary inherit the primary's direction? | the carrier's `spec` is per-secondary; C3 asserts rendered direction text per metric AND the primary's words absent from secondary lines |
| Is absence honest? | `unavailable` requires the output's declared stamp; undeclared tasks render zero bytes |
| Third persistence shape? | one: the `failure_counts` idiom, asserted in the symmetry test |
| ★ Can a crash masquerade as science? | the crash carrier is textual and separate; the validator refuses an id in two carriers; §2.6's taxonomy keeps the classes apart exactly as the primary does |
| ★ Can a framework-integrity failure hide inside the secondary loop? | no — `ScopeViolationError` RE-RAISES per the frozen §4.2 order and the C2 fixture asserts run termination; "observational" is explicitly bounded to ordinary secondary outcomes |
| ★ Can zero-secondary artifacts drift byte-wise into a broken claim? | the frozen contract is §4.7's SEMANTIC emptiness; byte parity binds only prompts/fingerprint/attempt lifecycle, where deterministic owners assert it |
| ★ Can adding the feature break existing composed resumes? | only a manifest that DECLARES a secondary changes its fingerprint (D3); the zero-secondary byte-identity test pins it |
| ★ Can the new fields leak to the LLM? | C2 asserts the planner/reflector serializations carry none of the three keys |
| ★ Did P2b quietly extend P2a's scanner or reuse its refusal formatter? | no — §2.5 records both non-uses and why; the scanner's precision contract is not diluted |
| Does P2b need P2a semantics? | only the guarantee that ordering is closed so nothing here migrates it — a sequencing dependency, not a code one |

---

## 14. Freeze dispositions (operator rulings 2026-08-21)

Architecture review verdict on rev 2: **PASS** — no child redesign; the
rulings below plus the C-P2b-1 serialization audit are the whole delta from
rev 2 to this frozen revision.

### 14.1 Q-P2b-1 = `WHEREVER_PRIMARY_EVALUATES`

Every declared secondary evaluates wherever the primary evaluates — trial
primary scoring → secondary scoring; formal primary scoring → secondary
scoring. **No round-type branch.** The existing scoring block already owns
both modes (`execution.py:845-846`); current secondaries are deterministic
arithmetic on already-produced deliverables. A future secondary requiring an
independent cadence is a NEW metric-evaluation policy capability — not P2b,
and not to be added quietly.

### 14.2 Q-P2b-2 — RESOLVED, with the exception-order correction

The source-grounded refusal-vs-crash distinction is approved. The frozen
per-secondary taxonomy, in catch order:

```text
NotScoreableError
    -> scientific secondary refusal
    -> secondary_metric_refusals
    -> attempt remains successful

ScopeViolationError
    -> RE-RAISE
    -> existing OUTER scope-violation handler retains ownership
    -> never downgraded into secondary_metric_errors

any other Exception
    -> secondary_metric_errors[metric_id] = concise diagnostic
    -> persisted diagnostic
    -> existing diagnostic/logging/stderr surface
    -> NEVER stdout-contract output
    -> NEVER planner/reflector prompt payload
    -> attempt remains successful
```

**Semantic wording, binding**: *"secondary metrics are observational"* does
NOT mean framework-integrity failures are swallowed. It means ordinary
secondary scientific/refusal/runtime outcomes do not alter primary
selection/retry semantics. A `ScopeViolationError` retains its pre-existing
stronger framework semantics.

The approved crash carrier is
`ExperimentRecord.secondary_metric_errors: dict[str, str]` — diagnostic
PROVENANCE, not scientific evidence. **No fourth `SecondaryMetricEvidence`
state; no new `SecondaryMetricError` model** unless source truth during
implementation proves the dict cannot satisfy this contract. The interpreter
continues to project crash / no-result / no-refusal under a declared stamp
as `unavailable`.

### 14.3 Q-P2b-3 = `_STATS_SUFFICIENT`

`_stats` cache-carry is sufficient; **the committed interpretation digest is
NOT widened in P2b.** Durable evidence already lives artifact-borne in the
`ExperimentRecord` secondary carriers plus
`HyperparamTuningOutput.secondary_metric_specs`; `_stats` owns the existing
quiet-iteration / Stability-Filter reuse carry, exactly mirroring
`failure_counts`.

**Ownership-wording correction (operator)**: the rev-2 phrase "digest
widening would be P5 territory" is REMOVED as a false default-ownership
claim. P5 is not a generic owner for arbitrary future digest fields. The
corrected statement: no current P2b consumer requires secondary evidence in
the committed interpretation digest, so digest widening is unnecessary and
outside P2b; a future requirement for secondary evidence in a
cross-iteration semantic digest would require its own explicit ownership
decision.

### 14.4 C-P2b-1 — zero-secondary serialization, audited and frozen

The persistence path was audited (§4.7): the record path is a
builder-controlled dict pass-through, while the output path is
`model_dump()` with no exclude flags — **default-empty fields WILL
serialize** there. Per the ruling's ELSE branch, the frozen contract is the
§4.7 **semantic-emptiness invariant** (additive empty fields may serialize
and are equivalent to absence; `secondary_metric_specs` absent / `null` /
`[]` equivalent on read), and **no custom omission/serializer machinery is
built for cosmetic byte identity** — no existing public byte contract
requires it. §5, C2 and §7 were corrected to this one contract.

### 14.5 Gate ruling — FROZEN

**Gate 1 NOT REQUIRED · Gate 2 NOT REQUIRED.** Deterministic
composition/evaluation/transport/projection; the 09b renderer's semantics
are reused unchanged; TIDMAD prompt bytes have a deterministic parity owner;
`StubSandbox` exercises the real evaluation call shape; no new
timing/real-training/LLM failure class. Real LLM/training/GPU must not be
run for P2b.

### 14.6 Final consistency sweep (performed at freeze)

Swept for: `PROVISIONAL`, `open operator`, `proposed`, `ratify`,
`P5 territory`, generic "any other Exception" without the carve-out,
un-narrowed "never touching the attempt lifecycle", "no output stamp",
"byte-identical", `secondary_metric_errors`, `ScopeViolationError`. Every
remaining occurrence is historical text (rev-1/rev-2 quotes in §0.1's delta
table and §9's resolution table) or the frozen contract itself. Required
final state holds: **open operator questions 0 · material contradictions 0 ·
unresolved PROVISIONAL semantics 0.**

---

## 15. Implementation ledger (LIVE — opened at implementation start)

**Numbering note (IR-P2b-1).** C0 §2 says the disposition table lives "in
THIS document, §13 when it opens". At freeze, §13 is *Adversarial
self-review* and §14 is *Freeze dispositions*, both frozen. Renumbering a
frozen section would rewrite frozen history, so the ledger opens at **§15**
and every C0-§2 reference to "§13" reads as §15. No semantic change.

| field | value |
|---|---|
| freeze SHA | `3dc298f11a92f1a3de5820a6e436b86c41028c12` (subject: *docs(step10/p2b): REVISION 3 — FROZEN; operator freeze rulings + two boundary corrections*; parent `77b19389`) |
| implementation base | `3dc298f1` — **identical to `origin/master`** at implementation start, so post-freeze drift is ZERO. Contains P1 `bcb17e45`, P2a `e094fa26`, P4 `79833db8` |
| implementation branch | `step10-p2b-secondary-metric-production-transport-impl` |
| tracked design path | `pr_10_p2b_secondary_metric_transport.md` (the kickoff's `..._production_transport.md` does not exist; repository truth used) |
| Gate disposition | Gate 1 NOT REQUIRED / NOT RUN · Gate 2 NOT REQUIRED / NOT RUN · real LLM, training, GPU NOT RUN (frozen §14.5) |

### 15.1 Source preflight (performed BEFORE any edit, at `3dc298f1`)

Every §2 / §3.1 anchor re-measured. **Line counts identical to §3.1**
(`task_composition.py` 982 · `execution.py` 1,172 · `evidence.py` 481), so
the design's measurements describe the tree being edited.

Confirmed at head: `_MANIFEST_KEYS` :93-102 (six keys, unknown refused
:275-282) · `_REQUIRED_KEYS` :109-111 · `_compose_metric` :537-592 (note: it
hardcodes `where = "metric"`) · `compute_semantic_fingerprint` :712-764 ·
`compose_run_task_bindings` metric section :820-826 ·
`bind_run_task_composition` ExitStack :931-936 ·
`verify_composition_is_bound` :939-982 · `bind_run_metric` /
`resolve_bound_run_metric` `evaluation_metric.py:1079/:1102` · tuner
acquisition `ml_hyperparameter_tune_agent.py:548`, `run_order` :561 ·
`RunBindings.run_metric` `contracts.py:116` ·
`AttemptExecution.metric_payload` `contracts.py:343` · scoring `try`
`execution.py:843`, `evaluate_metric` :882-888, `metric_payload` :915,
`ScopeViolationError` handler :1016-1022, generic handler :1023-1049 ·
record `"metric_result"` `records.py:1122` · output stamp `records.py:939`
(and the DEGRADED partial stamp :1000) · healthy output path
`model_validate` → `model_dump()` with no exclude flags :952-957 ·
`ExperimentRecord.metric_result` / `.metric_refusal`
`hyperparam_tuning.py:659/:674` · `HyperparamTuningOutput.metric_spec` :3022
· `SecondaryMetricEvidence` `interpretation.py:114-165` · the `[]` hardcode
`evidence.py:479` · `_stats` write `result_interpretation_agent.py:526-530`
and read-back :353-358, `per_model_secondary_metrics` :361-365.

Three preflight findings, all bounded:

* **F-P2b-1** — `_PLANNER_HIDDEN_RECORD_KEYS` (`agent/prompts.py:944-946`)
  is an **enumerated** frozenset. C2 must add the three secondary record
  keys to it, and test on the SERIALIZED text. The reflector surface leaks
  nothing by construction: it receives `{**train_results, **score_results}`
  (`ml_hyperparameter_tune_agent.py:1227`) and secondaries never enter
  `score_res["results"]` — which C2 also asserts rather than assumes.
* **F-P2b-2** — `StubSandbox.evaluate_metric` (`sandbox_executor.py:2366`)
  already reads `metric.spec.id` / `.direction` from the handle it is
  PASSED, so each secondary keeps its real identity with no stub change.
  Its synthesised scalar comes from `self._rng`, so two secondaries in one
  attempt get distinct values — which is what makes a per-id assertion
  meaningful.
* **F-P2b-3** — `_compose_metric` hardcodes `where = "metric"` inside its
  five fail-closed messages. Reusing it verbatim per secondary would emit
  messages naming the wrong role. See IR-P2b-2.

Measured anchor corrections to §2.8 (drift in the TEST file only, ±1 line):
the record-schema guard is at **:510** (§2.8 said :509) and the tuning-output
guard at **:513** (§2.8 said :514); the evaluator/binder guard is at :518 as
stated. The builder-emptiness assertions are :350-366 and the
fabricated-key mutation :368-385 (§2.8 said :372-379).

### 15.2 Guard disposition table (C0 — every §2.8 guard, with its flipping commit)

| # | guard (file `tests/unit/agent/result_interpretation_agent/test_step09a_c6_evidence_projection.py`) | anchor at base | disposition | flipping commit | status |
|---|---|---|---|---|---|
| G1 | `TestQ097StaysBinding::test_no_secondary_field_was_added_to_the_record_schema` | :510 | **INVERT** — the record MUST carry exactly `secondary_metric_results`, `secondary_metric_refusals`, `secondary_metric_errors` | **C2** | `[x]` |
| G2 | `TestQ097StaysBinding::test_no_secondary_field_was_added_to_the_tuning_output` | :513 | **INVERT** — the output MUST carry exactly `secondary_metric_specs` | **C2** | `[x]` |
| G3 | `TestQ097StaysBinding::test_no_production_module_evaluates_a_secondary_metric` | :518-532 | **INVERT in two halves**: the BINDER must exist in its named owner (C1) and the EVALUATOR in its named owner (C2), and nowhere else | **C1** (binder) + **C2** (evaluator) | `[x]` both halves inverted (C1 `f9d6ea53`, C2) |
| G4 | `TestSecondaryMetricEvidence::test_the_production_builder_leaves_it_EMPTY` (both params) | :350-366 | **REWRITE** into projection-correctness | **C3** | `[x]` |
| G5 | `TestSecondaryMetricEvidence::test_the_builder_does_not_read_undeclared_record_keys` | :368-385 | **KEEP** — the fabricated payload moves to a key that REMAINS undeclared | **C2** (re-pointed from C3 — D-P2b-1: C2 is the commit that trips it) | `[x]` |
| G6 | `TestSecondariesCannotReachOrdering` — ordering-operand invariant + plant + behavioural flip | :440-504 | **KEEP, scope EXTENDED** over P2b's production surfaces | **C0** declares/proves · **C4** re-proves at the final head | `[x]` both halves done |

C4 STOPS on any row still `[ ]` without a citing commit.

### 15.3 C0 — guard dispositions + invariant scope baseline — **COMPLETE**

Commit: see §15.11. Test/docs only; **zero production files changed**
(`git status --porcelain` showed exactly one modified path, the guard test).

- [x] §2.8 disposition table recorded with re-verified anchors and named
      flipping commits — §15.2 above (six rows, zero unaccounted).
- [x] Scanned-surface extension. `INTERPRETER_FILES` (the 09a five) is kept
      as its own named list; `PRODUCTION_FILES` adds P2b's measured touch
      set — `workflows/task_composition.py`,
      `execute_tools/evaluation_metric.py`, the four tuner modules
      (`execution.py`, `ml_hyperparameter_tune_agent.py`, `contracts.py`,
      `records.py`) plus `policy.py` (the tuner's ordering authority — the
      single most likely home for an accidental secondary vote),
      `agent/schemas/hyperparam_tuning.py`,
      `agent/schemas/interpretation.py` and
      `agent/prompt_templates/interpretation/rendering.py`.
      `SCANNED_FILES` is their union and is what the census iterates.
      **GREEN at base over the extended surface**: 25 passed, 1.31 s.
- [x] The census now also FAILS when a scanned file does not exist (a
      vanished path would otherwise make the census pass by looking at
      nothing), and a new `test_the_scope_extension_is_live` reads each
      newly-scanned file from disk, appends an offending expression and
      requires a hit — so a name in the list that the census never opens is
      RED.
- [x] **Plant-and-catch on the EXTENDED scope**, verbatim transcript. A
      synthetic offender appended to `nodes/ml_hyperparameter_tune_agent/
      execution.py` (a NEWLY-scanned file):

      ```python
      def _p2b_c0_plant(models, order):
          return order.best(models, key=lambda m: m.secondary_metric_results[0].scalar)
      ```

      RED, naming **exactly one** site (the §6 edge-case requirement):

      ```text
      E  AssertionError: a secondary metric is an operand of an ordering
      E  expression — secondaries are OBSERVATIONAL and must never affect a
      E  ranking: {'nodes/ml_hyperparameter_tune_agent/execution.py':
      E  ['1176: order.best(models, key=lambda m:
      E  m.secondary_metric_results[0].scalar)']}
      1 failed, 24 deselected in 1.15s
      ```

      Reverted from a pre-plant copy; `git diff -- execution.py` EMPTY;
      `__pycache__` cleared before and after; re-run **33 passed, 1.36 s**
      (guard module + the C1a differential oracle).
- [x] The three Q097 guards measured **GREEN at base** — 32 passed, 1.25 s
      before any edit. None was already red, so the design's baseline is the
      tree being edited.
- [x] **TIDMAD prompt-parity baseline recorded.** The owner is the Step-09a
      C1a differential oracle, whose goldens hold the sha256 of every
      rendered system/user prompt in the fixed-input call sequence — and
      which already covers 09b C3's `### Secondary metrics` section:

      | golden | sha256 at base |
      |---|---|
      | `goldens/step09a_differential_llm_calls.json` | `376f289e5caff1d1522ef6c4e63a4abb9115189692e1e1789af7921cfb30b352` |
      | `goldens/step09a_differential_digest.json` | `aa676b69fa9ff364077785aa54663b7e1c15299a9f8246195a6303038b96b664` |

      TIDMAD declares no secondary, so C3/C4 must leave BOTH byte-identical
      and the oracle green with no regeneration. A regenerated golden here
      is a P2b failure, not a declared delta.

**C0 acceptance**: all five criteria met — table complete with named
flipping commits · invariant green over the extended surface · plant
transcript recorded verbatim (RED → revert → green) · Q097 guards green at
base · parity shas recorded · zero production files changed.

### 15.4 C1 — declaration + composition + run-scoped binding — **COMPLETE**

Commit: see §15.11.

**Production surface.** `workflows/task_composition.py`: `_MANIFEST_KEYS`
gains `secondary_metrics` (7 keys; `_REQUIRED_KEYS` unchanged, with the
reason recorded at its declaration); `_compose_metric` gains a `where: str =
"metric"` ROLE parameter (IR-P2b-2); the new `_compose_secondary_metrics`
resolves the optional list through `_compose_metric` ITSELF and adds only
the two rules a single metric cannot violate; `RunTaskComposition
.secondary_metrics: tuple[EvaluationMetric, ...] = ()` is appended so the
existing nine fields keep their positions; `compute_semantic_fingerprint`
gains the ADDITIVE-WHEN-NON-EMPTY `secondary_metric_declarations` key;
`compose_run_task_bindings` resolves the secondaries immediately beside the
primary (so the collision check has the primary id), extends `plugins` and
writes one `secondary_metric_declaration[i]` provenance entry per entry;
`bind_run_task_composition` enters the new binding on the SAME `ExitStack`;
`verify_composition_is_bound` gains the per-entry identity check.
`execute_tools/evaluation_metric.py` gains `bind_run_secondary_metrics` /
`resolve_bound_run_secondary_metrics` beside the primary pair, resolving to
`()` when unbound.

**Fingerprint evidence** — literals captured at the freeze commit `3dc298f1`
BEFORE any production line existed, and pinned in the test as frozen
evidence (never recomputed on both sides of one run):

| task | pre-P2b sha | after C1 | verdict |
|---|---|---|---|
| tidmad | `d6628a93fcb3578ca32812f39246f2b51abeecbd24d21df56856ea0ef9c56d3a` | **identical** | zero-secondary byte identity HELD |
| fourth_task | `fe00fd076153c847da65c71c72df5520bec902d6d17b43b9c7b1bb80e2ab099a` | **identical** | second zero-secondary control |
| pets | `52a422b030bb896cc22862b687855101ed302f2e59792b523d353b7dc67d6086` | `2b3b5383…` | CHANGED — it now declares `macro_f1` |
| davis | `9980a7a955c689a8f94ab048eee9c4715ce9a25fdaac7bf3a510197cf2e0ac26` | `c59342f8…` | CHANGED — it now declares `psnr`, `mae` |

Also pinned: an explicit `secondary_metrics: []` composes and hashes
identically to the section being ABSENT; reordering DAVIS's two entries
CHANGES the sha (manifest order is semantic); the same declared family at two
absolute paths yields ONE sha (Q-P1-2 held).

**Composed sets, as literals**: TIDMAD `()` · Pets `[("macro_f1","higher")]`
· DAVIS `[("psnr","higher"), ("mae","lower")]` — two directions opposing each
other AND the `lower` `mse` primary.

**Reuse proven, not asserted**: deleting `implementation` from
`secondary_metrics[1]` raises `_compose_metric`'s OWN branch with the message
naming `secondary_metrics[1]`; deleting it from `metric` still raises the
byte-identical pre-P2b `metric requires an 'implementation' mapping`.

**Guard flip (G3, binder half)**: the 09a evaluator/binder census is NARROWED
to the evaluator half (`evaluat|scor|load`, C2 flips it) and the binder half
INVERTS into `tests/unit/workflows/test_step10_p2b_c1_secondary_declaration.py
::TestTheBinderHasExactlyOneOwner`, which asserts the pair exists in
`execute_tools/evaluation_metric.py` and **nowhere else** — an equality
against an exact `{owner: [names]}` mapping, so a second binder anywhere in
`nodes|agent|core|execute_tools|workflows` is RED.

**The extended invariant did its job in this commit.** It flagged a REAL hit
on the first production edit — see IR-P2b-3. That is the C0 §6 edge case
("the extended invariant flags an EXISTING expression ⇒ STOP and audit")
firing on the very commit it was built for, and it was resolved by fixing the
detector's precision, never by an allowlist.

### 15.5 C2 — evaluation + record/output transport — **COMPLETE**

Commit: see §15.11.

**Production surface.** `agent/schemas/hyperparam_tuning.py`: the three
reserved record carriers (`secondary_metric_results: list[MetricResult]`,
`secondary_metric_refusals: list[NotScoreableResult]`,
`secondary_metric_errors: dict[str, str]` — a PLAIN dict, no new Pydantic
model, per Q-P2b-2) plus a per-id exclusivity validator, and
`HyperparamTuningOutput.secondary_metric_specs: list[MetricSpecField] | None`.
`nodes/ml_hyperparameter_tune_agent/execution.py`: the extracted
`_evaluate_secondary_metrics` boundary (typed inputs, a typed three-part
result, one diagnostic print per crash, no access to attempt control flow),
called once after the primary result inside the existing `try`.
`ml_hyperparameter_tune_agent.py`: `resolve_bound_run_secondary_metrics()`
beside the primary acquisition, with NO legacy branch — there is nothing to
fall back to. `contracts.py`: `RunBindings.run_secondary_metrics` and three
`AttemptExecution` carriers. `records.py`: record keys written only when
non-empty (the builder controls the dict key-by-key), the output stamp beside
`metric_spec`, and the SAME stamp on the DEGRADED partial-output branch — the
declared set is a launch fact and does not stop existing because the tuner
later failed. `agent/prompts.py`: the three keys join
`_PLANNER_HIDDEN_RECORD_KEYS`.

**The frozen taxonomy, per secondary, in catch order** — implemented exactly
as §4.2 froze it, and the ORDER is load-bearing: `ScopeViolationError`
subclasses `ValueError`, so a generic-first arrangement would silently convert
a non-retryable run termination into a dictionary entry.

**Attempt-parity evidence.** The IDENTICAL bounded pseudo iteration was run
twice — once with `()` bound, once with DAVIS's pair bound and one of them
CRASHING — and compared on nine lifecycle surfaces (status,
termination_reason, completed_rounds, total_attempts, per-record status
sequence, per-record scores, every primary `metric_result` payload,
best_denoising_score, and the ordered LLM call-label sequence). Deep-equal.
The comparison deliberately excludes the three new record keys and the stamp:
those ARE the declared delta.

**State-sequence evidence** (the lifecycle-evidence rule, not "the field is
populated"): on a DAVIS-bound run every primary-scored record carries
`[("psnr","higher",31.5), ("mae","lower",0.017)]` in manifest order, empty
refusals and empty errors; the sandbox saw exactly `("psnr","mae")` once per
scored record; the scored set spans BOTH a trial and a formal round, which is
what makes Q-P2b-1's "no round-type branch" claim testable rather than
asserted. On a mixed run, `psnr` lands in refusals and `mae` in errors, both
stay on the stamp, and results is empty.

**Mutation proofs** (each planted, caught, reverted, baseline re-proven green
at 21 passed):

| # | mutation | caught by |
|---|---|---|
| M1 | `except ScopeViolationError: raise` deleted, so the generic clause swallows it | `test_a_scope_violation_is_RE_RAISED_not_downgraded` |
| M2 | the crash never writes `errors[metric_id]` | 5 tests, incl. attempt parity |
| M3 | every secondary evaluated under `secondaries[0]`'s identity | 8 tests |
| M4 | the record builder never writes `secondary_metric_results` | `test_the_declared_family_is_evaluated_and_lands_on_every_scored_record` |
| M5 | the output stamp is always `None` | 2 tests |
| M6 | the three keys removed from `_PLANNER_HIDDEN_RECORD_KEYS` | `test_the_planner_prompt_carries_none_of_the_three_keys` |

**Prompt boundary, proven on serialized text.** The planner prompt is built by
the REAL `get_planner_user_prompt` over a record carrying all three keys: none
of the key names, neither secondary value, and the crash text are present —
while the record's own `exp_id` still is, so it is an exclusion test and not
an empty-prompt test. The reflector needs no filter: its payload is
`{**train_results, **score_results}` and secondaries never enter
`score_res["results"]` — pinned by a source assertion over that literal.

**Guards.** G1/G2 inverted to EXACT name sets (a fourth record carrier or a
differently-spelled stamp is RED). G3's evaluator half inverted to an exact
one-owner census. See F-P2b-4 for the defect the inversion exposed.

**Declared golden deltas** (§4.7: the output path is `model_dump()` with no
exclude flags, so additive default-empty fields DO serialize; the frozen
contract is semantic emptiness, and building omission machinery for cosmetic
byte identity is explicitly forbidden):

| golden | delta |
|---|---|
| `rec3_schema_field_lists.json` | `hyperparam_tuning_output` gains `secondary_metric_specs` (47 → 48) |
| `rec2_formal_success_projection.json`, `rec2_oom_skip_projection.json` | each gains the three EMPTY record carriers |
| `EXPERIMENT_RECORD_FIELDS_58` → `_61` | three names appended after the primary pair; every earlier position unchanged |
| `step09_5a_pre_refactor_oracle.json` | the result gains `secondary_metric_specs: None`, its record the three empty carriers |

Every delta is the EMPTY state and nothing pre-existing moved — each was
applied surgically key-by-key and then verified, never regenerated to green.

### 15.6 C3 — interpreter projection + quiet-iteration carry + rendering — **COMPLETE**

Commit: see §15.11.

**Production surface.** `nodes/result_interpretation_agent/evidence.py`:
`_project_secondary_metrics(output, record)` replaces the `[]` hardcode —
declared stamp × the record the HEADLINE score came from (`best_rec`), which
is what keeps a secondary number describing the same experiment as the score
printed beside it (IR-P2b-5). `result_interpretation_agent.py`: the `_stats`
write beside `failure_counts` and the read-back beside it, closing the B-6
asymmetry.

**Projection matrix**, asserted as hand-written literals on the projected
STATE SEQUENCE `(id, its OWN direction, status)` — never read back from the
projection:

| record state under a stamp | projects |
|---|---|
| a matching result | `scored` |
| a matching refusal | `refused` |
| neither | `unavailable` — a NAMED absence |
| a crash (`secondary_metric_errors`) | `unavailable`, with the diagnostic kept separately — NEVER a fourth scientific state |
| **no stamp** (legacy or a task with none) | `[]` — zero rows, zero rendered bytes, even when the record DOES carry evidence |

DAVIS's discriminating case holds: `[("psnr","higher",…), ("mae","lower",…)]`
beside a `lower` primary, in declared order, with the declared literals pinned
against the REAL DAVIS composition so the matrix cannot drift onto a metric
nobody runs.

**B-6 symmetry.** One fixture, both keys, one assertion block: a model that
contributes no summary this iteration gets BOTH `failure_counts` AND
`secondary_metrics` back from `_stats`. A cache predating the key contributes
ABSENCE, never zero. A corrupt payload degrades to absence with a printed
warning. §4.7 held: a zero-secondary run writes NO `_stats` secondary key at
all (verified on the HEALTHY path — the degraded path writes no `_stats`, so
the degraded harness could not have seen it).

**Rendering.** The 09b renderer is REUSED UNCHANGED (`git diff` over
`rendering.py` is empty). Its per-line direction words are asserted textually:
the `psnr` line says `higher`, the `mae` line says `lower`, and neither
carries the other's word — inheritance disproven on the bytes rather than
inferred. A refusal renders its contract id verbatim. No declared secondary
renders NO line at all, not an empty section.

**TIDMAD prompt parity — byte-identical, no regeneration.** The C1a
differential oracle is green and both goldens still hash to their C0 baseline
values (`376f289e5caff1d1522ef6c4e63a4abb9115189692e1e1789af7921cfb30b352`
calls, `aa676b69fa9ff364077785aa54663b7e1c15299a9f8246195a6303038b96b664`
digest). `git diff 3dc298f1 -- .../goldens/` over that directory is EMPTY.

**Mutation proofs** (each planted, reverted, baseline re-proven at 55 passed):

| # | mutation | outcome |
|---|---|---|
| M7 | the projection reverted to `[]` | CAUGHT — 10 failures |
| M8 | a refusal silently collapsed into `unavailable` | CAUGHT — 3 failures |
| M9 | the `if not declared: return []` early return removed | **SURVIVED — EQUIVALENT.** Iterating an empty declared list yields `[]` either way, so the mutation changes no behaviour. Replaced by M9′ |
| M9′ | the projection ignores the stamp and synthesises specs from the RECORD's own carriers (the real failure mode) | CAUGHT — both `no-stamp` cases |
| M10 | the `_stats` READ-BACK half deleted (B-6 reopened) | CAUGHT — 3 failures |
| M11 | the `_stats` WRITE half deleted | **SURVIVED at first — a REAL GAP.** The carry fixture hand-built its cache, so the producer half was untested. Closed by `test_the_write_and_the_read_back_are_ONE_round_trip`, which runs a healthy interpretation, takes the cache IT produced and feeds that into a second quiet-model run. Re-run: CAUGHT |

**Guard dispositions applied.** G4 REWRITTEN — "the builder always leaves it
empty" would now assert the opposite of the shipped contract, so it states the
claim that actually survives: evidence appears ONLY under a declared set. Both
original parametrisations (bare record / fully-scored record) are preserved,
and the fully-scored one is now load-bearing, since a projection falling back
to the record's carriers is exactly what M9′ plants. The module docstring
records the inversion rather than pretending Q-09-7 = B never said otherwise.

### 15.7 C4 — three-task closure + final invariant + docs — **COMPLETE**

Commit: see §15.11.

**Three-task lifecycle, driven through the REAL chain.** Every earlier commit
proved one hop with the others stubbed; C4 drives each task once, end to end,
with nothing hand-assembled in between —
compose the task's OWN manifest → bind for the run → the real tuner (pseudo
mode) evaluates and records → the real output stamp → the real interpreter
projection → the real 09b renderer — and asserts the STATE SEQUENCE the whole
chain produced.

| task | composed | record carriers | stamp | projection | rendered |
|---|---|---|---|---|---|
| **TIDMAD** | `[]` | **no secondary key written at all** | `None` | `[]` | `[]` — ZERO lines |
| **Pets** | `[("macro_f1","higher")]` | `secondary_metric_results` only | `[("macro_f1","higher")]` | `scored` | 1 line; `log_loss` absent from the ENTIRE observed state (Q-10-4 = A) |
| **DAVIS** (scored) | `[("psnr","higher"), ("mae","lower")]` | both results, in order | both | `scored`, `scored` | the psnr line says `higher` and not `lower`; the mae line the reverse |
| **DAVIS** (mixed) | same | `secondary_metric_refusals` + `secondary_metric_errors`, results EMPTY | both still stamped | `refused`, `unavailable` | the refusal renders its contract id; the crash text `boom` is ABSENT from the render |

The DAVIS rows are the discriminating ones: two opposing secondary directions
beside a `lower` primary, so nothing observed can have been produced by
inheriting a single direction from anywhere.

**Final observational invariant + anti-vacuity.** The census is re-run over
the finished surface and is green. The C4 plant is EXECUTABLE rather than a
manual transcript: for each of the FIVE files P2b actually changed
(`task_composition.py`, `evaluation_metric.py`, tuner `execution.py`,
`evidence.py`, `result_interpretation_agent.py`) it appends a probe containing
an order comparison, a `MetricOrder` call and a sort key, requires a hit, and
asserts the UN-planted source is clean in the same test. Aiming it at the
changed files rather than at the whole declared scope is deliberate: a census
green because it read a file P2b never touched would prove nothing about P2b.

**Guard closure.** All six §2.8 rows reached their dispositioned end state
with a citing commit — G1/G2/G5 in C2, G3 across C1+C2, G4 in C3, G6 declared
and proven in C0 and re-proven here. Zero rows uncited, so C4's STOP condition
does not fire.

**Docs sync**, each claim quoted against merged source:

* `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md` — the
  three record carriers in the record-payload table (including the
  `ScopeViolationError` carve-out), the run-scope acquisition bullet (no
  legacy branch, the stamp on BOTH output branches, `run_order` reads the
  primary only), and the hidden-payload section extended with why the
  widening moved no existing prompt byte.
* `nodes/result_interpretation_agent/result_interpretation_agent.md` — the
  projection table (four states + the no-stamp row), the `_stats` carry row,
  the rewritten "observational, and live since Step 10 / P2b" section
  including the closed B-6 asymmetry, and the rendered-section row.
* **Measured, not assumed**: there is no `--task_composition` CLI flag and no
  operator-facing composition doc (P1's edge is programmatic — `grep` over
  `docs/`, `scripts/` and the workflow argument parsers found none), so the
  two node docs are the complete doc surface. The manifest key itself is
  documented at its declaration in `task_composition.py`.

### 15.8 Local implementation rulings (IR-P2b-N)

**IR-P2b-1 — the ledger opens at §15, not §13.**
*Question*: C0 §2 says the disposition table lives in "§13 when it opens".
*Source*: at the freeze SHA, §13 is *Adversarial self-review* and §14 is
*Freeze dispositions*. *Options*: renumber the frozen sections; append the
table with no section; open a new section. *Ruling*: open **§15** and read
every "§13" reference in C0 as §15. Renumbering frozen sections would
rewrite frozen history for a cosmetic reason. *Validation*: none needed —
documentation numbering, zero semantic content.

**IR-P2b-2 — `_compose_metric` gains a `where` role parameter.**
*Question*: §3.1 requires the secondary loop to CALL `_compose_metric` with
NO duplicated fail-closed branches ("if reuse proves impossible, STOP"), but
the function hardcodes `where = "metric"` inside all five of its messages, so
verbatim reuse would tell an operator that `metric` failed when
`secondary_metrics[1]` did. *Source*: `task_composition.py:537-592` at head;
the five branches at :553, :560, :567, :580, :587 all interpolate `where`.
*Options*: (a) copy the function — forbidden by §3.1 and the exact drift the
rule exists to prevent; (b) reuse verbatim and accept misleading messages —
a composition error's whole job is to name what failed; (c) post-process the
message text — fragile string surgery over a contract; (d) add a `where`
parameter defaulting to `"metric"`. *Ruling*: **(d)**. It is the smallest
change, it keeps the primary's messages BYTE-identical (the default), and it
makes the role explicit at the one call site that is not the primary.
*Validation*: `test_an_inherited_branch_fires_with_the_SECONDARY_s_role_named`
(the inherited branch fires for a secondary, naming `secondary_metrics[1]`)
and `test_the_primary_s_own_messages_are_unchanged` (anchored `^metric
requires an 'implementation' mapping`).

**IR-P2b-3 — the ordering-operand invariant flags ORDER comparisons, not all
comparisons.**
*Question*: C1's first production edit turned the C0-extended invariant RED
on `resolve_bound_run_secondary_metrics() != composition.secondary_metrics`
(`task_composition.py`, inside `verify_composition_is_bound`). C0 §6 requires
a STOP-and-audit: real latent offender, or precision defect?
*Source*: the flagged node is an `ast.Compare` with `NotEq`, inside a
binding-integrity check, written in the SAME `!=` idiom as the pre-P2b
`task_config` check on the line directly below it (`bound_config.get
("task_description") != composition.task_description`). It decides SAMENESS
of a bound family, and reaches no ranking. Verdict: **precision defect in the
detector**, not an offender. *Options*: (a) allowlist the file — explicitly
forbidden by C0 §6; (b) drop the `verify_composition_is_bound` check — it is
the only thing that catches a run which stamps a declared family it never
bound, whose failure mode is a silent all-`unavailable` projection; (c)
rewrite the check into a helper call so no `Compare` names a secondary — the
detector's own docstring calls contorting production to satisfy the census
"the tail wagging the dog"; (d) narrow the `Compare` branch to ORDER
operators (`Lt`, `LtE`, `Gt`, `GtE`). *Ruling*: **(d)**. Before P2b no
production line touched a secondary, so flagging every comparison was free;
P2b makes legitimate equality comparisons unavoidable. The CLASS claim is
"secondaries cannot reach an ordering decision", and a ranking must produce
an order through an order comparison, an extremum call, a sort key or a
`MetricOrder` method — all four still flagged. *Validation*: the plant
family grew from 3 to 8 shapes covering `>`, `<`, `>=`, `<=`, `max`,
`sorted`, `.sort` and `order.best`; `test_a_binding_integrity_check_is_
deliberately_not_an_offender` pins the narrowing as a decision rather than a
drift; `test_the_scope_extension_is_live` now plants BOTH an order-method and
an order-comparison shape into every newly-scanned file's real source; and
`test_flipping_every_secondary_value_changes_no_ordering_output` remains the
behavioural backstop for whatever the AST cannot see.

**IR-P2b-4 — `per_sample` is NOT excluded from a secondary's record payload.**
*Question*: the primary dumps its result with `exclude={"per_sample"}`
(`execution.py:915`); should the secondary carriers mirror that?
*Source*: the primary's exclusion is DEDUPLICATION — the same values are on the
record as `file_vector`, and the Step-06 comment says so in as many words. A
secondary has no `file_vector` twin on the record. *Options*: (a) mirror the
exclusion — would silently DROP per-sample evidence rather than deduplicate it;
(b) dump in full. *Ruling*: **(b)**, with the reason recorded at the write site
so the asymmetry does not read as an oversight. *Validation*: the round-trip
test persists and re-validates a full secondary payload; today's three declared
secondaries are scalar-only, so this is a contract choice with no current
byte impact.

**IR-P2b-5 — the projection follows the record the HEADLINE score came from.**
*Question*: §4.4 says "find its result or refusal on the record" without
naming which record, and a tuning output holds many.
*Source*: `ModelRunSummary.secondary_metrics` is ONE list with no role field,
and `SecondaryMetricEvidence` (frozen, 09a) has none either — so the shape
cannot express two roles the way `best_/formal_training_diagnosis` does.
Meanwhile `evidence.py` already computes four role records
(`best_rec`, `valid_best_rec`, `valid_formal_rec`, `formal_rec`).
*Options*: (a) `best_rec` — the record `best_denoising_score` came from;
(b) `formal_rec`; (c) the last record; (d) widen the frozen carrier with a
role. *Ruling*: **(a)**. 09a's per-role lesson is that evidence and the score
printed beside it must describe the SAME experiment; the summary's headline
number is `best_*`, so anything else would pair a secondary with a different
run. (d) would redesign a frozen receiving model, which is out of scope.
*Validation*: `test_the_projection_follows_the_record_the_headline_score_came_
FROM` — two records with different secondary values, and only the best
record's reaches the summary.

**IR-P2b-6 — the `_stats` read-back catches `Exception`, not a narrow tuple.**
*Question*: which exceptions should the corrupt-cache branch absorb?
*Source*: written first as `(ValidationError, TypeError)`; a test drove a spec
dict missing `scoreability` through it and got an uncaught **`KeyError`** from
`metric_spec_from_declaration` (`evaluation_metric.py:670`) via
`MetricSpecField`'s BeforeValidator. *Options*: (a) add `KeyError`;
(b) enumerate every type the declaration parser might raise; (c) catch
`Exception`. *Ruling*: **(c)**. This parses untrusted JSON written by a
PREVIOUS iteration, and the design's requirement is "never a crash" — (a)
fixes one instance of a class, and (b) is a promise about a nested parser's
internals that this call site cannot keep. The absorbed error is PRINTED, so
the branch is loud rather than silent. *Validation*:
`test_a_corrupt_cached_payload_degrades_to_absence_without_crashing`, plus
mutation M10 proving the branch is reached at all.

### 15.9 Deviations from the frozen design

None material. Two BOUNDED deviations, both from §2.8's assignment of a guard
to a commit rather than from any frozen semantic:

**D-P2b-1 — guard G5 was re-pointed from C3 to C2.** §2.8 assigns the
ignore-undeclared-keys mutation to C3. It breaks in **C2**, because C2 is what
turns its fabricated `secondary_metric_results` into a real declared field:
the payload then reaches a validator through `object.__setattr__` and raises.
C0's own rule is that each guard is flipped by the commit that TRIPS it, so
holding it for C3 would have meant committing a red tree. The disposition
itself is unchanged — KEEP the mutation, move the payload to a key that
remains undeclared — and the test now asserts that key is undeclared rather
than assuming it.

**D-P2b-2 — four baselines outside §2.8 carried the declared delta.** The
Step-00 record baselines (2 goldens + the ordered field list) and the
Step-09.5a workflow envelope oracle pin serialized shapes that §4.7 predicts
will change. Each was updated surgically with the delta recorded in its own
module, per those baselines' stated update policy; none was regenerated.

IR-P2b-2, IR-P2b-3 and IR-P2b-4 are bounded implementation rulings inside the
frozen contract, not deviations: none changes a frozen semantic, and all three
STRENGTHEN the surfaces the design names.

### 15.10 Findings

**F-P2b-1**, **F-P2b-2**, **F-P2b-3** — recorded in §15.1.

**F-P2b-4 — the Step-09a evaluator census was blind to a leading underscore.**
Inverting G3 in C2 produced `{}` where the real evaluator sits. The cause: the
09a census used two ANCHORED alternations, one requiring the name to BEGIN
with `evaluat`/`load`. `_evaluate_secondary_metrics` begins with `_`, so the
guard would have reported "no production module evaluates a secondary metric"
while one did — a guard green for the wrong reason, which is the only kind
that is worse than absent. It also missed the plural (`_score_secondaries`).
Fixed by stating the predicate ONCE over the whole name with no anchoring
(`"secondar" in name` AND `evaluat|scor|load`), shared by the census and its
probe so the probe cannot test a copy, with five plant shapes pinning it.
Severity: the defect was latent — nothing evaluated a secondary before P2b —
but the SAME shape guards other censuses and is worth a look when one is next
touched.

### 15.11 Commits

| commit | milestone | subject |
|---|---|---|
| `9250343e` | C0 | test(step10/p2b): C0 — guard dispositions, extended ordering-operand scope, parity baseline |
| `f9d6ea53` | C1 | feat(step10/p2b): C1 — declare secondary metrics in the manifest and bind them for the run |
| `ec05f3a2` | C2 | feat(step10/p2b): C2 — evaluate the declared secondaries and transport their outcomes |
| `ab5a3da4` | C3 | feat(step10/p2b): C3 — project secondary evidence, carry it across quiet iterations, render it |
| `5b77742d` | C4 | test(step10/p2b): C4 — three-task lifecycle closure, final invariant plant, docs |
| `f6a73afd` | — | docs(step10/p2b): ledger numbering — sequential §15 sections, ordered IR entries (docs only) |

**Exact-head CI.** Run
[**32439134908**](https://github.com/Galileo-Sandbox/SIDERIUS/actions/runs/32439134908)
— **SUCCESS** — tested `f6a73afdc4bcfca3800ecac6d641c8d570be24d1`, identical
to the PR head at the time of the run. Scope: **FULL SUITE** (the selector
does not narrow on `pull_request` — "runs everything by policy"). Steps: ruff
check · ruff format · **pyright** · unit, all success. Verdict read from the
JOB LOG rather than a wrapper's exit status:

```text
11318 passed, 33 skipped, 516 warnings in 993.60s (0:16:33)
```

pyright could not be run locally (Node `v10.19.0`), so this run is its ONLY
evidence — and it is green on the exact head.

**Superseded run, recorded so the canonical one is unambiguous**: run
`32438162347` ran on `5b77742d` and was AUTO-CANCELLED by GitHub's concurrency
group when `f6a73afd` was pushed. It is NOT acceptance evidence; its lint,
ruff-format and pyright steps had all reported success before cancellation.
Exactly one full CI produced this PR's evidence.

Any commit after `f6a73afd` is documentation-only provenance synchronisation
and names the executable head it describes rather than its own SHA — the
self-reference the C4 plan warns about is avoided by recording ANOTHER
commit's run, not by skipping the record.

---

*END — REVISION 3 — FROZEN, operator approved 2026-08-21 (architecture PASS
+ freeze rulings Q-P2b-1/2/3 + C-P2b-1 serialization resolution applied).
Source anchor `96dc1327`. Implementation status at the freeze commit: NOT
STARTED. Gate 1 NOT REQUIRED; Gate 2 NOT REQUIRED. P2b implementation begins
in a FRESH session from a newly filled Implementation Working Rules
contract.*
