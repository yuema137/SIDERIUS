# nodes/result_interpretation_agent/result_interpretation_agent.py
"""
result_interpretation_agent — Node 2 in the SIDERIUS graph.

Two-phase interpretation:
  Phase 1 — Per-model summarization: one LLM call per model type, receiving
            the condensed ModelRunSummary (scores, trajectory, conclusions)
            — NOT raw experiment records.
  Phase 2 — Cross-model synthesis: one LLM call consuming all per-model
            summaries to produce the final interpretation.

Node contract:
  run(input: InterpretationInput) -> InterpretationOutput
  CLI: --workspace, --run_name, --model_type, --provider, --model_id
"""

import argparse
import json
import os
from typing import TYPE_CHECKING, Any, cast

from pydantic import ValidationError

from agent.cache_consolidator import consolidate
from agent.llm_bridge import LLMBridge
from agent.schemas.cache_entry import CacheEntry
from agent.schemas.health_feedback import (
    CollapseFingerprint,
    merge_fingerprint_history,
)
from agent.schemas.hyperparam_tuning import serialize_expert_advice
from agent.schemas.interpretation import (
    InterpretationInput,
    InterpretationOutput,
    MetricIdentity,
    ModelRunSummary,
)
from agent.schemas.score_table import ScoreComparisonTable
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from execute_tools.metric_order import MetricOrder
from ml_models.model_descriptions import get_model_description

# Node-private modules (Step 09a C1b). Imported EAGERLY and at module scope on
# purpose: `__init__.py` rebinds `sys.modules["nodes.result_interpretation_agent"]`
# to THIS module, so after that rebind the package path has no `__path__` and a
# lazy `import nodes.result_interpretation_agent.evidence` would fail. Binding
# them while `__init__` is still executing puts each submodule in `sys.modules`
# for good. (Same rule the tuner's C7 decomposition follows.)
from nodes.result_interpretation_agent.evidence import (
    InterpretationContractError,
    _collect_health_evidence,
    _required_denoising_score,
    _round_health,
    _round_ordering,
    reconcile_metric_spec,
    tuning_output_to_model_run_summary,
)
from nodes.result_interpretation_agent.ordering import (
    bind_run_order,
    collect_enriched_fields,
    precompute_evidence,
)
from nodes.result_interpretation_agent.prediction import (
    PREDICTION_SEMANTICS_LEGACY_V1,
    PREDICTION_SEMANTICS_SIGNSAFE_V2,
    accumulate_information_gain,
    accumulate_prediction_outcomes,
    evaluate_prediction,
    prediction_pool_sizes,
)

if TYPE_CHECKING:
    from agent.schemas.proposal import VocabEntry

__all__ = [
    "DEDUP_SYSTEM_PROMPT",
    "HEALTH_FEEDBACK_SYSTEM_INSTRUCTIONS",
    "PER_MODEL_SYSTEM_PROMPT",
    "SYNTHESIS_SYSTEM_PROMPT",
    "InterpretationContractError",
    "ResultInterpretationAgent",
    "main",
    "reconcile_metric_spec",
    "tuning_output_to_model_run_summary",
]

#: COMPATIBILITY ONLY — not part of the node's contract.
#:
#: C1b moved these helpers into the node-local submodules. They are re-exported
#: here because the package `__init__` and a body of tests reach them at this
#: path, and because `mock.patch("nodes.result_interpretation_agent.X")` must
#: keep resolving to the object production actually calls.
#:
#: They are NOT documented in result_interpretation_agent.md, they are NOT a
#: promise to callers, and NO new production consumer may be added: import the
#: owning submodule from inside the node instead. The list is expected to
#: shrink, never grow.
#:
#: Listing them here also KEEPS them alive: without a reference the linter
#: prunes the re-export and the package `__init__` fails at import.
_COMPATIBILITY_REEXPORTS = (
    _collect_health_evidence,
    _required_denoising_score,
    _round_health,
    _round_ordering,
    accumulate_information_gain,
    accumulate_prediction_outcomes,
    collect_enriched_fields,
    evaluate_prediction,
    precompute_evidence,
)

# ---------------------------------------------------------------------------
# Phase 1 — Per-model summarization
# ---------------------------------------------------------------------------

PER_MODEL_SYSTEM_PROMPT = """\
You are a senior ML research analyst.

Your task: analyse the tuning run summary for ONE model architecture and produce a
structured analysis covering performance, per-file behaviour, data sensitivity,
training dynamics, efficiency, and strategy assessment. The research context is:

{TASK_DESCRIPTION}

You will receive:
- The model's architectural description (markdown + math)
- Best and worst denoising scores (trial best and formal score if available)
- Best configuration
- Score trajectory across rounds (with trial portions and model sizes)
- Per-round conclusions from the tuning agent's reflections
- A per-file score table: one row per validation file with raw_baseline,
  ground_truth, model, gain_vs_raw, headroom_vs_gt, Linear_Weight, and Impact_Score
  columns, followed by a secondary block re-ranking the sampled rows by
  Impact_Score descending
- Data volume: how many PSD segments were used for training vs baseline

### Reading the per-file score table — the Log-of-Mean trap

The aggregate denoising scalar is the log of a *sum* of per-segment linear
energies, not a mean of per-file log scores. Two columns describe each file's
contribution to the next-iter improvement budget:

- **`Linear_Weight`** — the file's current share of the scalar's linear
  denominator. Tells you *where the scalar lives now*. Sums to 1 across
  sampled files.
- **`Impact_Score`** — the log-scalar gain you would obtain by lifting this
  file's `model` to its `ground_truth`. Tells you *where the next-iter lever
  is*. A high `Impact_Score` means a file with both meaningful weight and
  remaining headroom; a near-zero `Impact_Score` means the file is either
  already at its ceiling or its weight is too small for any improvement to
  register.

When you analyse bottlenecks for this model:

1. Rank the files by `Impact_Score` descending — that is the per-iter
   opportunity ranking. A multi-log-unit `headroom_vs_gt` does not by itself
   indicate opportunity; only `Impact_Score` does.
2. Read `Linear_Weight` for context. A high-weight file at its ceiling has
   zero `Impact_Score` and is not actionable.
3. Saturation is a relative reading. If the entire `Impact_Score` column is
   small in magnitude relative to `model_scalar` and to the gains your
   chain has been making per iter, this model has reached the dataset
   ceiling — say so.
4. No file is permanently irrelevant. A near-zero `Impact_Score` today may
   rise next iter once higher-`Impact_Score` files are recovered. Do not
   memorise file-index labels across iterations — re-read the column each
   iter.

Produce a JSON object with exactly these fields:

{
  "key_findings": [
    "Most important finding — concrete, references actual scores and configs",
    ...
  ],
  "bottlenecks": [
    "Root cause preventing further improvement for this specific model",
    ...
  ],
  "best_config_analysis": "Why the best config worked — what made it better than others",
  "score_trend": "How scores evolved across rounds — improving, plateauing, or erratic",
  "per_file_analysis": "Read the per-file table by Impact_Score descending. Cite specific files BY file_index together with their Impact_Score and Linear_Weight values for this iter. When a clear Impact_Score leader exists, you MUST name the leader's file_index explicitly as the primary remaining lever — do NOT declare this model saturated while a clear lever remains, even if model_scalar is close to its ceiling. Only call a file 'already saturated' when its Impact_Score is uniformly small with the rest of the column. Do not assert a file is permanently weak from a single iter's reading.",
  "data_sensitivity": "How sensitive the model is to data volume. Did scores improve when trial_portion increased? How large is the trial-vs-formal gap?",
  "efficiency_assessment": "Model parameter count vs performance. Is there a simpler config with similar score? Cost-performance tradeoff.",
  "strategy_assessment": "Did the agent explore effectively? Did it increase data when needed? Did it follow screening→refinement→solidification phases?"
}

Rules:
- key_findings: ranked by importance, evidence-based, reference actual values
- bottlenecks: root causes (e.g. 'architecture capacity ceiling', 'all sampled files saturated against their ground_truth ceiling'), not symptoms
- best_config_analysis: be specific about which hyperparameters mattered most
- score_trend: identify whether the model has saturated or still has room to improve
- per_file_analysis: rank by Impact_Score; cite Linear_Weight as context, not as a ranking metric on its own; never use fixed cutoffs
- data_sensitivity: reference training_psd_segments, trial_portion changes across rounds
- efficiency_assessment: reference model_params and training times if available
- strategy_assessment: comment on whether the agent's exploration strategy was effective
- Output only the JSON object — no preamble, no commentary, no markdown
"""


def _build_per_model_system_prompt(inp: "InterpretationInput") -> str:
    """Substitute the ``{TASK_DESCRIPTION}`` placeholder in
    ``PER_MODEL_SYSTEM_PROMPT`` from ``inp.task_description``.

    Production callers always populate ``inp.task_description`` via the
    workflow (T4b — see docs/design/enable_global_task_config.md § Commit T4);
    test fixtures may leave it at the default ``""``, in which case the
    placeholder collapses to ``""`` and the prompt's "The research context
    is:" preamble has no payload (acceptable for tests, never reached in
    production).
    """
    rendered = PER_MODEL_SYSTEM_PROMPT.replace("{TASK_DESCRIPTION}", inp.task_description)
    # V19 PR 3 §3.6 item 3 (flag-gated): instruction block for handling the
    # structured HealthGate evidence. OFF ⇒ byte-identical to pre-PR3
    # (golden-parity tested).
    if inp.enable_structured_health_feedback:
        rendered += HEALTH_FEEDBACK_SYSTEM_INSTRUCTIONS
    return rendered


HEALTH_FEEDBACK_SYSTEM_INSTRUCTIONS = """

### Structured HealthGate evidence (additional rules)

The user prompt may contain a "HealthGate summary" section and per-round
GATE labels. These are DETERMINISTIC facts from the health-gate system,
not opinions. Rules:

- Preserve every collapse fingerprint VERBATIM in your findings — the
  exact signature string with its numbers (e.g.
  "output_diversity_blocking:n_unique_int8_values=1"). Never paraphrase
  the numbers away.
- A high raw score on a round with invalid gate evidence is an INVALID
  result. Report it as a failure mode, never as an achievement.
- Rounds marked "unknown" or with legacy/no gate evidence carry NO
  health verdict. Do not describe them as healthy or collapsed.
- Attribute each fingerprint to exactly the model and rounds it came
  from. Never transfer evidence between models."""


