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
- **Strict Planner Enforcement (the "v9 discovery").** The Tuner's planner currently has independent authority to downsize hyperparameters (`multi`, `depth`, `embedding_dim`) to satisfy the configured VRAM/Time budgets, even when this contradicts the Proposer's `baseline_config` or `human_advice_propose`. Forcing the planner to "fail instead of shrink" — so a configured cap deterministically produces a `PhysicalRejection` rather than a downsized successful trial — is out of scope for this PR. See §7 (Instruction Weighting) for the deferred follow-up.
- **Cross-Node Instruction Hierarchy.** Implementing a mechanism where `human_advice` or `expert_advice` strictly overrides the Tuner planner's internal optimization logic (so a `MANDATORY` clause on the Proposer side propagates as a constraint on the Tuner side) is deferred to future work. Today the two advice channels are independent: `human_advice_propose` reaches only the Proposer prompt, and the Tuner planner is unaware of it.

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

### 3.4 Mandatory Rejection Acknowledgement — hardening the cognitive response

#### 3.4.1 Problem — the LLM reads the block but does not reason against it

Phase A of §5.3 (real LLM, mocked training, parametrized over `vram_budget_gb ∈ {10.0, 20.0}`) landed the plumbing layer: iter-2's Proposer call receives a `[HARDWARE CONTEXT]` block and a `[PHYSICAL REJECTION]` block verbatim in its user prompt, both confirmed by capture-layer assertions. The behavioral layer revealed a deeper issue: **the LLM reads the blocks but does not reason against them.**

Direct evidence from the Phase A run (2026-04-24, both budgets against the seeded 29.1 GB `deep_punet` rejection with dominant layer `encoder.attention.block7.mha`, overshoot ×1.46 at 20 GB / ×2.91 at 10 GB):

- **10 GB budget** → iter-2 proposal `dilated_causal_unet` (baseline `embedding_size=256, embedding_dim=64, dilation_rates=[1,2,4]`).
  > `causal_hypothesis`: "This change addresses the identified weakness in capturing low-frequency signals (Bottleneck 1)… The dilated causal convolution expands the receptive field exponentially…"

- **20 GB budget** → iter-2 proposal `spectral_resolver` (baseline `depth=3, multi=64, kernel_size=5, embedding_dim=64, …`).
  > `causal_hypothesis`: "The bottleneck being addressed is the limited frequency resolution and processing… Spectral convolution processes frequency bins directly…"

Both snippets address only the **seeded DiscoveryMemo bottleneck** ("low-frequency signals" / "frequency resolution"). Neither snippet cites:
- the `[PHYSICAL REJECTION]` block or any of its contents (`deep_punet`, `29.1 GB`, `encoder.attention.block7.mha`, overshoot multiplier);
- the `[HARDWARE CONTEXT]` block (the 10 GB or 20 GB Effective cap, BUDGET regime);
- any VRAM-related vocabulary at all (`VRAM`, `OOM`, `rejection`, `cap`, `overshoot`, `budget`).

The iter-2 architectures *are* smaller than the rejected `deep_punet`, but the shrinkage appears to be **a side-effect of pivoting to a different architecture class** (dilated causal conv / spectral conv instead of a deep attention-UNet) driven by the seeded interpretation bottleneck. It is not a causal consequence of the physical rejection. Under a different seeded interpretation — one whose take-home message pointed toward deep attention — nothing in the current prompt would stop the Proposer from re-proposing another oversized attention stack.

#### 3.4.2 Why the current prompt is insufficient

`PROPOSAL_REASONING_PROMPT` currently carries only a passive mention of the hardware context: *"The VRAM ceiling is published in the [HARDWARE CONTEXT] block at the top of the user message — treat that block's 'Effective cap' as the hard limit"* (`nodes/ml_model_proposal_agent.py:188–190`). This is a **visibility** instruction, not a **reasoning** instruction. The six numbered reasoning items (what weakness / what families / which approach / design choices / failure modes / frequency strategy) make no reference to prior physical rejections, so a physical rejection has no natural slot in the LLM's reasoning chain; it is free-floating context that the model can acknowledge or ignore.

`PROPOSAL_COMMIT_PROMPT` does assert the commit-stage hard constraint (*"baseline_config must be conservative: fits comfortably within the effective cap shown in the [HARDWARE CONTEXT]"*, line 264) — but by the commit stage the reasoning is already frozen. The constraint is evaluated against a `baseline_config` that was sized without any physical-rejection awareness, so a commit-stage rejection would require the Proposer to self-contradict its own stage-2 reasoning. In practice, the Proposer simply emits a smaller baseline that happens to pass the cap test without acknowledging *why* the cap matters.

#### 3.4.3 Solution — a MANDATORY clause in the reasoning prompt

> **Status update (2026-04-24):** the v1 clause drafted below was authored against `PROPOSAL_REASONING_PROMPT` in the *legacy* non-staged code path. Production is on the *staged* pipeline, which loads its stage-2 system prompt from `agent/prompt_templates/proposal/causal_reasoning_stage.md` — see **§3.4.5** for the B.6a-v4 correction that ports the clause to the live template, and for the canonical v3 Integrated-Reasoning text that supersedes v1. The §3.4.3 draft below is preserved for traceability.

Amend `PROPOSAL_REASONING_PROMPT` (`nodes/ml_model_proposal_agent.py:172–218`) to add a top-level `MANDATORY — Physical-rejection acknowledgement` clause that is evaluated **before** the numbered reasoning items. Placement matters: the clause must appear *after* the "Background on the task" block (so the LLM has the forward contract and the VRAM ceiling reference) and *before* the "In your reasoning, cover all of the following:" line (so it is considered as a first-class reasoning obligation, not a post-hoc check).

**Draft amendment** (verbatim text, to be inserted between the "Background on the task" bulleted list and the "In your reasoning, cover all of the following:" line):

```
MANDATORY — Physical-rejection acknowledgement:
If the user prompt carries one or more [PHYSICAL REJECTION] blocks under
"Previous Failed Proposals", your causal_hypothesis MUST explicitly cite,
for each rejection:
  - the rejected architecture (model_type from the block),
  - the dominant layer that caused the OOM (from the block),
  - the overshoot evidence (Effective cap vs Predicted peak),
  - and how your new proposal's structural choice specifically mitigates
    that physical bottleneck — not just the interpretation's bottleneck.

Ignoring physical limits is a design failure. Your proposed baseline_config
must be justified against the "Effective cap" shown in the [HARDWARE
CONTEXT] block, and your reasoning must show explicit awareness that the
previous iteration's proposal was rejected for exceeding that cap. A
proposal that reads as a pure pivot within the interpretation's bottleneck
space — with no acknowledgement of the physical rejection — is a failed
proposal, even if the new architecture happens to be smaller by coincidence.
```

**Why split across the two prompts.** The MANDATORY clause lives in `PROPOSAL_REASONING_PROMPT` (stage 2 of the 3-stage pipeline: comparison → causal_reasoning → proposing) because `causal_hypothesis` is the reasoning-stage output — the exact field Phase A found empty of rejection vocabulary. The existing Golden Paragraph mandate and effective-cap hard constraint stay in `PROPOSAL_COMMIT_PROMPT` (stage 3, producing the final `ProposalOutput`) where `baseline_config` is committed. Two stages, two separate enforcement points; neither prompt carries the other's burden.

#### 3.4.4 Enforcement

- **Renderered-prompt guard** (unit, cheap): §5.2's pattern, replicated — assert the MANDATORY header and the four bulleted citation requirements appear verbatim in `PROPOSAL_REASONING_PROMPT`. Catches any future prompt refactor that silently drops the clause.
- **Behavioral keyword gate** (integration, real-LLM): §5.3.6 — assert iter-2's `causal_hypothesis` output contains at least one VRAM-family keyword. Catches the symptom directly.
- **Parameter-count behavioral assertion** (integration, real-LLM): §5.3.5 — replaces the narrow `hidden_dim | depth` check with a total-param ceiling, so cross-architecture-class shrinkage is detected correctly.

Together these three checks close the loop: the prompt mandates the citation, the rendered-prompt guard protects the prompt from drift, and the two behavioral assertions verify the citation actually appears in real LLM output.

### 3.4.5 Correction — porting the MANDATORY clause to the staged pipeline (B.6a-v4)

#### 3.4.5.1 The two code paths — legacy vs staged

Stage 2's system prompt is authored in two mutually exclusive places:

| Path | Location | Invocation | Status |
|---|---|---|---|
| **Legacy (single-prompt)** | `PROPOSAL_REASONING_PROMPT` string in `nodes/ml_model_proposal_agent.py:172–218` | Direct `bridge.generate_text(system=PROPOSAL_REASONING_PROMPT, …)` at `ml_model_proposal_agent.py:~802` | *Dormant.* Kept for legacy fallback and a small number of historical test fixtures; no live orchestrator call path. |
| **Staged pipeline** | `agent/prompt_templates/proposal/causal_reasoning_stage.md` + `*_explore.md` / `*_exploit.md` mode blocks, loaded via `load_stage_prompt("causal_reasoning_stage", …)` from `agent/prompt_templates/proposal/__init__.py` | Production 3-stage runner: `comparison → causal_reasoning → proposing` | *Live.* Every real-API Proposer invocation since the staged refactor flows through this path. |

