# Step 06 — Metric interface — detailed design (FROZEN)

Roadmap §15 step 6, module §10. Roadmap row §15.1 `§10 Metric interface`.
Post-Step-05 addendum: roadmap **§20** (the semantic authority for the two
obligations this step inherits beyond §10).

| Field | Value |
|---|---|
| Status | **STEP 06 — IMPLEMENTED ON PR #213, CORRECTIVE ROUND COMPLETE, READY FOR OPERATOR REVIEW (2026-08-15) — NOT MERGED.** Design FROZEN and operator-approved 2026-08-15; implemented on `feat/generic-framework-step-06-metric-interface` (base `530f574c`). Round 1 executable head `15c4dd08` (CI 31874417871); operator adversarial review → corrective round (§20.11): executable head `14591821` (CI run 31903559222 SUCCESS); the docs-only closeout commit after it carries its own CI run — the exact merge head is what PR #213 shows and its three-way identity is read at close. §20 is the ledger; §19 checklists all `[x]`; §12 criteria all `[x]` with evidence; Gate 1 PASS (corrective, §20.11), Gate 2 NOT REQUIRED. §16's Q1-Q6 all resolved. §18 remains the Definition of Done — **freeze ≠ done**; post-merge finalizer pending. Revision history: rev 4 per-commit checklists after seam inspection; rev 3 ownership wording, scoreability scope, Gate 2 source-grounded NOT REQUIRED, two-route parity as compatibility; rev 2 scalar-mandatory semantics, executable scoreability, DeliverableSpec/ScoreabilityContract split, 06/12 declaration split; rev 1 initial draft. |
| Design base | master `75525dc9` (Step 05 COMPLETE: 05a `cfb3b1c7`, 05b `5ce205d3`, 05c `03e00944`; finalizer `75525dc9`) |
| Depends on | Step 02 (`DatasetProfile`) · Step 03 (`ModelIOContract`) · Step 05c (`DeliverableSpec`, provisional) · roadmap §10, §14, §16, §20 |
| Owns | the **EvaluationMetric** interface; the **evaluation-vs-training-diagnostics boundary** (by exclusion); the **Deliverable-Contract confirm-or-say-why review** |
| Does NOT own | `TrainingHistory` / `TrainingDiagnosis` (Step 07, §20.2) · incumbent/threshold/skip-bypass policy (Step 07a) · HealthGate semantics (Step 08) · Interpreter consumption (Step 09) · the executable data path (D14, §20.5) · the two composed contrast tasks (Step 12 / M1, §20.3) |
| Risk | Medium-high: it touches the frozen scientific formula's *call path* (never its arithmetic) and the record payload every downstream reader keys on |
| Remaining operator decisions | none — §16's Q1-Q6 all resolved at freeze (row kept for history) |

---

## 0. Scope / capability

**Observable final capability (FROZEN):**

> A task declares ONE primary evaluation metric — named, with explicit
> direction and aggregation, a mandatory scalar result, optional
> structured/per-sample evidence, optional reference baselines, and an
> EXECUTABLE scoreability contract on the persisted deliverable that is
> evaluated BEFORE metric arithmetic — and PRODUCTION SCORING invokes it
> through that interface. The frozen TIDMAD scorer is instance #1,
> byte-identical in every value it produces. Optional secondary metrics are
> expressible. The metric's identity, direction and value are machine-readable
> on every record. **Training loss and validation loss are NOT evaluation
> metrics** and this step establishes that boundary by exclusion, leaving the
> generic surfacing mechanism to Step 07.

**Explicitly claimed**: metric identity · direction · aggregation semantics ·
mandatory scalar result · optional structured/per-sample evidence ·
reference/baseline slot · an EXECUTABLE scoreability contract · one production
consumer (scoring) through the handle · record-facing payload · the TIDMAD
instance byte-identical.

**Explicitly NOT claimed** (each has an owner): incumbent selection,
best-score comparison, direction-sensitive thresholds, skip/bypass — Step 07a
(roadmap :1394, "freeze reconciliation 2"); training diagnostics — Step 07;
HealthGate checks — Step 08; the Interpreter's sign-band and
`*_denoising_score` field consumption — Step 09 / D1; dashboard/resume
direction literals — D1 (M2 blocker, roadmap :1035-1040); the executable data
path — D14; renaming `denoising_score` — D1, **not authorized**.

## 1. Current-state evidence (audit at `75525dc9`)

### 1.1 The frozen scorer and its two entry points

| Fact | Evidence |
|---|---|
| The formula: PSD → peak → SNR → per-segment anchor-normalised → linear grand-mean → `log_5.27` | `execute_tools/scoring_utils.py:104-264` (`get_one_sec_psd`, `get_snr`), `:490-610` (`score_vector`); `scoring_helpers.py:36` `_LOG_BASE = 5.27` |
| **Two live entry points.** (i) In-process: the tuner calls `sandbox.score_vector(...)` directly (`ml_hyperparameter_tune_agent.py:5321-5326` → `TidmadSandbox.score_vector` `sandbox_executor.py:1858-1897` → `scoring_utils.score_vector`). (ii) Subprocess: `TidmadSandbox.execute_scoring` spawns `denoising_score_single.py` (`sandbox_executor.py:1899-1971`) — used by `scripts/run_comparison.py:241` and `agent/skills/denoising_score_skill/wrapper.py:12`, **not by the tuner's live round path** | the tuner's scoring is in-process; §7c's "isolated argv contract" note (roadmap :843-844) describes route (ii). **Positioning (revision 3): the two-route equality is a COMPATIBILITY / route-parity obligation for the two existing TIDMAD entry points — not a requirement that every future metric expose two scoring routes.** Step 06's genericity target is `metric handle → production scoring`; the second route is legacy/helper infrastructure that must keep agreeing |
| Return shape | `score_vector -> tuple[file_vector, scalar]` (2-tuple, "pure scoring" per CLAUDE.md invariant); `denoising_score_single.py:220-227` merges `denoising_score` + `file_vector` into `--output_json` |
| Record payload | `ExperimentRecord.denoising_score / file_vector / score_table` (`hyperparam_tuning.py:381-399`); tuner writes them `:5780-5786`; `ScoreComparisonTable` built at `:5538` |
| Direction is implicit and repeated | `max(...)` / `>` at tuner `:5608-5613`, `:5701`; workflow `model_exploration.py:2740`; `core/resume.py:438`; `per_file_best._row_beats` :478-480; dashboard `local_json.py:245`, `base.py:119` — roadmap :1029-1040 |
| Metric-identity precedent already in-tree | `execute_tools/per_file_best.py:358-362` emits `metric_id: "tidmad_denoising_score"`, `score_transform: "log"`, `log_base`, key set pinned by `tests/unit/execute_tools/test_per_file_best.py:719`. Roadmap :1058-1063: the interface **EXTENDS this precedent** |
| Reference/baseline | the raw-baseline row in `ScoreComparisonTable` (`agent/schemas/score_table.py`), the committed anchor map + 42 reference JSONs (roadmap :1033), `baseline_record` lookup by exp_id substring `"baseline"` (`ml_hyperparameter_tune_agent.py:5605-5607`) |
| Scoreability | **none today** — `_is_complete_trial_output` (`inference_single.py:84-126`) is a crash-resume REUSE guard, never consulted by scoring; a wrong-shaped artifact errors inside the scorer worker (roadmap :1052-1058). It must **NOT** be relocated into scoreability |
| Authority layer is metric-blind | `ScientificAuthority` consumes three non-score facts; frozen 3×3×3 matrix test (roadmap :1043-1046) — an invariant to preserve |

### 1.2 The deliverable, as the scorer actually consumes it (§20.4 finding)

`scoring_utils.py:160-163` reads `attrs["voltage_range_mV"]` and
`attrs["sampling_frequency"]` from `timeseries/channel0001` of the
**denoised deliverable**, and `get_one_sec_psd(..., ch=1/ch=2)` (`:261-264`,
`:396-401`) addresses channels positionally. 05c §0.3 left the five instrument
attrs literal because "no production consumer reads the attrs at all" — **the
frozen scorer is such a consumer** (two of the five). This is direct evidence
that final evaluation depends on the deliverable's *interior* (layout, attrs,
channel addressing), not only its name. §4 below draws the consequence.

### 1.3 Training-side facts this step must NOT absorb

Restated from roadmap §20.2 for self-containment: train loss exists per epoch
(`train_engine_sandbox.py:1178-1179`), rides `experiment_results_*.json` →
`execute_training` → `ExperimentRecord.loss_history` (`hyperparam_tuning.py:371`),
has **zero readers**; validation loss does not exist; the reflector prompt
substitutes the final score for it (`agent/prompts.py:232-238`). All of that
is Step-07 territory.

## 2. Problem statement

1. Metric **identity, direction and aggregation** are implicit and repeated
   across ≥8 consumer families; nothing declares them once. A lower-is-better
   task cannot be expressed without editing every `max`/`>`.
2. There is **no scoreability contract**: what makes a deliverable scoreable
   is whatever does not crash inside the scorer worker.
3. The **evaluation-vs-training-diagnostics boundary** is undefined, and the
   reflector already conflates them (§1.3). Left undefined, Step 07's
   `TrainingHistory` will either be forced into the metric interface or
   invent a parallel one.
4. The **Deliverable Contract has no confirmed owner**, and §1.2 shows the
   scorer has a real stake in its interior.

## 3. Design principles / invariants (binding on the freeze)

- **Extract from the working system** — the interface is defined FROM the
  TIDMAD instance and extends `per_file_best`'s `metric_id` precedent; no
  parallel invention (roadmap :1058-1065).
