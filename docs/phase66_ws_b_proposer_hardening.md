# Phase 6.6 WS-B — Proposer Hardening (Hardware Aware + Failure Educated)

**Status:** Design, pre-implementation.
**Author:** SIDERIUS core
**Date:** 2026-04-23
**Parent:** `docs/phase66_deterministic_vram_and_hardening.md` (WS-A landed as PR #60). This document governs the WS-B work-stream — the Proposer-side consumer of the WS-A physical-cap engine.
**Companion:** `docs/phase66_ws_a_refactor_and_cleanup.md` (paused structural refactor; orthogonal; lands as PR #1.1 after WS-B).

---

## 1. Rationale & Objectives

### 1.1 The "Neural Link" gap

WS-A delivered a deterministic VRAM engine (Evidence Gate PASS at ±0.04% training / ±0.01% inference). Every rejected tuner attempt now produces a **Memory Killer report** — a structured `MemoryKillerDetails` payload specifying the binding cap, the dominant layer, its absolute and fractional share of the predicted peak, and a calibrated suggestion (`agent/skills/evaluate_vram_skill/killer_report.py`, `agent/skills/evaluate_vram_skill/wrapper.py:517`).

**The report is currently a dead letter.** The tuner logs a `skipped_oom_risk` record and `continue`s (`nodes/ml_hyperparameter_tune_agent.py:1159–1209`). The Memory Killer payload is *generated* but never *consumed*. The downstream Proposer has no visibility into which architectures the physical engine has rejected, why, or what the active hardware cap is. As a consequence:

- **Pre-emptively**, the Proposer prompt (`nodes/ml_model_proposal_agent.py:187`) carries a stale hardcoded `<10 GB VRAM` string — a Principle-5 violation surviving from the v2 design. It is wrong on every deployment: lilab's RTX 5090 has a 25.6 GB cap (80% of 32 GB); SDSC's H100 has 76.8 GB (80% of 96 GB). The Proposer has been reasoning against the wrong ceiling for the entire Stage 2 campaign.
- **Reactively**, when the tuner rejects an architecture for being fundamentally over-budget, the next iteration's Proposer sees no evidence of that rejection. It cannot learn; it can only re-propose the same class of architecture. The WS-A audit flagged this as the single largest remaining integration gap.

### 1.2 Objectives

WS-B closes this gap along two orthogonal axes:

| Axis | Current | Target |
|---|---|---|
| **Hardware Aware** (pre-emptive) | Prompt carries hardcoded `<10 GB` | Prompt carries a `[HARDWARE CONTEXT]` block rendered from the live `HardwareContext` manifest (§3.9 of parent). Three regimes: PHYSICAL / BUDGET / PHYSICAL VETO. |
| **Failure Educated** (reactive) | Memory Killer payload dropped; no feedback channel | Each physical rejection flows through a 5-hop wire (tuner → schema → orchestrator → Proposer prompt) and surfaces as a `[PHYSICAL REJECTION]` block under the existing *Previous Failed Proposals* header. |

Additionally, §3.3 folds in the **Contract Re-Assertion** work from parent §4.1 — the Proposer's `mathematical_definition` field must now cite the non-negotiable I/O contract verbatim. This is orthogonal to the feedback loop but lands in the same prompt edits, so it ships together.

### 1.3 Non-goals

- No new schema on the VRAM skill itself. `MemoryKillerDetails` already exists and is the authoritative payload shape.
- No changes to the three-regime cap classifier in `wrapper.py` — the classifier's output is consumed verbatim.
- No Implementor-side work. Implementor hardening (variable-reference audit, tensor arithmetic guard) remains scoped to parent §4.2–4.4 and lands as its own work-stream.
- No new "typed-rejection" field on `ProposalInput`. The existing `previous_failures: List[str]` is retained — rejection strings flow into it under a reserved `[PHYSICAL REJECTION]` prefix. Rationale: keeps the Proposer's prompt renderer untouched; keeps the schema diff minimal.

---

## 2. Data Flow Architecture — The 5-Hop Wiring

### 2.1 End-to-end diagram

```
┌────────────────────────────────────────────────────────────────────────┐
│  HOP 1 — VRAM Skill generates the report                              │
│  agent/skills/evaluate_vram_skill/wrapper.py:517                      │
│                                                                        │
│  killer_report.render_*_report()                                       │
│    → MemoryKillerDetails { binding_cap, dominant_layer,                │
│        dominant_layer_bytes, dominant_fraction, per_layer, ... }       │
│    → resource_check = { feasible=False, status, verdict, suggestion,   │
│        memory_killer: MemoryKillerDetails.model_dump(),                │
│        estimated_gb, limit_gb, ... }                                   │
│  NO CHANGE — WS-A shipped this payload.                                │
└───────────────────────────────┬────────────────────────────────────────┘
                                │
                                ▼
┌────────────────────────────────────────────────────────────────────────┐
│  HOP 2 — Tuner captures failed attempts                               │
│  nodes/ml_hyperparameter_tune_agent.py:1159–1209                      │
│                                                                        │
│  CURRENT: logs skipped_oom_risk; memory_killer dropped.                │
│  NEW: ALSO append PhysicalRejection to self._physical_rejections.      │
│       Flush onto HyperparamTuningOutput at run() exit.                 │
└───────────────────────────────┬────────────────────────────────────────┘
                                │
                                ▼
┌────────────────────────────────────────────────────────────────────────┐
│  HOP 3 — Schema carries rejections on the tuner output                │
│  agent/schemas/hyperparam_tuning.py                                    │
│                                                                        │
│  NEW: class PhysicalRejection (frozen).                                │
│  NEW: HyperparamTuningOutput.physical_rejections: List[...] = [].      │
│  NEW: ProposalInput.hardware_context, ProposalInput.vram_budget_gb.    │
└───────────────────────────────┬────────────────────────────────────────┘
                                │
                                ▼
┌────────────────────────────────────────────────────────────────────────┐
│  HOP 4 — Orchestrator renders strings + threads hardware context      │
│  workflows/model_exploration.py (iteration loop)                      │
│                                                                        │
│  After each HyperparamTuningAgent.run():                               │
│    for rej in aggregate_by_architecture(out.physical_rejections):      │
│        prev_failures.append(_render_physical_rejection(rej))           │
│  On the next MLModelProposalAgent.run():                               │
│    ProposalInput(                                                      │
│      previous_failures=prev_failures,                                  │
│      hardware_context=hw_ctx,          ← NEW (B.1)                     │
│      vram_budget_gb=active_budget,     ← NEW (B.1)                     │
│    )                                                                   │
└───────────────────────────────┬────────────────────────────────────────┘
                                │
                                ▼
┌────────────────────────────────────────────────────────────────────────┐
│  HOP 5 — Proposer sees context + rejection in its user prompt         │
│  nodes/ml_model_proposal_agent.py                                     │
│                                                                        │
│  NEW: [HARDWARE CONTEXT] block injected near the top of the user      │
│       prompt (rendered from hardware_context + vram_budget_gb).        │
│  NEW: [PHYSICAL REJECTION] strings appear under the existing          │
│       "Previous Failed Proposals" header (no renderer change).         │
│  NEW: mathematical_definition field spec mandates I/O contract        │
│       citation (Contract Re-Assertion, parent §4.1).                   │
│  REMOVED: the hardcoded "<10 GB VRAM" line at :187.                    │
└────────────────────────────────────────────────────────────────────────┘
```

### 2.2 File table

| Hop | File | Current | Change | Reason |
|---|---|---|---|---|
| 1 | `agent/skills/evaluate_vram_skill/wrapper.py:517` | Populates `memory_killer` in return dict | None | WS-A shipped it |
| 1 | `agent/skills/evaluate_vram_skill/killer_report.py` | Renders `MemoryKillerDetails` + suggestion | None | WS-A shipped it |
| 2 | `nodes/ml_hyperparameter_tune_agent.py:1159–1209` | Drops `memory_killer` after logging `skipped_oom_risk` | Append `PhysicalRejection` to run-level buffer; flush at `run()` exit | This is where the dead letter dies today |
| 3 | `agent/schemas/hyperparam_tuning.py` | `HyperparamTuningOutput` has no rejection field | Add `PhysicalRejection` + `physical_rejections: List[PhysicalRejection] = []` | Typed channel tuner → orchestrator |
| 3 | `agent/schemas/proposal.py:473+` | `ProposalInput` has no hardware fields | Add `hardware_context: Optional[HardwareContext]`, `vram_budget_gb: Optional[float]` | Carries the live cap to the Proposer |
| 4 | `workflows/model_exploration.py:~578` (iter loop) | `previous_failures` wired only on code-validation failures | Also render `physical_rejections` → strings, append | Orchestrator-level translation — single owner |
| 4 | `workflows/model_exploration.py` | No formatter | New `_render_physical_rejection(rej) -> str` helper | Unit-testable string template |
| 4 | `workflows/model_exploration.py` | No hardware thread | Call `HardwareContext.get_or_create()` at iter start; thread into `ProposalInput` | Wires B.1 |
| 5 | `nodes/ml_model_proposal_agent.py:556–560` | Renders `previous_failures` under existing header | None — strings flow verbatim | No renderer change needed |
| 5 | `nodes/ml_model_proposal_agent.py:~414` (`_build_reasoning_prompt`) | No hardware block | Inject `[HARDWARE CONTEXT]` block near top | Pre-emptive ceiling visibility |
| 5 | `nodes/ml_model_proposal_agent.py:187` | Hardcoded `<10 GB VRAM` | Remove | Principle 5 violation — device literal in live code |
| 5 | `nodes/ml_model_proposal_agent.py:227` (`PROPOSAL_COMMIT_PROMPT.mathematical_definition` field spec) | "Do NOT include concrete layer dimensions" | Rewrite: mandate three-citation Golden Paragraph | Contract Re-Assertion (parent §4.1) |

### 2.3 The `PhysicalRejection` schema (Hop 3)

New class in `agent/schemas/hyperparam_tuning.py`, alongside the existing `GateExhaustionInfo` but distinct (the latter is an iteration-terminal summary; `PhysicalRejection` is per-attempt evidence):

```python
class PhysicalRejection(BaseModel):
    """One VRAM-gate rejection, captured at the moment feasible=False."""
    model_config = ConfigDict(frozen=True)

    attempt_config:    Dict[str, Any]  # pruned active_params at rejection time
    binding_cap:       Literal["vram", "compute_intensity",
                                "vram+compute_intensity"]
    dominant_layer:    str             # e.g. "attention_block_4"
    dominant_layer_gb: float
    dominant_fraction: float           # 0.0–1.0
    budget_gb:         float           # effective cap at rejection time
    estimated_gb:      float           # predicted peak
    suggestion:        str             # calibrated suggestion from killer_report
```

Added to the tuner output:

```python
class HyperparamTuningOutput(BaseModel):
    ...
    physical_rejections: List[PhysicalRejection] = Field(
        default_factory=list,
        description="One entry per VRAM-gate rejection. Consumed by "
                    "workflows/model_exploration.py and rendered into the "
                    "next iteration's Proposer prompt as [PHYSICAL REJECTION] "
                    "strings. Empty list on iterations with no infeasible "
                    "attempts — back-compat with pre-WS-B callers.",
    )
```

New fields on `ProposalInput`:

```python
class ProposalInput(BaseModel):
    ...
    hardware_context: Optional[HardwareContext] = Field(
        default=None,
        description="Live hardware manifest from core.hardware_context. "
                    "None for tests / CPU-only stubs; when present, "
                    "rendered into the [HARDWARE CONTEXT] prompt block.",
    )
    vram_budget_gb: Optional[float] = Field(
        default=None,
        description="Active operator-defined VRAM ceiling for the next "
                    "tuning iteration (trial or formal, whichever the "
                    "planner will drive). When set and lower than the "
                    "physical cap, renders as the BUDGET regime; when "
                    "higher, renders as the PHYSICAL VETO regime.",
    )
```

### 2.4 Aggregation rule — worst offender per architecture

A single failed iteration can produce up to `attempts_per_round + attempts_per_formal_round` rejections (8 under the current defaults). Feeding all of them to the Proposer would flood the prompt and dilute the signal. The orchestrator aggregates:

1. Group `physical_rejections` by `attempt_config["model_type"]` (architecture identity).
2. Within each group, select the **worst offender** — the rejection with the highest `estimated_gb / budget_gb` ratio. Ties broken by `dominant_fraction` (which layer consumed the largest share of the peak).
3. Emit one `[PHYSICAL REJECTION]` string per group.
4. If the group has `N` rejections total and all attempts on that architecture failed, the string reports `"rejected N of N attempts"` — the canonical signal that the architecture is fundamentally infeasible at the current segmentation_size.

Rationale: the Proposer does not need the fine-grained attempt log — it needs *per-architecture lessons*. The tuner's internal retry variants (depth ±1, width ±30%) all hit the same dominant-layer bottleneck; one string captures the class, not each knob twist.

---

## 3. Proposer UI/UX — The Prompt Dashboard

### 3.1 `[HARDWARE CONTEXT]` block

Rendered once per Proposer invocation, at the top of `_build_reasoning_prompt`'s user-message body (before the interpretation). Three regimes mirror the `[Hardware]` log classifier in `wrapper.py`:

**Regime A — PHYSICAL** (no operator budget set; cap is the 80% physical floor)
```
[HARDWARE CONTEXT]
Device:            NVIDIA GeForce RTX 5090
Total VRAM:        32.00 GB
Usable cap (80%):  25.60 GB
Host:              lilab
Regime:            PHYSICAL — no operator budget set; cap = 25.60 GB.
```

**Regime B — BUDGET** (operator budget set, lower than physical cap)
```
[HARDWARE CONTEXT]
Device:            NVIDIA GeForce RTX 5090
Total VRAM:        32.00 GB
Usable cap (80%):  25.60 GB
Host:              lilab
Operator budget:   20.00 GB
Effective cap:     20.00 GB
Regime:            BUDGET — operator's budget is the binding ceiling.
```

**Regime C — PHYSICAL VETO** (operator budget set above physical cap; physical wins)
```
[HARDWARE CONTEXT]
Device:            NVIDIA GeForce RTX 5090
Total VRAM:        32.00 GB
Usable cap (80%):  25.60 GB
Host:              lilab
Operator budget:   40.00 GB
Effective cap:     25.60 GB
Regime:            PHYSICAL VETO — operator budget exceeds the 80%
                   physical safety floor; the physical cap wins.
```

Regime selection logic (pure function, unit-testable):

```python
def _render_hardware_context_block(
    ctx: Optional[HardwareContext],
    vram_budget_gb: Optional[float],
) -> str:
    if ctx is None or not ctx.device_available:
        return ""  # CPU-only / test stub — no block rendered
    usable = ctx.usable_cap_gb
    if vram_budget_gb is None:
        regime, effective = "PHYSICAL", usable
    elif vram_budget_gb <= usable:
        regime, effective = "BUDGET", vram_budget_gb
    else:
        regime, effective = "PHYSICAL VETO", usable
    # render the five/seven lines above
```

**Companion instruction text** (added to `PROPOSAL_REASONING_PROMPT` after the block):

> Your baseline_config must fit within the **effective cap** shown above. The VRAM engine will reject any architecture whose predicted peak exceeds this ceiling; a rejection consumes a tuner attempt with no scored round. Size your baseline to stay comfortably below the cap (target ≤ 80% of the effective cap at baseline) so the tuner has headroom to vary batch_size and segmentation_size upward.

**Removal:** delete the hardcoded `GPU budget: target <10 GB VRAM and <100M parameters for initial exploration.` line at `nodes/ml_model_proposal_agent.py:187`. The new `[HARDWARE CONTEXT]` block replaces it. Parameter count guidance stays — it is not a device literal.

### 3.2 `[PHYSICAL REJECTION]` block

Rendered by `_render_physical_rejection(rej: PhysicalRejection) -> str` in `workflows/model_exploration.py`. Appended verbatim to `previous_failures`, so the existing Proposer renderer at `nodes/ml_model_proposal_agent.py:556–560` picks it up under its *Previous Failed Proposals (DO NOT repeat these mistakes)* header.

**Template:**

```
[PHYSICAL REJECTION] (iter {iter_index}, architecture '{model_type}')
The VRAM engine rejected {R} of {A} tuner attempts on this architecture.
Binding constraint: {binding_cap}. Dominant layer: {dominant_layer}
({dominant_layer_gb:.2f} GB — {dominant_fraction:.0%} of predicted peak).
Effective cap: {budget_gb:.2f} GB. Predicted peak: {estimated_gb:.2f} GB
(overshoot ×{estimated_gb/budget_gb:.2f}).
Worst attempted config: {compact_config_summary}.
Killer's suggestion: {suggestion}
Do not re-propose an architecture whose {dominant_layer_family} layer
dominates the peak at this segmentation_size.
```

Where:
- `{iter_index}` is the iteration number the rejection came from (e.g. `iter 2` means the Proposer reading this in iter 3 knows the lesson is one step old).
- `{R}` is the number of rejected attempts on this architecture; `{A}` is the total attempted.
- `{compact_config_summary}` is a 1-line dump of the *relevant* hyperparameters (`batch_size`, `segmentation_size`, architecture-specific critical dims). Not the full `attempt_config` dict — only the dimensions that matter to the Proposer's next decision.
- `{dominant_layer_family}` is derived from `{dominant_layer}` (e.g. `"attention_block_4"` → `"attention"`). If the family cannot be inferred, fall back to the layer name itself.

**Example rendering:**

```
[PHYSICAL REJECTION] (iter 2, architecture 'attn_unet_v3')
The VRAM engine rejected 3 of 3 tuner attempts on this architecture.
Binding constraint: vram. Dominant layer: attention_block_4
(19.40 GB — 68% of predicted peak).
Effective cap: 25.60 GB. Predicted peak: 28.50 GB (overshoot ×1.11).
Worst attempted config: batch_size=32, segmentation_size=40000,
                       d_model=512, num_heads=8.
Killer's suggestion: halve d_model or reduce num_heads to 4.
Do not re-propose an architecture whose attention layer dominates
the peak at this segmentation_size.
```

### 3.3 Contract Re-Assertion — the Golden Paragraph

Parent §4.1 mandates the Proposer cite the I/O contract explicitly in every `mathematical_definition`. WS-B lands this as a rewrite of the field spec in `PROPOSAL_COMMIT_PROMPT` (`nodes/ml_model_proposal_agent.py:227`).

**Current spec** (from the code):
> `"mathematical_definition": "Abstract architectural framework: [...] Do NOT include concrete layer dimensions, kernel sizes, or channel counts — those belong in baseline_config. Focus on the structural novelty [...]"`

**New spec:**
> `"mathematical_definition": "Must open with a three-sentence 'Golden Paragraph' that cites: (1) the forward contract verbatim — 'Input: [B, T] int64 (per-timestep ADC class indices). Output: [B, 256, T] float32 (per-timestep logits over 256 denoising classes)'; (2) the segmentation semantics — state whether the body is segment-local (no cross-segment state) or segment-cross (e.g. global attention within a segment), and whether causal masking is required; (3) the fixed dimension '256 denoising bins per time step is contract-fixed, not a hyperparameter'. After the Golden Paragraph, describe the architectural framework abstractly: key computational stages, mathematical operations, data flow. Do NOT include concrete layer dimensions, kernel sizes, or channel counts — those belong in baseline_config."`

**Why it matters.** Stage 2 attempts 1 and 2 produced Implementor code that violated the contract subtly (channel-mismatched output_conv). The Implementor is a clean-room developer; if the Proposer does not restate the contract, the Implementor's LLM may re-derive it from the architecture description and get it wrong. The Golden Paragraph is a single-point-of-truth citation the Implementor can copy-paste-check against.

**Enforcement.** A rendered-prompt unit test (§5.2) asserts that the commit-stage prompt string contains the three citation markers verbatim. Future prompt refactors cannot silently drop any of them.

---

## 4. Orchestrator Logic — `workflows/model_exploration.py`

### 4.1 Where changes land

The iteration loop at `workflows/model_exploration.py:~578` currently threads `previous_failures` as a plain list populated only from code-validation failures (line 609–610). WS-B extends this loop in three places:

1. **Iteration start** (once, before the first `iteration` increment): call `HardwareContext.get_or_create(workspace, run_name)` and hold the result.
2. **After `MLModelProposalAgent.run()`**: no change here — the call already receives `ProposalInput(previous_failures=previous_failures)`. The new `hardware_context` and `vram_budget_gb` fields get populated from §4.2 below.
3. **After `HyperparamTuningAgent.run()`**: NEW — aggregate the returned `physical_rejections` per-architecture, render via `_render_physical_rejection`, append to an accumulator that survives across iterations (so iter 3 sees iter 1's and iter 2's lessons).

### 4.2 `previous_failures` merge logic

Two sources now populate `previous_failures`:

| Source | Producer | Format | Insertion point |
|---|---|---|---|
| Code-validation failures | `_run_implementor_and_validator` inside the per-iter attempt loop | Free-form strings from the validator | Inner attempt retry loop (existing, unchanged) |
| Physical rejections | `HyperparamTuningOutput.physical_rejections` via `_render_physical_rejection` | `[PHYSICAL REJECTION]` prefixed strings | End-of-iteration, after the tuner returns |

Both land in the same `List[str]`. Ordering: **insertion order, newest last** — the existing Proposer renderer uses `enumerate(..., 1)`, so iter 1's lessons read as item 1, iter N's as item N. The Proposer sees the full timeline.

**Cross-iteration persistence:** the accumulator lives in the workflow's outer scope, not in per-iteration state. An iteration loop of N iterations therefore threads up to N-1 iterations' worth of cumulative lessons into iteration N's Proposer call. No deduplication — two identical rejections across iterations both appear, and that repetition itself is a signal (the Proposer ignored last iteration's lesson).

**Budget sourcing for `vram_budget_gb` on the Proposer side:** the orchestrator knows the tuner's `trial_vram_budget_gb` and `formal_vram_budget_gb` from the workflow's CLI args. The Proposer's baseline is gated against the *trial* budget first (consistent with how the tuner picks which budget applies per round via `plan.is_trial`), so the orchestrator passes `trial_vram_budget_gb` into `ProposalInput.vram_budget_gb` when set, else `formal_vram_budget_gb`, else `None` (falls through to the PHYSICAL regime).

### 4.3 Protocol responsibility

Per CLAUDE.md's inter-node communication principle, the orchestrator-level merging lives in the workflow, not inside the Proposer or tuner. The workflow is the only place that has visibility into all three upstream sources (code-validation failures from the implementor path, physical rejections from the tuner path, hardware context from `core.hardware_context`). Pushing any of this into the Proposer would create a hidden cross-node dependency.

The existing `local_full_context` protocol in `agent/schemas/protocols/interp_to_propose.py` gets two small additions — it already takes budget-related kwargs (`trial_time_budget_minutes`, `formal_time_budget_minutes`, `data_dir`); we add `hardware_context` and `vram_budget_gb` in the same shape.

---

## 5. Verification Plan — Evidence Gate 2.0

The verification layer has three tiers: **new WS-B-specific tests** (§5.1–5.3), **inherited invariants from parent §5** (§5.4 — must stay green), and **deferred tests** (§5.5 — scoped out under the Proposer-hardening reframe, call out explicitly so they don't get lost).

### 5.1 Unit tests (new, WS-B specific)

Three new tests, each targeting one seam of the wire:

1. **`tests/unit/workflows/test_render_physical_rejection.py`** — construct a stub `PhysicalRejection`, call `_render_physical_rejection`, assert the string contains the `[PHYSICAL REJECTION]` prefix, the `binding_cap`, the `dominant_layer` name, the `suggestion`, and the overshoot multiplier. Also test the "rejected N of N" phrasing when all attempts on the architecture failed.
2. **`tests/unit/agent/tune_ml_hyperparam_agent/test_physical_rejection_capture.py`** — stub `_run_skill("evaluate_vram_skill", ...)` to return `feasible=False` with a known `memory_killer` payload. Drive one tuner round. Assert `HyperparamTuningOutput.physical_rejections` has exactly one entry with the expected `dominant_layer`, `binding_cap`, and `suggestion`.
3. **`tests/unit/agent/ml_model_proposal_agent/test_hardware_context_block.py`** — for each of the three regimes (PHYSICAL / BUDGET / PHYSICAL VETO), construct a `ProposalInput` with the matching `hardware_context` + `vram_budget_gb`, render the reasoning prompt, and assert the correct regime label and effective-cap number appear. Also test the `ctx=None` fallback renders an empty string (no block).

### 5.2 Rendered-prompt guard — Contract Re-Assertion

**`tests/unit/agent/ml_model_proposal_agent/test_contract_reassertion.py`** — this is **parent §5.3 item 1**, inherited verbatim into WS-B scope. Render `PROPOSAL_COMMIT_PROMPT` and assert the field spec for `mathematical_definition` contains the three Golden-Paragraph citation markers: the I/O contract string (`[B, T] int64`, `[B, 256, T] float32`), the "segmentation semantics" marker, and the "256 denoising bins" clause. Parent's §5.3 version also asserts `segmentation_size` and `causal mask` are named — both requirements carried forward unchanged.

This is the single mechanical guard against a future prompt refactor silently dropping the Golden Paragraph.

### 5.3 VRAM-Awareness End-to-End Test

A Tier-2 integration smoke (dual-mode, pseudo by default, `--real-api-call` opt-in):

**`tests/integration/workflows/test_vram_awareness.py`** — two-iteration workflow:

1. **Iteration 1 setup.** Seed an interpretation whose take-home message implies an oversized architecture is reasonable (e.g. "the bottleneck is low-frequency recovery, need large receptive field"). Stub the tuner to return `HyperparamTuningOutput` with `physical_rejections=[one oversized attention architecture]` and `best_denoising_score=None` (no round scored).
2. **Iteration 2 assertion.** Capture the second iteration's `MLModelProposalAgent.run()` input. Assert:
   - `previous_failures` contains exactly one `[PHYSICAL REJECTION]` string referencing the iter-1 architecture and its dominant attention layer.
   - `hardware_context.device_available` is True (the orchestrator called `get_or_create`).
   - The rendered reasoning prompt contains the `[HARDWARE CONTEXT]` block with the correct regime.
3. **Behavioral assertion (real-mode only).** In `--real-api-call` mode, also assert the iter-2 `ProposalOutput.baseline_config.model_config` carries a *smaller* dominant-layer hyperparameter than iter-1's rejected config (e.g. `d_model` ≤ half of the rejected value, or `num_heads` reduced). This is the "Proposer is actually listening" check — the unit tests prove the strings flow; this test proves the LLM reads them.

The real-mode behavioral assertion is inherently probabilistic (one LLM sample). Threshold: the assertion passes if the dominant hyperparameter decreased at all; it fails only if the Proposer re-proposed the same or larger value. A single pass is sufficient evidence — the goal is not statistical characterization, but a regression trip-wire for future prompt edits that accidentally suppress the signal.

### 5.4 Inherited invariants from parent §5 (must stay green)

WS-B touches the Proposer's prompt layout and the tuner→orchestrator→Proposer wire. It does *not* touch the VRAM physics engine or the guardrail-protected invariants. The following must all stay green after every WS-B commit:

**5.4.1 Evidence Gate (parent §5.2).** Training 0.8228 GB predicted / 0.8231 GB measured (−0.04%), inference 0.4211 / 0.4212 (−0.01%). Regression: re-run `docs/phase66_telemetry/evidence_gate_dynamic_depth_simple.py`; bytes must match Appendix A.2 verbatim. WS-B makes no composition-layer changes, so any residual drift indicates an accidental upstream edit.

**5.4.2 Guardrail `test_no_model_name_branches.py` (parent §5.4).** Scans `agent/skills/evaluate_vram_skill/`, `agent/skills/training_skill/estimator.py`, `agent/skills/inference_skill/estimator.py`, `core/inference_defaults.py` for model-family tokens (`wavenet`, `punet`, `fcnet`, `rnn`, `transformer`, `cnn`). Three items remain xfailed (`training_estimator`, `inference_estimator`, `inference_defaults`) pending the paused A.6/A.7/A.9 cleanup in the WS-A follow-up doc — not WS-B's concern, but any new model-name string introduced by WS-B's prompt edits (e.g. "for CNN architectures, prefer…") will flip the evaluate_vram_skill scan red. WS-B prompts must use generic phrasing per Principle 2.

**5.4.3 Guardrail `test_no_hardcoded_device_literals.py` (parent §5.1).** Scans `core/`, `agent/`, `nodes/` for device tokens (`5090`, `A100`, `V100`, `H100`, `32 GB`, `25.6`). Currently fully green. WS-B's B.2 removes the `<10 GB` literal at `nodes/ml_model_proposal_agent.py:187` — this is the *positive* side of the guardrail for WS-B: the literal is a violation today (masked only because `<10 GB` doesn't match the pattern, but the spirit of Principle 5 covers it). The replacement `[HARDWARE CONTEXT]` block renders numbers from `HardwareContext.usable_cap_gb` at prompt-assembly time; the block's template string itself must not carry any device literal. Any accidental regression (e.g. a developer hardcoding "25.60 GB" as a fallback string when `ctx is None`) will be caught by this guardrail.

**5.4.4 Wrapper return-dict contract.** `test_wrapper_contract.py` pins the `memory_killer` payload shape. WS-B consumes the payload via `PhysicalRejection.model_validate`; any schema drift in the VRAM skill would break Hop 2's ingestion. The contract test is the canary.

### 5.5 Deferred from parent §5.3 (out of scope under the Proposer-hardening reframe)

The parent doc's §5.3 specified four WS-B tests. Under the pre-WS-B audit and strategic redirection, WS-B's scope tightened to Proposer-side hardening (hardware awareness + physical-rejection feedback loop + Contract Re-Assertion). Implementor-side hardening (parent §4.2–4.4) was split off as a separate work-stream. The following parent-§5.3 items therefore land with the Implementor stream, not here:

| Parent §5.3 item | File | Lands with |
|---|---|---|
| Item 2 — Reasoning-prompt rules test | `tests/unit/nodes/ml_model_implementor/test_reasoning_prompt_rules.py` | Implementor hardening (parent §4.2 Variable-Reference Audit + §4.3 Tensor Arithmetic Guard) |
| Item 3 — Repair-prompt AttributeError test | `tests/unit/nodes/ml_model_implementor/test_repair_prompt_attributeerror.py` | Implementor hardening (parent §4.4) |
| Item 4 — Stage 2 iter_001 regression replay | `tests/integration/workflows/test_implementor_regression.py` | *Spans both streams.* The original WS-B design positioned this as "the observable success signal for WS-B" (parent §5.3). Under the reframe, passing this test on first attempt requires both Proposer-side fixes (Contract Re-Assertion Golden Paragraph, from this doc) *and* Implementor-side fixes (Variable-Reference Audit + Tensor Arithmetic Guard, from the other stream). It lands in the Implementor stream's PR, with this doc's §5.2 listed as a prerequisite. |

These deferrals are tracked — not dropped. The WS-B PR (#2 per this doc) will include a note pointing at the Implementor-hardening PR (numbered later) for item 4. If the Proposer-hardening lands but the Implementor-hardening does not, `test_implementor_regression.py` will continue to fail in the same way it does today; it is not a regression introduced by WS-B.

---

## 6. Checklist & Implementation Sequencing

**Legend:** `[ ]` = not started · `[~]` = in flight · `[x]` = landed.

### 6.1 Sequencing rationale

The four tasks are not independent. Land order matters because later tasks reference data the earlier tasks wire up:

1. **B.1 first.** Schema additions are the typed contract; everything else threads through them. Smallest blast radius, no prompt changes yet, reversible.
2. **B.3 next** (not B.2). The feedback loop depends on B.1's schema. It is the single highest-leverage change — closing the dead letter. Landing it before B.2 means the feedback is already flowing when the Proposer starts seeing hardware context.
3. **B.2 third.** Prompt-level rendering of the hardware context. Depends on B.1's `ProposalInput` fields being in place. Low risk; one file.
4. **B.4 last.** Pure prompt edit for Contract Re-Assertion. Orthogonal to the feedback loop; could land anytime after B.2, but grouping it into WS-B keeps the Proposer-side edits in one PR.

Each is a single commit with its own focused test. Estimated ship: four commits, one PR.

### 6.2 Checklist

- [x] **B.1 — Schema + hardware thread.** *(landed as commit `2d62cc6` on `feat/deterministic-vram`; Level 0 REPL + Level 1 pytest 162/162 green)*
  - [x] Add `PhysicalRejection` model to `agent/schemas/hyperparam_tuning.py`.
  - [x] Add `physical_rejections: List[PhysicalRejection] = []` to `HyperparamTuningOutput`.
  - [x] Add `hardware_context: Optional[HardwareContext]` and `vram_budget_gb: Optional[float]` to `ProposalInput` in `agent/schemas/proposal.py`.
  - [x] ~~Update `local_full_context` in `agent/schemas/protocols/interp_to_propose.py`~~ → **Deviation:** protocol file (actual name: `agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py`) left untouched; orchestrator assigns `hardware_context` and `vram_budget_gb` **post-hoc** on the `ProposalInput` returned from `local_full_context`, mirroring the existing `previous_failures` / `mindset` pattern at the propose call site. Rationale: the two new fields are orchestrator-level context (not interpretation-derived), so forcing them through the protocol's signature would couple the interpretation→proposal edge to workflow-level state for no structural benefit. Three files changed instead of four; protocol tests pass unmodified.
  - [x] Thread `HardwareContext.get_or_create()` through `workflows/model_exploration.py` so the iter loop produces a live manifest and passes it on every `ProposalInput` construction.
  - [x] Tests: Level 1 pytest covers protocol back-compat (unchanged signature still produces valid `ProposalInput` with `hardware_context=None`, `vram_budget_gb=None`); `PhysicalRejection` round-trip + frozen-mutation assertion covered by Level 0 REPL. Dedicated unit test for `PhysicalRejection` roundtrip deferred to B.3 where it is first populated in production.

- [x] **B.3 — Physical-rejection feedback loop.** *(landed as commit `870ca41` on `feat/deterministic-vram`; dry-run evidence /tmp/ws_b_b3_dryrun.py shows 3-rejection → 2-group aggregation + correct `[PHYSICAL REJECTION]` render in iter-2 Proposer prompt)*
  - [x] **Hop 2 — tuner capture.** `nodes/ml_hyperparameter_tune_agent.py` imports `PhysicalRejection` + `ValidationError`; initialises `physical_rejections_buffer: list[PhysicalRejection] = []` at iteration-loop start; appends one entry inside the `resource_check.get("feasible") is False` branch (reads `memory_killer` sub-dict, snapshots `active_params` as `attempt_config` incl. `model_type`, `batch_size`, `segmentation_size`, and detected architecture knobs `depth/width/hidden_dim/n_heads/d_model/kernel_size/num_layers`); flushes buffer into `HyperparamTuningOutput.physical_rejections` at `run()` exit. Malformed rejections are logged and skipped (best-effort contract).
  - [x] **Hop 4 — orchestrator aggregation + seeding.** `workflows/model_exploration.py` imports `PhysicalRejection`; adds module-level `_aggregate_worst_offender_rejections(rejections) -> list[tuple[PhysicalRejection, int]]` (group-by `attempt_config["model_type"]`, worst by `estimated_gb / budget_gb` ratio, tiebreak by `dominant_fraction`; `budget_gb == 0` → `+inf`) and `_render_physical_rejection(rej, n_rejections) -> str` (multi-line `[PHYSICAL REJECTION]` block with worst-offender stats, dominant layer when present, attempted config, suggestion). At iteration-loop start — right after `previous_failures: list[str] = []` — pulls `iteration_results[-1].physical_rejections` from the prior iteration, aggregates, renders, and seeds `previous_failures`. No-op on iteration 1 / zero-rejection iterations.
  - [x] **Validation dry-run** (/tmp/ws_b_b3_dryrun.py): 3 simulated rejections across 2 architectures (`deep_punet` x2, `wide_transformer` x1) → aggregator correctly picks the worst `deep_punet` attempt (29.10 GB / 20.00 GB ratio 1.46, dropping the milder 22.40 GB attempt) and the sole `wide_transformer` compute-intensity attempt. Iter-2 user prompt (33 lines): `[HARDWARE CONTEXT]` block x1, `[PHYSICAL REJECTION]` block x2, correct placement inside the "Previous Failed Proposals (DO NOT repeat these mistakes)" section, compute-intensity path correctly suppresses the Dominant-layer line when `dominant_layer=""`.
  - [x] **§5.1 test 1 landed** — `tests/unit/workflows/test_render_physical_rejection.py` (16 cases: worst-offender aggregation by ratio, tie-break by `dominant_fraction`, `budget_gb=0 → +inf`, missing-`model_type` → `unknown`, `dominant_layer=""` suppression for compute-intensity path, singular/plural phrasing). All 16 green.
  - [x] **Pseudo-mode E2E smoke** — `tests/integration/workflows/test_vram_awareness.py` pseudo-mode passed (0.93 s) — iter-2 ProposalInput captured via `_CapturingProposer` shows `[HARDWARE CONTEXT]` BUDGET regime + `[PHYSICAL REJECTION]` block with `deep_punet` / 29.10 GB / dominant layer `encoder.attention.block7.mha` surfaced verbatim into the Proposer prompt.
  - [x] **§5.1 test 2 landed** — `tests/unit/agent/tune_ml_hyperparam_agent/test_physical_rejection_capture.py` (7 cases: single-OOM capture with expected `dominant_layer`/`binding_cap`/`suggestion` per the spec, `attempt_config.model_type` populated, 3 sequential OOMs preserved in encounter order, missing-`memory_killer` defaults applied, feasible runs emit empty buffer, `dominant_layer_bytes → dominant_layer_gb` conversion exact at 1 GiB and correctly rounded to 4 decimals at 2.5 GB). 7/7 green in 4.92s. Harness mirrors `test_per_round_attempt_budget.py` with an added `get_or_create` patch so the run never touches real CUDA. `max_fail_rounds` is set to match the rejection count exactly — otherwise the tuner's generic `except Exception` swallows a schedule-exhausted `IndexError` and `time.sleep(5)`s per remaining fail-slot (empirically ~45s per test without this).
  - [ ] **Real-mode B.5** still pending (separate PR task).

- [x] **B.2 — `[HARDWARE CONTEXT]` block + literal removal.** *(landed as two commits: B.2a renderer + B.2b literal-removal)*
  - [x] **B.2a — renderer landed.** Commit `2029eda` on `feat/deterministic-vram`. `_render_hardware_context_block(ctx, vram_budget_gb) -> str` in `nodes/ml_model_proposal_agent.py` matches §3.1 regime-selection logic verbatim; companion instruction text appended inline. Uses `ctx.hostname` (actual field name) — §3.1 template literal `Host:` is rendered from `ctx.hostname`.
  - [x] **Injection at top of `_build_reasoning_prompt`.** Level 2 dry-run output: lines 1–10 of user prompt carry the block; 29-line total prompt, 1 occurrence of `[HARDWARE CONTEXT]`, BUDGET regime correctly selected when `vram_budget_gb=20.0 < usable_cap_gb=25.60`.
  - [x] **B.2b — literal removal.** Replaced the hardcoded `GPU budget: target <10 GB VRAM and <100M parameters for initial exploration.` line in `PROPOSAL_REASONING_PROMPT` with a pointer to the `[HARDWARE CONTEXT]` block's "Effective cap"; kept the parameter-count `~100M` guidance per §3.1 ("Parameter count guidance stays — it is not a device literal"). Guardrail `test_no_hardcoded_device_literals` **3/3 green** (core / agent / nodes). Note: the guardrail's regex does not currently catch the `<10 GB` token pattern (scans `5090|A100|V100|H100|32\s*GB|25.6`), so the removal is a positive Principle-5-spirit compliance cleanup, not a test-driven fix.
  - [x] **B.2c landed.** Second `<10 GB VRAM` occurrence in `PROPOSAL_COMMIT_PROMPT` (hard-constraint list for baseline_config, line 264) replaced with a pointer to the `[HARDWARE CONTEXT]` block's effective cap: `- baseline_config must be conservative: fits comfortably within the effective cap shown in the [HARDWARE CONTEXT] (the VRAM gate rejects anything above it)`. No device literals remain in either prompt string. Targeted pytest (389 cases across `tests/unit/agent/ml_model_proposal_agent/` + `tests/unit/workflows/test_render_physical_rejection.py`) stays green after the edit.
  - [x] **§5.1 test 3 landed** — `tests/unit/agent/ml_model_proposal_agent/test_hardware_context_block.py` (16 cases: BUDGET / PHYSICAL / PHYSICAL VETO regime selection, `ctx=None` + `device_available=False` fallback → empty string, trailing instruction text parametrized across all three regimes). Boundary case `budget == usable_cap` passes `ctx.usable_cap_gb` verbatim rather than the literal `25.6` to sidestep the `int(0.80 * 32*1024**3) / 1024**3` float epsilon. All 16 green.

- [x] **B.4 — Contract Re-Assertion (Golden Paragraph).** *(landed as commit `3d357cb` on `feat/deterministic-vram`; audit dry-run /tmp/ws_b_b4_dryrun.py confirms all 9 marker checks pass)*
  - [x] Rewrote the `mathematical_definition` field spec in `PROPOSAL_COMMIT_PROMPT` verbatim per §3.3. Three citation markers confirmed present: (1) forward contract (`[B, T] int64` / `[B, 256, T] float32`), (2) segmentation semantics (`segment-local`, `segment-cross`, `causal masking`), (3) fixed-dimension clause (`256 denoising bins` + `contract-fixed`). Existing "Do NOT include concrete layer dimensions" + `belong in baseline_config` guardrails preserved. Field spec length: 777 chars (up from 342).
  - [x] **§5.2 rendered-prompt guard landed** — `tests/unit/agent/ml_model_proposal_agent/test_contract_reassertion.py` (13 cases across 5 classes: forward-contract citation, segmentation-semantics citation, fixed-dimension clause with a co-occurrence regex pinning `256 denoising bins` + `contract-fixed` in the same clause, preserved pre-WS-B guardrails, Golden-Paragraph header literal + ≥600-char length guard). All 13 green.

- [ ] **B.5 — VRAM-Awareness end-to-end test.**
  - Implement `tests/integration/workflows/test_vram_awareness.py` per §5.3.
  - Verify pseudo mode passes in CI; verify real mode passes locally on lilab.

- [ ] **B.6 — Regression + PR.**
  - Re-run the WS-A evidence gate (`docs/phase66_telemetry/evidence_gate_dynamic_depth_simple.py`) and confirm Appendix A.2 bytes unchanged.
  - Re-run the guardrail suite (`tests/unit/guardrails/`) — `test_no_hardcoded_device_literals` stayed green through the WS-B edits (the `<10 GB` literal at :187 was removed in B.2b / commit `e935a12`, though note the regex does not actually match that token pattern).
  - Open PR #2 with all B.1–B.5 commits.

### 6.3 Mapping from parent §7's B.1–B.8

The parent doc's §7 checklist listed B.1–B.8 as the original WS-B scope. The pre-WS-B audit and reframe reshuffled this: WS-B now owns the Proposer-side hardening (this doc's B.1–B.6), while Implementor-side hardening moves to a separate later stream. Mapping:

| Parent §7 item | Parent §§ | Lands where |
|---|---|---|
| B.1 Contract Re-Assertion | §4.1 | **This doc — B.4** (absorbs parent §4.1 verbatim; adds Golden Paragraph formalization) |
| B.2 Variable-Reference Audit | §4.2 | Implementor stream (future PR) |
| B.3 Tensor Arithmetic Guard | §4.3 | Implementor stream (future PR) |
| B.4 AttributeError repair clause | §4.4 | Implementor stream (future PR) |
| B.5 Rendered-prompt unit tests | §5.3 items 1–3 | Split — item 1 is this doc's §5.2; items 2–3 are Implementor stream |
| B.6 Regression replay | §5.3 item 4 | Implementor stream (requires both fixes to pass; see §5.5) |
| B.7 Guardrail re-verification | §5.4 / §5.1 | This doc's §5.4 (continuous invariant) |
| B.8 Self-review + open PR | — | This doc's B.6 for the Proposer-side PR; Implementor stream owns its own |

Net: this doc is authoritative for Proposer-side WS-B. Parent §4 and §5.3 remain authoritative for Implementor-side WS-B until that stream gets its own governing doc.

### 6.4 Out of scope for WS-B (explicit deferrals)

- **WS-A refactor cleanup** (`docs/phase66_ws_a_refactor_and_cleanup.md` — A.6/A.7/A.9/A.15/A.16). Ships as PR #1.1 after WS-B merges.
- **Implementor hardening** (parent §4.2–4.4 — variable-reference audit, tensor arithmetic guard, targeted AttributeError repair). Separate work-stream.
- **Typed-rejection field on `ProposalInput`.** Rejected — reusing `previous_failures: List[str]` with a `[PHYSICAL REJECTION]` prefix keeps the prompt renderer untouched and avoids a schema ratchet whose only consumer is this one feedback path.
- **Deduplication of repeated rejections across iterations.** Intentionally absent — a repeat rejection *is* a signal that the Proposer ignored the lesson, and suppressing it would hide that.
- **Static AST analysis of proposed architectures against the VRAM engine's class library.** Out of scope; the VRAM skill itself is the single source of truth for what fits.

---

## 7. Invariants

WS-B must not:

- Change the WS-A Evidence Gate numbers (parent Appendix A.2). Training residual stays at −0.04%, inference at −0.01%.
- Introduce any model-name branch (parent §5.4 guardrail).
- Introduce any device literal in live code (parent §5.1 guardrail). Removing the `<10 GB` literal at :187 is the *positive* side of this invariant for WS-B.
- Change the `HardwareContext` schema or the `_SAFETY_FRACTION = 0.80` constant (§3.9.1 of parent).
- Change the `memory_killer` return-dict shape at `wrapper.py:517`. WS-B consumes it verbatim.
- Change the `[Hardware]` log-line regime classifier. The `[HARDWARE CONTEXT]` prompt block mirrors the classifier's semantics but is a separate renderer; the two must never disagree, and a unit test could assert they stay in sync if that becomes a real risk.
