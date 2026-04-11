# nodes/proposal_helpers.py
"""
Pure helper functions for ml_model_proposal_agent.

These are deterministic Python functions with no LLM calls, no I/O,
and no side effects. They prepare context for the reasoning pipeline.
"""

import os
import re
from typing import Any, Dict, List

from agent.schemas.proposal import (
    ModelSelectionStrategy,
    ReasoningPipelineConfig,
)

# Root of the SIDERIUS project
_SIDERIUS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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

def load_model_source(model_type: str) -> str | None:
    """
    Load the source code for a model.

    Searches:
      1. Built-in models: extracts the relevant class(es) from
         ``ml_models/models_sandbox.py`` by finding the class name
         associated with the model_type in MODEL_REGISTRY-style patterns.
      2. Agent-generated plugins: reads from
         ``agent_generated/models/{model_type}/{model_type}.py``
         or ``agent_generated/models/{model_type}.py``.

    Returns the source code as a string, or None if not found.
    """
    # Try agent-generated plugin first (more specific)
    plugin_candidates = [
        os.path.join(_SIDERIUS_ROOT, "agent_generated", "models", model_type, f"{model_type}.py"),
        os.path.join(_SIDERIUS_ROOT, "agent_generated", "models", f"{model_type}.py"),
    ]
    for path in plugin_candidates:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()

    # Try built-in models — extract from models_sandbox.py
    sandbox_path = os.path.join(_SIDERIUS_ROOT, "ml_models", "models_sandbox.py")
    if not os.path.isfile(sandbox_path):
        return None

    # Map model_type to class names
    _MODEL_CLASS_MAP = {
        "punet": ["PositionalUNet", "DoubleConv", "Down", "Up", "OutConv", "PositionalEncoding"],
        "fcnet": ["AE"],
        "transformer": ["TransformerModel"],
        "wavenet": ["CausalConv1d", "WaveNetBlock", "SimpleWaveNet"],
        "rnn": ["Seq2SeqEncoder", "Seq2SeqDecoder", "RNNSeq2Seq"],
        "gated_fno": ["FullSpectrumGatedConv1d", "GatedFNO"],
    }

    class_names = _MODEL_CLASS_MAP.get(model_type)
    if not class_names:
        return None

    with open(sandbox_path, "r", encoding="utf-8") as f:
        full_source = f.read()

    # Extract each class definition (from 'class Name' to the next top-level class or EOF)
    extracted = []
    lines = full_source.split("\n")
    for target_class in class_names:
        in_class = False
        class_lines = []
        for line in lines:
            if re.match(rf"^class {target_class}\b", line):
                in_class = True
                class_lines = [line]
            elif in_class:
                # End of class: next top-level class or top-level non-indented code
                if re.match(r"^class \w", line) or (re.match(r"^[A-Z_]", line) and not line.startswith(" ")):
                    in_class = False
                else:
                    class_lines.append(line)
        if class_lines:
            extracted.append("\n".join(class_lines))

    return "\n\n".join(extracted) if extracted else None


def enrich_candidates_with_source(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Add source code to each candidate model summary.

    Loads the model's source code (from built-in or agent-generated) and
    adds it as a ``source_code`` field. Models without available source
    get ``source_code: None``.
    """
    for candidate in candidates:
        mt = candidate.get("model_type")
        if mt:
            source = load_model_source(mt)
            candidate["source_code"] = source
            if source:
                candidate["source_code_lines"] = len(source.split("\n"))
    return candidates


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
