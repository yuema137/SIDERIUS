# Validation-Awareness Across Proposer + Implementor

**Status**: Phase A complete 2026-04-16; Phase B.1 + B.2a landed 2026-04-17, B.2b+ in progress; **Phase D.4 landed 2026-04-17** (reactive constraint-aware retry); D.1/D.2/D.3/D.5 pending
**Author**: design discussion 2026-04-16; Phase D addendum 2026-04-17
**Motivation**: two iter-1 runs (`exploit_cnn_v1`, `explore_novel_v1`, launched 2026-04-16 23:02) burned their entire 9-attempt budgets and produced **zero successful rounds** because the proposer wrote `baseline_config` values that violated downstream validation rules. Both runs reached `status="partial", completed_rounds=0, all_records=[]` after ~2.5 minutes each, then advanced to iter-2 and would have repeated the same failure mode for the rest of the 20-iteration budget. A **second class of failure** surfaced during the Phase C.3 re-launch on 2026-04-17: `exploit_cnn_v1` iter-1 burned 9 attempts on the same pydantic `@model_validator(mode='after')` cross-field invariant (`nondecreasing channels`) — the tuner's planner cannot see this kind of rule because `PLUGIN_CONFIG_CLASS.model_json_schema()` drops `@model_validator` bodies. Phase D closes this new gap.

## Progress log

| Phase | Date | Commit | Tests |
|---|---|---|---|
| Design doc | 2026-04-16 | `ba1d9d0` | n/a |
| A.1 — `ProposalOutput` segmentation_size validator + `DatasetConfig.valid_segmentation_sizes()` helper | 2026-04-16 | `7c935b0` | 6 helper + 9 validator tests; 253 full proposer suite + 899 full agent unit suite all green |
| A.2 + A.3 — `_format_known_constraints_block` helper, `{known_constraints_block}` placeholder in `proposing_stage.md`, wired in `nodes/ml_model_proposal_agent.py` with `DATASET_CONFIG` | 2026-04-16 | `8c37d61` | 10 new tests; 263 full proposer suite green |
| A.4 — confirm existing proposer retry loop catches the A.1 validator (no new wiring) + 3 integration tests | 2026-04-16 | `ff59aa8` | 3 new tests in `TestSegmentationSizeRetryIntegration`; 28 full pipeline_runner suite green |
| A.5 — Phase A acceptance gate (stubborn-LLM scenario covered by A.4 unit tests; dual-mode test deferred to C.3) | 2026-04-16 | `b904fe2` | 272 tests (266 proposer + 6 dataset_config) |
| B.1 — `ConfigAdjustment` schema + `ImplementorOutput.baseline_config_adjustments` dict; §2.4 policy enforced (forbidden list for dataset-level fields; ±20% delta on numeric; bool/str rejected) | 2026-04-17 | `240fd5e` | 22 new tests; 88 full implementor suite green |
| B.2a — baseline-self-check helper + wiring into `_validate_code`; existing retry loop picks up schema-relax path | 2026-04-17 | `4ca5ca4` | 17 new tests; 105 full implementor suite green |
| C.3 (test infra) — Tier-3 replay test `test_baseline_validation_fix.py` for propose→implement→validate slice of the 2026-04-16 failures | 2026-04-17 | `3458ef0` | 2 new real-LLM tests; both passed (601 s) |
| D observation — `exploit_cnn_v1` iter-1 re-launch burned 9 attempts on `@model_validator` cross-field invariant (`nondecreasing channels`); root-caused to `model_json_schema()` dropping validator bodies | 2026-04-17 | run log `logs/exploit_cnn_v1_20260417_005517.log` | design below |
| D.4 — reactive constraint-aware retry: `skipped_schema_violation` record type, wrapper returns structured `schema_violation` on `ValidationError`, tuner saves record + continues without advancing round | 2026-04-17 | `51c0b87` (schema) + `8785f8d` (wrapper) + `5c65106` (tuner) + `5e65655` (tests + doc) | 3 new schema tests + 10 new D.4 tests (`test_constraint_aware_retry.py`); 193 full `tune_ml_hyperparam_agent` suite green |

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