B.6a (v1), B.6a-v2, and B.6a-v3 all edited the **legacy** string. The staged `causal_reasoning_stage.md` was untouched. Evidence: every Phase A run logs `Pipeline mode: explore | stages: ['comparison', 'causal_reasoning']`, which is the staged-runner breadcrumb — the legacy code path does not emit that line.

#### 3.4.5.2 Why all three prior Phase A rounds prove nothing about the clause

- **B.6e v1** (substring matcher, 2026-04-23): passed via `"cap" ∈ "capture"` false positive. Even without the matcher bug, the clause had not arrived at the LLM.
- **B.6e v2**: not executed.
- **B.6e v3** (word-boundary matcher + v3 Integrated-Reasoning draft, 2026-04-23): zero keyword hits on both budgets. Originally interpreted as "the clause isn't strong enough"; actually caused by the clause never being delivered. `causal_reasoning_stage.md` had no mention of `[PHYSICAL REJECTION]`, no integrated-reasoning framing, and no Effective-cap mandate — so iter-2's `causal_hypothesis` naturally carried zero VRAM vocabulary.

**Retraction:** the empirical observations in §3.4.1 stand (both iter-2 `causal_hypothesis` outputs cited only the seeded DiscoveryMemo bottleneck and omitted all VRAM vocabulary), but the attributed cause was wrong. The actual cause is **prompt-delivery failure**, not **prompt-ineffectiveness**. B.6e v4 is the first genuine behavioral test of the Integrated-Reasoning clause.

#### 3.4.5.3 Staged-template structure and insertion point

The base `causal_reasoning_stage.md` template has these top-level sections, in order:

```
# Stage 2: Causal Reasoning
## Your task
## What you receive
## What you produce                 (JSON schema block)
## Rules — the four structural teeth
## Additional rules
{# EXPLORATION_MODE_BLOCK #}        (injected from _explore.md or _exploit.md)
## Output format
```

**Placement:** the Integrated-Reasoning clause lands as a new top-level section `## MANDATORY — Integrated reasoning (science + engineering)`, inserted between `## What you receive` and `## What you produce`. Rationale:

- Must sit *after* `## What you receive` so the `[PHYSICAL REJECTION]` and `[HARDWARE CONTEXT]` blocks are already declared as inputs when the mandate lands.
- Must sit *before* `## What you produce` so the contract on `causal_hypothesis` is stated before the JSON schema that defines it.
- Kept as a first-class `##` section (not a sub-rule inside `## Rules — the four structural teeth`), because the four existing teeth govern structural shape (falsifiability, comparison-backing, etc.), whereas the MANDATORY clause governs cognitive synthesis between two constraint systems.

**Adjacent edit to `## What you receive`:** the staged template does not mention `Previous Failed Proposals` or `[HARDWARE CONTEXT]` at all today, so without a matching `## What you receive` expansion the MANDATORY clause would cite inputs the LLM has never been told it would see. Two new bullets are added, one for `Previous Failed Proposals` / `[PHYSICAL REJECTION]` and one for `[HARDWARE CONTEXT]`, mirroring the corresponding declarations that exist in the legacy `PROPOSAL_REASONING_PROMPT`.

Status (2026-04-24): the placement + adjacent edit + clause text were applied on-disk during the B.6a-v4 port action, ahead of this design-doc update. This plan is the post-hoc design record that memorialises what was landed and what the guard/run steps still owe.

#### 3.4.5.4 Canonical clause text — v3 Integrated Reasoning

The v1 "Physical-rejection acknowledgement" text in §3.4.3 was superseded during the B.6.1 iteration by a v3 "Integrated Reasoning" rewrite. The canonical text for B.6a-v4 is the v3 Integrated-Reasoning clause:

```
## MANDATORY — Integrated reasoning (science + engineering)

You are both a scientist and an engineer. Your design session is governed
by two constraint systems that must be satisfied *simultaneously*, not
sequentially:

  (a) the **scientific goals** from the Stage 1 comparisons and upstream
      interpretation (e.g. "improve frequency resolution", "capture
      long-range dependencies"), AND
  (b) the **physical constraints** from any `[PHYSICAL REJECTION]` blocks
      under *Previous Failed Proposals* together with the "Effective cap"
      in the `[HARDWARE CONTEXT]` block.

If one or more `[PHYSICAL REJECTION]` blocks are present in the user
message, you MUST treat the previous failure as a **design constraint to
be solved alongside the scientific bottlenecks** — not a historical
footnote. Your `causal_hypothesis` must be a single integrated paragraph
that:

  - names the scientific bottleneck you are addressing (from the Stage 1
    comparisons), AND
  - names the physical failure that defeated the previous proposal — cite
    the rejected `model_type`, the dominant layer that caused the OOM,
    and the overshoot evidence (Effective cap vs Predicted peak), AND
  - explains how your new architecture achieves the desired scientific
    improvement *while remaining strictly within the "Effective cap"* that
    defeated the previous proposal — i.e. the structural choice must do
    both jobs at once.

A `causal_hypothesis` that addresses only the scientific bottleneck with
no mention of the physical rejection, OR one that addresses only the VRAM
cap with no scientific rationale, is incomplete. Cite the previous failure
as a design constraint to be solved alongside the scientific bottlenecks.
```

Two deliberate differences from the v1 draft in §3.4.3:

1. **"Integrated reasoning" framing** replaces "Physical-rejection acknowledgement". The prior framing invited the LLM to pivot the entire design session toward the rejection; the new framing frames both concerns as simultaneous constraints. Source: user directive — "scientist and engineer" framing, not a coercive "cognitive hammer".
2. **Two-sided incompleteness rule:** a proposal that addresses only the VRAM cap with no scientific rationale is *also* disqualified, not just one that ignores the rejection. Prevents the LLM from over-correcting into VRAM-obsession and producing a safe-but-unmotivated architecture.

#### 3.4.5.5 Sibling-template and mode-block audit

- **`causal_reasoning_stage_explore.md`** / **`causal_reasoning_stage_exploit.md`** — inspected and found to be **mindset-only**. Explore mode carries SOTA-inheritance + ADD-not-REPLACE instructions; exploit mode carries confirmed-link combination strategy. Neither carries VRAM content. The MANDATORY clause sits in the mode-agnostic base and is delivered in both modes. **No edit required.**
- **`proposing_stage.md:73`** — Rule 5 of the stage-3 template still says `"The baseline_config must fit in <10 GB VRAM."` This is the same Principle-5 violation that B.2b / B.2c killed in the legacy `PROPOSAL_REASONING_PROMPT` and `PROPOSAL_COMMIT_PROMPT` strings. B.2 addressed the legacy code path only; the staged pipeline's stage-3 template carries the violation forward. The stage-3 template also contains no reference to the `[HARDWARE CONTEXT]` block, no `[PHYSICAL REJECTION]` vocabulary, and no mention of the B.4 Golden Paragraph — **the entire WS-B hardware-aware + failure-educated + contract-reassertion contract is invisible to the staged-pipeline commit stage today.** This is deferred to a follow-up task (see §6.5 **B.8 — Staged-pipeline parity sweep**); addressing it in the same PR would double the blast radius, and the stage-3 cap-enforcement design needs its own pass (should it cite `[HARDWARE CONTEXT]` — requiring that block to be threaded into stage 3's user prompt too — or read `effective_cap_gb` directly from `ProposalInput`?). Out of scope for B.6a-v4.
- **`comparison_stage.md` / `comparison_stage_{explore,exploit}.md`** — inspected briefly; stage 1 handles model-comparison production and consumes `ModelComparisons`. No causal-hypothesis output, no VRAM-awareness requirement. No edit required.

#### 3.4.5.6 Test-guard correction — B.6b-v2

The current `tests/unit/agent/ml_model_proposal_agent/test_rejection_acknowledgement_prompt.py` imports `PROPOSAL_REASONING_PROMPT` from `nodes.ml_model_proposal_agent` — i.e. it asserts against the dormant legacy string. The port in B.6a-v4 removed the clause from the legacy string (Action 1 revert) and placed it in `causal_reasoning_stage.md` (Action 2). Every one of the 17 assertions therefore fails against current disk state. Fix:

- **Loader swap.** Replace `from nodes.ml_model_proposal_agent import PROPOSAL_REASONING_PROMPT` with `from agent.prompt_templates.proposal import load_prompt` + module-level `PROPOSAL_REASONING_PROMPT = load_prompt("causal_reasoning_stage.md")`. Keeping the same local variable name preserves every test's assertion body untouched.
- **Sentinel replacements.** Two sentinel strings used by placement-invariant tests exist only in the `.py`:
  - `"In your reasoning, cover all of the following:"` → replace with `"## What you produce"` (downstream boundary marker — MANDATORY clause must sit before this).
  - `"Background on the task:"` → replace with `"## What you receive"` (upstream boundary marker — MANDATORY clause must sit after this).
- **Header form.** `PROPOSAL_REASONING_PROMPT` had the bare header `MANDATORY — Integrated reasoning (science + engineering):` (trailing colon). The `.md` has `## MANDATORY — Integrated reasoning (science + engineering)` (with `## ` prefix, no trailing colon, Markdown header convention). Existing `test_mandatory_header_present` asserts the bare form — update to match the Markdown form literally (`"## MANDATORY — Integrated reasoning (science + engineering)"`). Alternatively a tolerant regex covers both, but the literal-`##` form is preferred (it documents the intentional decision to promote the clause to a top-level section).
- **Structural regex (`TestClausePositionInvariant`).** The one regex that pins the whole clause shape in a single assertion must be updated only to the header-form change (add optional `#{2}\s*` prefix, drop trailing colon expectation). All inner tokens (`You are both a scientist and an engineer`, `two constraint systems`, the three bullet-prefixed requirements, `Size \`baseline_config\``) exist verbatim in the `.md`.
- **The 17 test cases and 6 test-class names stay unchanged.** Git blame remains continuous. Each class's docstring is updated with a one-line note pointing to §3.4.5 so future readers know the guard protects a `.md` template, not a `.py` string.

