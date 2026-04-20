# Reliable Resource-Aware Proposer — Problem Analysis & Solution Design

**Status**: design doc, pending implementation
**Date**: 2026-04-20
**Related**: `docs/resource_estimator_implement.md` (Phases K–N), `docs/adaptive_new_model_proposer.md`

---

## 1. Observed Failure — `explore_novel_v3_0420`

In the 4-iteration `explore_novel_v3_0420` run (VRAM budget 8 GB, trial time budget 20 min, seg_size pinned to 40000/50000), 3 of 4 iterations failed:

| Iter | Model | Status | Best score | Attempts | Gate exhaustion |
|------|-------|--------|------------|----------|-----------------|
| 1 | `bidirectional_spectral_gated_stack` | completed | 0.610 | 6 | — |
| 2 | `selective_bidirectional_scan_conv` | aborted | — | 9 | 9 time-gated, factor **18,772×** |
| 3 | `dual_path_gated_gru_stack` | aborted | — | 9 | 7 time + 2 other, factor **28×** |
| 4 | `gated_fourier_tcn` | killed mid-inference | partial | ≥3 | — (separate failure mode) |

Iter 2's baseline was estimated at **375,438 minutes** (~260 days) per trial vs. the 20-min budget. Iter 3's at **561 minutes** (~9.3 h) vs. 20 min. Both were *pre-flight time-gate rejections* — the `evaluate_time_skill` correctly refused to launch them. Phase L's `attempts_per_round=3 × max_fail_rounds=3 = 9` ceiling triggered the Trigger A abort. The system worked; the proposals were structurally infeasible.

## 2. The Smoking Gun

Comparing what each proposal *declared it knew* vs. what it *produced*:

### Iter 3's own `expert_advice.known_failures[0]` (verbatim):
> "Even with a streamlined implementation, bidirectional selective_state_space over segmentation_size=40000 may still exceed wall-time/VRAM budget, **repeating the non-execution seen for selective_bidirectional_scan_conv**."

### Iter 3's own `expert_advice.constraints[3]` (verbatim):
> "Avoid architectures with full-segment selective state-space scans or spectral full-segment branches under the 20 min trial budget."

### Then iter 3 emitted `baseline_config` for a **GRU stack** — i.e. O(T) sequential recurrence over T=40000.

The proposer **articulated its own failure in English** and then produced the architecture anyway. Iter 4 only survived because its `constraints[3]` finally named the class by a word the LLM couldn't rationalize around:
> "Avoid encoder-decoder pyramids or **recurrent/global-scan modules** in the first sweep."

Iter 4 then picked an FFT+TCN (parallel-in-T, no recurrence) — the first proposal that was architecturally compatible with a 20-min budget at T=40000.

## 3. Design Gaps (Ranked by Impact)

### Gap 1 — Gate-exhaustion feedback is English prose, not a structured architectural blacklist

`GateExhaustionInfo.summary_message` says:
> "The baseline estimated 375438.77 min wall-time vs the 20.00 min trial budget (factor 18771.94×); worst was factor 18771.94×. Verdict: the proposed architecture is too slow for the active time budget. **Reduce model depth/width or computation per step** so the next baseline lands below the budget."

**This advice is wrong for this failure mode.** The problem is not depth/width — it is *algorithmic class*. Sequential recurrence over T=40000 is infeasible at **any** depth or width given the time budget. The current `GateExhaustionInfo` schema has 14 numeric fields but no field that names the architectural pattern that blew up. The proposer cannot reliably infer *"ban recurrence over T"* from the scalar `factor=18772×`.

### Gap 2 — No pre-flight cost check at proposal time

`evaluate_time_skill` runs inside the tuner, *after* the proposer has committed. The pipeline for a single architecture is:

```
interp → propose → implement → validate → 9 failed tuner attempts (~minutes of LLM + sandbox cost) → gate aborts whole class
```

The skill itself is a static ms/step lookup. It could be surfaced as a **tool the proposer calls in its reasoning stage** on a draft `baseline_config`, with a cheap reject-and-revise loop before emit. The cost of a static estimate is negligible relative to an entire failed iteration.

### Gap 3 — `known_failures` is advisory, not prescriptive (the "I-warned-myself" pattern)

The LLM will happily articulate a warning in `known_failures` and then violate it in `baseline_config` on the same generation pass, because the two fields are not logically linked at generation time. There is no validator that cross-checks the produced `baseline_config` against the proposer's own self-declared `known_failures`.

