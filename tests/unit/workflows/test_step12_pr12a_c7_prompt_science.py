"""Composed tuner prompts remain task-neutral at their rendering boundary.

The supported execution path always supplies a task composition. These tests
therefore protect the generic composed rendering and the separation between
render authority and prompt assembly; historical uncomposed task bytes belong
to the external task package rather than framework CI.
"""

from __future__ import annotations

from pathlib import Path

from agent.prompt_templates.tuner.rendering import (
    build_tuner_task_render,
    render_available_models_block,
    render_per_file_table_protocol,
    render_score_display_noun,
    render_score_field_noun,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

NEUTRAL_MODEL_BLOCK = (
    "### THE MODEL UNDER TUNING:\n"
    "This run tunes ONE model, supplied by the task package. Its architecture "
    "description — when the task declares one — appears in the "
    "[MODEL ARCHITECTURE DESCRIPTION] block of the user message. Do not assume "
    "a built-in architecture or its properties.\n"
)


class TestComposedRenderAuthority:
    def test_frozen_record_key_uses_a_task_neutral_noun(self):
        assert render_score_field_noun(composed=True) == "field"
        assert render_score_display_noun(composed=True) == "score"

    def test_model_block_points_to_the_declared_architecture(self):
        block = render_available_models_block(composed=True)
        assert block == NEUTRAL_MODEL_BLOCK

    def test_undeclared_per_partition_protocol_renders_nothing(self):
        assert render_per_file_table_protocol(composed=True) == ""

    def test_complete_render_contains_replacements_without_task_science(self):
        render = build_tuner_task_render(
            dataset=type("DatasetFacts", (), {"num_files": 4, "segments_per_file": 8})(),
            model_io_contract=None,
            health_config=type("HealthFacts", (), {"health_gates": []})(),
            efficiency_band_fraction=0.05,
            composed=True,
        )
        assert render.available_models_block == NEUTRAL_MODEL_BLOCK
        assert render.per_file_table_protocol == ""
        assert render.score_field_noun == "field"
        assert render.score_display_noun == "score"


class TestAssemblyDoesNotOwnComposition:
    def test_llm_bridge_does_not_read_a_composition_authority(self):
        source = (REPO_ROOT / "agent" / "llm_bridge.py").read_text(encoding="utf-8")
        for forbidden in (
            "active_task_data_path",
            "active_composition_fingerprint",
            "task_composition_ref",
            "bind_run_task_composition",
        ):
            assert forbidden not in source, forbidden

    def test_prompt_module_is_composition_free(self):
        source = (REPO_ROOT / "agent" / "prompts.py").read_text(encoding="utf-8")
        assert "task_composition" not in source
        assert "active_task_data_path" not in source
