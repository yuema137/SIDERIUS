# nodes/proposal_helpers.py
"""
Pure helper functions for ml_model_proposal_agent.

These are deterministic Python functions with no LLM calls, no I/O,
and no side effects. They prepare context for the reasoning pipeline.
"""

from typing import Any, Dict, List

from agent.schemas.proposal import (
    ModelSelectionStrategy,
    ReasoningPipelineConfig,
)


# ---------------------------------------------------------------------------
# B.10 — Model selection pre-filter
# ---------------------------------------------------------------------------

def select_candidate_models(
    interpretation: Dict[str, Any],
    strategy: ModelSelectionStrategy,
) -> List[Dict[str, Any]]:
    """
    Pre-filter past models before the comparison stage.

    Reduces the full set of models from the interpretation to a candidate
    set based on the strategy. Controls token cost (fewer models = cheaper
    comparison call) while expert_context controls focus (what to emphasize).

    Args:
        interpretation: Serialized InterpretationOutput dict.
        strategy: ModelSelectionStrategy from the pipeline config.

    Returns:
        List of per-model summary dicts, each containing model_type,
        best_score, and any available metadata (file_vector, params, etc.).
    """
    model_types = interpretation.get("model_types", [])
    per_best = interpretation.get("per_model_best") or {}
    per_worst = interpretation.get("per_model_worst") or {}
    file_vectors = interpretation.get("per_model_file_vectors") or {}
    model_params = interpretation.get("per_model_params") or {}
    descriptions = interpretation.get("model_descriptions") or {}
    training_segs = interpretation.get("per_model_training_segments") or {}

    # Build a summary for each model
    all_models = []
    for mt in model_types:
        summary = {
            "model_type": mt,
            "best_score": per_best.get(mt),
            "worst_score": per_worst.get(mt),
            "file_vector": file_vectors.get(mt),
            "model_params": model_params.get(mt),
            "description": descriptions.get(mt),
            "training_segments": training_segs.get(mt),
            "source": "seed" if mt in _BUILTIN_MODELS else _guess_source(mt, interpretation),
        }
        all_models.append(summary)

    # Apply strategy
    method = strategy.method
    params = strategy.params

    if method == "all":
        return all_models

    if method == "top_n":
        n = params.get("n", 10)
        # Sort by best_score descending, take top N
        scored = [m for m in all_models if m["best_score"] is not None]
        scored.sort(key=lambda m: m["best_score"], reverse=True)
        return scored[:n]

    if method == "human_specified":
        specified = set(params.get("models", []))
        return [m for m in all_models if m["model_type"] in specified]

    if method == "feature_match":
        # Filter to models whose description mentions the target feature
        feature = params.get("feature", "")
        return [
            m for m in all_models
            if m.get("description") and feature in m["description"]
        ]

    # Unknown strategy — return all with a warning
    print(f"[proposal_helpers] Unknown model selection method: {method!r}, returning all models.")
    return all_models


# Known built-in model types — used to set source="seed"
_BUILTIN_MODELS = {"punet", "wavenet", "fcnet", "transformer", "rnn", "gated_fno"}


def _guess_source(model_type: str, interpretation: Dict[str, Any]) -> str:
    """Guess whether a model was agent-proposed based on available data."""
    # Simple heuristic: if it's not a built-in, it's agent-proposed
    return "proposed"


# ---------------------------------------------------------------------------
# B.16a — Exploration mode resolver
# ---------------------------------------------------------------------------

def resolve_exploration_mode(
    interpretation: Dict[str, Any],
    pipeline: ReasoningPipelineConfig,
) -> str:
    """
    Decide whether to use explore or exploit mode.

    In 'auto' mode, checks evidence depth:
    - Few agent-proposed models (<5) → explore
    - Otherwise → exploit

    Args:
        interpretation: Serialized InterpretationOutput.
        pipeline: The reasoning pipeline config (carries exploration_mode).

    Returns:
        "explore" or "exploit".
    """
    if pipeline.exploration_mode != "auto":
        return pipeline.exploration_mode

    model_types = interpretation.get("model_types", [])
    agent_proposed = [mt for mt in model_types if mt not in _BUILTIN_MODELS]

    if len(agent_proposed) < 5:
        return "explore"

    return "exploit"