### Gap 4 — The aggregate-window memory (Phase N) carries the symptom but not the lesson

The `[RECENT GATE EXHAUSTIONS]` block renders, for iter 2, a message like "factor=18772×, reduce depth/width." It does **not** render a structural rule like *"no recurrence when seg_size ≥ 40000."* Rule-extraction from the numeric factor is left to the LLM at propose-time — which is exactly where LLMs are weakest. The machinery that propagates feedback is correct; the *content* of the feedback is underspecified.

### Gap 5 — `segmentation_size` is a user hard constraint the proposer cannot relax

At T=40000, the feasible architectural space collapses to parallel-in-T families (TCN, attention, FFT-based). The proposer should either (a) know this arithmetically — `T × per_step_flops × batches > budget ⇒ recurrence banned` — or (b) be allowed to push back and declare *"cannot meet budget under given seg_size constraint."* Neither capability exists today.

## 4. Solution Sketch (Smallest → Largest)

### Fix 1 (Quick, ~1 commit) — Structured `disallowed_architectural_patterns`

Add a field to `GateExhaustionInfo`:

```python
class GateExhaustionInfo(BaseModel):
    ...
    # Existing 14 fields remain unchanged
    disallowed_architectural_patterns: list[str] = Field(
        default_factory=list,
        description=(
            "Architectural patterns the tuner has structurally ruled out "
            "for the active (seg_size, budget) combination. The next "
            "proposer iteration must treat these as hard bans."
        ),
    )
```

Populate it from the tuner based on the failed attempts' baseline configs. Pattern vocabulary (initial):

- `recurrent_over_T` — any RNN/GRU/LSTM over the time axis
- `scan_over_T` — selective-scan / SSM scan recurrence over time
- `dense_attention_over_T` — O(T²) attention without windowing
- `per_step_spectral_full_segment` — full-segment FFT at every layer

Render the list as a hard-banned block in the proposer's `[RECENT GATE EXHAUSTIONS]` prompt section. The proposer's `expert_advice.constraints` must then explicitly mirror each banned pattern in natural language.

**Where to detect**: inside the tuner's pre-flight gate, when `worst_time_factor > 5×` (threshold TBD), classify the attempted `baseline_config` into one or more patterns via a static analyzer (keyword match on `model_config` keys + known implementor patterns) and record them.

### Fix 2 (Medium, ~3 commits) — Proposer-side pre-flight cost check

Surface `evaluate_time_skill` as a tool callable from the proposer's reasoning stage. Flow:

1. Proposer drafts a candidate `baseline_config` in reasoning.
2. Proposer calls `evaluate_time_skill(candidate_config, seg_size, time_budget_minutes)`.
3. Skill returns `{estimated_minutes, factor, verdict}`.
4. If `factor > 1.0×`, the proposer revises and re-checks (up to N=3 inner revisions).
5. Only a passing config reaches the proposing stage's final emit.

Cost: static ms/step is a table lookup; per-call overhead is microseconds. Total budget: ≤3 inner revisions per proposal. This moves the reject-revise loop from the tuner (9 attempts × full pipeline) to the proposer (3 attempts × table lookup).

**Interface**: expose via the existing `bridge_factory` pattern so pseudo-mode tests can inject a deterministic estimator.

### Fix 3 (Bigger, ~5 commits) — Structured `ExtractedLesson` schema

Replace (or augment) `summary_message: str` with:

```python
class ExtractedLesson(BaseModel):
    banned_classes: list[str]          # mirrors disallowed_architectural_patterns
    minimum_parallelism_over_T: bool   # must the next arch be parallel-in-T?
    max_per_step_flops: float | None   # derived from time_budget / T / epochs
    max_parameters: int | None         # derived from VRAM budget
    natural_language_summary: str      # for human readers / audit logs
```

Rule-extraction happens **inside the tuner** (which has the numbers) rather than inside the proposer (which has the reasoning but not the arithmetic). The proposer then receives typed, prescriptive constraints and renders them into `expert_advice.constraints` verbatim.

### Fix 4 (Optional) — `known_failures` ↔ `baseline_config` cross-validator

Add a Pydantic model-level validator on `ProposalOutput`:

```python
@model_validator(mode="after")
def _knownfailures_not_realized(self) -> "ProposalOutput":
    for kf in self.expert_advice.known_failures:
        if _config_matches_failure_description(self.baseline_config, kf):
            raise ValueError(
                f"Proposal's baseline_config realizes a pattern that its own "
                f"known_failures[{self.expert_advice.known_failures.index(kf)}] "
                f"flagged as a risk: {kf!r}"
            )
    return self
```

