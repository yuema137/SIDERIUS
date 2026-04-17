# Validation-Awareness Across Proposer + Implementor

**Status**: Phase A complete 2026-04-16; Phase B not started
**Author**: design discussion 2026-04-16
**Motivation**: two iter-1 runs (`exploit_cnn_v1`, `explore_novel_v1`, launched 2026-04-16 23:02) burned their entire 9-attempt budgets and produced **zero successful rounds** because the proposer wrote `baseline_config` values that violated downstream validation rules. Both runs reached `status="partial", completed_rounds=0, all_records=[]` after ~2.5 minutes each, then advanced to iter-2 and would have repeated the same failure mode for the rest of the 20-iteration budget.

## Progress log

| Phase | Date | Commit | Tests |
|---|---|---|---|
| Design doc | 2026-04-16 | `ba1d9d0` | n/a |
| A.1 — `ProposalOutput` segmentation_size validator + `DatasetConfig.valid_segmentation_sizes()` helper | 2026-04-16 | `7c935b0` | 6 helper + 9 validator tests; 253 full proposer suite + 899 full agent unit suite all green |
| A.2 + A.3 — `_format_known_constraints_block` helper, `{known_constraints_block}` placeholder in `proposing_stage.md`, wired in `nodes/ml_model_proposal_agent.py` with `DATASET_CONFIG` | 2026-04-16 | `8c37d61` | 10 new tests; 263 full proposer suite green |
| A.4 — confirm existing proposer retry loop catches the A.1 validator (no new wiring) + 3 integration tests | 2026-04-16 | `ff59aa8` | 3 new tests in `TestSegmentationSizeRetryIntegration`; 28 full pipeline_runner suite green |
| A.5 — Phase A acceptance gate (stubborn-LLM scenario covered by A.4 unit tests; dual-mode test deferred to C.3) | 2026-04-16 | (this commit — doc only) | 272 tests (266 proposer + 6 dataset_config) |

---

## 1. Problem Statement

### 1.1 What happened

Two parallel runs launched in screens at 2026-04-16 23:02. Both used the trial-mode workflow defaults (`is_trial=True`, `trial_portion=0.1`, `train_portion=1.0`, `eval_portion=0.1`, `max_epochs=1`). Both failed identically: 9/9 tuner-planning attempts rejected with the same `ValidationError` repeating across attempts.

