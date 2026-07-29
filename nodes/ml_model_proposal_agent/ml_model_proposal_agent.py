# nodes/ml_model_proposal_agent/ml_model_proposal_agent.py
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

import argparse
import json
import os
from typing import Any, cast

from pydantic import ValidationError

from agent.llm_bridge import LLMBridge
from agent.prompt_templates.proposal import live_loss_registry_names
from agent.prompts import _format_known_constraints_block
from agent.schemas.hyperparam_tuning import GateExhaustionInfo
from agent.schemas.proposal import FalsifiablePrediction, ProposalInput, ProposalOutput
from agent.schemas.task_config import ForwardContract
from agent.utils.architectural_pattern_tagger import ARCHITECTURAL_PATTERNS
from agent.utils.proposer_preflight import estimate_proposal_time
from agent_generated._registry import CapabilityRegistry
from core.hardware_context import HardwareContext
from execute_tools.dataset_config import TIDMAD as DATASET_CONFIG
from workflows.task_config import render_forward_contract

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


def _live_model_registry_names(registry: CapabilityRegistry) -> list[str]:
    """Return the intersection of the capability index and the live
    ``MODEL_REGISTRY``.

    Fix for phantom Branch B model reuse. The implementor writes a
    ``CapabilityMetadata`` entry to ``agent_generated/_capability_index.json``
    *before* the code validator runs (``ml_model_implementor.py`` line 1690).
    If validation subsequently fails the entry stays in the index, so the
    next iteration's proposer sees the failed model as a Branch B reuse
    candidate. That is the v16 iter_015 loss-chain failure mode
    (``gated_dilated_tcn`` proposed in iter_009, never validated, offered
    to iter_015's proposer as reusable).

    ``ml_models.models_sandbox.MODEL_REGISTRY`` is populated only by
    ``register_model_in_memory``, which the workflow calls from
    ``_promote_model_to_global`` — after successful validation. It is the
    correct source of truth for "what has actually validated and is loadable
    right now."

    We keep the index as the source of the *metadata* (description,
    mathematical_definition) needed to render the ``{available_models_block}``
    prompt, but for the phantom-Branch-B validator context we filter to the
    intersection so ``ProposalOutput.model_validate`` only accepts
    ``model_name`` values that will actually load at training time.

    Returns:
        Sorted list of names present in both the capability index and the
        live in-memory ``MODEL_REGISTRY``. Empty list when the intersection
        is empty (fresh workspace or all indexed models are phantoms).
    """
    from ml_models.models_sandbox import MODEL_REGISTRY

    indexed = {m.name for m in registry.list(capability_type="model")}
    live = set(MODEL_REGISTRY.keys())
    return sorted(indexed & live)


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
        data_scope=inp.data_scope,
    )
    output.preflight_estimated_minutes = verdict["estimated_minutes"]
    output.preflight_factor = verdict["factor"]
    return verdict["factor"]


