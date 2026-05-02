# nodes/ml_model_proposal_agent.py
"""
ml_model_proposal_agent — Node 3 in the SIDERIUS graph.

Reads the structured interpretation from result_interpretation_agent and proposes
a new neural architecture that addresses the identified bottlenecks.

Uses a two-call chain-of-thought:
  1. Reasoning call (generate_text): free-form architectural reasoning — no JSON constraints,
     so the LLM can think deeply about bottlenecks, architecture families, and tradeoffs.
  2. Commit call (generate): given the reasoning, commit to a specific design as strict JSON
     matching ProposalOutput.

Consumed by ml_model_implementor via proposal_to_implementor_v1, and by
tune_ml_hyperparam_agent via proposal_to_hyperparam_seeded_v1.

Node contract:
  run(input: ProposalInput) -> ProposalOutput
  CLI: --workspace, --run_name, --provider, --model_id
"""

import os
import json
import argparse

from pydantic import ValidationError

from typing import Any, Dict, List, Optional

from agent.llm_bridge import LLMBridge
from agent.prompts import _format_known_constraints_block
from agent.schemas.proposal import ProposalInput, ProposalOutput, FalsifiablePrediction
from agent.schemas.storage import StorageConfig, LocalStorageConfig
from agent.schemas.hyperparam_tuning import GateExhaustionInfo, serialize_expert_advice
from core.hardware_context import HardwareContext
from agent.utils.architectural_pattern_tagger import ARCHITECTURAL_PATTERNS
from agent.utils.proposer_preflight import estimate_proposal_time
from execute_tools.dataset_config import TIDMAD as DATASET_CONFIG

# Maximum number of retries when the proposing stage produces invalid output.
# Total attempts = _MAX_PROPOSING_RETRIES + 1.
_MAX_PROPOSING_RETRIES = 2

# One retry when causal_reasoning produces a prediction below minimum_boldness.
_MAX_REASONING_RETRIES = 1

# Fix 2 Commit 6 — total number of proposing-stage calls the pre-flight
# revision loop is allowed. 1 initial draft + 2 revisions. The structural-
# retry loop (_MAX_PROPOSING_RETRIES) is nested inside each pre-flight
# attempt; schema errors do not burn a pre-flight budget slot.
_MAX_PREFLIGHT_ATTEMPTS = 3


def _active_time_budget_minutes(inp: ProposalInput) -> float | None:
    """Select the budget the pre-flight gate should check against.

    Returns ``None`` when the relevant budget is unset — the caller treats
    that as "pre-flight disabled for this proposal" rather than "budget=0".
    """
    if inp.is_trial:
        return inp.trial_time_budget_minutes
    return inp.formal_time_budget_minutes


def _build_preflight_rejection_block(
    num_params: int,
    estimated_minutes: float,
    factor: float,
    budget_minutes: float,
) -> str:
    """Render the prescriptive ``[PRE-FLIGHT REJECTION]`` block.

    Decision 7 (§9 Commit 6): all four numeric substitutions must appear so
    the LLM's next revision is grounded in concrete numbers, not a vague
    "too slow" signal. Vague feedback produces vague revisions.
    """
    return (
        f"[PRE-FLIGHT REJECTION]\n"
        f"Based on your estimated {num_params:,} parameters, the static cost "
        f"model predicts a {estimated_minutes:.1f} min runtime, which is "
        f"{factor:.1f}x over the {budget_minutes:.1f} min budget.\n"
        f"Please simplify the architecture or use a more efficient model "
        f"family. To fit within the budget you must reduce compute by roughly "
        f"{factor:.1f}x — reduce parameter_count_estimate, reduce depth/width, "
        f"or switch to a lighter architectural class (e.g. TCN, FFT-based, or "
        f"windowed-attention) if the current family is structurally too "
        f"expensive at the active segmentation_size."
    )


def _run_preflight_check(
    inp: ProposalInput,
    output: ProposalOutput,
) -> float | None:
    """Evaluate the static-formula pre-flight gate on a candidate ``output``.

    Mutates ``output`` in place: sets ``preflight_estimated_minutes`` and
    ``preflight_factor`` when the gate runs; appends a ``PREFLIGHT_SKIPPED``
    note to ``memo_consistency_notes`` when the LLM failed to supply a
    usable ``parameter_count_estimate``.

    Returns the numeric ``factor`` when the gate ran, or ``None`` when it
    was skipped (budget disabled, or params missing / non-positive). The
    caller uses ``None`` as the "pre-flight inconclusive — do not revise"
    signal.
    """
    budget = _active_time_budget_minutes(inp)
    if budget is None:
        return None

    num_params = output.parameter_count_estimate
    if num_params is None or num_params <= 0:
        output.memo_consistency_notes.append(
            "PREFLIGHT_SKIPPED: parameter_count_estimate was None or "
            "non-positive; pre-flight gate could not run for this draft."
        )
        return None

    baseline = output.baseline_config or {}
    verdict = estimate_proposal_time(
        model_type=output.model_name,
        model_config=baseline.get("model_config") or {},
        train_config=baseline.get("train_config") or {},
        loss_config=baseline.get("loss_config") or {},
        num_params=num_params,
        time_budget_minutes=budget,
        train_portion=inp.train_portion,
        trial_portion=inp.trial_portion,
    )
    output.preflight_estimated_minutes = verdict["estimated_minutes"]
    output.preflight_factor = verdict["factor"]
    return verdict["factor"]


def _check_citation_discipline(
    citation_sources: list,
    causal_hypothesis: str,
    proposed_change: str,
) -> list:
    """Return a warning message for each cite_id that was cited but not referenced.

    Each cite_id in citation_sources must appear verbatim in causal_hypothesis
    or proposed_change.  Violations are soft warnings — the proposal is not
    rejected, but the issues are appended to ProposalOutput.memo_consistency_notes
    so the validator and the human reviewer can see them.

    Args:
        citation_sources: list of cite_id strings from DiscoveryMemo.
        causal_hypothesis: the reasoning text that should reference the cited items.
        proposed_change: the change description that should reference the cited items.

    Returns:
        List of violation strings, one per uncited cite_id.  Empty = all citations
        are properly referenced in the reasoning text.
    """
    combined = causal_hypothesis + " " + proposed_change
    violations = []
    for cite_id in citation_sources:
        if cite_id not in combined:
            violations.append(
                f"CITATION_NOT_REFERENCED: cite_id '{cite_id}' is listed in "
                f"citation_sources but does not appear verbatim in causal_hypothesis "
                f"or proposed_change. Either reference it in your reasoning or remove "
                f"it from citations."
            )
    return violations


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

