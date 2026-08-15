# Step 06 — Metric interface — detailed design (DRAFT)

Roadmap §15 step 6, module §10. Roadmap row §15.1 `§10 Metric interface`.
Post-Step-05 addendum: roadmap **§20** (the semantic authority for the two
obligations this step inherits beyond §10).

| Field | Value |
|---|---|
| Status | **DRAFT — READY FOR OPERATOR REVIEW. NOT FROZEN. NOT IMPLEMENTED.** Revision 1 (2026-08-15). Implementation is NOT authorized by this document. |
| Design base | master `75525dc9` (Step 05 COMPLETE: 05a `cfb3b1c7`, 05b `5ce205d3`, 05c `03e00944`; finalizer `75525dc9`) |
| Depends on | Step 02 (`DatasetProfile`) · Step 03 (`ModelIOContract`) · Step 05c (`DeliverableSpec`, provisional) · roadmap §10, §14, §16, §20 |
| Owns | the **EvaluationMetric** interface; the **evaluation-vs-training-diagnostics boundary** (by exclusion); the **Deliverable-Contract confirm-or-say-why review** |
| Does NOT own | `TrainingHistory` / `TrainingDiagnosis` (Step 07, §20.2) · incumbent/threshold/skip-bypass policy (Step 07a) · HealthGate semantics (Step 08) · Interpreter consumption (Step 09) · the executable data path (D14, §20.5) · the two composed contrast tasks (Step 12 / M1, §20.3) |
| Risk | Medium-high: it touches the frozen scientific formula's *call path* (never its arithmetic) and the record payload every downstream reader keys on |
| Remaining operator decisions | **§16 — six, listed.** None blocks review; two block freeze |

---

## 0. Scope / capability

**Observable final capability (PROVISIONAL wording, to be frozen):**

> A task declares ONE primary evaluation metric — named, with explicit
> direction and aggregation, optional reference baselines, and a scoreability
> contract on the persisted deliverable — and PRODUCTION SCORING invokes it
> through that interface. The frozen TIDMAD scorer is instance #1,
> byte-identical in every value it produces. Optional secondary metrics are
> expressible. The metric's identity, direction and value are machine-readable
> on every record. **Training loss and validation loss are NOT evaluation
> metrics** and this step establishes that boundary by exclusion, leaving the
> generic surfacing mechanism to Step 07.

**Explicitly claimed**: metric identity · direction · aggregation semantics ·
reference/baseline slot · scoreability contract · one production consumer
(scoring) through the handle · record-facing payload · the TIDMAD instance
byte-identical.

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
| **Two live entry points.** (i) In-process: the tuner calls `sandbox.score_vector(...)` directly (`ml_hyperparameter_tune_agent.py:5321-5326` → `TidmadSandbox.score_vector` `sandbox_executor.py:1858-1897` → `scoring_utils.score_vector`). (ii) Subprocess: `TidmadSandbox.execute_scoring` spawns `denoising_score_single.py` (`sandbox_executor.py:1899-1971`) — used by `scripts/run_comparison.py:241` and `agent/skills/denoising_score_skill/wrapper.py:12`, **not by the tuner's live round path** | the tuner's scoring is in-process; §7c's "isolated argv contract" note (roadmap :843-844) describes route (ii) |
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

**What an EvaluationMetric IS (PROVISIONAL definition, to freeze):**

> A named, directional evaluation of the **persisted scientific deliverable**
> of one attempt: it produces a per-sample vector and a scalar aggregate,
> declares whether higher or lower is better, declares how per-sample values
> aggregate to the scalar, may carry reference baselines against which the
> scalar is interpreted, and states what the deliverable must satisfy to be
> scoreable at all.

**What it is NOT**: a training observation (no deliverable, no baseline, no
task-independent direction — roadmap §20.2); a health verdict (Step 08); a
policy (Step 07a).

**Semantic components — DECIDED as the component list, PROVISIONAL as to
field names:**