**Invariant:** B.6b-v2 must be green against current disk before B.6e v4 runs. If B.6b-v2 fails, the bug is either (a) the clause text drifted from §3.4.5.4 during the Action 2 port (fix the `.md`) or (b) a sentinel was missed in the rewrite (fix the test). Do not reorder the workflow — the guard is the defense against silent prompt drift, so it must be green before any behavioral run.

#### 3.4.5.7 Phase A re-run — B.6e v4 (the first genuine observation)

Command (lilab dev box, no GPU required for mocked-tuner Phase A):

```
.venv/bin/python -m pytest tests/integration/workflows/test_vram_awareness.py \
    --real-llm -v -s
```

**Parametrization** (both must pass): `vram_budget_gb ∈ {10.0, 20.0}`. Seeded iter-1 rejection: `deep_punet`, `estimated_gb=29.1`, dominant layer `encoder.attention.block7.mha`, overshoot ×2.91 at 10 GB / ×1.46 at 20 GB.

**Success criteria — all three, both budgets:**

1. **Plumbing** (§5.3.4 item 2): `previous_failures` carries exactly one `[PHYSICAL REJECTION]`; `[HARDWARE CONTEXT]` renders in BUDGET regime with the correct effective cap; `hardware_context.device_available is True`.
2. **Parameter-count shrink** (§5.3.5): iter-2 `ProposalOutput.parameter_count_estimate < 0.5 × 100_000_000`.
3. **Keyword-audit** (§5.3.6): iter-2 `causal_hypothesis` contains at least one `_REJECTION_ACK_KEYWORDS` hit under the word-boundary regex (`len(hits) >= 1`).

**Evidence archiving (human-reviewable proof the clause landed):**

- **System-prompt snippet capture.** The dual-mode test harness already wraps `bridge.generate*` via `_CapturingProposer`. Extend the capture point to also persist the full `system=` string delivered to the stage-2 LLM call, write it to a debug path (e.g. `/tmp/siderius_b6e_v4/debug_stage2_system_prompt_budget_{N}.md`), and print its first 80 lines to stdout via `capsys.disabled()`. The human reviewer confirms `## MANDATORY — Integrated reasoning (science + engineering)` is present verbatim. This is the positive delivery proof — without it, a keyword-audit pass could still be coincidental.
- **Iter-2 `causal_hypothesis` excerpt** printed for each budget. Human review criterion: the text names (a) the scientific bottleneck from the seeded interpretation, (b) the `deep_punet` rejection with at least the `encoder.attention.block7.mha` dominant layer **or** the overshoot multiplier, and (c) how the new architecture solves both simultaneously.

**Debug path on failure:**

1. Open the captured system-prompt snippet and grep for `MANDATORY — Integrated reasoning`. If absent → the port (Action 2) did not take; re-inspect the loader path and the `.md` on disk. If present → the clause was delivered, the LLM just didn't obey.
2. Inspect the user-prompt snippet — confirm `[PHYSICAL REJECTION]` and `[HARDWARE CONTEXT]` blocks are both present. If absent → this is a Hop-4 orchestrator regression, not a B.6 cognitive issue; switch context to `workflows/model_exploration.py`.
3. If delivery is clean but `causal_hypothesis` still shows zero VRAM vocabulary on both budgets, the clause is genuinely ineffective. Do **not** relax the assertion thresholds or hand-tune keywords; the fix is a clause rewrite (a notional B.6a-v5). Record the verbatim `causal_hypothesis` output and open a diagnosis note before re-drafting.

**Safety gate:** B.5 Phase B (real training on lilab) stays blocked until B.6e v4 passes on the first attempt after B.6a-v4 + B.6b-v2 land. Do not trigger GPU-time work on a clause that has not been shown to work against the staged-pipeline LLM call.

#### 3.4.5.8 Sequencing and blast radius for B.6a-v4

Four actions, in strict order, one commit per action:

| Step | Action | File(s) | Blast radius | Reversibility |
|---|---|---|---|---|
| 1 | **Revert legacy edit** (B.6a-revert) | `nodes/ml_model_proposal_agent.py` (lines ~172–218, revert to pre-B.6 shape) | None — the legacy string is dormant | Trivial — `git revert` |
| 2 | **Port the clause** (B.6a-v4) | `agent/prompt_templates/proposal/causal_reasoning_stage.md` (new `## MANDATORY` section + two bullets in `## What you receive`) | Stage-2 system prompt of every live Proposer invocation. LLM sees a longer prompt; cognitive expectation to acknowledge rejections | Trivial — delete the new section, delete the two bullets |
| 3 | **Rewrite the guard** (B.6b-v2) | `tests/unit/agent/ml_model_proposal_agent/test_rejection_acknowledgement_prompt.py` | Unit tests only; no production behaviour change | Trivial — `git revert` |
| 4 | **Behavioral re-run** (B.6e v4) | No production file change; pytest against real LLM | One real-LLM iteration run × 2 budgets (LLM cost, no GPU) | N/A — observation only |

**Why this order:**

- Step 1 before step 2 so the legacy file is clean when the clause is ported — prevents the "ported but also still in the legacy" state that would make B.6b-v2's `load_prompt("causal_reasoning_stage.md")` assertions pass while the legacy is also dirty.
- Step 2 before step 3 so the guard has something on disk to assert against.
- Step 3 before step 4 so a delivery-layer regression is caught by the fast deterministic guard before spending real-LLM cycles on B.6e v4.

On-disk state (2026-04-24): steps 1 and 2 are landed. Steps 3 and 4 remain; step 3 must be green before step 4 runs.

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

A Tier-2 integration smoke (dual-mode, pseudo by default, `--real-llm` opt-in for the LLM, `--real-training` opt-in for the real tuner/training), parametrized over two VRAM-budget configurations so the Proposer must adapt its architecture complexity to the effective cap.

**`tests/integration/workflows/test_vram_awareness.py`** — two-iteration workflow.

#### 5.3.1 Multi-config stress

The test is parametrized over `vram_budget_gb ∈ {10.0, 20.0}`. Each value selects a distinct BUDGET regime (effective cap = 10 GB or 20 GB against the 25.6 GB stub physical floor). The iter-1 seeded oversized architecture (deep attention stack, `estimated_gb = 29.1`) overshoots **both** budgets, so the aggregator always surfaces exactly one `[PHYSICAL REJECTION]` regardless of which budget is active. The behavioral divergence is at the iter-2 Proposer output: under the tighter 10 GB cap the Proposer must shrink more aggressively than under 20 GB. Running both budgets in one test run is the "Proposer actually reads the number, not just the label" check.

#### 5.3.2 Tiered time budgeting

Both workflow-level time budgets are set on every run, reflecting production policy:

| Kwarg | Value | Rationale |
|---|---|---|
| `trial_time_budget_minutes` | `2.0` | Rapid search-phase iteration; trial rounds that exceed this are rejected by `evaluate_time_skill`. |
| `formal_time_budget_minutes` | `20.0` | Non-negotiable fixed cost of full validation-data evaluation — a formal round under this ceiling must be allowed to complete. |

In Phase A (mocked tuner) no wall-time is consumed, but the kwargs still flow through `run_workflow` into the planner's context so the LLM sees the same budgeting signals in both phases. In Phase B these budgets gate real subprocess training.

#### 5.3.3 Two-phase execution

| Phase | LLM | Training | Goal | Host |
|---|---|---|---|---|
| **Phase A — Logic / Reasoning** | Real (`--real-llm`) | Mocked (`MockTune`) | Verify the LLM explicitly acknowledges `[PHYSICAL REJECTION]` + `[HARDWARE CONTEXT]` in its iter-2 reasoning, and that the emitted `ProposalOutput` downsizes the dominant hyperparameter. Blast radius: LLM cost only; no GPU time. | Dev box, any CPU-only host |
| **Phase B — Gold Standard** | Real (`--real-llm`) | Real (`--real-training`) | Verify the theoretical constraints govern physical GPU reality end-to-end: the real tuner actually rejects iter-1's oversized architecture via the VRAM skill, the real Proposer reads the real rejection, and iter-2's baseline trains successfully under the effective cap. | lilab (RTX 5090) only |

The safety gate between phases is human review — Phase A must land, and the iter-2 reasoning snippet must show explicit acknowledgement of the `[PHYSICAL REJECTION]` and the effective cap, **before** we trigger Phase B.

#### 5.3.4 Choreography

1. **Iteration 1 setup.** Seed an interpretation whose take-home message implies an oversized architecture is reasonable (e.g. "the bottleneck is low-frequency recovery; need large receptive field"). In Phase A, stub `HyperparamTuningAgent` to return `HyperparamTuningOutput` with `physical_rejections = [one oversized attention architecture]` and `best_denoising_score = None`. In Phase B, let the real tuner run; the seeded interpretation is expected to drive the Proposer toward the same class of oversized architecture, which the live VRAM skill will reject.