PROPOSAL_REASONING_PROMPT = """\
You are a senior ML architect specialising in deep learning for signal denoising.

Your task: given a structured analysis of past hyperparameter tuning experiments
across one or more model architectures, reason deeply about what new neural
architecture could best overcome the identified bottlenecks.

Background on the task:
- Input data: TIDMAD SQUID magnetometry time-series, integer ADC values 0–255,
  signal length up to 40000 timesteps per segment.
- The model must satisfy this forward contract (non-negotiable):
    input:  [B, T]       int64   — raw signal, integer class indices
    output: [B, 256, T]  float32 — per-timestep logits over 256 denoising classes
- This is offline denoising — the output at position t may depend on all positions.
  Causal constraints are not required.
- Loss is cross-entropy or focal loss: per-timestep 256-class classification.
- The VRAM ceiling is published in the [HARDWARE CONTEXT] block at the top of
  the user message — treat that block's "Effective cap" as the hard limit,
  and keep `parameter_count_estimate` under ~100M for initial exploration.

In your reasoning, cover all of the following:
1. What structural weakness do the bottlenecks and take-home message specifically point to?
   Be concrete — name the architectural property that is limiting performance.
2. What architecture families could address that weakness?
   Consider: multi-scale convolutions, attention mechanisms, CNN+attention hybrids,
   state-space models (Mamba/S4), temporal convolution networks, etc.
   Discuss the tradeoffs of each in the context of this task.
3. Which approach do you think is most promising, and why?
   Justify your choice by connecting it directly to the identified bottlenecks.
4. What are the key design choices (depth, width, kernel sizes, attention heads, etc.)
   for a safe, moderate baseline configuration that fits within the GPU budget?
   Note: keep the mathematical_definition abstract (computational principles, not shapes).
   Concrete dimensions belong only in baseline_config.
5. What are the likely failure modes of this architecture?
   What should the hyperparameter tuning agent watch out for?
6. Per-file analysis and trial strategy guidance:
   - Read each model's per-file score table by `Impact_Score` descending — that is
     the per-iter opportunity ranking. Cite `Linear_Weight` as context, not as a
     ranking metric on its own. Identify whether the largest remaining
     `Impact_Score` levers concentrate on a small subset of files or are
     distributed broadly, and whether the same files dominate across models —
     those are the cross-model opportunities the new architecture should target.
     Do not assert that any file is universally weak from `headroom_vs_gt` alone
     or from a fixed file-index label.
   - Recommend a trial strategy for the hyperparameter tuner:
     * What trial_portion to start with (based on model complexity — larger models need more data)
     * How many epochs for initial screening vs refinement
     * Whether to use "snapshot" (broad coverage), "target" (concentrate on the
       highest-Impact_Score files), or "anchors" (small fixed subset)
     * Whether the architecture is data-hungry (needs high trial_portion) or data-efficient

Think step by step. Be specific. Reference actual scores, model names, and the
`Impact_Score` / `Linear_Weight` columns of the per-file score table. Do not
produce JSON — that is the next step."""


PROPOSAL_COMMIT_PROMPT = """\
You are a senior ML architect. You have just completed a detailed reasoning step
about a new architecture proposal. Now commit to a specific design.

Output a JSON object with exactly these fields:

{
  "model_name": "short_snake_case_key",
  "model_description": "One paragraph plain-English description of the architecture and why it is expected to improve on the current best.",
  "mathematical_definition": "Must open with a three-sentence 'Golden Paragraph' that cites: (1) the forward contract verbatim — 'Input: [B, T] int64 (per-timestep ADC class indices). Output: [B, 256, T] float32 (per-timestep logits over 256 denoising classes)'; (2) the segmentation semantics — state whether the body is segment-local (no cross-segment state) or segment-cross (e.g. global attention within a segment), and whether causal masking is required; (3) the fixed dimension '256 denoising bins per time step is contract-fixed, not a hyperparameter'. After the Golden Paragraph, describe the architectural framework abstractly: key computational stages, mathematical operations, data flow. Do NOT include concrete layer dimensions, kernel sizes, or channel counts — those belong in baseline_config.",
  "motivation": "Why this specific architecture addresses the bottlenecks from the interpretation. Must reference the take-home message directly and name at least one specific bottleneck.",
  "expert_advice": {
    "focus_areas": ["What to prioritise during hyperparameter tuning for this architecture"],
    "constraints": ["Hard limits — must include at least one VRAM limit and one parameter count limit"],
    "known_failures": ["Configs or approaches to avoid, based on patterns in the interpretation"],
    "suggested_directions": [
      "Concrete first experiments to try, e.g. 'start with depth=2, lr=1e-4'",
      "Trial strategy guidance: recommended trial_portion (e.g. 0.1 for data-hungry models)",
      "Recommended epochs for screening (1-3) vs refinement (5-10)",
      "Whether to use snapshot/target/anchors strategy based on the Impact_Score distribution",
      "Which files (by Impact_Score ranking, not by fixed indices) to focus on if using target strategy"
    ],
    "rationale": "Why this guidance is appropriate for this specific architecture. Include reasoning about data volume needs and per-file lever distribution from the Impact_Score column."
  },
  "baseline_config": {
    "model_config": { ... architecture-specific hyperparameter fields ... },
    "train_config": {
      "lr": 1e-4,
      "epochs": 10,
      "batch_size": 1,
      "optimizer_type": "adamw",
      "weight_decay": 1e-5,
      "device": "cuda"
    },
    "loss_config": { "loss_type": "focal", "alpha": 0.5, "gamma": 2.0, "reduction": "mean" }
  },
  "parameter_count_estimate": 1234567
}

Hard constraints — violating any of these makes the proposal invalid:
- model_name must NOT be any of the existing model types listed in the context
- model_name must be snake_case: lowercase letters, digits, and underscores only
- The forward contract is fixed: input [B, T] int64 → output [B, 256, T] float32
- baseline_config must be conservative: fits comfortably within the effective cap shown in the [HARDWARE CONTEXT] (the VRAM gate rejects anything above it)
- expert_advice.constraints must include at least one VRAM limit and one parameter count limit
- parameter_count_estimate must be a positive integer — your best estimate of the total
  trainable parameter count at the baseline_config. An order-of-magnitude estimate is
  sufficient; be realistic about multi-head attention, state dims, dilated stacks, etc.
  This drives the proposer-side pre-flight cost check.

Output only the JSON object — no preamble, no markdown fences, no commentary."""


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _render_hardware_context_block(
    ctx: Optional[HardwareContext],
    vram_budget_gb: Optional[float],
) -> str:
    """Render the ``[HARDWARE CONTEXT]`` prompt block.

    Mirrors the three regimes of ``wrapper.py``'s ``[Hardware]`` log
    classifier (PHYSICAL / BUDGET / PHYSICAL VETO). See
    docs/phase66_ws_b_proposer_hardening.md §3.1.

    Returns ``""`` when ``ctx`` is None or ``device_available=False`` —
    CPU-only runs and legacy callers get no block injected, preserving
    back-compat with prompts rendered pre-WS-B.

    Regime selection:
      - ``vram_budget_gb is None``                 → PHYSICAL       (cap = usable_cap_gb)
      - ``vram_budget_gb <= usable_cap_gb``        → BUDGET         (cap = vram_budget_gb)
      - ``vram_budget_gb  > usable_cap_gb``        → PHYSICAL VETO  (cap = usable_cap_gb; operator ceiling is above the 80% physical safety floor and therefore ignored)
    """
    if ctx is None or not ctx.device_available:
        return ""

    usable = ctx.usable_cap_gb
    if vram_budget_gb is None:
        regime, effective = "PHYSICAL", usable
    elif vram_budget_gb <= usable:
        regime, effective = "BUDGET", vram_budget_gb
    else:
        regime, effective = "PHYSICAL VETO", usable

    lines = [
        "[HARDWARE CONTEXT]",
        f"Device:            {ctx.device_name}",
        f"Total VRAM:        {ctx.total_memory_gb:.2f} GB",
        f"Usable cap (80%):  {usable:.2f} GB",
        f"Host:              {ctx.hostname}",
    ]
    if vram_budget_gb is not None:
        lines.append(f"Operator budget:   {vram_budget_gb:.2f} GB")
        lines.append(f"Effective cap:     {effective:.2f} GB")

    if regime == "PHYSICAL":
        lines.append(
            f"Regime:            PHYSICAL — no operator budget set; cap = {effective:.2f} GB."
        )
    elif regime == "BUDGET":
        lines.append(
            "Regime:            BUDGET — operator's budget is the binding ceiling."
        )
    else:  # PHYSICAL VETO
        lines.append(
            "Regime:            PHYSICAL VETO — operator budget exceeds the 80%"
        )
        lines.append(
            "                   physical safety floor; the physical cap wins."
        )

    lines.append("")
    lines.append(
        "Your baseline_config must fit within the **effective cap** shown above. "
        "The VRAM engine will reject any architecture whose predicted peak exceeds "
        "this ceiling; a rejection consumes a tuner attempt with no scored round. "
        "Size your baseline to stay comfortably below the cap (target ≤ 80% of the "
        "effective cap at baseline) so the tuner has headroom to vary batch_size "
        "and segmentation_size upward."
    )
    return "\n".join(lines)


