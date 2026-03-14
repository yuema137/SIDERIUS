# nodes/result_interpretation_agent.py
"""
result_interpretation_agent — Node 2 in the SIDERIUS graph.

Reads experiment records from one or more tuning runs, loads the architectural
description for every model type involved, and produces a structured interpretation:
key findings, per-model score ranges, bottlenecks, and a take-home message that
directly motivates proposing a new architecture.

Consumed by ml_model_proposal_agent via interpretation_to_proposal_v1.

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
# Prompts
# ---------------------------------------------------------------------------

INTERPRETATION_SYSTEM_PROMPT = """\
You are a senior ML research analyst specialising in deep learning for signal denoising.

Your task: read the architectural descriptions and hyperparameter tuning experiment logs
for one or more model architectures, then produce a structured, evidence-based interpretation.

You will receive:
- The architectural description of each model (markdown + math)
- Per-model best and worst denoising scores
- Experiment records for each model, containing configs, results, and agent reflections

Produce a JSON object with exactly these three fields:

{
  "key_findings": [
    "Finding ranked #1 — most important, concrete, references actual values and model names",
    "Finding ranked #2 — ...",
    ...
  ],
  "bottlenecks": [
    "Root cause #1 preventing further improvement",
    ...
  ],
  "take_home_message": "One sentence: the single most critical insight that motivates designing a new architecture."
}

Rules:
- key_findings: ranked by importance, evidence-based, reference actual scores/configs/models
- bottlenecks: identify root causes (e.g. 'architecture capacity ceiling') not symptoms
- take_home_message: exactly one sentence, must directly motivate why a new architecture is needed
- If multiple models are provided, compare them and surface cross-model insights
- Do not repeat information across fields
- Do not include vague statements like 'more experiments needed' or 'results are promising'
- Output only the JSON object — no preamble, no commentary, no markdown
"""


def _build_user_prompt(
    inp: InterpretationInput,
    model_descriptions: Dict[str, str],
    per_model_best: Dict[str, Optional[float]],
    per_model_worst: Dict[str, Optional[float]],
    overall_best_score: Optional[float],
    overall_worst_score: Optional[float],
    overall_best_config: Optional[Dict[str, Any]],
) -> str:
    lines = []

    # --- Score summary ---
    lines += [
        "## Performance Summary",
        f"Overall best denoising score : {overall_best_score  if overall_best_score  is not None else 'none'}",
        f"Overall worst denoising score: {overall_worst_score if overall_worst_score is not None else 'none'}",
        f"Config that produced overall best:\n{json.dumps(overall_best_config, indent=2) if overall_best_config else 'none'}",
        "",
    ]

    # --- Per-model sections ---
    for model_type, description in model_descriptions.items():
        lines += [
            f"---",
            f"## Model: {model_type}",
            f"Best score : {per_model_best.get(model_type)}",
            f"Worst score: {per_model_worst.get(model_type)}",
            "",
            "### Architecture Description",
            description,
            "",
        ]

        # Append experiment records for this model
        model_records = []
        for group in inp.summaries:
            if group.model_type == model_type:
                truncated = group.records[-inp.max_records_per_group:]
                model_records.append({
                    "run_name": group.run_name,
                    "total_records": len(group.records),
                    "records_shown": len(truncated),
                    "records": truncated,
                })

        if model_records:
            lines += [
                "### Experiment Records",
                json.dumps(model_records, indent=2),
            ]
        else:
            lines.append("### Experiment Records\nNo experiment records provided for this model.")

        lines.append("")

    # --- Human advice (injected by workflow) ---
    if inp.human_advice:
        lines += [
            "---",
            "## Human Guidance (high priority)",
            inp.human_advice,
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
        overall_best_score:  Optional[float] = None
        overall_worst_score: Optional[float] = None
        overall_best_config: Optional[Dict[str, Any]] = None
        total_experiments = 0

        for group in inp.summaries:
            total_experiments += len(group.records)
            successful = [
                r for r in group.records
                if r.get("status") == "success" and r.get("denoising_score") is not None
            ]
            if successful:
                group_best  = max(successful, key=lambda r: r["denoising_score"])
                group_worst = min(successful, key=lambda r: r["denoising_score"])
                mt = group.model_type

                # Per-model best
                if per_model_best.get(mt) is None or group_best["denoising_score"] > per_model_best[mt]:
                    per_model_best[mt] = group_best["denoising_score"]
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

        print(f"🔍 Interpreting {len(inp.summaries)} summary group(s) across "
              f"{len(effective_types)} model(s): {effective_types} "
              f"(overall best: {overall_best_score})")

        # --- LLM call ---
        user_prompt = _build_user_prompt(
            inp, model_descriptions,
            per_model_best, per_model_worst,
            overall_best_score, overall_worst_score, overall_best_config,
        )
        llm_response = self.bridge.generate(INTERPRETATION_SYSTEM_PROMPT, user_prompt)

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
            "key_findings":          llm_response.get("key_findings", []),
            "bottlenecks":           llm_response.get("bottlenecks", []),
            "take_home_message":     llm_response.get("take_home_message", ""),
        })

        # --- Persist ---
        if inp.storage.backend == "local" and inp.storage.local:
            workspace = inp.storage.local.workspace
            run_name  = inp.storage.local.run_name
            os.makedirs(workspace, exist_ok=True)
            out_path = os.path.join(workspace, f"interpretation_{run_name}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(output.model_dump_json(indent=4))
            print(f"✅ Interpretation saved → {out_path}")

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
    print(f"✅ Input validated: model={args.model_type} | "
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
