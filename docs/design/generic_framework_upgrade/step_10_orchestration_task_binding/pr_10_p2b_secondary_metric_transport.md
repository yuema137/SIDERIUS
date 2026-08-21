# Step 10 / P2b — Secondary Metric Production Transport

## 0. Status

**DRAFT rev 2 — POST-P2a/P4 RECONCILIATION — FOR OPERATOR REVIEW. NOT
FROZEN. IMPLEMENTATION NOT STARTED.**

Rev 2 is the post-merge reconciliation rev 1 demanded of itself: every
`PROVISIONAL(P1)` / `PROVISIONAL(P2a)` marker is resolved against MERGED
source, all line anchors re-measured, and the §6 commit decomposition is
rewritten into full eight-section per-commit plans with all-`[ ]` checklists.
The Q-P2b-2 taxonomy audit the operator required before freeze has been
**performed** (§2.6) and its disposition is PROPOSED in §12 — the ruling
itself remains the operator's.

| field | value |
|---|---|
| parent | Step-10 parent REVISION 2 (frozen), §3.4 / §9 / §9.4; owns scope item **S3** |
| source anchor | merged `master` = **`96dc1327`** (production tree identical to the P2a squash `e094fa26`). Contains P1 `bcb17e45` + P4 `79833db8` + P2a `e094fa26`. Line anchors are evidence, not implementation authority |
| depends on | **P1 MERGED** (the composition edge C1 extends), **P2a MERGED** (ordering is closed, so nothing here migrates or duplicates it — parent §9.4 item 8). **P4 MERGED with ZERO production-file overlap with P2b's touch set** (measured §2.7) — a sequencing fact, not a dependency edge |
| Gate disposition | proposed: **NO Gate — Gate 1 NOT REQUIRED, Gate 2 NOT REQUIRED.** Deterministic transport + carry-symmetry tests + the ordering-operand invariant are the owners (parent §22.1). The only LLM-facing delta is real values flowing through the ALREADY-LANDED 09b renderer (validated by 09b's Gate 1); TIDMAD prompt bytes are pinned identical (§5). Quoted against `docs/gates/gate_testing_standard.md` at freeze |
| open operator questions | **3** (§12 — each now carries a post-audit disposition proposal) |

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
  (`:845-846`) — the measured fact behind Q-P2b-1's proposal.
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
mirror (proposed in §12 Q-P2b-2): a secondary `NotScoreableResult` → that
secondary's typed `refusal` entry; a secondary CRASH → an additive
`secondary_metric_errors: dict[metric_id, str]` on the record (non-silent:
persisted + printed), which the interpreter projects as `unavailable` — the
frozen three-state carrier is untouched, and no crash is ever dressed as a
scientific refusal. Scope violations are not per-secondary (the SampleSet is
validated once, before the primary).

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

### 3.1 Structure preflight (parent §19.3 — binding at freeze)

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
* **Gate 1 / Gate 2**: NOT REQUIRED (proposed) — no new LLM-facing semantics
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
* a secondary refusal (`NotScoreableError` caught around ITS call only) is
  captured as that secondary's typed refusal — it never fails the attempt,
  never alters the primary result, never triggers retries;
* a secondary evaluation CRASH is caught around ITS call only, recorded per
  the §12 Q-P2b-2 disposition as ratified at freeze (every candidate shape
  is non-silent), and never propagates into the attempt lifecycle;
* the primary's own error semantics (`ScopeViolationError` → end round;
  primary exception → `error_scoring` record) are byte-untouched — the
  secondary loop runs only after a SUCCESSFUL primary result, so an
  `error_scoring` attempt carries no secondary entries by construction;
* evaluation happens **wherever the primary evaluates** (Q-P2b-1 proposal):
  the scoring block already runs for both trial and formal modes
  (`execution.py:845-846`), and no round-type branch is added.

### 4.3 Record + output transport — the reserved names (delta D1)

