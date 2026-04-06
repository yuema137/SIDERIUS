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
from agent.schemas.storage import StorageConfig, LocalStorageConfig
from ml_models.model_descriptions import get_model_description
from agent.schemas.hyperparam_tuning import serialize_expert_advice


# ---------------------------------------------------------------------------
# Phase 1 — Per-model summarization
# ---------------------------------------------------------------------------

PER_MODEL_SYSTEM_PROMPT = """\
You are a senior ML research analyst specialising in deep learning for signal denoising.

Your task: analyse the tuning run summary for ONE model architecture and produce a
structured analysis covering performance, frequency response, data sensitivity,
training dynamics, efficiency, and strategy assessment.

You will receive:
- The model's architectural description (markdown + math)
- Best and worst denoising scores (trial best and formal score if available)
- Best configuration
- Score trajectory across rounds (with trial portions and model sizes)
- Per-round conclusions from the tuning agent's reflections
- File vector: per-file denoising scores (20 files, frequency increases with index on log scale)
- Data volume: how many PSD segments were used for training vs baseline

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
  "frequency_analysis": "Which frequency bands (file indices) the model handles well vs poorly. Identify blind spots (near-zero scores) and strong ranges.",
  "data_sensitivity": "How sensitive the model is to data volume. Did scores improve when trial_portion increased? How large is the trial-vs-formal gap?",
  "efficiency_assessment": "Model parameter count vs performance. Is there a simpler config with similar score? Cost-performance tradeoff.",
  "strategy_assessment": "Did the agent explore effectively? Did it increase data when needed? Did it follow screening→refinement→solidification phases?"
}

Rules:
- key_findings: ranked by importance, evidence-based, reference actual values
- bottlenecks: root causes (e.g. 'architecture capacity ceiling', 'low-frequency blindness'), not symptoms
- best_config_analysis: be specific about which hyperparameters mattered most
- score_trend: identify whether the model has saturated or still has room to improve
- frequency_analysis: reference specific file indices and score values from the file_vector
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

    # File vector (per-file performance)
    if summary.best_file_vector is not None:
        import math
        lines += ["", "### File Vector (per-file denoising scores, best experiment)"]
        lines.append("File index → frequency (log scale): 0=lowest, 19=highest")
        for i, v in enumerate(summary.best_file_vector):
            if math.isnan(v):
                lines.append(f"  File {i:2d}: NaN (not evaluated)")
            else:
                lines.append(f"  File {i:2d}: {v:.4f}")

    if summary.formal_file_vector is not None:
        import math
        lines += ["", "### File Vector (formal round — definitive)"]
        for i, v in enumerate(summary.formal_file_vector):
            if math.isnan(v):
                lines.append(f"  File {i:2d}: NaN")
            else:
                lines.append(f"  File {i:2d}: {v:.4f}")

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
  frequency analysis, data sensitivity, efficiency, strategy assessment)
- Per-model best and worst scores
- Per-model file vectors (per-file performance across 20 frequency bands)
- Per-model parameter counts and training data volumes
- Overall best score and the config that produced it

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
  "frequency_comparison": "Which frequency ranges are well-handled by all models vs which are universally weak. Identify if there are frequency bands where no model succeeds.",
  "efficiency_comparison": "Compare model sizes (parameter counts) against scores. Identify the best score-per-parameter architecture.",
  "take_home_message": "One sentence: the single most critical insight that motivates designing a new architecture."
}

Rules:
- key_findings: ranked by importance, MUST compare across models, reference actual scores
- bottlenecks: focus on fundamental limitations shared across architectures, not per-model issues
- frequency_comparison: reference specific file indices and per-model file_vector values
- efficiency_comparison: reference actual parameter counts and scores
- take_home_message: exactly one sentence, must directly motivate why a new architecture is needed
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
    per_model_file_vectors: Optional[Dict[str, List[float]]] = None,
    per_model_params: Optional[Dict[str, int]] = None,
    per_model_training_segments: Optional[Dict[str, int]] = None,
    expert_advice_str: str = "",
    human_advice: Optional[str] = None,
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
        for field in ["frequency_analysis", "data_sensitivity", "efficiency_assessment", "strategy_assessment"]:
            val = summary.get(field)
            if val:
                lines += ["", f"### {field.replace('_', ' ').title()}", val]

        # File vector summary
        if per_model_file_vectors and model_type in per_model_file_vectors:
            import math
            fv = per_model_file_vectors[model_type]
            non_nan = [(i, v) for i, v in enumerate(fv) if not math.isnan(v)]
            if non_nan:
                weak = [(i, v) for i, v in non_nan if v < 1.0]
                strong = [(i, v) for i, v in non_nan if v >= 10.0]
                lines += ["", f"### File Vector Summary (best experiment)"]
                lines.append(f"  Files evaluated: {len(non_nan)}/20")
                if weak:
                    lines.append(f"  Weak files (score < 1.0): {[i for i,_ in weak]}")
                if strong:
                    lines.append(f"  Strong files (score >= 10): {[i for i,_ in strong]}")

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

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

class ResultInterpretationAgent:

    def __init__(self, provider: str = "gemini", model_id: str = "gemini-3.1-flash-lite-preview"):
        self.bridge = LLMBridge(provider=provider, model_id=model_id)

    def run(self, inp: InterpretationInput) -> InterpretationOutput:
        # --- Effective model types ---
        effective_types = sorted(
            {s.model_type for s in inp.summaries} | set(inp.model_types or [])
        )

        # --- Load descriptions ---
        # For agent-generated models, the description may be passed directly
        # in ModelRunSummary.model_description (avoiding filesystem dependency).
        # For built-in models, load from description.md on disk.
        model_descriptions: Dict[str, str] = {}
        for mt in effective_types:
            # Check if any summary carries the description inline
            inline_desc = None
            for s in inp.summaries:
                if s.model_type == mt and s.model_description:
                    inline_desc = s.model_description
                    break
            if inline_desc:
                model_descriptions[mt] = inline_desc
            else:
                model_descriptions[mt] = get_model_description(mt)

        # --- Deterministic pre-computation from summaries ---
        per_model_best:   Dict[str, Optional[float]] = {}
        per_model_worst:  Dict[str, Optional[float]] = {}
        per_model_best_config: Dict[str, Optional[Dict]] = {}
        overall_best_score:  Optional[float] = None
        overall_worst_score: Optional[float] = None
        overall_best_config: Optional[Dict[str, Any]] = None
        total_experiments = 0

        # Map model_type → ModelRunSummary
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

        # Fill None for model types with no summaries
        for mt in effective_types:
            per_model_best.setdefault(mt, None)
            per_model_worst.setdefault(mt, None)
            per_model_best_config.setdefault(mt, None)

        # Serialize expert advice (soft edge input)
        expert_advice_str = serialize_expert_advice(inp.expert_advice) if inp.expert_advice else ""

        print(f"Interpreting {len(inp.summaries)} model summary(ies) across "
              f"{len(effective_types)} model(s): {effective_types} "
              f"(overall best: {overall_best_score})")

        # --- Phase 1: Per-model summarization ---
        per_model_summaries: Dict[str, Dict] = {}
        for mt in effective_types:
            if mt not in per_model_summary_input:
                per_model_summaries[mt] = {
                    "key_findings": ["No tuning run available for this model."],
                    "bottlenecks": [],
                    "best_config_analysis": "N/A",
                    "score_trend": "N/A",
                }
                continue

            summary = per_model_summary_input[mt]
            print(f"  Phase 1: Summarizing {mt} ({summary.completed_rounds} rounds)...")
            per_model_prompt = _build_per_model_prompt(
                summary=summary,
                description=model_descriptions[mt],
                expert_advice_str=expert_advice_str,
                human_advice=inp.human_advice,
            )
            per_model_response = self.bridge.generate(PER_MODEL_SYSTEM_PROMPT, per_model_prompt)
            per_model_summaries[mt] = per_model_response
            print(f"    {mt}: {len(per_model_response.get('key_findings', []))} findings, "
                  f"{len(per_model_response.get('bottlenecks', []))} bottlenecks")

        # --- Pre-compute enriched fields from summaries ---
        per_model_file_vectors: Dict[str, List[float]] = {}
        weak_frequency_files: Dict[str, List[int]] = {}
        per_model_params: Dict[str, int] = {}
        per_model_training_segments: Dict[str, int] = {}

        import math
        for s in inp.summaries:
            mt = s.model_type
            if s.best_file_vector is not None:
                per_model_file_vectors[mt] = s.best_file_vector
                # Weak files: non-NaN entries below 1.0 (raw data baseline)
                weak = [i for i, v in enumerate(s.best_file_vector)
                        if not math.isnan(v) and v < 1.0]
                if weak:
                    weak_frequency_files[mt] = weak
            if s.best_model_params is not None:
                per_model_params[mt] = s.best_model_params
            if s.training_psd_segments is not None:
                per_model_training_segments[mt] = s.training_psd_segments

        # --- Phase 2: Cross-model synthesis ---
        if len(effective_types) == 1:
            single_mt = effective_types[0]
            summary = per_model_summaries[single_mt]
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
                per_model_summaries=per_model_summaries,
                per_model_best=per_model_best,
                per_model_worst=per_model_worst,
                overall_best_score=overall_best_score,
                overall_worst_score=overall_worst_score,
                overall_best_config=overall_best_config,
                per_model_file_vectors=per_model_file_vectors or None,
                per_model_params=per_model_params or None,
                per_model_training_segments=per_model_training_segments or None,
                expert_advice_str=expert_advice_str,
                human_advice=inp.human_advice,
            )
            synthesis_response = self.bridge.generate(SYNTHESIS_SYSTEM_PROMPT, synthesis_prompt)
            llm_findings = synthesis_response.get("key_findings", [])
            llm_bottlenecks = synthesis_response.get("bottlenecks", [])
            llm_take_home = synthesis_response.get("take_home_message", "")

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
            "per_model_summaries":   per_model_summaries,
            "key_findings":          llm_findings,
            "bottlenecks":           llm_bottlenecks,
            # Enriched fields
            "per_model_file_vectors":      per_model_file_vectors or None,
            "weak_frequency_files":        weak_frequency_files or None,
            "per_model_params":            per_model_params or None,
            "per_model_training_segments": per_model_training_segments or None,
            "take_home_message":     llm_take_home,
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

        return output


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
        # Per-file performance
        best_file_vector=best_rec.get("file_vector") if best_rec else None,
        formal_score=formal_rec.get("denoising_score") if formal_rec else None,
        formal_file_vector=formal_rec.get("file_vector") if formal_rec else None,
        # Efficiency
        best_model_params=best_rec.get("model_params") if best_rec else None,
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
