# Step 06 — Metric interface — detailed design (DRAFT)

Roadmap §15 step 6, module §10. Roadmap row §15.1 `§10 Metric interface`.
Post-Step-05 addendum: roadmap **§20** (the semantic authority for the two
obligations this step inherits beyond §10).

| Field | Value |
|---|---|
| Status | **DRAFT — READY FOR OPERATOR REVIEW. NOT FROZEN. NOT IMPLEMENTED.** Revision 3 (2026-08-15, operator review of revision 2): Q1 ownership wording sharpened to the 05c-representation / 06-acceptance split (§4, §16); scoreability's SEMANTIC SCOPE bounded — execution semantics frozen, no universal completeness/channel/shape schema (§4, §16-Q3); **Gate 2 re-dispositioned to NOT REQUIRED on the standard's own assignment table and roadmap §17's metric-handle rule, quoted** (§13); the two-route parity re-positioned as a compatibility obligation, not a generic-metric requirement (§1.1, §11); Checkpoint-0 oracle wording generalized (§11). Revision 2 (operator review of revision 1): scalar-mandatory / per-sample-evidence-optional metric semantics (§4); scoreability made an EXECUTABLE behaviour and a DoD item (§4, §12); `DeliverableSpec` vs `ScoreabilityContract` ownership sharpened (§4); the Step-06 runtime-interface vs Step-12 task-declaration split made explicit (§5, §16-Q2); Q3 now blocks freeze on semantics. Implementation is NOT authorized by this document. |
| Design base | master `75525dc9` (Step 05 COMPLETE: 05a `cfb3b1c7`, 05b `5ce205d3`, 05c `03e00944`; finalizer `75525dc9`) |
| Depends on | Step 02 (`DatasetProfile`) · Step 03 (`ModelIOContract`) · Step 05c (`DeliverableSpec`, provisional) · roadmap §10, §14, §16, §20 |
| Owns | the **EvaluationMetric** interface; the **evaluation-vs-training-diagnostics boundary** (by exclusion); the **Deliverable-Contract confirm-or-say-why review** |
| Does NOT own | `TrainingHistory` / `TrainingDiagnosis` (Step 07, §20.2) · incumbent/threshold/skip-bypass policy (Step 07a) · HealthGate semantics (Step 08) · Interpreter consumption (Step 09) · the executable data path (D14, §20.5) · the two composed contrast tasks (Step 12 / M1, §20.3) |
| Risk | Medium-high: it touches the frozen scientific formula's *call path* (never its arithmetic) and the record payload every downstream reader keys on |
| Remaining operator decisions | **§16 — six, listed.** None blocks review; **three block freeze** (Q1 ownership, Q2 declaration form, Q3 scoreability semantics) |

---

## 0. Scope / capability

**Observable final capability (PROVISIONAL wording, to be frozen):**

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

**What an EvaluationMetric IS (PROVISIONAL definition, to freeze):**

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

**Semantic components — DECIDED as the component list, PROVISIONAL as to
field names:**

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
PROVISIONAL RECOMMENDATION (wording sharpened at revision 3 so it cannot be
read as "the metric owns deliverable semantics"): **CONFIRM that Step 06
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
still missing.

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

- [ ] a task can declare ONE primary metric; secondary metrics are optional
- [ ] identity, direction and aggregation are explicit and machine-readable on every record
- [ ] PRODUCTION SCORING (the tuner's live route) invokes the frozen TIDMAD instance THROUGH the handle
- [ ] the two scoring routes produce equal `(file_vector, scalar)` for the same deliverable
- [ ] the frozen TIDMAD values are byte-identical; `_LOG_BASE`/`s_max`/formula untouched
- [ ] historical records/outputs validate unchanged; regime A resolves TIDMAD deep-equal
- [ ] `denoising_score`/`file_vector`/`score_table` names and semantics unchanged
- [ ] the metric types carry no loss field, and the negative test reds if one is added
- [ ] **the metric's scoreability contract is EXECUTABLE and is evaluated BEFORE metric arithmetic on both scoring routes; an invalid deliverable produces a structured not-scoreable result rather than an incidental scorer exception** (revision 2)
- [ ] `_is_complete_trial_output` is unchanged and is NOT the scoreability mechanism (roadmap :1052-1058)
- [ ] a scalar-only metric instance (no per-sample evidence) is constructible and enters the record through the handle (revision 2)
- [ ] Deliverable-Contract ownership is CONFIRMED or DEFERRED-with-reason in the ledger (OD-20-7), under the `DeliverableSpec` (representation) / `ScoreabilityContract` (acceptance) split
- [ ] no new top-level config hierarchy; model/loss/train/tuner/profile configs untouched
- [ ] no new independent state store; no new argv (or an honestly downgraded Stage-A claim)
- [ ] the enumerated list of direction consumers this step does NOT reach is recorded (D1)

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
(§11). The operator may still elect a bounded Gate 2 at freeze (§16-Q5); this
section records that the standard does **not** require it, so electing one is
a discretionary cost, not a compliance need.

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
| Q1 | **Confirm** that Step 06 owns the evaluation-side ACCEPTANCE contract and the deliverable facts required for scoreability, while Step 05c retains EXCLUSIVE ownership of producer-side representation semantics (§4) — or **defer** with the missing consumer evidence named? | **YES** | Confirm — the scorer reads the deliverable's interior (§1.2); the metric references `DeliverableSpec`, never redefines it |
| Q2 | Metric declaration form for non-TIDMAD tasks: derived-only in Step 06 (regime A) with the declared additive block deferred to Step 12, or an additive block in `task_config.yaml` now? | **YES** | derived-only now; declared block lands with the first composed contrast task (Step 12), consistent with §0 rule 8. *(Roadmap §20.3 records the 06-runtime-interface / 12-declaration split as DECIDED; what remains for freeze is confirming no `task_config.yaml` edit in Step 06.)* |
| Q3 | Scoreability contract **semantics**: EXECUTION semantics frozen (executable before arithmetic; structured failure; reuse guard not the mechanism) — **and its SCOPE bounded: NO universal task-independent schema for completeness / channels / shape; requirements are per-metric-instance, declared against `DeliverableSpec`** (§5, revision 3). | **YES — on semantics and scope.** Exact field names remain implementation detail. | freeze the execution semantics and the scope bound as stated in §5; leave field names to the implementation ledger |
| Q4 | Any TIDMAD *secondary* metric instance in Step 06? | no | none — no consumer |
| Q5 | Gate 2: the standard and roadmap §17 say NOT REQUIRED (§13, quoted). Does the operator nonetheless ELECT a bounded Gate 2 as discretionary evidence? | no | **NOT REQUIRED per the authorities**; electing one is the operator's discretionary call, not a compliance need |
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
`[x]` with recorded evidence — **including that scoreability is an executed
behaviour on both routes, not a documented intention**; the Deliverable-Contract review verdict is
recorded (confirm, or defer-with-reason); the D1 not-reached consumer list is
enumerated; roadmap §15.1 row and README mirror synchronized post-merge; and
Step 07a can bind the metric handle for policy without touching scoring.

**Until then: NOT FROZEN. NOT IMPLEMENTED.**
