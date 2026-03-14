# nodes/result_interpretation_agent.py
"""
result_interpretation_agent — Node 2 in the SIDERIUS graph.

Two-phase interpretation:
  Phase 1 — Per-model summarization: one LLM call per model type, producing
            a structured summary (findings, bottlenecks, config analysis).
  Phase 2 — Cross-model synthesis: one LLM call consuming all per-model
            summaries (not raw records) to produce the final interpretation.

This keeps each LLM call focused and within token limits.

Node contract:
  run(input: InterpretationInput) -> InterpretationOutput
  CLI: --workspace, --run_name, --model_type, --max_records_per_group,
       --provider, --model_id
"""

import os
import json
import argparse
from typing import Any, Dict, List, Optional

from agent.llm_bridge import LLMBridge
from agent.schemas.interpretation import (
    InterpretationInput, InterpretationOutput, SummaryGroup,
)
from agent.schemas.storage import StorageConfig, LocalStorageConfig
from ml_models.model_descriptions import get_model_description


# ---------------------------------------------------------------------------
# Phase 1 — Per-model summarization
# ---------------------------------------------------------------------------

PER_MODEL_SYSTEM_PROMPT = """\
You are a senior ML research analyst specialising in deep learning for signal denoising.

Your task: analyse the hyperparameter tuning experiment logs for ONE model architecture
and produce a structured summary.

You will receive:
- The model's architectural description (markdown + math)
- Best and worst denoising scores for this model
- Experiment records containing configs, results, and agent reflections

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
  "score_trend": "How scores evolved across experiments — improving, plateauing, or erratic"
}

Rules:
- key_findings: ranked by importance, evidence-based, reference actual values
- bottlenecks: root causes (e.g. 'architecture capacity ceiling'), not symptoms
- best_config_analysis: be specific about which hyperparameters mattered most
- score_trend: identify whether the model has saturated or still has room to improve
- Output only the JSON object — no preamble, no commentary, no markdown
"""