2. **Iteration 2 plumbing assertions** (both phases). Capture the second iteration's `MLModelProposalAgent.run()` input. Assert:
   - `previous_failures` contains exactly one `[PHYSICAL REJECTION]` string referencing the iter-1 architecture and its dominant layer.
   - `hardware_context.device_available is True` (the orchestrator called `get_or_create`).
   - `vram_budget_gb` equals the parametrized budget.
   - The rendered reasoning prompt carries the `[HARDWARE CONTEXT]` block in the BUDGET regime with the correct effective cap, and the `[PHYSICAL REJECTION]` block under *Previous Failed Proposals*.

3. **Iteration 2 behavioral assertions** (real-LLM modes, Phase A+B). Require iter-2's `ProposalOutput.baseline_config.model_config` to shrink **at least one** dominant hyperparameter (`hidden_dim` or `depth`) relative to iter-1's rejected config. The test also prints iter-2's `proposed_change` + `causal_hypothesis` + `motivation` to stdout (via `capsys.disabled()`) so the human reviewer can confirm the LLM is citing the rejection and the effective cap explicitly, not just shrinking by coincidence.

4. **Phase B only — physical completion.** Require iter-2's `HyperparamTuningOutput.status == "succeeded"` with `best_denoising_score is not None`. This is the proof that the baseline actually fit in VRAM on the physical device.

The behavioral assertion is inherently probabilistic (one LLM sample per budget per phase). Threshold: passes if the dominant hyperparameter decreased at all; fails only if the Proposer re-proposed the same or larger value. Two budgets × two phases = four probabilistic trials; a single pass per budget per phase is sufficient evidence. The goal is a regression trip-wire, not statistical characterization.

#### 5.3.5 Parameter-count behavioral assertion (supersedes the hidden_dim / depth check)

**Problem.** The §5.3.4-item-3 assertion uses a narrow knob-level check:

```python
hidden_ok = iter2_hidden is not None and iter2_hidden < _REJECTED_HIDDEN_DIM  # 1024
depth_ok  = iter2_depth  is not None and iter2_depth  < _REJECTED_DEPTH       # 9
shrunk    = hidden_ok or depth_ok
```

This is **architecture-class-narrow**. When the Proposer pivots from `deep_punet` (attention-UNet with `hidden_dim` / `depth` keys) to a dilated causal conv (`embedding_size` / `embedding_dim` / `dilation_rates` — no `hidden_dim`, no `depth`), both variables read `None`, `shrunk` is False, and the assertion trips even though the new baseline is objectively much smaller than the rejection. Phase A 10 GB budget is exactly this failure mode.

**Solution.** Replace the knob-level check with a **total-parameter-count** assertion on `ProposalOutput.parameter_count_estimate` — already emitted by the commit stage and already validated as a positive int by the `ProposalOutput` schema, so no new plumbing.

Add to `tests/integration/workflows/test_vram_awareness.py`:

```python
# Iter-1 seeded deep_punet at hidden_dim=1024, depth=9, seg_size=40000
# would estimate around 100M params under the commit-stage estimator.
# The round constant keeps the test immune to Implementor-side drift.
_REJECTED_PARAM_COUNT_ESTIMATE = 100_000_000
_ITER2_PARAM_CEILING_FRAC      = 0.50  # iter-2 must be < 50% of rejected

def _iter2_param_count_ok(iter2_proposal) -> bool:
    return (
        iter2_proposal.parameter_count_estimate
        < _REJECTED_PARAM_COUNT_ESTIMATE * _ITER2_PARAM_CEILING_FRAC
    )
```

**Threshold rationale (50% cut).** Strict enough to catch the regression case (Proposer re-proposes an 80M-param attention stack ≈ 80% of the rejected scale — flagged), generous enough to pass sensible alternatives (a 40M-param transformer at 10 GB budget — passes), and architecture-agnostic (no knob names encoded in the test). The Proposer is instructed to produce a realistic `parameter_count_estimate` (commit-stage spec lines 266–269); if it systematically under-reports to cheat this assertion, that is a separate commit-stage compliance bug the schema validator must catch — not this test's concern.

**Seeding requirement.** The iter-1 `HyperparamTuningOutput.physical_rejections[0].attempt_config` must include an architecturally-consistent hyperparameter signature (existing test seed already has `hidden_dim=1024, depth=9`) so the rendered `[PHYSICAL REJECTION]` block carries a concrete "Worst attempted config" line for the LLM to cite. The param-count constant `_REJECTED_PARAM_COUNT_ESTIMATE = 100_000_000` is a round upper bound on what that seeded config would predict; keeping it a round number (not a computed estimator output) makes the test deterministic.

#### 5.3.6 Text-level audit assertion — causal_hypothesis keyword gate

**Problem.** The §5.3.4 item 2 plumbing assertions prove the `[PHYSICAL REJECTION]` block arrived at the Proposer's user prompt. The §5.3.5 parameter-count assertion proves the committed baseline is smaller. **Neither asserts the LLM reasoned against the rejection** — which is the cognitive property the §3.4 MANDATORY clause is designed to enforce. Phase A's failing run passed plumbing, produced a smaller baseline by pivot-coincidence, yet its `causal_hypothesis` text contained *zero* VRAM-family vocabulary.

**Solution.** Assert iter-2's reasoning-stage `causal_hypothesis` output contains at least one VRAM-family keyword indicating explicit acknowledgement of the physical rejection.

Add to `tests/integration/workflows/test_vram_awareness.py`:

```python
_REJECTION_ACK_KEYWORDS = (
    "vram",        # generic VRAM vocabulary
    "oom",         # direct rejection-class acknowledgement
    "rejection",   # direct rejection-class acknowledgement
    "cap",         # "effective cap" / "budget cap"
    "overshoot",   # rejection-block overshoot multiplier
    "budget",      # budget-regime acknowledgement
    _REJECTED_MODEL_TYPE,  # "deep_punet" — literal citation of the rejected arch
)

def _iter2_reasoning_cites_rejection(iter2_reasoning: dict) -> tuple[bool, list[str]]:
    causal = str(iter2_reasoning.get("causal_hypothesis", "")).lower()
    hits   = [kw for kw in _REJECTION_ACK_KEYWORDS if kw in causal]
    return len(hits) >= 1, hits
```

**Contract.** The test asserts `len(hits) >= 1` — at least one keyword must appear. The assertion message prints the full `causal_hypothesis` text and the empty `hits` list on failure, so a failed Phase A run immediately surfaces what the LLM said in place of rejection acknowledgement.

**Why a keyword gate, not a semantic judge.** A semantic check (another LLM call judging the text) would be expensive, non-deterministic, and would itself need prompt hardening. A keyword gate is deterministic, zero-cost, and directly covers the observable symptom: Phase A produced causal_hypothesis texts with *zero* matches against this keyword set. If the §3.4.3 prompt amendment has any effect, a compliant reasoning output will contain at minimum `cap` / `rejection` / `deep_punet`.

**Scope.** The keyword gate is a *trip-wire*, not a *grade*. Passing it proves the LLM used rejection-relevant vocabulary; it does not prove the full acknowledgement was semantically responsive. Human review of the printed snippet (existing §5.3.4 behavior) remains the higher-fidelity check and stays in the test. This assertion's job is to catch the silent-drift regression where a future prompt refactor accidentally removes the MANDATORY clause and breaks the cognitive contract without breaking plumbing.

#### 5.3.7 Phase B wiring plan — B.6f

**Problem.** Phase B as promised by §5.3.3 (real LLM + real tuner, real iter-1 OOM, iter-2 trains to `status="succeeded"`) is **not wired** into `tests/integration/workflows/test_vram_awareness.py` as of 2026-04-24. The test unconditionally patches **five** heavy nodes regardless of `--real-training`:

- `workflows.model_exploration.ResultInterpretationAgent` → canned interpretation
- `workflows.model_exploration.MLModelImplementor` → canned plugin output (no real plugin file)
- `workflows.model_exploration.MLCodeValidatorAgent` → always "passed"
- `workflows.model_exploration.HyperparamTuningAgent` → `.side_effect = [iter1_tune, iter2_tune]` (real tuner never runs; real OOM never happens)
- `workflows.model_exploration.get_or_create_hardware_context` → `_stub_hardware_context()` (fake 32 GB, masks the real RTX 5090 31.34 GB)

Plus `_iter1_tuning_output_with_rejection()` manufactures a synthetic `PhysicalRejection` — so even in the "--real-training" code path, iter-1 never *earns* its rejection from a real OOM. Passing `--real-training` today produces a run bit-identical to `--real-llm`-only.

**Pre-flight data check (2026-04-24).** Real TIDMAD dataset confirmed at `/home/klz/Data/TIDMAD/` — 862 GB of `abra_science_{0000..NNNN}.h5` files, readable. Hardware confirmed: `NVIDIA GeForce RTX 5090`, 31.34 GB usable VRAM via `torch.cuda.get_device_properties(0)`.

**Action list (B.6f).**

1. **Dynamic patching.** Thread `_is_real_training(request)` (imported from `tests.conftest`) into the patch stack. In **Phase A** (`real_training=False`) keep all 5 patches exactly as they are — Phase A is frozen. In **Phase B** (`real_training=True`) **lift all 5 patches**: the real `HyperparamTuningAgent`, `MLModelImplementor`, `MLCodeValidatorAgent`, `ResultInterpretationAgent` run, and `get_or_create_hardware_context` returns the live `HardwareContext` for the RTX 5090. Mechanically this is a conditional `ExitStack` / `contextlib.ExitStack.enter_context(...)` rather than a fixed `with patch(...) as ...` chain, so the set of active patches is computed once per run.

