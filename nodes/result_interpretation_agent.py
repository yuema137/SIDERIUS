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


# ---------------------------------------------------------------------------
# Phase 1 — Per-model summarization
# ---------------------------------------------------------------------------

PER_MODEL_SYSTEM_PROMPT = """\
You are a senior ML research analyst specialising in deep learning for signal denoising.

Your task: analyse the tuning run summary for ONE model architecture and produce a
structured summary of what was learned.

You will receive:
- The model's architectural description (markdown + math)
- Best and worst denoising scores
- Best configuration
- Score trajectory across rounds
- Per-round conclusions from the tuning agent's reflections

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
  "score_trend": "How scores evolved across rounds — improving, plateauing, or erratic"
}

Rules:
- key_findings: ranked by importance, evidence-based, reference actual values
- bottlenecks: root causes (e.g. 'architecture capacity ceiling'), not symptoms
- best_config_analysis: be specific about which hyperparameters mattered most
- score_trend: identify whether the model has saturated or still has room to improve
- Output only the JSON object — no preamble, no commentary, no markdown
"""


def _build_per_model_prompt(
    summary: ModelRunSummary,
    description: str,
    human_advice: Optional[str] = None,
) -> str:
    """Build the user prompt for a single model's summarization."""
    lines = [
        f"## Model: {summary.model_type}",
        f"Run: {summary.run_name} | Status: {summary.status} | Rounds: {summary.completed_rounds}",
        f"Best denoising score : {summary.best_denoising_score}",
        f"Worst denoising score: {summary.worst_denoising_score}",
        "",
        "### Architecture Description",
        description,
        "",
        "### Best Config",
        json.dumps(summary.best_config, indent=2) if summary.best_config else "none",
        "",
        "### Score Trajectory (chronological)",
    ]

    for i, (score, conclusion) in enumerate(
        zip(summary.round_scores, summary.round_conclusions), 1
    ):
        score_str = f"{score:.4f}" if score is not None else "skipped"
        lines.append(f"  Round {i}: score={score_str} — {conclusion}")

    # Handle case where scores and conclusions have different lengths
    if len(summary.round_scores) > len(summary.round_conclusions):
        for i in range(len(summary.round_conclusions), len(summary.round_scores)):
            score = summary.round_scores[i]
            score_str = f"{score:.4f}" if score is not None else "skipped"
            lines.append(f"  Round {i+1}: score={score_str}")

    if human_advice:
        lines += [
            "",
            "---",
            "## Human Guidance (high priority)",
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
- Per-model summaries (key findings, bottlenecks, config analysis, score trends)
- Per-model best and worst scores
- Overall best score and the config that produced it

Produce a JSON object with exactly these three fields:

{
  "key_findings": [
    "Cross-model finding #1 — most important, compares models, references scores",
    ...
  ],
  "bottlenecks": [
    "Cross-model root cause #1 — what is fundamentally limiting ALL current models",
    ...
  ],
  "take_home_message": "One sentence: the single most critical insight that motivates designing a new architecture."
}

Rules:
- key_findings: ranked by importance, MUST compare across models, reference actual scores
- bottlenecks: focus on fundamental limitations shared across architectures, not per-model issues
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
            "",
            "### Key Findings",
        ]
        for f in summary.get("key_findings", []):
            lines.append(f"  - {f}")
        lines += [
            "",
            "### Bottlenecks",
        ]
        for b in summary.get("bottlenecks", []):
            lines.append(f"  - {b}")
        lines += [
            "",
            f"### Best Config Analysis",
            summary.get("best_config_analysis", "N/A"),
            "",
            f"### Score Trend",
            summary.get("score_trend", "N/A"),
            "",
        ]

    if human_advice:
        lines += [
            "---",
            "## Human Guidance (high priority)",
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
                human_advice=inp.human_advice,
            )
            per_model_response = self.bridge.generate(PER_MODEL_SYSTEM_PROMPT, per_model_prompt)
            per_model_summaries[mt] = per_model_response
            print(f"    {mt}: {len(per_model_response.get('key_findings', []))} findings, "
                  f"{len(per_model_response.get('bottlenecks', []))} bottlenecks")

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