def _format_recent_gate_exhaustions_block(
    entries: List[GateExhaustionInfo],
) -> str:
    """Render the [RECENT GATE EXHAUSTIONS] block per §14.N.3.

    Aggregate-window successor to the K.7.6 singular helper: carries the
    structured failure reports from up to the last 3 tuner iterations so
    the next proposer can spot *repeated* abort-class failures on the same
    architecture family and switch family rather than shrink.

    Empty list → "" so callers can unconditionally splice the result into
    a template (no empty section, no header).

    Non-empty list → header tagged with the entry count, each entry
    labelled with a relative iteration tag (``iter N-k``, oldest first,
    ``iter N-1`` = most recent), entries separated by a horizontal rule,
    and a closing paragraph that tells the LLM to switch family when the
    same failure mode recurs. See docs/resource_estimator_implement.md §14.N.
    """
    if not entries:
        return ""

    def _num(v, suffix=""):
        return f"{v}{suffix}" if v is not None else "n/a"

    def _factor(v):
        return f"{v:.2f}×" if v is not None else "n/a"

    def _entry_lines(info: GateExhaustionInfo, label: str) -> list:
        lines = [
            f"{label}",
            info.summary_message,
            "",
            "Resource accounting:",
            f"  Mode active:       {info.active_mode}",
            f"  VRAM budget:       {_num(info.vram_budget_gb, ' GB')}",
            f"  Time budget:       {_num(info.time_budget_minutes, ' min')}",
            f"  Baseline factors:  VRAM {_factor(info.baseline_vram_factor)}   "
            f"Time {_factor(info.baseline_time_factor)}",
            f"  Worst factors:     VRAM {_factor(info.worst_vram_factor)}      "
            f"Time {_factor(info.worst_time_factor)}",
            f"  Attempt counts:    {info.total_attempts} total, "
            f"{info.vram_gated_attempts} VRAM-gated,",
            f"                     {info.time_gated_attempts} time-gated, "
            f"{info.other_failure_attempts} other failures",
        ]
        # Fix 1 — surface structured architectural bans as a hard DO-NOT-PROPOSE
        # block. Tags are rendered with their English descriptions imported
        # from the tagger (single source of truth). Only tags with a
        # registered description appear; unknown tags are dropped defensively
        # (the completeness invariant in the tagger's tests prevents this in
        # practice). See docs/reliable_resource_proposer.md §9 Commit 4.
        described = [
            (t, ARCHITECTURAL_PATTERNS[t])
            for t in info.disallowed_architectural_patterns
            if t in ARCHITECTURAL_PATTERNS
        ]
        if described:
            lines += ["", "[DISALLOWED PATTERNS] DO NOT PROPOSE:"]
            for tag, description in described:
                lines.append(f"  - {tag}: {description}")
        return lines

    n = len(entries)
    plural = "s" if n > 1 else ""
    separator = "-" * 68
    lines = [f"[RECENT GATE EXHAUSTIONS (last {n} iteration{plural})]"]

    for i, info in enumerate(entries):
        # entries[0] is oldest → iter N-n ... entries[-1] is newest → iter N-1
        rel = n - i
        suffix = " (most recent)" if rel == 1 else ""
        label = f"iter N-{rel}{suffix}:"
        if i > 0:
            lines += ["", separator, ""]
        lines += _entry_lines(info, label)

    lines += [
        "",
        "For this iteration: if the same architecture family or scale appears",
        "in multiple entries above, that is a strong signal the family is",
        "structurally infeasible under the active budgets — propose a",
        "different family, not a smaller variant of the same family. If only",
        "a single entry is shown, reduce parameter count and/or layer count",
        "enough that the resulting baseline estimates land below the budgets.",
    ]
    return "\n".join(lines)


def _render_stage_user_prompt(accumulated: Dict[str, Any]) -> str:
    """Render a pipeline-stage user prompt: native markdown + clean JSON.

    Splits the stage user prompt into two concatenated regions:

    * **Top-level markdown** — one section per candidate, carrying the full
      `ScoreComparisonTable.rendered_markdown` + fenced source code block.
      This is what the LLM reads for high-density per-file reasoning. Empty
      when there are no candidates.
    * **JSON region** — scalar metadata (`best_score`, `model_params`, etc.),
      non-candidate overview one-liners, `interpretation_summary`, and the
      rest of the pipeline state.

    Before dumping the JSON region, we:

    * Strip `score_table`, `source_code`, `source_code_lines` from every
      candidate entry (the heavy content now lives in the top-level markdown).
    * Drop `per_model_score_tables` from `interpretation_summary` — redundant
      with the top-level markdown and the non-candidate `score_summary` lines.
    """
    from nodes.proposal_helpers import (
        build_candidate_markdown_block,
        strip_heavy_fields_for_json,
    )

    candidates = accumulated.get("candidates") or []
    markdown_block = build_candidate_markdown_block(candidates)

    cleaned: Dict[str, Any] = dict(accumulated)
    cleaned["candidates"] = strip_heavy_fields_for_json(candidates)
    interp_summary = cleaned.get("interpretation_summary")
    if isinstance(interp_summary, dict) and "per_model_score_tables" in interp_summary:
        cleaned["interpretation_summary"] = {
            k: v for k, v in interp_summary.items() if k != "per_model_score_tables"
        }

    json_region = (
        "## Accumulated context\n\n"
        "```json\n"
        + json.dumps(cleaned, indent=2, default=str)
        + "\n```"
    )
    if markdown_block:
        return f"{markdown_block}\n{json_region}"
    return json_region