Requires a classifier mapping `known_failure` text to config patterns — NLP-lite (keyword + regex per known failure class). Rejected proposals trigger a regeneration with the violated warning surfaced explicitly.

## 5. Implementation Order (Overview)

Recommended sequencing (land in this order, each fully tested before the next):

1. **Fix 1** — structured `disallowed_architectural_patterns`. Lowest risk, highest immediate impact. Closes the Phase N content gap.
2. **Fix 2** — proposer-side pre-flight cost check. Moves the reject-revise loop upstream; biggest reduction in wasted iterations.
3. **Fix 3** — `ExtractedLesson` schema. Generalizes Fix 1 into a principled contract. *(Deferred — not part of the current branch.)*
4. **Fix 4** — `known_failures` validator. Defensive hardening; only useful once Fixes 1–3 are in place. *(Deferred — not part of the current branch.)*

Each fix must land with:
- A unit test covering the new field / tool / validator in isolation.
- A pseudo-mode dual-mode integration test demonstrating the fix on a canned failure trace (extend `test_n_recent_gate_exhaustions_dual_mode.py` as a template).
- A row in `docs/resource_estimator_implement.md`'s progress-log table.

---

## 6. Branch & Immediate Scope

**Branch**: `feat/reliable-proposer-preflight` (created 2026-04-20 from `feat/phase-l-attempt-budget`).

**In scope for this branch**: Fix 1 + Fix 2 only. Fixes 3 and 4 are deferred to future branches.

**Out of scope for this branch** (see §8): iter 4 silent-death investigation, seg_size constraint relaxation, `denoising_score` metric ceiling bug.

### Landed progress (this branch)

| Commit | SHA | Subject | Files | Δ |
|--------|-----|---------|-------|---|
| 1 | `ef02dc3` | `feat(schema): add disallowed_architectural_patterns to GateExhaustionInfo` | 2 | +80 / −0 |
| 2 | `45ea78d` | `feat(tagger): architectural-pattern tagger for failed proposals` | 5 | +391 / −5 |
| 3 | _pending_ | `feat(tuner): populate disallowed_architectural_patterns on gate exhaustion` | — | — |
| 4 | _pending_ | `feat(proposer): render DO-NOT-PROPOSE block from disallowed patterns` | — | — |
| 5 | _pending_ | `feat(proposer): estimate_proposal_time static-mode wrapper` | — | — |
| 6 | _pending_ | `feat(proposer): pre-flight cost-check loop with up-to-3 revisions` | — | — |
| 7 | _pending_ | `docs: mark Fix 1 + Fix 2 landed` | — | — |

**Next up**: Commit 3 — populate `disallowed_architectural_patterns` inside the tuner's `GateExhaustionInfo` builder over every gate-rejected attempt, gated on the §7 Decision 2 thresholds (`worst_time_factor > 5.0` OR `worst_vram_factor > 2.0`).

---

## 7. Design Decisions (v1)

**Status**: Confirmed 2026-04-20 by y5ma@ucsd.edu. All four decisions below are locked for the `feat/reliable-proposer-preflight` branch and implementation has been authorized to proceed.

These decisions lock the initial shape of Fix 1 + Fix 2 for this branch. They are revisitable in future branches (specifically Fix 3 generalizes Decision 1).

### Decision 1 — Pattern-tagger vocabulary (three initial tags)

The tagger emits from a **closed vocabulary** of tags. The mechanism is rule-based keyword matching — not ML classification — so the module is named `architectural_pattern_tagger.py` with a public entry point `tag_architecture(model_type, model_config) -> list[str]`. v1 ships with:

| Tag | Heuristic trigger |
|-----|-------------------|
| `recurrent_over_T` | `model_type.lower()` contains any of `rnn`, `gru`, `lstm`, `recurrent` **OR** `model_config` has any key in `{gru_hidden_size, lstm_hidden_size, rnn_hidden_size, recurrent_hidden}` |
| `scan_over_T` | `model_type.lower()` contains any of `scan`, `ssm`, `mamba`, `s4`, `s5` **OR** (`state_dim` key present **AND** `ssm_*` key present) |
| `dense_attention_over_T` | `model_type.lower()` contains `transformer` or `attention` **AND** `model_config` has no windowing key (`window_size`, `chunk_size`, `attention_window`, `local_window`) |