| Component | TIDMAD instance | Generic meaning |
|---|---|---|
| identity | `tidmad_denoising_score` (`per_file_best.py:360`) | stable id; the record key set extends around it |
| direction | higher-is-better | `higher \| lower` — explicit, never inferred |
| per-sample vector | length-20 `file_vector` (dense; `None` for out-of-scope files) | per-input-identity values indexed as §4.3 says ("INDEXED by input identity") |
| aggregation | anchor-normalised linear grand-mean → `log_5.27` | declared aggregation semantics; the TIDMAD one is the frozen instance's own function |
| references | raw baseline (`ScoreComparisonTable` raw row), anchor map, `baseline` exp_id | optional named references the interpretation layer may compare against |
| scoreability | (none today) | a **fresh** contract on the deliverable (§1.1 last row): what layout/dtype/completeness the metric needs — the natural home for the §1.2 finding |
| transform | `score_transform: "log"`, `log_base` | already emitted by `per_file_best`; carried, not re-declared |

**Deliverable-Contract ownership — the confirm-or-say-why (OD-20-7).**
PROVISIONAL RECOMMENDATION: **CONFIRM final-evaluation-side ownership of the
Deliverable Contract's *semantic identity*** — because (§1.2) the scorer reads
attrs and addresses channels inside the artifact, so scoreability cannot be
defined without owning what the artifact contains. Concretely: 05c's
producer-side `DeliverableSpec` (naming · cleanup · channel identity ·
storage representation) is **retained as the producer adapter**, and Step 06
declares the **scoreability contract** over it — the interior facts scoring
requires (channel addressing, storage dtype/offset, the two attrs it reads,
completeness of the sample set). Instrument attrs 05c left literal move from
"unowned debt" to "scoreability-owned facts". **Not confirmed here** — the
operator confirms at freeze (§16-Q1). If deferred, the reason must name the
consumer evidence still missing.

## 5. Metric schema / representation (PROVISIONAL)

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
file; the TIDMAD instance is derived with **no declaration** (regime A). If a
declared form is needed for the composed contrast tasks, it is an **additive
block inside the existing task configuration** (`configs/task_config.yaml`
already hosts `forward_contract`), never a new hierarchy — and its physical
placement is D4/D12 territory, decided when ≥3 module configs exist.
**Existing fields are untouched**: `denoising_score`, `file_vector`,
`score_table` keep their names and semantics; `MetricResult` sits beside
them so historical records validate unchanged.

## 6. Primary / secondary / mandatory metrics

- **Exactly one PRIMARY metric per task** — the one incumbent selection
  (Step 07a) will use. Mandatory. TIDMAD's is `tidmad_denoising_score`.
- **Secondary metrics — optional, zero or more**, recorded but never
  consulted by policy in this step. Whether TIDMAD gets any secondary
  instance in Step 06 is **§16-Q4** — the default recommendation is *no*
  (nothing in-tree consumes one; §0 rule 8).
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
| Checkpoint 0 | capture the **two-route parity oracle** — the exact `(file_vector, scalar)` for a fixed synthetic deliverable via BOTH `sandbox.score_vector` and the `execute_scoring` spawn, plus the `per_file_best` key set | new (the routes have never been pinned as equal to each other) |
| Stage A | frozen-formula pins, offline scalar baseline, `real_run` legacy parity, historical record/output validation | existing + one replay test |
| Stage B (atomic, one axis) | **metric-direction axis**: a lower-is-better scalar metric on stub outputs enters the record through the handle with `direction="lower"` and TIDMAD's identity/direction unchanged (roadmap §10.5) | new |
| Boundary negative | a loss-shaped "metric" is rejected; `loss_history` cannot populate `MetricResult` | new (§7) |
| Structural guard | no owned scoring consumer executes a hardcoded direction where the handle is available; the TIDMAD `metric_id` literal is declared once (05c "declared exactly once" pattern) | new |
| Mutations (per semantic family, count not frozen) | identity swap · direction flip · aggregation substitution · scoreability bypass · route divergence (in-process vs subprocess) | new; site count asserted 1, restored from clean, baseline re-verified — 05c hygiene |
| Checkpoint C | a **real** `execute_scoring` subprocess scores a real small deliverable through the handle; result equals the in-process route; helper-only is insufficient (05c §6 discipline) | new (reuse the 05c Checkpoint-C harness) |

