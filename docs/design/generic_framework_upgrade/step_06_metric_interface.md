# Step 06 — Metric interface — detailed design (FROZEN)

Roadmap §15 step 6, module §10. Roadmap row §15.1 `§10 Metric interface`.
Post-Step-05 addendum: roadmap **§20** (the semantic authority for the two
obligations this step inherits beyond §10).

| Field | Value |
|---|---|
| Status | **STEP 06 DESIGN — FROZEN. OPERATOR APPROVED FOR IMPLEMENTATION (2026-08-15). NOT IMPLEMENTED.** Implementation is authorized under a separately filled Implementation Working Rules contract; the design freeze does not itself begin implementation. §16's Q1-Q6 are all resolved (Q1 CONFIRMED · Q2 DECIDED · Q3 FROZEN · Q4-Q6 ACCEPTED). §19 (C0-C8, all `[ ]`) remains the implementation plan and §20 the empty ledger; §18 remains the eventual Definition of Done — **freeze ≠ done**. Revision history: rev 4 per-commit checklists after seam inspection; rev 3 ownership wording, scoreability scope, Gate 2 source-grounded NOT REQUIRED, two-route parity as compatibility; rev 2 scalar-mandatory semantics, executable scoreability, DeliverableSpec/ScoreabilityContract split, 06/12 declaration split; rev 1 initial draft. |
| Design base | master `75525dc9` (Step 05 COMPLETE: 05a `cfb3b1c7`, 05b `5ce205d3`, 05c `03e00944`; finalizer `75525dc9`) |
| Depends on | Step 02 (`DatasetProfile`) · Step 03 (`ModelIOContract`) · Step 05c (`DeliverableSpec`, provisional) · roadmap §10, §14, §16, §20 |
| Owns | the **EvaluationMetric** interface; the **evaluation-vs-training-diagnostics boundary** (by exclusion); the **Deliverable-Contract confirm-or-say-why review** |
| Does NOT own | `TrainingHistory` / `TrainingDiagnosis` (Step 07, §20.2) · incumbent/threshold/skip-bypass policy (Step 07a) · HealthGate semantics (Step 08) · Interpreter consumption (Step 09) · the executable data path (D14, §20.5) · the two composed contrast tasks (Step 12 / M1, §20.3) |
| Risk | Medium-high: it touches the frozen scientific formula's *call path* (never its arithmetic) and the record payload every downstream reader keys on |
| Remaining operator decisions | **§16 — six, listed.** None blocks review; **three block freeze** (Q1 ownership, Q2 declaration form, Q3 scoreability semantics) |

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
- [ ] Re-read `score_vector` `:490-610` and `denoising_score_single.py:150-227`
      and record how each route obtains `sample_set`, `anchor_map`, `s_max`,
      `denoised_filename_fn`, `profile`.
- [ ] Build one deterministic synthetic deliverable (small, both channels,
      known sample values) with the real writer, under a small bound profile
      so the run is seconds — the 05c Checkpoint-C fixture geometry
      (`psd_segment_length` 4,096) is the precedent.
- [ ] Capture route (i): `TidmadSandbox.score_vector(...)` on it → record the
      exact **existing TIDMAD result and its key/output shape** (today a
      scalar and a `file_vector`) as **hardcoded literals**.
- [ ] Capture route (ii): drive `execute_scoring` → `denoising_score_single.py`
      as a **real subprocess** on the same deliverable; record the
      `--output_json` keys and values as hardcoded literals.
- [ ] Assert route (i) == route (ii) on scalar and per-file values (exact
      float equality — same arithmetic, same inputs; if they differ, that is
      a **finding**, recorded before anything is built).
- [ ] Capture the `per_file_best` identity key set as it stands
      (`test_per_file_best.py:719` already pins it — reference, do not
      duplicate).
- [ ] Capture the pseudo path: `StubSandbox.score_vector` return shape
      (2-tuple, length-9 vector) as a hardcoded expectation.
- [ ] Record every captured value in §20.

**4. Validation plan.**
- *Unit*: every new capture passes against unmodified production code.
- *Integration/pseudo*: the route-(ii) capture IS a real subprocess.
- *Negative*: none at C0 (captures only).
- *Backward-compat*: this commit **is** the parity instrument.
- *Gate*: none.

