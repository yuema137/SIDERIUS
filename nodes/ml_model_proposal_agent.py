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

from agent.llm_bridge import LLMBridge
from agent.schemas.proposal import ProposalInput, ProposalOutput
from agent.schemas.storage import StorageConfig, LocalStorageConfig


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
- GPU budget: target <10 GB VRAM and <100M parameters for initial exploration.

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
5. What are the likely failure modes of this architecture?
   What should the hyperparameter tuning agent watch out for?

Think step by step. Be specific. Reference actual scores and model names from the
interpretation. Do not produce JSON — that is the next step."""


PROPOSAL_COMMIT_PROMPT = """\
You are a senior ML architect. You have just completed a detailed reasoning step
about a new architecture proposal. Now commit to a specific design.

Output a JSON object with exactly these fields:

{
  "model_name": "short_snake_case_key",
  "model_description": "One paragraph plain-English description of the architecture and why it is expected to improve on the current best.",
  "mathematical_definition": "Precise, layer-by-layer specification of the architecture. Include: input embedding, all layer types with dimensions, activation functions, skip/residual connections, and the full forward pass data flow. Must be concrete enough for an LLM implementor to write complete PyTorch code directly from this description — no ambiguity allowed.",
  "motivation": "Why this specific architecture addresses the bottlenecks from the interpretation. Must reference the take-home message directly and name at least one specific bottleneck.",
  "expert_advice": {
    "focus_areas": ["What to prioritise during hyperparameter tuning for this architecture"],
    "constraints": ["Hard limits — must include at least one VRAM limit and one parameter count limit"],
    "known_failures": ["Configs or approaches to avoid, based on patterns in the interpretation"],
    "suggested_directions": ["Concrete first experiments to try, e.g. 'start with depth=2, lr=1e-4'"],
    "rationale": "Why this guidance is appropriate for this specific architecture."
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
  }
}

Hard constraints — violating any of these makes the proposal invalid:
- model_name must NOT be any of the existing model types listed in the context
- model_name must be snake_case: lowercase letters, digits, and underscores only
- The forward contract is fixed: input [B, T] int64 → output [B, 256, T] float32
- baseline_config must be conservative: fits comfortably in <10 GB VRAM
- expert_advice.constraints must include at least one VRAM limit and one parameter count limit

Output only the JSON object — no preamble, no markdown fences, no commentary."""


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _build_reasoning_prompt(inp: ProposalInput) -> str:
    """Build the user prompt for the reasoning call."""
    interp = inp.interpretation
    lines = []

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

    descriptions = interp.get("model_descriptions", {})
    if descriptions:
        lines.append("## Existing Architecture Descriptions")
        for mt, desc in descriptions.items():
            lines += [f"### {mt}", desc, ""]

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

    def __init__(self, provider: str = "gemini", model_id: str = "gemini-3.1-flash-lite-preview"):
        self.bridge = LLMBridge(provider=provider, model_id=model_id)

    def run(self, inp: ProposalInput) -> ProposalOutput:
        print(f"💡 Proposing new architecture based on interpretation of "
              f"{inp.interpretation.get('model_types', [])} ...")

        # --- Call 1: free reasoning (plain text, no JSON constraints) ---
        reasoning_prompt = _build_reasoning_prompt(inp)
        reasoning = self.bridge.generate_text(PROPOSAL_REASONING_PROMPT, reasoning_prompt)
        print(f"   Reasoning complete ({len(reasoning)} chars).")

        # --- Call 2: structured commit (strict JSON) ---
        commit_prompt = _build_commit_prompt(reasoning, inp.existing_model_types)
        raw = self.bridge.generate(PROPOSAL_COMMIT_PROMPT, commit_prompt)

        # --- Guard: LLM must not reuse an existing model name ---
        proposed_name = raw.get("model_name", "")
        if proposed_name in inp.existing_model_types:
            raise ValueError(
                f"LLM proposed model_name '{proposed_name}' which already exists in "
                f"existing_model_types: {inp.existing_model_types}. "
                f"Re-run or adjust the constraints."
            )

        # --- Build and validate output ---
        output = ProposalOutput.model_validate({
            "model_name":              proposed_name,
            "model_description":       raw.get("model_description", ""),
            "mathematical_definition": raw.get("mathematical_definition", ""),
            "motivation":              raw.get("motivation", ""),
            "expert_advice":           raw.get("expert_advice", {}),
            "baseline_config":         raw.get("baseline_config", {}),
        })
        print(f"✅ Proposed model: '{output.model_name}'")

        # --- Persist ---
        if inp.storage.backend == "local" and inp.storage.local:
            workspace = inp.storage.local.workspace
            run_name  = inp.storage.local.run_name
            os.makedirs(workspace, exist_ok=True)
            out_path = os.path.join(workspace, f"proposal_{run_name}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(output.model_dump_json(indent=4))
            print(f"✅ Proposal saved → {out_path}")

        return output


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