**Rationale**: these three are the actually-observed failure modes in `explore_novel_v3_0420` (iter 2 = `scan_over_T`, iter 3 = `recurrent_over_T`, and `dense_attention_over_T` is pre-emptively included because the LLM will pitch it as a "solution" once recurrence is banned).

Vocabulary extensions are cheap — add a new tag + heuristic and re-ship. No schema migration needed. Fix 3 will replace this keyword-based tagger with a structured `ExtractedLesson`.

### Decision 2 — Population threshold

The tagger only contributes tags for attempts with `worst_time_factor > 5×` **OR** `worst_vram_factor > 2×`. Marginal overshoots (e.g., 1.3× time) do not ban the architectural class — they may be recoverable by reducing depth/width.

**Rationale**: an 18,772× overshoot is structural; a 1.3× overshoot is a hyperparameter choice. Banning the whole class on 1.3× would over-constrain the proposer.

Thresholds are module-level constants (not config flags) for v1. Promote to config if tuning them becomes a recurring need.

### Decision 3 — Fix 2 runs in static-only mode

The proposer's pre-flight calls `evaluate_time_skill.run_skill` with:
- `data_dir=None` → skips the real-dataset CUDA warmup entirely
- Synthesized `sample_set` representative of the active scope (20 files × 2 PSDs for snapshot × trial_portion=0.1)
- `sandbox=None` (verified: the `sandbox` param is unused inside `run_skill`)

The skill's existing `static_formula_phase_b` fallback path does the arithmetic: `num_params × seg × batch × 6e-10 s/step × total_steps × epochs`. Cost: O(ms) per call. No GPU, no disk I/O.

**Rationale**: the proposer runs in the LLM loop — GPU warmup would cost seconds per call and couple the proposer to CUDA availability. The static formula is less accurate but sufficient for **rejecting the worst classes** (18,772× will still read as ≫1.0× under the static formula).

### Decision 4 — Commit policy

Per user preference (`feedback_commits.md`): ask before each commit, explain what changed + how it was verified, prefer many small commits. Test commands are shown and approved before being run (`feedback_show_command_before_launch.md`), and real-run testing happens **before** commit (`feedback_test_before_commit.md`).

Each commit in §9's checklist is one atomic diff with its own verification step.

---

## 8. Detailed Implementation Plan

### 8.1 Fix 1 — Structured blacklist (4 commits)

| # | Commit subject | Primary files | Verification |
|---|----------------|---------------|--------------|
| 1 | `feat(schema): add disallowed_architectural_patterns to GateExhaustionInfo` | `agent/schemas/hyperparam_tuning.py` | Unit test: field defaults to `[]`, round-trips through `model_dump`/`model_validate` |
| 2 | `feat(tagger): architectural-pattern tagger for failed proposals` | new `agent/utils/architectural_pattern_tagger.py` | Unit tests: known model names hit the right tags; unknown models return `[]`; threshold gate behaves |
| 3 | `feat(tuner): populate disallowed_architectural_patterns on gate exhaustion` | `nodes/ml_hyperparameter_tune_agent.py` | Unit tests: synthetic gate-exhausted record → populated tags; healthy record → empty list |
| 4 | `feat(proposer): render DO-NOT-PROPOSE block from disallowed patterns` | `nodes/ml_model_proposal_agent.py` + prompt template | Unit test: rendered prompt contains `[DISALLOWED PATTERNS]` header + each tag's English description |

### 8.2 Fix 2 — Proposer-side pre-flight (2 commits)

| # | Commit subject | Primary files | Verification |
|---|----------------|---------------|--------------|
| 5 | `feat(proposer): estimate_proposal_time static-mode wrapper` | new `agent/utils/proposer_preflight.py` | Unit tests: a known-overbudget config returns `factor > 1.0`; a known-feasible config returns `factor < 1.0`; no GPU/disk touched |
| 6 | `feat(proposer): pre-flight cost-check loop with up-to-3 revisions` | `nodes/ml_model_proposal_agent.py` | Integration test (pseudo mode): canned over-budget draft triggers one revision, second draft passes; emitted proposal has `factor < 1.0` |

### 8.3 Docs (1 commit)

| # | Commit subject | Primary files | Verification |
|---|----------------|---------------|--------------|
| 7 | `docs: mark Fix 1 + Fix 2 landed in reliable_resource_proposer.md` | `docs/reliable_resource_proposer.md`, `docs/resource_estimator_implement.md` | Visual diff review; progress table row added |

---

## 9. Per-Commit Checklists

Each checkbox is a pre-commit gate. Do not proceed to the next commit until every box is ticked. Mark commits with their SHA inline after landing (e.g., `- [x] land commit 1 → abc1234`).