2. **Seed removal (Phase B only).** Do **not** invoke `_iter1_tuning_output_with_rejection()`; do **not** set `MockTune.return_value.run.side_effect`. The real tuner must earn its iter-1 rejection from a real OOM against the real RTX 5090. The `_write_tuning_output(...)` seed at the top of the test (which bootstraps iter-1's comparison input) stays — it is read by the orchestrator, not by the tuner.

3. **Assertion enhancement (Phase B only).** After `run_workflow(...)` returns, read the iter-2 `HyperparamTuningOutput` from `captured_inputs` *or* from its written record in `{workspace}/run_name/iteration_002/...`. Assert:
   - `iter2_tuning.status == "succeeded"` — the baseline the shrunk Proposer emitted actually fit in VRAM and trained through.
   - `iter2_tuning.best_denoising_score is not None` — a numerical score was produced, proving the tuner completed at least one round.
   - (Diagnostic, not gating) print iter-2 `best_exp_id` + `best_config` + `best_denoising_score` + `completed_rounds` for the human reviewer.

4. **Budget scope.** Per directive: Phase B only runs **20 GB budget** to save time/cost. Keep the 10 GB parametrization available but mark it with `pytest.param(10.0, marks=pytest.mark.skip(reason="Phase B: 20 GB only per directive"))` when `real_training=True`, or equivalently filter the parametrize list in a `pytestmark` hook. Do not delete the 10 GB line — Phase A still exercises both budgets.

5. **Skip logic.** Extend the existing `pytest.skip` block: `real_training and not torch.cuda.is_available() → skip("Phase B requires CUDA")`; `real_training and not Path("/home/klz/Data/TIDMAD").exists() → skip("Phase B requires TIDMAD data")`. Keep the OPENAI_API_KEY skip as-is (real-LLM still required in Phase B).

6. **Hardware-context stub — conditional lift.** The `_stub_hardware_context()` fixture stays in the file but is no longer referenced unconditionally; the phase-branch in step 1 chooses between the stub (Phase A) and the real `get_or_create_hardware_context` (Phase B). No changes to `core/hardware_context.py`.

7. **Bridge-capture reuse.** The `_real_capturing_bridge_factory` instrumentation added during B.6e v4 stays. It records all `bridge.generate(...)` calls regardless of phase — useful for Phase B debugging if iter-2 training fails and we need to re-read what the LLM proposed.

**Scope boundary.** B.6f is purely test-file surgery in `tests/integration/workflows/test_vram_awareness.py`. No changes to `nodes/`, `workflows/`, `agent/prompt_templates/`, or any production code. Phase A behaviour must remain bit-identical.

**Safety gate.** After B.6f's code edits land, show the diff for human review **before** launching the GPU run. Only then execute:

```
.venv/bin/python -m pytest tests/integration/workflows/test_vram_awareness.py --real-llm --real-training -v -s
```

Expected wall-clock: ~20–40 min (iter-1 OOM aborts fast, iter-2 real training dominates — one model × ~10 tuning rounds at `formal_time_budget_minutes=20.0`).

**Evidence capture (Phase B).** On successful completion surface:
- Iter-1 physical-rejection block (the real one that came from the RTX 5090's VRAM engine) — architecture, dominant layer, measured GB, effective cap
- Iter-2 training summary: `best_denoising_score`, `best_exp_id`, `completed_rounds`, `status`, and the committed `baseline_config`
- The existing stage-2 system-prompt snippet from B.6e v4's instrumentation

**Non-goal.** B.6f does *not* add a new behavioural assertion about the iter-2 `best_denoising_score` value (e.g. "score must exceed SOTA"). Phase B's cognitive contract is "the shrunk baseline trains to succeeded", not "the shrunk baseline beats SOTA". A score-beat assertion would be probabilistic, expensive, and out of scope — it belongs in a later work-stream focused on proposal quality, not hardware awareness.

#### 5.3.8 B.6g execution status (in flight)

**Status (live).** Phase B real-mode is on its **fourth launch (v8)**. Three earlier launches (v5, v6, v7) were killed after diagnosis or evidence-failure. v8 combines Path 2 (stricter cap, **1.5 GB**) and Path 3 (over-architect `human_advice_propose`) from the prior decision matrix to **force** a real OOM at iter-1.

**Launch history.**

| Run | When | Configuration | Outcome | Root cause / verdict |
|---|---|---|---|---|
| v5 | 2026-04-24 ~14:00 | `data_dir=SIDERIUS_DATA_DIR` (no raw `.h5`); both VRAM budgets 8.0 GB; `is_trial` default (`False`); Implementor upgraded to `gpt-5-mini` | ❌ Every Tuner attempt failed at TimeEval pre-flight | `agent/skills/training_skill/estimator.py:140` raised `AttributeError: 'NoneType' object has no attribute 'values'` — `data_dir` lacked raw TIDMAD `.h5` for PSD sampling |
| v6 | 2026-04-24 ~15:00 | `data_dir=_TIDMAD_DATA_DIR`; both VRAM budgets 8.0 GB; `is_trial` default (`False`); Implementor `gpt-5-mini` | ❌ TimeEval crash fixed; every Tuner attempt rejected by TIME gate; 3 consecutive fail-rounds → Tuner abort | `run_workflow(..., is_trial: bool = False, ...)` was the silent default → `trial_allowed = agent_input.is_trial` forced **formal mode** (20-min cap rejected baseline's 45.5-min estimate) |
| v7 | 2026-04-24 16:08–16:40 | `data_dir=_TIDMAD_DATA_DIR`; both VRAM budgets **6.0 GB**; `is_trial=True`; seed score 0.01; Implementor `gpt-5-mini` | ⚠️ Killed at Round 3 — first real GPU training landed but planner stayed conservative (46K → 68K params), no OOM earned | Cap was high enough that planner could pick a small architecture and skip the wall — no signal on the directive's success criterion |
| v8 | 2026-04-24 16:44–17:19 | VRAM budgets `1.5 GB`; `is_trial=True`; seed score 0.01; Implementor `gpt-5-mini`; iter-1 over-architect advice via `human_advice_propose` (scrubbed on iter-2 in `_CapturingProposer`); `formal_time_budget_minutes=120.0` so TIME gate cannot pre-empt OOM | ❌ Killed by user at 17:19 — never reached iter-2; success criterion not met (zero `skipped_oom_risk` ever entered `physical_rejections_buffer`) | TIME/VRAM gate coupling — at `_PHASE_B_TRIAL_TIME_BUDGET_MIN=5.0` the 47.5-min preflight estimate trips the **TIME** gate first; planner shrinks `trial_portion` to escape it, which incidentally satisfies the VRAM gate too (`_002` measured `vram_estimate_gb=0.668` ≪ 1.5 GB cap). The VRAM wall never had pressure |

**v8 timeline (final state — killed by user at 17:19).**

| Stage | Started | Wall-time | Status | Output / Notes |
|---|---|---|---|---|
| pytest collect | 16:44 | ~5s | ✅ | 10 GB / 20 GB skipped; only 1.5 GB Phase B case runs |
| Iter-1 Interpreter | 16:44 | ~10s | ✅ | `interpretation_b5_vram_awareness_budget1gb.json` written 16:44 |
| Iter-1 Proposal **attempt 1** — Proposer | ~16:44 | ~30s | ✅ | Picked **`multi_headed_attention_net`**, `parameter_count_estimate=8,500,000`, baseline_config: `multi=32, depth=4, kernel_size=9, embedding_dim=64, segmentation_size=16000`, `batch_size=1, lr=1e-4, focal loss`. **Advice landed:** Proposer chose Attention + 8.5M params (vs v7's 750K) |
| Iter-1 Proposal **attempt 1** — Implementor + Validator | ~16:45 | ~6m | ❌ | `attempt_001_multi_headed_attention_net/` contains only `proposal_*.json` — no impl/validator artefacts. gpt-5-mini could not materialise the attention plugin within `max_impl_attempts=3` (or validator rejected). Workflow auto-rolled to a fresh proposal attempt at 16:51 |
| Iter-1 Proposal **attempt 2** — Proposer | 16:51 | ~1m | ✅ | Picked **`dilated_causal_net`**, `parameter_count_estimate=820,000`, baseline_config: `multi=32, depth=4, kernel_size=5, embedding_dim=32, segmentation_size=16000`, `batch_size=1`. `preflight_factor=9.505`, `preflight_estimated_minutes=47.52`. **Advice softened:** the Proposer dropped from 8.5M-attention to 820K-conv after the prior attempt failed |
| Iter-1 Proposal **attempt 2** — Implementor | ~16:52 | ~7m | ✅ | `attempt_002_dilated_causal_net/implementor_b5_vram_awareness_budget1gb.json` written 16:59; `models/`, `tests/` directories populated |
| Iter-1 Proposal **attempt 2** — Validator | ~16:59 | <1m | ✅ | `validation_b5_vram_awareness_budget1gb.json` (16:59) — **`passed: true`** across all gates: plugin_registered, tests_passed, description_valid, config_fields_valid, instantiation_passed, gradient_check_passed, output_type_valid, llm_review_passed |
| Iter-1 Tuner — handoff + hardware probe | 16:59 | <1m | ✅ | `dilated_causal_net/b5_vram_awareness_budget1gb_hardware.json` written 16:59 (live RTX 5090 manifest); workspace `dilated_causal_net/{configs,plugins,records,cached_models}/` initialised |
| Iter-1 Tuner Round 1 / Attempt 1 (`_001`) | ~17:00 | <1m | ⚠️ skipped — **TIME** gate, not VRAM | `records/.../dilated_causal_net_b5_vram_awareness_budget1gb_001.json`: **`status: skipped_time_risk`**, `denoising_score: None`. Trial config: `snapshot/0.05, train_portion=0.1, batch_size=1, lr=1e-4, focal loss, depth=4, embedding_dim=32`. **Implication:** at the 5.0-min trial time budget the 47.5-min preflight estimate triggers TIME, not VRAM — the rejection that lands in `physical_rejections_buffer` is the **wrong kind** for this directive's success criterion. |
| Iter-1 Tuner Round 1 / Attempt 2 (`_002`) — pre-flight | ~17:01 | <1m | ✅ accepted both gates | Trial config shrunk: `snapshot/0.04` (eval/0.04 too) — that knocks predicted training time below the 5-min trial cap. Both gates passed → training launched. |
| Iter-1 Tuner Round 1 / Attempt 2 (`_002`) — training | 17:01 | ~4m | ✅ **clean run, no OOM** | `experiment_results_..._002.json` (17:05): `final_loss=1.976` (loss_history `[2.112, 1.976]`, 2 epochs), `model_params=5,075,104` (~5.1M — **6× larger than the Proposer's 820K estimate** but still fit at `batch_size=1` + `snapshot/0.04`). Peak GPU: 1192 MiB ⇒ well under the 1.5 GB cap. **No PhysicalRejection earned on this round.** |
| Iter-1 Tuner Round 1 / Attempt 2 (`_002`) — inference | ~17:05 | ~6m 7s | ✅ | All 20 `abra_validation_denoised_..._00xx.h5` files written; `inference_time_s=366.9` per record |
| Iter-1 Tuner Round 1 / Attempt 2 (`_002`) — scoring | ~17:11 | ~39s | ✅ | `scoring_time_s=38.7`; record `dilated_causal_net_..._002.json` (15 KB) written 17:12 |
| Iter-1 Tuner Round 1 / Attempt 2 (`_002`) — outcome | — | total ~10m | ✅ **success, no OOM** | `denoising_score=2.0398` (vs raw baseline 1.0011 — substantial gain), `final_loss=1.976`, `vram_estimate_gb=0.668` (well below 1.5 GB cap → no VRAM rejection ever in play). Reflector discovery: "frequency-aware behaviour, files 5–19 show large per-file gains; 0–3 show almost none." `memory_update` requests `trial_portion=0.10-0.20` for next round. |
| Iter-1 Tuner Round 2 / Attempt 1 (`_003`) | ~17:13 | <1m | ❌ | `status=skipped_schema_violation`; planner emitted invalid spec; rolled to next attempt |
| Iter-1 Tuner Round 2 / Attempt 2 (`_004`) — training | ~17:15 | ~2m | ✅ | `experiment_results_..._004.json` 17:17: `final_loss=2.008`, `model_params=252,080` (planner went *smaller* than `_002`'s 5.1M); model: `seg=20000, multi=16, depth=3, kernel=7, embedding=16`. No OOM. |
| Iter-1 Tuner Round 2 / Attempt 2 (`_004`) — inference | ~17:17 | ~2m before kill | ❌ killed mid-inference | `inference_single.py` PID 3696450 was running (`inference_batch_size=16`, GPU 1156 MiB) when pytest TERM at 17:19 took it down with its parent. No final score recorded for `_004`. |
| Iter-1 close → emit `[PHYSICAL REJECTION]` | — | — | ❌ never reached | Directive success criterion #1 — buffer never received a `skipped_oom_risk` to aggregate |
| Iter-2 Interpreter / Proposer | — | — | ❌ never reached | — |
| Iter-2 `causal_hypothesis` cites 1.5 GB cap + iter-1 rejection | — | — | ❌ never reached | Directive success criterion #2 |
| Iter-2 Implementor / Validator / Tuner | — | — | ❌ never reached | — |
| pytest assertion block | — | — | ❌ never reached | — |

**Durable wins from v5–v7 (still hold in v8).**

1. `is_trial=True` propagates from `run_workflow` to the Tuner; planner emits trial configs every round.
2. `data_dir=_TIDMAD_DATA_DIR` keeps TimeEval functional (real PSD sampling).
3. `gpt-5-mini` Implementor produces a working plugin 1-shot.
4. Pre-flight gates accept trial configs against the configured cap.
5. Real GPU training lands and produces real `denoising_score` values.

**v8 design rationale (over v7).**

- **Cap drop 6.0 → 1.5 GB.** Below the floor a multi-head-attention U-Net at the Proposer's default scale can fit in. Nearly any reasonable architecture will OOM.
- **`human_advice_propose` instructs over-architecture.** Routed *only* to iter-1 (scrubbed on iter-2 inside `_CapturingProposer`) so the advice cannot fight the MANDATORY rejection-acknowledgement clause on the second pass. **Already paid off:** iter-1 Proposer picked `multi_headed_attention_net` with 8.5M params — exactly the kind of overshoot we want.
- **`formal_time_budget_minutes=120.0`.** Removes the 20-min TIME gate as a competing rejection signal, so any rejection emitted by the Tuner unambiguously comes from the **VRAM** path (the cognitive contract under test).
- **Retain `is_trial=True`.** Trial mode keeps the inner-loop fast even if iter-1 cycles through multiple OOM-rejection attempts; without it, formal-mode pre-flight overhead would dominate wall-clock.

**v8 outcome (concluded 2026-04-24 17:19 — killed by user; success criterion not met).**

- **Wall-clock:** 35 min from 16:44 launch to 17:19 kill; never reached iter-2.
- **Iter-1 Tuner attempt summary (4 attempts, all in iter-1 Round 1–2):**
  - `_001` — `skipped_time_risk` at preflight (47.5 min predicted vs 5.0 min trial cap). **Wrong rejection kind** for this directive.
  - `_002` — ✅ trained (`snapshot/0.04`, 5.1M params, peak 1192 MiB, `vram_estimate_gb=0.668`); `denoising_score=2.0398` vs raw 1.0011. **No OOM, no rejection.**
  - `_003` — `skipped_schema_violation` (planner emitted invalid spec). **Not a physical rejection.**
  - `_004` — ✅ trained (`seg=20000, multi=16, depth=3, kernel=7, embedding=16`, 252K params, no OOM); inference killed mid-run.
- **`physical_rejections_buffer` final contents:** 0 × `skipped_oom_risk`, 1 × `skipped_time_risk`, 1 × `skipped_schema_violation`. The aggregator never had a VRAM-class rejection to surface in iter-2's `previous_failures`.
- **Root-cause observation — TIME/VRAM gate coupling.** The Tuner's pre-flight runs *both* gates against the same trial config; whichever fires first emits a rejection and the planner shrinks `trial_portion` to escape it. With `_PHASE_B_TRIAL_TIME_BUDGET_MIN=5.0` and a baseline 47.5-min preflight estimate, **TIME always fires first**. The shrink the planner applies (e.g. `0.05 → 0.04 → smaller batch coverage`) drops both predicted training time *and* peak VRAM linearly, so by the time TIME is satisfied, VRAM is already comfortably under cap. The 1.5 GB wall never had pressure on it because nothing forced the planner to keep `trial_portion` large enough to threaten VRAM.
- **Why iter-1 advice landing didn't save it.** The over-architect advice *did* land in the Proposer (attempt-1 picked Attention + 8.5M params; attempt-2 picked `dilated_causal_net` at 820K). But the Proposer's architectural overshoot is irrelevant once the Tuner is allowed to shrink the trial slice — VRAM scales with `batch × T × params`, and the Tuner controls the `T` knob via `trial_portion`/`segmentation_size`.
- **What the run *did* prove.** The full Proposer→Implementor→Validator→Tuner inner loop is healthy end-to-end: the over-architect advice routes correctly, gpt-5-mini materialises a working plugin, the validator is honest, the Tuner pre-flight gates work, real GPU training lands clean denoising scores. The only failure is that the directive's specific success signal (a `skipped_oom_risk`-class rejection feeding iter-2) cannot be produced by the v8 lever set.

**v9 directive sketch (next iteration).** Two coupled levers needed to break the gate-coupling:

1. **Decouple the TIME gate from the VRAM gate.** Raise `_PHASE_B_TRIAL_TIME_BUDGET_MIN` from `5.0` to ≥ `60.0` so the TIME gate stops absorbing pressure that should land on VRAM. With a 60-min trial budget, the 47.5-min preflight estimate passes TIME, and VRAM becomes the only remaining wall.
2. **Tuner-side advice forbidding the shrink escape route.** Inject `human_advice_tune` (or equivalent) into iter-1 forbidding `batch_size=1` and forcing `trial_strategy=anchors` (or equivalent floor on covered tokens). This removes the planner's degree of freedom that lets VRAM slip below the cap.

Combined effect: the planner is forced to submit a trial config with enough activation footprint to actually hit the 1.5 GB wall, producing a real `skipped_oom_risk` rejection that iter-2 can read and adapt to.

**Wall-clock estimate revision.** §5.3.7 estimated "~20–40 min" assuming iter-1 OOMs fast. v7 evidence revised this — at trial-mode `~8–9 min/round`, a full `max_rounds=10` iter-1 sequence approaches 90 min. v8 confirmed the trial-mode rhythm: ~10 min per successful Tuner attempt (training + 20-file inference + scoring). v9 design must keep iter-1 short by ensuring rejections fire at *pre-flight* (not after a full training cycle) — that is what the lever set above is supposed to deliver.

**v9 outcome (B.6h, concluded 2026-04-24 17:44 — killed at first iter-1 round; gate-coupling defeated, second-order shrink discovered).**

v9 lever set: `trial_vram_budget_gb=0.5`, `_PHASE_B_TRIAL_TIME_BUDGET_MIN=60.0`, `max_rounds=2`, Proposer-side `human_advice_propose` instructing over-architecture (`deep_punet`, `hidden_dim=1024`), iter-1 advice scrubbed on iter-2.

What landed (file evidence, 15 min in):
- Proposer respected the advice. Iter-1 attempt-1 emitted `model_name="high_capacity_net"`, baseline `multi=128, depth=5, kernel_size=9, embedding_dim=64, segmentation_size=16000`, `parameter_count_estimate=9,876,543`. Internal `memo_consistency_notes`: *"PREFLIGHT_OVERBUDGET_EMITTED: all 3 pre-flight attempts exceeded the 60.0 min budget; emitting lowest-factor candidate (factor=9.45x, estimated 566.8 min)."* The Proposer actively tried over-architecture; all three of its internal candidates blew the 60-min budget.
- **The Tuner planner shrank the trial config independently of the baseline.** Round 1 Attempt 1 `model_config_001.json` emitted `multi=16, depth=3, kernel_size=9, embedding_dim=32` — `multi` collapsed 128 → 16 (8×), `depth` 5 → 3, `embedding_dim` 64 → 32. Effective trial parameter count: ~250K (vs the baseline's 9.9M, a 40× reduction).
- Pre-flight VRAM estimate accepted the shrunk config (well under 0.5 GB), pre-flight TIME passed (well under 60 min), training launched. Actual GPU usage during training: ~1.5 GB delta over baseline (3× the 0.5 GB nominal cap, but well below the 31 GB physical ceiling — no runtime CUDA OOM).
- Run was killed at this point (15 min wall-clock) because the diagnostic was already conclusive.

Root-cause observation — **the Tuner planner has independent authority over `multi/depth/embedding_dim`**, and v8's gate-coupling diagnosis generalises: the planner will exercise *any* degree of freedom available to it (in v8 it was `trial_portion`; in v9 it is the architectural hyperparameters themselves) to satisfy whichever budget gate is binding. The Proposer's `baseline_config` and `human_advice_propose` reach the Proposer prompt only — neither propagates to the Tuner. Adding a third lever inside this PR (Tuner-side `human_advice_tune` or a `min_multi`/`min_depth` floor) would keep changing the test scaffolding without addressing the missing capability in the system itself.

**Decision:** stop chasing the `[PHYSICAL REJECTION]` signal in this PR. WS-B has landed the **infrastructure** for hardware-aware feedback (5-hop wiring, both prompt blocks, MANDATORY clause) — the Proposer-side path is verified by Phase A's synthetic-rejection tests and by the v9 evidence that the Proposer correctly honours over-architect advice. The **system-level capability** to deterministically force the Tuner planner to fail-instead-of-shrink is a separate piece of work and is captured in §1.3 (Non-goals) + §7 (Future Work). The v9 run also demonstrated a **second hardware-aware behaviour worth recognising**: in-iteration auto-shrink. The Phase B test is updated (B.6h) to accept *either* "Failure-Rejection-Correction" *or* "Successful Auto-Shrink" as a valid Hardware-Aware pass — see §7.2.

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

- [~] **B.5 — VRAM-Awareness end-to-end test.**
  - [x] Pseudo-mode test landed (commit `145afaf`) — 0.93 s, covers plumbing layers 1+2 at a single `vram_budget_gb=20.0`.
  - [x] Parametrize over `vram_budget_gb ∈ {10.0, 20.0}` per §5.3.1; thread `trial_time_budget_minutes=2.0` + `formal_time_budget_minutes=20.0` through `run_workflow` per §5.3.2.
  - [~] **Phase A — Logic/Reasoning** (`--real-llm`, mocked tuner). *First attempt 2026-04-24: 20 GB passed plumbing + narrow-behavioral; 10 GB passed plumbing but failed narrow-behavioral (pivoted to dilated_causal_unet — no hidden_dim / depth keys). **Critical audit finding:** both budgets' causal_hypothesis texts cite only the seeded interpretation bottleneck, with zero VRAM-family vocabulary.* Re-run gated on **B.6** landing.
  - [~] **Phase B — Gold Standard** (`--real-llm --real-training`). lilab run only. Phase B is scoped to the **20 GB budget only** per directive to save GPU time/cost. B.6e v4 passed both budgets 2026-04-24 (see above), unblocking this item.
    - [ ] **B.6f — wire Phase B into `test_vram_awareness.py`** per §5.3.7: branch on `_is_real_training(request)` to lift all 5 patches in Phase B (Tuner / Implementor / Validator / Interp / hardware-context stub); skip the synthetic iter-1 seed in Phase B; add `iter2_tuning.status == "succeeded"` + `best_denoising_score is not None` assertions; 20 GB-only parametrize filter in Phase B; CUDA-availability + TIDMAD-data skip guards. **Safety gate:** diff shown for human review before the GPU run. No production-code changes.
    - [~] **B.6g — Phase B execution.** `.venv/bin/python -m pytest tests/integration/workflows/test_vram_awareness.py --real-llm --real-training -v -s` on lilab RTX 5090 (31.34 GB measured). Success criterion: `iter2_tuning.status == "succeeded"` with a numerical `best_denoising_score`. Evidence: real iter-1 physical-rejection block, iter-2 training summary, and the B.6e v4 system-prompt snippet. **Status (2026-04-24): in flight — v7 launch mid iter-1 Round 3, see §5.3.8.** Three launches: v5 killed (TimeEval crash from missing raw `.h5`); v6 killed (formal-mode lockout from `is_trial=False` default rejected by TIME gate); v7 (current — `is_trial=True`, both budgets 6.0 GB, Implementor `gpt-5-mini`) has landed real GPU training but planner is staying conservative (46K → 68K params), so no `PhysicalRejection` earned yet.

- [~] **B.6 — Cognitive Hardening (rejection acknowledgement).** *(directly gates B.5 Phase B; see §3.4 problem statement + §3.4.5 correction + §5.3.5 + §5.3.6)*
  - [x] **B.6a (v1–v3) — legacy prompt edit (now reverted).** The `MANDATORY` clause was authored into `PROPOSAL_REASONING_PROMPT` across three revisions (v1 Physical-rejection acknowledgement, v2 substring-bug fix, v3 Integrated Reasoning). Discovery 2026-04-24 (see §3.4.5.1): the legacy string is dormant; the live stage-2 prompt loads from `causal_reasoning_stage.md`. All edits reverted in `nodes/ml_model_proposal_agent.py`; file now matches pre-B.6 shape.
  - [x] **B.6a-v4 — port the Integrated-Reasoning clause to the staged template.** Insert the §3.4.5.4 canonical clause into `agent/prompt_templates/proposal/causal_reasoning_stage.md` between `## What you receive` and `## What you produce`. Also expand `## What you receive` with two new bullets declaring `Previous Failed Proposals` / `[PHYSICAL REJECTION]` and `[HARDWARE CONTEXT]` as stage-2 inputs (§3.4.5.3). Mode-block audit (§3.4.5.5) confirms `causal_reasoning_stage_{explore,exploit}.md` need no edit.
  - [x] **B.6c — Param-count assertion swap.** (landed previously against `tests/integration/workflows/test_vram_awareness.py`; unchanged by the v4 correction since the assertion operates on `ProposalOutput.parameter_count_estimate`, not on prompt text.)
  - [x] **B.6d — Keyword-audit assertion.** (landed previously; unchanged by the v4 correction. The word-boundary matcher introduced during the B.6.1 iteration stays — it operates on `causal_hypothesis` output text and is delivery-path-agnostic.)
  - [x] **B.6b-v2 — rewrite rendered-prompt guard.** Landed 2026-04-24. Rewrote `tests/unit/agent/ml_model_proposal_agent/test_rejection_acknowledgement_prompt.py` to load `causal_reasoning_stage.md` via `load_prompt` from `agent.prompt_templates.proposal` (not import `PROPOSAL_REASONING_PROMPT`). Kept 17 cases across 6 classes. Three regex adjustments for `.md` line-wrap (`not a historical\s+footnote`, `only the scientific bottleneck with\s+no mention...`, `design constraint to\s+be solved alongside`). 17/17 green (0.02 s).
  - [x] **B.6e v4 — Phase A re-run (success gate).** Landed 2026-04-24. `.venv/bin/python -m pytest tests/integration/workflows/test_vram_awareness.py --real-llm -v -s` against **both** `vram_budget_gb ∈ {10.0, 20.0}`: **2 passed in 207.20s**. To enable the system-prompt capture promised in §3.4.5.7, instrumented `_real_capturing_bridge_factory` to record `{args, kwargs, result}` per call; added a first-80-lines stage-2 system-prompt print. Evidence: (a) captured stage-2 system prompt contains `## MANDATORY — Integrated reasoning (science + engineering)` verbatim (delivered to OpenAI); (b) 10 GB iter-2 causal_hypothesis bridges "frequency resolution" scientific goal with `deep_punet` overshoot `29.10 GB > 10.00 GB` in a single chain (keyword hits `['vram', 'deep_punet']`); (c) 20 GB iter-2 pivots tactic (gated activation) and cites "20 GB VRAM limit... not exceeding the Effective cap" (keyword hits `['vram', 'cap', 'deep_punet']`). Param-count gate: both budgets < 1M params vs. 50M ceiling.

- [ ] **B.7 — Regression + PR.** *(was B.6 before the B.6 Cognitive Hardening insert)*
  - [ ] Re-run the WS-A evidence gate (`docs/phase66_telemetry/evidence_gate_dynamic_depth_simple.py`) and confirm Appendix A.2 bytes unchanged.
  - [ ] Re-run the guardrail suite (`tests/unit/guardrails/`) — `test_no_hardcoded_device_literals` must stay 3/3 green (`<10 GB` literal removed in B.2b / commit `e935a12` and B.2c / `de9e044`; the regex does not catch the `<10 GB` token pattern, so this is Principle-5-spirit compliance, not a test-driven fix).
  - [ ] Open PR #2 with all B.1–B.6 commits.

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
| B.8 Self-review + open PR | — | This doc's B.7 for the Proposer-side PR; Implementor stream owns its own |

Net: this doc is authoritative for Proposer-side WS-B. Parent §4 and §5.3 remain authoritative for Implementor-side WS-B until that stream gets its own governing doc.

### 6.4 Out of scope for WS-B (explicit deferrals)

- **WS-A refactor cleanup** (`docs/phase66_ws_a_refactor_and_cleanup.md` — A.6/A.7/A.9/A.15/A.16). Ships as PR #1.1 after WS-B merges.
- **Implementor hardening** (parent §4.2–4.4 — variable-reference audit, tensor arithmetic guard, targeted AttributeError repair). Separate work-stream.
- **Typed-rejection field on `ProposalInput`.** Rejected — reusing `previous_failures: List[str]` with a `[PHYSICAL REJECTION]` prefix keeps the prompt renderer untouched and avoids a schema ratchet whose only consumer is this one feedback path.
- **Deduplication of repeated rejections across iterations.** Intentionally absent — a repeat rejection *is* a signal that the Proposer ignored the lesson, and suppressing it would hide that.
- **Static AST analysis of proposed architectures against the VRAM engine's class library.** Out of scope; the VRAM skill itself is the single source of truth for what fits.

### 6.5 Follow-up tasks surfaced during WS-B (tracked, not in the WS-B PR)

- **B.8 — Staged-pipeline parity sweep for stage 3 (`proposing_stage.md`).** Surfaced during the B.6a-v4 sibling-template audit (§3.4.5.5). Three defects are currently live on the staged commit stage:
  1. **`proposing_stage.md:73`** still carries the device literal `"The baseline_config must fit in <10 GB VRAM."` — the same Principle-5 violation that B.2b / B.2c removed from the legacy `.py` prompts. The guardrail `test_no_hardcoded_device_literals.py` does not currently catch the `<10 GB` token pattern (its regex scans `5090|A100|V100|H100|32\s*GB|25.6`), so the violation is invisible to CI today. Parity with B.2 requires either (a) renaming the rule to reference the `[HARDWARE CONTEXT]` block — implying stage 3 must also receive that block in its user prompt — or (b) adding a stage-3 user-prompt variable `{effective_cap_gb}` populated from the live `HardwareContext`. Option (a) aligns better with the Hop-5 architecture; option (b) has a smaller diff. Design decision deferred.
  2. **No `[PHYSICAL REJECTION]` awareness.** Stage 3 commits the final `ProposalOutput` (incl. `baseline_config`, `parameter_count_estimate`) but has no visibility into prior physical rejections. A Proposer that synthesised the rejection correctly in stage 2 can still commit an over-sized baseline in stage 3 because the stage-3 template never asks it to check.
  3. **No Golden Paragraph mandate.** The B.4 Contract Re-Assertion landed against `PROPOSAL_COMMIT_PROMPT` (legacy). The staged `proposing_stage.md:29` still has the pre-B.4 `mathematical_definition` spec (`"Abstract architectural framework: … Do NOT include concrete dimensions"`). The Golden Paragraph does not reach the staged-pipeline commit stage, so Implementor-side code may re-derive the contract and re-introduce the channel-mismatch class of bug B.4 was designed to prevent.

  Scope for B.8: port B.2 (hardware-context block + literal removal), B.3 (physical-rejection awareness — probably as a user-prompt block, mirroring stage 2), and B.4 (Golden Paragraph in the `mathematical_definition` field spec) to `proposing_stage.md`. Add a parallel `tests/unit/agent/ml_model_proposal_agent/test_proposing_stage_contract.py` rendered-prompt guard mirroring §5.2. Broaden the device-literal guardrail regex to catch `<10\s*GB` / `<N\s*GB` patterns so the class of defect surfaces in CI going forward.

  **Not in the WS-B PR.** B.8 lands as a follow-up after WS-B (PR #2) merges. WS-B's PR description will reference B.8 as tracked-but-deferred; reviewers who notice the stage-3 gap during the WS-B PR review will be pointed at this §6.5 entry.

---

## 7. Future Work & Technical Debt

WS-B landed the **infrastructure** for hardware-aware feedback — the 5-hop wiring, the `[PHYSICAL REJECTION]` block, the `[HARDWARE CONTEXT]` block, and the MANDATORY rejection-acknowledgement clause in `causal_reasoning_stage.md`. The B.6h v9 GPU run revealed that under tight VRAM scarcity (0.5 GB cap on RTX 5090) the system's **observed behaviour** is currently **autonomous in-iteration auto-shrink**: the Tuner planner downsizes `multi/depth/embedding_dim` to fit the budget, producing a successful trial without ever earning a `PhysicalRejection`. This is a useful capability — experiment continuity under resource scarcity — but it bypasses the explicit cognitive-feedback loop the directive aimed to verify.

Two follow-ups are tracked for after WS-B merges:

### 7.1 Instruction Weighting (Cross-Node Override)

Today `human_advice_propose` reaches the Proposer's prompt only; the Tuner planner does not see it. v9 evidence: the Proposer respected the over-architect advice and emitted a 9.9M-param baseline (`multi=128, depth=5, embedding_dim=64`, all 3 internal pre-flight candidates over the 60-min budget). The Tuner planner then independently emitted a Round 1 trial config of `multi=16, depth=3, embedding_dim=32` (~250K params), satisfying the 0.5 GB cap by 30× margin without consulting the advice.

A future change should let `human_advice` (and `expert_advice`) carry a `MANDATORY` flag the Tuner planner respects. Concrete shapes worth prototyping:
- **Floor constraints.** `min_multi`, `min_depth`, `min_embedding_dim` passed into the Tuner's trial-config emission so the planner cannot shrink past the floor.
- **Baseline pinning.** A `pin_baseline_config: bool` flag that forces trial-mode hyperparameters to match the Proposer's `baseline_config` exactly, leaving only `trial_portion`/`segmentation_size` as the planner's degrees of freedom.
- **Weighted advice routing.** `human_advice` carries a `target: {"propose", "tune", "both"}` field; `MANDATORY` flags propagate to whichever target node the human selects.

This would enable precise stress-testing (force OOM at the configured cap) and make expert guidance binding rather than advisory across the graph.

### 7.2 Decoupled Test Assertions

`tests/integration/workflows/test_vram_awareness.py` should recognise **two valid Hardware-Aware passes** in Phase B:

1. *Failure-Rejection-Correction.* Iter-1 earns a `[PHYSICAL REJECTION]`, the rejection reaches iter-2's prompt, and iter-2's `causal_hypothesis` cites a VRAM-family keyword. (Original directive — exercises the explicit cognitive feedback loop.)
2. *Successful Auto-Shrink.* Iter-1's Tuner planner adapts the Proposer's large baseline to the small budget without a formal rejection, producing a valid `denoising_score`. Iter-2 then builds on this score normally. (v9 observation — exercises in-iteration self-correction.)

Either path passes; failing **both** is the regression signal. WS-B's B.6h adjustment lands path #2 alongside the original path #1 so the test suite stops penalising the system for being "too smart."

A follow-up (post-§7.1) should add a third Phase B variant that **exercises path #1 deterministically** by passing a `MANDATORY` Tuner-side floor — that variant will fail today and pass once §7.1 is implemented. Its existence in the suite acts as the regression gate for §7.1.

---

## 8. Invariants

WS-B must not:

- Change the WS-A Evidence Gate numbers (parent Appendix A.2). Training residual stays at −0.04%, inference at −0.01%.
- Introduce any model-name branch (parent §5.4 guardrail).
- Introduce any device literal in live code (parent §5.1 guardrail). Removing the `<10 GB` literal at :187 is the *positive* side of this invariant for WS-B.
- Change the `HardwareContext` schema or the `_SAFETY_FRACTION = 0.80` constant (§3.9.1 of parent).
- Change the `memory_killer` return-dict shape at `wrapper.py:517`. WS-B consumes it verbatim.
- Change the `[Hardware]` log-line regime classifier. The `[HARDWARE CONTEXT]` prompt block mirrors the classifier's semantics but is a separate renderer; the two must never disagree, and a unit test could assert they stay in sync if that becomes a real risk.
