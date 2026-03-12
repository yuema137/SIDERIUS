# result_interpretation_agent.py
"""
result_interpretation_agent — Node 2 in the SIDERIUS graph.

Reads experiment records produced by tune_ml_hyperparam_agent and produces
a structured interpretation: key findings, bottlenecks, and a take-home message
that directly motivates proposing a new architecture.

Consumed by ml_model_proposal_agent via interpretation_to_proposal_v1.

Node contract:
  run(input: InterpretationInput) -> InterpretationOutput
  CLI: --workspace, --run_name, --model_type, --max_records, --provider, --model_id
"""

import os
import json
import argparse
from typing import Any, Dict, List, Optional

from agent.llm_bridge import LLMBridge
from agent.schemas.interpretation import InterpretationInput, InterpretationOutput
from agent.schemas.storage import StorageConfig, LocalStorageConfig


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

INTERPRETATION_SYSTEM_PROMPT = """\
You are a senior ML research analyst specialising in deep learning for signal denoising.

Your task: read a log of hyperparameter tuning experiments for a specific model architecture
and produce a structured, evidence-based interpretation.

You will receive:
- The model architecture being evaluated
- The best denoising score achieved and the config that produced it
- A list of experiment records, each containing the config tested, the result,
  and the agent's own reflection (hypothesis, conclusion, discovery, memory_update)

Produce a JSON object with exactly these three fields:

{
  "key_findings": [
    "Finding ranked #1 — most important, concrete, references actual values",
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
- key_findings: ranked by importance, evidence-based, reference actual scores/configs/loss types
- bottlenecks: identify root causes (e.g. 'architecture capacity ceiling') not symptoms (e.g. 'score is not improving')
- take_home_message: exactly one sentence, must directly motivate why a new architecture is needed
- Do not repeat information across fields
- Do not include vague statements like 'more experiments needed' or 'results are promising'
- Output only the JSON object — no preamble, no commentary, no markdown
"""


def _build_user_prompt(
    inp: InterpretationInput,
    best_score: Optional[float],
    best_config: Optional[Dict[str, Any]],
) -> str:
    records_to_show = inp.summary_records[-inp.max_records:]
    lines = [
        f"Model architecture: {inp.model_type}",
        f"Total experiments in history: {len(inp.summary_records)}",
        f"Records shown to you: {len(records_to_show)} (most recent)",
        f"Best denoising score achieved: {best_score if best_score is not None else 'none yet'}",
        f"Config that produced best score:\n{json.dumps(best_config, indent=2) if best_config else 'none'}",
        "",
        "Experiment records:",
        json.dumps(records_to_show, indent=2),
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

class ResultInterpretationAgent:

    def __init__(self, provider: str = "gemini", model_id: str = "gemini-3.1-flash-lite-preview"):
        self.bridge = LLMBridge(provider=provider, model_id=model_id)

    def run(self, inp: InterpretationInput) -> InterpretationOutput:
        # --- Deterministic pre-computation (never delegated to LLM) ---
        successful = [
            r for r in inp.summary_records
            if r.get("status") == "success" and r.get("denoising_score") is not None
        ]
        best_record = max(successful, key=lambda r: r["denoising_score"]) if successful else None
        best_score = best_record["denoising_score"] if best_record else None
        best_config = best_record.get("params") if best_record else None

        print(f"🔍 Interpreting {len(inp.summary_records)} records for {inp.model_type} "
              f"(best score: {best_score})")

        # --- LLM call ---
        user_prompt = _build_user_prompt(inp, best_score, best_config)
        llm_response = self.bridge.generate(INTERPRETATION_SYSTEM_PROMPT, user_prompt)

        # --- Build and validate output ---
        output = InterpretationOutput.model_validate({
            "model_type":            inp.model_type,
            "total_experiments":     len(inp.summary_records),
            "best_denoising_score":  best_score,
            "best_config":           best_config,
            "key_findings":          llm_response.get("key_findings", []),
            "bottlenecks":           llm_response.get("bottlenecks", []),
            "take_home_message":     llm_response.get("take_home_message", ""),
        })

        # --- Persist ---
        if inp.storage.backend == "local" and inp.storage.local:
            workspace = inp.storage.local.workspace
            run_name = inp.storage.local.run_name
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
                        help="Root directory containing summary_{run_name}.json")
    parser.add_argument("--run_name",    type=str, default="v1",
                        help="Run name — reads summary_{run_name}.json, writes interpretation_{run_name}.json")
    parser.add_argument("--model_type",  type=str, required=True,
                        help="Model architecture that was tuned (e.g. 'punet', 'fcnet')")
    parser.add_argument("--max_records", type=int, default=50,
                        help="Maximum number of records passed to the LLM (most recent)")
    parser.add_argument("--provider",    type=str, default="gemini", choices=["gemini", "openai"])
    parser.add_argument("--model_id",    type=str, default="gemini-3.1-flash-lite-preview")
    args = parser.parse_args()

    # Load summary records from workspace
    summary_path = os.path.join(args.workspace, f"summary_{args.run_name}.json")
    if not os.path.exists(summary_path):
        raise FileNotFoundError(
            f"Summary file not found: {summary_path}\n"
            f"Run tune_ml_hyperparam_agent first, or check --workspace and --run_name."
        )
    with open(summary_path, "r", encoding="utf-8") as f:
        summary_records = json.load(f)

    agent_input = InterpretationInput.model_validate({
        "summary_records": summary_records,
        "model_type":      args.model_type,
        "max_records":     args.max_records,
        "storage": {
            "backend": "local",
            "local": {"workspace": args.workspace, "run_name": args.run_name},
        },
    })
    print(f"✅ Input validated: model={agent_input.model_type} | "
          f"records={len(agent_input.summary_records)} | max_records={agent_input.max_records}")

    agent = ResultInterpretationAgent(provider=args.provider, model_id=args.model_id)
    output = agent.run(agent_input)

    print(f"\n{'='*60}")
    print(f"  Interpretation — {output.model_type}")
    print(f"{'='*60}")
    print(f"  Total experiments : {output.total_experiments}")
    print(f"  Best score        : {output.best_denoising_score}")
    print(f"\n  Key findings:")
    for finding in output.key_findings:
        print(f"    - {finding}")
    print(f"\n  Bottlenecks:")
    for bottleneck in output.bottlenecks:
        print(f"    - {bottleneck}")
    print(f"\n  Take-home message:")
    print(f"    {output.take_home_message}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
