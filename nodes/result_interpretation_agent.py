# nodes/result_interpretation_agent.py
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

import os
import json
import argparse
from typing import Any, Dict, List, Optional

from agent.llm_bridge import LLMBridge
from agent.schemas.interpretation import (
    InterpretationInput, InterpretationOutput, ModelRunSummary,
)
from agent.schemas.score_table import ScoreComparisonTable
from agent.schemas.storage import StorageConfig, LocalStorageConfig
from ml_models.model_descriptions import get_model_description
from agent.schemas.hyperparam_tuning import serialize_expert_advice


# ---------------------------------------------------------------------------
# Phase 1 — Per-model summarization
# ---------------------------------------------------------------------------

PER_MODEL_SYSTEM_PROMPT = """\
You are a senior ML research analyst specialising in deep learning for signal denoising.

Your task: analyse the tuning run summary for ONE model architecture and produce a
structured analysis covering performance, per-file behaviour, data sensitivity,
training dynamics, efficiency, and strategy assessment.

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
  "per_file_analysis": "Read the per-file table by Impact_Score descending. Cite specific files only by their Impact_Score and Linear_Weight values for this iter. Identify which files carry the largest remaining lever and which are already saturated. Do not assert a file is permanently weak from a single iter's reading.",
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


def _build_per_model_prompt(
    summary: ModelRunSummary,
    description: str,
    expert_advice_str: str = "",
    human_advice: Optional[str] = None,
) -> str:
    """Build the user prompt for a single model's summarization."""
    lines = [
        f"## Model: {summary.model_type}",
        f"Run: {summary.run_name} | Status: {summary.status} | Rounds: {summary.completed_rounds}",
        f"Best denoising score : {summary.best_denoising_score}",
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
        lines.append(f"Training PSD segments: {summary.training_psd_segments} "
                      f"(baseline typically uses 4000)")
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
        trial_p = (summary.round_trial_portions[i]
                   if summary.round_trial_portions and i < len(summary.round_trial_portions) else None)
        params = (summary.round_model_params[i]
                  if summary.round_model_params and i < len(summary.round_model_params) else None)

        score_str = f"{score:.4f}" if score is not None else "skipped"
        extras = []
        if trial_p is not None:
            extras.append(f"portion={trial_p}")
        if params is not None:
            extras.append(f"params={params:,}")
        extra_str = f" [{', '.join(extras)}]" if extras else ""

        lines.append(f"  Round {i+1}: score={score_str}{extra_str} — {conclusion}")

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
You are a senior ML research analyst specialising in deep learning for signal denoising.

Your task: read structured summaries of multiple model architectures and produce a
cross-model interpretation that identifies the overall state of the research and
motivates the next step.

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
  "take_home_message": "One sentence: the single most critical insight that motivates the next step. If the Impact_Score distribution across all candidate models is small relative to model_scalar, declare ceiling reached rather than manufacture an architectural deficiency."
}

