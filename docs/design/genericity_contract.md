# SIDERIUS Genericity Contract

**Status**: living contract — created 2026-07-28 (V19 PR 2, commit A).
**Authority**: this document defines the generic seams ONCE. Every in-passing
refactor converges to the seams named here. Inventing a new abstraction
requires updating this document FIRST (baseline rule,
`docs/design/v19_priorities.md` §1.3 guardrail 1).

## Why this exists

SIDERIUS is being reshaped from a TIDMAD-only repository into a generic
dataset/task/metric framework (operator decision 2026-07-27). The mechanism is
**gradual, in-passing refactoring, never a big-bang**: when a PR touches a
module, that PR also moves the touched module toward the seams below, in its
own commit.

Without a single written target, incremental refactors produce divergent
half-generic layers. That is what this file prevents.

Progress against the seams is tracked in
`docs/design/tidmad_coupling_ledger.md`.

---

## Seam 1 — Indexed dataset

**Status: partially implemented** (training filename template landed in V19
PR 2 commit A).

A dataset is an indexed collection of files, each holding a fixed number of
segments. The contract is:

```text
file_index -> (readable path, segment list)
```

resolved through `DatasetConfig` (`execute_tools/dataset_config.py`), never
through a filename literal inlined at the call site.

Implemented today:

| Concern | Contract surface |
|---|---|
| Physical constants | `DatasetConfig.psd_segment_length`, `.segments_per_file`, `.num_files`, `.sampling_frequency` |
| Training filename | `DatasetConfig.training_file_name(file_index)` — the ONLY place a training filename is built |
| Filename patterns | `DatasetConfig.training_file_pattern` / `.validation_file_pattern`, validated at construction (see below) |
| Which files a run may touch | `DataScope` (+ `resolve(dataset)`) |
| Which segments are in play | `SampleSet` = `{file_index: [segment_indices]}`, built by `execute_tools/sample_set_builder.py`, boundary-validated by `validate_sample_set` |

**Pattern validation is part of the contract.** `str.format()` does NOT raise
when a replacement field is absent, so a pattern like `training_file.h5` would
map every file index to the SAME file and corrupt an entire run with no error
raised anywhere. `DatasetConfig` therefore validates at construction that each
pattern (a) contains a usable `file_index` replacement field and (b) actually
formats with an integer index. A dataset whose pattern cannot distinguish
files is rejected before any file is opened.

**Not yet generic**: the training engine still reads the module-level `TIDMAD`
singleton. Commit A moved the *template* behind the config seam, not the
*choice of dataset*. Injecting the dataset instance is a later step on the
ladder; the coupling ledger tracks it.

**Porting target**: adding a second indexed dataset should be a
`configs/task_config.yaml`-level change (the already-declared porting entry
point), not a grep-and-replace across Python sources.

---

## Seam 2 — Configuration: proposed / override / resolved

**Status: first implementation in V19 PR 2 (ordering).**

Governing principle (operator, 2026-07-28):

> Configurable options may have a proposed value, an operator override, and a
> resolved execution value. Only the resolved value defines what ran. Every
> override must remain visible in provenance and downstream interpretation.

Concretely, for any option that adopts this pattern:

```text
default
  -> agent proposal      (intent; from the LLM plan, typed and validated)
  -> operator override   (control; chain-level, stable for the chain)
  -> resolved value      (fact; the ONLY thing execution consumes)

precedence: operator override > agent proposal > default
```

Rules that come with the pattern:

1. **One resolver per option.** Precedence is implemented exactly once.
   Workflow, node, and execution layers consume the resolver's output; they
   never re-derive precedence.
2. **Execution consumes resolved values only.** The execution layer does not
   know how a value was resolved.
3. **Provenance records all three levels** plus the resolution source, so a
   reviewer can reconstruct "agent proposed X, operator overrode with Y,
   executed Z, source S" from the record alone.
4. **Attribution uses resolved values.** Downstream interpretation and any
   feedback path must describe the resolved value as what ran. An overridden
   proposal is never reported as executed.