Additive, defaults empty, frozen names untouched:

* `ExperimentRecord.secondary_metric_results: list[MetricResult]` — one
  entry per scored secondary;
* `ExperimentRecord.secondary_metric_refusals: list[NotScoreableResult]` —
  one entry per refused secondary;
* per the Q-P2b-2 disposition, the crash carrier (proposed:
  `secondary_metric_errors: dict[str, str]`, id → one-line diagnosis);
* a cross-field validator: no `metric_id` appears in more than one of the
  three carriers, and none duplicates within a carrier (per-secondary
  result/refusal exclusivity — the primary pair's validator idiom, per id);
* `HyperparamTuningOutput.secondary_metric_specs: list[MetricSpecField]` —
  the run's DECLARED set, stamped by the tuner from the bound tuple exactly
  as the 09a `metric_spec` stamp is (`:3023` precedent). Absent/empty on
  legacy outputs. This is §4.5's absence-detection source: artifact-borne,
  so it survives chain-subprocess restore and mixed legacy/new corpora —
  the same "consumers read what is persisted, never re-derive" rule P2a
  enforced for the primary.

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

---

## 5. Three-task acceptance

| task | required behaviour |
|---|---|
| TIDMAD | absence path: no secondary bound, no record field populated, no output stamp, no `_stats` key, renderer emits **zero bytes** for the section, prompts byte-identical to pre-P2b (parity sha) |
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
- [ ] Record the §2.8 disposition table in the ledger with each guard's
      current line anchor re-verified and its flipping commit named
      (C1/C2/C3 per §2.8).
- [ ] Extend the invariant's scanned-file declaration to the three P2b
      surfaces; run it green at base over the extended surface.
- [ ] Plant-and-catch on the EXTENDED scope: a synthetic secondary-operand
      ordering expression planted in one newly-scanned production file turns
      the invariant RED; revert; record verbatim output.
- [ ] Record the three Q097 guards green at base (they must be green NOW —
      if any is already red, STOP: the baseline is not what this design
      measured).
- [ ] Record TIDMAD prompt-parity baseline: the rendered-prompt sha256 of
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
- [ ] Disposition table lists EVERY §2.8 guard with a named flipping commit;
      zero guards unaccounted.
- [ ] Invariant green over the extended surface at base; plant transcript
      (RED → revert → green) recorded verbatim.
- [ ] Q097 guards measured green at base.
- [ ] TIDMAD prompt-parity sha recorded.
- [ ] Zero production files changed (`git diff --stat` recorded).

**6. Failure and edge cases.**
| case | required behaviour |
|---|---|
| a §2.8 guard is already red at base | STOP — the design's baseline is stale; re-audit before proceeding |
| the extended invariant flags an EXISTING expression | STOP and audit: either a real latent offender (a finding, filed) or a precision defect in the extension (fix the extension, never allowlist silently) |
| the plant is caught but names two sites | fix the plant to name exactly one; a multi-hit plant proves less |

**7. Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/agent/result_interpretation_agent/test_step09a_c6_evidence_projection.py -q` — record count + wall time.
- [ ] Plant transcript — record verbatim.
- [ ] `git diff --stat` — record (must show tests + this doc only).
- [ ] `ruff check` + `ruff format --check` on touched files.

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
- [ ] Re-read `_compose_metric` and `_read_manifest` at head before
      editing; extend `_MANIFEST_KEYS` (NOT `_REQUIRED_KEYS`).
- [ ] Implement `_compose_secondary_metrics`: list-shaped section
      validation, per-entry `_compose_metric` call, duplicate-id and
      primary-id-collision refusals (`TaskCompositionError`, message naming
      the colliding id and both roles), plugin + source-path collection.
- [ ] `RunTaskComposition.secondary_metrics: tuple[EvaluationMetric, ...] = ()`
      (verify the `__post_init__` derived-name guard needs no change).
- [ ] Fingerprint: append `secondary_metric_declarations` (manifest-order
      list of raw declaration dicts) to the payload ONLY when non-empty;
      secondary plugins join `plugins`.
- [ ] ContextVar pair in `evaluation_metric.py`, mirroring
      `bind_run_metric`'s shape; enter it in `bind_run_task_composition`'s
      `ExitStack`; `resolve_...` returns `()` when unbound.
- [ ] Update the Pets/DAVIS fixture manifests; TIDMAD untouched.
- [ ] Flip the Q097 binder guard per the C0 table: the binder now EXISTS in
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
- [ ] DAVIS composition carries exactly `("psnr", "mae")` with directions
      `("higher", "lower")` — opposite each other AND the `lower` primary —
      asserted as literals.
- [ ] TIDMAD/zero-secondary fingerprint byte-identical to the recorded
      pre-P2b sha; the identity is asserted against the FROZEN recorded
      value, not recomputed on both sides of one run.
- [ ] Both refusal constraints fire with messages naming the offending id.
- [ ] The Q097 binder guard is inverted and green; the other two Q097
      guards remain green (record schema and evaluator untouched here).
- [ ] `run_workflow` and the tuner are untouched (`git diff` shows neither).

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
- [ ] `.venv/bin/python -m pytest tests/unit/workflows -q -k "composition or task_composition"` — count + wall time.
- [ ] The fingerprint identity/change/reorder literals — record.
- [ ] `ruff check` + `ruff format --check`; pyright note if locally
      unrunnable (CI-owned, never claimed).

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
- [ ] Re-read the scoring block and the record/output build sites at head;
      verify where `metric_payload` enters the record and where
      `metric_spec` is stamped, and mirror both.
- [ ] Schema first: the three additive fields + crash carrier + validator;
      round-trip test before any tuner change.
- [ ] `_evaluate_secondary_metrics(sandbox, secondaries, sample_set,
      anchor_map, s_max, denoised_fn) -> (results, refusals, errors)` —
      per-secondary try: `NotScoreableError` → refusal; `Exception` → error
      entry (printed, never raised); returns typed lists.
- [ ] Call it ONLY on the primary-success path; populate the record payload
      beside `metric_payload`; stamp `secondary_metric_specs` from the bound
      tuple beside the `metric_spec` stamp.
- [ ] Verify the planner/reflector prompt serializations exclude the new
      keys (inspect the actual hidden-keys mechanism; add the keys to it if
      it is enumerated, and TEST the exclusion either way).
- [ ] StubSandbox route: confirm `StubSandbox.evaluate_metric` synthesises
      per-secondary results under each secondary's identity (it takes the
      metric argument — verify, and extend the stub minimally ONLY if
      measurement shows it collapses identities).
- [ ] Flip the two Q097 schema guards + the evaluator guard per the C0
      table, citing this commit.

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
- [ ] Primary result/status/retry byte-identical with and without
      secondaries on the same fixture (asserted on the attempt outcome
      tuple, not on prints).
- [ ] A refused secondary yields exactly one `secondary_metric_refusals`
      entry and zero attempt-lifecycle deltas; a crashing secondary yields
      exactly one error entry and zero attempt-lifecycle deltas.
- [ ] The output stamp equals the bound declared set, in order; legacy
      outputs re-validate with the fields absent.
- [ ] Planner/reflector serializations proven not to carry the new keys
      (test asserts on the serialized text, not the mechanism's docstring).
- [ ] All three Q097 guards now inverted and green.

**6. Failure and edge cases.**
| case | required behaviour |
|---|---|
| primary raises (scoring crash / not-scoreable) | `error_scoring` path byte-unchanged; NO secondary evaluation runs; no secondary fields on the error record |
| scope violation | run termination byte-unchanged; secondaries never evaluated |
| every declared secondary refuses | all-refusals record; attempt success unchanged |
| secondary evaluation crash | error entry per §12 disposition; NEVER coerced into `NotScoreableResult`; never silent |
| zero bound secondaries | empty carriers, no stamp write difference vs pre-P2b (parity) |

**7. Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/agent/tune_ml_hyperparam_agent -q -k "secondary or scoring"` plus the new module — count + wall time. (Directory name MEASURED: the tuner's unit tree is `tests/unit/agent/tune_ml_hyperparam_agent/`, not the node's own name.)
- [ ] Attempt-parity byte-comparison output — record.
- [ ] `ruff` clean; pyright CI-owned note if applicable.

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
- [ ] Re-read the summary-build path in `evidence.py` and both `_stats`
      sites at head before editing.
- [ ] Implement the projection: declared stamp × record carriers →
      scored/refused/unavailable per §4.4/§4.5; no stamp → `[]`.
- [ ] `_stats["secondary_metrics"]`: typed model_dump on write, validated
      read-back on the quiet path — the `failure_counts` idiom, asserted
      to be the SAME mechanism (one test touches both keys).
- [ ] Apply the C0 test dispositions; the upgraded tests land HERE, in the
      same commit as the behaviour they now assert.
- [ ] TIDMAD prompt parity: re-render the C0-recorded golden(s); sha256
      byte-identical.

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
- [ ] The quiet-iteration fixture shows secondaries surviving EXACTLY as
      long as failure counts — one fixture, both keys, one assertion block.
- [ ] All four projection states asserted with hand-written expected
      literals (spec ids + statuses per model), not values read back from
      the projection.
- [ ] Rendered DAVIS text contains each secondary's OWN direction words;
      an explicit assertion shows the primary's direction words absent from
      the secondary lines.
- [ ] TIDMAD prompt sha byte-identical to the C0 baseline.
- [ ] The rewritten C6 tests fail if the projection is reverted to `[]`
      (mutation recorded).

**6. Failure and edge cases.**
| case | required behaviour |
|---|---|
| records predating the fields under a stamped output | project as `unavailable` per declared spec (named absence) |
| output without a stamp (legacy) | `[]` — zero absence rows, zero rendered bytes |
| all declared secondaries refused | refusals rendered as refusals, never absence |
| `_stats` missing the key (pre-P2b cache) | absent, never fabricated |
| corrupt cached payload | validated read-back → absence + warning, no crash |

**7. Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/agent/result_interpretation_agent -q` — count + wall time.
- [ ] Quiet-iteration symmetry output — record.
- [ ] TIDMAD parity shas (C0 baseline vs C3) — record both.

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
- [ ] Three-task lifecycle fixtures per §5, each asserting the full state
      sequence (composed set → bound set → record carriers → stamp →
      projection statuses → rendered bytes/zero-bytes).
- [ ] Re-run the ordering-operand invariant over the final surface; final
      plant-and-catch (RED → revert → green) recorded.
- [ ] Confirm all §2.8 guards reached their dispositioned end-state; any
      row without a citing commit ⇒ STOP (a lifecycle stage was skipped).
- [ ] Docs sync with each documented behaviour quoted against merged
      source; tick every checklist item in this doc with evidence or an
      explicit not-run reason.
- [ ] Push ONCE at the final head; open/update the PR; ONE automatic
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
- [ ] All three §5 rows green with state-sequence evidence.
- [ ] Invariant green over the final surface; final plant RED then green,
      recorded.
- [ ] Every §2.8 row closed with its citing commit.
- [ ] Exact-head CI SUCCESS with tested SHA == final PR head, both
      recorded.
- [ ] Working tree clean; READY FOR OPERATOR REVIEW; **DO NOT MERGE**.

**6. Failure and edge cases.** A guard row with no citing commit ⇒ STOP. CI
failure ⇒ diagnose from the log, fix autonomously, push, let CI re-run
(routine, not an operator stop).

**7. Verification commands and evidence.**
- [ ] The fixture + invariant modules — counts + wall time.
- [ ] CI run id + `headSha` — record both.

**8. Commit boundary.** Fixtures + docs + ledger close. The last commit
before READY FOR OPERATOR REVIEW.

---

## 7. Preservation invariants

Primary scoring arithmetic, ordering, retry/round semantics, record frozen
names, prompts on secondary-less runs: byte-identical. The 09a carrier and
renderer: shape-unchanged. `_is_loss_shaped`: untouched. P2a's ordering
closure: zero sites re-opened (its scanner stays green over P2b's diff).
P4's Health surface: untouched. Zero-secondary composed manifests: same
semantic fingerprint as pre-P2b.

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

## 12. Open operator questions (3 — now with post-audit disposition proposals)

| id | question | disposition proposal (ratify at freeze) |
|---|---|---|
| **Q-P2b-1** | Evaluate secondaries on trial rounds too, or formal-scored records only? | **Wherever the primary evaluates** — the scoring block already runs in both modes (`execution.py:845-846`); one rule, no round-type branch. Cost note: DAVIS adds two `GlobalMseMetric` passes per scored attempt — deterministic CPU arithmetic on already-produced deliverables |
| **Q-P2b-2** | Classification of a secondary evaluation EXCEPTION | **Audit performed (§2.6).** Proposal: mirror the primary's two existing classes per-secondary — `NotScoreableError` → typed `refusal`; any other exception → `secondary_metric_errors[metric_id] = "{type}: {msg}"` (additive record field, persisted + printed, projecting as `unavailable`). Never coerced into `NotScoreableResult` (the primary's own rule at `records.py:592-623` keeps crash ≠ refusal); never silent; never touching the attempt lifecycle. The interpreter's frozen three-state carrier is untouched |
| **Q-P2b-3** | Does the interpreter's own persisted digest carry per-model secondaries for resume continuity, or is `_stats` cache-carry sufficient? | `_stats` sufficient — matches `failure_counts` exactly (measured §2.2: same write site, same read-back site); digest widening would need its own projection rule (P5 territory) and no consumer requires it |

## 13. Adversarial self-review (rev-2 additions marked ★)

| attack | answer |
|---|---|
| Can a secondary select a winner? | no production read feeds an ordering expression; invariant + extended scope + plant prove it |
| Does the DAVIS secondary inherit the primary's direction? | the carrier's `spec` is per-secondary; C3 asserts rendered direction text per metric AND the primary's words absent from secondary lines |
| Is absence honest? | `unavailable` requires the output's declared stamp; undeclared tasks render zero bytes |
| Third persistence shape? | one: the `failure_counts` idiom, asserted in the symmetry test |
| ★ Can a crash masquerade as science? | the crash carrier is textual and separate; the validator refuses an id in two carriers; §2.6's taxonomy keeps the classes apart exactly as the primary does |
| ★ Can adding the feature break existing composed resumes? | only a manifest that DECLARES a secondary changes its fingerprint (D3); the zero-secondary byte-identity test pins it |
| ★ Can the new fields leak to the LLM? | C2 asserts the planner/reflector serializations carry none of the three keys |
| ★ Did P2b quietly extend P2a's scanner or reuse its refusal formatter? | no — §2.5 records both non-uses and why; the scanner's precision contract is not diluted |
| Does P2b need P2a semantics? | only the guarantee that ordering is closed so nothing here migrates it — a sequencing dependency, not a code one |

---

*END — DRAFT rev 2, post-P2a/P4 reconciliation at `96dc1327`. NOT FROZEN;
freeze is an operator act after this revision's review. Q-P2b-1/2/3 carry
disposition proposals; the Q-P2b-2 pre-freeze taxonomy audit obligation is
DISCHARGED (§2.6). Implementation begins only after freeze, in a fresh
session, from a freshly filled Implementation Working Rules contract.*