def _render_health_summary_section(summary: ModelRunSummary, *, order: MetricOrder) -> list[str]:
    """Deterministic ``### HealthGate summary`` body (V19 PR 3 §3.6 item 2).

    Reads ONLY the ``round_health`` data — never LLM prose. Returns [] when
    every round is legacy/unknown with nothing to report, so the caller can
    skip the header entirely.

    ``order`` (Step 09a C3) picks the BEST-SCORING round whose recording
    diagnostics are rendered. That selection is a direction question: under a
    lower-is-better metric the old ``s > best_score`` literal would surface the
    WORST round's diagnostics while calling them the best round's.
    """
    counts = {"valid": 0, "invalid": 0, "unknown": 0}
    fingerprint_rounds: dict[str, list[int]] = {}
    fingerprint_by_sig: dict[str, CollapseFingerprint] = {}
    for i, health in enumerate(summary.round_health):
        counts[str(health.health_validity)] += 1
        if health.fingerprint is not None:
            sig = health.fingerprint.signature
            fingerprint_rounds.setdefault(sig, []).append(i + 1)
            fingerprint_by_sig.setdefault(sig, health.fingerprint)

    lines = [
        f"Round validity: {counts['valid']} valid, {counts['invalid']} invalid, "
        f"{counts['unknown']} unknown (of {len(summary.round_health)})"
    ]
    if fingerprint_rounds:
        lines.append(
            "Distinct collapse fingerprints (deterministic, from persisted gate evidence):"
        )
        for sig in sorted(fingerprint_rounds):
            rounds = fingerprint_rounds[sig]
            fp = fingerprint_by_sig[sig]
            lines.append(
                f"  - {sig}  (x{len(rounds)}, round{'s' if len(rounds) > 1 else ''} "
                f"{', '.join(str(r) for r in rounds)}) — {fp.human_readable}"
            )

    # Recording-only diagnostics for the best-scoring round, if any round
    # carries them (e.g. pearson_dispersion — the misleading-high-score
    # discriminator, design §2.4).
    best_idx = None
    best_score = None
    for i, s in enumerate(summary.round_scores):
        if s is not None and (best_score is None or order.is_better(s, best_score)):
            best_idx, best_score = i, s
    if best_idx is not None and best_idx < len(summary.round_health):
        recording = {
            k: v
            for outcome in summary.round_health[best_idx].gate_outcomes
            if outcome.gate_name.endswith("_recording")
            for k, v in outcome.key_metrics.items()
        }
        if recording:
            rendered = ", ".join(f"{k}={v}" for k, v in sorted(recording.items()))
            lines.append(f"Best-round recording diagnostics: {rendered}")

    if counts["invalid"] == 0 and counts["valid"] == 0 and not fingerprint_rounds:
        # All-unknown/legacy with no fingerprints: nothing informative.
        return []
    return lines