5. **Structural validity is checked at every intake**, even for a value that
   an override will discard — malformed agent output must not be silently
   masked. Checks that depend on resolution (e.g. against a resolved
   `DataScope`) apply to the resolved value.
6. **Chain locking applies to the override, not the resolution.** The operator
   override is chain control policy and is pinned in the run-invariants lock;
   the resolved value may legitimately vary per round when no override is
   active.

Reference implementation: data ordering
(`docs/design/v19_priorities/pr2_data_ordering.md` §3.6–§3.8).

### Permissions taxonomy

Adopting this pattern does NOT make an option agent-settable. Each option
declares its permissions explicitly:

| Class | Meaning |
|---|---|
| `agent-settable` | The agent may propose a value. |
| `operator-overridable` | An operator may force a value for a chain. |
| `chain-locked` | The controlling value is pinned in the run-invariants lock; changing it mid-chain is a violation. |
| `frozen` | Not configurable by agent or operator. Changing it requires a design decision and a written justification. |

Safety limits (resource budgets, watchdog policy) and the frozen scoring rules
do **not** become agent-settable merely because ordering is. The migration
inventory in the coupling ledger records the expected class for each candidate
option; the class is confirmed by the PR that migrates it.

---

## Seam 3 — Task pack

**Status: PLACEHOLDER** — partially anticipated by `configs/task_config.yaml`
(`task_description`, `forward_contract`), which is already injected into agent
system prompts. TIDMAD-worded prose still exists in node prompt modules (see
ledger).

To be defined by the first PR that genuinely needs a second task. Expected
scope: task description, forward contract, and task-specific prompt fragments
travelling as one pluggable unit rather than as literals spread across nodes.

**Do not invent this seam ad hoc** — update this section first.

### Recorded gaps — TIDMAD prose that stays literal, and why (Step 07 PR 07b)

07b rendered every planner/reflector token whose fact a landed authority owns.
The list below is what it deliberately did NOT render, recorded here rather
than papered over with an invented `task_config` field. Each is a Seam-3 (or
Step-08) gap, not an oversight:

| Literal | Why no authority owns it |
|---|---|
| the five per-model roster one-liners (`PLANNER_PROMPT`) | the model NAMES come from `MODEL_REGISTRY` and are rendered; the descriptions are prose no registry declares |
| the CH1/CH2 + log-space explanation | `MetricSpec` owns id, direction, aggregation, transform and references — not prose about them |
| the regressor `[B, T]` / HYBRID sentences | the CLASSIFIER shape renders from the run-bound `ModelIOContract`; the other two describe contracts the run has not bound |
| the built-in loss list at `PLANNER_PROMPT` | owned by `LossConfig.loss_type` and renderable — but the shipped literal WRAPS MID-LIST, so a single-token render would move an LLM-visible byte that P2 is not allowed to move |
| the per-semantic loss subsets in the force-model branch | their literal order differs from the `Literal`'s declaration order |
| the "200 segments" / "20× less data" illustrations | the FULL-SCOPE number renders from the profile; 200 is an example portion no default declares |
| the reflector's "200 vs 4000" anchor | the frozen bridge contract gives `reflect()` no task-render transport, and widening it is out of 07b's scope |
| class-127 mode collapse and PSD-amplitude wording | the check NAMES render from the effective health config; what the checks MEAN is TIDMAD health semantics — **Step 08** |

A future task pack supplies these; until then they are TIDMAD-rendered from
their current owner, and the contrast rung asserts only the tokens that ARE
rendered.

---

## Seam 4 — Metric

