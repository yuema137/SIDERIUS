# Step 10 / P2b — Secondary Metric Production Transport

## 0. Status

**DRAFT rev 1 — FOR OPERATOR REVIEW. NOT FROZEN. IMPLEMENTATION NOT
STARTED.** Parent semantics complete; **implementation details subject to
post-P1-merge AND post-P2a-merge reconciliation** (labelled
`PROVISIONAL(P1)` / `PROVISIONAL(P2a)`).

| field | value |
|---|---|
| parent | Step-10 parent REVISION 2 (frozen), §3.4 / §9 / §9.4; owns scope item **S3** |
| source anchor | merged `master` = **`2393aacc`** — line anchors are evidence, not implementation authority |
| depends on | **P1** (composition schema carries the secondary declarations) and **P2a** (so the primary ordering migration is never duplicated here — parent Q-10-1) |
| Gate disposition | proposed: NO Gate — deterministic transport + carry-symmetry tests + the ordering-operand invariant are the owners (parent §22.1). Quoted against the gate standard at freeze |
| open operator questions | **3** (§12) |

**Frozen in this draft regardless of upstream shape** (operator §15): the
declaration/binding concept, the result/refusal lifecycle, persistence,
interpretation availability, the observational-only rule, and the three-task
behaviour.

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

## 2. Current source audit (at `2393aacc`)

### 2.1 The receiving side — complete, frozen, empty

* `SecondaryMetricEvidence` (`agent/schemas/interpretation.py:114`): `spec`
  (its OWN direction) + mutually exclusive `result`/`refusal`
  (validator `:149-156`), `status` property `∈ {scored, refused, unavailable}`
  (`:158-165`).
* Transport: `ModelRunSummary.secondary_metrics` (`:561-571`),
  `InterpretationOutput.per_model_secondary_metrics` (`:1272-1278`).
* Rendering: `render_secondary_metrics`
  (`agent/prompt_templates/interpretation/rendering.py:298-332`, sole caller
  `:539`).
* Producer hardcode: `nodes/result_interpretation_agent/evidence.py:486`
  `secondary_metrics=[]`, with the comment naming the missing pieces
  verbatim: *"No record-level carrier exists until Step 10 lands
  `ExperimentRecord.secondary_metric_results` and the tuner-side
  evaluation."* **The field name is therefore already reserved by the
  receiving side's own guard tests** —
  `test_step09a_c6_evidence_projection.py:379` fabricates exactly
  `secondary_metric_results` to prove the builder does not read undeclared
  keys today.

### 2.2 The cache-carry asymmetry (audit B-6) — located