**5. Acceptance criteria.**
- [ ] `git status --porcelain` lists **no production file** in this commit.
- [ ] Captured values are hardcoded literals, never re-derived by calling
      the code under test.
- [ ] Route (i) and route (ii) results are asserted **equal to each other**
      and each equal to its literal.
- [ ] The oracle is worded as "the existing TIDMAD result and shape", not as
      `(file_vector, scalar)` (revision 3, §11).
- [ ] Each capture is traceable to the production site it guards, by
      `file:line`.

**6. Failure and edge cases.**
- Routes disagree at C0 → **record as a pre-existing finding**; do not fix
  in C0; the design's parity claim is then "each route unchanged", not
  "routes equal", until diagnosed. Surface to the operator.
- The subprocess route needs `--anchor_map` / real anchor JSON → use the
  committed anchor goldens; if the fixture cannot satisfy it without real
  data, record the substitution and move that capture to Checkpoint C.

**7. Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools/<c0 module> tests/unit/core/<c0 module> -q`
      *(narrow at implementation time)*
- [ ] Record: test count, wall time, and explicit confirmation that zero
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
- [ ] Re-read `deliverable_spec.py` and mirror its shape: frozen Pydantic
      models, one derivation function, defaults that yield the TIDMAD
      instance with no input.
- [ ] Define `MetricSpec` (id · direction · aggregation id · transform +
      params · references · scoreability) and `MetricResult` (metric_id ·
      direction · scalar · optional evidence · references_used) — names
      provisional.
- [ ] Define `ScoreabilityContract` with an executable
      `validate(deliverable_path, ...) -> ok | structured failure` and NO
      universal completeness/channel/shape schema (§5 scope bound): TIDMAD's
      predicate is TIDMAD's instance, declared against `DeliverableSpec`.
- [ ] Provide the TIDMAD derivation (`derive_tidmad_metric_spec(profile,
      deliverable_spec)` or equivalent) — the aggregation is a *reference*
      to the frozen `score_vector`, never a re-implementation.
- [ ] Confirm by scan that no production module imports it (05c's
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
- [ ] A **scalar-only** `MetricSpec`/`MetricResult` is constructible
      (evidence optional — §4).
- [ ] The TIDMAD instance derives with no declaration and matches the C0
      identity literals.
- [ ] `validate` on the C0 deliverable → ok; on each invalid variant → the
      structured failure names the violated requirement.
- [ ] Zero production importers (asserted).
- [ ] No file under `configs/` changed; no existing schema gained a field.
- [ ] No field on any metric type can hold a loss (negative test reds if one
      is added).

**6. Failure and edge cases.**
- A required scoreability fact is not derivable from `DeliverableSpec` +
  profile → **MATERIAL STOP** (would need a declaration Step 06 does not
  own).
- Two scoring routes need different scoreability inputs → they must resolve
  the **same** predicate; a per-route predicate is two authorities.

**7. Verification commands and evidence.**
- [ ] targeted selector for the new module + the C0 captures.
- [ ] Record counts, wall time, the zero-importer confirmation.

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
- [ ] Re-read `:5300-5340` (call site + `_denoised_fn`) and `:1858-1897`
      and record exactly what crosses today.
- [ ] Bind `run_metric` at run scope from the run profile + run deliverable
      spec — one acquisition point.
- [ ] Route the live call through the handle: scoreability `validate` on the
      deliverable set → on failure, a **structured not-scoreable result**
      reaches the round-outcome path (record which existing status/failure
      field carries it — inspect `_decide_round_outcome` `:366-388` before
      choosing; do not invent a new status if an existing one is honest).
- [ ] On success, delegate to `scoring_utils.score_vector` unchanged.
- [ ] Keep `StubSandbox` returning its 2-tuple.

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
- [ ] The tuner's live scoring call resolves through `run_metric` — asserted
      by reachability (a renamed/contrast handle changes the observed
      behaviour), not by inspection alone.
- [ ] Route (i) result equals the C0 literal exactly.
- [ ] Scoreability failure short-circuits scoring with a structured result;
      `score_vector` is not reached.
- [ ] `StubSandbox.score_vector` return is unchanged (C0 pseudo capture).
- [ ] `scoring_utils.score_vector` diff is **empty**.
- [ ] Legacy callers of `TidmadSandbox.score_vector` are unaffected.

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
- [ ] `.venv/bin/python -m pytest tests/unit/agent/tune_ml_hyperparam_agent tests/unit/core -q` *(narrow)*
- [ ] Record counts, wall time, the route-(i) equality, the short-circuit
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
- [ ] Re-read `denoising_score_single.py` argv + main flow; confirm the
      profile is loaded fail-closed (`:151-155`).
- [ ] Derive the metric spec in the child from `dataset_profile` (+ the
      derived deliverable spec) — one derivation, two callers.
- [ ] Validate scoreability before `score_vector`; on failure write a
      **structured** not-scoreable payload to `--output_json` and exit with a
      status the parent's existing handler classifies honestly (inspect
      `:1961-1971`).
- [ ] Assert no ambient second resolution in the child when a profile path
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
- [ ] `execute_scoring` argv identical (ordered) to the pre-C3 capture.
- [ ] Route (ii) == route (i) == the C0 literal.
- [ ] Exactly one `derive_*_metric_spec` call in the child; exactly one
      `resolve_dataset_profile()` (the pre-existing legacy adapter) — no
      second.
- [ ] Structured not-scoreable output on the negative fixture.

**6. Failure and edge cases.**
- Child cannot derive a required scoreability fact from the transported
  profile → same MATERIAL STOP as C1 (transport insufficiency; not an argv
  problem to solve here).
- Parent's error classifier maps the new structured failure to `"error"` →
  record; do not invent a new status in this step.

**7. Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools tests/unit/core -q` *(narrow)*; the real-subprocess test under `tests/integration/execute_tools/`.
- [ ] Record counts, wall time, the two-route equality.

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
- [ ] Re-read `:5768-5800` and the schema; add the optional field(s).
- [ ] Populate from the C2 handle result on the success path; leave `None`
      on failure paths (and on the pseudo path unless the stub supplies it —
      inspect).