**Status: DEFINED and LANDED — Step 06 (PR #213, merged `02f382eb`, 2026-08-15).**
`execute_tools/evaluation_metric.py`: `MetricSpec` (id · direction · aggregation
· transform · references · EXECUTABLE `ScoreabilityContract`), the
`EvaluationMetric` handle (scoreability BEFORE arithmetic), `MetricResult` /
`NotScoreableResult`; the frozen TIDMAD scorer is instance #1 derived under
Regime A (`derive_tidmad_metric`) and both production scoring routes go
through the handle. Contract test evidence: the strict direction-only rung
(C6a) and the broader different-metric rung (C6b) in
`tests/unit/execute_tools/test_step06_c6_stage_b_direction_rung.py`. 

**Step 07 PR 07b LANDED the tuner's direction consumers.**
`execute_tools/metric_order.py::MetricOrder` is now the ONE place
`MetricSpec.direction` is interpreted: it is constructed once per run from the
bound handle, and all 21 golden-metric ordering expressions the Step-07 census
found in the tuner ask it — trial winner, skip/bypass orientation and their
disabled sentinels, the bootstrap sentinel, the planner's score-table
incumbent, the reflector's best/worst/rank/new-best/efficiency band, and the
five `best_*` finalization tracks. The same-loss `final_loss` rank deliberately
does NOT (a loss is lower-is-better by definition), and a test pins that it does
not move when the metric direction flips. Scale-sensitive rules are classified
per rule rather than sign-flipped, and the one with no honest generic reading
(`degenerate_penalty_score` under a minimised metric) FAILS CLOSED at startup.
The planner/reflector prompts render task content, direction wording, metric
identity and compact `TrainingDiagnosis` lines from landed authorities.
Structural guard: `tests/unit/execute_tools/test_step06_c5_boundary_and_structure.py`
allows an executed direction literal in exactly TWO modules — the metric module
DECLARES the vocabulary, the order module INTERPRETS it — and pins each one's
literals as an exact multiset.

Not yet generic (owned later): the PERIPHERAL direction consumers
(`workflows/model_exploration.py`, `core/resume.py`,
`execute_tools/per_file_best.py`, `core/campaign_artifacts.py`, the dashboard)
— **Steps 09 / 10 / M2**, and they may import `MetricOrder` when they migrate;
task-level metric declaration (Step 12); the lexical loss-id rule (temporary
debt — roadmap §20.8). Design: `docs/design/generic_framework_upgrade/step_06_metric_interface.md`.
The hard constraint below still holds.

**Frozen exception (baseline §1.3 guardrail 4)**: the TIDMAD score formula is
frozen and stays byte-identical, because published-paper comparability depends
on it. Metric pluggability means new metrics plug in **beside** it; it is
never rewritten. This applies to the `log_{5.27}` convention, the global
`s_max` ruler, and the grand-mean aggregation.

*(Historical expectation, superseded by Step 06: "to be defined by the first PR
that adds a second metric — name, per-file vector, scalar aggregate,
comparability rules". The landed interface makes the per-sample vector OPTIONAL
— a scalar-only metric is a first-class instance — and adds the executable
scoreability contract.)*

**Do not invent this seam ad hoc** — update this section first.

---

## Seam 5 — Training observation (History ≠ Diagnosis)

**Status: DEFINED — Step 07 PR 07a (written BEFORE the implementation, as
this contract requires; landed with 07a C1/C3).** Design:
`docs/design/generic_framework_upgrade/step_07_tuner_policy_and_training_diagnostics/pr_07a_training_history_diagnosis.md`
(§3.2–§3.9); semantics frozen by the roadmap §22.1–§22.8 and the Step-07
parent §8.2.

A training run produces **observations** of the run-resolved training
objective; a **diagnosis** is a pure, deterministic derivation from those
observations. The seam separates the two so that a new task changes WHAT is
observed, never HOW the framework records or derives.

```text
R1  the run-resolved training objective   (LossConfig → criterion; a loss family is a run choice,
                                           NOT task semantics; identified by objective_kind +
                                           objective_config_fingerprint — a configuration fingerprint,
                                           not a hash of plugin code)
R2  per-epoch TRAINING observation of R1  (= legacy loss_history; unchanged)
R3  per-epoch VALIDATION observation of the SAME resolved computation on the run-bound validation
    scope (the tuner's EXISTING eval SampleSet — no second split concept), no backprop, no optimizer
    step, transactional (model / optimizer / objective state and every RNG restored)
R4  optional checkpointed observations   (`observations: {name: [per-epoch]}` — the slot exists;
                                           producers land with task declarations, D14 / Step 12)
```

| Concern | Contract surface (generic) | TIDMAD-shaped today |
|---|---|---|
| The observation payload | `execute_tools/training_history.py::TrainingHistory` — cadence `per_epoch`, `objective_kind`, `objective_config_fingerprint`, `objective_reduction`, `epoch_statistic` (R2 and R3 use ONE declared estimator: the sample-count-weighted mean of the criterion's batch scalar), `comparability` + reason (`established` only for the audited mean-normalized built-ins; `sum` / custom → `not_established`, recorded never assumed), `epochs_planned/completed`, `train_objective`, `validation_objective`, `validation_requested_samples == validation_samples > 0`, `validation_seconds`, `observations` | the producer is `execute_tools/train_engine_sandbox.py` reading TIDMAD-family HDF5 through the Dataset Profile (Seam 1); the validation family is `DatasetConfig.validation_file_name` |
| The producer→consumer contract | `interpret_training_results(raw, *, expected_validation)` — typed, fail-closed at the ONE validation site (the tuner boundary): schema-invalid history, R2 ≠ `loss_history`, `final_loss` ≠ last R2, or an EXPECTED R3 that is missing → `TrainingResultsContractError` → the existing `error_training` path. `absent` is honest ONLY when validation was not expected | the legacy single-file trainer (no validation scope) is the only "not expected" producer |
| Validation scope | the eval `SampleSet` (Seam 1) travels as ONE argv flag `--eval_sample_set_json`; the declared scope must materialize EXACTLY (`ValidationScopeError` on zero / partial) — validation does NOT inherit the training path's silent skip | scope validated by `validate_sample_set` against the run's `DataScope`, as the train set is |
| The derivation | `agent/schemas/training_diagnosis.py::derive_training_diagnosis(history) -> TrainingDiagnosis` — pure, deterministic, no I/O, no LLM, computed ONCE at the tuner boundary; factual / calibration-free fields only (state, best validation epoch, trends with the symmetric scale-free deadband `r(a,b)=|b−a|/max(|a|,|b|)`, degradation, gap gated on `comparability == established`); NO overfitting / plateau / converged / underfitting labels | none — the derivation is task-agnostic by construction (contract test: rung B-07a-1 over TIDMAD focal / Pets CE + accuracy / DAVIS MAE + PSNR fixtures) |
| Persistence vs visibility | `ExperimentRecord.training_history` / `.training_diagnosis` (additive) are persisted evidence; in 07a they are HIDDEN from BOTH LLM-facing renders (planner hidden-key set; reflector receives the legacy payload only). Rendering is 07b's; interpretation / condensation is Step 09's | — |
| Runtime accounting | validation batches are not optimizer steps; validation seconds are excluded from the training ACTUAL and persisted as evidence; the un-priced validation phase is 07c / runtime-control debt | — |

**Not yet generic (owned later)**: task-declared optional observations
(D14 / Step 12); a plugin-loss normalization declaration that would flip
`custom` to `established` by declaration (Step 12 / loss-plugin contract);
selected rendering (07b); calibrated labels (Step 09).

**Do not invent this seam ad hoc** — update this section first.

---

## Working rules

- **Contract tests, not claims.** Each genericized seam gets a unit test
  against a minimal synthetic second-dataset (or second-task/metric) fixture.
  A seam without such a test is "renamed", not "generic". Current evidence:
  `tests/unit/execute_tools/test_dataset_contract.py`.
- **In-passing, own commit.** The refactor rides on the normal development
  ladder, lives in its own commit within the PR, and is skippable for urgent
  fixes.
- **Bounded.** A PR genericizes the module it touches. Sites in other modules
  become ledger entries, not scope creep.
- **Update this doc first** when a new abstraction is needed.