`nodes/result_interpretation_agent/result_interpretation_agent.py`:
`per_model_failure_counts` is built from `inp.summaries` (`:348-352`) **and**
back-filled from the `_stats` cache (`:353-358`) because `failure_counts` is
written into `_stats` at `:526-530` ("so a model that goes quiet keeps its
failure counts… exactly as `round_health_counts` does").
`per_model_secondary_metrics` (`:361-365`) has **neither half**. The
Stability-Filter reuse path (`:455-470`, no LLM call) is the path that loses
them.

Existing golden-score carry precedents (parent §3.4): `_stats` scalar
(`interpretation_helpers.py:760`, `:783`) and `best_score_table` re-read at
`ordering.py:294`. **A secondary carrier must not become a third shape** —
§4.4 chooses the `failure_counts` precedent (typed model_dump into `_stats`,
validated read-back), which is the newest and the only one built for exactly
this quiet-model case.

### 2.3 The evaluation point and the record

* The tuner's ONE scoring route: `sandbox.evaluate_metric(...)` at
  `nodes/ml_hyperparameter_tune_agent/execution.py:882`, producing
  `MetricResult` / `NotScoreableResult` under the Step-06 order
  (scoreability BEFORE arithmetic).
* `ExperimentRecord` (`agent/schemas/hyperparam_tuning.py:298`) already
  carries the additive primary pair `metric_result` (`:659`) /
  `metric_refusal` (`:674`) with the frozen-name consistency validator
  (`:689-711`).
* `HyperparamTuningOutput.metric_spec` stamp: `:3023` (09a).

### 2.4 What the tasks declare (and the gap)

| task | declared secondary files | note |
|---|---|---|
| TIDMAD | none | absence is a supported state |
| Pets | `declared/metric_macro_f1.json` (**higher**) | `log_loss` intentionally NOT declarable (D16; `examples/oxford_iiit_pet/STATUS.md:16`) |
| DAVIS | `declared/metric_psnr.json` (**higher**), `declared/metric_mae.json` (**lower**) | the mixed-direction control: `lower` primary beside a `higher` secondary |

**Nothing in a pack marks primary vs secondary — the consumer names a
filename** (parent §3.4). The relation must become a task declaration
(§4.1). Also note: DAVIS `psnr` is `GlobalMseMetric`'s aggregation with a
`psnr_db` transform (`data_range: 1.0`) — implementation refs are per-metric,
not per-file-name.

---

## 3. Goal / semantic owner / scope

**One semantic owner: observational secondary-metric evidence, production
lifecycle end-to-end.** After P2b: a task declares its secondaries; the run
binds them beside the primary; the tuner evaluates them at the same scoring
point; records carry typed results/refusals; the interpreter receives them,
carries them across quiet iterations symmetrically with `failure_counts`,
and renders them; a declared-but-unevaluated secondary is a **named
absence**; and none of it can influence any ordering decision.

**Non-goals**: any ordering semantics (P2a's, complete before this lands);
any new rendering design (09b's renderer is reused as-is); D16/`log_loss`;
secondary-metric *history* beyond the existing cache-carry shape; dashboards
(secondaries are interpreter evidence, not dashboard rows — adding them
there is future scope, not smuggled in).

---

## 4. Design

### 4.1 Declaration + binding — `PROVISIONAL(P1)`

P1's composition schema gains an **additive** `secondary_metrics` list; each
entry = declaration ref + implementation ref, resolved through the SAME
loaders P1 built for the primary (`metric_spec_from_declaration` + plugin
ref → `EvaluationMetric`). The composed value carries
`secondary_metrics: tuple[EvaluationMetric, ...]` beside `metric`.
Constraints, frozen now:

* a secondary whose spec id equals the primary's fails composition;
* duplicate secondary ids fail composition;
* each carries its OWN direction (the carrier's existing shape);
* un-composed (legacy TIDMAD) runs have **no** secondaries — the empty
  state, byte-identical behaviour.

### 4.2 Evaluation — beside the primary, never gating it

At the tuner's scoring point (`execution.py:882` — `PROVISIONAL(P2a/P1)` for
exact signature), after the primary result/refusal is produced:

* each bound secondary evaluates the SAME deliverable through the SAME
  handle route (scoreability contract first, then arithmetic);
* a secondary refusal (`NotScoreableResult`) is captured as that
  secondary's refusal state — it never fails the attempt, never alters the
  primary result, never triggers retries;
* a secondary evaluation EXCEPTION is caught, **never silently dropped**,
  and never propagated into the attempt lifecycle — the primary's error
  semantics are untouched. **How the captured exception is CLASSIFIED is
  deliberately NOT decided here** (Q-P2b-2, OPEN): *scientifically not
  scoreable* and *plugin/runtime implementation failure* are potentially
  different failure classes, and an arbitrary exception must NOT be coerced
  into `NotScoreableResult` unless the existing contract explicitly defines
  that classification. Before P2b freezes, the existing scorer/error
  taxonomy is re-audited and the existing typed operational-error path is
  chosen if one exists.

### 4.3 Record transport — the reserved additive field

`ExperimentRecord.secondary_metric_results` (the name `evidence.py:486`
already reserves): additive, default empty, a list of typed entries each
carrying the spec identity + `MetricResult` OR `NotScoreableResult` (the
carrier-compatible pair). Frozen record names untouched; the existing
primary consistency validator untouched. Output-level: no new stamp needed —
each entry carries its own spec (`PROVISIONAL(P1)` whether the composition
also stamps the declared set on the output for absence-detection; see §4.5).

### 4.4 Interpreter projection + cache-carry symmetry (B-6, same child)

* `evidence.py` replaces the `[]` hardcode with a projection from the
  records' `secondary_metric_results` into `SecondaryMetricEvidence`
  (scored/refused), plus §4.5's named absences. The 09a-C6 guard tests that
  pinned "builder leaves empty / ignores undeclared keys" are **UPGRADED by
  disposition** (KEEP the ignore-undeclared-keys mutation; REWRITE the
  emptiness assertions into projection-correctness assertions) — recorded
  test-disposition table in the implementation ledger.
* `_stats` gains `"secondary_metrics"` written beside `failure_counts`
  (`:526-530` site) and read back beside it (`:353-358` pattern applied at
  `:361-365`), so the Stability-Filter reuse path preserves them. One
  authority shape: the same typed model_dump/validated read-back
  `failure_counts` uses — explicitly NOT a third representation.

### 4.5 Named absence

A secondary that is **declared for the run** but has no evaluation for a
record (older record, skipped evaluation) projects as
`status="unavailable"` with its spec — rendered as the named absence 09b's
renderer already supports. Detection source for "declared for the run":
the run's bound set (`PROVISIONAL(P1)`: composition on the bindings;
degraded legacy inputs have no declared set and therefore no absence rows).

### 4.6 The observational invariant, kept executable

The 09a ordering-operand AST invariant
(`test_step09a_c6_evidence_projection.py:404` region) must stay green after
activation, and its scope extends to the new production surfaces P2b touches
(tuner evaluation site, `_stats` carry, projection). P2a's scanner ignores
secondary names by construction (they are not golden-score names); the
operand invariant is the guard on this side. Plant-and-catch: a synthetic
`sorted(models, key=macro_f1)` planted in a touched scope must turn it RED.

---

## 5. Three-task acceptance

| task | required behaviour |
|---|---|
| TIDMAD | absence path: no secondary evaluated, no record field populated, no `_stats` key, renderer emits **zero bytes** for the section, prompts byte-identical to pre-P2b (parity check) |
| Pets | `macro_f1` (higher) scored beside `accuracy`: present in record → summary → rendered block; carry survives a quiet iteration (cache test); D16 note untouched |
| DAVIS | the discriminating case: `psnr` (**higher**) scored beside `mse` (**lower**) primary — the carrier's own direction words rendered, proven NOT inherited from the primary (explicit assertion on rendered direction text); `mae` exercised in the **unavailable** state on at least one fixture record; a refusal fixture (contract-failing deliverable) exercises `refused` |

All three lifecycles are proven by deterministic fixtures (L1-style), not by
Gates; the DAVIS L1 fixture shape (psnr scored, mae declared-but-unavailable)
already exists and the production path must produce what it asserts (parent
§9.3).

---

## 6. Commit decomposition (provisional pending P1/P2a reconciliation)

### C0 — invariant baseline + test-disposition table

- [ ] Record the 09a ordering-operand invariant green at base; extend its
      scope declaration to the files P2b will touch; plant-and-catch
      recorded.
- [ ] Disposition table for every 09a-C6 emptiness-pinning test
      (KEEP/UPGRADE/REWRITE per the test-disposition rule), committed before
      any behaviour changes.

### C1 — declaration + binding (composition schema extension)

- [ ] Add `secondary_metrics` to P1's composition schema + loader
      (additive); §4.1 fail-closed constraints; three-task composition
      fixtures (TIDMAD none / Pets one / DAVIS two).
- [ ] Validation: loader unit tests incl. duplicate-id and primary-collision
      refusals; un-composed runs unaffected (census).
- [ ] Acceptance: DAVIS composition carries two secondaries with opposite
      directions to each other and to the primary.

### C2 — evaluation + record transport

- [ ] Evaluate bound secondaries at the scoring point per §4.2;
      `ExperimentRecord.secondary_metric_results` additive field; refusal
      capture semantics; exception capture per the Q-P2b-2 classification
      as dispositioned at freeze (non-silent in every candidate shape).
- [ ] Validation: pseudo-mode tuner round with a stub sandbox producing
      primary + secondary results; refusal fixture; exception fixture
      (attempt lifecycle unchanged — assert retry/status identical to a
      no-secondary run); record round-trip through persistence.
- [ ] Acceptance: primary result/status/retry byte-identical with and
      without secondaries on the same fixture; secondary refusal never
      changes `status`.

### C3 — interpreter projection + cache-carry symmetry + rendering

- [ ] Replace the `[]` hardcode with the projection; named-absence rows;
      `_stats` write + read-back beside `failure_counts`; upgraded C6
      tests land here per the C0 disposition table.
- [ ] Validation: quiet-model carry test (model skipped by the Stability
      Filter keeps secondaries AND failure counts — the B-6 symmetry
      asserted on both in ONE test); rendering fixtures for all four states
      (scored/refused/unavailable/absent-entirely); TIDMAD prompt parity
      (zero-byte section).
- [ ] Acceptance: the quiet-iteration fixture shows secondaries surviving
      exactly as long as failure counts; TIDMAD parity sha recorded.

### C4 — invariant closure + docs + ledger

- [ ] Ordering-operand invariant re-run over the final surface with the
      §4.6 plant; three-task L1-style end-to-end fixtures (declaration →
      rendering) green; docs sync; ONE exact-head CI.
- [ ] Acceptance: invariant green + plant RED recorded; CI id recorded.

Per-commit rules (corrected 2026-08-20 — per-commit operator approval was a
process error): **semantic commits are autonomous** — inspect the diff
scope, run the cheapest authoritative targeted validation, update the
ledger, commit if coherent; pause only for a genuine material deviation or
at the terminal READY FOR OPERATOR REVIEW. Targeted suites only; evidence in
the ledger before ticking.

---

## 7. Preservation invariants

Primary scoring arithmetic, ordering, retry/round semantics, record frozen
names, prompts on secondary-less runs: byte-identical. The 09a carrier and
renderer: shape-unchanged. `_is_loss_shaped`: untouched.

## 8. Failure / edge cases

Secondary impl import failure at composition (fail closed, P1's loader);
secondary refusal on every record (all-refused renders refusals, not
absence); records predating the field (default empty → absence rows when
declared); a task declaring zero secondaries (TIDMAD path — first-class);
cache entries predating the `_stats` key (read-back treats missing as
absent, never fabricates).

## 9. Upstream-sensitive assumptions (reconcile before freeze)

1. `PROVISIONAL(P1)`: composition schema shape, bindings field spelling,
   whether the declared set is stamped on the output for absence detection.
2. `PROVISIONAL(P2a)`: the scoring call-site signature and any refusal-notice
   helper reuse.
3. Line anchors in §2 (P1 edits `model_exploration.py`; P2a edits the
   proposer helper and consumers).

## 10. Cross-child ownership statements

* P2b introduces **no** metric-order authority and re-migrates **no** P2a
  site (§9.4 item 8 — checked by P2a's scanner staying green over P2b's
  diff).
* P2b extends P1's composition schema **additively** — no competing
  `WorkflowRunBindings` field (the secondaries ride the same
  `task_composition` value).
* P2b touches `evidence.py` / `result_interpretation_agent.py` for
  projection/carry only; P3's reader architecture is untouched (P3 lands
  after, consuming whatever the typed output carries).

## 11. Risk register

| risk | mitigation |
|---|---|
| secondaries acquire a vote via a "helpful" ordering line | §4.6 invariant + plant; review trigger |
| a third carry representation appears | §4.4 names the `failure_counts` precedent as THE shape; test asserts both ride the same `_stats` write |
| C6 emptiness tests deleted instead of upgraded | C0 disposition table first, behaviour later |
| secondary exception breaks an attempt | §4.2 capture semantics + the byte-identical-lifecycle test |
| TIDMAD prompt drift | zero-byte-section parity check in C3 |

## 12. Open operator questions

| id | question | proposal |
|---|---|---|
| **Q-P2b-1** | Evaluate secondaries on trial rounds too, or formal-scored records only? | wherever the primary evaluates — one rule, no round-type branch |
| **Q-P2b-2** | Classification of a secondary evaluation EXCEPTION | **OPEN / PROVISIONAL (operator ruling 2026-08-20: must re-audit the existing scorer/error taxonomy before P2b freeze).** Frozen draft-stage rule only: exceptions never disappear silently, and an arbitrary implementation exception is NOT coerced into scientific `NotScoreableResult` unless the existing contract explicitly supports that classification. *Scientific scoreability refusal* vs *plugin/runtime implementation failure* stay distinct candidate classes until the taxonomy audit chooses the existing typed path |
| **Q-P2b-3** | Does the interpreter's own persisted digest carry per-model secondaries for resume continuity, or is `_stats` cache-carry sufficient (proposed)? | `_stats` sufficient — matches `failure_counts` exactly; digest widening would need its own projection rule (P5 territory) and is not required by any consumer |

## 13. Adversarial self-review (draft-stage)

| attack | answer |
|---|---|
| Can a secondary select a winner? | no production read feeds an ordering expression; invariant + plant prove it |
| Does the DAVIS secondary inherit the primary's direction? | the carrier's `spec` is per-secondary; C3 asserts rendered direction text per metric |
| Is absence honest? | `unavailable` requires a declared set; undeclared tasks render zero bytes |
| Third persistence shape? | one: the `failure_counts` idiom, asserted in the symmetry test |
| Does P2b need P2a semantics? | only the guarantee that ordering is already closed so nothing here migrates it — a sequencing dependency, not a code one |