### Commit 1 — Schema field → landed `ef02dc3`

- [x] `disallowed_architectural_patterns: list[str]` added to `GateExhaustionInfo` with `default_factory=list`
- [x] Field docstring explains: (a) what the tuner writes, (b) what the proposer reads, (c) population threshold
- [x] Unit test: default is `[]`
- [x] Unit test: `model_dump()` → JSON → `model_validate()` round-trips patterns
- [x] Unit test: existing `GateExhaustionInfo` tests still pass (backward-compat)
- [x] Test command shown to user before execution
- [x] Tests run green → user approves commit
- [x] **Known debt** — docstring referenced `agent/utils/architectural_classifier.py` (stale name); folded into Commit 2 (`45ea78d`)

### Commit 2 — Pattern-tagger module → landed `45ea78d`

- [x] `agent/utils/architectural_pattern_tagger.py` created with `tag_architecture(model_type: str, model_config: dict) -> list[str]`
- [x] Module-level constants: `TIME_FACTOR_THRESHOLD = 5.0`, `VRAM_FACTOR_THRESHOLD = 2.0`
- [x] Three tag functions: `_is_recurrent_over_T`, `_is_scan_over_T`, `_is_dense_attention_over_T` (private, individually testable)
- [x] Top-level function returns `sorted(set(tags))` — deterministic order
- [x] Module-level `ARCHITECTURAL_PATTERNS: dict[str, str]` — the tag→English-description map (single source of truth; Commit 4's renderer imports from here)
- [x] Unit test: `selective_bidirectional_scan_conv` + iter 2's config → `["scan_over_T"]`
- [x] Unit test: `dual_path_gated_gru_stack` + iter 3's config → `["recurrent_over_T"]`
- [x] Unit test: `gated_fourier_tcn` + iter 4's config → `[]` (successful arch must not be tagged)
- [x] Unit test: `transformer_base` with no window key → `["dense_attention_over_T"]`; with `window_size=128` → `[]`
- [x] Unit test: unknown model_type with no matching keys → `[]`
- [x] Unit test: every tag returned by `tag_architecture` has an entry in `ARCHITECTURAL_PATTERNS` (completeness invariant)
- [x] **Follow-up**: Commit 1's schema docstring in `agent/schemas/hyperparam_tuning.py` updated from `architectural_classifier.py` to `architectural_pattern_tagger.py` (folded into this commit)
- [x] Test command shown to user → 22 new + 126 existing tests green → user approved commit

### Commit 3 — Tuner population

- [ ] Tuner's `_build_gate_exhaustion_info` (or equivalent) calls `tag_architecture` over every gate-rejected attempt's `model_type` + `model_config`
- [ ] Threshold applied: only attempts with `worst_time_factor > 5×` OR `worst_vram_factor > 2×` contribute
- [ ] Union of tags populated on the new field; deterministic sort order preserved
- [ ] Unit test: iter-2-style synthetic records (9 × scan arch, factor=18772) → patterns == `["scan_over_T"]`
- [ ] Unit test: iter-3-style synthetic records (9 × GRU arch, factor=28) → patterns == `["recurrent_over_T"]`
- [ ] Unit test: mixed records (some scan, some GRU) → patterns == `["recurrent_over_T", "scan_over_T"]` (sorted)
- [ ] Unit test: marginal overshoot (factor=1.2×) → patterns == `[]` (threshold gate works)
- [ ] Unit test: healthy iteration (`gate_exhaustion` remains None) → unchanged
- [ ] Tests green → commit

### Commit 4 — Proposer renderer

- [ ] `[RECENT GATE EXHAUSTIONS]` prompt block extended with a `[DISALLOWED PATTERNS]` sub-section when any recent exhaustion has non-empty `disallowed_architectural_patterns`
- [ ] Each tag rendered with its English description (mapping table colocated with the renderer):
  - `recurrent_over_T` → "Avoid any RNN/GRU/LSTM or other recurrence over the time dimension at the active segmentation_size."
  - `scan_over_T` → "Avoid selective-scan / SSM / Mamba-style sequential state recurrence over the time dimension."
  - `dense_attention_over_T` → "Avoid dense (non-windowed) attention over the time dimension at the active segmentation_size."
- [ ] Tag→description map lives in `agent/utils/architectural_pattern_tagger.py` as `ARCHITECTURAL_PATTERNS` (single source of truth; tagger and renderer share it)
- [ ] Unit test: `GateExhaustionInfo` with `patterns=["scan_over_T"]` → rendered prompt contains the English description
- [ ] Unit test: empty patterns → no `[DISALLOWED PATTERNS]` block in the prompt (zero-noise when not applicable)
- [ ] Unit test: multiple patterns → all descriptions appear, deterministic order
- [ ] Existing `test_n_recent_gate_exhaustions_dual_mode.py` still passes (backward-compat for the aggregate-window block)
- [ ] Tests green → commit

### Commit 5 — `estimate_proposal_time` wrapper

- [ ] `agent/utils/proposer_preflight.py` created with:
  - `estimate_proposal_time(baseline_config, time_budget_minutes, seg_size=None, sample_set=None) -> dict`
  - Returns `{"estimated_minutes": float, "factor": float, "verdict": str, "feasible": bool}`
- [ ] Internally synthesizes a representative `sample_set` (20 files × 2 PSDs) when none provided
- [ ] Calls `evaluate_time_skill.run_skill(sandbox=None, data_dir=None, ...)` — static-formula path only
- [ ] Unit test: iter-2-style config (12-block SSM, seg=40000, epochs=10, budget=20min) → `factor > 10.0`, `feasible=False`
- [ ] Unit test: iter-4-style config (6-block TCN, seg=40000, epochs=2, budget=20min) → `factor < 5.0`, `feasible=True`
- [ ] Unit test: invalid config (missing required field) raises a clear error (not silent factor=∞)
- [ ] Unit test: no GPU required (runs on CPU-only CI), no disk I/O required
- [ ] Tests green → commit

### Commit 6 — Pre-flight revision loop

- [ ] Proposer's reasoning stage (after the LLM drafts `baseline_config`) calls `estimate_proposal_time`
- [ ] If `factor > 1.0`, the verdict + suggestion + factor are injected back into the next LLM call as a `[PRE-FLIGHT REJECTION]` block; LLM is instructed to revise
- [ ] Max 3 inner revisions per proposing-stage call; on exhaustion, emit the best-factor candidate and surface a warning to the output
- [ ] `ProposalOutput` gains an optional field `preflight_estimated_minutes: Optional[float]` + `preflight_factor: Optional[float]` for audit
- [ ] Integration test (pseudo mode, extends `test_n_recent_gate_exhaustions_dual_mode.py` pattern): canned bridge emits over-budget draft on call 1, feasible draft on call 2 → proposer emits the revised proposal; `preflight_factor < 1.0` recorded
- [ ] Integration test: canned bridge emits over-budget draft 3 times → proposer emits last draft with warning + records all three `factor` values
- [ ] Existing proposer unit tests still pass
- [ ] Tests green → commit

### Commit 7 — Docs

- [ ] In `docs/reliable_resource_proposer.md`: mark §8.1 and §8.2 commits checkboxes fully ticked with SHAs
- [ ] Add a "Landed" section at the top summarizing commit SHAs and the branch's diff stat
- [ ] Add row to `docs/resource_estimator_implement.md` progress table: `| **O — Reliable proposer pre-flight: blacklist + static-mode cost check** | 2026-04-20 | ... |`
- [ ] No code changes in this commit — docs only
- [ ] User approves doc diff → commit

---

## 10. Acceptance Criterion

Re-run `explore_novel_v3_0420` with identical seeds after commits 1–6 land. **Expected outcome**: iter 2 either (a) never emits a selective-scan architecture (Fix 1 blacklist enforced via the Phase N aggregate window) or (b) self-rejects during proposer-side pre-flight (Fix 2 `factor > 1.0` check catches it before commit). The tuner should see **≤1 gate-exhausted iteration** across a 4-iteration run, not 2.

Secondary metric: the proposer's reasoning-stage LLM call count rises by at most 3× (worst-case 3 revisions per proposal); the tuner's wasted-attempt count drops by ~9× per saved iteration.

---

## 11. Out of Scope

- Fixing the iter 4 mid-inference crash (separate failure mode, silent process death during h5py writes — needs independent root-cause work).
- Relaxing the user-imposed `segmentation_size` constraint — that is an upstream advice-authoring concern, not a proposer concern.
- The `denoising_score` metric's model-collapse ceiling bug (tracked separately — scores of ~5.97 achievable via constant class-127 output).
- Fix 3 (`ExtractedLesson` typed schema) and Fix 4 (`known_failures` validator) — deferred to a future branch once Fixes 1 + 2 have run live and we've observed which tag vocabulary extensions the proposer actually needs.