def _truncate_description(text: str, max_chars: int = 1500) -> str:
    """Truncate a model description for prompt injection."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n[...truncated]"


def _build_reasoning_prompt(inp: ProposalInput) -> str:
    """Build the user prompt for the reasoning call."""
    interp = inp.interpretation
    lines = []

    # Phase 6.6 WS-B (B.2 bleed-over, landed with B.1 for Level-2 validation):
    # Render the [HARDWARE CONTEXT] block at the top of the user prompt so the
    # Proposer sees the effective VRAM ceiling (PHYSICAL / BUDGET / PHYSICAL
    # VETO regime) before any interpretation data. Empty string on CPU-only /
    # legacy-caller runs — no visible change for pre-WS-B test fixtures.
    hw_block = _render_hardware_context_block(inp.hardware_context, inp.vram_budget_gb)
    if hw_block:
        lines += [hw_block, ""]

    lines += [
        "## Interpretation Summary",
        f"Models analysed     : {interp.get('model_types', [])}",
        f"Total experiments   : {interp.get('total_experiments', 'unknown')}",
        f"Overall best score  : {interp.get('best_denoising_score')}",
        f"Overall worst score : {interp.get('worst_denoising_score')}",
        "",
    ]

    per_best  = interp.get("per_model_best",  {})
    per_worst = interp.get("per_model_worst", {})
    if per_best:
        lines.append("### Per-model scores")
        for mt in interp.get("model_types", []):
            lines.append(f"  {mt}: best={per_best.get(mt)}  worst={per_worst.get(mt)}")
        lines.append("")

    findings = interp.get("key_findings", [])
    if findings:
        lines.append("### Key Findings")
        for f in findings:
            lines.append(f"  - {f}")
        lines.append("")

    bottlenecks = interp.get("bottlenecks", [])
    if bottlenecks:
        lines.append("### Bottlenecks")
        for b in bottlenecks:
            lines.append(f"  - {b}")
        lines.append("")

    lines += [
        "### Take-home message",
        interp.get("take_home_message", ""),
        "",
    ]

    # Phase E — prediction track record (scientific accuracy + information gain)
    sci_acc   = interp.get("scientific_accuracy")
    cum_ig    = interp.get("cumulative_information_gain")
    pred_hist = interp.get("prediction_outcomes_history") or {}
    if sci_acc is not None or cum_ig is not None:
        lines.append("### Prediction Track Record")
        total = sum(pred_hist.values()) if pred_hist else 0
        if cum_ig is not None:
            lines.append(f"  Cumulative information gain : {cum_ig:.3f}")
        if sci_acc is not None:
            confirmed_pct = sci_acc.get("confirmed", 0.0) * 100
            partial_pct   = sci_acc.get("partial",   0.0) * 100
            refuted_pct   = sci_acc.get("refuted",   0.0) * 100
            lines.append(
                f"  Scientific accuracy (N={total}) : "
                f"confirmed={confirmed_pct:.0f}%  "
                f"partial={partial_pct:.0f}%  "
                f"refuted={refuted_pct:.0f}%"
            )
        lines.append("")

    # Phase C — vocabulary health
    vdr = interp.get("vocab_diversity_ratio")
    if vdr is not None:
        lines += [
            "### Vocabulary Health",
            f"  Diversity ratio : {vdr:.2f}  "
            f"({'LOW — consider proposing new vocabulary entries' if vdr < 0.1 else 'OK'})",
            "",
        ]

    # Per-file analysis (from enriched interpretation)
    per_file_comp = interp.get("per_file_comparison")
    if per_file_comp:
        lines += ["### Per-File Comparison (cross-model)", per_file_comp, ""]

    eff_comp = interp.get("efficiency_comparison")
    if eff_comp:
        lines += ["### Efficiency Comparison (cross-model)", eff_comp, ""]

    # Per-model score tables — full rendered_markdown per model (Phase 5 C).
    # Legacy path has no ModelSelectionStrategy to split on, so every model
    # gets the complete 3-column table (raw_baseline / ground_truth / model)
    # plus the subset-scoped aggregate scalars.
    score_tables = interp.get("per_model_score_tables")
    if score_tables:
        lines.append("### Per-model score tables")
        lines.append("")
        for mt, table in score_tables.items():
            rendered = table.get("rendered_markdown") if isinstance(table, dict) else None
            if not rendered:
                continue
            lines.append(f"#### {mt}")
            lines.append(rendered)
            lines.append("")

    # Per-model efficiency
    model_params = interp.get("per_model_params")
    if model_params:
        lines.append("### Model Parameters")
        for mt, params in model_params.items():
            score = per_best.get(mt)
            lines.append(f"  {mt}: {params:,} params → score {score}")
        lines.append("")

    # Per-model training data volume
    training_segs = interp.get("per_model_training_segments")
    if training_segs:
        lines.append("### Training Data Volume (PSD segments)")
        for mt, segs in training_segs.items():
            lines.append(f"  {mt}: {segs} segments (baseline=4000)")
        lines.append("")

    descriptions = interp.get("model_descriptions", {})
    if descriptions:
        lines.append("## Existing Architecture Descriptions")
        for mt, desc in descriptions.items():
            lines += [f"### {mt}", _truncate_description(desc), ""]

    best_config = interp.get("best_config")
    if best_config:
        lines += [
            "## Best Config So Far",
            json.dumps(best_config, indent=2),
            "",
        ]

    lines += [
        "## Constraints",
        f"Existing model type keys (your model_name must NOT be any of these): {inp.existing_model_types}",
    ]
    for c in inp.constraints:
        lines.append(f"  - {c}")
    lines.append("")

    if inp.previous_failures:
        lines.append("## Previous Failed Proposals (DO NOT repeat these mistakes)")
        for i, failure in enumerate(inp.previous_failures, 1):
            lines.append(f"  {i}. {failure}")
        lines.append("")

    # Phase N (§14.N) — aggregate-window cross-iteration gate-exhaustion
    # report. Rendered from up to the last 3 tuner iterations so the
    # proposer can spot repeated abort-class failures on the same family
    # and switch family rather than shrink. Empty list → no block.
    gate_block = _format_recent_gate_exhaustions_block(inp.recent_gate_exhaustions)
    if gate_block:
        lines += [gate_block, ""]

    # --- Expert advice (from upstream agents) ---
    expert_advice_str = serialize_expert_advice(inp.expert_advice) if inp.expert_advice else ""
    if expert_advice_str:
        lines += [
            "## Expert Guidance (from upstream agents)",
            expert_advice_str,
            "",
        ]

    if inp.human_advice:
        lines.append("## Human Expert Advice (high priority — address these explicitly)")
        if isinstance(inp.human_advice, str):
            lines.append(inp.human_advice)
        else:
            adv = inp.human_advice
            if adv.focus_areas:
                lines.append("### Focus areas")
                for item in adv.focus_areas:
                    lines.append(f"  - {item}")
            if adv.constraints:
                lines.append("### Additional constraints")
                for item in adv.constraints:
                    lines.append(f"  - {item}")
            if adv.known_failures:
                lines.append("### Known failures to avoid")
                for item in adv.known_failures:
                    lines.append(f"  - {item}")
            if adv.suggested_directions:
                lines.append("### Suggested directions")
                for item in adv.suggested_directions:
                    lines.append(f"  - {item}")
            if adv.rationale:
                lines += ["### Rationale", adv.rationale]
        lines.append("")

    return "\n".join(lines)


def _build_commit_prompt(reasoning: str, existing_model_types: list) -> str:
    """Build the user prompt for the commit call, injecting the reasoning."""
    return (
        f"## Your Reasoning\n\n{reasoning}\n\n"
        f"---\n\n"
        f"## Reminder — your model_name must NOT be any of: {existing_model_types}\n\n"
        "Now output the JSON proposal."
    )


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

class MLModelProposalAgent:
    """
    Proposal agent — Node 3 in the SIDERIUS graph.

    Supports two modes:
      - **Legacy mode**: 2-call pattern (reasoning + commit). Used when
        ``reasoning_pipeline`` has no stages or ``use_pipeline=False``.
      - **Pipeline mode**: 3-stage configurable pipeline (comparison →
        causal reasoning → proposing). Used when ``reasoning_pipeline``
        has stages configured. See docs/adaptive_new_model_proposer.md §2A.

    Constructor DI (``bridge_factory``) follows PR #24's pattern: optional
    factory param, defaults to the real ``LLMBridge`` class. Tests can
    inject a ``RecordingLLMBridge``. The existing ``(provider, model_id)``
    interface is preserved for backward compat.
    """

    def __init__(self, provider: str = "gemini", model_id: str = "gemini-3.1-flash-lite-preview",
                 max_retries: int | None = None, bridge_factory=None, **kwargs):
        # **kwargs absorbs per-stage kwargs from ProposalLLMConfig flattening
        # (comparison_provider, reasoning_model_id, etc.) — these are for
        # future per-stage bridge routing, currently unused.
        self._bridge_factory = bridge_factory or LLMBridge
        self.bridge = self._bridge_factory(
            provider=provider, model_id=model_id, max_retries=max_retries,
        )

    def run(self, inp: ProposalInput) -> ProposalOutput:
        print(f"Proposing new architecture based on interpretation of "
              f"{inp.interpretation.get('model_types', [])} ...")

        # Decide: pipeline mode or legacy mode
        has_pipeline = (
            inp.reasoning_pipeline
            and inp.reasoning_pipeline.stages
            and any(s.enabled for s in inp.reasoning_pipeline.stages)
        )

        if has_pipeline:
            output = self._run_pipeline(inp)
        else:
            output = self._run_legacy(inp)

        # --- Persist ---
        if inp.storage.backend == "local" and inp.storage.local:
            workspace = inp.storage.local.workspace
            run_name  = inp.storage.local.run_name
            os.makedirs(workspace, exist_ok=True)
            out_path = os.path.join(workspace, f"proposal_{run_name}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(output.model_dump_json(indent=4))
            print(f"Proposal saved -> {out_path}")

        return output

    # ------------------------------------------------------------------
    # Legacy mode (existing 2-call pattern, backward compat)
    # ------------------------------------------------------------------

    def _run_legacy(self, inp: ProposalInput) -> ProposalOutput:
        """Original 2-call pattern: reasoning (text) + commit (JSON).

        Wrapped with the Fix 2 Commit 6 pre-flight revision loop: up to
        ``_MAX_PREFLIGHT_ATTEMPTS`` commit calls, with ``[PRE-FLIGHT
        REJECTION]`` appended on each revision. Legacy mode has no
        structural-retry inner loop — a schema-violating draft raises
        immediately (unchanged behavior).
        """
        reasoning_prompt = _build_reasoning_prompt(inp)
        print(f"    [PROMPT_SIZE] proposer_reasoning: {len(reasoning_prompt)} chars")
        reasoning = self.bridge.generate_text(PROPOSAL_REASONING_PROMPT, reasoning_prompt)
        print(f"   Legacy reasoning complete ({len(reasoning)} chars).")

        base_commit_prompt = _build_commit_prompt(reasoning, inp.existing_model_types)
        budget = _active_time_budget_minutes(inp)
        preflight_errors: list[str] = []
        candidates: list[ProposalOutput] = []

        for preflight_attempt in range(_MAX_PREFLIGHT_ATTEMPTS):
            commit_prompt = base_commit_prompt
            if preflight_errors:
                commit_prompt = (
                    base_commit_prompt
                    + "\n\n---\n\n"
                    + "\n\n".join(preflight_errors)
                )

            raw = self.bridge.generate(PROPOSAL_COMMIT_PROMPT, commit_prompt)

            proposed_name = raw.get("model_name", "")
            if proposed_name in inp.existing_model_types:
                raise ValueError(
                    f"LLM proposed model_name '{proposed_name}' which already exists in "
                    f"existing_model_types: {inp.existing_model_types}. "
                    f"Re-run or adjust the constraints."
                )

            output = ProposalOutput.model_validate({
                "model_name":               proposed_name,
                "model_description":        raw.get("model_description", ""),
                "mathematical_definition":  raw.get("mathematical_definition", ""),
                "motivation":               raw.get("motivation", ""),
                "expert_advice":            raw.get("expert_advice", {}),
                "baseline_config":          raw.get("baseline_config", {}),
                "parameter_count_estimate": raw.get("parameter_count_estimate"),
            })

            factor = _run_preflight_check(inp, output)
            if factor is None or factor <= 1.0:
                print(f"Proposed model (legacy): '{output.model_name}'")
                return output

            candidates.append(output)
            if preflight_attempt < _MAX_PREFLIGHT_ATTEMPTS - 1:
                preflight_errors.append(
                    _build_preflight_rejection_block(
                        num_params=output.parameter_count_estimate,
                        estimated_minutes=output.preflight_estimated_minutes,
                        factor=factor,
                        budget_minutes=budget,
                    )
                )
                print(
                    f"   Pre-flight rejected (factor={factor:.2f}x); "
                    f"requesting revision {preflight_attempt + 2}/"
                    f"{_MAX_PREFLIGHT_ATTEMPTS}."
                )

        best = min(candidates, key=lambda o: o.preflight_factor)
        best.memo_consistency_notes.append(
            f"PREFLIGHT_OVERBUDGET_EMITTED: all {_MAX_PREFLIGHT_ATTEMPTS} "
            f"pre-flight attempts exceeded the {budget:.1f} min budget; "
            f"emitting lowest-factor candidate "
            f"(factor={best.preflight_factor:.2f}x, "
            f"estimated {best.preflight_estimated_minutes:.1f} min). "
            f"The tuner's real-data gate may still reject this at trial time."
        )
        print(
            f"Proposed model (legacy, pre-flight exhausted): '{best.model_name}' "
            f"factor={best.preflight_factor:.2f}x"
        )
        return best

    # ------------------------------------------------------------------
    # Pipeline mode (B.11 + B.12 — 3-stage reasoning pipeline)
    # ------------------------------------------------------------------

    def _run_pipeline(self, inp: ProposalInput) -> ProposalOutput:
        """Three-stage pipeline: comparison → reasoning → proposing."""
        from nodes.proposal_helpers import (
            select_candidate_models,
            resolve_exploration_mode,
            enrich_candidates_with_source,
            build_score_summary_line,
        )
        from agent.prompt_templates.proposal import load_stage_prompt, render_expert_context, render_agent_cards

        pipeline = inp.reasoning_pipeline
        policy = pipeline.policy

        # B.16a — resolve exploration mode
        mode = resolve_exploration_mode(inp.interpretation, pipeline)
        print(f"   Pipeline mode: {mode} | stages: {[s.name for s in pipeline.stages if s.enabled]}")

        # B.10 — pre-filter models
        candidates = select_candidate_models(inp.interpretation, pipeline.model_selection)
        # Enrich with source code + descriptions for the comparison stage
        candidates = enrich_candidates_with_source(candidates)
        source_counts = sum(1 for c in candidates if c.get("source_code"))

        # Build lightweight summaries for models excluded by the pre-filter.
        # These models were tested but did not make the top-N cut. Their source
        # code is intentionally omitted (that is the point of filtering), but
        # the LLM still needs to know: what was tried, why it fell short, and
        # what we learned — so it can avoid repeating past failures and build
        # on partial successes.
        _CACHE_TEXT_FIELDS = (
            "key_findings", "bottlenecks", "score_trend", "strategy_assessment",
        )
        candidate_names = {c["model_type"] for c in candidates}
        cache = inp.interpretation.get("model_knowledge_cache") or {}
        descriptions = inp.interpretation.get("model_descriptions") or {}
        per_best = inp.interpretation.get("per_model_best") or {}
        score_tables = inp.interpretation.get("per_model_score_tables") or {}

        non_candidates_overview = []
        for mt in inp.interpretation.get("model_types", []):
            if mt in candidate_names:
                continue
            entry = cache.get(mt) or {}
            overview: dict = {
                "model_type": mt,
                "best_score": per_best.get(mt),
                "description": descriptions.get(mt),
            }
            # Phase 5 C: compact score-table summary so the LLM sees the
            # per-file recovery context without the 20-row markdown weight.
            summary_line = build_score_summary_line(score_tables.get(mt))
            if summary_line:
                overview["score_summary"] = summary_line
            for field in _CACHE_TEXT_FIELDS:
                if entry.get(field):
                    overview[field] = entry[field]
            non_candidates_overview.append(overview)

        print(f"   Candidates: {[c['model_type'] for c in candidates]} "
              f"({len(candidates)} models, {source_counts} with source code); "
              f"non-candidates: {[o['model_type'] for o in non_candidates_overview]}")

        # Prepare shared context for all stages
        agent_cards_block = render_agent_cards(inp.agent_cards)
        expert_context_block = render_expert_context(inp.expert_context)
        vocab_block = self._render_vocabulary(inp.vocab_seed)

        # --- Run enabled reasoning stages (accumulate context) ---
        accumulated = {
            "candidates": candidates,
            "non_candidates_overview": non_candidates_overview,
            "interpretation_summary": {
                k: inp.interpretation.get(k)
                for k in (
                    "model_types", "total_experiments", "best_denoising_score",
                    "worst_denoising_score", "key_findings", "bottlenecks",
                    "take_home_message", "per_model_best", "per_model_worst",
                    "per_model_score_tables",
                    # Phase E — prediction track record (surfaced to all stages)
                    "scientific_accuracy", "cumulative_information_gain",
                    "prediction_outcomes_history",
                    # Phase C — vocabulary health metric
                    "vocab_diversity_ratio",
                )
                if inp.interpretation.get(k) is not None
            },
            "existing_model_types": inp.existing_model_types,
            "previous_failures": inp.previous_failures,
        }

        # Count confirmed feature→capability links: entries with non-empty related_to.
        def _get_related(entry) -> list:
            if hasattr(entry, "related_to"):
                return getattr(entry, "related_to") or []
            if isinstance(entry, dict):
                return entry.get("related_to") or []
            return []

        n_confirmed_links = sum(
            1 for v in inp.vocab_seed if _get_related(v)
        )
        template_vars = {
            "minimum_boldness": str(policy.minimum_boldness),
            "n_agent_proposed": str(len([
                c for c in candidates if c.get("source") != "seed"
            ])),
            "n_confirmed_links": str(n_confirmed_links),
            "existing_model_types": ", ".join(inp.existing_model_types),
            # Proposing-stage placeholder. Other stages don't reference it; the
            # template_vars replace is a no-op when the placeholder is absent.
            # See docs/improving_validation_awareness.md Phase A.2/A.3.
            "known_constraints_block": _format_known_constraints_block(DATASET_CONFIG),
            # Phase N (§14.N.3) — proposing-stage placeholder for the
            # aggregate-window gate-exhaustion report across up to the
            # last 3 tuner iterations. Empty list collapses to "".
            "recent_gate_exhaustions_block": _format_recent_gate_exhaustions_block(
                inp.recent_gate_exhaustions
            ),
        }

        for stage in pipeline.stages:
            if not stage.enabled:
                continue

            # Map system_prompt_key to filename:
            # COMPARATIVE_ANALYSIS → comparison_stage
            # CAUSAL_REASONING → causal_reasoning_stage
            stage_file_map = {
                "COMPARATIVE_ANALYSIS": "comparison_stage",
                "CAUSAL_REASONING": "causal_reasoning_stage",
            }
            stage_filename = stage_file_map.get(
                stage.system_prompt_key,
                stage.system_prompt_key.lower() + "_stage",
            )
            system_prompt = load_stage_prompt(
                stage_filename,
                exploration_mode=mode,
                template_vars=template_vars,
                mindset=inp.mindset,
            )

            # Build user prompt: candidate markdown block + JSON region + cards + context + vocab
            user_prompt = _render_stage_user_prompt(accumulated)
            if agent_cards_block:
                user_prompt += f"\n\n{agent_cards_block}"
            if expert_context_block:
                user_prompt += f"\n\n{expert_context_block}"
            if vocab_block:
                user_prompt += f"\n\n{vocab_block}"

            print(f"   Stage '{stage.name}': calling LLM... "
                  f"[PROMPT_SIZE] {len(user_prompt)} chars")
            if stage.output_mode == "text":
                result = self.bridge.generate_text(system_prompt, user_prompt)
                accumulated[stage.name] = result
            else:
                result = self.bridge.generate(system_prompt, user_prompt)
                accumulated[stage.name] = result

            print(f"   Stage '{stage.name}': done.")

        # --- Boldness check: re-run causal_reasoning if prediction is too timid ---
        # Mirrors the B.22 proposing-stage retry but targets Stage 2 specifically.
        # Stage 1 (comparison) is expensive; we never re-run it for a boldness violation.
        reasoning_raw = accumulated.get("causal_reasoning")
        if isinstance(reasoning_raw, dict):
            pred_raw = reasoning_raw.get("falsifiable_prediction")
            if pred_raw and isinstance(pred_raw, dict):
                try:
                    pred = FalsifiablePrediction.model_validate(pred_raw)
                    if pred.boldness < policy.minimum_boldness:
                        print(
                            f"   Boldness check: boldness={pred.boldness:.4f} < "
                            f"minimum_boldness={policy.minimum_boldness} — "
                            f"retrying causal_reasoning."
                        )
                        accumulated.setdefault("proposing_stage_errors", []).append(
                            f"BOLDNESS_TOO_LOW: prediction boldness={pred.boldness:.4f} "
                            f"is below minimum_boldness={policy.minimum_boldness}. "
                            f"Current: {pred.current_value}, "
                            f"Predicted: {pred.predicted_value}. "
                            f"Make a bolder prediction — increase the delta between "
                            f"current and predicted value."
                        )
                        reasoning_stage = next(
                            (s for s in pipeline.stages
                             if s.name == "causal_reasoning" and s.enabled),
                            None,
                        )
                        if reasoning_stage is not None:
                            retry_system = load_stage_prompt(
                                "causal_reasoning_stage",
                                exploration_mode=mode,
                                template_vars=template_vars,
                                mindset=inp.mindset,
                            )
                            retry_user = _render_stage_user_prompt(accumulated)
                            if agent_cards_block:
                                retry_user += f"\n\n{agent_cards_block}"
                            if expert_context_block:
                                retry_user += f"\n\n{expert_context_block}"
                            if vocab_block:
                                retry_user += f"\n\n{vocab_block}"
                            print("   Stage 'causal_reasoning': retrying (boldness)...")
                            accumulated["causal_reasoning"] = self.bridge.generate(
                                retry_system, retry_user
                            )
                except (ValidationError, Exception):
                    pass  # malformed prediction — let the proposing stage handle it

        # --- B.12 + B.22: Proposing stage (always runs last, retries on validation failure) ---
        proposing_prompt = load_stage_prompt(
            "proposing_stage",
            exploration_mode=mode,
            template_vars=template_vars,
        )

        # Phase K.8 debug instrumentation: optionally dump the rendered
        # proposing-stage system prompt so smoke runs can audit the exact
        # text the LLM saw (in particular the K.7.6 [PRIOR ITERATION GATE
        # EXHAUSTION] block). No-op when the field is None (default).
        if inp.debug_dump_proposing_prompt_path:
            from pathlib import Path
            dump_path = Path(inp.debug_dump_proposing_prompt_path)
            dump_path.parent.mkdir(parents=True, exist_ok=True)
            dump_path.write_text(proposing_prompt)
            print(f"   [debug] dumped proposing-stage system prompt → {dump_path}")

        # Extract scientific content from reasoning stages once — these don't change on retry.
        reasoning_output = accumulated.get("causal_reasoning", {})
        comparison_output = accumulated.get("comparison", {})
        if not isinstance(reasoning_output, dict):
            reasoning_output = {}
        if not isinstance(comparison_output, dict):
            comparison_output = {}

        inherited = reasoning_output.get("inherited_components", [])
        prediction = reasoning_output.get("falsifiable_prediction")
        vocab_links = comparison_output.get("proposed_vocab_links", [])
        # Separate candidates by kind: feature/capability → vocab pipeline; discovery → discoveries
        vocab_candidates = []
        discoveries = []
        for stage_output in [comparison_output, reasoning_output]:
            for candidate in stage_output.get("proposed_vocab_candidates", []):
                if not isinstance(candidate, dict):
                    continue
                kind = candidate.get("kind", "")
                if kind in {"feature", "capability"}:
                    vocab_candidates.append(candidate)
                elif kind == "discovery":
                    discoveries.append(candidate)

        # Fix 2 Commit 6 — two-layer loop: the outer pre-flight revision
        # loop wraps the existing structural-retry inner loop. Schema errors
        # are handled by the inner loop (burn structural-retry slots); pre-
        # flight rejections are handled by the outer loop (burn pre-flight
        # slots). Stages 1+2 are never re-run from either loop.
        budget = _active_time_budget_minutes(inp)
        preflight_candidates: list[ProposalOutput] = []

        for preflight_attempt in range(_MAX_PREFLIGHT_ATTEMPTS):
            output: ProposalOutput | None = None
            last_exc: Exception | None = None

            for attempt in range(_MAX_PROPOSING_RETRIES + 1):
                proposing_user = _render_stage_user_prompt(accumulated)
                if agent_cards_block:
                    proposing_user += f"\n\n{agent_cards_block}"
                if expert_context_block:
                    proposing_user += f"\n\n{expert_context_block}"

                print(
                    f"   Stage 'proposing': calling LLM "
                    f"(pre-flight {preflight_attempt + 1}/{_MAX_PREFLIGHT_ATTEMPTS}, "
                    f"structural {attempt + 1}/{_MAX_PROPOSING_RETRIES + 1})..."
                )
                raw = self.bridge.generate(proposing_prompt, proposing_user)

                try:
                    proposed_name = raw.get("model_name", "")
                    if proposed_name in inp.existing_model_types:
                        raise ValueError(
                            f"model_name '{proposed_name}' already exists in "
                            f"existing_model_types: {inp.existing_model_types}. "
                            f"Choose a different name."
                        )

                    output = ProposalOutput.model_validate({
                        "model_name":               proposed_name,
                        "model_description":        raw.get("model_description", ""),
                        "mathematical_definition":  raw.get("mathematical_definition", ""),
                        "motivation":               raw.get("motivation", ""),
                        "expert_advice":            raw.get("expert_advice", {}),
                        "baseline_config":          raw.get("baseline_config", {}),
                        "inherited_components":     inherited,
                        "falsifiable_prediction":   prediction,
                        "proposed_vocab_links":     vocab_links,
                        "proposed_vocab_candidates": vocab_candidates,
                        "proposed_discoveries":     discoveries,
                        "memo_consistency_notes":   raw.get("memo_consistency_notes", []),
                        "parameter_count_estimate": raw.get("parameter_count_estimate"),
                    })
                    # Citation discipline — warnings, not hard failures.
                    citation_violations = _check_citation_discipline(
                        citation_sources=reasoning_output.get("citation_sources", []),
                        causal_hypothesis=reasoning_output.get("causal_hypothesis", ""),
                        proposed_change=reasoning_output.get("proposed_change", ""),
                    )
                    if citation_violations:
                        output.memo_consistency_notes.extend(citation_violations)
                        print(
                            f"   Citation check: {len(citation_violations)} "
                            f"violation(s) appended to memo_consistency_notes."
                        )
                    break  # structurally valid — proceed to pre-flight

                except (ValidationError, ValueError) as exc:
                    last_exc = exc
                    if isinstance(exc, ValidationError):
                        error_summary = "; ".join(
                            f"{' → '.join(str(l) for l in e['loc'])}: {e['msg']}"
                            for e in exc.errors()[:5]
                        )
                    else:
                        error_summary = str(exc)

                    if attempt < _MAX_PROPOSING_RETRIES:
                        print(
                            f"   Proposing attempt {attempt + 1} failed — "
                            f"injecting error and retrying."
                        )
                        errors_so_far = accumulated.get("proposing_stage_errors", [])
                        errors_so_far.append(
                            f"Attempt {attempt + 1} error: {error_summary}. "
                            f"Correct this in your next response."
                        )
                        accumulated["proposing_stage_errors"] = errors_so_far

            if output is None:
                raise RuntimeError(
                    f"Proposing stage failed after {_MAX_PROPOSING_RETRIES + 1} "
                    f"structural attempts. Last error: {last_exc}"
                ) from last_exc

            # ---- Outer: pre-flight cost gate on the structurally-valid draft ----
            factor = _run_preflight_check(inp, output)
            if factor is None or factor <= 1.0:
                print(f"Proposed model (pipeline): '{output.model_name}'")
                return output

            preflight_candidates.append(output)
            if preflight_attempt < _MAX_PREFLIGHT_ATTEMPTS - 1:
                rejection = _build_preflight_rejection_block(
                    num_params=output.parameter_count_estimate,
                    estimated_minutes=output.preflight_estimated_minutes,
                    factor=factor,
                    budget_minutes=budget,
                )
                errors_so_far = accumulated.get("proposing_stage_errors", [])
                errors_so_far.append(rejection)
                accumulated["proposing_stage_errors"] = errors_so_far
                print(
                    f"   Pre-flight rejected (factor={factor:.2f}x); "
                    f"requesting revision "
                    f"{preflight_attempt + 2}/{_MAX_PREFLIGHT_ATTEMPTS}."
                )

        best = min(preflight_candidates, key=lambda o: o.preflight_factor)
        best.memo_consistency_notes.append(
            f"PREFLIGHT_OVERBUDGET_EMITTED: all {_MAX_PREFLIGHT_ATTEMPTS} "
            f"pre-flight attempts exceeded the {budget:.1f} min budget; "
            f"emitting lowest-factor candidate "
            f"(factor={best.preflight_factor:.2f}x, "
            f"estimated {best.preflight_estimated_minutes:.1f} min). "
            f"The tuner's real-data gate may still reject this at trial time."
        )
        print(
            f"Proposed model (pipeline, pre-flight exhausted): "
            f"'{best.model_name}' factor={best.preflight_factor:.2f}x"
        )
        return best

    @staticmethod
    def _render_vocabulary(vocab_seed: list) -> str:
        """Render the full vocabulary seed into a prompt block.

        Renders all four kinds: feature, capability, discovery, candidate.
        Discoveries carry empirical CONFIRMED/REFUTED/PARTIAL outcomes and are
        critical for the feedback loop — the proposer must see them.
        """
        if not vocab_seed:
            return ""

        # Handle both VocabEntry objects and dicts
        def _get(entry, key, default=""):
            if hasattr(entry, key):
                return getattr(entry, key)
            if isinstance(entry, dict):
                return entry.get(key, default)
            return default

        features     = [v for v in vocab_seed if _get(v, "kind") == "feature"]
        capabilities = [v for v in vocab_seed if _get(v, "kind") == "capability"]
        discoveries  = [v for v in vocab_seed if _get(v, "kind") == "discovery"]
        candidates   = [v for v in vocab_seed if _get(v, "kind") == "candidate"]

        lines = ["## Vocabulary\n"]

        if features:
            lines.append("### Features (concrete building blocks)")
            for v in features:
                pattern = _get(v, "pattern")
                pat_str = f" [pattern: {pattern}]" if pattern else ""
                related = _get(v, "related_to", [])
                rel_str = f" → enables: {', '.join(related)}" if related else ""
                lines.append(f"- **{_get(v, 'name')}**: {_get(v, 'description')}{pat_str}{rel_str}")
            lines.append("")

        if capabilities:
            lines.append("### Capabilities (measurable architectural properties)")
            for v in capabilities:
                related = _get(v, "related_to", [])
                rel_str = f" ← enabled by: {', '.join(related)}" if related else ""
                lines.append(f"- **{_get(v, 'name')}**: {_get(v, 'description')}{rel_str}")
            lines.append("")

        if discoveries:
            lines.append("### Discoveries (empirical outcomes — CONFIRMED/REFUTED/PARTIAL)")
            lines.append("These are the results of past falsifiable predictions. "
                         "Use them to avoid repeating failures and to build on confirmed findings.")
            for v in discoveries:
                lines.append(f"- **{_get(v, 'name')}**: {_get(v, 'description')}")
            lines.append("")

        if candidates:
            lines.append("### Candidates (proposed but not yet confirmed)")
            for v in candidates:
                lines.append(f"- **{_get(v, 'name')}**: {_get(v, 'description')}")
            lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="SIDERIUS ml_model_proposal_agent")
    parser.add_argument("--workspace", type=str, default="./siderius_workspace",
                        help="Root directory for reading interpretation output and writing proposal")
    parser.add_argument("--run_name",  type=str, default="v1",
                        help="Run name — reads interpretation_{run_name}.json, "
                             "writes proposal_{run_name}.json")
    parser.add_argument("--provider",  type=str, default="gemini", choices=["gemini", "openai"])
    parser.add_argument("--model_id",  type=str, default="gemini-3.1-flash-lite-preview")
    args = parser.parse_args()

    interp_path = os.path.join(args.workspace, f"interpretation_{args.run_name}.json")
    if not os.path.exists(interp_path):
        raise FileNotFoundError(
            f"Interpretation file not found: {interp_path}\n"
            f"Run result_interpretation_agent first, or check --workspace and --run_name."
        )
    with open(interp_path, "r", encoding="utf-8") as f:
        interpretation = json.load(f)

    agent_input = ProposalInput.model_validate({
        "interpretation": interpretation,
        "storage": {
            "backend": "local",
            "local": {"workspace": args.workspace, "run_name": args.run_name},
        },
    })
    print(f"✅ Input validated: models={interpretation.get('model_types')} | "
          f"experiments={interpretation.get('total_experiments')}")

    agent = MLModelProposalAgent(provider=args.provider, model_id=args.model_id)
    output = agent.run(agent_input)

    print(f"\n{'='*60}")
    print(f"  Proposal — {output.model_name}")
    print(f"{'='*60}")
    print(f"  Description : {output.model_description}")
    print(f"  Motivation  : {output.motivation}")
    print(f"\n  Mathematical definition:")
    print(f"    {output.mathematical_definition[:500]}...")
    print(f"\n  Expert advice:")
    print(f"    Focus areas    : {output.expert_advice.focus_areas}")
    print(f"    Constraints    : {output.expert_advice.constraints}")
    print(f"    Suggested dirs : {output.expert_advice.suggested_directions}")
    print(f"\n  Baseline config:")
    print(f"    {json.dumps(output.baseline_config, indent=4)}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