- [ ] Confirm `save_record` / `coerce_nonfinite_to_none` need no change.

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
- [ ] `denoising_score`, `file_vector`, `score_table` names and semantics
      unchanged; `git diff` shows only additions to the schema.
- [ ] Historical artifacts validate unchanged (count recorded).
- [ ] The additive field is populated on the live path and `None`
      elsewhere.

**6. Failure and edge cases.**
- Pseudo path (`StubSandbox`) does not carry identity → `None` is honest;
  do not fabricate.
- A record with `denoising_score` but no `MetricResult` (pre-C4 record) is
  valid — additive optional.

**7. Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/agent tests/unit/core -q` *(narrow)*.
- [ ] Record counts, wall time, the historical-artifact count validated.

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
- [ ] Boundary negative: constructing a metric whose identity is a loss, or
      populating `MetricResult` from `loss_history`, is rejected.
- [ ] Structural guard over the **owned** consumers (the tuner's live
      scoring path, `TidmadSandbox.score_vector`, `denoising_score_single.py`,
      the metric module): no executed hardcoded direction; the
      `tidmad_denoising_score` literal appears in exactly one executed
      constant (05c "declared exactly once" pattern, AST over executed
      constants, docstrings excluded).
- [ ] Record the **not-reached** direction consumers as an explicit list
      (D1) — a test that asserts they still contain their literal, so the
      list cannot silently drift (05c out-of-rung pattern).

**4. Validation plan.** *Unit*: the above. *Negative*: the guards red on a
re-inlined direction / a second `metric_id` declaration (proved at C7 by
mutation). *Gate*: none.

**5. Acceptance criteria.**
- [ ] Loss-shaped metric rejected; `loss_history` → `MetricResult` rejected.
- [ ] Owned surfaces: zero executed hardcoded direction; `metric_id` declared
      once.
- [ ] The D1 not-reached list is asserted, not merely written.

**6. Failure and edge cases.** A guard finds a direction literal in an
owned surface that C2/C3 missed → same-authority missed site → migrate in
this commit and record (05c precedent), unless it is scorer arithmetic
(then flip candidate — record, stop).

**7. Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools tests/unit/core -q` *(narrow)*.
- [ ] Record counts, wall time.

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
- [ ] Construct a scalar-only, `direction="lower"` `MetricSpec` in-process
      (regime A instance stays TIDMAD; the contrast is injected at the seam,
      exactly as 05c's renamed naming was).
- [ ] Drive the live route with it on stub outputs; assert the record's
      additive payload carries `direction="lower"` and the contrast identity,
      and that TIDMAD's identity/direction are untouched in the same process.
- [ ] Negative: the rung does not fire on the shipped instance.

**4. Validation plan.** *Unit*: the rung. *Negative*: shipped instance
unchanged. *Gate*: none.

**5. Acceptance criteria.**
- [ ] A scalar-only lower-is-better metric enters the record through the
      handle with explicit `direction="lower"`.
- [ ] TIDMAD identity/direction unchanged in the same run.
- [ ] Nothing else varied (one axis).

**6. Failure and edge cases.** The rung passes only because a seam returns
the contrast value unconditionally → the negative catches it.

**7. Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools tests/unit/core -q` *(narrow)*.
- [ ] Record counts, wall time.

**8. Commit boundary.** Evidence only.

---

### C7 — mutations per semantic family + Checkpoint C (real subprocess)

**1. Goal.** Prove each semantic family is load-bearing and cross the real
subprocess boundary with the finished seam.

**2. Scope.** Tests + a scratch mutation runner (05c pattern; not committed
into the tree unless it already has a home). **Non-goals**: no production
change. Depends on: C6.

**3. Implementation plan.**
- [ ] Mutation families (count NOT frozen; add finer ones only where they
      supply unique evidence): identity swap · direction flip · aggregation
      substitution · **scoreability bypass** (validate skipped → arithmetic
      reached on an invalid artifact) · route divergence (in-process vs
      subprocess) · declared-once (a second `metric_id` literal).
- [ ] Hygiene: assert each mutation's site count == 1 before applying; clear
      `__pycache__`; restore from clean source; re-verify green.
- [ ] Checkpoint C: a **real** `execute_scoring` subprocess scores a real
      small deliverable through the handle; result equals the in-process
      route; the scoreability negative also runs through the real subprocess.
      Helper-only is insufficient (05c §6 discipline; reuse
      `test_step05c_checkpoint_c_deliverable_boundary.py`'s harness).
- [ ] Classify any survivor (real gap / equivalent / unreachable / wrong
      fixture) **before** strengthening an oracle.

**4. Validation plan.** *Unit*: mutations. *Integration*: Checkpoint C. *Gate*:
NOT REQUIRED (§13) — listed separately, not launched.

**5. Acceptance criteria.**
- [ ] Every family reds; each failure names the family.
- [ ] Zero survivors, or each survivor classified and recorded.
- [ ] Checkpoint C: real subprocess result == in-process == C0 literal; the
      structured not-scoreable result observed through the real subprocess.
- [ ] Tree restored green after every mutation.

**6. Failure and edge cases.** A survivor → inspect test architecture first.
Real subprocess needs anchors → the committed goldens; if real data is
genuinely required, record and route that assertion to a (discretionary,
operator-elected) Gate 2 rather than pretending coverage.

**7. Verification commands and evidence.**
- [ ] mutation runner log; `.venv/bin/python -m pytest tests/integration/execute_tools/<checkpoint c module> -q`.
- [ ] Record each mutation's expected vs observed, and the restored-green
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
- [ ] Synchronize §20 with actual findings, deviations, evidence.
- [ ] Record the OD-20-7 verdict in the ledger — resolved at freeze as CONFIRMED
      (§16-Q1).
- [ ] Update touched docs as the last pre-merge step, quoting each documented
      behaviour against merged source (CLAUDE.md doc-sync rule).
- [ ] Terminal checks from a **clean tree**: directly affected unit
      subsystems · Checkpoint C · `ruff check` · `ruff format --check` ·
      exact-head CI (strict pyright is CI's — record the local-node
      limitation if it recurs).
- [ ] Open/update ONE PR; drive exact-final-head CI green; verify local HEAD
      == PR `headRefOid` == successful CI `headSha`.

**4. Validation plan.** As listed. **No local full suite by default.**

**5. Acceptance criteria.**
- [ ] Every verdict read from the log file, never a wrapper's exit status.
- [ ] Three-way SHA identity read, not reconstructed.
- [ ] Working tree clean; §20 records every deviation; the D1 not-reached
      list is enumerated.

**6. Failure and edge cases.** The PR3-L2 preflight guard reds on a dirty
tree → commit the checkpoint first; never relax it. CI env-only failures →
diagnose, fix, not a stop.

**7. Verification commands and evidence.**
- [ ] the terminal command set with counts and wall time; CI run id and
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

*(empty — populated at implementation kickoff; the freeze does not begin
implementation)*