#### B.1 — `ConfigAdjustment` schema + `ImplementorOutput.baseline_config_adjustments` ✅
- [x] Added `ConfigAdjustment` model in `agent/schemas/implementor.py` with fields `original_value`, `adjusted_value`, `reason` (min_length=1 for audit trail readability)
- [x] Added `baseline_config_adjustments: Dict[str, ConfigAdjustment] = Field(default_factory=dict)` to `ImplementorOutput` (default empty preserves backward compat with existing implementor tests)
- [x] Enforced §2.4 policy across two validator sites:
  - `ConfigAdjustment.model_validator` (single-entry): ±20% delta for numeric (int/float, non-bool), zero-original requires zero-adjusted, bool rejected as categorical, non-numeric (str/list/dict) rejected
  - `ImplementorOutput.model_validator` (cross-key): keys in `_FORBIDDEN_ADJUSTMENT_FIELDS` (currently `{"segmentation_size"}`) rejected with error text routing the retry upstream to the proposer
- [x] **Simplification from the original spec**: the doc originally distinguished "continuous numeric" (±20% enforced) from "discrete numeric with constraint" (any value). In pydantic both are typically `int`, so type-based discrimination is unreliable. Per locked decision §5.2 ("±20% accepted as default"), we enforce ±20% universally on int+float. If legitimate `multiple_of` snaps can't satisfy this (e.g., `kernel_size=3` with `multiple_of=5` → 5, 66%), the LLM must relax the schema instead. Revisit if this fires on real runs.
- [x] Unit tests: `tests/unit/agent/ml_model_implementor/test_config_adjustment_schema.py` (22 tests across 4 classes: numeric policy, categorical rejection, edge cases, ImplementorOutput ownership, module constants)

#### B.2 — Implementor post-write check

Split into two sub-steps for digestibility:

##### B.2a — Baseline self-check fires via existing retry loop (schema-relax path) ✅

- [x] New helper `_check_baseline_schema_compatibility(plugin_src, model_name, baseline_config)` in `nodes/ml_model_implementor.py` — imports the written plugin via `importlib.util`, then runs `PLUGIN_CONFIG_CLASS(**baseline_config['model_config'])`. On failure returns a human-readable error string; on success returns `None`. No-ops when baseline is empty. Never raises (graceful on malformed plugins — the smoke/syntax checks surface those).
- [x] Wired as the 5th check inside `MLModelImplementor._validate_code` (after smoke test) so the **existing** repair loop picks up the error automatically via `_build_repair_prompt` — no new retry machinery needed. This is the exact pattern Phase A.4 established on the proposer side.
- [x] Error message routes the LLM: names the offending field, includes the offending `model_config` dict verbatim, says "RELAX the offending schema constraint", reminds it not to touch `segmentation_size` (proposer-owned per §2.1).
- [x] **Scope for this sub-step is the schema-relax path only** — the LLM resolves the conflict by regenerating its schema with a less restrictive constraint. `baseline_config_adjustments` stays empty; the explicit adjust-path lands in B.2b.
- [x] Failure on all retries propagates via the existing `ValueError("Code generation failed after {max_retries + 1} attempts...")` path — no new failure wiring.
- [x] Unit + integration tests: `tests/unit/agent/ml_model_implementor/test_baseline_self_check.py` (17 tests across 5 classes: no-op paths, schema-accepts, schema-rejects with error content checks, graceful handling of malformed plugins, `_validate_code` integration with check ordering).

##### B.2b — LLM-driven `baseline_config_adjustments` emission (adjust path)

Requires B.3's prompt work first so LLM knows the adjust option exists.

