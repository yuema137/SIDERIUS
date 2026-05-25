"""Tests for the SYSTEM-ENFORCED DATASET CONSTRAINTS block injected into the
proposing-stage prompt.

See docs/improving_validation_awareness.md Phase A.2 / A.3.

Validates:
  _format_known_constraints_block:
    - Returns empty string when dataset_config is None (backward compat)
    - Renders block with psd_segment_length verbatim
    - Lists valid divisors
    - Calls out invalid powers of 2 (16384, 8192, 4096) explicitly
    - Mentions 16000 as the recovery hint for 16384

  proposing_stage prompt rendering:
    - Block renders into the {known_constraints_block} placeholder
    - When dataset_config is None, the placeholder collapses to empty (no leftover braces)
    - Rendered block precedes the Rules section (high salience near baseline_config)
"""

from agent.prompt_templates.proposal import load_stage_prompt
from agent.prompts import _format_known_constraints_block
from execute_tools.dataset_config import TIDMAD

# ---- _format_known_constraints_block ----


def test_empty_when_dataset_config_none():
    assert _format_known_constraints_block(None) == ""


def test_block_includes_psd_segment_length():
    block = _format_known_constraints_block(TIDMAD)
    assert "10,000,000" in block or "10000000" in block


def test_block_lists_valid_divisors():
    block = _format_known_constraints_block(TIDMAD)
    assert "16000" in block
    assert "1250" in block
    assert "100" in block


def test_block_calls_out_invalid_powers_of_two():
    block = _format_known_constraints_block(TIDMAD)
    assert "16384" in block
    assert "8192" in block
    assert "4096" in block
    assert "INVALID" in block


def test_block_has_high_salience_heading():
    block = _format_known_constraints_block(TIDMAD)
    assert "SYSTEM-ENFORCED DATASET CONSTRAINTS" in block
    assert "machine-validated" in block.lower()


def test_block_mentions_recovery_hint():
    """The LLM kept proposing 16384 — the block should suggest 16000 explicitly."""
    block = _format_known_constraints_block(TIDMAD)
    # 16000 is the nearest valid neighbor of 16384.
    assert "16000" in block


# ---- proposing_stage prompt integration ----


def test_proposing_stage_renders_block_when_supplied():
    block = _format_known_constraints_block(TIDMAD)
    prompt = load_stage_prompt(
        "proposing_stage",
        exploration_mode="explore",
        template_vars={
            "minimum_boldness": "0.05",
            "n_agent_proposed": "0",
            "n_confirmed_links": "0",
            "existing_model_types": "wavenet, punet",
            "known_constraints_block": block,
        },
    )
    assert "SYSTEM-ENFORCED DATASET CONSTRAINTS" in prompt
    assert "16384" in prompt
    assert "16000" in prompt


def test_proposing_stage_collapses_block_to_empty_when_none():
    prompt = load_stage_prompt(
        "proposing_stage",
        exploration_mode="explore",
        template_vars={
            "minimum_boldness": "0.05",
            "n_agent_proposed": "0",
            "n_confirmed_links": "0",
            "existing_model_types": "wavenet",
            "known_constraints_block": "",
        },
    )
    # Placeholder substituted; no SYSTEM-ENFORCED block content.
    assert "{known_constraints_block}" not in prompt
    assert "SYSTEM-ENFORCED DATASET CONSTRAINTS" not in prompt


def test_block_precedes_rules_section():
    """The block must render above the Rules section so the LLM reads
    constraints right next to the baseline_config description."""
    block = _format_known_constraints_block(TIDMAD)
    prompt = load_stage_prompt(
        "proposing_stage",
        exploration_mode="explore",
        template_vars={
            "minimum_boldness": "0.05",
            "n_agent_proposed": "0",
            "n_confirmed_links": "0",
            "existing_model_types": "wavenet",
            "known_constraints_block": block,
        },
    )
    constraints_idx = prompt.index("SYSTEM-ENFORCED DATASET CONSTRAINTS")
    rules_idx = prompt.index("## Rules")
    assert constraints_idx < rules_idx


def test_other_stages_unaffected_by_unknown_placeholder():
    """The {known_constraints_block} placeholder appears only in proposing_stage.md.
    Comparison and causal_reasoning templates must not have it."""
    for stage in ("comparison_stage", "causal_reasoning_stage"):
        prompt = load_stage_prompt(
            stage,
            exploration_mode="explore",
            template_vars={
                "minimum_boldness": "0.05",
                "n_agent_proposed": "0",
                "n_confirmed_links": "0",
                "existing_model_types": "wavenet",
                "known_constraints_block": _format_known_constraints_block(TIDMAD),
            },
        )
        # Other stages should not echo the constraints block content.
        assert "SYSTEM-ENFORCED DATASET CONSTRAINTS" not in prompt
