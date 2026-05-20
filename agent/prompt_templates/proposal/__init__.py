# agent/prompt_templates/proposal/__init__.py
"""
Prompt templates for the proposal agent's three-stage reasoning pipeline.

Templates are stored as .md files in this directory:
  - comparison_stage.md          (Stage 1 system prompt)
  - causal_reasoning_stage.md    (Stage 2 system prompt)
  - proposing_stage.md           (Stage 3 system prompt)
  - *_explore.md / *_exploit.md  (mode-specific additions)

The pipeline runner loads and assembles prompts at runtime via
load_stage_prompt() and render_expert_context().
"""

import os
from typing import List, Optional

_PROMPT_DIR = os.path.dirname(os.path.abspath(__file__))


def load_prompt(filename: str) -> str:
    """Load a prompt template from this directory."""
    path = os.path.join(_PROMPT_DIR, filename)
    with open(path, encoding="utf-8") as f:
        return f.read()


def load_stage_prompt(
    stage_name: str,
    exploration_mode: str = "explore",
    template_vars: dict | None = None,
    mindset: str | None = None,
) -> str:
    """
    Load and assemble a stage's full system prompt.

    Loads the base template (e.g. ``comparison_stage.md``), injects the
    exploration/exploitation mode block, and substitutes template variables.

    The mindset block is injected at the ``{# EXPLORATION_MODE_BLOCK #}``
    placeholder. Priority:
      1. ``mindset`` argument (from advice file) — overrides the default
      2. ``{stage_name}_{exploration_mode}.md`` file — default fallback

    Args:
        stage_name: One of ``"comparison_stage"``, ``"causal_reasoning_stage"``,
                    ``"proposing_stage"``.
        exploration_mode: ``"explore"`` or ``"exploit"``.
        template_vars: Dict of ``{placeholder: value}`` for substitution.
                       E.g. ``{"minimum_boldness": "0.05", "n_agent_proposed": "3"}``.
        mindset: Optional mindset text from the advice file. When provided,
                 overrides the default ``_explore.md`` / ``_exploit.md`` block.
                 When absent, the mode file is used (backward compatible).

    Returns:
        The assembled prompt string ready for the LLM.
    """
    base = load_prompt(f"{stage_name}.md")

    # Resolve mindset block: advice-provided mindset takes priority over mode file
    if mindset is not None:
        mode_block = mindset
    else:
        mode_file = f"{stage_name}_{exploration_mode}.md"
        mode_path = os.path.join(_PROMPT_DIR, mode_file)
        mode_block = load_prompt(mode_file) if os.path.exists(mode_path) else ""

    # Inject mode block into placeholder
    prompt = base.replace("{# EXPLORATION_MODE_BLOCK #}", mode_block)

    # Substitute template variables
    if template_vars:
        for key, value in template_vars.items():
            prompt = prompt.replace(f"{{{key}}}", str(value))

    return prompt


def render_agent_cards(cards: list) -> str:
    """
    Render agent name cards as a labeled 'Contributors' section.

    Called before render_expert_context() so the LLM reads who is
    contributing before it reads their specific findings.

    Args:
        cards: List of AgentCard dicts or Pydantic objects.

    Returns:
        Formatted string, or empty string when cards is empty (no noise
        in single-agent runs).
    """
    if not cards:
        return ""

    lines = [
        "## External Contributors\n",
        "Read each contributor's role and trust guidance before reading their findings.\n",
    ]
    for card in cards:
        if hasattr(card, "model_dump"):
            card = card.model_dump()
        name = card.get("agent_name", "unknown")
        lines.append(f"### {name}")
        for field in ("role", "expertise_domain", "coverage", "limitations", "trust_guidance"):
            val = card.get(field, "")
            if val:
                lines.append(f"  {field.replace('_', ' ').title()}: {val}")
        lines.append("")

    return "\n".join(lines)


def render_expert_context(items: list) -> str:
    """
    Render a list of ExpertContextItem dicts into a labeled prompt block.

    Groups items by kind, deduplicates by cite_id (last occurrence wins),
    and sorts each group by confidence descending (None last).
    The grouping and labeling IS the priority system — no explicit weights.

    Args:
        items: List of ExpertContextItem dicts (or Pydantic objects with
               .model_dump()).

    Returns:
        Formatted string ready for injection into any stage prompt.
    """
    if not items:
        return ""

    # Normalize to dicts
    normalized = []
    for item in items:
        if hasattr(item, "model_dump"):
            normalized.append(item.model_dump())
        else:
            normalized.append(item)

    # Deduplicate by cite_id — last occurrence wins (most recent agent's version kept)
    seen_cite_ids: dict[str, dict] = {}
    for item in normalized:
        cite_id = item.get("cite_id", "")
        seen_cite_ids[cite_id] = item
    deduplicated = list(seen_cite_ids.values())

    # Group by kind
    KIND_ORDER = ["empirical", "theoretical", "strategy_report", "human", "narrative", "literature"]
    KIND_LABELS = {
        "empirical": "EMPIRICAL FINDING",
        "theoretical": "THEORETICAL CONSTRAINT",
        "strategy_report": "STRATEGY REPORT",
        "human": "HUMAN DIRECTIVE",
        "narrative": "NARRATIVE CONTEXT",
        "literature": "LITERATURE REFERENCE",
    }

    groups: dict[str, list] = {}
    for item in deduplicated:
        kind = item.get("kind", "human")
        groups.setdefault(kind, []).append(item)

    # Sort each group by confidence descending; None sorts last
    def _conf_key(item: dict) -> float:
        c = item.get("confidence")
        return c if c is not None else -1.0

    lines = ["## Expert Context\n"]
    for kind in KIND_ORDER:
        if kind not in groups:
            continue
        for item in sorted(groups[kind], key=_conf_key, reverse=True):
            label = KIND_LABELS.get(kind, kind.upper())
            source = item.get("source", "unknown")
            confidence = item.get("confidence")
            conf_str = f", confidence={confidence}" if confidence is not None else ""
            cite_id = item.get("cite_id", "")

            lines.append(f"[{label}] (from {source}{conf_str}, cite_id={cite_id})")
            lines.append(f"  {item.get('content', '')}")
            lines.append("")

    # Handle any kinds not in KIND_ORDER
    for kind, items_in_group in groups.items():
        if kind in KIND_ORDER:
            continue
        for item in sorted(items_in_group, key=_conf_key, reverse=True):
            lines.append(f"[{kind.upper()}] (from {item.get('source', 'unknown')})")
            lines.append(f"  {item.get('content', '')}")
            lines.append("")

    return "\n".join(lines)