def _build_per_model_prompt(
    summary: ModelRunSummary,
    description: str,
    expert_advice_str: str = "",
    human_advice: str | None = None,
    *,
    structured_health_feedback: bool = False,
    order: MetricOrder | None = None,
) -> str:
    """Build the user prompt for a single model's summarization.

    ``structured_health_feedback`` (V19 PR 3 §3.6) gates the structured
    HealthGate additions — the trajectory gate labels and the
    ``### HealthGate summary`` section. OFF (default): output is
    byte-identical to the pre-PR3 prompt, proven by golden-file equality
    in ``test_health_prompt_parity.py`` — every PR 3 addition below must
    stay behind this flag.

    ``order`` (Step 09a C3) is needed ONLY by that flag-ON section, which
    picks a best-scoring round. It therefore keeps a ``None`` default so every
    flag-OFF caller and every prompt golden is untouched — and raises when the
    flag is ON without it, rather than rendering a round chosen by an assumed
    direction.
    """
    if structured_health_feedback and order is None:
        raise ValueError(
            "structured_health_feedback=True renders the best-scoring round's "
            "diagnostics, which requires the run's MetricOrder. Pass order=; the "
            "direction is never assumed."
        )
    lines = [
        f"## Model: {summary.model_type}",
        f"Run: {summary.run_name} | Status: {summary.status} | Rounds: {summary.completed_rounds}",
        f"Raw best score       : {summary.best_denoising_score} "
        f"(health={summary.best_raw_health_validity})",
        f"Best valid score     : {summary.best_valid_denoising_score}",
        f"Worst denoising score: {summary.worst_denoising_score}",
    ]

    # Formal score (if available and distinct from best)
    if summary.formal_score is not None:
        lines.append(f"Formal round score   : {summary.formal_score}")

    # Model efficiency
    if summary.best_model_params is not None:
        lines.append(f"Best model params    : {summary.best_model_params:,}")

    # Data volume context
    if summary.training_psd_segments is not None:
        lines.append(
            f"Training PSD segments: {summary.training_psd_segments} (baseline typically uses 4000)"
        )
    if summary.eval_psd_segments is not None:
        lines.append(f"Eval PSD segments    : {summary.eval_psd_segments}")
    if summary.trial_portion is not None:
        lines.append(f"Trial portion (best) : {summary.trial_portion}")

    lines += [
        "",
        "### Architecture Description",
        description,
        "",
        "### Best Config",
        json.dumps(summary.best_config, indent=2) if summary.best_config else "none",
    ]

    # Per-file performance — rendered as the full ScoreComparisonTable
    # markdown (raw_baseline / ground_truth / model columns + subset-scoped
    # aggregates + Recovery line). Single source of truth lives on the
    # table.rendered_markdown field, produced by render_comparison_table.
    if summary.best_score_table is not None:
        lines += [
            "",
            "### Per-file performance (best experiment)",
            summary.best_score_table.rendered_markdown,
        ]

    if summary.formal_score_table is not None:
        lines += [
            "",
            "### Per-file performance (formal round — definitive)",
            summary.formal_score_table.rendered_markdown,
        ]

    # Score trajectory with per-round trial portions and model params
    lines += ["", "### Score Trajectory (chronological)"]

    n_rounds = len(summary.round_scores)
    for i in range(n_rounds):
        score = summary.round_scores[i] if i < len(summary.round_scores) else None
        conclusion = summary.round_conclusions[i] if i < len(summary.round_conclusions) else ""
        trial_p = (
            summary.round_trial_portions[i]
            if summary.round_trial_portions and i < len(summary.round_trial_portions)
            else None
        )
        params = (
            summary.round_model_params[i]
            if summary.round_model_params and i < len(summary.round_model_params)
            else None
        )

        score_str = f"{score:.4f}" if score is not None else "skipped"
        extras = []
        if trial_p is not None:
            extras.append(f"portion={trial_p}")
        if params is not None:
            extras.append(f"params={params:,}")
        extra_str = f" [{', '.join(extras)}]" if extras else ""

        # V19 PR 3 §3.6 item 1 (flag-gated): label gate-invalidated rounds
        # with the resolved action and the deterministic collapse identity,
        # instead of the ambiguous bare "skipped".
        gate_str = ""
        if structured_health_feedback and i < len(summary.round_health):
            health = summary.round_health[i]
            if health.gate_action is not None and health.gate_action != "continue":
                cause = (
                    health.fingerprint.signature
                    if health.fingerprint is not None
                    else (health.failure_reason or "no persisted gate detail")
                )
                if score is None:
                    score_str = "invalidated"
                gate_str = f" [GATE {health.gate_action} — {cause}]"

        lines.append(f"  Round {i + 1}: score={score_str}{extra_str}{gate_str} — {conclusion}")

    # V19 PR 3 §3.6 item 2 (flag-gated): per-model HealthGate summary —
    # validity counts, distinct fingerprints with occurrence counts and
    # round indices, and recording-only diagnostics for the best round.
    # Rendered ONLY when there is something to say (no empty headers).
    # `order is not None` is guaranteed by the guard at the top of this
    # function whenever the flag is on; restating it here is what lets a type
    # checker see the narrowing, and it can never change behaviour.
    if structured_health_feedback and order is not None and summary.round_health:
        health_lines = _render_health_summary_section(summary, order=order)
        if health_lines:
            lines += ["", "### HealthGate summary", *health_lines]

    if expert_advice_str:
        lines += [
            "",
            "---",
            "## Expert Guidance",
            expert_advice_str,
        ]

    if human_advice:
        lines += [
            "",
            "---",
            "## Human Guidance (highest priority — overrides expert advice)",
            human_advice,
        ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Phase 2 — Cross-model synthesis
# ---------------------------------------------------------------------------

SYNTHESIS_SYSTEM_PROMPT = """\
You are a senior ML research analyst.

Your task: read structured summaries of multiple model architectures and produce a
cross-model interpretation that identifies the overall state of the research and
motivates the next step. The research context is:

{TASK_DESCRIPTION}

You will receive:
- Per-model summaries (key findings, bottlenecks, config analysis, score trends,
  per-file analysis, data sensitivity, efficiency, strategy assessment)
- Per-model best and worst scores
- Per-model score tables — per-file `raw_baseline` / `ground_truth` / `model`
  in log-space, alongside `Linear_Weight` (each file's share of the linear
  denominator behind the aggregate scalar) and `Impact_Score` (the log-scalar
  gain available if that file's `model` were lifted to its `ground_truth`)
- Per-model parameter counts and training data volumes
- Overall best score and the config that produced it
- Established discoveries from previous iterations (if any) — empirical findings
  already confirmed by past experiments. Build on these, confirm or contradict them.

### Reading the score table — the Log-of-Mean trap

The aggregate denoising scalar is the log of a *sum* of per-segment linear
energies, not a mean of per-file log scores. Two columns describe each file's
contribution to the next-iter improvement budget:

- **`Linear_Weight`** — the file's current share of the scalar's linear
  denominator. Tells you *where the scalar lives now*. Sums to 1 across
  sampled files.
- **`Impact_Score`** — the log-scalar gain you would obtain by lifting this
  file's `model` to its `ground_truth`. Tells you *where the next-iter lever
  is*. A high `Impact_Score` means a file with both meaningful weight and
  remaining headroom; a near-zero `Impact_Score` means the file is either
  already at its ceiling or its weight is too small for any improvement to
  register.

When you analyse bottlenecks across the candidate models:

1. **Rank by `Impact_Score` descending** to identify each model's largest
   remaining levers, then look across models for files that share a high
   Impact_Score — those are the cross-model opportunities. A multi-log-unit
   `headroom_vs_gt` does not by itself indicate opportunity; only
   `Impact_Score` does.
2. **Read `Linear_Weight` for context.** It is *not* a ranking metric on its
   own — a high-weight file at its ceiling has zero `Impact_Score` and is
   not actionable.
3. **Saturation is a relative reading.** If the entire `Impact_Score` column
   is small in magnitude relative to the current `model_scalar` and to the
   per-iter gains the chain has been making, the chain has reached the
   dataset ceiling on that model — declare it explicitly. There is no fixed
   cutoff; you compare the distribution against the scale of progress.
4. **No file is permanently irrelevant.** Today's near-zero `Impact_Score`
   may rise next iter once higher-`Impact_Score` files are fully recovered.
   Re-read the column each iter; do not memorise file-index labels across
   iterations.

Produce a JSON object with exactly these fields:

{
  "key_findings": [
    "Cross-model finding #1 — most important, compares models, references scores",
    ...
  ],
  "bottlenecks": [
    "Cross-model root cause #1 — what is fundamentally limiting ALL current models",
    ...
  ],
  "per_file_comparison": "Cite Impact_Score, Linear_Weight, and gain_vs_raw together when discussing per-file bottlenecks. Rank candidates for the next iter's improvement by Impact_Score descending across models. Do not assert a file is universally weak from headroom alone — a large headroom on a low-weight file implies a near-zero Impact_Score and is not actionable.",
  "efficiency_comparison": "Compare model sizes (parameter counts) against scores. Identify the best score-per-parameter architecture.",
  "take_home_message": "One sentence: the single most critical insight that motivates the next step. Read the Impact_Score column FIRST — never decide saturation from model_scalar alone. (a) If one or more files show an Impact_Score visibly larger than the rest (a clear leader, even when model_scalar is close to its ceiling), your take_home_message MUST explicitly identify the file_index with the largest Impact_Score as the primary objective for the next iteration; do NOT declare saturation while a clear performance lever remains. (b) Only when the entire Impact_Score column is uniformly small relative to model_scalar AND significantly smaller than the gains identified in previous iterations of this chain, declare ceiling reached rather than manufacture an architectural deficiency."
}

Rules:
- key_findings: ranked by importance, MUST compare across models, reference actual scores
- bottlenecks: focus on fundamental limitations shared across architectures, not per-model issues
- per_file_comparison: rank by Impact_Score descending; cite Linear_Weight as context, not as a ranking metric on its own; do not use fixed cutoffs or fixed file-index labels
- efficiency_comparison: reference actual parameter counts and scores
- take_home_message: exactly one sentence, grounded in the Impact_Score distribution. When a clear Impact_Score leader exists, you MUST cite that file's file_index explicitly (e.g. "file 17"); a high model_scalar does not override a remaining lever.
- Do not repeat per-model findings verbatim — synthesise and draw cross-model conclusions
- Output only the JSON object — no preamble, no commentary, no markdown
"""


# Narrative fields that, post-Commit-6.3 consolidation, are stored as
# ConsolidatedNarrative dicts `{"latest": str, "history": [...]}` instead of
# bare strings. The synthesis prompt builder still expects bare strings.
_NARRATIVE_FIELDS_FOR_PROMPT = (
    "best_config_analysis",
    "score_trend",
    "per_file_analysis",
    "data_sensitivity",
    "efficiency_assessment",
    "strategy_assessment",
)
# List fields that, post-Commit-6.3, are stored as list[ConsolidatedFinding]
# dicts instead of list[str].
_LIST_FIELDS_FOR_PROMPT = ("key_findings", "bottlenecks")


def _flatten_entry_for_prompt(entry: dict[str, Any]) -> dict[str, Any]:
    """Flatten a (possibly modern-shape) cache entry into the legacy display
    shape the synthesis prompt builder expects.

    Why: post-Commit-6.3 active cache entries hold ConsolidatedFinding dicts
    and ConsolidatedNarrative dicts. The synthesis builder reads narratives
    as bare strings and findings as list-of-strings. This helper bridges the
    two shapes without touching the builder — cache-miss (legacy flat) entries
    pass through unchanged.
    """
    flat: dict[str, Any] = {}
    for k, v in entry.items():
        if k == "_stats":
            continue
        if k in _LIST_FIELDS_FOR_PROMPT and isinstance(v, list):
            flat[k] = [
                item["statement"] if isinstance(item, dict) and "statement" in item else item
                for item in v
            ]
        elif k in _NARRATIVE_FIELDS_FOR_PROMPT and isinstance(v, dict):
            flat[k] = v.get("latest", "") or ""
        else:
            flat[k] = v
    return flat


def _build_synthesis_system_prompt(inp: "InterpretationInput") -> str:
    """Substitute the ``{TASK_DESCRIPTION}`` placeholder in
    ``SYNTHESIS_SYSTEM_PROMPT`` from ``inp.task_description``.

    Mirrors :func:`_build_per_model_system_prompt` for the cross-model
    synthesis call site. See docs/design/enable_global_task_config.md
    § Commit T4 for the substitution contract.
    """
    return SYNTHESIS_SYSTEM_PROMPT.replace("{TASK_DESCRIPTION}", inp.task_description)


def _build_synthesis_prompt(
    per_model_summaries: dict[str, dict],
    per_model_best: dict[str, float | None],
    per_model_worst: dict[str, float | None],
    overall_best_score: float | None,
    overall_worst_score: float | None,
    overall_best_config: dict | None,
    per_model_best_valid: dict[str, float | None] | None = None,
    per_model_raw_best_health_validity: dict[str, str] | None = None,
    overall_best_valid_score: float | None = None,
    per_model_score_tables: dict[str, ScoreComparisonTable] | None = None,
    per_model_params: dict[str, int] | None = None,
    per_model_training_segments: dict[str, int] | None = None,
    expert_advice_str: str = "",
    human_advice: str | None = None,
    runtime_vocab: list | None = None,
    per_model_formal: dict[str, float | None] | None = None,
    vocab_diversity_ratio: float | None = None,
    cumulative_information_gain: float | None = None,
    compressed_model_types: set[str] | None = None,
    workspace: str | None = None,
) -> str:
    """Build the user prompt for cross-model synthesis.

    ``compressed_model_types`` (Commit 6.1 — Sliding Window) marks the
    model_types whose ``per_model_summaries`` entry has been replaced
    by a deterministic one-line takeaway (output of
    ``compress_model_summary``). For those entries, this function emits
    a short 3-line block (header + best/n_rounds + takeaway) instead of
    the full multi-section LLM-text expansion, and prefixes the block
    with a single header line that points the LLM to the on-disk
    iteration record for full detail. Active models render unchanged.
    """
    per_model_best_valid = per_model_best_valid or {}
    per_model_raw_best_health_validity = per_model_raw_best_health_validity or {}
    compressed_model_types = compressed_model_types or set()

    lines = [
        "## Overall Performance",
        f"Raw best across all models   : {overall_best_score}",
        f"Best valid across all models : {overall_best_valid_score}",
        f"Worst score across all models: {overall_worst_score}",
        f"Config that produced overall best:\n{json.dumps(overall_best_config, indent=2) if overall_best_config else 'none'}",
        "",
    ]

    # Render active models first (full block), then compressed models
    # (short block) under a single header. Stable iteration order is
    # preserved within each group via the dict's insertion order.
    active_items = [
        (mt, s) for mt, s in per_model_summaries.items() if mt not in compressed_model_types
    ]
    compressed_items = [
        (mt, s) for mt, s in per_model_summaries.items() if mt in compressed_model_types
    ]

    for model_type, summary in active_items:
        lines += [
            "---",
            f"## Model: {model_type}",
            f"Raw best   : {per_model_best.get(model_type)} "
            f"(health={per_model_raw_best_health_validity.get(model_type, 'unknown')})",
            f"Best valid : {per_model_best_valid.get(model_type)}",
            f"Worst score: {per_model_worst.get(model_type)}",
        ]
        if per_model_formal:
            formal = per_model_formal.get(model_type)
            if formal is not None and formal != per_model_best.get(model_type):
                lines.append(
                    f"Formal score: {formal}  (best_score above may be from a trial round)"
                )
        if per_model_params and model_type in per_model_params:
            lines.append(f"Parameters : {per_model_params[model_type]:,}")
        if per_model_training_segments and model_type in per_model_training_segments:
            lines.append(f"Training PSD segments: {per_model_training_segments[model_type]}")

        lines += ["", "### Key Findings"]
        for f in summary.get("key_findings", []):
            lines.append(f"  - {f}")
        lines += ["", "### Bottlenecks"]
        for b in summary.get("bottlenecks", []):
            lines.append(f"  - {b}")
        lines += [
            "",
            "### Best Config Analysis",
            summary.get("best_config_analysis", "N/A"),
            "",
            "### Score Trend",
            summary.get("score_trend", "N/A"),
        ]
        # New per-model analysis fields
        for field in [
            "per_file_analysis",
            "data_sensitivity",
            "efficiency_assessment",
            "strategy_assessment",
        ]:
            val = summary.get(field)
            if val:
                lines += ["", f"### {field.replace('_', ' ').title()}", val]

        # Per-file performance — the full ScoreComparisonTable markdown,
        # which already includes the Impact_Score-ranked secondary block.
        # No threshold-based attention cue: opportunity is read from the
        # Impact_Score column directly.
        if per_model_score_tables and model_type in per_model_score_tables:
            table = per_model_score_tables[model_type]
            lines += [
                "",
                "### Per-file performance (best experiment)",
                table.rendered_markdown,
            ]

        lines.append("")

    # Compressed (stable) models: single header + short blocks.
    if compressed_items:
        ws_hint = (
            f"see {workspace}/iter_*/interpretation.json for full detail"
            if workspace
            else "see prior interpretation.json files for full detail"
        )
        lines += [
            "---",
            "## Stable Architectures (Compressed)",
            f"[{len(compressed_items)} older architectures compressed for "
            f"context budget — {ws_hint}]",
            "",
        ]
        for model_type, summary in compressed_items:
            # Read the field the producer actually emits.
            #
            # This was:
            #     (A or B) if summary.get("key_findings") else "(no cached takeaway)"
            # and `compress_model_summary` returns exactly
            # {model_type, best_score, n_rounds, one_line_takeaway} -- never
            # `key_findings`. The guard was therefore always falsy and EVERY
            # compressed model rendered the placeholder, discarding a
            # takeaway the producer had already computed and truncated to
            # `max_takeaway_chars`. Both sides were tested and both were
            # green; nothing tested the join.
            #
            # No legacy fallback: `compressed_items` is fed only by
            # `compress_model_summary` (one call site, result.py:1301), and
            # 40 persisted interpretation artifacts contain zero
            # compressed-shaped entries carrying `key_findings`.
            takeaway = summary.get("one_line_takeaway") or "(no cached takeaway)"
            best = summary.get("best_score", per_model_best.get(model_type))
            n_rounds = summary.get("n_rounds", 0)
            lines += [
                f"- **{model_type}** (best={best}, n_rounds={n_rounds}): {takeaway}",
            ]
        lines.append("")

    # Established discoveries from previous iterations
    if runtime_vocab:
        discoveries = [
            v
            for v in runtime_vocab
            if (v.get("kind") if isinstance(v, dict) else getattr(v, "kind", None)) == "discovery"
        ]
        if discoveries:
            lines += [
                "---",
                "## Established Discoveries (from previous iterations)",
                "These are empirically confirmed findings from past experiments.",
                "Confirm, contradict, or build on them — do not simply repeat them verbatim.",
            ]
            for v in discoveries:
                name = v.get("name") if isinstance(v, dict) else getattr(v, "name", "")
                desc = (
                    v.get("description") if isinstance(v, dict) else getattr(v, "description", "")
                )
                lines.append(f"  [{name}]: {desc}")
            lines.append("")

    if expert_advice_str:
        lines += [
            "---",
            "## Expert Guidance",
            expert_advice_str,
            "",
        ]

    if human_advice:
        lines += [
            "---",
            "## Human Guidance (highest priority — overrides expert advice)",
            human_advice,
            "",
        ]

    # Research health metrics (centrifugal forces)
    if vocab_diversity_ratio is not None or cumulative_information_gain is not None:
        lines += ["---", "## Research Health Metrics"]
        if vocab_diversity_ratio is not None:
            stagnation_note = " [LOW — explore new concepts]" if vocab_diversity_ratio < 0.1 else ""
            lines.append(
                f"Vocabulary diversity ratio: {vocab_diversity_ratio:.3f}"
                f"  (fraction of feature/capability entries still in candidate tier){stagnation_note}"
            )
        if cumulative_information_gain is not None:
            lines.append(
                f"Cumulative information gain: {cumulative_information_gain:.4f}"
                f"  (total boldness × confirmed across all iterations)"
            )
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Phase C — Semantic deduplication (C.6)
# ---------------------------------------------------------------------------

DEDUP_SYSTEM_PROMPT = """\
You are a scientific vocabulary curator for an ML research system.

Your task: determine whether a newly promoted vocabulary term is a near-duplicate
or synonym of an existing canonical term of the same kind.

Two terms ARE duplicates if they describe the same architectural concept using
different wording — e.g. "gated_recurrence" and "gated_rnn" both describe
hidden-state gating in recurrent networks.

Two terms are NOT duplicates if they describe related but technically distinct
concepts — e.g. "dilated_convolution" and "causal_convolution" are related but
have different technical properties and should remain separate entries.

Judge only on technical meaning, not superficial name similarity.

Respond with a JSON object and nothing else:
{
  "is_duplicate": true or false,
  "duplicate_of": "name_of_existing_term or null",
  "rationale": "one sentence"
}
"""


def _build_dedup_prompt(entry: "VocabEntry", existing_canonicals: list) -> str:
    """Build the user prompt for one dedup judgment."""
    lines = [
        "## Candidate term (newly promoted)",
        f"Name       : {entry.name}",
        f"Kind       : {entry.kind}",
        f"Description: {entry.description}",
        "",
        f"## Existing canonical terms (kind: {entry.kind})",
    ]
    for canon in existing_canonicals:
        name = canon.name if hasattr(canon, "name") else canon.get("name", "")
        desc = canon.description if hasattr(canon, "description") else canon.get("description", "")
        lines.append(f"  - {name}: {desc}")
    lines += [
        "",
        f'Is "{entry.name}" a near-duplicate or synonym of any of the existing terms above?',
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# V8 hardening Domain 3 — Evolution observability
# ---------------------------------------------------------------------------


def _resolve_evolution_log_root(agent_workspace: str) -> str:
    """Resolve the chain-root directory where evolution_log.jsonl lives.

    In chain mode, run_one_iteration.py sets SIDERIUS_CHAIN_WORKSPACE to the
    chain root (one level above the per-iter dir given to the agent), so the
    log accumulates across iters at a single tail-able path. In single-process
    mode the env var is unset and we fall back to the agent's own workspace.
    """
    return os.environ.get("SIDERIUS_CHAIN_WORKSPACE", agent_workspace)


def _compute_evolution_stats(
    runtime_vocab: list[Any],
    promoted_this_iter: int,
    is_degraded: bool,
) -> dict[str, int | bool]:
    """Snapshot vocab counts + promotion + degraded flag.

    `promoted_this_iter` is the count returned by promote_candidates() this
    iter — entries that crossed the Tested-only threshold (seen_in_runs >= 3
    distinct actually-tried runs). It excludes any vocab additions from
    new_discoveries or proposed_candidates that are still in the candidate
    tier.
    """
    canonical = sum(
        1 for v in runtime_vocab if (v.tier if hasattr(v, "tier") else v.get("tier")) == "canonical"
    )
    candidate = sum(
        1 for v in runtime_vocab if (v.tier if hasattr(v, "tier") else v.get("tier")) == "candidate"
    )
    return {
        "vocab_total": len(runtime_vocab),
        "vocab_canonical": canonical,
        "vocab_candidate": candidate,
        "promoted_this_iter": promoted_this_iter,
        "is_degraded": is_degraded,
    }


def _append_evolution_log(workspace_root: str, payload: dict[str, Any]) -> None:
    """Append one JSON line to {workspace_root}/evolution_log.jsonl.

    Append-only: the file is created on first call (iteration 1 of a new
    workspace) and grown on subsequent iters. Each line is a self-contained
    JSON object so `tail -f` shows complete rows. Any IO error is logged but
    swallowed — observability must never break the pipeline.
    """
    import datetime

    log_path = os.path.join(workspace_root, "evolution_log.jsonl")
    line = {
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        **payload,
    }
    try:
        os.makedirs(workspace_root, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, default=str) + "\n")
    except Exception as e:
        print(f"  [evolution_log] WARN: failed to append to {log_path}: {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------


class ResultInterpretationAgent:
    def __init__(
        self,
        provider: str = "gemini",
        model_id: str = "gemini-3.1-flash-lite-preview",
        max_retries: int | None = None,
        bridge_factory=None,
        **kwargs,
    ):
        self._bridge_factory = bridge_factory or LLMBridge
        self.bridge = self._bridge_factory(
            provider=provider, model_id=model_id, max_retries=max_retries
        )

    def run(self, inp: InterpretationInput) -> InterpretationOutput:
        # --- Cold-start branch (explicit workflow state) ---
        # A cold start is the first iteration of a chain with NO prior
        # experimental evidence. There is nothing to interpret or rank, so emit
        # a deterministic "no prior evidence" interpretation (no LLM call, no
        # fabricated history). We branch on the EXPLICIT inp.cold_start flag set
        # by the workflow — never inferred here from empty summaries. Registries
        # remain the proposer's concern (available options), so model_types and
        # model_descriptions are intentionally left empty.
        if inp.cold_start:
            return InterpretationOutput(
                model_types=[],
                model_descriptions={},
                total_experiments=0,
                key_findings=[
                    "Cold start: no prior experimental runs or score history exist yet.",
                ],
                bottlenecks=[],
                take_home_message=(
                    "This is a cold start — there is no prior experimental evidence. "
                    "Propose the first experiment from the task description, the "
                    "available model/loss registries (as options, not results), "
                    "advice, and resource constraints. Do not claim improvement "
                    "over prior runs; none exist."
                ),
                runtime_vocab=inp.runtime_vocab,
                cold_start=True,
                # V19 PR 3 — the deterministic merge runs on every path
                # (a cold start has no summaries, so this is retention
                # applied to the carried history — normally empty).
                collapse_fingerprint_history=merge_fingerprint_history(
                    inp.collapse_fingerprint_history,
                    {},
                    inp.iteration,
                    inp.health_feedback_retention_policy(),
                ),
            )

        # --- Bind the run's ordering authority (Step 09a C2) ---
        # ONE MetricOrder for the whole iteration, from the spec the run
        # already resolved and transported. `None` only where the input
        # contract admitted a spec-less input (cold start / scoreless); a
        # score-bearing input without a spec was refused at construction, so
        # nothing below can silently fall back to "higher is better".
        run_order = bind_run_order(inp)

        def _require_order(what: str) -> MetricOrder:
            """The bound order, or a refusal naming what needed it.

            ``run_order`` is ``None`` only on the cold-start / scoreless path
            the contract admits. Anything below that actually ranks says so.
            """
            if run_order is None:
                raise InterpretationContractError(
                    f"{what} requires the run's MetricOrder, but this input was admitted "
                    "without a MetricSpec (cold start / scoreless). Refusing rather than "
                    "assuming a direction."
                )
            return run_order

        def _require_metric_identity(what: str) -> MetricIdentity:
            """The bound metric's identity, or a refusal naming what needed it.

            Step 09a C4: a NEW prediction's default metric is the run's bound
            id — never the literal ``denoising_score``, which was one task's
            name hardcoded in the framework.
            """
            if run_metric_identity is None:
                raise InterpretationContractError(
                    f"{what} requires the run's bound metric identity, but this input "
                    "was admitted without a MetricSpec (cold start / scoreless)."
                )
            return run_metric_identity

        run_metric_identity = (
            MetricIdentity(metric_id=inp.metric_spec.id, direction=inp.metric_spec.direction)
            if inp.metric_spec is not None
            else None
        )

        # --- Effective model types ---
        # Union of: new summaries + explicitly listed types + cache (models from prior iterations)
        effective_types = sorted(
            {s.model_type for s in inp.summaries}
            | set(inp.model_types or [])
            | set(inp.model_knowledge_cache.keys())
        )

        # --- Load descriptions ---
        # For agent-generated models, the description may be passed directly
        # in ModelRunSummary.model_description (avoiding filesystem dependency).
        # For built-in models, load from description.md on disk.
        model_descriptions: dict[str, str] = {}
        for mt in effective_types:
            # Priority 1: inline description from current iteration's summaries
            inline_desc = None
            for s in inp.summaries:
                if s.model_type == mt and s.model_description:
                    inline_desc = s.model_description
                    break
            if inline_desc:
                model_descriptions[mt] = inline_desc
                continue

            # Priority 2: description cached from a previous iteration's _stats
            cached_stats = inp.model_knowledge_cache.get(mt, {}).get("_stats", {})
            cached_desc = cached_stats.get("model_description")
            if cached_desc:
                model_descriptions[mt] = cached_desc
                continue

            # Priority 3: load from description.md on disk (built-in or plugin models)
            model_descriptions[mt] = get_model_description(mt)

        # --- Deterministic pre-computation (ordering.precompute_evidence) ---
        # New models are read from inp.summaries, cached models from their
        # `_stats` block, and the scientific-aggregation authority filter runs
        # inside the boundary — all BEFORE any LLM call. Unpacked into the
        # local names the rest of the lifecycle already reads.
        evidence = precompute_evidence(
            inp.summaries, inp.model_knowledge_cache, effective_types, order=run_order
        )
        per_model_best = evidence.per_model_best
        per_model_best_valid = evidence.per_model_best_valid
        per_model_raw_best_health_validity = evidence.per_model_raw_best_health_validity
        per_model_worst = evidence.per_model_worst
        per_model_formal = evidence.per_model_formal
        # `evidence.per_model_best_config` is deliberately NOT unpacked: the
        # pre-C1b `run()` built that dict in three places and read it in none
        # (verified at a325f33b). The boundary still computes and exposes it —
        # C6's projections are its first real consumer — but reintroducing a
        # dead local here would be noise, not parity.
        overall_best_score = evidence.overall_best_score
        overall_best_valid_score = evidence.overall_best_valid_score
        overall_worst_score = evidence.overall_worst_score
        overall_best_config = evidence.overall_best_config
        overall_best_valid_config = evidence.overall_best_valid_config
        total_experiments = evidence.total_experiments
        per_model_summary_input = evidence.per_model_summary_input
        aggregation_scope = evidence.aggregation_scope

        # --- Step 09a C6: per-model evidence projection ---
        # Deterministic reads of persisted record fields, computed BEFORE the
        # LLM block for the same structural reason the health evidence is: an
        # interpreter LLM failure must not lose them. New summaries project
        # fresh; cached models keep whatever their `_stats` carried, and a
        # cached model with no stored counts is simply ABSENT rather than
        # reported as zero failures.
        per_model_failure_counts: dict[str, Any] = {
            s_.model_type: s_.failure_counts
            for s_ in inp.summaries
            if s_.failure_counts is not None
        }
        for _mt, _entry in inp.model_knowledge_cache.items():
            if _mt in per_model_failure_counts:
                continue
            _cached_counts = (_entry.get("_stats") or {}).get("failure_counts")
            if _cached_counts is not None:
                per_model_failure_counts[_mt] = _cached_counts
        # Present-when-present. Empty in production until Step 10 carries
        # secondaries upstream (Q-09-7 = B); L1 fixtures supply them directly.
        per_model_secondary_metrics: dict[str, Any] = {
            s_.model_type: list(s_.secondary_metrics)
            for s_ in inp.summaries
            if s_.secondary_metrics
        }

        # Serialize expert advice (soft edge input)
        expert_advice_str = serialize_expert_advice(inp.expert_advice) if inp.expert_advice else ""

        # --- Structured HealthGate feedback: deterministic aggregates +
        #     history merge (V19 PR 3, design §3.6/§3.8/§3.10) ---
        # Computed BEFORE the LLM try-block and threaded into BOTH the
        # healthy and degraded output dicts, so the §3.10 invariant is
        # structural: an interpreter LLM failure cannot lose this
        # iteration's real gate evidence. Inputs are the deterministic
        # RoundHealth data on the summaries — never LLM prose. Populated
        # regardless of enable_structured_health_feedback (recording-only
        # provenance; the flag gates PROMPTS only).
        (
            per_model_round_health_counts,
            per_model_collapse_fingerprints,
            _health_merge_input,
        ) = _collect_health_evidence(inp.summaries)
        collapse_fingerprint_history = merge_fingerprint_history(
            inp.collapse_fingerprint_history,
            _health_merge_input,
            inp.iteration,
            inp.health_feedback_retention_policy(),
        )

        # The bound metric is stated in the operator log: "overall best" means
        # nothing without knowing which way is better (Step 09a C2).
        _metric_banner = (
            f"{run_metric_identity.metric_id} ({run_order.direction}-is-better)"
            if run_order is not None and run_metric_identity is not None
            else "no bound metric (scoreless input)"
        )
        print(
            f"Interpreting {len(inp.summaries)} model summary(ies) across "
            f"{len(effective_types)} model(s): {effective_types} "
            f"(overall best: {overall_best_score}; metric: {_metric_banner})"
        )

        # --- LLM-dependent flow ---
        # V8 hardening Domain 2b: the LLM-dependent portion of run() is
        # wrapped in a try/except. If any bridge.generate() call raises
        # past the Bridge's 3-retry envelope (genuinely persistent failure),
        # we still write a digest carrying the incoming runtime_vocab forward
        # unchanged with is_degraded=True. Without this, an interp LLM
        # failure left no digest on disk and the next iter's
        # load_latest_knowledge() skipped the affected iter — causing a
        # 2-iter vocab regression. See docs/V8_Gap_Report.md Domain 2b.
        try:
            # --- Phase 1: Per-model summarization (Stability Filter — Commit 6.1) ---
            # Compute the active set ONCE for this iter — gates both per_model
            # recall (axis 2) and synthesis-prompt expansion (axis 1).
            #     active_set = Top-K-by-best-score
            #                  ∪ Last-N-by-recency
            #                  ∪ {mt | |Δ score| ≥ threshold}
            # `should_recall_per_model` then decides per-model whether the
            # cache entry can be reused verbatim (no LLM call) or whether
            # fresh evidence warrants a fresh per_model call.
            from nodes.interpretation_helpers import (
                select_active_models,
                should_recall_per_model,
            )

            active_set = select_active_models(
                cache_entries=inp.model_knowledge_cache,
                current_iter_summaries=inp.summaries,
                top_k=inp.active_model_top_k,
                last_n=inp.active_model_last_n,
                score_delta_threshold=inp.active_model_score_delta,
                order=_require_order("selecting the active model set"),
            )
            print(
                f"  Active models ({len(active_set)}/{len(effective_types)}): {sorted(active_set)}"
            )

            model_knowledge_cache: dict[str, dict] = {}
            n_skipped = 0
            for mt in effective_types:
                cache_entry = inp.model_knowledge_cache.get(mt)
                current_summary = per_model_summary_input.get(mt)

                # Stability Filter decision: True → recall LLM, False → reuse cache.
                recall = should_recall_per_model(
                    model_type=mt,
                    cache_entry=cache_entry,
                    current_iter_summary=current_summary,
                    active_set=active_set,
                    score_delta_threshold=inp.active_model_score_delta,
                )

                if not recall and cache_entry is not None:
                    # Stable model with a usable cache → reuse verbatim, emit
                    # audit marker so build_token_baseline_report.py can count
                    # the savings. The skip is countable but charges zero
                    # tokens / chars.
                    model_knowledge_cache[mt] = cache_entry
                    n_skipped += 1
                    self.bridge.emit_marker(
                        label="interpretation.per_model_skipped",
                        extra={"reason": "stable", "model_type": mt},
                    )
                    print(
                        f"  Phase 1: {mt} — Stability Filter skip "
                        f"(cached entry reused, no LLM call)."
                    )
                    continue

                if mt not in per_model_summary_input:
                    # No tuning data and no cache: placeholder (shouldn't happen in normal flow)
                    model_knowledge_cache[mt] = {
                        "key_findings": ["No tuning run available for this model."],
                        "bottlenecks": [],
                        "best_config_analysis": "N/A",
                        "score_trend": "N/A",
                        "_stats": {},
                    }
                    continue

                summary = per_model_summary_input[mt]
                print(
                    f"  Phase 1: Summarizing {mt} ({summary.completed_rounds} rounds) — LLM call..."
                )
                per_model_prompt = _build_per_model_prompt(
                    summary=summary,
                    description=model_descriptions[mt],
                    expert_advice_str=expert_advice_str,
                    human_advice=inp.human_advice,
                    structured_health_feedback=inp.enable_structured_health_feedback,
                    order=run_order,
                )
                # T4b — system prompt has {TASK_DESCRIPTION} placeholder
                # substituted at call time from inp.task_description; see
                # docs/design/enable_global_task_config.md § Commit T4.
                llm_response = self.bridge.generate(
                    _build_per_model_system_prompt(inp),
                    per_model_prompt,
                    label="interpretation.per_model",
                )

                new_stats = {
                    "best_denoising_score": summary.best_denoising_score,
                    "best_valid_denoising_score": summary.best_valid_denoising_score,
                    "best_raw_health_validity": summary.best_raw_health_validity,
                    "worst_denoising_score": summary.worst_denoising_score,
                    "best_file_vector": summary.best_file_vector,
                    "best_score_table": (
                        summary.best_score_table.model_dump() if summary.best_score_table else None
                    ),
                    "best_model_params": summary.best_model_params,
                    "completed_rounds": summary.completed_rounds,
                    "best_config": summary.best_config,
                    "best_valid_config": summary.best_valid_config,
                    "formal_score": summary.formal_score,
                    "model_description": model_descriptions.get(mt),
                    # V19 PR 3 — deterministic side of the cache (§3.6):
                    # cached (non-active) models keep their health facts
                    # without a fresh LLM call.
                    "round_health_counts": per_model_round_health_counts.get(mt, {}),
                    # Step 09a C6 — so a model that goes quiet keeps its
                    # failure counts across iterations without a fresh LLM
                    # call, exactly as round_health_counts does.
                    "failure_counts": (
                        summary.failure_counts.model_dump()
                        if summary.failure_counts is not None
                        else None
                    ),
                    "collapse_fingerprints": [
                        fp.model_dump() for fp in per_model_collapse_fingerprints.get(mt, [])
                    ],
                }

                if cache_entry is None:
                    # Cache miss: build initial entry from the LLM response.
                    # Structurally unchanged from the legacy flat-dict shape
                    # (Rev 8.5 C4 directive). Next iter, this entry is lifted
                    # via CacheEntry.from_legacy_dict before being passed to
                    # consolidate() — so the accumulator activates on the first
                    # active-cache-hit and not earlier.
                    model_knowledge_cache[mt] = {
                        **llm_response,
                        "_stats": new_stats,
                    }
                else:
                    # Active cache hit: run the LLM-powered semantic
                    # consolidator (Commit 6.3, Rev 8.5). The prior entry may
                    # be legacy-flat (first re-call after cache-miss build) or
                    # already in CacheEntry shape (post-first-merge); try the
                    # modern shape first, fall back to the legacy adapter.
                    prior_iter = max(0, inp.iteration - 1)
                    # Modern-shape entries are stored with the `_stats` legacy
                    # alias (line ~920); restore the schema name before
                    # validation. The legacy flat-dict shape (cache-miss build)
                    # has no `model_type` key and falls through to the adapter.
                    candidate = dict(cache_entry)
                    if "_stats" in candidate and "stats" not in candidate:
                        candidate["stats"] = candidate.pop("_stats")
                    try:
                        prior_entry = CacheEntry.model_validate(candidate)
                    except ValidationError:
                        prior_entry = CacheEntry.from_legacy_dict(
                            cache_entry,
                            model_type=mt,
                            current_iter=prior_iter,
                        )

                    merged_entry, archived_items = consolidate(
                        self.bridge,
                        prior=prior_entry,
                        new_llm_response=llm_response,
                        new_stats=new_stats,
                        current_iter=inp.iteration,
                        prior_iter=prior_iter,
                    )

                    dumped = merged_entry.model_dump()
                    # Back-compat: legacy `_stats` key for downstream readers
                    # in this module (lines ~643, ~693, ~873) and the
                    # synthesis-prompt filter (line ~897). The CacheEntry's
                    # `stats` field is the same passthrough dict — only the
                    # key name differs.
                    dumped["_stats"] = dumped.pop("stats")
                    model_knowledge_cache[mt] = dumped

                    if archived_items and inp.storage.backend == "local" and inp.storage.local:
                        archive_dir = os.path.join(
                            inp.storage.local.workspace,
                            f"iter_{inp.iteration:03d}",
                        )
                        os.makedirs(archive_dir, exist_ok=True)
                        archive_path = os.path.join(archive_dir, f"cache_archive_{mt}.json")
                        with open(archive_path, "w", encoding="utf-8") as f:
                            json.dump(archived_items, f, indent=2, default=str)

                print(
                    f"    {mt}: {len(llm_response.get('key_findings', []))} findings, "
                    f"{len(llm_response.get('bottlenecks', []))} bottlenecks"
                )

            if n_skipped:
                print(
                    f"  Stability Filter: {n_skipped} model_type(s) skipped "
                    f"(cache reused; saved {n_skipped} interpretation.per_model "
                    f"LLM call(s) this iter)."
                )

            # --- Pre-compute enriched fields (ordering.collect_enriched_fields) ---
            # Called from HERE, inside the try-block, exactly as before: a
            # malformed cached score table raises, and the degraded path is the
            # designed outcome for that.
            enriched = collect_enriched_fields(
                inp.summaries, inp.model_knowledge_cache, per_model_summary_input
            )
            per_model_score_tables = enriched.per_model_score_tables
            per_model_params = enriched.per_model_params
            per_model_training_segments = enriched.per_model_training_segments

            # --- Phase 2: Cross-model synthesis (Sliding Window — Commit 6.1) ---
            # Active models: full LLM-text block expanded into the synthesis
            # prompt (existing behaviour, minus _stats which is shown separately).
            # Stable models: deterministic one-line takeaway via
            # `compress_model_summary` — no LLM call, target ≤ 200 chars per
            # model. This clamps axis 1 (synthesis prompt-size growth) by
            # replacing the V12 "concatenate every cache entry verbatim"
            # behaviour with a windowed view.
            from nodes.interpretation_helpers import compress_model_summary

            per_model_summaries_for_prompt: dict[str, dict] = {}
            compressed_set: set[str] = set()
            for mt, entry in model_knowledge_cache.items():
                if mt in active_set:
                    per_model_summaries_for_prompt[mt] = _flatten_entry_for_prompt(entry)
                else:
                    per_model_summaries_for_prompt[mt] = compress_model_summary(mt, entry)
                    compressed_set.add(mt)
            n_compressed = len(compressed_set)
            if n_compressed:
                print(
                    f"  Phase 2: {n_compressed} stable model(s) compressed "
                    f"to one-liners for the synthesis prompt "
                    f"(active: {len(active_set)})."
                )

            # Compute prior-state health metrics from the *incoming* vocab and cumulative
            # before Phase 2 synthesis so the LLM can see the research trajectory so far.
            # The updated metrics (post-Phase-C) are computed after vocab is rebuilt below.
            from nodes.interpretation_helpers import compute_vocab_diversity_ratio as _cvdr

            prior_vocab_diversity_ratio = _cvdr(list(inp.runtime_vocab))
            prior_cumulative_info_gain = inp.cumulative_information_gain

            if len(effective_types) == 1:
                single_mt = effective_types[0]
                summary = model_knowledge_cache[single_mt]
                llm_findings = summary.get("key_findings", [])
                llm_bottlenecks = summary.get("bottlenecks", [])
                llm_take_home = (
                    f"The {single_mt} model shows: "
                    + summary.get("score_trend", "unclear trend")
                    + ". "
                    + (summary.get("best_config_analysis", "") or "")
                )
                print("  Phase 2: Single model — skipping synthesis.")
            else:
                print(f"  Phase 2: Synthesizing across {len(effective_types)} models...")
                synthesis_prompt = _build_synthesis_prompt(
                    per_model_summaries=per_model_summaries_for_prompt,
                    per_model_best=per_model_best,
                    per_model_best_valid=per_model_best_valid,
                    per_model_raw_best_health_validity=per_model_raw_best_health_validity,
                    per_model_worst=per_model_worst,
                    overall_best_score=overall_best_score,
                    overall_best_valid_score=overall_best_valid_score,
                    overall_worst_score=overall_worst_score,
                    overall_best_config=overall_best_config,
                    per_model_score_tables=per_model_score_tables or None,
                    per_model_params=per_model_params or None,
                    per_model_training_segments=per_model_training_segments or None,
                    expert_advice_str=expert_advice_str,
                    human_advice=inp.human_advice,
                    runtime_vocab=list(inp.runtime_vocab) if inp.runtime_vocab else None,
                    per_model_formal=per_model_formal or None,
                    vocab_diversity_ratio=prior_vocab_diversity_ratio,
                    cumulative_information_gain=prior_cumulative_info_gain,
                    compressed_model_types=compressed_set,
                    # Cast is a pure type-system shim: at every caller of
                    # this synthesis branch, `storage.backend == "local"` and
                    # `storage.local` is populated. Avoids re-declaring the
                    # invariant as a runtime guard.
                    workspace=cast(LocalStorageConfig, inp.storage.local).workspace,
                )
                # T4b — system prompt has {TASK_DESCRIPTION} placeholder
                # substituted at call time from inp.task_description.
                synthesis_response = self.bridge.generate(
                    _build_synthesis_system_prompt(inp),
                    synthesis_prompt,
                    label="interpretation.synthesis",
                )
                llm_findings = synthesis_response.get("key_findings", [])
                llm_bottlenecks = synthesis_response.get("bottlenecks", [])
                llm_take_home = synthesis_response.get("take_home_message", "")

            # --- Phase C: Vocabulary feedback loop ---
            from nodes.interpretation_helpers import (
                build_runtime_vocab,
                generate_discoveries,
                promote_candidates,
                update_vocab_link_confirmations,
            )

            prediction_evaluation = None
            new_discoveries = []
            prev_model_type = ""

            if inp.previous_proposal:
                prev_prediction = inp.previous_proposal.get("falsifiable_prediction")
                prev_model_type = inp.previous_proposal.get("model_name", "unknown")
                prev_inherited = inp.previous_proposal.get("inherited_components", [])
                prev_vocab_links = inp.previous_proposal.get("proposed_vocab_links", [])

                # Evaluate the prediction against actual results
                if prev_prediction:
                    # Find the best score for the proposed model
                    prev_best = per_model_best.get(prev_model_type)
                    # evaluate_prediction consumes the file_vector as a list of floats
                    # (per its metric-parser contract: "mean(file_vector[N:M])",
                    # "file_vector[N]"). Synthesize that list from rows[i].model so
                    # the reflector-side payload key "best_file_vector" keeps its
                    # existing shape while the upstream dict stores a
                    # ScoreComparisonTable.
                    prev_table = (per_model_score_tables or {}).get(prev_model_type)
                    prev_fv = [r.model for r in prev_table.rows] if prev_table is not None else None

                    actual_results = {
                        "best_denoising_score": prev_best,
                        "best_file_vector": prev_fv,
                    }
                    # current_sota = SOTA at proposal time (FalsifiablePrediction.current_value).
                    # The workflow may pass a fresher value via overall_best_score if needed,
                    # but the proposal-time baseline is the fairest comparison for evaluation.
                    sota_at_proposal = prev_prediction.get("current_value")
                    prediction_evaluation = evaluate_prediction(
                        prev_prediction,
                        actual_results,
                        current_sota=sota_at_proposal,
                        order=_require_order("evaluating the previous prediction"),
                        bound_metric_id=_require_metric_identity(
                            "evaluating the previous prediction"
                        ).metric_id,
                    )
                    print(
                        f"  Prediction evaluation: {prediction_evaluation.get('outcome', '?')} "
                        f"(delta_from_sota={prediction_evaluation.get('delta_from_sota')}, "
                        f"actual={prediction_evaluation.get('actual_value')})"
                    )

                # Generate discoveries from the evaluation
                prev_summary = per_model_summary_input.get(prev_model_type)
                prev_timing = prev_summary.best_timing if prev_summary else None
                new_discoveries = generate_discoveries(
                    prediction_eval=prediction_evaluation,
                    model_type=prev_model_type,
                    best_score=per_model_best.get(prev_model_type),
                    inherited_components=prev_inherited,
                    proposed_vocab_links=prev_vocab_links,
                    timing=prev_timing,
                    overall_best_score=overall_best_score,
                    order=_require_order("generating score-comparison discoveries"),
                )
                if new_discoveries:
                    print(f"  New discoveries: {len(new_discoveries)}")
                    for d in new_discoveries:
                        print(f"    - {d.description[:100]}...")

            # Build updated runtime vocabulary
            # Feature/capability candidates come from proposed_vocab_candidates (C.5-2).
            # Discovery entries are generated separately above and passed as new_discoveries.
            # Inject proposed_by_run from the proposal's model_name so build_runtime_vocab
            # can populate seen_in_runs — the LLM never produces this key itself.
            proposed_candidates = []
            if inp.previous_proposal:
                model_name = inp.previous_proposal.get("model_name", "")
                raw_candidates = inp.previous_proposal.get("proposed_vocab_candidates", [])
                proposed_candidates = [
                    {**c, "proposed_by_run": model_name} if not c.get("proposed_by_run") else c
                    for c in raw_candidates
                ]
            runtime_vocab = build_runtime_vocab(
                incoming_vocab=list(inp.runtime_vocab),
                new_discoveries=new_discoveries,
                proposed_candidates=proposed_candidates,
            )

            # Structural promotion: candidates seen in >= 3 runs → canonical
            runtime_vocab, promoted_names = promote_candidates(runtime_vocab)
            # Log promotions before dedup (promoted entries may be removed by dedup)
            vocab_changes = [
                f"Promoted '{name}' to canonical (seen in "
                f"{next(len(e.seen_in_runs) for e in runtime_vocab if e.name == name)} runs)."
                for name in promoted_names
            ]
            if promoted_names:
                print(f"  Vocab promotions ({len(promoted_names)}): {promoted_names}")

            # Semantic dedup: check newly promoted entries against existing canonicals
            if promoted_names:
                print(f"  Dedup: checking {len(promoted_names)} newly promoted entries...")
                runtime_vocab, merge_changes = self._dedup_promoted(promoted_names, runtime_vocab)
                vocab_changes.extend(merge_changes)

            print(
                f"  Runtime vocab: {len(runtime_vocab)} entries "
                f"({sum(1 for v in runtime_vocab if v.kind == 'discovery')} discoveries, "
                f"{sum(1 for v in runtime_vocab if v.tier == 'canonical')} canonical)"
            )

            # --- Phase E.7: Update ProposedVocabLink confirmation tracking ---
            # When prediction is confirmed, each proposed link from the previous run
            # gains one confirmation. Links confirmed in >= min_runs distinct runs
            # are promoted to VocabEntry.related_to (feature gains capability as established fact).
            prev_vocab_links: list[dict[str, Any]] = (
                inp.previous_proposal.get("proposed_vocab_links", [])
                if inp.previous_proposal
                else []
            )
            link_confirmations, runtime_vocab, promoted_link_pairs = (
                update_vocab_link_confirmations(
                    prev_vocab_links=prev_vocab_links,
                    prediction_outcome=(
                        prediction_evaluation.get("outcome") if prediction_evaluation else None
                    ),
                    run_name=prev_model_type if inp.previous_proposal else "",
                    existing_confirmations=inp.vocab_link_confirmations,
                    runtime_vocab=runtime_vocab,
                    min_runs=3,
                )
            )
            if promoted_link_pairs:
                print(
                    f"  Vocab link promotions ({len(promoted_link_pairs)}): {promoted_link_pairs}"
                )
                for pair in promoted_link_pairs:
                    feature, _, capability = pair.partition(":")
                    vocab_changes.append(
                        f"Link '{feature} → {capability}' confirmed in ≥3 runs; "
                        f"added '{capability}' to {feature}.related_to."
                    )

            # --- Phase E.4: Scientific accuracy tracking (prediction.py) ---
            # Step 09a C4: the LEGACY pool is carried forward untouched; only
            # the versioned pool accumulates, and the accuracy is computed from
            # that pool alone (Q-09a-2).
            legacy_outcomes_history = dict(inp.prediction_outcomes_history)
            new_outcomes_by_semantics, scientific_accuracy = accumulate_prediction_outcomes(
                inp.prediction_outcomes_by_semantics, prediction_evaluation
            )
            pool_sizes = prediction_pool_sizes(legacy_outcomes_history, new_outcomes_by_semantics)
            if scientific_accuracy:
                v2_total = pool_sizes[PREDICTION_SEMANTICS_SIGNSAFE_V2]
                print(
                    f"  Scientific accuracy ({PREDICTION_SEMANTICS_SIGNSAFE_V2}): "
                    f"{scientific_accuracy} (n={v2_total}; "
                    f"legacy pool n={pool_sizes[PREDICTION_SEMANTICS_LEGACY_V1]}, "
                    f"not pooled)"
                )

            # --- Centrifugal health metrics (post-Phase-C, on the updated vocab) ---
            vocab_diversity_ratio = _cvdr(runtime_vocab)
            # The legacy scalar is preserved verbatim; only the versioned sum
            # accumulates. No single number anywhere means "legacy + v2".
            cumulative_information_gain = inp.cumulative_information_gain
            new_gain_by_semantics = accumulate_information_gain(
                inp.cumulative_information_gain_by_semantics, prediction_evaluation
            )
            print(
                f"  Vocab diversity ratio: {vocab_diversity_ratio:.3f} "
                f"(cumulative info gain: {cumulative_information_gain:.4f})"
            )

            # --- V8 Domain 3 — evolution stats (healthy path) ---
            # Snapshot vocab counts + promotion count + degraded flag now,
            # after promote_candidates + dedup have settled. promoted_names
            # carries the count from promote_candidates this iter (Tested-only
            # threshold). is_degraded=False on the healthy return.
            evolution_stats = _compute_evolution_stats(
                runtime_vocab=runtime_vocab,
                promoted_this_iter=len(promoted_names),
                is_degraded=False,
            )

            # --- Build and validate output ---
            output = InterpretationOutput.model_validate(
                {
                    "model_types": effective_types,
                    "model_descriptions": model_descriptions,
                    "total_experiments": total_experiments,
                    "per_model_best": per_model_best,
                    "per_model_best_valid": per_model_best_valid,
                    "per_model_raw_best_health_validity": per_model_raw_best_health_validity,
                    "per_model_worst": per_model_worst,
                    # D-C5: threaded into BOTH the healthy and the
                    # degraded dict, so an interpreter LLM failure
                    # cannot lose the exclusion provenance — the same
                    # structural rule the health evidence follows.
                    "scientific_aggregation": aggregation_scope.model_dump(),
                    "best_denoising_score": overall_best_score,
                    "best_valid_denoising_score": overall_best_valid_score,
                    "worst_denoising_score": overall_worst_score,
                    "best_config": overall_best_config,
                    "best_valid_config": overall_best_valid_config,
                    "model_knowledge_cache": model_knowledge_cache,
                    # V19 PR 3 — deterministic health evidence, computed
                    # before the LLM block (never from prose).
                    "per_model_round_health_counts": per_model_round_health_counts,
                    "per_model_collapse_fingerprints": per_model_collapse_fingerprints,
                    "collapse_fingerprint_history": collapse_fingerprint_history,
                    "key_findings": llm_findings,
                    "bottlenecks": llm_bottlenecks,
                    # Enriched fields
                    "per_model_score_tables": per_model_score_tables or None,
                    "per_model_params": per_model_params or None,
                    "per_model_training_segments": per_model_training_segments or None,
                    "take_home_message": llm_take_home,
                    # Phase C: vocabulary feedback
                    "runtime_vocab": [
                        v.model_dump() if hasattr(v, "model_dump") else v for v in runtime_vocab
                    ],
                    "prediction_evaluation": prediction_evaluation,
                    "new_discoveries": [d.model_dump() for d in new_discoveries],
                    "vocab_changes": vocab_changes,
                    # Centrifugal health metrics
                    "vocab_diversity_ratio": vocab_diversity_ratio,
                    "cumulative_information_gain": cumulative_information_gain,
                    # Phase E: scientific accuracy + vocab link promotion
                    "scientific_accuracy": scientific_accuracy,
                    # Step 09a C4 — the legacy pool passes through UNCHANGED;
                    # the versioned pools carry this iteration's outcome.
                    "prediction_outcomes_history": legacy_outcomes_history,
                    "prediction_outcomes_by_semantics": new_outcomes_by_semantics,
                    "cumulative_information_gain_by_semantics": new_gain_by_semantics,
                    "prediction_pool_sizes": pool_sizes,
                    "prediction_evaluation_semantics": PREDICTION_SEMANTICS_SIGNSAFE_V2,
                    "vocab_link_confirmations": link_confirmations,
                    # V8 Domain 3 — evolution observability
                    "evolution_stats": evolution_stats,
                    # Step 09a C2 — which metric this iteration was ORDERED
                    # under. Provenance, not evidence.
                    "metric_identity": run_metric_identity,
                    # Step 09a C6 — deterministic evidence projection.
                    "per_model_failure_counts": per_model_failure_counts,
                    "per_model_secondary_metrics": per_model_secondary_metrics,
                }
            )

            # --- Persist ---
            if inp.storage.backend == "local" and inp.storage.local:
                workspace = inp.storage.local.workspace
                run_name = inp.storage.local.run_name
                os.makedirs(workspace, exist_ok=True)
                out_path = os.path.join(workspace, f"interpretation_{run_name}.json")
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(output.model_dump_json(indent=4))
                print(f"Interpretation saved -> {out_path}")

                # V8 Domain 3 — append per-iter row to chain-root evolution log.
                # Resolved via SIDERIUS_CHAIN_WORKSPACE in chain mode (one level
                # above the per-iter agent workspace) so all iters share one
                # tail-able file. Falls back to the agent workspace otherwise.
                _append_evolution_log(
                    workspace_root=_resolve_evolution_log_root(workspace),
                    payload={
                        "iteration": inp.iteration,
                        "evolution_stats": evolution_stats,
                        "best_score_so_far": output.best_denoising_score,
                        "take_home_message": output.take_home_message,
                    },
                )

            return output
        except Exception as e:
            print(f"  [DEGRADED] Interpretation LLM flow failed: {type(e).__name__}: {e}")
            print(
                f"  [DEGRADED] Carrying forward incoming runtime_vocab "
                f"({len(inp.runtime_vocab)} entries) unchanged. "
                f"Writing digest with is_degraded=True."
            )
            # V8 Domain 3 — evolution stats (degraded path).
            # No promotions ran; vocab is the incoming list verbatim. Still
            # emit a row so tail -f sees the iter and the dashboard can flag
            # is_degraded=True visually.
            degraded_stats = _compute_evolution_stats(
                runtime_vocab=list(inp.runtime_vocab),
                promoted_this_iter=0,
                is_degraded=True,
            )
            output = InterpretationOutput.model_validate(
                {
                    "model_types": effective_types,
                    "model_descriptions": model_descriptions,
                    "total_experiments": total_experiments,
                    "per_model_best": per_model_best,
                    "per_model_best_valid": per_model_best_valid,
                    "per_model_raw_best_health_validity": per_model_raw_best_health_validity,
                    "per_model_worst": per_model_worst,
                    # D-C5: threaded into BOTH the healthy and the
                    # degraded dict, so an interpreter LLM failure
                    # cannot lose the exclusion provenance — the same
                    # structural rule the health evidence follows.
                    "scientific_aggregation": aggregation_scope.model_dump(),
                    "best_denoising_score": overall_best_score,
                    "best_valid_denoising_score": overall_best_valid_score,
                    "worst_denoising_score": overall_worst_score,
                    "best_config": overall_best_config,
                    "best_valid_config": overall_best_valid_config,
                    "model_knowledge_cache": dict(inp.model_knowledge_cache),
                    # V19 PR 3 §3.10 invariant: the deterministic merge ran
                    # BEFORE the LLM block, so this iteration's real gate
                    # evidence is recorded even though the LLM failed.
                    # Degradation affects LLM commentary only.
                    "per_model_round_health_counts": per_model_round_health_counts,
                    "per_model_collapse_fingerprints": per_model_collapse_fingerprints,
                    "collapse_fingerprint_history": collapse_fingerprint_history,
                    "key_findings": [],
                    "bottlenecks": [],
                    "take_home_message": (
                        f"DEGRADED: interpreter LLM failed "
                        f"({type(e).__name__}). Vocab carried forward unchanged."
                    ),
                    "runtime_vocab": [
                        v.model_dump() if hasattr(v, "model_dump") else v for v in inp.runtime_vocab
                    ],
                    "new_discoveries": [],
                    "vocab_changes": [],
                    "prediction_outcomes_history": dict(inp.prediction_outcomes_history),
                    # Step 09a C4 — the degraded path copies every pool and sum
                    # forward unchanged. No re-basing exists: the structure is
                    # versioned, so nothing has to be reinterpreted here.
                    "prediction_outcomes_by_semantics": {
                        version: dict(counts)
                        for version, counts in inp.prediction_outcomes_by_semantics.items()
                    },
                    "cumulative_information_gain_by_semantics": dict(
                        inp.cumulative_information_gain_by_semantics
                    ),
                    "prediction_pool_sizes": prediction_pool_sizes(
                        dict(inp.prediction_outcomes_history),
                        inp.prediction_outcomes_by_semantics,
                    ),
                    "prediction_evaluation_semantics": PREDICTION_SEMANTICS_SIGNSAFE_V2,
                    "vocab_link_confirmations": dict(inp.vocab_link_confirmations),
                    "cumulative_information_gain": inp.cumulative_information_gain,
                    "is_degraded": True,
                    "evolution_stats": degraded_stats,
                    # Step 09a C2 — threaded into the degraded dict too: an
                    # interpreter LLM failure must not lose the ordering
                    # provenance (the same structural rule the health
                    # evidence and the aggregation scope follow).
                    "metric_identity": run_metric_identity,
                    # Step 09a C6 — deterministic evidence projection.
                    "per_model_failure_counts": per_model_failure_counts,
                    "per_model_secondary_metrics": per_model_secondary_metrics,
                }
            )
            if inp.storage.backend == "local" and inp.storage.local:
                workspace = inp.storage.local.workspace
                run_name = inp.storage.local.run_name
                os.makedirs(workspace, exist_ok=True)
                out_path = os.path.join(workspace, f"interpretation_{run_name}.json")
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(output.model_dump_json(indent=4))
                print(f"  [DEGRADED] Interpretation saved -> {out_path}")

                _append_evolution_log(
                    workspace_root=_resolve_evolution_log_root(workspace),
                    payload={
                        "iteration": inp.iteration,
                        "evolution_stats": degraded_stats,
                        "best_score_so_far": output.best_denoising_score,
                        "take_home_message": output.take_home_message,
                    },
                )
            return output

    def _dedup_promoted(
        self,
        promoted_names: list[str],
        vocab: list["VocabEntry"],
    ) -> tuple[list["VocabEntry"], list[str]]:
        """
        Semantic deduplication of newly promoted canonical entries (C.6).

        For each promoted entry, asks the LLM whether it is a near-duplicate of
        an existing canonical of the same kind. If yes: the promoted entry is
        removed from the vocab and its name is added to the existing entry's
        aliases. If no: it stays canonical.

        Each promoted entry that has at least one existing canonical of the same
        kind triggers one LLM call. Promotion is rare so total cost is low.

        Args:
            promoted_names: Names of entries just promoted by promote_candidates.
            vocab:          Current runtime vocabulary (includes promoted entries).

        Returns:
            (updated_vocab, merge_changes) — updated vocab and human-readable
            log strings for each merge (e.g. "Merged 'x' into 'y' as alias.").
        """

        if not promoted_names:
            return vocab, []

        vocab_by_name: dict[str, Any] = {e.name: e for e in vocab}
        merge_changes: list[str] = []

        for name in promoted_names:
            if name not in vocab_by_name:
                continue  # already removed by a prior merge this loop

            entry = vocab_by_name[name]
            kind = entry.kind if hasattr(entry, "kind") else entry.get("kind", "")

            # Only compare against existing canonicals of the same kind
            existing = [
                e
                for n, e in vocab_by_name.items()
                if n != name
                and (e.tier if hasattr(e, "tier") else e.get("tier")) == "canonical"
                and (e.kind if hasattr(e, "kind") else e.get("kind")) == kind
            ]
            if not existing:
                print(f"  Dedup: '{name}' — no existing canonicals of kind='{kind}', keeping.")
                continue

            prompt = _build_dedup_prompt(entry, existing)
            response = self.bridge.generate(
                DEDUP_SYSTEM_PROMPT,
                prompt,
                label="interpretation.dedup",
            )

            is_dup = response.get("is_duplicate", False)
            dup_of = response.get("duplicate_of")
            rationale = response.get("rationale", "")

            if is_dup and dup_of and dup_of in vocab_by_name:
                existing_entry = vocab_by_name[dup_of]
                current_aliases = (
                    existing_entry.aliases
                    if hasattr(existing_entry, "aliases")
                    else existing_entry.get("aliases", [])
                )
                vocab_by_name[dup_of] = existing_entry.model_copy(
                    update={"aliases": [*current_aliases, name]}
                )
                del vocab_by_name[name]
                msg = f"Merged '{name}' into '{dup_of}' as alias. Rationale: {rationale}"
                merge_changes.append(msg)
                print(f"  Dedup: {msg}")
            else:
                print(f"  Dedup: '{name}' — genuine new canonical.")

        return list(vocab_by_name.values()), merge_changes


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="SIDERIUS result_interpretation_agent")
    parser.add_argument(
        "--workspace",
        type=str,
        default="./siderius_workspace",
        help="Root directory for reading summaries and writing output",
    )
    parser.add_argument(
        "--run_name",
        type=str,
        default="v1",
        help="Run name — reads summary_{run_name}.json, writes interpretation_{run_name}.json",
    )
    parser.add_argument(
        "--model_type", type=str, required=True, help="Model architecture (e.g. 'punet')."
    )
    parser.add_argument("--provider", type=str, default="gemini", choices=["gemini", "openai"])
    parser.add_argument("--model_id", type=str, default="gemini-3.1-flash-lite-preview")
    args = parser.parse_args()

    # Load run output from workspace
    output_path = os.path.join(args.workspace, f"run_output_{args.run_name}.json")
    if not os.path.exists(output_path):
        raise FileNotFoundError(
            f"Run output not found: {output_path}\n"
            f"Run tune_ml_hyperparam_agent first, or check --workspace and --run_name."
        )
    with open(output_path, encoding="utf-8") as f:
        run_data = json.load(f)

    # Build ModelRunSummary from run output
    from agent.schemas.hyperparam_tuning import HyperparamTuningOutput

    tune_output = HyperparamTuningOutput.model_validate(run_data)
    run_metric_spec = reconcile_metric_spec([tune_output])
    summary = tuning_output_to_model_run_summary(
        tune_output,
        order=MetricOrder(run_metric_spec) if run_metric_spec is not None else None,
    )

    agent_input = InterpretationInput(
        summaries=[summary],
        # Step 09a C2 — the spec comes FROM the loaded output; the CLI derives
        # nothing. A legacy/pre-09a output carries none, and the input contract
        # then refuses with a named error instead of ordering on a guess.
        metric_spec=run_metric_spec,
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=args.workspace, run_name=args.run_name),
        ),
    )
    print(f"Input validated: model={args.model_type} | rounds={summary.completed_rounds}")

    agent = ResultInterpretationAgent(provider=args.provider, model_id=args.model_id)
    output = agent.run(agent_input)

    print(f"\n{'=' * 60}")
    print(f"  Interpretation — {output.model_types}")
    print(f"{'=' * 60}")
    print(f"  Total experiments : {output.total_experiments}")
    print(f"  Overall best      : {output.best_denoising_score}")
    print(f"  Overall worst     : {output.worst_denoising_score}")
    for mt in output.model_types:
        print(
            f"  {mt}: best={output.per_model_best.get(mt)} worst={output.per_model_worst.get(mt)}"
        )
    print("\n  Key findings:")
    for f in output.key_findings:
        print(f"    - {f}")
    print("\n  Bottlenecks:")
    for b in output.bottlenecks:
        print(f"    - {b}")
    print("\n  Take-home message:")
    print(f"    {output.take_home_message}")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