- [ ] Extend the code-generation output JSON schema with optional `baseline_config_adjustments: Dict[str, {original_value, adjusted_value, reason}]`
- [ ] Implementor applies any returned adjustments to the written plugin's config defaults before re-running the baseline check
- [ ] Validate adjustments against `ConfigAdjustment` (from B.1); a policy violation (forbidden field, > ±20%) consumes a retry just like a pydantic failure
- [ ] Populate `ImplementorOutput.baseline_config_adjustments` so downstream protocols (B.4) can thread it through
- [ ] Unit tests: valid adjustment captured, forbidden adjustment triggers retry, > ±20% adjustment triggers retry, empty adjustments dict is the default success path

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
- [x] Tier-3 replay test `tests/integration/workflows/test_baseline_validation_fix.py` landed (commit `3458ef0`) — both `exploit_cnn_v1` and `explore_novel_v1` propose→implement→validate slices pass with real OpenAI
- [x] Re-launch `exploit_cnn_v1` in screen (2026-04-17 00:55 PDT) — 4 iterations reached; iter-1 abandoned (see Phase D below), iter-2/3 completed, iter-4 in progress at time of writing
- [x] Re-launch `explore_novel_v1` in screen (2026-04-17 00:55 PDT, relaunched 09:35 with `segmentation_size ≥ 40000` advice restriction + trial 30 min / formal 120 min budgets after first relaunch stalled on formal inference)
- [x] **Original failure mode confirmed closed from the proposer side**: zero Phase A gate fires and zero Phase B.2a fires across both runs (LLM produced valid baselines on first try every iter). The silent-guard contract holds.
- [ ] **New failure mode surfaced in exploit_cnn_v1 iter-1** (see Phase D) — not covered by A or B.2a.
- [x] Documented in this doc's Progress Log

---

### Phase D — Cross-field invariant awareness (implementor → tuner) (Fix D)

Catches hand-rolled `@model_validator(mode='after')` cross-field invariants before the tuner's planner wastes attempts proposing configs that violate them.

#### D.0 — Problem statement (observed 2026-04-17 in `exploit_cnn_v1` iter-1)

**What happened.** `exploit_cnn_v1` iter-1 (model `dual_path_skip_fusion_cnn`) burned all 9 retry attempts: 2 on time-gate failures and **7 consecutively** on the same pydantic `ValidationError`:

```
Value error, context channels must be nondecreasing, got 32, 96, 128, 96
Value error, context channels must be nondecreasing, got 24, 96, 128, 64
Value error, context channels must be nondecreasing, got 32, 96, 128, 80
...
```

The validator lives in the implementor-generated plugin at `agent_generated/models/dual_path_skip_fusion_cnn.py:28-36`:

```python
@model_validator(mode='after')
def check_constraints(self):
    if not (self.context_stem_channels
            <= self.context_level2_channels
            <= self.context_level3_channels
            <= self.context_bottleneck_channels):
        raise ValueError(f'context channels must be nondecreasing, got ...')
    return self
```

Baseline passed the check (defaults `64 ≤ 96 ≤ 128 ≤ 160` — valid). The failing configs were all **tuner-perturbed variants** emitted by the planner round by round. `dual_path_skip_fusion_cnn` iteration was abandoned with `best_score=None` after exhausting the retry budget.

**Root cause: lossy implementor→tuner schema handoff.**

| Party | Sees plugin source? | How it learns the schema |
|---|:---:|---|
| implementor | ✓ (it wrote it) | — |
| validator (`ml_code_validator_agent`) | ✓ | reads the plugin file |
| **tuner planner** | **✗** | `PLUGIN_CONFIG_CLASS.model_json_schema()` — see `nodes/ml_hyperparameter_tune_agent.py:265` |

Pydantic's `model_json_schema()` exposes per-field constraints (`minimum`, `maximum`, `multipleOf`) but **has no representation for `@model_validator(mode='after')` bodies**. So the planner sees the four `context_*_channels` as independent ints within their overlapping `ge`/`le` ranges — monotonicity is invisible.

