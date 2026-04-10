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
from agent.schemas.hyperparam_tuning import serialize_expert_advice


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
   Note: keep the mathematical_definition abstract (computational principles, not shapes).
   Concrete dimensions belong only in baseline_config.
5. What are the likely failure modes of this architecture?
   What should the hyperparameter tuning agent watch out for?
6. Frequency analysis and trial strategy guidance:
   - Review the per-model file vectors to identify which frequency bands are weak.
     If low-frequency files (0-4) score near zero across all models, the new architecture
     should specifically address low-frequency signal recovery.
   - Recommend a trial strategy for the hyperparameter tuner:
     * What trial_portion to start with (based on model complexity — larger models need more data)
     * How many epochs for initial screening vs refinement
     * Whether to use "snapshot" (all files), "target" (weak files only), or "anchors" (extrema)
     * Whether the architecture is data-hungry (needs high trial_portion) or data-efficient

Think step by step. Be specific. Reference actual scores, model names, and file vector
patterns from the interpretation. Do not produce JSON — that is the next step."""


PROPOSAL_COMMIT_PROMPT = """\
You are a senior ML architect. You have just completed a detailed reasoning step
about a new architecture proposal. Now commit to a specific design.

Output a JSON object with exactly these fields:

{
  "model_name": "short_snake_case_key",
  "model_description": "One paragraph plain-English description of the architecture and why it is expected to improve on the current best.",
  "mathematical_definition": "Abstract architectural framework: describe the key computational stages, the mathematical operations at each stage (e.g. convolution, attention, SSM state update), and how data flows through them. Do NOT include concrete layer dimensions, kernel sizes, or channel counts — those belong in baseline_config. Focus on the structural novelty and the mathematical principles that differentiate this architecture from existing ones.",
  "motivation": "Why this specific architecture addresses the bottlenecks from the interpretation. Must reference the take-home message directly and name at least one specific bottleneck.",
  "expert_advice": {
    "focus_areas": ["What to prioritise during hyperparameter tuning for this architecture"],
    "constraints": ["Hard limits — must include at least one VRAM limit and one parameter count limit"],
    "known_failures": ["Configs or approaches to avoid, based on patterns in the interpretation"],
    "suggested_directions": [
      "Concrete first experiments to try, e.g. 'start with depth=2, lr=1e-4'",
      "Trial strategy guidance: recommended trial_portion (e.g. 0.1 for data-hungry models)",
      "Recommended epochs for screening (1-3) vs refinement (5-10)",
      "Whether to use snapshot/target/anchors strategy based on frequency weaknesses",
      "Which frequency bands (file indices) to focus on if using target strategy"
    ],
    "rationale": "Why this guidance is appropriate for this specific architecture. Include reasoning about data volume needs and frequency-specific training."
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

    # Frequency analysis (from enriched interpretation)
    freq_comp = interp.get("frequency_comparison")
    if freq_comp:
        lines += ["### Frequency Comparison (cross-model)", freq_comp, ""]

    eff_comp = interp.get("efficiency_comparison")
    if eff_comp:
        lines += ["### Efficiency Comparison (cross-model)", eff_comp, ""]

    # Per-model file vectors
    file_vectors = interp.get("per_model_file_vectors")
    if file_vectors:
        import math
        lines.append("### Per-model File Vectors (per-file denoising scores)")
        lines.append("File index → frequency (log scale): 0=lowest, 19=highest")
        for mt, fv in file_vectors.items():
            present = [
                (i, v) for i, v in enumerate(fv)
                if v is not None and not (isinstance(v, float) and math.isnan(v))
            ]
            weak = [i for i, v in present if v < 1.0]
            strong = [i for i, v in present if v >= 10.0]
            lines.append(f"  {mt}: weak files (score<1.0)={weak}, strong files (score>=10)={strong}")
        lines.append("")

    # Weak frequency files
    weak_files = interp.get("weak_frequency_files")
    if weak_files:
        lines.append("### Weak Frequency Bands (score < 1.0 = no denoising effect)")
        for mt, files in weak_files.items():
            lines.append(f"  {mt}: files {files}")
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

    if inp.previous_failures:
        lines.append("## Previous Failed Proposals (DO NOT repeat these mistakes)")
        for i, failure in enumerate(inp.previous_failures, 1):
            lines.append(f"  {i}. {failure}")
        lines.append("")

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
                 max_retries: int | None = None, bridge_factory=None):
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
        """Original 2-call pattern: reasoning (text) + commit (JSON)."""
        reasoning_prompt = _build_reasoning_prompt(inp)
        reasoning = self.bridge.generate_text(PROPOSAL_REASONING_PROMPT, reasoning_prompt)
        print(f"   Legacy reasoning complete ({len(reasoning)} chars).")

        commit_prompt = _build_commit_prompt(reasoning, inp.existing_model_types)
        raw = self.bridge.generate(PROPOSAL_COMMIT_PROMPT, commit_prompt)

        proposed_name = raw.get("model_name", "")
        if proposed_name in inp.existing_model_types:
            raise ValueError(
                f"LLM proposed model_name '{proposed_name}' which already exists in "
                f"existing_model_types: {inp.existing_model_types}. "
                f"Re-run or adjust the constraints."
            )

        output = ProposalOutput.model_validate({
            "model_name":              proposed_name,
            "model_description":       raw.get("model_description", ""),
            "mathematical_definition": raw.get("mathematical_definition", ""),
            "motivation":              raw.get("motivation", ""),
            "expert_advice":           raw.get("expert_advice", {}),
            "baseline_config":         raw.get("baseline_config", {}),
        })
        print(f"Proposed model (legacy): '{output.model_name}'")
        return output

    # ------------------------------------------------------------------
    # Pipeline mode (B.11 + B.12 — 3-stage reasoning pipeline)
    # ------------------------------------------------------------------

    def _run_pipeline(self, inp: ProposalInput) -> ProposalOutput:
        """Three-stage pipeline: comparison → reasoning → proposing."""
        from nodes.proposal_helpers import select_candidate_models, resolve_exploration_mode
        from agent.prompt_templates.proposal import load_stage_prompt, render_expert_context

        pipeline = inp.reasoning_pipeline
        policy = pipeline.policy

        # B.16a — resolve exploration mode
        mode = resolve_exploration_mode(inp.interpretation, pipeline)
        print(f"   Pipeline mode: {mode} | stages: {[s.name for s in pipeline.stages if s.enabled]}")

        # B.10 — pre-filter models
        candidates = select_candidate_models(inp.interpretation, pipeline.model_selection)
        print(f"   Candidates: {[c['model_type'] for c in candidates]} ({len(candidates)} models)")

        # Prepare shared context for all stages
        expert_context_block = render_expert_context(inp.expert_context)
        vocab_block = self._render_vocabulary(inp.vocab_seed)

        # --- Run enabled reasoning stages (accumulate context) ---
        accumulated = {
            "candidates": candidates,
            "interpretation_summary": {
                k: inp.interpretation.get(k)
                for k in ("model_types", "total_experiments", "best_denoising_score",
                          "worst_denoising_score", "key_findings", "bottlenecks",
                          "take_home_message", "per_model_best", "per_model_worst",
                          "per_model_file_vectors")
                if inp.interpretation.get(k) is not None
            },
            "existing_model_types": inp.existing_model_types,
            "previous_failures": inp.previous_failures,
        }

        template_vars = {
            "minimum_boldness": str(policy.minimum_boldness),
            "n_agent_proposed": str(len([
                c for c in candidates if c.get("source") != "seed"
            ])),
            "n_confirmed_links": "0",  # TODO: count from vocab_seed related_to
            "existing_model_types": ", ".join(inp.existing_model_types),
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
            )

            # Build user prompt: accumulated context + expert context + vocab
            user_prompt = json.dumps(accumulated, indent=2, default=str)
            if expert_context_block:
                user_prompt += f"\n\n{expert_context_block}"
            if vocab_block:
                user_prompt += f"\n\n{vocab_block}"

            print(f"   Stage '{stage.name}': calling LLM...")
            if stage.output_mode == "text":
                result = self.bridge.generate_text(system_prompt, user_prompt)
                accumulated[stage.name] = result
            else:
                result = self.bridge.generate(system_prompt, user_prompt)
                accumulated[stage.name] = result

            print(f"   Stage '{stage.name}': done.")

        # --- B.12: Proposing stage (always runs last) ---
        proposing_prompt = load_stage_prompt(
            "proposing_stage",
            exploration_mode=mode,
            template_vars=template_vars,
        )

        proposing_user = json.dumps(accumulated, indent=2, default=str)
        if expert_context_block:
            proposing_user += f"\n\n{expert_context_block}"

        print(f"   Stage 'proposing': calling LLM...")
        raw = self.bridge.generate(proposing_prompt, proposing_user)

        # --- Guard: LLM must not reuse an existing model name ---
        proposed_name = raw.get("model_name", "")
        if proposed_name in inp.existing_model_types:
            raise ValueError(
                f"LLM proposed model_name '{proposed_name}' which already exists in "
                f"existing_model_types: {inp.existing_model_types}. "
                f"Re-run or adjust the constraints."
            )

        # --- Extract inherited_components from reasoning stages ---
        inherited = []
        reasoning_output = accumulated.get("causal_reasoning", {})
        if isinstance(reasoning_output, dict):
            inherited = reasoning_output.get("inherited_components", [])

        # --- Build and validate output ---
        output = ProposalOutput.model_validate({
            "model_name":              proposed_name,
            "model_description":       raw.get("model_description", ""),
            "mathematical_definition": raw.get("mathematical_definition", ""),
            "motivation":              raw.get("motivation", ""),
            "expert_advice":           raw.get("expert_advice", {}),
            "baseline_config":         raw.get("baseline_config", {}),
            "inherited_components":    inherited,
            "memo_consistency_notes":  raw.get("memo_consistency_notes", []),
        })
        print(f"Proposed model (pipeline): '{output.model_name}'")
        return output

    @staticmethod
    def _render_vocabulary(vocab_seed: list) -> str:
        """Render the vocabulary seed into a prompt block."""
        if not vocab_seed:
            return ""

        lines = ["## Vocabulary (use these terms consistently)\n"]
        features = [v for v in vocab_seed if hasattr(v, "kind") and v.kind == "feature"]
        capabilities = [v for v in vocab_seed if hasattr(v, "kind") and v.kind == "capability"]

        # Handle both VocabEntry objects and dicts
        def _get(entry, key, default=""):
            if hasattr(entry, key):
                return getattr(entry, key)
            if isinstance(entry, dict):
                return entry.get(key, default)
            return default

        if features:
            lines.append("### Features (concrete building blocks)")
            for v in features:
                pattern = _get(v, "pattern")
                pat_str = f" [pattern: {pattern}]" if pattern else ""
                lines.append(f"- **{_get(v, 'name')}**: {_get(v, 'description')}{pat_str}")
            lines.append("")

        if capabilities:
            lines.append("### Capabilities (measurable architectural properties)")
            for v in capabilities:
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
