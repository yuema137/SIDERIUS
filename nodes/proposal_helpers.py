# nodes/proposal_helpers.py
"""
Pure helper functions for ml_model_proposal_agent.

These are deterministic Python functions with no LLM calls, no I/O,
and no side effects. They prepare context for the reasoning pipeline.
"""

import os
import re
from typing import Any, Dict, List, Optional

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
        best_score, and any available metadata (score_table, params, etc.).
        The ``score_table`` entry carries the serialized
        ``ScoreComparisonTable`` dict (``rendered_markdown`` + scalars + rows)
        straight through — downstream stages render from its fields directly.
    """
    model_types = interpretation.get("model_types", [])
    per_best = interpretation.get("per_model_best") or {}
    per_worst = interpretation.get("per_model_worst") or {}
    score_tables = interpretation.get("per_model_score_tables") or {}
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
            "score_table": score_tables.get(mt),
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


# ---------------------------------------------------------------------------
# Phase 5 C — stage user-prompt rendering helpers
#
# These lift the heavy, read-intensive content (score_table markdown + source
# code) out of the JSON-escaped candidate dicts into a top-level markdown
# block the LLM reads natively. Scalar metadata stays in the JSON region.
# See docs/aggregated_score_table_awareness.md §"Sub-commit C detailed plan".
# ---------------------------------------------------------------------------


def build_score_summary_line(score_table: Optional[Dict[str, Any]]) -> Optional[str]:
    """One-liner summary for a non-candidate model's score table.

    Reads ``aggregate.{model_scalar, raw_baseline_scalar, percent_of_ceiling_log,
    num_sampled_files}`` from a serialized ``ScoreComparisonTable`` dict and
    returns one of:

    * ``"log_scalar=X.XX, recovery=YY% on N files"`` — normal case.
    * ``"log_scalar=X.XX, below raw baseline on N files"`` — when
      ``model_scalar < raw_baseline_scalar``. Mirrors the below-baseline
      guard in ``execute_tools.scoring_helpers.render_comparison_table`` so
      we never emit a misleading sign-flipped percentage here.

    Returns ``None`` when ``score_table`` is ``None`` or lacks an
    ``aggregate`` sub-dict — caller decides whether to omit the field.
    """
    if not isinstance(score_table, dict):
        return None
    agg = score_table.get("aggregate")
    if not isinstance(agg, dict):
        return None

    model_scalar = agg.get("model_scalar")
    raw_baseline = agg.get("raw_baseline_scalar")
    recovery = agg.get("percent_of_ceiling_log")
    n_files = agg.get("num_sampled_files")
    if model_scalar is None or n_files is None:
        return None

    if raw_baseline is not None and model_scalar < raw_baseline:
        return (
            f"log_scalar={model_scalar:.2f}, "
            f"below raw baseline on {n_files} files"
        )

    if recovery is None:
        return f"log_scalar={model_scalar:.2f} on {n_files} files"

    return (
        f"log_scalar={model_scalar:.2f}, "
        f"recovery={recovery * 100:.1f}% on {n_files} files"
    )


def build_candidate_markdown_block(candidates: List[Dict[str, Any]]) -> str:
    """Top-level markdown block rendering each candidate's full detail.

    For each candidate dict, emits a section:

    ```
    ### Candidate: <model_type>

    <score_table.rendered_markdown>

    #### Source Code
    ```python
    <source_code>
    ```

    ---
    ```

    Falls back to ``_Score table unavailable._`` / ``_Source code
    unavailable._`` when the corresponding field is missing. Returns an
    empty string when ``candidates`` is empty — callers typically omit
    the whole block (heading + separator) on an empty return.
    """
    if not candidates:
        return ""

    sections: List[str] = ["## Candidate Models — detailed view", ""]
    for candidate in candidates:
        mt = candidate.get("model_type", "<unknown>")
        sections.append(f"### Candidate: {mt}")
        sections.append("")

        table = candidate.get("score_table")
        rendered = table.get("rendered_markdown") if isinstance(table, dict) else None
        if rendered:
            sections.append(rendered)
        else:
            sections.append("_Score table unavailable._")
        sections.append("")

        source = candidate.get("source_code")
        sections.append("#### Source Code")
        if source:
            sections.append("```python")
            sections.append(source)
            sections.append("```")
        else:
            sections.append("_Source code unavailable._")
        sections.append("")
        sections.append("---")
        sections.append("")

    return "\n".join(sections).rstrip() + "\n"


def strip_heavy_fields_for_json(
    candidates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Shallow copy per candidate with heavy fields removed for JSON dump.

    Removes ``score_table``, ``source_code``, and ``source_code_lines`` —
    the fields that live in the top-level markdown block after
    ``build_candidate_markdown_block``. Preserves every other field so
    stage prompts that enumerate candidate scalars (``best_score``,
    ``model_params``, ``description``, ``source``, ...) keep working.

    Input list is not mutated.
    """
    _HEAVY_FIELDS = ("score_table", "source_code", "source_code_lines")
    return [
        {k: v for k, v in candidate.items() if k not in _HEAVY_FIELDS}
        for candidate in candidates
    ]


def resolve_exploration_mode(
    interpretation: Dict[str, Any],
    pipeline: ReasoningPipelineConfig,
) -> str:
    """
    Decide whether to use explore or exploit mode.

    In 'auto' mode, checks two signals in priority order:

    1. Vocabulary stagnation (centrifugal): if the fraction of candidate
       feature/capability entries in the runtime vocab has dropped below
       policy.vocab_stagnation_threshold, force explore mode to prevent
       the system from only reusing canonical terms.

    2. Evidence depth: fewer than 5 agent-proposed models → explore to
       build up experimental evidence before switching to exploitation.

    Args:
        interpretation: Serialized InterpretationOutput.
        pipeline: The reasoning pipeline config (carries exploration_mode and policy).

    Returns:
        "explore" or "exploit".
    """
    if pipeline.exploration_mode != "auto":
        return pipeline.exploration_mode

    # Signal 1: vocabulary stagnation
    vocab_diversity_ratio = interpretation.get("vocab_diversity_ratio")
    if (
        vocab_diversity_ratio is not None
        and vocab_diversity_ratio < pipeline.policy.vocab_stagnation_threshold
    ):
        return "explore"

    # Signal 2: evidence depth
    model_types = interpretation.get("model_types", [])
    agent_proposed = [mt for mt in model_types if mt not in _BUILTIN_MODELS]

    if len(agent_proposed) < 5:
        return "explore"

    return "exploit"