Deliberately NOT tested here: incumbent selection under a lower-is-better
metric (Step 07a), Interpreter rendering (Step 09), dashboards (D1).

## 12. Checkpoint / acceptance criteria (semantic)

- [ ] a task can declare ONE primary metric; secondary metrics are optional
- [ ] identity, direction and aggregation are explicit and machine-readable on every record
- [ ] PRODUCTION SCORING (the tuner's live route) invokes the frozen TIDMAD instance THROUGH the handle
- [ ] the two scoring routes produce equal `(file_vector, scalar)` for the same deliverable
- [ ] the frozen TIDMAD values are byte-identical; `_LOG_BASE`/`s_max`/formula untouched
- [ ] historical records/outputs validate unchanged; regime A resolves TIDMAD deep-equal
- [ ] `denoising_score`/`file_vector`/`score_table` names and semantics unchanged
- [ ] the metric types carry no loss field, and the negative test reds if one is added
- [ ] Deliverable-Contract ownership is CONFIRMED or DEFERRED-with-reason in the ledger (OD-20-7)
- [ ] no new top-level config hierarchy; model/loss/train/tuner/profile configs untouched
- [ ] no new independent state store; no new argv (or an honestly downgraded Stage-A claim)
- [ ] the enumerated list of direction consumers this step does NOT reach is recorded (D1)

## 13. Gate disposition (PROVISIONAL, from the current standard)

| Gate | Disposition | Reason |
|---|---|---|
| Gate 1 | **NOT REQUIRED** | Step 06 changes no prompt and no `LLMBridge` kwarg (§8). Flip: if any prompt byte changes |
| Gate 2 | **REQUIRED — bounded** (recommendation; §16-Q5) | the tuner's live scoring route changes call path; a real attempt that trains, infers, writes, **scores through the handle** and cleans is the only evidence that failure class "wrong scalar on the real path" cannot survive. Bounded exactly as 05c's C8 (one attempt, pro config, ~10 min). Counter-argument, recorded: if Checkpoint C's real-subprocess scoring plus the two-route oracle are judged sufficient, Gate 2 could be re-dispositioned to NOT REQUIRED — the operator decides at freeze |

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

**PR decomposition — ONE PR (recommendation).** The interface, the
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

## 16. Open decisions / operator decisions (before freeze)

| # | Question | Blocks freeze? | Recommendation |
|---|---|---|---|
| Q1 | **Confirm** final-evaluation-side ownership of the Deliverable Contract's semantic identity (§4), or **defer** with the missing consumer evidence named? | **YES** | Confirm — the scorer reads the deliverable's interior (§1.2) |
| Q2 | Metric declaration form for non-TIDMAD tasks: derived-only in Step 06 (regime A) with the declared additive block deferred to Step 12, or an additive block in `task_config.yaml` now? | **YES** | derived-only now; declared block lands with the first composed contrast task (Step 12), consistent with §0 rule 8 |
| Q3 | Scoreability contract shape: which interior facts (channel addressing, dtype/offset, the two attrs, completeness) does it *own* vs. *reference from* `DeliverableSpec`? | no (design detail) | own scoreability; reference producer facts |
| Q4 | Any TIDMAD *secondary* metric instance in Step 06? | no | none — no consumer |
| Q5 | Gate 2 REQUIRED-bounded vs NOT REQUIRED given Checkpoint C | no | REQUIRED-bounded |
| Q6 | Which direction consumers does Step 06 *reach*? Recommendation: the tuner's live scoring route + record payload only; workflow `:2740`, resume `:438`, `per_file_best._row_beats`, dashboard remain enumerated D1 debt | no | as recommended |

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

## 18. Definition of Done (for the future freeze — not yet applicable)

Step 06 is DONE when: the ONE PR is merged with Checkpoints 0/A/B/C(/D) and
its Gate disposition satisfied at the exact head; every §12 criterion is
`[x]` with recorded evidence; the Deliverable-Contract review verdict is
recorded (confirm, or defer-with-reason); the D1 not-reached consumer list is
enumerated; roadmap §15.1 row and README mirror synchronized post-merge; and
Step 07a can bind the metric handle for policy without touching scoring.

**Until then: NOT FROZEN. NOT IMPLEMENTED.**