- **The frozen formula is byte-identical** in every value it produces;
  `_LOG_BASE`, `s_max`, formula internals are the *instance's own constants*,
  never config (roadmap :1067-1069; CLAUDE.md "metric is the frozen task
  definition").
- **`score_vector` stays a pure 2-tuple** (CLAUDE.md subsystem invariant); the
  handle wraps, it does not change the arithmetic entry.
- **`denoising_score` field names are a schema-compatibility surface**;
  renaming is D1 and NOT authorized. New payload is **additive**.
- **No new top-level config hierarchy** for metrics. Metric identity lives
  in the task's existing configuration architecture as an additive block, or
  is derived; model/loss/train/tuner/profile configs are untouched (§20.6).
- **One semantic authority** for direction: after this step, the metric
  handle declares it; consumers this step *reaches* read it; consumers it
  does *not* reach are enumerated honestly (§10.5-style D1 statement,
  roadmap :1040-1043).
- **Losses are not metrics.** Stated once, in §7, and enforced by a
  negative test (§11).
- **Regime A preserved**: an existing TIDMAD caller that declares no metric
  resolves to the TIDMAD instance, deep-equal (roadmap §2 regime A).

## 4. Metric semantics

**What an EvaluationMetric IS (FROZEN definition):**

> A named, directional evaluation of the **persisted scientific deliverable**
> of one attempt: it produces a **primary scalar result** (mandatory) and
> MAY produce structured / per-sample evidence when the metric naturally
> decomposes that way (optional); declares whether higher or lower is
> better; declares how any per-sample evidence aggregates to the scalar; may
> carry reference baselines against which the scalar is interpreted; and
> declares an EXECUTABLE scoreability contract stating what the deliverable
> must satisfy before the metric is computed at all.
>
> A metric with only a scalar (e.g. `accuracy = 0.93`, a global statistic)
> is a first-class instance. TIDMAD's `scalar + length-20 file_vector` is
> instance #1, not the template. *(Revision 2: revision 1 made the
> per-sample vector part of the definition, which would have over-fitted
> the interface to TIDMAD's shape.)*

**What it is NOT**: a training observation (no deliverable, no baseline, no
task-independent direction — roadmap §20.2); a health verdict (Step 08); a
policy (Step 07a).

**Semantic components — FROZEN as the component list; field names remain
implementation detail (§19):**

| Component | TIDMAD instance | Generic meaning |
|---|---|---|
| identity | `tidmad_denoising_score` (`per_file_best.py:360`) | stable id; the record key set extends around it |
| direction | higher-is-better | `higher \| lower` — explicit, never inferred |
| structured / per-sample evidence (**optional**) | length-20 `file_vector` (dense; `None` for out-of-scope files) | when the metric decomposes per input identity, values indexed as roadmap §4.3 says ("INDEXED by input identity"); absent for scalar-only metrics |
| aggregation | anchor-normalised linear grand-mean → `log_5.27` | declared aggregation semantics; the TIDMAD one is the frozen instance's own function |
| references | raw baseline (`ScoreComparisonTable` raw row), anchor map, `baseline` exp_id | optional named references the interpretation layer may compare against |
| scoreability (**mandatory component; executable**) | (none today — a wrong artifact simply crashes the worker) | a **fresh** ACCEPTANCE contract on the deliverable, evaluated BEFORE metric arithmetic: required channels · required attrs · required dtype/range · required completeness. Failure yields a **structured not-scoreable result**, never an incidental scorer exception. `_is_complete_trial_output` stays a crash-resume REUSE guard and is NOT the mechanism |
| transform | `score_transform: "log"`, `log_base` | already emitted by `per_file_best`; carried, not re-declared |

**Deliverable-Contract ownership — the confirm-or-say-why (OD-20-7).**
**Q1 — CONFIRMED by the operator at freeze (2026-08-15)** (wording sharpened at
revision 3 so it cannot be read as "the metric owns deliverable semantics"): **Step 06
owns the evaluation-side ACCEPTANCE contract and the deliverable facts
required for scoreability, while Step 05c retains EXCLUSIVE ownership of
producer-side representation semantics.** The metric may *reference*
`DeliverableSpec`; it never redefines it. The evidence is §1.2 (the scorer
reads attrs and addresses channels inside the artifact). The split is exact,
and it is what stops two things owning the interior at once (roadmap §20.4):

```text
DeliverableSpec  (05c, RETAINED, producer-side)   "how the artifact IS represented"
    naming · cleanup identity · channel-group names · storage layout/serialization ·
    storage dtype + offset

Metric ScoreabilityContract  (Step 06, evaluation-side)   "what THIS metric REQUIRES"
    required channels · required attrs · required dtype/range · required completeness

Metric  REFERENCES DeliverableSpec  +  DECLARES ScoreabilityContract
```

Under this split the two attrs the scorer reads (`voltage_range_mV`,
`sampling_frequency`) become **required attrs of the TIDMAD metric's
acceptance contract**; how they are *written* stays with the producer
(05c left them literal in `create_abra_file`; whether the writer should
derive them from a declaration is a producer-side question that this
confirmation makes answerable but does not answer). Neither contract
absorbs the other's half. **Not confirmed here** — the operator confirms at
freeze (§16-Q1). If deferred, the reason must name the consumer evidence
still missing. *(Resolved: CONFIRMED — the confirmation stands as written above.)*

## 5. Metric schema / representation (FROZEN as to shape and rules; field names are implementation detail)

Smallest additive shape that carries the §4 components and extends the
existing precedent — **field names are illustrative, not frozen**:

```text
MetricSpec (typed runtime value, derived or declared additively)
  id:            str          e.g. "tidmad_denoising_score"
  direction:     "higher" | "lower"
  aggregation:   str          identity of the aggregation rule (TIDMAD: the frozen instance's own)
  transform:     str | None   e.g. "log";  transform_params e.g. {"log_base": 5.27}
  references:    list[str]    named reference kinds available (e.g. "raw_baseline")
  scoreability:  ScoreabilityContract   what the deliverable must satisfy

MetricResult (per attempt, on the record — ADDITIVE beside denoising_score/file_vector)
  metric_id, direction, scalar, per_sample (or a pointer to file_vector), references_used
```

Constraints: `MetricSpec` is a **typed runtime value** in the 05c
`DeliverableSpec` mould — not user-authored YAML, not a new top-level config
file; the TIDMAD instance is derived with **no declaration** (regime A).

**Step 06 vs Step 12, stated so implementers do not edit `task_config.yaml`
here (DECIDED, roadmap §20.3):**

```text
Step 06   the generic metric RUNTIME INTERFACE + the TIDMAD DERIVED instance
Step 12   task-level metric DECLARATION / BINDING for the composed contrast tasks
```

When a declared form is needed (Step 12), it is an **additive block inside
the existing task configuration** (`configs/task_config.yaml` already hosts
`forward_contract`), never a new hierarchy — and its physical placement is
D4/D12 territory. `ScoreabilityContract` is part of `MetricSpec` and is
**executable**: `validate(deliverable) -> ok | structured failure`, invoked by
the handle before arithmetic on both scoring routes.

**Semantic scope of scoreability — bounded (revision 3, §16-Q3).** Step 06
freezes the EXECUTION semantics of the contract — validate before
arithmetic; structured failure on rejection; the reuse guard is not the
mechanism — and **does NOT impose a universal, task-independent schema for
"completeness", "required channels" or "required shape"**. Those
requirements are declared **per metric instance**, against the
producer-side `DeliverableSpec`. "Completeness" for TIDMAD means every
in-scope file has a per-file output; for a dense-prediction task it may
mean output geometry matches target geometry; for a global scalar
regression it may mean one value exists. A generic `required_num_files /
required_channels / required_shape` schema would be the TIDMAD shape
re-declared as the universal one — exactly the anti-goal roadmap §21.10
names. Any future shared vocabulary here is evidence-driven (§21.4/§21.8),
not designed in Step 06.
**Existing fields are untouched**: `denoising_score`, `file_vector`,
`score_table` keep their names and semantics; `MetricResult` sits beside
them so historical records validate unchanged.

## 6. Primary / secondary / mandatory metrics

- **Exactly one PRIMARY metric per task** — the one incumbent selection
  (Step 07a) will use. Mandatory. TIDMAD's is `tidmad_denoising_score`.
- **Secondary metrics — optional, zero or more**, recorded but never
  consulted by policy in this step. Whether TIDMAD gets any secondary
  instance in Step 06 is **§16-Q4 — DECIDED: none** (nothing in-tree consumes
  one; §0 rule 8).
- **Mandatory components** of any metric: id, direction, aggregation.
  **Optional**: references, transform, secondary metrics.
- **Not a metric, not optional-metric**: train/validation loss — see §7.

## 7. Interaction with training diagnostics — the boundary (DECIDED)

Per roadmap §20.2 and operator decisions OD-20-4/5:

```text
Step 06 owns:   EvaluationMetric  — the persisted deliverable's quality
Step 07 owns:   TrainingHistory   — raw training observations
                TrainingDiagnosis — deterministic derivation, tuner-computed
Step 08 owns:   HealthGate        — validity/pathology of the result
```

Step 06's obligations at this boundary, all **by exclusion**:

1. The `MetricSpec`/`MetricResult` types carry **no field** for train or
   validation loss, and the freeze forbids adding one.
2. A negative test asserts that constructing a "metric" whose identity is a
   loss (or feeding `loss_history` into `MetricResult`) is rejected — the
   boundary is executable, not prose (§11).
3. Step 06 leaves `ExperimentRecord.loss_history / final_loss` **exactly as
   they are** — Step 07 extends them additively.
4. Step 06 does NOT define how losses are surfaced to agents; it records that
   the generic surfacing mechanism is Step 07's `TrainingDiagnosis` +
   Step 09's consumption (OD-20-5), and that the reflector prompt change
   makes Step 07a's Gate 1 REQUIRED (OD-20-6).

**Why exclusion is the whole of Step 06's job here**: the audit's Option A
("losses become metrics") and Option D ("one lifecycle-tagged
`MetricObservation`") were both rejected in the roadmap (§20.2) on semantic
grounds; the framework's own `RuntimeObservation` (`core/runtime_control/
records.py:1-27`) already demonstrates the never-conflate discipline. Step 06
implementing any half of `TrainingHistory` would pre-empt Step 07's design
and its (mandatory-when-available validation-loss) rules.

## 8. Agent-facing representation

Step 06 changes **no prompt** (see §13). The metric's agent-facing form
today is `ScoreComparisonTable` (pre-rendered markdown substituted into four
prompts, `hyperparam_tuning.py:389-399`) plus the `denoising_score` scalar
in `reflection_context`. Step 06 makes the metric's **identity and
direction machine-readable** on the record so that Step 07a can render
direction-aware prose ("higher is better" is currently prompt-hardcoded,
`agent/prompts.py:245-249`) and Step 09 can consume identity — but the
rendering itself is theirs. Full per-sample vectors are already not sent raw
to LLMs; that stays.

## 9. Persistence / transport boundary

- **In-process route** (tuner → `sandbox.score_vector`): the handle is
  resolved in the tuner's run scope beside `run_profile`, `run_model_io`,
  `run_deliverable_spec` (`ml_hyperparameter_tune_agent.py:3704-3740`), and
  `sandbox.score_vector` is invoked *through* it. No IPC involved.
- **Subprocess route** (`execute_scoring` → `denoising_score_single.py`):
  reuses the existing argv/`--output_json` contract; the child derives the
  same TIDMAD instance from what already crosses (`--dataset_profile_json`)
  — the 05c §3.2a Option-A pattern. **No new argv** unless the design proves
  one unavoidable, in which case the Stage-A claim is downgraded in writing,
  never quietly restated (05c precedent).
- **Record**: additive `MetricResult` on `ExperimentRecord`; `save_record`
  and `coerce_nonfinite_to_none` unchanged. `HyperparamTuningOutput`'s
  `best_*_denoising_score` fields untouched (D1).
- **Cross-iteration**: nothing new — identity/direction on the record is
  sufficient for Steps 07a/09; no new store (§20.2 rule).

## 10. Compatibility / historical replay

- Frozen-formula byte identity: existing pins + the offline scalar baseline +
  the `real_run` legacy parity test (roadmap :1074-1075) — all must pass
  unchanged.
- `per_file_best` key set pinned at `test_per_file_best.py:719` — extended
  additively if at all, never reshaped.
- Every committed historical `ExperimentRecord`, `HyperparamTuningOutput`,
  `InterpretationOutput` and `run_output_*.json` validates unchanged (new
  fields optional-with-default).
- Regime A: a caller declaring no metric resolves the TIDMAD instance,
  deep-equal to today's values, on both routes.
- Model/loss/train/tuner/profile configs: **untouched** (§20.6).

## 11. Tests / parity / mutation strategy (cheapest sufficient evidence first)

| Rung | What | Existing or new |
|---|---|---|
| Checkpoint 0 | capture the **two-route parity oracle** — the exact **existing TIDMAD scoring result and its key/output shape** (today: scalar + `file_vector`) for a fixed synthetic deliverable via BOTH `sandbox.score_vector` and the `execute_scoring` spawn, plus the `per_file_best` key set. Worded as the *existing TIDMAD result*, not as `(file_vector, scalar)`, so a future scalar-only metric is not bound by this oracle's shape (revision 3) | new (the routes have never been pinned as equal to each other) — a **compatibility** capture, not a generic-metric requirement |
| Stage A | frozen-formula pins, offline scalar baseline, `real_run` legacy parity, historical record/output validation | existing + one replay test |
| Stage B (atomic, one axis) | **metric-direction axis**: a lower-is-better scalar metric on stub outputs enters the record through the handle with `direction="lower"` and TIDMAD's identity/direction unchanged (roadmap §10.5). *Under roadmap §21.4 this is an ATOMIC fixture on the **learning-objective** coverage dimension at TIDMAD's topology — the cheapest Stage-B grade Step 06's abstraction can honestly support (§17 Checkpoint B, Rev 4); no image/spatiotemporal track is required of Step 06.* | new |
| Boundary negative | a loss-shaped "metric" is rejected; `loss_history` cannot populate `MetricResult` | new (§7) |
| Scoreability negative | a deliverable missing a required channel / attr / with the wrong dtype / incomplete sample set yields a STRUCTURED not-scoreable result BEFORE `score_vector` runs, on both routes; the reuse guard is untouched | new (revision 2) |
| Structural guard | no owned scoring consumer executes a hardcoded direction where the handle is available; the TIDMAD `metric_id` literal is declared once (05c "declared exactly once" pattern) | new |
| Mutations (per semantic family, count not frozen) | identity swap · direction flip · aggregation substitution · **scoreability bypass (validate skipped → arithmetic reached on an invalid artifact)** · route divergence (in-process vs subprocess) | new; site count asserted 1, restored from clean, baseline re-verified — 05c hygiene |
| Checkpoint C | a **real** `execute_scoring` subprocess scores a real small deliverable through the handle; result equals the in-process route; helper-only is insufficient (05c §6 discipline) | new (reuse the 05c Checkpoint-C harness) |

Deliberately NOT tested here: incumbent selection under a lower-is-better
metric (Step 07a), Interpreter rendering (Step 09), dashboards (D1).

## 12. Checkpoint / acceptance criteria (semantic)

- [x] a task can declare ONE primary metric; secondary metrics are optional — `MetricSpec` (one instance bound per run as `run_metric`); secondary metrics representable as further `MetricSpec`s, none for TIDMAD (§16-Q4); §20.3
- [x] identity, direction and aggregation are explicit and machine-readable on every record — `MetricSpec.id/direction/aggregation`; `ExperimentRecord.metric_result.{metric_id,direction,scalar}` on every scored record; §20.6
- [x] PRODUCTION SCORING (the tuner's live route) invokes the frozen TIDMAD instance THROUGH the handle — `sandbox.evaluate_metric(run_metric, …)`; reachability by contrast handle through the real `run()`; mutation 7 red; §20.4, §20.9
- [x] the two scoring routes produce equal `(file_vector, scalar)` for the same deliverable — C0 oracle (real child) and Checkpoint C (real chain): exact equality; §20.2, §20.9
- [x] the frozen TIDMAD values are byte-identical; `_LOG_BASE`/`s_max`/formula untouched — `scoring_utils.py` has NO diff on the branch; C0 literals reproduced through the handle; frozen numeric pins green; §20.4
- [x] historical records/outputs validate unchanged; regime A resolves TIDMAD deep-equal — pre-Step-06 record dicts + committed `run_output_iter_001.json` validate; `score_vector` (no metric) == handle values; §20.4, §20.6
- [x] `denoising_score`/`file_vector`/`score_table` names and semantics unchanged — schema diff is additive only (54 → 56 fields, earlier positions unchanged); §20.6
- [x] the metric types carry no loss field, and the negative test reds if one is added — `extra="forbid"`, loss-shaped ids refused on all three types, structural no-loss-field assertion; §20.3, §20.7
- [x] **the metric's scoreability contract is EXECUTABLE and is evaluated BEFORE metric arithmetic on both scoring routes; an invalid deliverable produces a structured not-scoreable result rather than an incidental scorer exception** (revision 2) — route (i): spy proves `score_vector` never entered on refusal, `NotScoreableError` → `error_scoring` + `metric_refusal`; route (ii): real child refuses int16 / missing deliverable with structured stderr + `not_scoreable` payload, no traceback; mutation 4 red; §20.4, §20.5, §20.9
- [x] `_is_complete_trial_output` is unchanged and is NOT the scoreability mechanism (roadmap :1052-1058) — `inference_single.py` has no diff; forbidden consumer in the Step-06 census; §20.4
- [x] a scalar-only metric instance (no per-sample evidence) is constructible and enters the record through the handle (revision 2) — C1 constructibility; C6 `MeanAbsAmplitudeMetric` (lower, `per_sample=None`) through the real seam and into the record; §20.3, §20.8
- [x] Deliverable-Contract ownership is CONFIRMED or DEFERRED-with-reason in the ledger (OD-20-7), under the `DeliverableSpec` (representation) / `ScoreabilityContract` (acceptance) split — **CONFIRMED** (§16-Q1 at freeze; §20.10 verdict) and exercised: the contract READS channel group + dtype from `DeliverableSpec`, and Checkpoint C shows the real producer's artifact satisfies the acceptance contract; §20.3, §20.9
- [x] no new top-level config hierarchy; model/loss/train/tuner/profile configs untouched — `configs/` has no diff on the branch; the metric is a runtime value; §20.3
- [x] no new independent state store; no new argv (or an honestly downgraded Stage-A claim) — `execute_scoring` argv golden byte-identical (C0 → C3); the child derives from `--dataset_profile_json`; §20.5
- [x] the enumerated list of direction consumers this step does NOT reach is recorded (D1) — 9 sites asserted in `test_step06_c5_boundary_and_structure.py`; §20.7

## 13. Gate disposition — SOURCE-GROUNDED (revision 3)

Roadmap §17.0 is binding: a design that names a Gate must **open
`docs/gates/gate_testing_standard.md`, quote its "Gate assignment by commit
type" row, and decide from that** — never from a sense that a change "feels
important". Revision 2 violated this: it recommended Gate 2 REQUIRED because
"the tuner's live scoring route changes call path", which is not a criterion
the standard or §17 recognizes. Corrected here from the two authorities,
quoted.

**The standard's assignment table** (`docs/gates/gate_testing_standard.md`,
"Gate assignment by commit type", read at design time 2026-08-15):

```text
| Config files, YAML, schema-only          | Unit only                     |
| New loader/renderer (pure Python)        | Unit only                     |
| Prompt placeholder substitution          | Unit only + optional Gate 1   |
| New LLM-facing system prompt             | Gate 1                        |
| New agent node or workflow wiring        | Gate 1                        |
| Checkpoint (end of feature)              | Gate 2                        |
| Loss function generation (L4)            | Gate 1 (dummy-tensor) + Gate 2 at Checkpoint L |
```

**Roadmap §17, the sentence that names this exact case** (quoted):

> "Bounded real Gates: conceptually REQUIRED … for modules that change real
> execution behavior — §7c, §7e, §9, and §8's blocking-verdict changes; **NOT
> required for prompt/config/metric-handle extractions whose parity is fully
> deterministic.**"

Step 06 **is** the metric-handle extraction. Its Stage-A parity is fully
deterministic (byte-identical formula values; the two-route oracle; historical
record validation), and its live-integration evidence is Checkpoint C through
the **real** `execute_scoring` subprocess. There is no LLM-visible change and
no execution-surface expansion (the arithmetic, the deliverable and the
subprocess contract are untouched; only the call path is routed through the
handle). The closest landed precedent, Step 04b, disposed Gate 2 NOT REQUIRED
on the same "authority/source change, no execution-surface expansion" ground.

| Gate | Disposition | Ground (quoted above) |
|---|---|---|
| Gate 1 | **NOT REQUIRED** | no new LLM-facing prompt, no new agent node/wiring, no placeholder change (§8). **Flip**: any prompt byte or `LLMBridge` kwarg change |
| Gate 2 | **NOT REQUIRED** | roadmap §17: metric-handle extraction with fully deterministic parity; the standard's only Gate-2 rows are "Checkpoint (end of feature)" and L4, neither of which describes Step 06's change. **Flip**: if implementation finds the handle must change scorer arithmetic, deliverable bytes, or the subprocess argv contract — any of which would make parity non-deterministic and re-open this row |

**What replaces the Gate as evidence**: Checkpoint C (real subprocess), the
two-route oracle, the scoreability-negative rung and the mutation families
(§11). **§16-Q5 resolved at freeze: Gate 2 NOT REQUIRED and not elected**; this
section records that the standard does **not** require it.

## 14. Rollback boundary

One PR (§15). Reverting it restores: the direct `sandbox.score_vector` call
path, the untouched record schema (new fields were optional), and the
absence of the metric module. Nothing in `scoring_utils.py`'s arithmetic,
`per_file_best`'s existing keys, or any config file is changed, so rollback
is a pure removal.

## 15. Dependencies and future-step boundaries; PR decomposition

**Depends on**: 05c's `DeliverableSpec` (reads it; does not modify it unless
the ownership confirmation moves attrs — then additively).
**Feeds**: Step 07a (metric handle for policy; the boundary for
`TrainingHistory`), Step 08 (scoreability/reader seam), Step 09 (identity),
Step 12 (a declared metric for each composed contrast task).

**PR decomposition — ONE PR (DECIDED at freeze).** The interface, the
scoring-consumer migration, the record payload and the boundary negative
share one authority (the metric handle), one failure class (a wrong or
misdirected scalar on the live path), one rollback (remove the handle), one
live consumer (the tuner's scoring route), and one parity surface (the
two-route oracle). Splitting "interface" from "consumption" would ship an
unused seam (§0 rule 8). Internal semantic checkpoints: C0 oracle → C1
inert handle + TIDMAD instance → C2 in-process route through the handle →
C3 subprocess route through the handle → C4 record payload → C5 boundary
negative + structural guard → C6 Stage-B direction axis → C7 mutations +
Checkpoint C → C8 Gate 2 (if required) → C9 docs/CI. Not frozen: commit
count, module placement, field names.

## 16. Operator decisions — ALL RESOLVED at freeze (2026-08-15)

| # | Question | Was freeze-blocking? | RESOLUTION |
|---|---|---|---|
| Q1 | **Confirm** that Step 06 owns the evaluation-side ACCEPTANCE contract and the deliverable facts required for scoreability, while Step 05c retains EXCLUSIVE ownership of producer-side representation semantics (§4) — or **defer** with the missing consumer evidence named? | yes | **CONFIRMED.** Step 06 owns the evaluation-side acceptance/scoreability contract and the deliverable facts required for scoreability; Step 05c retains EXCLUSIVE ownership of producer-side representation semantics; Step 06 references `DeliverableSpec` and does not redefine it |
| Q2 | Metric declaration form for non-TIDMAD tasks: derived-only in Step 06 (regime A) with the declared additive block deferred to Step 12, or an additive block in `task_config.yaml` now? | yes | **DECIDED.** Step 06 provides the generic runtime metric interface and derives the TIDMAD instance under Regime A. Task-level metric declaration is deferred to Step 12 and MUST use an additive block in the existing task configuration — no new top-level configuration hierarchy. No `task_config.yaml` edit in Step 06 |
| Q3 | Scoreability contract **semantics**: EXECUTION semantics frozen (executable before arithmetic; structured failure; reuse guard not the mechanism) — **and its SCOPE bounded: NO universal task-independent schema for completeness / channels / shape; requirements are per-metric-instance, declared against `DeliverableSpec`** (§5, revision 3). | yes | **FROZEN.** Scoreability is executable behaviour evaluated BEFORE metric arithmetic; rejected deliverables produce structured not-scoreable results; the contract has NO universal task-independent schema for completeness/channels/shape — requirements are declared per metric instance against `DeliverableSpec`. Field names remain implementation detail |
| Q4 | Any TIDMAD *secondary* metric instance in Step 06? | no | **ACCEPTED: none** — no consumer |
| Q5 | Gate 2: the standard and roadmap §17 say NOT REQUIRED (§13, quoted). Does the operator nonetheless ELECT a bounded Gate 2 as discretionary evidence? | no | **ACCEPTED: NOT REQUIRED** under the cited testing standard and roadmap §17 authority; not elected |
| Q6 | Which direction consumers does Step 06 *reach*? | no | **ACCEPTED:** the tuner's live scoring route + record payload only; workflow `:2740`, resume `:438`, `per_file_best._row_beats`, dashboard remain enumerated D1 debt, out of scope |

## 17. Implementation notes / source map (reading aids, not contracts)

- `execute_tools/scoring_utils.py` :104-264 (formula), :490-610 (`score_vector`); `scoring_helpers.py:36`
- `execute_tools/denoising_score_single.py` :104, :201, :220-227 (argv, call, output merge)
- `core/sandbox_executor.py` :1858-1897 (`score_vector` wrapper — the live route), :1899-1971 (`execute_scoring` spawn + merge)
- `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py` :3704-3740 (run-scope authorities — where the handle binds), :5321-5326 (live scoring call), :5538 (`build_score_table`), :5605-5613 (baseline/best/direction), :5776-5786 (record write)
- `agent/schemas/hyperparam_tuning.py` :381-399 (metric payload), :2465-2700 (`HyperparamTuningOutput` best_* fields — D1)
- `agent/schemas/score_table.py` (`ScoreComparisonTable`, raw-baseline reference)
- `execute_tools/per_file_best.py` :358-362 + `tests/unit/execute_tools/test_per_file_best.py:719` (identity precedent)
- `execute_tools/deliverable_spec.py` (05c producer contract the scoreability contract references)
- `execute_tools/inference_single.py::_is_complete_trial_output` :84-126 (the reuse guard NOT to relocate)
- Harness precedents: `tests/integration/execute_tools/test_step05c_checkpoint_c_deliverable_boundary.py`, `tests/unit/execute_tools/test_step05c_c0_deliverable_baseline.py`

## 18. Definition of Done (the eventual DONE state — NOT yet met; freeze ≠ done)

Step 06 is DONE when: the ONE PR is merged with Checkpoints 0/A/B/C(/D) and
its Gate disposition satisfied at the exact head; every §12 criterion is
`[x]` with recorded evidence — **including that scoreability is an executed
behaviour on both routes, not a documented intention**; the Deliverable-Contract review verdict is
recorded (confirm, or defer-with-reason); the D1 not-reached consumer list is
enumerated; roadmap §15.1 row and README mirror synchronized post-merge; and
Step 07a can bind the metric handle for policy without touching scoring.

**Design status: FROZEN, implementation authorized. Step 06 is NOT DONE until the above holds — freeze ≠ done.**

---

## 19. Commit plan — per-commit checklists (revision 4)

**Discipline (binding).** Every plan item below was written after inspecting
the seam it names at `b3c7ac8c`; line numbers are reading aids, not
contracts — re-read the touched source immediately before each commit. `[ ]`
= not done; `[x]` = done **and** verified with recorded evidence in the §20
ledger. Never mark `[x]` before the evidence exists. **Before each commit,
stop and show: the exact `git diff --stat`, the staged file list, the tests
run with counts and wall time, and any deviation from this plan** (the 05a/05b/05c
precedent). Planner exposure and production-default changes are outside these
commits and require separate evidence and operator approval. Exact commit
*count* is not frozen: a listed commit may be split at a clean boundary; the
semantic sequence, the §12 acceptance criteria and the §13 disposition are.

**Two inspection findings that shape the plan** (recorded here so no commit
"discovers" them):

- `scoring_utils.score_vector` sizes `file_vector` as `[None] * NUM_FILES`
  (`:583`) with `NUM_FILES` imported from `dataset_config` (`:64`), and
  bounds-checks `file_index` against it (`:317-318`). That is a
  TIDMAD-topology fact living inside the scorer. The handle must **not**
  re-declare it; C2 threads the existing `profile=` parameter (`:500`) the
  scorer already accepts, and the length stays whatever the frozen instance
  produces. Making the vector length profile-derived *inside* `score_vector`
  is scorer arithmetic-adjacent and is a §13 flip candidate — record, do not
  do, unless parity proves it neutral.
- `StubSandbox.score_vector` (`sandbox_executor.py:2175+`) returns the same
  2-tuple with a length-9 `file_vector` for pseudo mode. The pseudo path is a
  compatibility surface: C2 must keep the stub's contract byte-identical, and
  the pseudo-mode integration tests are part of Checkpoint D.

**Dependency chain.** `C0 → C1` (oracle, then inert type). `C1 → C2` (the
live in-process route). `C2 → C3` (the subprocess route must agree with the
now-migrated live route). `C3 → C4` (record payload assumes both routes emit
through the handle). `C4 → C5` (guards need the payload types to exist).
`C5 → C6` (contrast rung needs the guards so it cannot pass by re-inlining).
`C6 → C7` (mutations + Checkpoint C over the finished seam). `C7 → C8`
(terminal). Readers-first is not applicable here — there is one producer of
metric values (the scorer) and its consumers all read the record.

---

### C0 — Checkpoint 0: capture the two-route parity oracle and the metric-identity key set

**1. Goal.** Pin what no oracle pins today: that the two live scoring entry
points — in-process `TidmadSandbox.score_vector` (`sandbox_executor.py:1858`,
called by the tuner at `ml_hyperparameter_tune_agent.py:5321`) and the
`execute_scoring` subprocess (`:1899-1971` → `denoising_score_single.py`) —
produce the same result for the same deliverable, and what that result's
shape is. Separate commit because a parity baseline captured after C2 proves
nothing about C2.

**2. Scope.**
- New tests under `tests/unit/execute_tools/` and `tests/unit/core/` (settle
  exact module placement by inspection; the 05c C0 modules are the pattern).
- Reuse: `tests/unit/execute_tools/test_step05c_c0_deliverable_baseline.py`'s
  synthetic-deliverable writer (`create_abra_file` through the real writer),
  and `tests/unit/execute_tools/test_step00_numeric_baselines.py`'s anchor
  goldens for `s_max`/anchors.
- **Non-goals**: no production file changes; no re-capture of the frozen
  formula pins (`test_step00_numeric_baselines.py`, `test_scoring_helpers.py`,
  `test_phase67_scoring_precision.py` already pin them); no scorer-arithmetic
  assertion beyond "both routes agree".
- Depends on: nothing.

**3. Implementation plan.**
- [x] Re-read `score_vector` `:490-610` and `denoising_score_single.py:150-227`
      and record how each route obtains `sample_set`, `anchor_map`, `s_max`,
      `denoised_filename_fn`, `profile`.
- [x] Build one deterministic synthetic deliverable (small, both channels,
      known sample values) with the real writer, under a small bound profile
      so the run is seconds — the 05c Checkpoint-C fixture geometry
      (`psd_segment_length` 4,096) is the precedent. *(DEVIATED, bounded —
      full-length 10 M-sample single segment; §20.2.)*
- [x] Capture route (i): `TidmadSandbox.score_vector(...)` on it → record the
      exact **existing TIDMAD result and its key/output shape** (today a
      scalar and a `file_vector`) as **hardcoded literals**.
- [x] Capture route (ii): drive `execute_scoring` → `denoising_score_single.py`
      as a **real subprocess** on the same deliverable; record the
      `--output_json` keys and values as hardcoded literals.
- [x] Assert route (i) == route (ii) on scalar and per-file values (exact
      float equality — same arithmetic, same inputs; if they differ, that is
      a **finding**, recorded before anything is built).
- [x] Capture the `per_file_best` identity key set as it stands
      (`test_per_file_best.py:719` already pins it — reference, do not
      duplicate).
- [x] Capture the pseudo path: `StubSandbox.score_vector` return shape
      (2-tuple, length-9 vector) as a hardcoded expectation.
- [x] Record every captured value in §20.

**4. Validation plan.**
- *Unit*: every new capture passes against unmodified production code.
- *Integration/pseudo*: the route-(ii) capture IS a real subprocess.
- *Negative*: none at C0 (captures only).
- *Backward-compat*: this commit **is** the parity instrument.
- *Gate*: none.

**5. Acceptance criteria.**
- [x] `git status --porcelain` lists **no production file** in this commit.
- [x] Captured values are hardcoded literals, never re-derived by calling
      the code under test.
- [x] Route (i) and route (ii) results are asserted **equal to each other**
      and each equal to its literal.
- [x] The oracle is worded as "the existing TIDMAD result and shape", not as
      `(file_vector, scalar)` (revision 3, §11).
- [x] Each capture is traceable to the production site it guards, by
      `file:line`.

**6. Failure and edge cases.**
- Routes disagree at C0 → **record as a pre-existing finding**; do not fix
  in C0; the design's parity claim is then "each route unchanged", not
  "routes equal", until diagnosed. Surface to the operator.
- The subprocess route needs `--anchor_map` / real anchor JSON → use the
  committed anchor goldens; if the fixture cannot satisfy it without real
  data, record the substitution and move that capture to Checkpoint C.

**7. Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/execute_tools/<c0 module> tests/unit/core/<c0 module> -q`
      *(narrow at implementation time)* — actual: one module,
      `tests/unit/core/test_step06_c0_two_route_oracle.py`, 4 passed 3.62 s.
- [x] Record: test count, wall time, and explicit confirmation that zero
      production files were modified.

**8. Commit boundary.** Tests and a written census only. Independently
reviewable as "what we promise not to change". No production edit.

---

### C1 — the metric handle: `MetricSpec` / `ScoreabilityContract` / `MetricResult`, inert, with the TIDMAD instance

**1. Goal.** Introduce the typed runtime value §4/§5 froze — mandatory
scalar, optional evidence, explicit direction and aggregation, references,
an EXECUTABLE scoreability contract — with its TIDMAD derived instance and
**no production consumer**. Separate because "the type is correct" and
"production uses it" are different claims (05c C1 precedent).

**2. Scope.**
- One new module (placement by inspection; `execute_tools/deliverable_spec.py`
  is the pattern and the natural neighbour). Field names are implementation detail (§5).
- The TIDMAD instance derived with **no declaration** (regime A): identity
  extends `per_file_best`'s `metric_id: "tidmad_denoising_score"` /
  `score_transform` / `log_base` (`per_file_best.py:358-362`); direction
  `higher`; aggregation = the frozen instance's own function (referenced,
  not re-implemented); scoreability = required channels (the two the scorer
  addresses, `scoring_utils.py:261-264, 396-401`), required attrs
  (`voltage_range_mV`, `sampling_frequency` — `:160-163`), required storage
  dtype/offset (referenced from `DeliverableSpec.storage`), required
  completeness (TIDMAD meaning: every in-scope file has an output).
- **Non-goals**: no YAML, no `task_config.yaml` edit (Step 12), no schema
  field on any existing record, no call site, no change to `score_vector`,
  no loss field of any kind (§7).
- Depends on: C0.

**3. Implementation plan.**
- [x] Re-read `deliverable_spec.py` and mirror its shape: frozen Pydantic
      models, one derivation function, defaults that yield the TIDMAD
      instance with no input.
- [x] Define `MetricSpec` (id · direction · aggregation id · transform +
      params · references · scoreability) and `MetricResult` (metric_id ·
      direction · scalar · optional evidence · references_used) — names
      provisional.
- [x] Define `ScoreabilityContract` with an executable
      `validate(deliverable_path, ...) -> ok | structured failure` and NO
      universal completeness/channel/shape schema (§5 scope bound): TIDMAD's
      predicate is TIDMAD's instance, declared against `DeliverableSpec`.
- [x] Provide the TIDMAD derivation (`derive_tidmad_metric_spec(profile,
      deliverable_spec)` or equivalent) — the aggregation is a *reference*
      to the frozen `score_vector`, never a re-implementation.
- [x] Confirm by scan that no production module imports it (05c's
      inertness test pattern, later inverted).

**4. Validation plan.**
- *Unit*: the TIDMAD instance's identity fields equal the `per_file_best`
  literals; direction is `higher`; scoreability `validate` accepts the C0
  synthetic deliverable.
- *Negative*: a loss-shaped metric is rejected (§7 boundary — executable
  from C1 onward); a `MetricResult` cannot be built from `loss_history`;
  identical/missing required channels rejected; an unknown direction
  rejected; scoreability rejects a deliverable missing a required attr /
  channel / with the wrong dtype / incomplete — with a **structured**
  failure, not an exception from h5py.
- *Backward-compat*: no existing schema changed; no config file changed.
- *Gate*: none.

**5. Acceptance criteria.**
- [x] A **scalar-only** `MetricSpec`/`MetricResult` is constructible
      (evidence optional — §4).
- [x] The TIDMAD instance derives with no declaration and matches the C0
      identity literals.
- [x] `validate` on the C0 deliverable → ok; on each invalid variant → the
      structured failure names the violated requirement.
- [x] Zero production importers (asserted).
- [x] No file under `configs/` changed; no existing schema gained a field.
- [x] No field on any metric type can hold a loss (negative test reds if one
      is added).

**6. Failure and edge cases.**
- A required scoreability fact is not derivable from `DeliverableSpec` +
  profile → **MATERIAL STOP** (would need a declaration Step 06 does not
  own).
- Two scoring routes need different scoreability inputs → they must resolve
  the **same** predicate; a per-route predicate is two authorities.

**7. Verification commands and evidence.**
- [x] targeted selector for the new module + the C0 captures. — actual: 29 passed 3.94 s (§20.3).
- [x] Record counts, wall time, the zero-importer confirmation.

**8. Commit boundary.** One new typed value + TIDMAD derivation, inert,
independently revertible.

---

### C2 — the LIVE route through the handle: `TidmadSandbox.score_vector` + the tuner's run-scope binding

**1. Goal.** Make PRODUCTION SCORING (the tuner's in-process route) invoke
the frozen instance THROUGH the handle, with scoreability evaluated **before**
`score_vector` runs. This is the §15.1 row's named live consumer.

**2. Scope.**
- `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py`:
  bind `run_metric` once at run scope beside `run_profile` / `run_model_io`
  / `run_deliverable_spec` (`:3704-3740`); the scoring call `:5321-5326`
  goes through it.
- `core/sandbox_executor.py::TidmadSandbox.score_vector` (`:1858-1897`):
  accept the handle (or the spec) and evaluate scoreability before
  delegating to `scoring_utils.score_vector`; thread the existing
  `profile=` parameter rather than any new topology fact.
- `StubSandbox.score_vector` (`:2175+`): signature kept compatible; return
  contract byte-identical.
- **Non-goals**: no change to `scoring_utils.score_vector`'s arithmetic or
  its 2-tuple return; no change to `_LOG_BASE`, `s_max`, anchors; no record
  change yet (C4); no subprocess route yet (C3); no `NUM_FILES` change
  (see finding above).
- Depends on: C1.

**3. Implementation plan.**
- [x] Re-read `:5300-5340` (call site + `_denoised_fn`) and `:1858-1897`
      and record exactly what crosses today.
- [x] Bind `run_metric` at run scope from the run profile + run deliverable
      spec — one acquisition point.
- [x] Route the live call through the handle: scoreability `validate` on the
      deliverable set → on failure, a **structured not-scoreable result**
      reaches the round-outcome path (record which existing status/failure
      field carries it — inspect `_decide_round_outcome` `:366-388` before
      choosing; do not invent a new status if an existing one is honest).
- [x] On success, delegate to `scoring_utils.score_vector` unchanged.
- [x] Keep `StubSandbox` returning its 2-tuple.

**4. Validation plan.**
- *Unit*: the C0 route-(i) literal is reproduced exactly through the handle.
- *Integration/pseudo*: a pseudo-mode round reaches scoring and the
  `StubSandbox` contract is unchanged (existing pseudo smoke tests).
- *Negative*: an unscoreable deliverable set yields the structured failure
  **before** `score_vector` is called (assert `score_vector` not invoked).
- *Backward-compat*: `TidmadSandbox.score_vector` remains callable by
  callers that predate the handle (regime A default resolves TIDMAD).
- *Gate*: none.

**5. Acceptance criteria.**
- [x] The tuner's live scoring call resolves through `run_metric` — asserted
      by reachability (a renamed/contrast handle changes the observed
      behaviour), not by inspection alone.
- [x] Route (i) result equals the C0 literal exactly.
- [x] Scoreability failure short-circuits scoring with a structured result;
      `score_vector` is not reached.
- [x] `StubSandbox.score_vector` return is unchanged (C0 pseudo capture).
- [x] `scoring_utils.score_vector` diff is **empty**.
- [x] Legacy callers of `TidmadSandbox.score_vector` are unaffected.

**6. Failure and edge cases.**
- Scoreability needs the deliverable *set* but the tuner only has a
  filename fn → derive paths from `eval_sample_set` + `_denoised_fn` (both
  exist at `:5321-5326`); if that is insufficient, **record**, do not add
  argv.
- A not-scoreable result on a **formal** round → the round-outcome semantics
  (Step 07a) are NOT changed here; the failure must land in an existing
  honest field/status. If none is honest → **STOP** and surface.
- Resume: a resumed run must bind the same `run_metric` (regime A ensures
  it); assert, do not assume.

**7. Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/agent/tune_ml_hyperparam_agent tests/unit/core -q` *(narrow)* — actual: + `tests/unit/execute_tools`; counts in §20.4.
- [x] Record counts, wall time, the route-(i) equality, the short-circuit
      evidence.

**8. Commit boundary.** One live consumer, one route. No subprocess, no
record, no scripts.

---

### C3 — the SUBPROCESS route through the handle: `execute_scoring` / `denoising_score_single.py`

**1. Goal.** The second existing entry point reconstructs the same TIDMAD
instance from what already crosses (`--dataset_profile_json`) and evaluates
the same scoreability — so the two routes keep agreeing (§1.1 compatibility
obligation). Separate because it is a real subprocess boundary with its own
argv contract.

**2. Scope.**
- `execute_tools/denoising_score_single.py` (`:150-227`): derive the metric
  spec from the loaded profile (05c §3.2a Option-A pattern — no serialization
  of the spec, no new argv), validate scoreability, then `score_vector`.
- `core/sandbox_executor.py::execute_scoring` (`:1899-1971`): unchanged argv;
  the merged `--output_json` keys unchanged (C4 may add keys additively).
- Callers `scripts/run_comparison.py:241`, `agent/skills/denoising_score_skill/wrapper.py:12`:
  unchanged.
- **Non-goals**: no new argv (or the Stage-A claim is downgraded in
  writing — 05c precedent); no output-key removal/rename.
- Depends on: C2.

**3. Implementation plan.**
- [x] Re-read `denoising_score_single.py` argv + main flow; confirm the
      profile is loaded fail-closed (`:151-155`).
- [x] Derive the metric spec in the child from `dataset_profile` (+ the
      derived deliverable spec) — one derivation, two callers.
- [x] Validate scoreability before `score_vector`; on failure write a
      **structured** not-scoreable payload to `--output_json` and exit with a
      status the parent's existing handler classifies honestly (inspect
      `:1961-1971`).
- [x] Assert no ambient second resolution in the child when a profile path
      was given (05c C3 precedent).

**4. Validation plan.**
- *Unit*: argv for `execute_scoring` equals the pre-C3 ordered list (capture
  in C0 if not already pinned by an existing test — inspect
  `test_sandbox_executor.py`).
- *Integration*: a **real** `execute_scoring` subprocess on the C0
  deliverable reproduces the route-(ii) literal exactly, and equals route (i).
- *Negative*: an unscoreable deliverable → structured failure in
  `--output_json`, no scorer traceback.
- *Backward-compat*: `run_comparison.py` / the skill wrapper call sites are
  byte-unchanged.
- *Gate*: none.

**5. Acceptance criteria.**
- [x] `execute_scoring` argv identical (ordered) to the pre-C3 capture.
- [x] Route (ii) == route (i) == the C0 literal.
- [x] Exactly one `derive_*_metric_spec` call in the child; exactly one
      `resolve_dataset_profile()` (the pre-existing legacy adapter) — no
      second.
- [x] Structured not-scoreable output on the negative fixture.

**6. Failure and edge cases.**
- Child cannot derive a required scoreability fact from the transported
  profile → same MATERIAL STOP as C1 (transport insufficiency; not an argv
  problem to solve here).
- Parent's error classifier maps the new structured failure to `"error"` →
  record; do not invent a new status in this step.

**7. Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/execute_tools tests/unit/core -q` *(narrow)*; the real-subprocess test under `tests/integration/execute_tools/`. — actual: the real-child tests live in `tests/unit/execute_tools/test_step06_c3_subprocess_route.py` (hermetic, `allow_real_subprocess`, seconds — §20.2 placement decision); Checkpoint C proper is C7 (§20.5 counts).
- [x] Record counts, wall time, the two-route equality.

**8. Commit boundary.** One subprocess route. No record change.

---

### C4 — record-facing payload: additive `MetricResult` on `ExperimentRecord`

**1. Goal.** Make identity, direction and value **machine-readable on every
record** so Step 07a/09 can consume them — additively, beside
`denoising_score` / `file_vector` / `score_table`, which are untouched (D1).

**2. Scope.**
- `agent/schemas/hyperparam_tuning.py::ExperimentRecord` (`:381-399`): one
  additive optional field family (name provisional), default `None`.
- Tuner record write `ml_hyperparameter_tune_agent.py:5776-5786`: populate
  it from the handle result.
- `HyperparamTuningOutput` (`:2465-2700`): **untouched** — `best_*_denoising_score`
  fields are D1.
- **Non-goals**: no rename; no removal; no dashboard change; no
  `ModelRunSummary` change (Step 09).
- Depends on: C3.

**3. Implementation plan.**
- [x] Re-read `:5768-5800` and the schema; add the optional field(s).
- [x] Populate from the C2 handle result on the success path; leave `None`
      on failure paths (and on the pseudo path unless the stub supplies it —
      inspect).
- [x] Confirm `save_record` / `coerce_nonfinite_to_none` need no change.

**4. Validation plan.**
- *Unit*: a record built by the live path carries `metric_id ==
  "tidmad_denoising_score"`, `direction == "higher"`, `scalar ==
  denoising_score` (equal by construction, asserted).
- *Backward-compat*: every committed historical `ExperimentRecord`,
  `HyperparamTuningOutput`, `InterpretationOutput`, `run_output_*.json` under
  `tests/pseudo_data/` and any committed goldens validates unchanged (the
  05a "replay from committed artifacts" pattern).
- *Negative*: a record whose additive field disagrees with
  `denoising_score` is rejected (one value, two names — they must agree).
- *Gate*: none.

**5. Acceptance criteria.**
- [x] `denoising_score`, `file_vector`, `score_table` names and semantics
      unchanged; `git diff` shows only additions to the schema.
- [x] Historical artifacts validate unchanged (count recorded).
- [x] The additive field is populated on the live path and `None`
      elsewhere.

**6. Failure and edge cases.**
- Pseudo path (`StubSandbox`) does not carry identity → `None` is honest;
  do not fabricate.
- A record with `denoising_score` but no `MetricResult` (pre-C4 record) is
  valid — additive optional.

**7. Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/agent tests/unit/core -q` *(narrow)*. — actual: + nodes/workflows/dashboard; counts in §20.6.
- [x] Record counts, wall time, the historical-artifact count validated.

**8. Commit boundary.** Schema + one write site. Additive only.

---

### C5 — boundary negatives and the structural guard

**1. Goal.** Make the §7 boundary and the "declared once" property
executable: losses cannot enter the metric types; no owned scoring consumer
executes a hardcoded direction where the handle is available; the TIDMAD
`metric_id` literal is declared exactly once.

**2. Scope.** Tests only (+ the C1 negative tests may move here if not
already landed). **Non-goals**: no production change; no assertion against
consumers Step 06 does not reach (workflow `:2740`, resume `:438`,
`per_file_best._row_beats`, dashboards — the D1 list, enumerated in §20).
Depends on: C4.

**3. Implementation plan.**
- [x] Boundary negative: constructing a metric whose identity is a loss, or
      populating `MetricResult` from `loss_history`, is rejected.
- [x] Structural guard over the **owned** consumers (the tuner's live
      scoring path, `TidmadSandbox.score_vector`, `denoising_score_single.py`,
      the metric module): no executed hardcoded direction; the
      `tidmad_denoising_score` literal appears in exactly one executed
      constant (05c "declared exactly once" pattern, AST over executed
      constants, docstrings excluded).
- [x] Record the **not-reached** direction consumers as an explicit list
      (D1) — a test that asserts they still contain their literal, so the
      list cannot silently drift (05c out-of-rung pattern).

**4. Validation plan.** *Unit*: the above. *Negative*: the guards red on a
re-inlined direction / a second `metric_id` declaration (proved at C7 by
mutation). *Gate*: none.

**5. Acceptance criteria.**
- [x] Loss-shaped metric rejected; `loss_history` → `MetricResult` rejected.
- [x] Owned surfaces: zero executed hardcoded direction; `metric_id` declared
      once.
- [x] The D1 not-reached list is asserted, not merely written.

**6. Failure and edge cases.** A guard finds a direction literal in an
owned surface that C2/C3 missed → same-authority missed site → migrate in
this commit and record (05c precedent), unless it is scorer arithmetic
(then flip candidate — record, stop).

**7. Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/execute_tools tests/unit/core -q` *(narrow)*.
- [x] Record counts, wall time.

**8. Commit boundary.** Evidence only.

---

### C6 — Stage-B rung: the metric-direction axis (lower-is-better through the handle)

**1. Goal.** Prove the abstraction supports a materially different metric —
one axis: direction — on stub outputs, entering the record through the
handle, with TIDMAD's instance unchanged (roadmap §10.5; a §21.4
objective-dimension atomic fixture at TIDMAD's topology).

**2. Scope.** Tests only. **Non-goals**: no incumbent selection under the
contrast metric (Step 07a); no image/spatiotemporal track (§21.3 — Step 06
attaches the cheapest grade); no `task_config.yaml` declaration (Step 12).
Depends on: C5.

**3. Implementation plan.**
- [x] Construct a scalar-only, `direction="lower"` `MetricSpec` in-process
      (regime A instance stays TIDMAD; the contrast is injected at the seam,
      exactly as 05c's renamed naming was).
- [x] Drive the live route with it on stub outputs; assert the record's
      additive payload carries `direction="lower"` and the contrast identity,
      and that TIDMAD's identity/direction are untouched in the same process.
- [x] Negative: the rung does not fire on the shipped instance.

**4. Validation plan.** *Unit*: the rung. *Negative*: shipped instance
unchanged. *Gate*: none.

**5. Acceptance criteria.**
- [x] A scalar-only lower-is-better metric enters the record through the
      handle with explicit `direction="lower"`.
- [x] TIDMAD identity/direction unchanged in the same run.
- [x] Nothing else varied (one axis).

**6. Failure and edge cases.** The rung passes only because a seam returns
the contrast value unconditionally → the negative catches it.

**7. Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/execute_tools tests/unit/core -q` *(narrow)*.
- [x] Record counts, wall time.

**8. Commit boundary.** Evidence only.

---

### C7 — mutations per semantic family + Checkpoint C (real subprocess)

**1. Goal.** Prove each semantic family is load-bearing and cross the real
subprocess boundary with the finished seam.

**2. Scope.** Tests + a scratch mutation runner (05c pattern; not committed
into the tree unless it already has a home). **Non-goals**: no production
change. Depends on: C6.

**3. Implementation plan.**
- [x] Mutation families (count NOT frozen; add finer ones only where they
      supply unique evidence): identity swap · direction flip · aggregation
      substitution · **scoreability bypass** (validate skipped → arithmetic
      reached on an invalid artifact) · route divergence (in-process vs
      subprocess) · declared-once (a second `metric_id` literal).
- [x] Hygiene: assert each mutation's site count == 1 before applying; clear
      `__pycache__`; restore from clean source; re-verify green.
- [x] Checkpoint C: a **real** `execute_scoring` subprocess scores a real
      small deliverable through the handle; result equals the in-process
      route; the scoreability negative also runs through the real subprocess.
      Helper-only is insufficient (05c §6 discipline; reuse
      `test_step05c_checkpoint_c_deliverable_boundary.py`'s harness).
- [x] Classify any survivor (real gap / equivalent / unreachable / wrong
      fixture) **before** strengthening an oracle.

**4. Validation plan.** *Unit*: mutations. *Integration*: Checkpoint C. *Gate*:
NOT REQUIRED (§13) — listed separately, not launched.

**5. Acceptance criteria.**
- [x] Every family reds; each failure names the family.
- [x] Zero survivors, or each survivor classified and recorded.
- [x] Checkpoint C: real subprocess result == in-process == C0 literal; the
      structured not-scoreable result observed through the real subprocess.
- [x] Tree restored green after every mutation.

**6. Failure and edge cases.** A survivor → inspect test architecture first.
Real subprocess needs anchors → the committed goldens; if real data is
genuinely required, record and route that assertion to a (discretionary,
operator-elected) Gate 2 rather than pretending coverage.

**7. Verification commands and evidence.**
- [x] mutation runner log; `.venv/bin/python -m pytest tests/integration/execute_tools/<checkpoint c module> -q`. — actual: `test_step06_checkpoint_c_metric_boundary.py`, 3 passed 67 s.
- [x] Record each mutation's expected vs observed, and the restored-green
      re-run.

**8. Commit boundary.** Evidence only.

---

### C8 — terminal validation, docs, ledger, CI

**1. Goal.** Terminal evidence; leave the PR reviewable; record the
Deliverable-Contract verdict and the D1 not-reached list.

**2. Scope.** §20 ledger; touched module/node docs (tuner node doc for the
run-scope binding; `execute_tools` docs if the metric module gets a `.md`);
CI iteration. **Non-goals**: no new capability. Depends on: C7.

**3. Implementation plan.**
- [x] Synchronize §20 with actual findings, deviations, evidence.
- [x] Record the OD-20-7 verdict in the ledger — resolved at freeze as CONFIRMED
      (§16-Q1).
- [x] Update touched docs as the last pre-merge step, quoting each documented
      behaviour against merged source (CLAUDE.md doc-sync rule).
- [x] Terminal checks from a **clean tree**: directly affected unit
      subsystems · Checkpoint C · `ruff check` · `ruff format --check` ·
      exact-head CI (strict pyright is CI's — record the local-node
      limitation if it recurs).
- [x] Open/update ONE PR; drive exact-final-head CI green; verify local HEAD
      == PR `headRefOid` == successful CI `headSha`.

**4. Validation plan.** As listed. **No local full suite by default.**

**5. Acceptance criteria.**
- [x] Every verdict read from the log file, never a wrapper's exit status.
- [x] Three-way SHA identity read, not reconstructed.
- [x] Working tree clean; §20 records every deviation; the D1 not-reached
      list is enumerated.

**6. Failure and edge cases.** The PR3-L2 preflight guard reds on a dirty
tree → commit the checkpoint first; never relax it. CI env-only failures →
diagnose, fix, not a stop.

**7. Verification commands and evidence.**
- [x] the terminal command set with counts and wall time; CI run id and
      exact `headSha`.

**8. Commit boundary.** Docs and CI-driven fixes only.

### 19.1 Commit-boundary discipline (binding for every commit above)

Before each semantic commit, record in §20: the exact `git diff --stat`, the
staged file list, the tests run with counts and wall time, and any deviation
from this plan. **Then stop and show them** before committing. Never mark
`[x]` before the evidence exists; an unperformed exact command is recorded as
DEVIATED / SUPERSEDED with what was actually run.

### 19.2 C0-C8 and Checkpoints 0/A/B/C/D are internal milestones

They are semantic evidence milestones inside ONE PR — not child PRs and not
approval boundaries. Ordinary findings follow: inspect → classify → record →
fix → validate → continue. Only a MATERIAL STOP returns early: a scoreability
fact not derivable from existing authorities; a route that cannot agree
without new argv; a required change to scorer arithmetic, deliverable bytes or
the subprocess argv contract (each also flips §13); a not-scoreable outcome
that no existing status can carry honestly; or a `NUM_FILES`-class topology
fact the handle would have to re-declare.

### 19.3 Out of scope for these commits

Planner exposure (nothing here reaches an LLM prompt), production-default
changes, task-level metric declaration (Step 12), incumbent/threshold policy
(Step 07a), Interpreter consumption (Step 09), the empirical comparison
campaign. Only the validation needed to implement the feature safely is in
scope.

## 20. Implementation ledger

**LIVE.** Implementation authorized 2026-08-15 under the filled Implementation
Working Rules (PR context: Step 06 — Metric Interface). Branch
`feat/generic-framework-step-06-metric-interface`, implementation base
`530f574c` (= the freeze marker; `origin/master` at kickoff). Commit
granularity follows the Working Rules (autonomous semantic commits); the §19.1
"stop and show" is satisfied by RECORDING the diff-stat / staged list / tests /
wall time here before each commit.

### 20.0 Kickoff verification

| Check | Result |
|---|---|
| `origin/master` | `530f574cf572cda73043b1a1b1ed1d93685d99e8` — equals the implementation base and the frozen design content SHA |
| production source vs design base `75525dc9` | **byte-identical** — `git diff --name-only 75525dc9 HEAD` lists only `README.md`, `step_06_metric_interface.md`, `siderius_generic_framework_upgrade.md`; every `file:line` in §1/§17/§19 was re-checked directly |
| Step-05 merges `cfb3b1c7` / `5ce205d3` / `03e00944` | all ancestors of HEAD |
| working tree / untracked | clean / none (the git-ignored PR handoff re-initialised for THIS PR) |
| orphaned Gate / training / inference / scoring processes | none |
| Gate 1 / Gate 2 | NOT REQUIRED (§13) — not launched |

### 20.1 Current-source re-enumeration (before any production edit)

All frozen line numbers confirmed. Facts that shape the plan beyond §19's two
inspection findings:

| # | Fact | Evidence |
|---|---|---|
| 1 | Route (i) passes `data_dir=self.base_dir`, `raw_data_dir=self.dirs["data"]` (= `TIDMAD_DATA_DIR` from `tidmad_data_config.yaml`, not env) and validates the sample set against `self.data_scope` | `sandbox_executor.py:1886-1897`, `:1082`, `:58-59` |
| 2 | Route (ii) argv carries **neither** `--raw_data_dir` nor `--anchor_map`; the child defaults them to `TIDMAD_DATA_DIR` and the committed `reference_data/segment_anchors.json`; the child's `sample_set = {file_index: range(profile.segments_per_file)}` | `sandbox_executor.py:1919-1939`; `denoising_score_single.py:135-144`, `:190` |
| 3 | `score_vector(legacy_mode=False)` never reads `anchor_map` — only `s_max` | `scoring_utils.py:656-664` |
| 4 | The scorer reads raw CH2 (`:470`) and denoised CH1 (`:477`); `voltage_range_mV` / `sampling_frequency` are read UNCONDITIONALLY from `timeseries/channel0001` of whichever file is open | `scoring_utils.py:159-164` |
| 5 | The `execute_scoring` argv was NOT pinned as an ordered golden (only `stdout`/`stderr` kwargs) | `tests/unit/core/test_sandbox_executor.py:456-483` |
| 6 | No test drives `denoising_score_single.py` end-to-end as a real subprocess on a synthetic deliverable (02a/03/05c Checkpoint-C harnesses train + infer only) | `tests/integration/execute_tools/test_step0{2a,3,5c}_checkpoint_c_*.py` |
| 7 | Already pinned, referenced not duplicated: `StubSandbox.score_vector` 2-tuple + length-9 (`tests/unit/core/test_stub_sandbox.py:332-360`); `per_file_best` key set + `metric_id` (`test_per_file_best.py:719`; NUM-8 `test_step00_numeric_baselines.py:268-283`) | — |
| 8 | Route (ii) is reachable from the tuner only via the legacy no-anchor-map `else` branch `_run_skill("denoising_score_skill", …)`; the live round path is route (i) | `ml_hyperparameter_tune_agent.py:5289`, `:5426-5430` |
| 9 | 05c deliberately left the deliverable-name literals at `denoising_score_single.py:163,166` for Step 06 | 05c design `:178`, `:200`; the 05c handoff's "inherited by Step 06" note |
| 10 | Existing landing places for a not-scoreable outcome (decision at C2): the tuner's `except Exception` → `status: "error_scoring"` record (`:5438-5483`); `is_degenerate`/`failure_reason` merged by `_merge_score_validity_failure` (`:5407-5411`); the parent maps a child `CalledProcessError` to `"error"` / `"oom_host_ram"` (`:1963-1967`) | — |
| 11 | Run-scope authorities where `run_metric` binds: `run_profile` `:3722`, `run_model_io` `:3743`, `run_deliverable_spec` `:3757` | — |
| 12 | The unit-suite guard `tests/unit/conftest.py` refuses an unmarked real launch of `denoising_score_single.py`; the registered marker `allow_real_subprocess` (pyproject `:56`) is the documented opt-in for an INTENDED launch | — |

### 20.2 C0 — Checkpoint 0 (pre-edit captures)

**Decisions (bounded, recorded before the capture).**

```text
Previous assumption (§19 C0 §3):
  "a small bound profile so the run is seconds — the 05c Checkpoint-C fixture
   geometry (psd_segment_length 4,096) is the precedent."

Audit evidence:
  scoring_utils.get_one_sec_psd:143 sets N = SEGMENT_LENGTH — the MODULE
  constant (10,000,000), not the profile's psd_segment_length. A 4,096-sample
  file therefore reshapes to (0, 10_000_000) and raises. NUM-6 monkeypatches
  the constant (test_step00_numeric_baselines.py:171-172), which cannot reach
  the subprocess route.

Corrected understanding:
  The scorer's segment length is a TIDMAD-topology fact inside the scorer
  (the same class as §19's NUM_FILES finding). A route-parity fixture must
  be FULL-LENGTH to be honest on both routes with the same bytes.

Implementation consequence:
  C0 fixture = one 10 M-sample segment, one file, both channels, written by
  the REAL writer create_abra_file (indexed=False, storage=derived TIDMAD
  storage — the production deliverable path). Measured: ~1 s per file to
  write (20 MB), ~1.5 s per route to score. Nothing is monkeypatched.

Validation consequence:
  Both routes run unmodified production code on identical inputs; exact
  float equality is asserted.
```

```text
Decision — hermetic subprocess route.
  execute_scoring's argv has no --raw_data_dir / --anchor_map (fact 2). To
  run the REAL argv with zero machine data, the run-bound profile declares
  segments_per_file=1 and an ABSOLUTE validation_file_pattern under
  tmp_path. _write_dataset_profile_config (:1237) transports it; the child's
  os.path.join(TIDMAD_DATA_DIR, absolute_name) resolves to the tmp raw file —
  the same os.path.join property _build_denoised_filename (:1085-1088)
  documents and relies on. The pattern validator (dataset_config.py:63-113)
  accepts it. s_max comes from the committed anchor artifact on both routes.
  Alternative rejected: reading the machine's real raw file (non-hermetic,
  machine-dependent skip).
```

```text
Decision — placement of the real-subprocess capture.
  §19 C0 §2 places C0 under tests/unit/ and §4 says "the route-(ii) capture
  IS a real subprocess". The unit-suite guard (fact 12) is opted out per
  test with @pytest.mark.allow_real_subprocess, whose registered purpose is
  exactly an intended scoring launch. The launch is hermetic, CPU-only,
  ~1.5 s. Checkpoint C (C7) still lands in tests/integration/.
```

**Captures — `tests/unit/core/test_step06_c0_two_route_oracle.py` (4 tests).**

| Capture | Literal / oracle | Guards |
|---|---|---|
| Route (i) existing TIDMAD result and shape | scalar `5.174659969078518`; length-20 vector; file 0 `5434.0608313142075`, every other entry `None` | `sandbox_executor.py:1858-1897` → `scoring_utils.py:491-687` |
| Route (ii) REAL `execute_scoring` subprocess: `--output_json` keys and values | keys exactly `["denoising_score", "file_vector"]`; same scalar / vector literals; parent status `success` | `sandbox_executor.py:1899-1970`; `denoising_score_single.py:186-227` |
| Route (i) == route (ii) | exact float equality on scalar and every per-file value — **the routes agree; no pre-existing divergence** | the compatibility obligation (§1.1) |
| Ordered `execute_scoring` argv golden (mocked `subprocess.run`, `<PYTHON>`/`<WS>` normalization) | 18-token list, verbatim order; transported profile == `TIDMAD_PROFILE.model_dump()` | `sandbox_executor.py:1919-1939` |
| `per_file_best` key set + `metric_id`; `StubSandbox` 2-tuple/len-9 | referenced (fact 7), not duplicated | — |

Fixture: `_signal(seed)` = clipped `20·sin(2πt/64) + N(0,3)` int8, seed 10 raw
(both channels), seed 20 denoised CH1 with the raw signal as CH2; instrument
attrs from the real writer (`voltage_range_mV=80`, `sampling_frequency=10 MS/s`).

**Validation.**

```text
command:  .venv/bin/python -m pytest tests/unit/core/test_step06_c0_two_route_oracle.py -q
result:   4 passed in 3.62 s   (ruff check clean; ruff format applied)
tree:     git status --porcelain lists ONLY the new test module and this
          design doc — zero production files (verified before commit)
```

### 20.3 C1 — the metric handle, inert, with the TIDMAD instance

**Module**: `execute_tools/evaluation_metric.py` (580 lines incl. docstrings),
beside `deliverable_spec.py`. Names (provisional per §5, now the
implementation's): `MetricSpec` · `MetricResult` · `NotScoreableResult` ·
`MetricOutcome = MetricResult | NotScoreableResult` · `ScoreabilityContract`
(abstract, `check(deliverables) -> ScoreabilityVerdict`) ·
`ScoreabilityVerdict` / `ScoreabilityFailure` · `TidmadScoreabilityContract` ·
`PresenceScoreabilityContract` (weakest acceptance: named files exist — for
scalar-only metrics; NOT a universal schema) · `EvaluationMetric` (abstract
handle: `evaluate()` runs scoreability FIRST, then the subclass's `_compute`) ·
`TidmadDenoisingMetric` (`_compute` forwards its kwargs verbatim to
`scoring_utils.score_vector`) · `derive_tidmad_metric_spec(profile,
deliverable_spec=None)` / `derive_tidmad_metric(...)` (Regime A) · constants
`TIDMAD_METRIC_ID = "tidmad_denoising_score"`, `TIDMAD_AGGREGATION_ID`,
`TIDMAD_TRANSFORM = "log"`, `TIDMAD_REFERENCES`, `TIDMAD_REQUIRED_ATTRS`.

**Decisions (bounded).**

| # | Question | Evidence inspected | Decision / why |
|---|---|---|---|
| 1 | Method name for the executable contract | Pydantic v2 reserves `BaseModel.validate` (deprecated classmethod) | `check()` — the design's `validate(...)` was illustrative (§5 "field names are implementation detail") |
| 2 | Where `log_base` comes from ("carried, not re-declared", §4) | `per_file_best.LOG_BASE` imports `agent.schemas.hyperparam_tuning` + `core.resume` → would cycle once C4 adds the record payload; `scoring_helpers._LOG_BASE` imports only `score_table`/`dataset_config`/`nodes.scoring_reference` — cycle-free | imported from `scoring_helpers._LOG_BASE`; the C1 test pins metric == `per_file_best.LOG_BASE` == `_LOG_BASE` (NUM-5 extended to a 4th expression) |
| 3 | `MetricResult.scalar` type | `denoising_score: float \| None`; `coerce_nonfinite_to_none` writes the scorer's `-inf` as `null` and the record must re-validate on reload | `float \| None`, documented as the storage-boundary image ONLY; the handle never produces `None` — an unscoreable deliverable is a `NotScoreableResult`, not a result without a scalar |
| 4 | Loss-shaped rejection rule | roadmap §20.2 (identity: a loss names the training objective); a `loss_type` such as `"mse"` is a legitimate contrast-metric identity | token rule: any identifier token `loss`/`losses` is refused by `MetricSpec.id`, `MetricResult.metric_id`, `NotScoreableResult.metric_id`; `extra="forbid"` on all metric types so `loss_history=`/`final_loss=` cannot attach; a structural test asserts no field name contains "loss"; `mse` accepted (guards over-reach) |
| 5 | Scoreability requirements of the TIDMAD contract | scorer reads `timeseries/<group>/timeseries` for ch=1/ch=2 (`:150`, `:261-264`), attrs on the input group (`:159-164`), dtype (a float artifact would silently mis-scale, not crash); completeness at file level | required channels + dtype READ from `DeliverableSpec.storage` (declared against it, not restated); attrs + in-file path are the scorer's own requirements stated in the metric module; completeness = every requested input identity has an HDF5 file that opens. **No segment-length arithmetic**: `SEGMENT_LENGTH` is a scorer constant the handle must not re-declare (§19, §19.2); the scorer's `reshape` boundary stays the frozen mechanism |
| 6 | Deliverables argument shape | route (i) has `sample_set` + `denoised_filename_fn` (abs paths, `:5305-5319`); route (ii) has one `full_path` + `file_index` | `check(deliverables: Mapping[int, str])` — input identity → path, as the scorer will open it (roadmap §4.3 "indexed by input identity"); the caller derives it — no TIDMAD-shaped signature on the generic handle |
| 7 | Handle vs spec | §9 "invoked *through* it"; C2 "accept the handle (or the spec)" | `EvaluationMetric` (plain ABC, holds `spec`) is the handle; `evaluate(deliverables, /, **compute_kwargs)` — TIDMAD's kwargs are `score_vector`'s own, unchanged |
| 8 | "Unknown direction rejected" (design C1 §4) | `MetricDirection = Literal["higher","lower"]` | not pytested — CLAUDE.md forbids testing what a `Literal` declaration enforces; recorded here instead |

**Residual recorded (not a deviation)**: the frozen scorer addresses channels
POSITIONALLY by literal (`f"channel{ch:04d}"`, `:149`) — under Regime A the
contract's groups (read from `DeliverableSpec`) coincide with them. A
renamed-channel profile would pass the contract and then fail inside the scorer:
scorer genericization is not authorized in Step 06 (D14 / arithmetic-adjacent);
the C1 test `test_a_renamed_deliverable_spec_moves_the_contract_with_it` pins
only that the contract holds no second copy of the TIDMAD names.

**Finding for C3 (recorded now)**: `tests/unit/core/test_step05c_c2_reader_migration.py::FORBIDDEN_CONSUMERS`
lists `denoising_score_single.py` and `scoring_utils.py` as forbidden
`deliverable_spec` consumers *because they are "the Step-06 boundary"*. Step 06
is that owner: C3 will migrate `denoising_score_single.py:163,166` (the two
literals 05c left for Step 06, §20.1 fact 9) to `DeliverableSpec.naming` and
move that ONE file out of the forbidden census with this reason;
`scoring_utils.py` stays forbidden (arithmetic untouched).

**Validation.**

```text
command:  .venv/bin/python -m pytest tests/unit/execute_tools/test_step06_c1_evaluation_metric.py \
              tests/unit/core/test_step06_c0_two_route_oracle.py -q
result:   29 passed in 3.94 s (25 new + 4 C0)   ruff check / format clean
zero production importers: asserted (test_zero_production_importers_at_c1)
configs/: untouched;  no existing schema gained a field;  git diff on tracked
files: empty (two new files only)
```

New tests, each with its unique failure class: TIDMAD derivation == precedent
literals; contract declared against `DeliverableSpec` (+ renamed profile moves
it); scalar-only + lower-is-better constructible; loss identity refused on all
three types ×6 identities; `loss_history` under any key refused + no loss
field structurally; boundary is by identity (`mse` accepted);
NotScoreableResult needs a failure; contract accepts the production writer's
file; missing file / empty scope / non-HDF5 / missing channel / wrong dtype /
missing attr each a NAMED structured failure, no exception; every violation
reported; `evaluate` refuses BEFORE `_compute` (spy); TIDMAD handle forwards
kwargs verbatim and maps the 2-tuple; handle == derived spec.

### 20.4 C2 — the LIVE route through the handle

**Correction to C1 (source-grounded, before the route went live).**

```text
Previous assumption (§19 C1 §2, ledger §20.3 decision 5):
  "scoreability = required channels (the two the scorer addresses,
   scoring_utils.py:261-264, 396-401)" — C1 declared BOTH the input and the
  target channel group of the DELIVERABLE as required.

Audit evidence:
  The LIVE route is score_vector → _collect_raw_pairs (:440-488), which reads
  ch=2 from the RAW validation file (:470, `raw_filename`) and ch=1 from the
  DENOISED file (:477). The cited :261-264 (`process_segment`) and :396-401
  (`score_segments`) are not on the live path: `process_segment` is used
  only by scripts/compute_raw_baseline.py on RAW files; `score_segments` /
  `_score_one_file` are "kept for backward compatibility" (:411-417) with
  no production caller.

Corrected understanding:
  The frozen scorer requires, OF THE DELIVERABLE, the input channel dataset
  (ch=1), the two attrs on that group, and (evaluation-side) the declared
  storage dtype. The deliverable's target group is written by the producer
  (05c) but never read by the live scorer; requiring it would make the
  contract STRICTER than the frozen instance and would refuse a deliverable
  the scorer scores today.

Implementation consequence:
  `TidmadScoreabilityContract` drops `target_channel_group`; requirements =
  completeness · required input channel · required attrs · required dtype.
  Derivation reads `input_channel_group` + `storage_dtype` from
  `DeliverableSpec.storage`.

Validation consequence:
  C1 tests updated: `test_a_missing_input_channel_is_named` (ch=1 group
  absent → named failure) and NEW `test_an_input_only_deliverable_is_scoreable`
  (create_abra_file with array2=None → scoreable), which guards the contract
  against becoming stricter than the scorer again.
```

**Route (i) wiring.**

| Site | Change |
|---|---|
| `core/sandbox_executor.py::TidmadSandbox.evaluate_metric` (NEW) | the live seam: `validate_sample_set(scope)` FIRST (unchanged boundary invariant) → deliverables `{file_index: os.path.join(base_dir, denoised_filename_fn(fi))}` (exactly the path `score_vector` opens) → `metric.evaluate(deliverables, data_dir=…, sample_set=…, anchor_map=…, s_max=…, denoised_filename_fn=…, raw_data_dir=self.dirs["data"], profile=resolve_dataset_profile(), **kwargs)` → returns `MetricResult`; a `NotScoreableResult` is raised as `NotScoreableError` (typed, carries the structured result). `profile=` is threaded explicitly (design §19 C2) — the same object `score_vector` resolved ambiently before |
| `TidmadSandbox.score_vector` | now a thin wrapper: `metric=None` → Regime-A `derive_tidmad_metric(resolve_dataset_profile())`; returns `(result.per_sample, result.scalar)` — legacy callers observe identical values |
| `StubSandbox.evaluate_metric` (NEW) | pseudo mirror: one `score_vector` draw (same RNG stream, so pseudo values are unchanged) returned as `MetricResult` under the handle's REAL identity/direction — the run's declaration, not an invention |
| tuner `run()` :3757+ | `run_metric: EvaluationMetric = derive_tidmad_metric(run_profile, run_deliverable_spec)` — bound once beside `run_profile` / `run_model_io` / `run_deliverable_spec` |
| tuner live call (was `:5321-5326`) | `metric_result = sandbox.evaluate_metric(run_metric, sample_set=eval_sample_set, anchor_map=…, s_max=…, denoised_filename_fn=_denoised_fn)`; `file_vector, final_scalar = metric_result.per_sample, metric_result.scalar` — everything downstream (gates, `score_res`, record write) unchanged |
| tuner scoring `except Exception` | the inline `error_scoring` dict EXTRACTED to `_build_scoring_failure_record(exc, …)` (module-level, typed, tested); `run()` gains NO branch |
| `evaluation_metric.NotScoreableError` (NEW) | `Exception` carrying `.result: NotScoreableResult`; message names contract, metric and every violated requirement |

**Decision — where a not-scoreable outcome lands (design C2 §3/§6).**

| Question | Evidence | Decision |
|---|---|---|
| Return the union or raise? | `run()` sits at pyright's complexity ceiling — the outer handler says so verbatim ("one more clause on this try pushes run() past pyright's complexity-analysis ceiling", `:6058-6063`); the tuner's scoring `try/except` IS the round-outcome path for every scoring-phase failure (V8 Domain 2a, `:5280-5287`); `TidmadSandbox.score_vector`'s documented contract is exception-based (`:1878-1884`) | the sandbox seam raises `NotScoreableError`; the handle itself still RETURNS the structured `NotScoreableResult` (C1) — the exception is a typed carrier across the one seam whose contract is exception-based, never an incidental scorer error |
| Which existing status? | `error_scoring` = "no score produced; terminated before gate evidence" (`health_feedback.PRE_GATE_ERROR_STATUSES` :93-104); `failed_mode_collapse` is a HealthGate verdict (Step 08); `is_degenerate`/`failure_reason` are score-validity fields on a `success` record | **`error_scoring`** — honest for "no score, no gates"; the record additionally carries `failure_stage="scoring"`, `failure_type="not_scoreable"` (existing free-text fields) and prose naming contract + violated requirements; the "Scoring crashed" wording is NOT used for a refusal. No new status |
| Round-outcome semantics | Step 07a owns them | unchanged: an `error_scoring` record → `continue` to the next attempt exactly as before |

**Test disposition (the seam moved, so its stubs moved).** 13 tuner tests stubbed
`mock_sandbox.score_vector.return_value`; the live seam is now `evaluate_metric`,
so those stubs were aimed at a retired entry point (the exact class the unit
conftest guard exists for). UPGRADED through ONE shared helper
`tests/helpers/scoring_stubs.py::stub_scoring(mock_sandbox, file_vector, scalar)`
which stubs BOTH seams with the same values (9 files, 13 sites).
`tests/helpers/recording_sandbox.py::RecordingSandbox` (the drop-in
`TidmadSandbox` double) gained the mirrored `evaluate_metric` (same predefined
FIFO, records `("evaluate_metric", metric_id, direction)`), which is what makes
the reachability test possible. `tests/unit/core/test_step05c_c2_reader_migration.py`
`scorer_closure` end-anchor updated from `sandbox.score_vector` to
`sandbox.evaluate_metric(` (its block — `_denoised_fn` — is unchanged).
Step-00 REC-2/REC-3 goldens: pass unchanged (record shape untouched at C2).

**New tests.** `tests/unit/core/test_step06_c2_live_route.py` (6): live route
== C0 literal through the handle; legacy 2-tuple seam unchanged (Regime A);
unscoreable set → `NotScoreableError` BEFORE `score_vector` (spy raises if
reached); scope validation still precedes scoreability; StubSandbox mirror
under a contrast identity; the inverted C1 inertness assertion (consumer census:
MIGRATED = sandbox + tuner; FORBIDDEN = `scoring_utils.py`, `inference_single.py`,
`workflows/model_exploration.py`, `core/resume.py`, dashboard sources).
`tests/unit/agent/tune_ml_hyperparam_agent/test_step06_c2_tuner_metric_binding.py`
(7): the PRODUCTION loop (Step-00 pseudo harness, real `run()`) scores through
the TIDMAD handle and never the legacy seam; a contrast handle swapped at the
run-scope derivation reaches the seam (reachability, not inspection); the
extracted record helper: byte-for-byte parity for a generic exception (incl. the
pre-existing doubled type name in `discovery`, preserved), the not-scoreable
description (status `error_scoring`, `failure_stage/type`, requirement named, no
"crash"), the live `except` calls the helper, non-refusals never gain
`failure_type`.

**Validation.**

```text
targeted:  42 passed 8.9 s  (C0 4 · C1 26 · C2 core 6 · C2 tuner 7 — before census add: see log)
pseudo:    tests/integration/workflows/test_data_scope_tuner_pseudo.py
           tests/integration/workflows/test_healthgate_ten_collapse_continuation.py
           tests/integration/nodes/test_step05b_checkpoint_c.py
           tests/integration/workflows/test_full_exploration_loop.py
           → 11 passed, 2 skipped in 237 s (StubSandbox / RecordingSandbox routes)
subsystem: tests/unit/agent/tune_ml_hyperparam_agent tests/unit/core tests/unit/execute_tools
           → 4503 passed, 3 skipped in 345.9 s, rc=0 (read from the log file)
scoring_utils.score_vector diff: EMPTY (git diff --stat lists no scoring_utils.py)
```

### 20.5 C3 — the SUBPROCESS route through the handle

**Child (`execute_tools/denoising_score_single.py`).** After the profile is
loaded (fail-closed / Regime A, unchanged `:150-154`): `deliverable_spec =
derive_tidmad_deliverable_spec(dataset_profile)`; `metric =
derive_tidmad_metric(dataset_profile, deliverable_spec)` — ONE derivation each,
from what already crosses (05c §3.2a Option A; no spec/metric serialized, **no
new argv**). The two deliverable-name literals 05c left for Step 06 (§20.1 fact
9) now resolve through `deliverable_spec.naming.unqualified_name(...)` (fix
mode) / `.name(...)` (agent mode) — byte-identical names; the `"none"` raw
branch is unchanged. Scoring is `metric.evaluate({file_index: full_path},
**exactly the kwargs score_vector received before**)`. On a
`NotScoreableResult`: each violated requirement is printed to **stderr**
(always captured by the parent's `_format_subprocess_error`), the structured
payload (`denoising_score: None`, `file_vector: None`, `not_scoreable:
<NotScoreableResult json>`) is merged into `--output_json` when the parent
pre-created it, and the child exits **1** — the same exit the retired "File not
found" pre-check used, so the parent's existing classifier says `"error"`
(design C3 §6 — no new status) and every caller's handling is unchanged. The
pre-check itself is retired: a missing deliverable is now the contract's
`completeness` refusal (structured), on the same exit code.

**Parent.** `execute_scoring` argv **byte-identical** (C0 golden runs against
this code and passes); merge unchanged. Callers `scripts/run_comparison.py`
and `agent/skills/denoising_score_skill/wrapper.py`: `git diff` empty.

**Census updates (05c guards that named Step 06 as the owner).**
`tests/unit/core/test_step05c_c2_reader_migration.py`: `denoising_score_single.py`
moved from `FORBIDDEN_CONSUMERS` (whose comment says it is "the Step-06
boundary") to a new `STEP06_CONSUMERS` tuple, asserted as a consumer;
`scoring_utils.py` stays forbidden. `tests/unit/execute_tools/test_step05c_c7_stage_b_rung.py`:
the file left `OUT_OF_RUNG_FILES` (its docstring: "legitimately keeps its
literals until Step 06"); the historical scripts stay. Step-06 census
(`test_step06_c2_live_route.py::MIGRATED_CONSUMERS`) gained the child.

**Validation.**

```text
new:      tests/unit/execute_tools/test_step06_c3_subprocess_route.py (5)
            structure: exactly one derive_tidmad_metric / derive_tidmad_deliverable_spec /
              resolve_dataset_profile call; no executed deliverable-name literal;
              scoreability precedes arithmetic (no direct score_vector call)
            REAL child (allow_real_subprocess): int16 deliverable → parent "error",
              message names "[tidmad_denoised_h5] required_dtype … int16 … int8", no
              Traceback; --output_json carries the structured not_scoreable payload
              (metric_id, direction, requirement, input_identity)
            REAL child: missing deliverable → "completeness: deliverable not found at",
              no Traceback
parity:   tests/unit/core/test_step06_c0_two_route_oracle.py — route (ii) REAL child ==
          route (i) == C0 literal, argv golden — 4 passed against the C3 code
neighbours: test_step05c_c2_reader_migration, test_step05c_c7_stage_b_rung,
          test_step02a_c4_inference_scoring, test_step02a_c1_baselines,
          test_step05c_c6_launcher_reconstruction, test_sandbox_executor,
          test_step06_c2_live_route → 137 passed;
          tests/integration/execute_tools/test_step02a_checkpoint_c_profile_boundary.py
          -k "fails_closed or omitted_flag or imports_this_checkout" → 7 passed (real child)
ruff check / format: clean
```

### 20.6 C4 — the additive record payload

**Schema** (`agent/schemas/hyperparam_tuning.py::ExperimentRecord`, appended
after the last field): `metric_result: MetricResult | None = None` and
`metric_refusal: NotScoreableResult | None = None` (names now the
implementation's), plus a `model_validator` `_metric_payload_agrees_with_the_score_fields`
and a module helper `_same_score` (non-finite values equal their storage image
`None` and each other). `denoising_score` / `file_vector` / `score_table`
untouched. Ordered field list 54 → 56, positions of every earlier field
unchanged. `HyperparamTuningOutput` untouched (D1).

**Write sites.** Tuner: `metric_payload = metric_result.model_dump(mode="json",
exclude={"per_sample"})` set in the anchor-map branch (initialised `None`
before the scoring `try`, no branch added to `run()`); the success record gets
`"metric_result": metric_payload`. Refusal: `_build_scoring_failure_record`
adds `"metric_refusal": exc.result.model_dump(mode="json")` on a
`NotScoreableError`. Pseudo (`RecordingSandbox` / `StubSandbox`): the mirror
seams return a `MetricResult` under the run's real identity, so pseudo success
records carry the payload with the pseudo values (as `denoising_score` already
does). Legacy skill route (`_run_skill("denoising_score_skill")`): `None` — the
child's payload is not the handle's, and (below) the child adds no key.

**Two source findings that shaped the placement (both bounded; recorded).**

```text
Finding 1 — the reflector prompt json-dumps score_results VERBATIM
  Evidence: ml_hyperparameter_tune_agent.py `reflect_results = {**train_results,
  **score_results}` → agent/prompts.py:1343 `json.dumps(actual_results)`.
  Consequence: `metric_result` is NOT put into `score_res["results"]` (a first
  draft did; WF-2 `wf2_reflect_call_surfaces` went red — the guard worked). It
  travels as its own local to the record write. Reflector prompt bytes:
  UNCHANGED (WF-2 golden passes untouched). The child's --output_json keys stay
  exactly the C0 two for the same reason (the legacy skill route feeds the same
  dump); the additive `not_scoreable` payload is written only on the exit-1
  path the parent never merges.

Finding 2 — the planner prompt json-dumps the last 3 records VERBATIM
  Evidence: agent/prompts.py:876-903 `_truncate_memory_history` keeps the most
  recent `full_window=3` records unchanged; :978 `json.dumps(windowed)`.
  Consequence: any additive record key is planner-visible data. Kept minimal:
  `per_sample` is stored as a POINTER (design §5 "per_sample (or a pointer to
  file_vector)") — the key is EXCLUDED from the persisted payload, `file_vector`
  on the same record IS the evidence — so the vector is not doubled in the
  history dump; `metric_refusal` is written only on refusal records. The
  planner therefore sees, on the last three success records,
  `"metric_result": {"metric_id","direction","scalar","references_used"}`.
  Gate reading: the standard's row "Config files, YAML, schema-only → Unit
  only" (design §13 quotes it as binding) covers an additive record field —
  the prompt TEMPLATE is unchanged, no placeholder changed, and every prior
  additive record field (candidate_id, ordering provenance, gate fields,
  scientific_authority) landed the same way. Gate 1 stays NOT REQUIRED;
  recorded here so the reviewer can disagree with a citation.
```

**Finding 3 — the collapse penalty.** `_apply_degeneracy_reaction` (:1929-1990)
REPLACES `denoising_score` with `degenerate_penalty_score` (or `None`) on a
formal collapse — Step 08/07a policy — while the metric's own result is the
evaluation. So "one value, two names — they must agree" holds on `success`
records (validated) and is deliberately NOT applied on `failed_mode_collapse`
(the raw metric result stays beside the penalised score; documented on the
field). `metric_result` / `metric_refusal` are validated mutually exclusive.

**Step-00 goldens — intentional-change regeneration (§17 rule 3, same commit).**
REC-1 inline list `EXPERIMENT_RECORD_FIELDS_54` → `_56` (+`metric_result`,
`metric_refusal`, annotated). REC-2 `rec2_formal_success_projection.json` (+
`metric_result` payload, `metric_refusal: null`) and `rec2_oom_skip_projection.json`
(+ both `null`), REC-3 `rec3_summary_entry_key_lists.json` (+ `metric_result` on
the two success entries) — regenerated by the SAME producer path the tests use
(`run_bounded_pseudo_iteration` + `project_record`), `_captured_at` provenance
= C3 head + regeneration note pointing here. Diffs are purely additive (reviewed
line by line). WF-2 golden: unchanged.

**Validation.**

```text
new:  tests/unit/agent/tune_ml_hyperparam_agent/test_step06_c4_record_payload.py (10)
        live path (real run(), pseudo harness): success records carry TIDMAD id/direction,
          scalar == denoising_score, per_sample None (pointer), raw dict has the key and
          no refusal key; skipped records carry neither key
        replay: pre-Step-06 record dicts (same raw dicts minus the added key) validate and
          read None; the committed Step-00 run_output_iter_001.json validates
        negatives: payload disagreeing with denoising_score → rejected; evidence
          disagreeing with file_vector → rejected; collapse penalty → accepted;
          result+refusal → rejected; -inf → null round trip validates on both fields
        refusal record from _build_scoring_failure_record validates with the structured
          NotScoreableResult
step-06 suite: 32 passed 13.3 s;  Step-00 record+choreography baselines: 12 passed
subsystems: tests/unit/agent tests/unit/nodes tests/unit/workflows tests/unit/dashboard
            tests/unit/core → 6710 passed, 2 skipped in 457.9 s, rc=0 (read from the log)
```

### 20.7 C5 — boundary negatives and the structural guard

**Boundary negatives** landed at C1 (`test_step06_c1_evaluation_metric.py` §3:
six loss-shaped identities refused on `MetricSpec` / `MetricResult` /
`NotScoreableResult`; `loss_history` / `final_loss` / `train_loss` refused
under any key by `extra="forbid"`; no field named `*loss*` on any metric type;
`mse` accepted — the boundary is by identity, not formula). Referenced, not
duplicated.

**Structural guard** — `tests/unit/execute_tools/test_step06_c5_boundary_and_structure.py`
(12 tests, AST over EXECUTED string constants, docstrings excluded — the 05c
helper `_executed_string_constants`):

| Property | Assertion | Same-authority migration it forced |
|---|---|---|
| `tidmad_denoising_score` declared exactly once | across `nodes/ agent/ core/ execute_tools/ ml_models/ workflows/ scripts/ dashboard/` the literal is an executed constant ONLY in `execute_tools/evaluation_metric.py` | `execute_tools/per_file_best.py:360` (the pre-Step-06 precedent) now `from execute_tools.evaluation_metric import TIDMAD_METRIC_ID` — emitted value and key set unchanged (NUM-8 golden + `test_per_file_best` pass; asserted again here through the real `build_table` over the RES-1 workspace). Import direction is cycle-free (evaluation_metric imports nothing from per_file_best) |
| no executed hardcoded DIRECTION where the handle is available | no production module executes a `"higher"` / `"lower"` constant except the metric module, and there exactly `Literal["higher","lower"]` (vocabulary) + `direction="higher"` (TIDMAD derivation) | none needed — the owned scoring surfaces (tuner live route, `TidmadSandbox`, scorer CLI) hold no direction literal |
| the D1 / Step-07a NOT-reached list is ASSERTED (§16-Q6) | 9 exact executed comparisons still present: tuner incumbent selection ×4 (`max(candidates, key=…denoising_score)` :1504, `max(successful, …)` :5728, `max(successful_records, …)` :6330, `current_score > best_score` :5818 — Step 07a); workflow `tune_output.best_formal_denoising_score > best_score_overall` (:2760 — the design's ":2740" moved); `core/resume.py` `if score > best_score or (` (:438); `per_file_best._row_beats` `>` (:480); dashboard `local_json.py` `reverse=True` (:245) and `base.py` "higher is better" (:119) | none — the guard fails in the direction people get wrong: migrating one of them later must be recorded as reached, not silence the guard |

**Validation.** `test_step06_c5_boundary_and_structure.py` + `test_per_file_best.py`
+ `test_step00_numeric_baselines.py` → 42 passed 6.5 s; ruff clean.

### 20.8 C6 — Stage-B rung: the metric-direction axis

`tests/unit/execute_tools/test_step06_c6_stage_b_direction_rung.py` (3 tests).
The contrast: `MeanAbsAmplitudeMetric` — a scalar-only, `direction="lower"`
metric (mean |int8| amplitude of the denoised channel, `PresenceScoreabilityContract`,
`per_sample=None`) — an ATOMIC fixture on the learning-objective dimension at
TIDMAD's topology (roadmap §21.4); no image/spatiotemporal track (§21.3), no
incumbent selection under it (Step 07a), no declaration (Step 12).

| Test | What it proves |
|---|---|
| through the REAL seam on a REAL deliverable | `TidmadSandbox.evaluate_metric(contrast, …)` on the C0 fixture → `MetricResult(metric_id=step06_mean_abs_amplitude, direction="lower", per_sample=None)`; the shipped derivation in the same process still yields TIDMAD / `higher` |
| through the PRODUCTION loop | run-scope derivation swapped for the contrast handle → every success record's `metric_result` carries the contrast identity, `direction="lower"`, `scalar == denoising_score`; shipped derivation object unchanged in the same process |
| negative | an unpatched run carries exactly `{(tidmad_denoising_score, higher)}` on every scored record and never the contrast id at the seam — the rung cannot pass because a seam returns the contrast unconditionally |

One axis moved (direction + the scalar-only shape that comes with it); the
seam, the loop, the record write and the TIDMAD instance are untouched.
Validation: 3 passed (with C5: 15 passed 5.8 s); ruff clean.

### 20.9 C7 — mutations per semantic family + Checkpoint C

#### (a) Checkpoint C — the handle across the REAL scoring boundary

`tests/integration/execute_tools/test_step06_checkpoint_c_metric_boundary.py`
(3 tests, **67 s** on this host, CPU; not in CI by design). Reuses the 05c
Checkpoint-C harness (real `train_engine_sandbox.py` → real `inference_single.py`
spawns, PYTHONPATH pinned to this checkout) at FULL segment length
(`psd_segment_length` 10 M, `segments_per_file=1`, `num_files=1`,
`segmentation_size` 10,000 — the trainer requires it to divide the segment,
`train_engine_sandbox.py:398`; the 4,096 geometry cannot be scored, §20.2),
1-block WaveNet, one epoch batched, one segment inferred. Then:

| Test | Proves |
|---|---|
| the real producer's deliverable satisfies the acceptance contract | the 05c representation (written by the REAL `inference_single`) and the Step-06 `TidmadScoreabilityContract` AGREE on a real artifact — the two halves of the ownership split (§4, Q1) meet |
| the two REAL routes agree on the real deliverable | in-process `evaluate_metric(run_metric, …)` == the REAL `execute_scoring` child (which reconstructs the metric from `--dataset_profile_json`) — `denoising_score` and `file_vector` exact, finite, TIDMAD identity/direction |
| the structured refusal crosses the real child | an int16 deliverable under the same name → parent `"error"`, message `[tidmad_denoised_h5] required_dtype`, no `Traceback`, `not_scoreable` payload persisted |

Helper-only would have been insufficient (05c §6): this is the seam being
real end to end — producer → deliverable → both scoring routes → structured
outcome. Gate 2 stays NOT REQUIRED (§13): parity is deterministic and this
Checkpoint is the live-integration evidence.

#### (b) Mutation evidence — one per independently failing semantic family

Scratch runner (`<scratchpad>/mutations_c7.py`, not committed — no home in the
tree; 05c precedent). Hygiene: target occurrence asserted **== 1** before each
edit; every `__pycache__` cleared before every run; each file restored with
`git checkout --`; baseline green before the first and after the last mutation.
Selector for every family: the eight Step-06 test modules (C0–C6), `-x`.

| # | Semantic family | Mutation | Result |
|---|---|---|---|
| 1 | identity swap | `TIDMAD_METRIC_ID` → `"tidmad_denoising_score_v2"` | **RED** |
| 2 | direction flip | TIDMAD derivation `direction="higher"` → `"lower"` | **RED** |
| 3 | aggregation substitution | `TidmadDenoisingMetric._compute` returns the mean of the per-file vector instead of `score_vector`'s scalar (the forbidden mean-of-means) | **RED** |
| 4 | scoreability bypass | `EvaluationMetric.evaluate` skips the verdict (`if False and not verdict.scoreable`) → arithmetic reached on an invalid artifact | **RED** |
| 5 | route divergence (child) | `denoising_score_single.py` passes `s_max * 2.0` to the arithmetic | **RED** |
| 6 | declared once | `per_file_best` restates the `"tidmad_denoising_score"` literal instead of importing it | **RED** |
| 7 | live route bypasses the handle | the tuner's scoring call re-derives the metric at the call site instead of reading `run_metric` | **SURVIVED → classified → RED** (see below) |
| 8 | record payload disagrees | the tuner writes `metric_result.scalar + 1.0` | **RED** |

**Survivor classification (family 7).** Not a production gap: the mutated
call site still scores through the handle and yields identical values; the
oracle was the weak part. The C2/C6 reachability tests replaced the
derivation FUNCTION with an always-contrast stub, so a call-site
re-derivation returned the same contrast — EQUIVALENT under that oracle. The
tests were strengthened rather than a superficial assertion added: the stub
now returns the contrast **only on the first derivation** (the run-scope
binding) and the shipped instance afterwards, and asserts exactly one
derivation per run. Under production the seam sees the contrast on every
scoring call; under the mutation it sees TIDMAD. Re-run: family 7 **RED**;
baseline green again after restore. **8 families, 8 killed, 0 survivors.**

Log: `<scratchpad>/mutations_c7.log`, `mutations_c7.stdout` (RESTORED
BASELINE rc=0; `git status` clean after the battery).

### 20.10 C8 — Gate disposition, ownership verdict, docs, terminal validation

**Gate disposition (C8).** Gate 1 **NOT REQUIRED**, Gate 2 **NOT REQUIRED** —
exactly as frozen in §13 / §16-Q5 and confirmed by implementation: no prompt
template or `LLMBridge` kwarg changed (WF-1/WF-2 choreography goldens
unchanged; the reflector's `score_results` is byte-identical; the planner's
history dump gains only the additive record key — the standard's "schema-only →
unit only" row, §20.6 finding 2), scorer arithmetic / deliverable bytes /
subprocess argv untouched (§13 flip conditions not met). Neither Gate was
launched. Replacement evidence as §13 lists: Checkpoint C (real chain, §20.9a),
the two-route oracle (§20.2), the scoreability negatives on both routes
(§20.4/§20.5), and the mutation families 8/8 (§20.9b).

**Deliverable-Contract ownership verdict (OD-20-7) — CONFIRMED.** Step 06 owns
the evaluation-side ACCEPTANCE contract (`TidmadScoreabilityContract`, declared
per instance) and the deliverable facts required for scoreability; Step 05c
retains EXCLUSIVE producer-side representation (`DeliverableSpec`). The metric
REFERENCES the spec (channel group + dtype are read from it) and never
redefines it. Evidence the split is real, not prose: the contract's
requirements moved with a renamed spec (C1), a real producer's artifact
satisfied the contract (Checkpoint C), and the scorer's own reads (`ch=1`,
the two attrs, dtype) are what the contract requires — no more (§20.4).
Consequence for 05c's open debt: the two instrument attrs the scorer reads are
now DECLARED as evaluation-side requirements; how they are WRITTEN stays in
`create_abra_file` (producer). Whether the writer should derive them from a
declaration is a producer-side question — recorded, not decided here.

**Direction consumers NOT reached (D1 / Step 07a) — enumerated and asserted
(§20.7):** tuner incumbent selection ×4; `workflows/model_exploration.py`
best-formal comparison; `core/resume.py` best-record comparison;
`execute_tools/per_file_best.py::_row_beats`; dashboard `local_json.py` sort /
`base.py` docstring.

**Doc sync (CLAUDE.md rule, last pre-merge step) — quoted against merged
source:**

| Doc | What changed | Verified against |
|---|---|---|
| `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md` | loop step 5 (scoring through the handle, refusal → `error_scoring`/`not_scoreable`); Output table rows `metric_result` / `metric_refusal`; Storage outputs bullet (runtime-only handle, no argv); new section "Evaluation metric handle (Step 06)" | `ml_hyperparameter_tune_agent.py` run-scope binding, `evaluate_metric` call, `_build_scoring_failure_record`; `hyperparam_tuning.py` fields |
| `docs/architecture.md` | new section "Evaluation Metric Interface (shipped 2026-08, Step 06)" | `execute_tools/evaluation_metric.py`, `sandbox_executor.py`, `denoising_score_single.py` |
| `CLAUDE.md` Subsystem Invariants | new bullet: scoring goes through the handle; order DataScope → contract → arithmetic; refusal semantics; declared-once ids | same |
| this design (§12, §18, §19 checklists, §20 ledger) | live | — |
Roadmap §15.1 row and README index mirror: **post-merge**, per the governance
convention (05c precedent: finalizer commit after merge) — not touched here.

**Terminal validation (final executable head = the C7 production state;
docs-only commits after it):**

```text
tree:      clean at 271d19bb — CORRECTED (audit, §20.11): the last production commit of
           the FIRST review round was 15c4dd08 (pyright narrowing), made AFTER this run;
           the binding terminal evidence for that round was CI on 15c4dd08 / 0c5b6de7
subsystems: .venv/bin/python -m pytest tests/unit/agent/tune_ml_hyperparam_agent tests/unit/core \
                tests/unit/execute_tools tests/unit/scripts -q
           → 5074 passed, 3 skipped in 359.1 s, rc=0 (read from <scratchpad>/terminal_run.log)
earlier at the same production state: agent+nodes+workflows+dashboard+core 6710 passed (C4);
           tuner+core+execute_tools 4503 passed (C2); pseudo integration 11 passed (C2)
Checkpoint C: tests/integration/execute_tools/test_step06_checkpoint_c_metric_boundary.py
           → 3 passed 67 s (C7, same production state)
ruff check . / ruff format --check .  → clean (repo-wide)
pyright:   CI-only on this host (Node v10 cannot run the vendored pyright) — recorded limitation
CI:        exact-head run recorded below at PR time
```

**CI iteration.** PR #213 opened at `0c219e9a`. CI run 31874116566 → FAILURE at
"Type check — pyright (strict, blocking)": ONE error, in the tuner's live-route
unpack — `metric_result.per_sample` is `list[float | None] | None` on the
generic result (a scalar-only metric carries none) while
`HealthCheckContext.file_vector` requires `list[float | None]`; the pre-Step-06
`sandbox.score_vector` returned an untyped `tuple`, which is why this was
invisible before. Fix (production, one expression): `file_vector =
list(metric_result.per_sample or [])` — TIDMAD always supplies a vector, a
scalar-only instance yields an empty one to the gate context; behaviour on the
TIDMAD route unchanged (109 affected tuner tests green). The 4 pyright warnings
are pre-existing (`core/runtime_control/*`, `scripts/legacy_fcnet_timing.py`),
non-blocking, not Step-06 files. pyright cannot run on this host (Node v10) —
CI is the only environment for it, as recorded.

**Exact-head CI: run 31874417871 — SUCCESS on `15c4dd08b09d4ec97a6251c776149aa81eccc0c3`**
(ruff check · ruff format --check · pyright strict · unit tests, all green).
Three-way identity READ, not reconstructed: local `git rev-parse HEAD` ==
PR #213 `headRefOid` == CI `headSha` == `15c4dd08…` (the docs commit below
moves the head; its CI is recorded in the handoff / PR).

**Status at that point: PR #213 READY FOR OPERATOR REVIEW — DO NOT MERGE** (superseded by the
corrective round §20.11; the exact final head/CI is recorded there). Post-merge
obligations (next context, finalizer): roadmap §15.1 `§10 Metric interface`
row → COMPLETE with the merge SHA; README index mirror; this doc's header →
IMPLEMENTED/MERGED.

### 20.11 Corrective scope after the read-only adversarial review (operator, 2026-08-15)

The operator's read-only audit of PR #213 @ `0c5b6de7` found **no correctness
or frozen-invariant failure** (arithmetic, scoreability ordering, two-route
parity, ownership split, Checkpoint C, mutations, Gate 2 all PASS) and
authorized exactly three merge-before items. Everything else the audit raised
(lexical loss-id rule, mandatory-scalar runtime validator, scalar-only
`file_vector=[]` semantics, D1 census completeness, import hygiene) is
**FOLLOW-UP DEBT — explicitly out of this scope**.

**Item 1 — planner visibility (ownership boundary, not just Gate 1).** Audit
fact chain, confirmed from source: `ExperimentRecord.metric_result` →
`sandbox.get_summary()` → `bridge.plan(memory_history)` →
`get_planner_user_prompt` → `_truncate_memory_history` keeps the last 3 records
VERBATIM → `json.dumps` → planner user message. So §20.6's "schema-only" framing
was wrong in effect: planner message bytes DID change, and on a
`failed_mode_collapse` record the LLM would have seen the raw
`metric_result.scalar` beside the penalised `denoising_score` with no
lifecycle explanation. Step 06 persists the payload for Steps 07a / 09; it does
NOT own agent-facing rendering. **Fix**: `agent/prompts.py` gains
`_PLANNER_HIDDEN_RECORD_KEYS = {"metric_result", "metric_refusal"}` and
`_truncate_memory_history` drops exactly those keys from the verbatim window
(condensed entries already excluded them; the persisted record is untouched).
No prompt TEMPLATE changed; for a pre-Step-06 record the render is
byte-identical (PB-1 goldens pass unchanged). New test
`tests/unit/agent/llm_bridge/test_step06_planner_boundary.py` (5): bytes equal
with/without payload through the REAL bridge boundary (`BoundaryRecorderBridge`,
`_chat_json` capture); condensed tail clean; persisted dicts untouched; the
collapse case renders only the policy-adjusted score; the hidden set pinned to
exactly the two Step-06 keys. Tuner .md row "what the LLMs see" corrected.

**Gate 1 — readiness packet (written BEFORE launch).**
```text
property:   with a REAL gpt-5.5 planner/reflector/proposer/implementor/validator,
            the chain whose tuner scores THROUGH the metric handle (pseudo training →
            StubSandbox.evaluate_metric) produces schema-valid outputs; the round-2
            planner receives round-1's record (now filtered) and yields a valid
            ExperimentPlan; NO planner message contains "metric_result"/"metric_refusal".
why not cheaper: the corrective commit touches the LLM-boundary serializer; the
            operator elected one Gate 1 as conservative evidence.
command:    run_one_iteration.py --workspace <scratch>/s06_gate1 --run_name s06_gate1
            --start_iteration 1 --max_rounds 2 --max_proposal_attempts 3 --max_epochs 1
            --data_scope 4-9 --health_gate_files 4,5,6,7,8,9 --healthgate_mode blocking
            --result_authority scientific --is_pseudo_training
            --llm_config llm_configs/openai_tiered_pro.json      (04a Gate-1 shape; cold-start)
tee:        a PASSIVE wrapper on LLMBridge._chat_json appends (label, lengths,
            contains-"metric_result"?, planner user_prompt) to llm_boundary_tee.jsonl
            before delegating unchanged — the artifact for the "no planner message"
            claim; behaviour unaltered.
bounds:     1 iteration, max_rounds 2, pseudo training, no GPU work; expected 3-8 min,
            hard timeout 20 min; ~$0.3; no retry on a model-judgment failure.
PASS:       GATE1_RC=0 read from the captured line (never the wrapper); run_output +
            records validate; every success record carries metric_result; tee shows
            zero planner messages with the payload keys.
```

**Gate 1 — RESULT: PASS** (launched 2026-08-15 12:07:46 local, ~8.7 min wall —
above the 3-8 min estimate, inside the 20-min bound; 12 real `gpt-5.5` calls,
316,474 tokens; exit status 0 read from the captured `wrapper_rc=` line, which is
the launcher's own status).

| Criterion (standard §Gate 1) | Evidence |
|---|---|
| LLM call completes without error | 12 boundary calls: proposer ×4, implementor ×2, validator ×2, tuner planner ×2, reflector ×2 — all completed |
| Output passes Pydantic schema validation | `run_output_iter_001.json` validates as `HyperparamTuningOutput` (status `completed`, 2 rounds, 2 records); `validation_iter_001.json` `passed=True` (instantiation / gradient / output_type / tests / llm_review all True); manifest written (`no_records` — see below) |
| Generated code compiles + dummy-tensor | `instantiation_passed=True`, `gradient_check_passed=True` (candidate `compact_spectral_gated_dilated_unet`, 2 implementor attempts) |
| **Step-06 property** — no planner message carries the payload | boundary tee: `metric_result` / `metric_refusal` in **0 of 12** user or system messages; the round-2 planner DID receive round-1's record (`exp_id`, `denoising_score` present in its 86,808-char user prompt) — the verbatim window is exercised and filtered |
| records carry the payload | both records: `metric_result = (tidmad_denoising_score, higher, scalar)`; the second is exactly the collapse case — `denoising_score=None` (formal collapse penalty) beside the raw `metric_result.scalar=-2.836` — persisted, NOT rendered |

Not a Step-06 finding: both records are `failed_mode_collapse` via
`output_diversity_blocking` ("all 6 peeked files failed I/O") because
`--is_pseudo_training` writes no deliverables while `--healthgate_mode blocking`
peeks them — the pseudo-mode consequence the 04a Gate-1 shape also has; the
chain exits gracefully with `manifest.status=no_records`. Artifacts (scratch,
this host): `<scratchpad>/s06_gate1_1786820866/` (+ `.log`, `llm_boundary_tee.jsonl`).

**Item 2 — C6 atomicity.** `test_step06_c6_stage_b_direction_rung.py` now
holds two rungs: **C6a** — the STRICT one-axis flip: `TidmadDenoisingMetric`
bound to `derive_tidmad_metric_spec(profile).model_copy(update={"id":
"step06_tidmad_denoising_score_lower", "direction": "lower"})` — asserted
field-by-field equal to the shipped spec except id/direction (same aggregation,
transform, references, and the SAME `TidmadScoreabilityContract`); through the
REAL seam on the C0 deliverable it returns the SAME scalar (`5.174659969078518`)
and the SAME `file_vector` as the shipped instance, only `direction` (and id)
differ; through the production loop (bind-once stub) every success record's
payload carries `direction="lower"` with `scalar == denoising_score`. **C6b** —
the previous `MeanAbsAmplitudeMetric` rung is KEPT and relabelled as the broader
different-metric evidence (scalar-only + different arithmetic + presence
contract), explicitly not the one-axis claim. §19 C6 acceptance "Nothing else
varied (one axis)" is now satisfied by C6a. Production untouched.

**Item 3 — governance.** The five C8 `[ ]` flipped (all were performed and
recorded in §20.10); §20.10 chronology corrected (the FIRST round's last
production commit was `15c4dd08`, made after the 5074-test run — CI on
`15c4dd08`/`0c5b6de7` was that round's binding terminal evidence); the stale
"Remaining operator decisions" header row corrected. Executable-head /
final-head CI for THIS round is recorded below when read.

**Validation (this round).**
```text
executable head of this round: 14591821 — CI run 31903559222 SUCCESS (ruff · format · pyright strict · unit)
the docs-only closeout commit on top has its own CI run; the exact merge head is what PR #213
  shows (three-way identity local == PR == CI is re-read in the handoff at close)
tests/unit/agent/llm_bridge + tests/unit/agent/tune_ml_hyperparam_agent
  + test_step06_c5 + test_step06_c6 → 1220 passed in 248.7 s, rc=0
  (first pass 1 failed: test_memory_history_truncation asserts IDENTITY of the
   verbatim-window records — the filter now returns the same object when a record
   carries no hidden key, copies only otherwise; pre-Step-06 identity preserved)
PB-1/PB-2 prompt goldens: unchanged, green.  ruff check/format: clean.
Gate 1: PASS (above).  Production diff this round: agent/prompts.py (data filter),
one tuner comment; tests + docs otherwise.
```