Verified directly by running `PLUGIN_CONFIG_CLASS.model_json_schema()` on the offending plugin and confirming the `check_constraints` body is absent from the output (only per-field `minimum`/`maximum`/`multipleOf` present).

**Why retries didn't rescue it.** The planner receives a generic "Loop Error: ValidationError" retry signal — the structured reason (the error message string, naming the fields and values) is not promoted to a first-class pinned "avoid-this-combo" rule in the next attempt's context. 7 identical failures in a row confirm the planner never internalized the rule.

**Why this is structural, not model-specific.** Cross-field invariants are **natural and common in ML configs**:
- U-Net encoders: widths monotonically non-decreasing (this case)
- Transformers: `hidden_dim % num_heads == 0`
- Dilated stacks: `receptive_field ≤ segmentation_size`
- Any concat/add fusion: branch widths must be compatible
- ResNet-style blocks: bottleneck channel ratio constraints

The project actively encourages this pattern via CLAUDE.md ("Pydantic validation and appropriate error message is highly recommended"). Every future plugin that writes a `@model_validator` will hit the same gap.

**Ownership.** Phase A closed proposer→validator (for `segmentation_size` divisibility). Phase B closed implementor→baseline (B.2a self-check). **Phase D closes implementor→tuner for cross-field invariants** — the last silent edge in the propose/implement/validate/tune graph for this class of failure.

#### D.1 — Surface plugin source excerpt to tuner planner (low effort, preventive)

Cheapest preventive fix. The planner already gets the json-schema dict; we additionally feed it the raw config-class block so `@model_validator` bodies are visible.

- [ ] Add extraction helper `_extract_config_class_excerpt(plugin_src: str) -> str` in `nodes/ml_hyperparameter_tune_agent.py` (or `agent/prompts.py` if shared): returns the `class *Config(BaseModel):` body plus any `@field_validator`/`@model_validator` decorators that appear before `PLUGIN_CONFIG_CLASS = ...`. Strip the `PLUGIN_MODEL_CLASS` forward code — it's not schema-relevant and would bloat the prompt.
- [ ] Truncate to ≤4000 chars; append `"... (truncated)"` marker if cut.
- [ ] Read plugin source once per run in `HyperparamTuningAgent.run()` (plugin path already in `agent_input`), cache as `self._plugin_source_excerpt`, pass to `brain.plan(..., plugin_source_excerpt=...)`.
- [ ] Update `build_exploration_checklist` (or render it in the planner prompt adjacent to the checklist) to inject the excerpt under a pinned heading like `## PLUGIN CONFIG SCHEMA (authoritative — read these validators carefully)`.
- [ ] Unit tests (`tests/unit/agent/ml_hyperparameter_tune_agent/test_plugin_source_excerpt.py`, new file):
  - [ ] extraction returns config class + validators only; forward code stripped
  - [ ] excerpt trimmed to ≤4000 chars with truncation marker
  - [ ] plugin lacking any `@*_validator` still returns a clean excerpt (just the class body)
  - [ ] plugin missing `PLUGIN_CONFIG_CLASS` returns empty string (graceful)
  - [ ] planner prompt renders the excerpt section when supplied; omits the whole section when empty
- [ ] Drawback: prompt bloat every planner call. Common-case excerpt is 500–1500 chars so bearable; track in production.

#### D.2 — `ImplementorOutput.schema_constraints` plain-English rules (medium effort, preventive, clean)

Long-term home: the implementor emits a structured summary of every cross-field rule it encodes. Two-channel redundancy with D.1 — if the LLM under-parses the source, it can lean on the plain-English list.