Rules:
- key_findings: ranked by importance, MUST compare across models, reference actual scores
- bottlenecks: focus on fundamental limitations shared across architectures, not per-model issues
- per_file_comparison: rank by Impact_Score descending; cite Linear_Weight as context, not as a ranking metric on its own; do not use fixed cutoffs or fixed file-index labels
- efficiency_comparison: reference actual parameter counts and scores
- take_home_message: exactly one sentence, grounded in the Impact_Score distribution
- Do not repeat per-model findings verbatim — synthesise and draw cross-model conclusions
- Output only the JSON object — no preamble, no commentary, no markdown
"""


def _build_synthesis_prompt(
    per_model_summaries: Dict[str, Dict],
    per_model_best: Dict[str, Optional[float]],
    per_model_worst: Dict[str, Optional[float]],
    overall_best_score: Optional[float],
    overall_worst_score: Optional[float],
    overall_best_config: Optional[Dict],
    per_model_score_tables: Optional[Dict[str, ScoreComparisonTable]] = None,
    per_model_params: Optional[Dict[str, int]] = None,
    per_model_training_segments: Optional[Dict[str, int]] = None,
    expert_advice_str: str = "",
    human_advice: Optional[str] = None,
    runtime_vocab: Optional[List] = None,
    per_model_formal: Optional[Dict[str, Optional[float]]] = None,
    vocab_diversity_ratio: Optional[float] = None,
    cumulative_information_gain: Optional[float] = None,
) -> str:
    """Build the user prompt for cross-model synthesis."""
    lines = [
        "## Overall Performance",
        f"Best score across all models : {overall_best_score}",
        f"Worst score across all models: {overall_worst_score}",
        f"Config that produced overall best:\n{json.dumps(overall_best_config, indent=2) if overall_best_config else 'none'}",
        "",
    ]

    for model_type, summary in per_model_summaries.items():
        lines += [
            "---",
            f"## Model: {model_type}",
            f"Best score : {per_model_best.get(model_type)}",
            f"Worst score: {per_model_worst.get(model_type)}",
        ]
        if per_model_formal:
            formal = per_model_formal.get(model_type)
            if formal is not None and formal != per_model_best.get(model_type):
                lines.append(f"Formal score: {formal}  (best_score above may be from a trial round)")
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
            f"### Best Config Analysis",
            summary.get("best_config_analysis", "N/A"),
            "",
            f"### Score Trend",
            summary.get("score_trend", "N/A"),
        ]
        # New per-model analysis fields
        for field in ["per_file_analysis", "data_sensitivity", "efficiency_assessment", "strategy_assessment"]:
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

    # Established discoveries from previous iterations
    if runtime_vocab:
        discoveries = [
            v for v in runtime_vocab
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
                desc = v.get("description") if isinstance(v, dict) else getattr(v, "description", "")
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


def _build_dedup_prompt(entry: "VocabEntry", existing_canonicals: List) -> str:
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
    runtime_vocab: List[Any],
    promoted_this_iter: int,
    is_degraded: bool,
) -> Dict[str, int | bool]:
    """Snapshot vocab counts + promotion + degraded flag.

    `promoted_this_iter` is the count returned by promote_candidates() this
    iter — entries that crossed the Tested-only threshold (seen_in_runs >= 3
    distinct actually-tried runs). It excludes any vocab additions from
    new_discoveries or proposed_candidates that are still in the candidate
    tier.
    """
    canonical = sum(
        1 for v in runtime_vocab
        if (v.tier if hasattr(v, "tier") else v.get("tier")) == "canonical"
    )
    candidate = sum(
        1 for v in runtime_vocab
        if (v.tier if hasattr(v, "tier") else v.get("tier")) == "candidate"
    )
    return {
        "vocab_total":         len(runtime_vocab),
        "vocab_canonical":     canonical,
        "vocab_candidate":     candidate,
        "promoted_this_iter":  promoted_this_iter,
        "is_degraded":         is_degraded,
    }


def _append_evolution_log(workspace_root: str, payload: Dict[str, Any]) -> None:
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
        print(
            f"  [evolution_log] WARN: failed to append to {log_path}: "
            f"{type(e).__name__}: {e}"
        )


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

class ResultInterpretationAgent:

    def __init__(self, provider: str = "gemini", model_id: str = "gemini-3.1-flash-lite-preview",
                 max_retries: int | None = None, bridge_factory=None, **kwargs):
        self._bridge_factory = bridge_factory or LLMBridge
        self.bridge = self._bridge_factory(provider=provider, model_id=model_id, max_retries=max_retries)

    def run(self, inp: InterpretationInput) -> InterpretationOutput:
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
        model_descriptions: Dict[str, str] = {}
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

        # --- Deterministic pre-computation ---
        # New models: read from inp.summaries.
        # Cached models: read from inp.model_knowledge_cache[mt]["_stats"].
        per_model_best:   Dict[str, Optional[float]] = {}
        per_model_worst:  Dict[str, Optional[float]] = {}
        per_model_formal: Dict[str, Optional[float]] = {}
        per_model_best_config: Dict[str, Optional[Dict]] = {}
        overall_best_score:  Optional[float] = None
        overall_worst_score: Optional[float] = None
        overall_best_config: Optional[Dict[str, Any]] = None
        total_experiments = 0

        # Map model_type → ModelRunSummary (new models only)
        per_model_summary_input: Dict[str, ModelRunSummary] = {}

        for s in inp.summaries:
            mt = s.model_type
            per_model_summary_input[mt] = s
            total_experiments += s.completed_rounds

            if s.best_denoising_score is not None:
                if per_model_best.get(mt) is None or s.best_denoising_score > per_model_best[mt]:
                    per_model_best[mt] = s.best_denoising_score
                    per_model_best_config[mt] = s.best_config
                if overall_best_score is None or s.best_denoising_score > overall_best_score:
                    overall_best_score = s.best_denoising_score
                    overall_best_config = s.best_config

            if s.worst_denoising_score is not None:
                if per_model_worst.get(mt) is None or s.worst_denoising_score < per_model_worst[mt]:
                    per_model_worst[mt] = s.worst_denoising_score
                if overall_worst_score is None or s.worst_denoising_score < overall_worst_score:
                    overall_worst_score = s.worst_denoising_score

            if s.formal_score is not None:
                per_model_formal[mt] = s.formal_score

        # Reconstruct stats for cached models from their _stats block
        for mt, entry in inp.model_knowledge_cache.items():
            if mt in per_model_summary_input:
                continue  # new summary takes precedence
            stats = entry.get("_stats", {})
            best  = stats.get("best_denoising_score")
            worst = stats.get("worst_denoising_score")
            total_experiments += stats.get("completed_rounds", 0)

            per_model_best[mt]   = best
            per_model_worst[mt]  = worst
            per_model_best_config[mt] = stats.get("best_config")
            if stats.get("formal_score") is not None:
                per_model_formal[mt] = stats["formal_score"]

            if best is not None:
                if overall_best_score is None or best > overall_best_score:
                    overall_best_score = best
                    overall_best_config = stats.get("best_config")
            if worst is not None:
                if overall_worst_score is None or worst < overall_worst_score:
                    overall_worst_score = worst

        # Fill None for any model type still missing
        for mt in effective_types:
            per_model_best.setdefault(mt, None)
            per_model_worst.setdefault(mt, None)
            per_model_best_config.setdefault(mt, None)

        # Serialize expert advice (soft edge input)
        expert_advice_str = serialize_expert_advice(inp.expert_advice) if inp.expert_advice else ""

        print(f"Interpreting {len(inp.summaries)} model summary(ies) across "
              f"{len(effective_types)} model(s): {effective_types} "
              f"(overall best: {overall_best_score})")

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
            # --- Phase 1: Per-model summarization (cache-first) ---
            # Cache hit  → reuse entry from inp.model_knowledge_cache, zero LLM calls.
            # Cache miss → call LLM, build self-sufficient entry (LLM text + _stats).
            model_knowledge_cache: Dict[str, Dict] = {}
            for mt in effective_types:
                if mt in inp.model_knowledge_cache:
                    # Cache hit: model was summarized in a previous iteration
                    model_knowledge_cache[mt] = inp.model_knowledge_cache[mt]
                    print(f"  Phase 1: {mt} — cache hit, skipping LLM call.")
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
                print(f"  Phase 1: Summarizing {mt} ({summary.completed_rounds} rounds) — LLM call...")
                per_model_prompt = _build_per_model_prompt(
                    summary=summary,
                    description=model_descriptions[mt],
                    expert_advice_str=expert_advice_str,
                    human_advice=inp.human_advice,
                )
                llm_response = self.bridge.generate(PER_MODEL_SYSTEM_PROMPT, per_model_prompt)
                # Build self-sufficient cache entry: LLM text + numerical _stats.
                # best_score_table is stored as a plain dict so model_knowledge_cache
                # round-trips through JSON serialization cleanly; reads must
                # re-validate it through ScoreComparisonTable.model_validate.
                model_knowledge_cache[mt] = {
                    **llm_response,
                    "_stats": {
                        "best_denoising_score":  summary.best_denoising_score,
                        "worst_denoising_score": summary.worst_denoising_score,
                        "best_file_vector":      summary.best_file_vector,
                        "best_score_table":      (
                            summary.best_score_table.model_dump()
                            if summary.best_score_table else None
                        ),
                        "best_model_params":     summary.best_model_params,
                        "completed_rounds":      summary.completed_rounds,
                        "best_config":           summary.best_config,
                        "formal_score":          summary.formal_score,
                        "model_description":     model_descriptions.get(mt),
                    },
                }
                print(f"    {mt}: {len(llm_response.get('key_findings', []))} findings, "
                      f"{len(llm_response.get('bottlenecks', []))} bottlenecks")

            # --- Pre-compute enriched fields ---
            # New models: read from inp.summaries.
            # Cached models: read from model_knowledge_cache[mt]["_stats"].
            per_model_score_tables: Dict[str, ScoreComparisonTable] = {}
            per_model_params: Dict[str, int] = {}
            per_model_training_segments: Dict[str, int] = {}

            def _register_score_table(mt: str, table: Optional[ScoreComparisonTable]):
                if table is None:
                    return
                per_model_score_tables[mt] = table

            for s in inp.summaries:
                mt = s.model_type
                _register_score_table(mt, s.best_score_table)
                if s.best_model_params is not None:
                    per_model_params[mt] = s.best_model_params
                if s.training_psd_segments is not None:
                    per_model_training_segments[mt] = s.training_psd_segments

            # Fill from cache _stats for cached models not in new summaries. The
            # cache stores best_score_table as a plain dict (JSON round-trip safe)
            # — re-validate it back into a ScoreComparisonTable before registering.
            for mt, entry in inp.model_knowledge_cache.items():
                if mt in per_model_summary_input:
                    continue
                stats = entry.get("_stats", {})
                cached_table_data = stats.get("best_score_table")
                cached_table = (
                    ScoreComparisonTable.model_validate(cached_table_data)
                    if cached_table_data is not None else None
                )
                _register_score_table(mt, cached_table)
                if stats.get("best_model_params") is not None:
                    per_model_params[mt] = stats["best_model_params"]

            # --- Phase 2: Cross-model synthesis ---
            # Strip _stats from model_knowledge_cache entries before passing to synthesis
            # (synthesis prompt receives the LLM text fields only, stats are shown separately)
            per_model_summaries_for_prompt = {
                mt: {k: v for k, v in entry.items() if k != "_stats"}
                for mt, entry in model_knowledge_cache.items()
            }

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
                    + ". " + (summary.get("best_config_analysis", "") or "")
                )
                print(f"  Phase 2: Single model — skipping synthesis.")
            else:
                print(f"  Phase 2: Synthesizing across {len(effective_types)} models...")
                synthesis_prompt = _build_synthesis_prompt(
                    per_model_summaries=per_model_summaries_for_prompt,
                    per_model_best=per_model_best,
                    per_model_worst=per_model_worst,
                    overall_best_score=overall_best_score,
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
                )
                synthesis_response = self.bridge.generate(SYNTHESIS_SYSTEM_PROMPT, synthesis_prompt)
                llm_findings = synthesis_response.get("key_findings", [])
                llm_bottlenecks = synthesis_response.get("bottlenecks", [])
                llm_take_home = synthesis_response.get("take_home_message", "")

            # --- Phase C: Vocabulary feedback loop ---
            from nodes.interpretation_helpers import (
                evaluate_prediction, generate_discoveries, build_runtime_vocab,
                promote_candidates, update_vocab_link_confirmations,
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
                    prev_fv = (
                        [r.model for r in prev_table.rows]
                        if prev_table is not None else None
                    )

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
                    )
                    print(f"  Prediction evaluation: {prediction_evaluation.get('outcome', '?')} "
                          f"(delta_from_sota={prediction_evaluation.get('delta_from_sota')}, "
                          f"actual={prediction_evaluation.get('actual_value')})")

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

            print(f"  Runtime vocab: {len(runtime_vocab)} entries "
                  f"({sum(1 for v in runtime_vocab if (v.kind if hasattr(v, 'kind') else v.get('kind')) == 'discovery')} discoveries, "
                  f"{sum(1 for v in runtime_vocab if (v.tier if hasattr(v, 'tier') else v.get('tier')) == 'canonical')} canonical)")

            # --- Phase E.7: Update ProposedVocabLink confirmation tracking ---
            # When prediction is confirmed, each proposed link from the previous run
            # gains one confirmation. Links confirmed in >= min_runs distinct runs
            # are promoted to VocabEntry.related_to (feature gains capability as established fact).
            prev_vocab_links: List[Dict[str, Any]] = (
                inp.previous_proposal.get("proposed_vocab_links", [])
                if inp.previous_proposal else []
            )
            link_confirmations, runtime_vocab, promoted_link_pairs = update_vocab_link_confirmations(
                prev_vocab_links=prev_vocab_links,
                prediction_outcome=(
                    prediction_evaluation.get("outcome") if prediction_evaluation else None
                ),
                run_name=prev_model_type if inp.previous_proposal else "",
                existing_confirmations=inp.vocab_link_confirmations,
                runtime_vocab=runtime_vocab,
                min_runs=3,
            )
            if promoted_link_pairs:
                print(f"  Vocab link promotions ({len(promoted_link_pairs)}): {promoted_link_pairs}")
                for pair in promoted_link_pairs:
                    feature, _, capability = pair.partition(":")
                    vocab_changes.append(
                        f"Link '{feature} → {capability}' confirmed in ≥3 runs; "
                        f"added '{capability}' to {feature}.related_to."
                    )

            # --- Phase E.4: Scientific accuracy tracking ---
            # Accumulate outcome counts and compute hit-rate fractions.
            new_outcomes_history = dict(inp.prediction_outcomes_history)
            if prediction_evaluation:
                outcome_label = prediction_evaluation.get("outcome")
                if outcome_label in ("confirmed", "partial", "refuted"):
                    new_outcomes_history[outcome_label] = (
                        new_outcomes_history.get(outcome_label, 0) + 1
                    )
            total_preds = sum(new_outcomes_history.values())
            scientific_accuracy: Optional[Dict[str, float]] = (
                {k: round(v / total_preds, 4) for k, v in new_outcomes_history.items()}
                if total_preds > 0 else None
            )
            if scientific_accuracy:
                print(f"  Scientific accuracy: {scientific_accuracy} "
                      f"(n={total_preds})")

            # --- Centrifugal health metrics (post-Phase-C, on the updated vocab) ---
            vocab_diversity_ratio = _cvdr(runtime_vocab)
            this_info_gain = (
                prediction_evaluation.get("information_gain", 0.0)
                if prediction_evaluation else 0.0
            )
            cumulative_information_gain = inp.cumulative_information_gain + this_info_gain
            print(f"  Vocab diversity ratio: {vocab_diversity_ratio:.3f} "
                  f"(cumulative info gain: {cumulative_information_gain:.4f})")

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
            output = InterpretationOutput.model_validate({
                "model_types":           effective_types,
                "model_descriptions":    model_descriptions,
                "total_experiments":     total_experiments,
                "per_model_best":        per_model_best,
                "per_model_worst":       per_model_worst,
                "best_denoising_score":  overall_best_score,
                "worst_denoising_score": overall_worst_score,
                "best_config":           overall_best_config,
                "model_knowledge_cache":  model_knowledge_cache,
                "key_findings":          llm_findings,
                "bottlenecks":           llm_bottlenecks,
                # Enriched fields
                "per_model_score_tables":      per_model_score_tables or None,
                "per_model_params":            per_model_params or None,
                "per_model_training_segments": per_model_training_segments or None,
                "take_home_message":     llm_take_home,
                # Phase C: vocabulary feedback
                "runtime_vocab":         [v.model_dump() if hasattr(v, "model_dump") else v for v in runtime_vocab],
                "prediction_evaluation": prediction_evaluation,
                "new_discoveries":       [d.model_dump() for d in new_discoveries],
                "vocab_changes":         vocab_changes,
                # Centrifugal health metrics
                "vocab_diversity_ratio":        vocab_diversity_ratio,
                "cumulative_information_gain":  cumulative_information_gain,
                # Phase E: scientific accuracy + vocab link promotion
                "scientific_accuracy":           scientific_accuracy,
                "prediction_outcomes_history":   new_outcomes_history,
                "vocab_link_confirmations":      link_confirmations,
                # V8 Domain 3 — evolution observability
                "evolution_stats":               evolution_stats,
            })

            # --- Persist ---
            if inp.storage.backend == "local" and inp.storage.local:
                workspace = inp.storage.local.workspace
                run_name  = inp.storage.local.run_name
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
                        "iteration":          inp.iteration,
                        "evolution_stats":    evolution_stats,
                        "best_score_so_far":  output.best_denoising_score,
                        "take_home_message":  output.take_home_message,
                    },
                )

            return output
        except Exception as e:
            print(
                f"  [DEGRADED] Interpretation LLM flow failed: "
                f"{type(e).__name__}: {e}"
            )
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
            output = InterpretationOutput.model_validate({
                "model_types":           effective_types,
                "model_descriptions":    model_descriptions,
                "total_experiments":     total_experiments,
                "per_model_best":        per_model_best,
                "per_model_worst":       per_model_worst,
                "best_denoising_score":  overall_best_score,
                "worst_denoising_score": overall_worst_score,
                "best_config":           overall_best_config,
                "model_knowledge_cache": dict(inp.model_knowledge_cache),
                "key_findings":          [],
                "bottlenecks":           [],
                "take_home_message": (
                    f"DEGRADED: interpreter LLM failed "
                    f"({type(e).__name__}). Vocab carried forward unchanged."
                ),
                "runtime_vocab": [
                    v.model_dump() if hasattr(v, "model_dump") else v
                    for v in inp.runtime_vocab
                ],
                "new_discoveries":              [],
                "vocab_changes":                [],
                "prediction_outcomes_history":  dict(inp.prediction_outcomes_history),
                "vocab_link_confirmations":     dict(inp.vocab_link_confirmations),
                "cumulative_information_gain":  inp.cumulative_information_gain,
                "is_degraded":                  True,
                "evolution_stats":              degraded_stats,
            })
            if inp.storage.backend == "local" and inp.storage.local:
                workspace = inp.storage.local.workspace
                run_name  = inp.storage.local.run_name
                os.makedirs(workspace, exist_ok=True)
                out_path = os.path.join(
                    workspace, f"interpretation_{run_name}.json"
                )
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(output.model_dump_json(indent=4))
                print(f"  [DEGRADED] Interpretation saved -> {out_path}")

                _append_evolution_log(
                    workspace_root=_resolve_evolution_log_root(workspace),
                    payload={
                        "iteration":          inp.iteration,
                        "evolution_stats":    degraded_stats,
                        "best_score_so_far":  output.best_denoising_score,
                        "take_home_message":  output.take_home_message,
                    },
                )
            return output


    def _dedup_promoted(
        self,
        promoted_names: List[str],
        vocab: List["VocabEntry"],
    ) -> tuple[List["VocabEntry"], List[str]]:
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
        from agent.schemas.proposal import VocabEntry as _VocabEntry

        if not promoted_names:
            return vocab, []

        vocab_by_name: Dict[str, Any] = {
            (e.name if hasattr(e, "name") else e["name"]): e for e in vocab
        }
        merge_changes: List[str] = []

        for name in promoted_names:
            if name not in vocab_by_name:
                continue  # already removed by a prior merge this loop

            entry = vocab_by_name[name]
            kind  = entry.kind if hasattr(entry, "kind") else entry.get("kind", "")

            # Only compare against existing canonicals of the same kind
            existing = [
                e for n, e in vocab_by_name.items()
                if n != name
                and (e.tier if hasattr(e, "tier") else e.get("tier")) == "canonical"
                and (e.kind if hasattr(e, "kind") else e.get("kind")) == kind
            ]
            if not existing:
                print(f"  Dedup: '{name}' — no existing canonicals of kind='{kind}', keeping.")
                continue

            prompt   = _build_dedup_prompt(entry, existing)
            response = self.bridge.generate(DEDUP_SYSTEM_PROMPT, prompt)

            is_dup = response.get("is_duplicate", False)
            dup_of = response.get("duplicate_of")
            rationale = response.get("rationale", "")

            if is_dup and dup_of and dup_of in vocab_by_name:
                existing_entry = vocab_by_name[dup_of]
                current_aliases = (
                    existing_entry.aliases if hasattr(existing_entry, "aliases")
                    else existing_entry.get("aliases", [])
                )
                vocab_by_name[dup_of] = existing_entry.model_copy(
                    update={"aliases": current_aliases + [name]}
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
    parser.add_argument("--workspace",   type=str, default="./siderius_workspace",
                        help="Root directory for reading summaries and writing output")
    parser.add_argument("--run_name",    type=str, default="v1",
                        help="Run name — reads summary_{run_name}.json, writes interpretation_{run_name}.json")
    parser.add_argument("--model_type",  type=str, required=True,
                        help="Model architecture (e.g. 'punet').")
    parser.add_argument("--provider",    type=str, default="gemini", choices=["gemini", "openai"])
    parser.add_argument("--model_id",    type=str, default="gemini-3.1-flash-lite-preview")
    args = parser.parse_args()

    # Load run output from workspace
    output_path = os.path.join(args.workspace, f"run_output_{args.run_name}.json")
    if not os.path.exists(output_path):
        raise FileNotFoundError(
            f"Run output not found: {output_path}\n"
            f"Run tune_ml_hyperparam_agent first, or check --workspace and --run_name."
        )
    with open(output_path, "r", encoding="utf-8") as f:
        run_data = json.load(f)

    # Build ModelRunSummary from run output
    from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
    tune_output = HyperparamTuningOutput.model_validate(run_data)
    summary = tuning_output_to_model_run_summary(tune_output)

    agent_input = InterpretationInput(
        summaries=[summary],
        storage={"backend": "local", "local": {"workspace": args.workspace, "run_name": args.run_name}},
    )
    print(f"Input validated: model={args.model_type} | rounds={summary.completed_rounds}")

    agent = ResultInterpretationAgent(provider=args.provider, model_id=args.model_id)
    output = agent.run(agent_input)

    print(f"\n{'='*60}")
    print(f"  Interpretation — {output.model_types}")
    print(f"{'='*60}")
    print(f"  Total experiments : {output.total_experiments}")
    print(f"  Overall best      : {output.best_denoising_score}")
    print(f"  Overall worst     : {output.worst_denoising_score}")
    for mt in output.model_types:
        print(f"  {mt}: best={output.per_model_best.get(mt)} worst={output.per_model_worst.get(mt)}")
    print(f"\n  Key findings:")
    for f in output.key_findings:
        print(f"    - {f}")
    print(f"\n  Bottlenecks:")
    for b in output.bottlenecks:
        print(f"    - {b}")
    print(f"\n  Take-home message:")
    print(f"    {output.take_home_message}")
    print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# Utility: convert HyperparamTuningOutput → ModelRunSummary
# ---------------------------------------------------------------------------

def tuning_output_to_model_run_summary(
    output: "HyperparamTuningOutput",
) -> ModelRunSummary:
    """
    Convert a HyperparamTuningOutput to a condensed ModelRunSummary.

    Extracts aggregates, per-round trajectory, file_vector, data volume,
    and efficiency metrics from the all_records field. The raw records
    are NOT carried forward — only the condensed summary.
    """
    records = output.all_records

    # Per-round extraction
    round_scores: List[Optional[float]] = []
    round_conclusions: List[str] = []
    round_trial_portions: List[Optional[float]] = []
    round_model_params: List[Optional[int]] = []

    for r in records:
        rec = r.model_dump() if hasattr(r, "model_dump") else r
        round_scores.append(rec.get("denoising_score"))
        round_trial_portions.append(rec.get("trial_portion"))
        round_model_params.append(rec.get("model_params"))
        memory = rec.get("memory") or {}
        if isinstance(memory, dict):
            round_conclusions.append(memory.get("conclusion") or "")
        else:
            conclusion = getattr(memory, "conclusion", None) or ""
            round_conclusions.append(conclusion)

    # Find best record (highest denoising_score)
    success = [
        (r.model_dump() if hasattr(r, "model_dump") else r)
        for r in records
        if (r.status if hasattr(r, "status") else r.get("status")) == "success"
        and (r.denoising_score if hasattr(r, "denoising_score") else r.get("denoising_score")) is not None
    ]
    best_rec = max(success, key=lambda r: r["denoising_score"]) if success else None

    # Find formal round (last record with is_trial=False)
    formal_rec = None
    for r in reversed(success):
        if not r.get("is_trial", True):
            formal_rec = r
            break

    # Compute worst score
    valid_scores = [s for s in round_scores if s is not None]
    worst_score = min(valid_scores) if valid_scores else None

    # --- Score tables (Phase 4 — enriched replacement for file_vector) ---
    # best_score_table prefers the pre-computed top-level field on the tuning
    # output (populated by the tuner per §7.1). The best_rec's own score_table
    # is a fallback in case the top-level field is None but the record carries
    # one. formal_score_table comes from the tuning output's top-level field
    # directly — it points at the last successful formal round's table.
    def _as_table(value) -> Optional[ScoreComparisonTable]:
        if value is None:
            return None
        if isinstance(value, ScoreComparisonTable):
            return value
        return ScoreComparisonTable.model_validate(value)

    best_score_table = _as_table(output.best_score_table)
    if best_score_table is None and best_rec is not None:
        best_score_table = _as_table(best_rec.get("score_table"))

    formal_score_table = _as_table(output.formal_score_table)
    if formal_score_table is None and formal_rec is not None:
        formal_score_table = _as_table(formal_rec.get("score_table"))

    return ModelRunSummary(
        model_type=output.model_type,
        run_name=output.run_name,
        status=output.status,
        completed_rounds=output.completed_rounds,
        best_denoising_score=output.best_denoising_score,
        worst_denoising_score=worst_score,
        best_config=output.best_config,
        round_scores=round_scores,
        round_conclusions=round_conclusions,
        # Per-file performance (raw primitive retained per §7.2 scope note)
        best_file_vector=best_rec.get("file_vector") if best_rec else None,
        formal_score=formal_rec.get("denoising_score") if formal_rec else None,
        formal_file_vector=formal_rec.get("file_vector") if formal_rec else None,
        # Per-file performance (enriched — Phase 4)
        best_score_table=best_score_table,
        formal_score_table=formal_score_table,
        # Efficiency
        best_model_params=best_rec.get("model_params") if best_rec else None,
        # Compute cost
        best_timing=best_rec.get("timing") if best_rec else None,
        # Data volume
        training_psd_segments=best_rec.get("training_psd_segments") if best_rec else None,
        eval_psd_segments=best_rec.get("eval_psd_segments") if best_rec else None,
        trial_portion=best_rec.get("trial_portion") if best_rec else None,
        # Per-round trends
        round_trial_portions=round_trial_portions,
        round_model_params=round_model_params,
    )


if __name__ == "__main__":
    main()