def _build_per_model_prompt(
    model_type: str,
    description: str,
    records: List[Dict],
    best_score: Optional[float],
    worst_score: Optional[float],
    best_config: Optional[Dict],
    max_records: int,
    human_advice: Optional[str] = None,
) -> str:
    """Build the user prompt for a single model's summarization."""
    truncated = records[-max_records:]

    lines = [
        f"## Model: {model_type}",
        f"Best denoising score : {best_score if best_score is not None else 'none'}",
        f"Worst denoising score: {worst_score if worst_score is not None else 'none'}",
        f"Total experiments: {len(records)} (showing last {len(truncated)})",
        "",
        "### Architecture Description",
        description,
        "",
        "### Best Config",
        json.dumps(best_config, indent=2) if best_config else "none",
        "",
        "### Experiment Records",
        json.dumps(truncated, indent=2),
    ]

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
    model_descriptions: Dict[str, str],
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
        # --- Effective model types (union of summaries and explicit model_types) ---
        effective_types = sorted(
            {g.model_type for g in inp.summaries} | set(inp.model_types or [])
        )

        # --- Load descriptions (raises FileNotFoundError if any missing) ---
        model_descriptions = {mt: get_model_description(mt) for mt in effective_types}

        # --- Deterministic pre-computation ---
        per_model_best:   Dict[str, Optional[float]] = {}
        per_model_worst:  Dict[str, Optional[float]] = {}
        per_model_best_config: Dict[str, Optional[Dict]] = {}
        overall_best_score:  Optional[float] = None
        overall_worst_score: Optional[float] = None
        overall_best_config: Optional[Dict[str, Any]] = None
        total_experiments = 0

        # Collect all records per model type
        per_model_records: Dict[str, List[Dict]] = {mt: [] for mt in effective_types}

        for group in inp.summaries:
            total_experiments += len(group.records)
            mt = group.model_type
            if mt in per_model_records:
                per_model_records[mt].extend(group.records)

            successful = [
                r for r in group.records
                if r.get("status") == "success" and r.get("denoising_score") is not None
            ]
            if successful:
                group_best  = max(successful, key=lambda r: r["denoising_score"])
                group_worst = min(successful, key=lambda r: r["denoising_score"])

                # Per-model best
                if per_model_best.get(mt) is None or group_best["denoising_score"] > per_model_best[mt]:
                    per_model_best[mt] = group_best["denoising_score"]
                    per_model_best_config[mt] = group_best.get("params")
                # Per-model worst
                if per_model_worst.get(mt) is None or group_worst["denoising_score"] < per_model_worst[mt]:
                    per_model_worst[mt] = group_worst["denoising_score"]
                # Overall best
                if overall_best_score is None or group_best["denoising_score"] > overall_best_score:
                    overall_best_score  = group_best["denoising_score"]
                    overall_best_config = group_best.get("params")
                # Overall worst
                if overall_worst_score is None or group_worst["denoising_score"] < overall_worst_score:
                    overall_worst_score = group_worst["denoising_score"]

        # Fill None for model types with no summaries
        for mt in effective_types:
            per_model_best.setdefault(mt, None)
            per_model_worst.setdefault(mt, None)
            per_model_best_config.setdefault(mt, None)

        print(f"Interpreting {len(inp.summaries)} summary group(s) across "
              f"{len(effective_types)} model(s): {effective_types} "
              f"(overall best: {overall_best_score})")

        # --- Phase 1: Per-model summarization ---
        per_model_summaries: Dict[str, Dict] = {}
        for mt in effective_types:
            records = per_model_records[mt]
            if not records:
                # No records for this model — use a minimal summary
                per_model_summaries[mt] = {
                    "key_findings": ["No experiment records available for this model."],
                    "bottlenecks": [],
                    "best_config_analysis": "N/A",
                    "score_trend": "N/A",
                }
                continue

            print(f"  Phase 1: Summarizing {mt} ({len(records)} records)...")
            per_model_prompt = _build_per_model_prompt(
                model_type=mt,
                description=model_descriptions[mt],
                records=records,
                best_score=per_model_best.get(mt),
                worst_score=per_model_worst.get(mt),
                best_config=per_model_best_config.get(mt),
                max_records=inp.max_records_per_group,
                human_advice=inp.human_advice,
            )
            per_model_response = self.bridge.generate(PER_MODEL_SYSTEM_PROMPT, per_model_prompt)
            per_model_summaries[mt] = per_model_response
            print(f"    {mt}: {len(per_model_response.get('key_findings', []))} findings, "
                  f"{len(per_model_response.get('bottlenecks', []))} bottlenecks")

        # --- Phase 2: Cross-model synthesis ---
        if len(effective_types) == 1:
            # Single model — skip synthesis, use per-model summary directly
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
                model_descriptions=model_descriptions,
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
                        help="Model architecture (e.g. 'punet'). Used as both model_types and summary lookup.")
    parser.add_argument("--max_records_per_group", type=int, default=50,
                        help="Maximum records passed to the LLM per summary group")
    parser.add_argument("--provider",    type=str, default="gemini", choices=["gemini", "openai"])
    parser.add_argument("--model_id",    type=str, default="gemini-3.1-flash-lite-preview")
    args = parser.parse_args()

    # Load summary from workspace
    summary_path = os.path.join(args.workspace, f"summary_{args.run_name}.json")
    if not os.path.exists(summary_path):
        raise FileNotFoundError(
            f"Summary file not found: {summary_path}\n"
            f"Run tune_ml_hyperparam_agent first, or check --workspace and --run_name."
        )
    with open(summary_path, "r", encoding="utf-8") as f:
        records = json.load(f)

    agent_input = InterpretationInput.model_validate({
        "summaries": [{"model_type": args.model_type, "run_name": args.run_name, "records": records}],
        "max_records_per_group": args.max_records_per_group,
        "storage": {
            "backend": "local",
            "local": {"workspace": args.workspace, "run_name": args.run_name},
        },
    })
    print(f"Input validated: model={args.model_type} | "
          f"records={len(records)} | max_records_per_group={args.max_records_per_group}")

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


if __name__ == "__main__":
    main()