- [ ] Add field to `agent/schemas/implementor.py`:
  ```python
  schema_constraints: list[str] = Field(
      default_factory=list,
      description="Plain-English statement of each cross-field invariant the plugin's "
                  "config schema enforces. Populate whenever @model_validator(mode='after') "
                  "or cross-field @field_validator is present. Empty allowed only when "
                  "the plugin has NO cross-field rules beyond per-field ge/le/multiple_of."
  )
  ```
- [ ] Extend the code-generation output JSON schema (the structured-output contract) with the same optional field.
- [ ] Update the implementor prompt (`agent/prompts.py` or the implementor's system prompt): when the LLM emits any `@model_validator(mode='after')` or any `@field_validator` that references multiple fields, it MUST also populate `schema_constraints` with one human-readable entry per rule. Example shown in-prompt: `"context_stem_channels <= context_level2_channels <= context_level3_channels <= context_bottleneck_channels (U-Net encoder widths must be monotonically non-decreasing for skip-fusion buffer shapes to line up)"`.
- [ ] Add a regex-based lint inside `_validate_code` (as a new 6th check, after baseline self-check): if plugin source contains `@model_validator` or `@field_validator` with an arg list of length ≥2, fail validation unless `schema_constraints` is non-empty. Error routes the LLM to populate the field (not to remove the validator).
- [ ] Thread `schema_constraints` through the graph:
  - `ImplementorOutput` → already on the implementor record
  - protocol `ml_model_impl_to_ml_model_tune` (whichever name): pass into tuner input
  - `HyperparamTuningInput`: new field `schema_constraints: list[str] = []`
  - tuner planner prompt: pinned "## CONFIG RULES" section rendering each entry verbatim
- [ ] Unit tests (`tests/unit/agent/ml_model_implementor/test_schema_constraints.py`):
  - [ ] default empty preserves backward compat
  - [ ] plugin with `@model_validator` + empty `schema_constraints` fails `_validate_code` lint
  - [ ] plugin with `@model_validator` + populated `schema_constraints` passes
  - [ ] plugin with only per-field `ge`/`le` (no `@*_validator`) passes with empty list
- [ ] Protocol tests verify pass-through. Tuner-side prompt test verifies rendering.

#### D.3 — Declarative constraint DSL (medium effort, cleanest, optional)

Sibling upgrade to D.2: in addition to plain-English, implementor emits machine-evaluable expressions. Lets the tuner gate configs *before* Pydantic instantiation, saving the full resource-check cost.

- [ ] Add `schema_constraints_declarative: list[str]` to `ImplementorOutput`. Each entry is a Python expression string using only: comparison ops (`<, <=, ==, !=, >=, >`), boolean ops (`and, or, not`), field names defined in the config, numeric literals. Example: `"context_stem_channels <= context_level2_channels"`.
- [ ] Parser + safety whitelist helper `parse_declarative_constraint(expr: str, field_names: set[str]) -> ast.Expression`: use `ast.parse` with restricted node types. Reject `Import`, `Attribute`, `Call`, `Subscript`, anything not in the whitelist. Reject unknown identifiers (not in `field_names`). Return parsed AST for later evaluation.
- [ ] Evaluator `evaluate_declarative_constraint(ast_expr, config_dict) -> bool`: walks the AST with the dict as the scope; no `eval`/`exec`.
- [ ] Tuner-side gate in `HyperparamTuningAgent.run()`: after the planner emits a config, evaluate every declarative constraint. If any fails, re-prompt the planner with the specific expression and the failing field values, **without** paying a Pydantic instantiation or resource-check attempt.
- [ ] Unit tests (`tests/unit/agent/protocols/test_declarative_constraints.py`):
  - [ ] parser accepts whitelisted exprs (monotone, multiple_of, equality)
  - [ ] parser rejects `import`, `__class__`, function calls, attribute access
  - [ ] parser rejects unknown field names
  - [ ] evaluator correctly flags monotone-violation; returns True for valid configs
  - [ ] tuner-side gate short-circuits before resource check on violation
- [ ] Note: only land if D.1+D.2+D.4 leave measurable failure rate. Revisit after one full real-run cycle with D.1+D.2 in place.

#### D.4 — Constraint-aware retry (low effort, reactive) ✅

Safety net: if a `ValidationError` slips through D.1–D.3 prevention, surface the *specific violating rule* back to the planner via the next attempt's `memory_history`, not as a generic "Loop Error".

**Design note (refined during implementation review 2026-04-17).** The original sketch proposed a dedicated `accumulator` of `{attempt_n: {config, violations}}` rendered into a custom `## DO NOT REPEAT THESE CONFIGS` prompt block. Reading the actual tuner loop shows the existing `skipped_oom_risk` / `skipped_time_risk` records already solve the same problem: they are saved via `sandbox.save_record()`, automatically appear in the next round's `memory_history = sandbox.get_summary()`, and their `memory.conclusion` + `memory.memory_update` fields are already rendered to the planner. A new `skipped_schema_violation` record type plugs straight into that machinery — no parallel accumulator, no new prompt block, no extra wiring.

This keeps D.4 identical in behavior (planner sees structured, field-level signal on next attempt) but removes ~30 lines of bespoke plumbing. Reconsider the dedicated accumulator only if real runs show the planner still repeats violations after 2-3 records (i.e. memory-history rendering is too dilute to cut through). Deviation explicitly flagged so the doc keeps pace with what was built.

- [x] Added `"skipped_schema_violation"` to `ExperimentRecord.status` Literal in `agent/schemas/hyperparam_tuning.py` (commit `51c0b87`).
- [x] Extended `agent/skills/evaluate_resource_skill/wrapper.py` (commit `8785f8d`): two new helpers `_extract_schema_violations` (turns `ValidationError.errors()` into serializable dicts with `loc` / `type` / `msg` / `input`; empty `loc` normalized to `"__root__"` for `@model_validator` cross-field rules) and `_format_schema_violation_verdict` (short one-liner for logs + `memory.conclusion`). The `_count_params(...)` call in `run_skill` is now wrapped in a dedicated `try/except ValidationError` **before** the existing broad `except Exception`; on match, returns `{"status": "schema_violation", "violations": [...], "offending_config": model_cfg, "message": <verdict>, "verdict": <verdict>, "suggestion": "Propose a config that satisfies the plugin's schema invariants. DO NOT repeat the same field/value combination."}` instead of raising.
- [x] In `nodes/ml_hyperparameter_tune_agent.py` (commit `5c65106`), added a new branch after the resource-check-error check and before the feasibility check, mirroring `skipped_oom_risk` / `skipped_time_risk`:
  - `if resource_check.get("status") == "schema_violation":` — builds and validates an `ExperimentRecord` with `status="skipped_schema_violation"`, `params=record_params`, `denoising_score=None`.
  - `memory.conclusion` reads *"Skipped: plugin schema rejected the proposed model_config. Violating fields: {field_list}. Offending values: {offending}."*
  - `memory.memory_update` reads *"DO NOT repeat this exact combination — plugin schema requires: {violation_summary}. Propose a config that satisfies every @model_validator(mode='after') and per-field bound in the plugin's PLUGIN_CONFIG_CLASS."*
  - Calls `sandbox.save_record(...)` then `continue` — the attempt does NOT count as a round, identical to the OOM/time-skip records.
- [x] Unit tests (`tests/unit/agent/tune_ml_hyperparam_agent/test_constraint_aware_retry.py`, 10 tests across 3 classes — commit `5e65655`):
  - [x] `TestExtractor::test_model_validator_violation_loc_is_root` — `@model_validator(mode='after')` empty `loc` normalized to `"__root__"`.
  - [x] `TestExtractor::test_multiple_of_loc_and_type_and_input` — `multiple_of` violation captures `loc`, `type="multiple_of"`, and `input` verbatim.
  - [x] `TestExtractor::test_greater_than_equal_loc_and_type` — `ge` violation extracted with correct `type="greater_than_equal"`.
  - [x] `TestWrapperSchemaViolation::test_model_validator_violation_returns_schema_violation` — mock nondecreasing-channels class (mirrors `dual_path_skip_fusion_cnn` invariant) → `status="schema_violation"`, offending config + suggestion + verdict present.
  - [x] `TestWrapperSchemaViolation::test_multiple_of_violation_returns_schema_violation` — per-field `multiple_of` surfaces through the wrapper.
  - [x] `TestWrapperSchemaViolation::test_ge_violation_returns_schema_violation` — per-field `ge` surfaces through the wrapper.
  - [x] `TestWrapperSchemaViolation::test_happy_path_unchanged` — valid real `rnn` plugin config → `status="success"`, `feasible=True` (confirms the new branch doesn't intercept healthy configs).
  - [x] `TestTunerSchemaViolationBehavior::test_does_not_raise_does_not_advance_rounds` — 3/3 attempts schema_violation → `status="partial"`, `completed_rounds=0`, no exception.
  - [x] `TestTunerSchemaViolationBehavior::test_all_records_saved_as_skipped_schema_violation` — every saved record carries the new literal.
  - [x] `TestTunerSchemaViolationBehavior::test_record_memory_carries_violation_details` — `memory.conclusion` names the violating field + offending values; `memory.memory_update` carries "DO NOT" marker + the pydantic rule text verbatim.
  - Schema-side coverage handled by 3 tests in `test_hyperparam_schemas.py::TestExperimentRecordSchemaViolation` (commit `51c0b87`).
- [x] Full `tune_ml_hyperparam_agent` suite green after each step (193 tests at step 3; 10/10 new D.4 tests at step 4).
- **Drawback (unchanged from design)**: purely reactive — wastes the first attempt before the signal arrives. Most valuable when paired with D.1 (prevention) as belt-and-suspenders. Prompt-side rendering relies on the existing `memory_history` mechanism; if real runs show dilution, escalate to a dedicated pinned block later.

#### D.5 — Phase D acceptance test

- [ ] **Pseudo-mode dual-mode test** in `tests/integration/workflows/test_cross_field_invariant_recovery.py` (new file): replay the `exploit_cnn_v1` iter-1 failure mode. Fixture plugin with `@model_validator` enforcing `nondecreasing channels`; canned planner that on attempt 1 emits a non-monotone tuple. Assertions:
  - [ ] Without Phase D (feature-flag off): ≥7 attempts before exhaustion (matches observed failure)
  - [ ] With D.1 only: planner converges in ≤3 attempts (prompt-level awareness)
  - [ ] With D.1 + D.4: planner converges in ≤2 attempts
- [ ] Unit test: `dual_path_skip_fusion_cnn`'s actual on-disk plugin extracted via D.1 helper still contains the `check_constraints` body within the 4000-char cap
- [ ] Unit test: tuner planner prompt renders `schema_constraints` list (D.2 end-to-end)
- [ ] Real-run Tier-3 (optional, after D.1+D.2+D.4 land): re-launch a single-iteration trial against `dual_path_skip_fusion_cnn` and confirm iter-1 reaches `completed_rounds ≥ 1`.

#### D.6 — Order of work + MVP

Recommended execution order (lowest-risk, fastest-value first):

1. **D.4 first** — reactive fix, lowest effort, immediately improves the observed failure mode.
2. **D.1 second** — preventive, also low effort; pairs with D.4 to stop most first-attempt failures.
3. **D.2 third** — the clean long-term home; schedule alongside B.2b's implementor prompt work since both touch the same prompt.
4. **D.3 last (optional)** — only if D.1+D.2+D.4 leave measurable failures in real runs.

**Minimum viable Phase D: D.1 + D.4 + D.5.** Everything else is polish.

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