def _check_citation_discipline(
    source_refs: list,
    causal_hypothesis: str,
    proposed_change: str,
) -> list:
    """Return a warning message for each source_ref that was cited but not referenced.

    Each source_ref in source_refs must appear verbatim in causal_hypothesis
    or proposed_change.  Violations are soft warnings — the proposal is not
    rejected, but the issues are appended to ProposalOutput.memo_consistency_notes
    so the validator and the human reviewer can see them.

    Args:
        source_refs: list of source_ref strings from DiscoveryMemo.
        causal_hypothesis: the reasoning text that should reference the cited items.
        proposed_change: the change description that should reference the cited items.

    Returns:
        List of violation strings, one per uncited source_ref.  Empty = all citations
        are properly referenced in the reasoning text.
    """
    combined = causal_hypothesis + " " + proposed_change
    violations = []
    for source_ref in source_refs:
        if source_ref not in combined:
            violations.append(
                f"CITATION_NOT_REFERENCED: source_ref '{source_ref}' is listed in "
                f"source_refs but does not appear verbatim in causal_hypothesis "
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

{TASK_BACKGROUND}- The VRAM ceiling is published in the [HARDWARE CONTEXT] block at the top of
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


def _render_task_background(task_description: str, fc: ForwardContract) -> str:
    """Render the ``{TASK_BACKGROUND}`` placeholder block for
    ``PROPOSAL_REASONING_PROMPT`` and the proposing-stage ``.md``
    templates.

    Returns the multi-line block ``Background on the task:`` header + a
    bullet for the task description + the rendered forward contract, with
    a trailing newline so the template's next line (``- The VRAM
    ceiling...``) follows naturally. Returns ``""`` when both
    ``task_description`` and ``fc`` are empty — only reachable from test
    fixtures that don't go through ``load_task_config`` (production
    callers always populate both).

    Mirrors the helper of the same name in
    ``nodes/ml_model_implementor/ml_model_implementor.py`` (T2) so that
    both agents render the task framing identically.
    """
    if not task_description and fc.is_empty():
        return ""
    parts = ["Background on the task:"]
    if task_description:
        parts.append(f"- {task_description}")
    fc_block = render_forward_contract(fc)
    if fc_block:
        parts.append(fc_block)
    # Trailing empty string → final "\n" so the next template line (the
    # VRAM-ceiling bullet) starts on a fresh line.
    parts.append("")
    return "\n".join(parts)


def _build_reasoning_system_prompt(inp: ProposalInput) -> str:
    """Substitute the ``{TASK_BACKGROUND}`` placeholder in
    ``PROPOSAL_REASONING_PROMPT`` from ``inp``.

    Production callers always have ``inp.task_description`` non-empty and
    ``inp.forward_contract`` fully populated (workflow injects from
    ``load_task_config()``); test fixtures may leave both at defaults, in
    which case the placeholder collapses to ``""``.
    """
    return PROPOSAL_REASONING_PROMPT.replace(
        "{TASK_BACKGROUND}",
        _render_task_background(inp.task_description, inp.forward_contract),
    )


def _render_cold_start_block(cold_start: bool) -> str:
    """Explicit cold-start banner for the proposer USER prompt.

    Non-empty ONLY when ``cold_start`` is True; returns the empty string
    otherwise so that seeded (history-backed) prompts are byte-for-byte
    unchanged. Communicates that no prior experimental evidence exists, treats
    registries as available options (not past results), and forbids claiming
    improvement over a non-existent history.
    """
    if not cold_start:
        return ""
    return (
        "[COLD START — NO PRIOR EXPERIMENTAL EVIDENCE]\n"
        "This is the first iteration of the chain. No prior experimental runs, "
        "scores, model history, or failures exist yet. Do not reference or claim "
        "improvement over previous results — there are none. Propose the first "
        "experiment grounded in the task contract, the available model and loss "
        "registries (listed below as available options, not past results), the "
        "advice, and the resource constraints."
    )


def _render_data_scope_block(scope) -> str:
    """Render the ``[DATA SCOPE]`` prompt block (DS7b).

    Returns ``""`` for a full scope — pre-DataScope prompts are
    byte-for-byte unchanged. Under a partial scope the proposer is told
    which files exist for this run and that sampling is snapshot-only, so
    drafts are not designed around out-of-scope data. Disclosure only —
    enforcement is the tuner/sandbox's job.
    """
    from execute_tools.dataset_config import TIDMAD as _TIDMAD

    if scope is None or scope.is_full(_TIDMAD):
        return ""
    resolved = scope.resolve(_TIDMAD)
    return (
        "[DATA SCOPE]\n"
        f"This run is restricted to validation files {resolved} — the ONLY\n"
        "files any training, inference, or scoring may access. Sampling is\n"
        "snapshot-only under this restriction (anchors/target strategies are\n"
        "normalized away). Design the proposal for THESE files' data; do not\n"
        "reason about, or optimize for, out-of-scope files."
    )


def _render_hardware_context_block(
    ctx: HardwareContext | None,
    vram_budget_gb: float | None,
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
        lines.append("Regime:            BUDGET — operator's budget is the binding ceiling.")
    else:  # PHYSICAL VETO
        lines.append("Regime:            PHYSICAL VETO — operator budget exceeds the 80%")
        lines.append("                   physical safety floor; the physical cap wins.")

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


def _render_constraints_block(
    constraints: list[str],
    existing_model_types: list[str],
) -> str:
    """Render the ``## Constraints`` prompt block (Commit P-d).

    Restores the constraints render path in pipeline mode. Pre-P-d this
    block was assembled only inside the legacy ``_build_reasoning_prompt``
    (at line 762-764), so production runs — which use pipeline mode
    exclusively — never saw `ProposalInput.constraints` nor the
    "your model_name must NOT be any of these" reminder list. This helper
    fixes that and is called at the top of every stage's user prompt by
    ``_run_pipeline``.

    Empty inputs yield an empty string so callers can skip-append in the
    same idiom as ``_render_hardware_context_block``.

    The proposing-stage `existing_model_types` name-uniqueness rule also
    reaches the LLM via the proposing system prompt's template variable
    ``{existing_model_types}``; rendering it again at the top of the user
    prompt is a deliberate redundancy — name-uniqueness is a frequent
    violation and the prompt is long enough that one reference at the top
    of the system prompt is insufficient signal.
    """
    if not constraints and not existing_model_types:
        return ""

    lines = ["## Constraints"]
    if existing_model_types:
        lines.append(
            f"Existing model type keys (your `model_name` must NOT be any of "
            f"these): {list(existing_model_types)}"
        )
    for c in constraints or []:
        lines.append(f"  - {c}")
    return "\n".join(lines)


def _format_recent_gate_exhaustions_block(
    entries: list[GateExhaustionInfo],
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


def _format_healthgate_evidence_block(interp: dict[str, Any]) -> str:
    """Render the flag-gated ``[HEALTHGATE EVIDENCE]`` block (V19 PR 3 §3.7).

    Source of truth is EXCLUSIVELY the deterministic interpretation fields
    (``per_model_round_health_counts``, ``per_model_collapse_fingerprints``,
    ``collapse_fingerprint_history``) — never ``key_findings`` or any other
    LLM prose. Distinct from the §14.N gate-exhaustion block (abort-class
    resource failures), which is untouched and rendered separately.

    Semantics:

    * Legacy interpretation dicts (all three fields absent) and empty
      evidence → ``""`` (no header — callers splice unconditionally).
    * Evidence is grouped by model exactly as CB3 grouped it; nothing is
      aggregated across models and nothing is rendered unlabelled.
    * History entries are POST-retention (merge-time expiry, design §3.8),
      so every occurrence bucket shown is inside the retained window —
      counts here are retained-window counts by construction, never
      lifetime totals; iteration tags are the buckets' absolute
      iterations.
    * Entry-level raw metrics follow the representative-observation rule
      (§3.8) and are labelled as such — one representative value, not a
      summary of every occurrence.
    * A malformed hand-built history entry (missing required keys) raises
      a diagnostic ``ValueError`` naming the model — never silent
      evidence loss or cross-model misattribution.
    """
    counts_by_model = interp.get("per_model_round_health_counts") or {}
    fps_by_model = interp.get("per_model_collapse_fingerprints") or {}
    history_by_model = interp.get("collapse_fingerprint_history") or {}
    if not counts_by_model and not fps_by_model and not history_by_model:
        return ""

    # Model order: interpretation's model_types first (matches the
    # per-model scores section), then any evidence-only models — nothing
    # silently dropped.
    ordered = list(interp.get("model_types") or [])
    for extra in sorted(set(counts_by_model) | set(fps_by_model) | set(history_by_model)):
        if extra not in ordered:
            ordered.append(extra)

    lines = [
        "[HEALTHGATE EVIDENCE] (deterministic, from the health-gate system — "
        "distinct from the resource-gate report above)"
    ]
    rendered_any = False
    for mt in ordered:
        counts = counts_by_model.get(mt)
        fps = fps_by_model.get(mt) or []
        history = history_by_model.get(mt) or []
        if not counts and not fps and not history:
            continue
        rendered_any = True
        lines += ["", f"### {mt}"]
        if counts:
            lines.append(
                f"Round validity (this iteration): {counts.get('valid', 0)} valid, "
                f"{counts.get('invalid', 0)} invalid, {counts.get('unknown', 0)} unknown"
            )
        if fps:
            lines.append("This iteration's collapse fingerprints:")
            for fp in fps:
                lines.append(f"  - {fp['signature']} — {fp.get('human_readable', '')}")
        if history:
            lines.append(
                "Retained history (bounded window; counts are retained-window "
                "occurrences, not lifetime totals):"
            )
            for entry in history:
                try:
                    signature = entry["signature"]
                    occurrences = entry["occurrences"]
                except (KeyError, TypeError) as e:
                    raise ValueError(
                        f"Malformed collapse_fingerprint_history entry for model "
                        f"{mt!r}: missing {e} — refusing to render partial "
                        f"evidence (silent loss / misattribution risk)"
                    ) from e
                total = sum(o["count"] for o in occurrences)
                iters = ", ".join(str(o["iteration"]) for o in occurrences)
                lines.append(f"  - {signature}: {total} occurrence(s) across iteration(s) {iters}")
                metrics = entry.get("metrics") or {}
                if metrics:
                    rendered = "; ".join(f"{k}={v}" for k, v in sorted(metrics.items()))
                    lines.append(f"      Representative observation: {rendered}")
                source_ids = [i for o in occurrences for i in o.get("source_exp_ids", [])]
                if source_ids:
                    lines.append(
                        f"      Source experiments (recent, bounded): {', '.join(source_ids)}"
                    )
    if not rendered_any:
        return ""

    lines += [
        "",
        "Rules for using this evidence:",
        "  - Do not repeat a fingerprinted failure mode without naming a "
        "concrete mechanism expected to break it.",
        "  - The mechanism must change the actual relevant configuration "
        "(architecture family, output activation, normalization, loss, "
        "optimizer/training policy) — not merely the explanation text.",
        "  - A high raw score from an invalid round is a failure, not a success.",
        "  - Do not avoid unrelated healthy strategies merely because another model failed.",
        "  - Do not transfer one model's failure evidence to another model without justification.",
        "  - Do not claim this feedback was used unless the proposal actually "
        "changes a relevant mechanism.",
    ]
    return "\n".join(lines)


def _render_stage_user_prompt(accumulated: dict[str, Any]) -> str:
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

    cleaned: dict[str, Any] = dict(accumulated)
    cleaned["candidates"] = strip_heavy_fields_for_json(candidates)
    interp_summary = cleaned.get("interpretation_summary")
    if isinstance(interp_summary, dict) and "per_model_score_tables" in interp_summary:
        cleaned["interpretation_summary"] = {
            k: v for k, v in interp_summary.items() if k != "per_model_score_tables"
        }

    json_region = (
        "## Accumulated context\n\n```json\n" + json.dumps(cleaned, indent=2, default=str) + "\n```"
    )
    if markdown_block:
        return f"{markdown_block}\n{json_region}"
    return json_region


# Keys in `accumulated` that came in from `ProposalInput` (vs. produced by
# upstream proposer stages such as `comparison`, `causal_reasoning`,
# `proposing_stage_errors`). Used by `_audit_proposer_components` to
# attribute prompt characters to the prior-stage-output bucket.
_PROPOSER_INPUT_KEYS = {
    "candidates",
    "non_candidates_overview",
    "interpretation_summary",
    "existing_model_types",
    "previous_failures",
}


def _extract_prior_stage_keys(accumulated: dict[str, Any]) -> dict[str, Any]:
    """Return the subset of ``accumulated`` produced by earlier proposer stages.

    Anything not in :data:`_PROPOSER_INPUT_KEYS` is treated as a stage output
    (``comparison``, ``causal_reasoning``, ``proposing_stage_errors``, etc.).
    """
    return {k: v for k, v in accumulated.items() if k not in _PROPOSER_INPUT_KEYS}


def _audit_proposer_components(
    *,
    inp: ProposalInput,
    accumulated: dict[str, Any],
    agent_cards_block: str,
    expert_context_block: str,
    vocab_block: str,
    system_prompt: str,
    stage_name: str,
) -> dict[str, Any]:
    """Pre-merge char-count breakdown of a proposer LLM call (§1.3).

    Returns a 10-key ``components`` dict suitable for ``bridge.generate(
    components=...)``, plus a ``stage_name`` and ``total_chars`` for tests
    and ad-hoc debugging. The breakdown mirrors the structure of the user
    prompt assembled by :func:`_render_stage_user_prompt` and the per-call-
    site appends of ``agent_cards_block`` / ``expert_context_block`` /
    ``vocab_block``. Each value is the char count of that component
    *before* tokenization, so a downstream report can localise bloat to a
    specific source even when the provider's tokenizer is opaque.

    Empty / missing blocks (``""`` or absent dict keys) yield ``0`` for
    that component — never a missing key. The 10 keys are stable and
    enforced by ``test_audit_components.py``.

    Commit 4.3.3 (Rev 8, 2026-05-05): added ``non_candidates_overview`` as
    a dedicated content key. The forensic audit (§8 Commit 4.3.2) showed
    this field carries a per-model dump pulled from ``model_descriptions``
    + ``model_knowledge_cache`` and grew from 15 K → 111 K chars between
    iter 1 and iter 14 of the V12 explore run — the dominant contributor
    (113 % of the catch-all delta) to the false ``template_and_scaffolding``
    11× signal. With this key live, the catch-all returns to its true
    fixed-template baseline (~8 K chars) and Phase 2 surgery operates on
    a trustworthy breakdown.

    Note (Commit 4.2, 2026-05-04): the audit hook covers the 10 *content*
    payloads injected into the user prompt, but not the template wrapper
    text (section headers, key-value preludes, stage instructions) added
    by the ``_build_*_prompt`` builders. Gate T1 measured that wrapper
    overhead at ~7.5-8.3 K chars per proposer call. To keep the row-level
    audit lossless, ``LLMBridge._record_usage`` augments the dict on
    write with a catch-all key ``template_and_scaffolding``
    (= ``chars.total - sum(this hook's 10)``). The hook itself is
    intentionally unaware of that key — it only reports content payloads
    it can derive from inputs.
    """
    from nodes.proposal_helpers import build_candidate_markdown_block

    # ---- candidates_markdown: identical computation to _render_stage_user_prompt
    candidates = accumulated.get("candidates") or []
    candidates_markdown_chars = len(build_candidate_markdown_block(candidates))

    # ---- interpretation_json: drop per_model_score_tables exactly like
    # _render_stage_user_prompt does, then serialise. Empty dict / missing
    # → empty JSON object literal "{}", contributing 2 chars.
    interp_summary = accumulated.get("interpretation_summary")
    if isinstance(interp_summary, dict) and "per_model_score_tables" in interp_summary:
        interp_summary = {k: v for k, v in interp_summary.items() if k != "per_model_score_tables"}
    interpretation_json_chars = len(json.dumps(interp_summary or {}, default=str))

    # ---- non_candidates_overview: list of per-non-candidate-model summary
    # dicts (lines 1010-1034), each carrying full ``description`` from
    # ``model_descriptions`` plus 4 cache fields (``key_findings``,
    # ``bottlenecks``, ``score_trend``, ``strategy_assessment``) drawn from
    # ``model_knowledge_cache``. Sized via the same compact serialization
    # used for ``interpretation_json`` / ``prior_stage_outputs`` for
    # consistency. Missing → ``[]`` → ``len("[]") == 2``. Promoted to a
    # named key by Commit 4.3.3 (Rev 8) after the §8 forensic audit
    # measured this single field at 15 K → 111 K chars across iter 1 → 14
    # of the V12 explore run — the dominant contributor (113 % of the Δ)
    # to the false ``template_and_scaffolding`` 11× growth signal.
    non_candidates_overview = accumulated.get("non_candidates_overview")
    non_candidates_overview_chars = len(json.dumps(non_candidates_overview or [], default=str))

    # ---- prior_stage_outputs: stage-produced keys, with heavy candidate
    # fields stripped to mirror what actually lands in the user prompt.
    prior_stage_payload = _extract_prior_stage_keys(accumulated)
    # candidates is an input key (handled separately above), but if a stage
    # ever overwrites it the markdown block already reflects that — leave
    # prior_stage_outputs to the actual stage-only keys.
    prior_stage_chars = len(json.dumps(prior_stage_payload, default=str))

    # ---- previous_failures: sum char count over the list of strings.
    previous_failures_chars = sum(len(s) for s in (inp.previous_failures or []))

    # ---- recent_gate_block: rendered via the same helper the prompt uses,
    # so the audit number matches what the LLM actually sees.
    recent_gate_chars = len(
        _format_recent_gate_exhaustions_block(inp.recent_gate_exhaustions or [])
    )

    components: dict[str, int] = {
        "system_prompt": len(system_prompt or ""),
        "candidates_markdown": candidates_markdown_chars,
        "interpretation_json": interpretation_json_chars,
        "non_candidates_overview": non_candidates_overview_chars,
        "previous_failures": previous_failures_chars,
        "vocab_block": len(vocab_block) if vocab_block else 0,
        "expert_context_block": len(expert_context_block) if expert_context_block else 0,
        "agent_cards_block": len(agent_cards_block) if agent_cards_block else 0,
        "prior_stage_outputs": prior_stage_chars,
        "recent_gate_block": recent_gate_chars,
    }
    return {
        "stage_name": stage_name,
        "components": components,
        "total_chars": sum(components.values()),
    }


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
    scope_block = _render_data_scope_block(inp.data_scope)
    if scope_block:
        lines += [scope_block, ""]

    lines += [
        "## Interpretation Summary",
        f"Models analysed     : {interp.get('model_types', [])}",
        f"Total experiments   : {interp.get('total_experiments', 'unknown')}",
        f"Overall raw best    : {interp.get('best_denoising_score')}",
        f"Overall best valid  : {interp.get('best_valid_denoising_score')}",
        f"Overall worst score : {interp.get('worst_denoising_score')}",
        "",
    ]

    per_best = interp.get("per_model_best", {})
    per_best_valid = interp.get("per_model_best_valid", {})
    per_raw_health = interp.get("per_model_raw_best_health_validity", {})
    per_worst = interp.get("per_model_worst", {})
    if per_best:
        lines.append("### Per-model scores")
        for mt in interp.get("model_types", []):
            lines.append(
                f"  {mt}: raw_best={per_best.get(mt)} "
                f"(health={per_raw_health.get(mt, 'unknown')}) "
                f"best_valid={per_best_valid.get(mt)} worst={per_worst.get(mt)}"
            )
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
    sci_acc = interp.get("scientific_accuracy")
    cum_ig = interp.get("cumulative_information_gain")
    pred_hist = interp.get("prediction_outcomes_history") or {}
    if sci_acc is not None or cum_ig is not None:
        lines.append("### Prediction Track Record")
        total = sum(pred_hist.values()) if pred_hist else 0
        if cum_ig is not None:
            lines.append(f"  Cumulative information gain : {cum_ig:.3f}")
        if sci_acc is not None:
            confirmed_pct = sci_acc.get("confirmed", 0.0) * 100
            partial_pct = sci_acc.get("partial", 0.0) * 100
            refuted_pct = sci_acc.get("refuted", 0.0) * 100
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

    # V19 PR 3 §3.7 (flag-gated) — structured HealthGate evidence, rendered
    # AFTER and visibly separate from the §14.N resource-gate block (a
    # different failure family). OFF (default): nothing rendered — the
    # prompt stays byte-identical to pre-PR3 (golden-parity tested) even
    # when the structured fields are present in the interpretation dump.
    if inp.enable_structured_health_feedback:
        health_block = _format_healthgate_evidence_block(interp)
        if health_block:
            lines += [health_block, ""]

    # NOTE: legacy ProposalInput.expert_advice render block was removed in
    # Commit P-d. The field was hard-removed from the schema; see proposal.py
    # for the rationale. External agent findings reach the proposer via
    # `agent_cards` + `expert_context` (rendered in _run_pipeline).

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

    def __init__(
        self,
        provider: str = "gemini",
        model_id: str = "gemini-3.1-flash-lite-preview",
        max_retries: int | None = None,
        bridge_factory=None,
        capability_index_path: str | None = None,
        **kwargs,
    ):
        # **kwargs absorbs per-stage kwargs from ProposalLLMConfig flattening
        # (comparison_provider, reasoning_model_id, etc.) — these are for
        # future per-stage bridge routing, currently unused.
        self._bridge_factory = bridge_factory or LLMBridge
        self.bridge = self._bridge_factory(
            provider=provider,
            model_id=model_id,
            max_retries=max_retries,
        )
        # L5b — registry handle for loss-awareness rendering in the proposer
        # prompt. Mirrors the L4b implementor DI pattern. Tests pass
        # ``capability_index_path=str(tmp_path / "_capability_index.json")``
        # to avoid contaminating the canonical index; production callers
        # leave it None to use ``agent_generated/_capability_index.json``.
        self._registry = CapabilityRegistry(index_path=capability_index_path)

    def run(self, inp: ProposalInput) -> ProposalOutput:
        print(
            f"Proposing new architecture based on interpretation of "
            f"{inp.interpretation.get('model_types', [])} ..."
        )

        # Decide: pipeline mode or legacy mode
        has_pipeline = (
            inp.reasoning_pipeline
            and inp.reasoning_pipeline.stages
            and any(s.enabled for s in inp.reasoning_pipeline.stages)
        )

        output = self._run_pipeline(inp) if has_pipeline else self._run_legacy(inp)

        # --- Persist ---
        if inp.storage.backend == "local" and inp.storage.local:
            workspace = inp.storage.local.workspace
            run_name = inp.storage.local.run_name
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
        # System prompt has its {TASK_BACKGROUND} placeholder substituted at
        # call time from inp.task_description + inp.forward_contract; see
        # docs/design/enable_global_task_config.md § Commit T3.
        reasoning_system_prompt = _build_reasoning_system_prompt(inp)
        reasoning = self.bridge.generate_text(
            reasoning_system_prompt,
            reasoning_prompt,
            label="proposer.legacy_reasoning",
        )
        print(f"   Legacy reasoning complete ({len(reasoning)} chars).")

        base_commit_prompt = _build_commit_prompt(reasoning, inp.existing_model_types)
        budget = _active_time_budget_minutes(inp)
        preflight_errors: list[str] = []
        candidates: list[ProposalOutput] = []

        for preflight_attempt in range(_MAX_PREFLIGHT_ATTEMPTS):
            commit_prompt = base_commit_prompt
            if preflight_errors:
                commit_prompt = base_commit_prompt + "\n\n---\n\n" + "\n\n".join(preflight_errors)

            raw = self.bridge.generate(
                PROPOSAL_COMMIT_PROMPT,
                commit_prompt,
                label="proposer.legacy_commit",
            )

            proposed_name = raw.get("model_name", "")
            if proposed_name in inp.existing_model_types:
                raise ValueError(
                    f"LLM proposed model_name '{proposed_name}' which already exists in "
                    f"existing_model_types: {inp.existing_model_types}. "
                    f"Re-run or adjust the constraints."
                )

            output = ProposalOutput.model_validate(
                {
                    "model_name": proposed_name,
                    "model_description": raw.get("model_description", ""),
                    "mathematical_definition": raw.get("mathematical_definition", ""),
                    "motivation": raw.get("motivation", ""),
                    "expert_advice": raw.get("expert_advice", {}),
                    "baseline_config": raw.get("baseline_config", {}),
                    "parameter_count_estimate": raw.get("parameter_count_estimate"),
                    "custom_loss_spec": raw.get("custom_loss_spec"),
                },
                context={
                    "loss_registry_names": live_loss_registry_names(self._registry),
                    "model_registry_names": _live_model_registry_names(self._registry),
                },
            )

            factor = _run_preflight_check(inp, output)
            if factor is None or factor <= 1.0:
                print(f"Proposed model (legacy): '{output.model_name}'")
                return output

            candidates.append(output)
            if preflight_attempt < _MAX_PREFLIGHT_ATTEMPTS - 1:
                # Invariant: factor > 1.0 here means _run_preflight_check did not
                # take its early-exit paths at L106-107 (budget None) or
                # L110-115 (num_params None / non-positive), and reached L128
                # where preflight_estimated_minutes is assigned. Narrow all three
                # explicitly so any future regression in that invariant surfaces
                # here with a clear message instead of crashing inside ``:,`` /
                # ``:.1f`` format on None.
                num_params = output.parameter_count_estimate
                est_mins = output.preflight_estimated_minutes
                if num_params is None or est_mins is None or budget is None:
                    raise RuntimeError(
                        "Preflight structural invariants violated: "
                        f"factor={factor} > 1.0 but one of "
                        f"(parameter_count_estimate={num_params}, "
                        f"preflight_estimated_minutes={est_mins}, "
                        f"budget={budget}) is None — _run_preflight_check "
                        "should have returned None for skipped pre-flight."
                    )
                preflight_errors.append(
                    _build_preflight_rejection_block(
                        num_params=num_params,
                        estimated_minutes=est_mins,
                        factor=factor,
                        budget_minutes=budget,
                    )
                )
                print(
                    f"   Pre-flight rejected (factor={factor:.2f}x); "
                    f"requesting revision {preflight_attempt + 2}/"
                    f"{_MAX_PREFLIGHT_ATTEMPTS}."
                )

        best = min(candidates, key=lambda o: cast(float, o.preflight_factor))
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
        from agent.prompt_templates.proposal import (
            load_stage_prompt,
            render_agent_cards,
            render_available_losses,
            render_available_models,
            render_expert_context,
        )
        from nodes.proposal_helpers import (
            build_score_summary_line,
            clamp_and_backstop_accumulated,
            enrich_candidates_with_source,
            resolve_exploration_mode,
            select_candidate_models,
        )

        pipeline = inp.reasoning_pipeline
        policy = pipeline.policy

        # B.16a — resolve exploration mode
        mode = resolve_exploration_mode(inp.interpretation, pipeline)
        print(
            f"   Pipeline mode: {mode} | stages: {[s.name for s in pipeline.stages if s.enabled]}"
        )

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
            "key_findings",
            "bottlenecks",
            "score_trend",
            "strategy_assessment",
        )
        candidate_names = {c["model_type"] for c in candidates}
        cache = inp.interpretation.get("model_knowledge_cache") or {}
        descriptions = inp.interpretation.get("model_descriptions") or {}
        per_best = inp.interpretation.get("per_model_best_valid") or {}
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

        print(
            f"   Candidates: {[c['model_type'] for c in candidates]} "
            f"({len(candidates)} models, {source_counts} with source code); "
            f"non-candidates: {[o['model_type'] for o in non_candidates_overview]}"
        )

        # Prepare shared context for all stages.
        # P-d: hardware + constraints blocks are now rendered in pipeline mode
        # (pre-P-d these were rendered only in legacy mode at _build_reasoning_prompt
        # so production runs never saw them — dangling pointers in the system prompts).
        hardware_block = _render_hardware_context_block(inp.hardware_context, inp.vram_budget_gb)
        data_scope_block = _render_data_scope_block(inp.data_scope)
        constraints_block = _render_constraints_block(inp.constraints, inp.existing_model_types)
        agent_cards_block = render_agent_cards(inp.agent_cards)
        expert_context_block = render_expert_context(inp.expert_context)
        vocab_block = self._render_vocabulary(inp.vocab_seed)
        # Explicit cold-start banner — empty string unless inp.cold_start is True,
        # so seeded prompts are byte-for-byte unchanged.
        cold_start_block = _render_cold_start_block(inp.cold_start)

        # --- Run enabled reasoning stages (accumulate context) ---
        accumulated = {
            "candidates": candidates,
            "non_candidates_overview": non_candidates_overview,
            "interpretation_summary": {
                k: inp.interpretation.get(k)
                for k in (
                    "model_types",
                    "total_experiments",
                    "best_denoising_score",
                    "worst_denoising_score",
                    "key_findings",
                    "bottlenecks",
                    "take_home_message",
                    "per_model_best",
                    "per_model_worst",
                    "per_model_score_tables",
                    # Phase E — prediction track record (surfaced to all stages)
                    "scientific_accuracy",
                    "cumulative_information_gain",
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
                return entry.related_to or []
            if isinstance(entry, dict):
                return entry.get("related_to") or []
            return []

        n_confirmed_links = sum(1 for v in inp.vocab_seed if _get_related(v))
        template_vars = {
            "minimum_boldness": str(policy.minimum_boldness),
            "n_agent_proposed": str(len([c for c in candidates if c.get("source") != "seed"])),
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
            # T3 — task config injection. {FORWARD_CONTRACT} is rendered into
            # proposing_stage.md (line 68 area); {TASK_DESCRIPTION} is rendered
            # into any future template that wants the bare task string. Both
            # placeholders are no-ops in stages that don't reference them.
            # See docs/design/enable_global_task_config.md § Commit T3.
            "task_description": inp.task_description,
            "forward_contract": render_forward_contract(inp.forward_contract),
            # L5b — loss-registry awareness. Rendered once per run() so all
            # stage prompts see a consistent snapshot of the registry — a
            # mid-run write (e.g. by the implementor in a parallel iteration)
            # would not retroactively change earlier stages' context. Empty
            # registry collapses to the fallback message ("No custom losses
            # registered yet — propose a new one..."). See
            # docs/design/enable_loss_inventory.md § Commit L5.
            "available_losses_block": render_available_losses(self._registry),
            # Symmetric for the model surface — rendered into the
            # ``{available_models_block}`` placeholder by the proposing
            # stage so the LLM can pick Branch B (reuse) for the model
            # config when an existing plugin already implements the
            # intended architecture. Empty registry collapses to the
            # fallback message ("No custom models registered yet...").
            "available_models_block": render_available_models(self._registry),
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

            # Build user prompt in the P-d order:
            #   1. [HARDWARE CONTEXT] block
            #   2. ## Constraints block
            #   3. ## External Contributors block
            #   4. ## Expert Context block
            #   5. Candidate markdown + accumulated JSON region
            #   6. Vocab block
            # Findings now precede the experiment-history dump so the LLM
            # reads external calibration before anchoring on past results
            # (position-bias fix, Problem 3 of the audit).
            clamped_accumulated = clamp_and_backstop_accumulated(
                accumulated,
                top_k=policy.comparative_analysis_top_k,
                max_chars=policy.prior_stage_max_chars,
                input_keys=_PROPOSER_INPUT_KEYS,
            )
            user_prompt_parts: list[str] = []
            if cold_start_block:
                user_prompt_parts.append(cold_start_block)
            if hardware_block:
                user_prompt_parts.append(hardware_block)
            if data_scope_block:
                user_prompt_parts.append(data_scope_block)
            if constraints_block:
                user_prompt_parts.append(constraints_block)
            if agent_cards_block:
                user_prompt_parts.append(agent_cards_block)
            if expert_context_block:
                user_prompt_parts.append(expert_context_block)
            user_prompt_parts.append(_render_stage_user_prompt(clamped_accumulated))
            if vocab_block:
                user_prompt_parts.append(vocab_block)
            user_prompt = "\n\n".join(user_prompt_parts)

            print(f"   Stage '{stage.name}': calling LLM... [PROMPT_SIZE] {len(user_prompt)} chars")
            stage_audit = _audit_proposer_components(
                inp=inp,
                accumulated=clamped_accumulated,
                agent_cards_block=agent_cards_block,
                expert_context_block=expert_context_block,
                vocab_block=vocab_block,
                system_prompt=system_prompt,
                stage_name=stage.name,
            )
            stage_label = f"proposer.{stage.name}"
            if stage.output_mode == "text":
                result = self.bridge.generate_text(
                    system_prompt,
                    user_prompt,
                    label=stage_label,
                    components=stage_audit["components"],
                )
                accumulated[stage.name] = result
            else:
                result = self.bridge.generate(
                    system_prompt,
                    user_prompt,
                    label=stage_label,
                    components=stage_audit["components"],
                )
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
                            (
                                s
                                for s in pipeline.stages
                                if s.name == "causal_reasoning" and s.enabled
                            ),
                            None,
                        )
                        if reasoning_stage is not None:
                            retry_system = load_stage_prompt(
                                "causal_reasoning_stage",
                                exploration_mode=mode,
                                template_vars=template_vars,
                                mindset=inp.mindset,
                            )
                            clamped_accumulated = clamp_and_backstop_accumulated(
                                accumulated,
                                top_k=policy.comparative_analysis_top_k,
                                max_chars=policy.prior_stage_max_chars,
                                input_keys=_PROPOSER_INPUT_KEYS,
                            )
                            # P-d order: hardware → constraints → cards →
                            # context → accumulated → vocab (matches the main
                            # reasoning-stage assembly above).
                            retry_parts: list[str] = []
                            if hardware_block:
                                retry_parts.append(hardware_block)
                            if data_scope_block:
                                retry_parts.append(data_scope_block)
                            if constraints_block:
                                retry_parts.append(constraints_block)
                            if agent_cards_block:
                                retry_parts.append(agent_cards_block)
                            if expert_context_block:
                                retry_parts.append(expert_context_block)
                            retry_parts.append(_render_stage_user_prompt(clamped_accumulated))
                            if vocab_block:
                                retry_parts.append(vocab_block)
                            retry_user = "\n\n".join(retry_parts)
                            print("   Stage 'causal_reasoning': retrying (boldness)...")
                            retry_audit = _audit_proposer_components(
                                inp=inp,
                                accumulated=clamped_accumulated,
                                agent_cards_block=agent_cards_block,
                                expert_context_block=expert_context_block,
                                vocab_block=vocab_block,
                                system_prompt=retry_system,
                                stage_name="causal_reasoning",
                            )
                            accumulated["causal_reasoning"] = self.bridge.generate(
                                retry_system,
                                retry_user,
                                label="proposer.causal_reasoning",
                                components=retry_audit["components"],
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
                clamped_accumulated = clamp_and_backstop_accumulated(
                    accumulated,
                    top_k=policy.comparative_analysis_top_k,
                    max_chars=policy.prior_stage_max_chars,
                    input_keys=_PROPOSER_INPUT_KEYS,
                )
                # Proposing-stage user prompt — P-d order matches the reasoning
                # stages above except the vocab block is intentionally omitted
                # (proposing-stage prompts already cite vocab via system-prompt
                # template_vars; rendering it again would bloat the prompt).
                proposing_parts: list[str] = []
                if hardware_block:
                    proposing_parts.append(hardware_block)
                if constraints_block:
                    proposing_parts.append(constraints_block)
                if agent_cards_block:
                    proposing_parts.append(agent_cards_block)
                if expert_context_block:
                    proposing_parts.append(expert_context_block)
                proposing_parts.append(_render_stage_user_prompt(clamped_accumulated))
                proposing_user = "\n\n".join(proposing_parts)

                print(
                    f"   Stage 'proposing': calling LLM "
                    f"(pre-flight {preflight_attempt + 1}/{_MAX_PREFLIGHT_ATTEMPTS}, "
                    f"structural {attempt + 1}/{_MAX_PROPOSING_RETRIES + 1})..."
                )
                # Proposing-stage user prompt does not append vocab_block
                # (only agent_cards + expert_context); the audit reflects
                # this so component sums match the actual prompt sent.
                proposing_audit = _audit_proposer_components(
                    inp=inp,
                    accumulated=clamped_accumulated,
                    agent_cards_block=agent_cards_block,
                    expert_context_block=expert_context_block,
                    vocab_block="",
                    system_prompt=proposing_prompt,
                    stage_name="proposing",
                )
                raw = self.bridge.generate(
                    proposing_prompt,
                    proposing_user,
                    label="proposer.proposing",
                    components=proposing_audit["components"],
                )

                try:
                    proposed_name = raw.get("model_name", "")
                    if proposed_name in inp.existing_model_types:
                        raise ValueError(
                            f"model_name '{proposed_name}' already exists in "
                            f"existing_model_types: {inp.existing_model_types}. "
                            f"Choose a different name."
                        )

                    output = ProposalOutput.model_validate(
                        {
                            "model_name": proposed_name,
                            "model_description": raw.get("model_description", ""),
                            "mathematical_definition": raw.get("mathematical_definition", ""),
                            "motivation": raw.get("motivation", ""),
                            "expert_advice": raw.get("expert_advice", {}),
                            "baseline_config": raw.get("baseline_config", {}),
                            "inherited_components": inherited,
                            "falsifiable_prediction": prediction,
                            "proposed_vocab_links": vocab_links,
                            "proposed_vocab_candidates": vocab_candidates,
                            "proposed_discoveries": discoveries,
                            "memo_consistency_notes": raw.get("memo_consistency_notes", []),
                            "parameter_count_estimate": raw.get("parameter_count_estimate"),
                            "custom_loss_spec": raw.get("custom_loss_spec"),
                        },
                        context={
                            "loss_registry_names": live_loss_registry_names(self._registry),
                            "model_registry_names": _live_model_registry_names(self._registry),
                        },
                    )
                    # Citation discipline — warnings, not hard failures.
                    citation_violations = _check_citation_discipline(
                        source_refs=reasoning_output.get("source_refs", []),
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
                            f"{' → '.join(str(loc_part) for loc_part in e['loc'])}: {e['msg']}"
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
                # Same invariant as in _run_legacy: factor > 1.0 implies
                # _run_preflight_check ran to completion and assigned
                # preflight_estimated_minutes. Explicit narrow surfaces any
                # regression with a diagnostic message.
                num_params = output.parameter_count_estimate
                est_mins = output.preflight_estimated_minutes
                if num_params is None or est_mins is None or budget is None:
                    raise RuntimeError(
                        "Preflight structural invariants violated: "
                        f"factor={factor} > 1.0 but one of "
                        f"(parameter_count_estimate={num_params}, "
                        f"preflight_estimated_minutes={est_mins}, "
                        f"budget={budget}) is None — _run_preflight_check "
                        "should have returned None for skipped pre-flight."
                    )
                rejection = _build_preflight_rejection_block(
                    num_params=num_params,
                    estimated_minutes=est_mins,
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

        best = min(preflight_candidates, key=lambda o: cast(float, o.preflight_factor))
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
        def _get(entry, key, default: Any = ""):
            if hasattr(entry, key):
                return getattr(entry, key)
            if isinstance(entry, dict):
                return entry.get(key, default)
            return default

        features = [v for v in vocab_seed if _get(v, "kind") == "feature"]
        capabilities = [v for v in vocab_seed if _get(v, "kind") == "capability"]
        discoveries = [v for v in vocab_seed if _get(v, "kind") == "discovery"]
        candidates = [v for v in vocab_seed if _get(v, "kind") == "candidate"]

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
            lines.append(
                "These are the results of past falsifiable predictions. "
                "Use them to avoid repeating failures and to build on confirmed findings."
            )
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
    parser.add_argument(
        "--workspace",
        type=str,
        default="./siderius_workspace",
        help="Root directory for reading interpretation output and writing proposal",
    )
    parser.add_argument(
        "--run_name",
        type=str,
        default="v1",
        help="Run name — reads interpretation_{run_name}.json, writes proposal_{run_name}.json",
    )
    parser.add_argument("--provider", type=str, default="gemini", choices=["gemini", "openai"])
    parser.add_argument("--model_id", type=str, default="gemini-3.1-flash-lite-preview")
    args = parser.parse_args()

    interp_path = os.path.join(args.workspace, f"interpretation_{args.run_name}.json")
    if not os.path.exists(interp_path):
        raise FileNotFoundError(
            f"Interpretation file not found: {interp_path}\n"
            f"Run result_interpretation_agent first, or check --workspace and --run_name."
        )
    with open(interp_path, encoding="utf-8") as f:
        interpretation = json.load(f)

    agent_input = ProposalInput.model_validate(
        {
            "interpretation": interpretation,
            "storage": {
                "backend": "local",
                "local": {"workspace": args.workspace, "run_name": args.run_name},
            },
        }
    )
    print(
        f"✅ Input validated: models={interpretation.get('model_types')} | "
        f"experiments={interpretation.get('total_experiments')}"
    )

    agent = MLModelProposalAgent(provider=args.provider, model_id=args.model_id)
    output = agent.run(agent_input)

    print(f"\n{'=' * 60}")
    print(f"  Proposal — {output.model_name}")
    print(f"{'=' * 60}")
    print(f"  Description : {output.model_description}")
    print(f"  Motivation  : {output.motivation}")
    print("\n  Mathematical definition:")
    print(f"    {output.mathematical_definition[:500]}...")
    print("\n  Expert advice:")
    print(f"    Focus areas    : {output.expert_advice.focus_areas}")
    print(f"    Constraints    : {output.expert_advice.constraints}")
    print(f"    Suggested dirs : {output.expert_advice.suggested_directions}")
    print("\n  Baseline config:")
    print(f"    {json.dumps(output.baseline_config, indent=4)}")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