| Run | Proposed model | Failing field | Failing value | Validator | Attempts |
|---|---|---|---|---|---|
| `exploit_cnn_v1` | `dual_branch_spectral_wavenet` | `model_config.segmentation_size` | `16384` | `_validate_data_config` (tuner) — `psd_segment_length=10_000_000` not divisible by `16384` | 9/9 failed |
| `explore_novel_v1` | `bidir_spectral_ssm_refiner` | `model_config.refiner_kernel_size` | `5` | `BidirSpectralSsmRefinerConfig` (implementor's own pydantic schema) — `multiple_of=2` constraint | 9/9 failed |

In both runs the tuner LLM's reasoning text **acknowledged** the error in attempt-2 prose ("the baseline `segmentation_size=16384` is invalid because…", "I correct segmentation_size to 16000…") but the **plan dict it emitted still carried the original invalid value**. The "Loop Error" feedback channel exists but the LLM doesn't reliably translate prose acknowledgement into a corrected field value, especially when the field was inherited from `baseline_config`.

### 1.2 Root cause

The two failures look the same on the surface but have **different upstream owners**, which is why a single fix doesn't cover both:

| # | Constraint family | Owner | Where currently checked | Why it leaked |
|---|---|---|---|---|
| 1 | **Dataset-level** — `segmentation_size` must divide `DATASET_CONFIG.psd_segment_length` | Dataset (fixed, global, knowable at proposal time) | `nodes/ml_hyperparameter_tune_agent.py:40` `_validate_data_config` (deep in the tuner's per-attempt loop) | The proposer is **never told** about the divisor list. It freely wrote a power-of-two value. The check fires only after the tuner has wasted a planning LLM call. |
| 2 | **Model-internal** — `refiner_kernel_size` must satisfy `multiple_of=2` | Implementor (invented at code-generation time when writing the pydantic config schema) | The implementor's own pydantic schema, which is invoked during the **tuner's resource check** at `agent/skills/evaluate_resource_skill/wrapper.py:37` via `config_cls(**model_cfg)` | Validator step 5 (`nodes/ml_code_validator_agent.py:310`) instantiates `PLUGIN_CONFIG_CLASS()` with **defaults only** — never with the proposer's `baseline_config['model_config']`. So a schema whose defaults satisfy its own constraints can ship even when the baseline values it was given do not. |

In both cases the **upstream node sent the tuner a baseline that was guaranteed to fail**, and the tuner LLM lacked the mechanical reflex to overwrite an inherited value.

### 1.3 Why the existing prose advice didn't save us

`tuner_advice/exploit_cnn_v1.json` already says:

> "NEVER use 4096, 8192, or other powers of 2 unless they appear in this list."

And lists the valid divisors verbatim. The LLM read this advice — its reasoning prose cited it — but the plan dict it emitted still contained `segmentation_size=16384`. **Prose constraints are not enforcement**. We need machine-checked gates.

---

## 2. Design

The design is built on a clear **ownership boundary** between dataset-level and model-internal fields, and a small **audit trail** so any implementor adjustments are visible downstream.

### 2.1 Ownership boundary

| Field family | Owner | Implementor allowed to modify? | Rationale |
|---|---|---|---|
| **Dataset-level** (`segmentation_size`, anything derived from `DATASET_CONFIG`) | Proposer | **No** | The constraint is global and known at proposal time. The proposer must produce a valid value. Letting the implementor mutate dataset-level fields would mean the proposer's `falsifiable_prediction` was made against a different data scale than what gets tested. |
| **Model-internal** (channel widths, kernel sizes, depths, layer counts) | Proposer proposes; implementor may adjust | **Yes**, within bounds (see §2.4) | The implementor invents constraints (`multiple_of`, `ge`, `le`, etc.) at schema-writing time. It has local information the proposer doesn't. It is the natural party to reconcile its own schema with the baseline it was handed. |

### 2.2 Two-stage gate

```
                ┌─────────────────────────────────────────────────────────┐
                │  PROPOSER                                                │
                │  - Prompt now includes "Known Validation Constraints"    │
                │    block listing dataset-level rules + valid divisor list│
                │  - ProposalOutput pydantic validator checks:             │
                │    DATASET_CONFIG.psd_segment_length %                   │
                │      baseline_config['model_config']['segmentation_size']│
                │      == 0                                                │
                │  - On failure: feeds back into proposer's existing       │
                │    3-attempt retry loop via previous_failures            │
                └────────────────┬────────────────────────────────────────┘
                                 │  ProposalOutput (dataset-validated)
                                 ▼
                ┌─────────────────────────────────────────────────────────┐
                │  IMPLEMENTOR                                             │
                │  - Writes plugin file as today                           │
                │  - NEW post-write check:                                 │
                │    PLUGIN_CONFIG_CLASS(                                  │
                │      **proposal.baseline_config['model_config']          │
                │    )                                                     │
                │  - If pydantic raises: consume one of max_retries=2,     │
                │    re-prompt LLM with the conflict. LLM chooses to:      │
                │      Option A: emit baseline_config_adjustments entry    │
                │                (within ±20% / nearest-valid for discrete)│
                │      Option B: relax the schema constraint               │
                │  - Records every LLM-driven adjustment in                │
                │    ImplementorOutput.baseline_config_adjustments         │
                │  - On all retries exhausted: implementor returns failure │
                └────────────────┬────────────────────────────────────────┘
                                 │  ImplementorOutput (with adjustments)
                                 ▼
                ┌─────────────────────────────────────────────────────────┐
                │  VALIDATOR                                               │
                │  - Step 5 unchanged (PLUGIN_CONFIG_CLASS() with defaults)│
                │  - NEW step 5b: if baseline_config provided in input,    │
                │    instantiate PLUGIN_CONFIG_CLASS(**baseline_config)    │
                │    as a redundant guard. This is belt-and-suspenders;    │
                │    the implementor should have caught it already.        │
                └─────────────────────────────────────────────────────────┘
```

### 2.3 Audit trail

`ImplementorOutput.baseline_config_adjustments: Dict[str, ConfigAdjustment]` where:

```python
class ConfigAdjustment(BaseModel):
    original_value: Any
    adjusted_value: Any
    reason: str   # e.g. "5 -> 4 to satisfy multiple_of=2 constraint on refiner_kernel_size"
```

**Downstream consumers**:
- The protocol `proposal_to_hyperparam_seeded_v1` uses the **adjusted** baseline for the tuner.
- The interpretation agent receives both the original and adjusted versions so its hypothesis-evaluation can flag when a prediction was made against a config that got mutated before testing.
- The reflector compares the run record against the **adjusted** baseline (that is what was actually tested).

### 2.4 Adjustment policy (boundary on implementor flexibility)

To prevent the implementor from silently turning a 5M-param baseline into a 100K toy:

| Field type | Allowed adjustment |
|---|---|
| Continuous numeric (channel widths, hidden dims) | Within ±20% of original value |
| Discrete numeric with constraint (kernel size, group size) | Nearest valid value satisfying the constraint |
| Boolean / categorical | Not adjustable — must retry the implementor with a different schema |
| Dataset-level (segmentation_size, etc.) | **Never** adjustable — must retry the proposer |

The policy is enforced as a pydantic validator on `ConfigAdjustment` and surfaced in the implementor's retry prompt: *"You may adjust within ±20%, snap to nearest valid value, or relax your schema constraint. You may NOT change segmentation_size — that is the proposer's responsibility."*

---

## 3. Phased Implementation Plan

### Phase A — Proposer-side gate + prompt awareness (Fix A)

Catches `segmentation_size=16384` before the implementor is even invoked.

#### A.1 — Schema validator on `ProposalOutput.baseline_config` ✅
- [x] Add `model_validator(mode="after")` on `ProposalOutput` in `agent/schemas/proposal.py`
- [x] Validator checks `DATASET_CONFIG.psd_segment_length % seg == 0` where `seg = baseline_config['model_config']['segmentation_size']`
- [x] Error message lists valid divisors (uses new `DatasetConfig.valid_segmentation_sizes()` helper instead of mirroring the tuner's slow `range(100, psd+1)` enumeration — sqrt-based, ~3000 iterations vs 10M)
- [x] Validator no-ops gracefully when `segmentation_size` is absent (some proposals may omit it)
- [x] Unit tests: `tests/unit/agent/ml_model_proposal_agent/test_baseline_config_validators.py`
  - [x] valid divisor passes (also batch-checks 100, 1000, 1250, 16000, 50000)
  - [x] invalid divisor (16384) raises with valid-divisor list in message
  - [x] missing `model_config` key — no error raised
  - [x] missing `segmentation_size` key — no error raised
  - [x] empty `baseline_config={}` — no error raised (backward compat with existing tests)
  - [x] negative / zero / non-int values rejected with type-specific message
- [x] Helper test file: `tests/unit/execute_tools/test_dataset_config.py` (6 tests covering `valid_segmentation_sizes`)
- [x] Verified by 253 full proposer-agent suite + 899 full agent unit suite — zero regressions

#### A.2 — Proposer prompt: known-constraints block ✅
- [x] Add `_format_known_constraints_block(dataset_config)` helper in `agent/prompts.py`
- [x] Block lists: `psd_segment_length`, valid `segmentation_size` divisors, calls out invalid powers-of-2 (16384/8192/4096) explicitly, mentions 16000 as recovery hint
- [x] Inject block into the **proposing stage** prompt only (not the comparison/causal-reasoning stages — they don't write `baseline_config`); placeholder `{known_constraints_block}` placed right before `## Rules` for high salience near `baseline_config` description
- [x] Unit tests: `tests/unit/agent/ml_model_proposal_agent/test_known_constraints_block.py` (10 tests)
  - [x] empty when `dataset_config` is None (backward compat)
  - [x] block includes psd_segment_length, valid divisors, invalid-power-of-2 callout, recovery hint
  - [x] high-salience heading present
  - [x] proposing_stage prompt renders block when supplied
  - [x] placeholder collapses to empty string when block is "" (no leftover braces)
  - [x] block precedes `## Rules` in rendered prompt
  - [x] other stages (comparison, causal_reasoning) ignore the unknown placeholder

#### A.3 — Wire `dataset_config` through to the proposer ✅
- [x] `DATASET_CONFIG` importable inside the proposer node (via `from execute_tools.dataset_config import TIDMAD as DATASET_CONFIG`)
- [x] `nodes/ml_model_proposal_agent.py` passes `dataset_config=DATASET_CONFIG` to `_format_known_constraints_block`, injected via `template_vars["known_constraints_block"]` in the stage runner
- [x] No new field on `ProposalInput` — `DATASET_CONFIG` is a global constant for now

#### A.4 — Verify existing retry loop catches the validator ✅
- [x] Confirmed by reading `nodes/ml_model_proposal_agent.py:795-868`: `_run_pipeline` already wraps the proposing stage in a `for attempt in range(_MAX_PROPOSING_RETRIES + 1)` loop. On `ValidationError` (which is what A.1's segmentation_size validator raises), the error summary is appended to `accumulated["proposing_stage_errors"]`, which the next attempt's user prompt re-emits via `json.dumps(accumulated, ...)`. No new wiring needed.
- [x] Note: the doc previously referred to `previous_failures`; the actual mechanism is the per-call `accumulated["proposing_stage_errors"]` channel. `inp.previous_failures` is a separate cross-call channel from the orchestration layer.
- [x] Integration tests in `tests/unit/agent/ml_model_proposal_agent/test_pipeline_runner.py::TestSegmentationSizeRetryIntegration` (3 tests):
  - [x] invalid segmentation_size=16384 on attempt 1 → 16000 on attempt 2 succeeds; only the proposing stage retries
  - [x] retry's user prompt contains `proposing_stage_errors` with the validator's diagnostic naming `segmentation_size` and the offending value `16384`
  - [x] never-corrected stubborn LLM exhausts retries and raises `RuntimeError` cleanly (count: 2 reasoning stages + `_MAX_PROPOSING_RETRIES + 1` proposing attempts)

#### A.5 — Phase A acceptance test ✅
- [x] Stubborn-LLM-picks-16384-then-16000 scenario covered by the A.4 unit tests (`TestSegmentationSizeRetryIntegration`). A separate dual-mode integration test in `tests/integration/nodes/` was considered but deferred — the three A.4 unit tests already lock in the contract end-to-end (mocked bridge, real `ProposalOutput` schema, real retry loop, real prompt injection). The more valuable real-API exercise lives in Phase C.3's re-launch of the killed runs.
- [x] Full proposer test suite + helper suite green: 272 tests (`tests/unit/agent/ml_model_proposal_agent/` 266 + `tests/unit/execute_tools/test_dataset_config.py` 6), zero regressions across A.1 → A.4.

**Phase A status: complete.** The proposer now (a) sees the dataset divisor rule in its prompt next to `baseline_config`, (b) machine-validates its own emitted `segmentation_size`, and (c) retries on violation with the validator error visible to the next LLM call. The 9-for-9 iter-1 failure mode observed on 2026-04-16 is closed from the proposer side.

---

### Phase B — Implementor-side baseline check + adjustment audit (Fix B)

Catches `multiple_of=2` vs `refiner_kernel_size=5` before the tuner runs.

#### B.1 — `ConfigAdjustment` schema + `ImplementorOutput.baseline_config_adjustments`
- [ ] Add `ConfigAdjustment` model in `agent/schemas/implementor.py`
- [ ] Add `baseline_config_adjustments: Dict[str, ConfigAdjustment] = Field(default_factory=dict)` to `ImplementorOutput`
- [ ] Add validator on `ConfigAdjustment` enforcing the §2.4 policy:
  - dataset-level fields rejected (constant list of forbidden field names: `segmentation_size`, …)
  - continuous numeric: `|new - old| / |old| <= 0.20`
  - discrete: any value (snap-to-nearest is the implementor's job, the validator just records)
- [ ] Unit tests: `tests/unit/agent/ml_model_implementor/test_config_adjustment_schema.py`

#### B.2 — Implementor post-write check
- [ ] After writing the plugin file in `nodes/ml_model_implementor.py`, import it via `importlib`
- [ ] Run `module.PLUGIN_CONFIG_CLASS(**baseline_config['model_config'])`
- [ ] Two outcomes:
  1. Pass → no adjustment, `baseline_config_adjustments={}`, return success
  2. Pydantic raises → consume one of `max_retries=2`, feed `previous_validation_failure` to LLM with the adjust-or-relax instruction (see B.3). The LLM is responsible for resolving — either by editing the schema or by emitting a `baseline_config_adjustments` entry with a value that passes its own schema. The post-write check re-runs after each retry.
- [ ] On all retries exhausted with the conflict still present, the implementor returns a failure status that propagates to the iteration controller (existing failure-path; no new wiring)
- [ ] Unit tests: `tests/unit/agent/ml_model_implementor/test_baseline_self_check.py`
  - [ ] schema accepts baseline as-is → no retry, no adjustment, success
  - [ ] schema rejects baseline → retry consumed, LLM-corrected schema (or adjustment) accepted on attempt 2
  - [ ] schema still rejects after all retries → implementor returns failure
  - [ ] adjustment violating §2.4 policy (dataset-level field, > 20% delta) → ConfigAdjustment validator rejects, retry consumed

#### B.3 — Implementor retry prompt: adjust-or-relax instruction
- [ ] Extend the retry prompt with a section: *"Your schema rejected the proposer's baseline value `<field>=<value>` (constraint: `<constraint>`). You have two options: (a) relax the constraint so the baseline value is accepted, or (b) change the constraint so the nearest valid value is within ±20% of `<value>`. You MAY NOT change `segmentation_size` — that is the proposer's responsibility, not yours."*
- [ ] Unit test: rendered prompt contains both options + the boundary clause

#### B.4 — Protocol updates
- [ ] `agent/schemas/protocols/proposal_to_hyperparam_seeded.py`: when assembling tuner input, apply `baseline_config_adjustments` to override original baseline values
- [ ] `agent/schemas/protocols/implementor_to_validator.py`: pass `baseline_config_adjustments` through (read-only — validator may surface a warning if non-empty)
- [ ] `agent/schemas/protocols/<tune>_to_<interp>.py`: ensure interpretation agent receives both original and adjusted baseline, so its hypothesis-eval can flag mutations
- [ ] Unit tests for each protocol covering the new field

#### B.5 — Validator step 5b (belt-and-suspenders)
- [ ] Add optional `baseline_config: Optional[Dict[str, Any]]` to `ValidatorInput`
- [ ] If present, instantiate `PLUGIN_CONFIG_CLASS(**baseline_config)` after the existing defaults check
- [ ] Failure surfaces a warning (`spec_alignment=false`) but does NOT set `passed=false` — the implementor should have caught this; if it didn't, the run will fail at the tuner anyway and we'll see the symptom, not silently corrupt
- [ ] Unit tests for the new step

#### B.6 — Phase B acceptance test
- [ ] Pseudo-mode dual-mode test: implementor attempt 1 writes schema with `multiple_of=2`, baseline has `=5`; post-write check fails; attempt 2 (LLM-driven) either emits `baseline_config_adjustments={"refiner_kernel_size": ConfigAdjustment(5, 4, "satisfy multiple_of=2")}` or relaxes the schema to accept `=5`; either path records the audit entry, downstream tuner receives a schema-compatible value
- [ ] Pseudo-mode dual-mode test: all retries exhausted with conflict unresolved → implementor returns failure status, iteration controller sees the failure
- [ ] Pseudo-mode dual-mode test: LLM proposes an adjustment violating §2.4 (e.g. -50% delta) → `ConfigAdjustment` validator rejects, next retry consumed
- [ ] Run full implementor test suite

---

### Phase C — End-to-end smoke + advice file cleanup

#### C.1 — End-to-end Tier-3 smoke
- [ ] Tier-3 dual-mode test (`tests/integration/workflows/`) running propose → implement → validate → tune through one round, with deliberate constraint conflicts injected at both the dataset level (proposer) and model-internal level (implementor)
- [ ] Verify zero attempts wasted on the per-round budget when the upstream gates fire correctly

#### C.2 — Advice file prose updates
- [ ] `tuner_advice/explore_novel_v1.json` and `tuner_advice/exploit_cnn_v1.json`: prose constraint about `segmentation_size` divisor list becomes secondary defense (machine gate is primary). Keep the prose for LLM context but update wording to "as a sanity reminder, the system also enforces…" rather than "NEVER use…"
- [ ] No new advice prose needed for `multiple_of` — that's per-model and the implementor handles it locally

#### C.3 — Re-launch the two killed runs
- [ ] Re-launch `exploit_cnn_v1` and `explore_novel_v1` in screens
- [ ] Confirm iter-1 reaches at least one completed round (the previously-failing pattern produces at minimum `completed_rounds=1`)
- [ ] Document the launch in this doc's Progress Log

---

## 4. Out of scope (tracked separately)

- **Tuner-side hint enhancement (Fix C from earlier discussion)**: when `_validate_data_config` fires anyway, prepend a structured repair instruction naming the field. Lower priority since A+B should cut off both failure paths upstream. Re-evaluate after A+B land.
- **Noisy `TimeEval error` print at proposer baseline gate**: the error is expected (model_type not yet in MODEL_REGISTRY for novel architectures), but the traceback is misleading. Downgrade to single-line message in a follow-up.
- **Cross-field constraints involving both proposer and implementor ownership**: e.g. if an implementor schema imposes `kernel_size <= segmentation_size / 4` — these compound constraints aren't handled by the §2.1 boundary. Defer until we hit one in practice.

---

## 5. Decisions (locked in 2026-04-16 design discussion)

1. **Dataset-level field list — every field covered by an existing strict validator that the proposer can violate.** Auditing `_validate_data_config` (`nodes/ml_hyperparameter_tune_agent.py:40`) gives three constraints, of which only one is proposer-controllable (`segmentation_size` divides `psd_segment_length`); the other two (`trial_portion`, `train_portion` minimums) are populated from workflow `plan_overrides`, not `baseline_config`. So Phase A enforces exactly that one rule, with the §3 plan structured so adding a second rule means adding a second clause to the same validator and prompt block — no architectural change. As new strict validators are added elsewhere in the codebase, they get mirrored here in the same way.
2. **±20% adjustment threshold accepted as the default.** Revisit after first end-to-end run if the auto-adjust path fires often enough to matter.
3. **Always-retry, no silent auto-adjust.** Every baseline-vs-schema conflict consumes one of the implementor's existing `max_retries=2` attempts. The retry prompt names the offending field, the constraint, and the original value, and instructs the LLM to either (a) adjust the baseline value to a valid one within ±20% / nearest-valid for discretes, or (b) relax the schema constraint. Rationale: silent code-level snaps would hide the conflict from the LLM, so the LLM never learns and can repeat the same mistake on the next iteration. Forcing the LLM to see and resolve every conflict produces a stronger learning signal across iterations and keeps the audit trail uniform — every change is LLM-attributed, recorded in `baseline_config_adjustments`, with the LLM's reasoning available.
