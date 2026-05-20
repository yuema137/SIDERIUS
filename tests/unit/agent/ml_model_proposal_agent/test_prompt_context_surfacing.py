"""
Unit tests for the prompt-context surfacing additions in nodes/ml_model_proposal_agent.py.

Covers:
  Group 1 — _build_reasoning_prompt: Phase E (prediction track record) and
             Phase C (vocabulary health) sections injected into the reasoning
             prompt when the corresponding fields are present in `interpretation`.

  Group 2 — MLModelProposalAgent._render_vocabulary: confirmed feature→capability
             links rendered with '→ enables:' and '← enabled by:' suffixes.

  Group 3 — n_confirmed_links template variable: computed from vocab_seed.related_to
             and substituted into the Stage 1 system prompt (exploit mode only, where
             comparison_stage_exploit.md contains the {n_confirmed_links} placeholder).

All tests are pure-Python / mocked-bridge — no LLM calls, no GPU, no disk I/O beyond
tmp_path fixture.
"""

import json
from unittest.mock import MagicMock

import pytest

from agent.schemas.proposal import (
    ProposalInput,
    ProposalOutput,
    ReasoningPipelineConfig,
    ReasoningStage,
    VocabEntry,
)
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from nodes.ml_model_proposal_agent import MLModelProposalAgent, _build_reasoning_prompt

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _minimal_interp(**extra) -> dict:
    """Minimal interpretation dict.  Pass extra= to add Phase E / Phase C fields."""
    base = {
        "model_types": ["wavenet"],
        "total_experiments": 5,
        "best_denoising_score": 5.5,
        "worst_denoising_score": 1.0,
        "key_findings": ["dilated conv wins"],
        "bottlenecks": ["low-freq gap"],
        "take_home_message": "Wavenet dominates; low-freq gap remains open.",
    }
    base.update(extra)
    return base


def _minimal_input(tmp_path, interp: dict, vocab_seed=None) -> ProposalInput:
    return ProposalInput(
        interpretation=interp,
        existing_model_types=["wavenet"],
        vocab_seed=vocab_seed or [],
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="test"),
        ),
    )


# ---------------------------------------------------------------------------
# Shared fake LLM outputs (reused across groups)
# ---------------------------------------------------------------------------

_FAKE_COMPARISON = {
    "comparisons": [],
    "proposed_vocab_links": [],
    "proposed_vocab_candidates": [],
    "sota_model_type": "wavenet",
    "sota_score": 5.5,
    "sota_mechanism": "Dilated causal conv.",
}

_FAKE_REASONING = {
    "proposed_change": "Add spectral layer.",
    "causal_hypothesis": "Spectral conv addresses low-freq.",
    "falsifiable_prediction": {
        "metric": "denoising_score",
        "current_value": 5.5,
        "predicted_value": 6.2,
        "threshold_for_refutation": 5.0,
        "rationale": "Spectral processing should lift low-freq by 0.7.",
    },
    "predicted_failure_modes": ["VRAM overflow."],
    "inherited_components": [],
    "proposed_vocab_candidates": [],
}

_FAKE_PROPOSING = {
    "model_name": "spectral_wavenet",
    "model_description": "WaveNet + spectral conv.",
    "mathematical_definition": "Dilated conv + FFT layer.",
    "motivation": "Addresses low-freq bottleneck.",
    "expert_advice": {
        "focus_areas": ["low-freq recovery"],
        "constraints": ["VRAM < 10 GB", "params < 50M"],
        "known_failures": [],
        "suggested_directions": ["start with depth=2"],
        "rationale": "Conservative baseline.",
    },
    "baseline_config": {
        "model_config": {"depth": 2},
        "train_config": {"lr": 1e-4, "epochs": 5},
        "loss_config": {"loss_type": "focal"},
    },
    "memo_consistency_notes": [],
}


def _make_agent_with_mock() -> tuple[MLModelProposalAgent, MagicMock]:
    mock_bridge = MagicMock()
    mock_bridge.generate.side_effect = [
        _FAKE_COMPARISON,
        _FAKE_REASONING,
        _FAKE_PROPOSING,
    ]
    agent = MLModelProposalAgent(
        provider="gemini",
        model_id="test",
        bridge_factory=lambda **kw: mock_bridge,
    )
    return agent, mock_bridge


def _pipeline_input(
    tmp_path, interp: dict, vocab_seed=None, exploration_mode: str = "exploit"
) -> ProposalInput:
    """Input wired with a 2-stage pipeline and explicit exploration mode."""
    return ProposalInput(
        interpretation=interp,
        existing_model_types=["wavenet"],
        vocab_seed=vocab_seed or [],
        reasoning_pipeline=ReasoningPipelineConfig(
            exploration_mode=exploration_mode,
            stages=[
                ReasoningStage(name="comparison", system_prompt_key="COMPARATIVE_ANALYSIS"),
                ReasoningStage(name="causal_reasoning", system_prompt_key="CAUSAL_REASONING"),
            ],
        ),
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="test"),
        ),
    )


# ===========================================================================
# Group 1 — _build_reasoning_prompt: Phase E + Phase C prompt sections
# ===========================================================================


class TestBuildReasoningPromptTrackRecord:
    """Phase E prediction track record appears iff scientific_accuracy or
    cumulative_information_gain is present in the interpretation dict."""

    def test_track_record_absent_when_neither_field_present(self, tmp_path):
        inp = _minimal_input(tmp_path, _minimal_interp())
        prompt = _build_reasoning_prompt(inp)
        assert "Prediction Track Record" not in prompt

    def test_track_record_present_when_scientific_accuracy_set(self, tmp_path):
        interp = _minimal_interp(
            scientific_accuracy={"confirmed": 0.6, "refuted": 0.3, "partial": 0.1}
        )
        prompt = _build_reasoning_prompt(_minimal_input(tmp_path, interp))
        assert "Prediction Track Record" in prompt

    def test_track_record_present_when_only_cumulative_ig_set(self, tmp_path):
        interp = _minimal_interp(cumulative_information_gain=0.42)
        prompt = _build_reasoning_prompt(_minimal_input(tmp_path, interp))
        assert "Prediction Track Record" in prompt

    def test_confirmed_percentage_rendered_correctly(self, tmp_path):
        interp = _minimal_interp(
            scientific_accuracy={"confirmed": 0.6, "refuted": 0.4, "partial": 0.0}
        )
        prompt = _build_reasoning_prompt(_minimal_input(tmp_path, interp))
        assert "confirmed=60%" in prompt
        assert "refuted=40%" in prompt

    def test_partial_percentage_rendered(self, tmp_path):
        interp = _minimal_interp(
            scientific_accuracy={"confirmed": 0.5, "partial": 0.3, "refuted": 0.2}
        )
        prompt = _build_reasoning_prompt(_minimal_input(tmp_path, interp))
        assert "partial=30%" in prompt

    def test_cumulative_ig_formatted_to_three_decimals(self, tmp_path):
        interp = _minimal_interp(cumulative_information_gain=1.23456)
        prompt = _build_reasoning_prompt(_minimal_input(tmp_path, interp))
        assert "1.235" in prompt  # rounds to 3dp

    def test_total_n_from_prediction_outcomes_history(self, tmp_path):
        interp = _minimal_interp(
            scientific_accuracy={"confirmed": 0.5, "refuted": 0.5, "partial": 0.0},
            prediction_outcomes_history={"confirmed": 3, "refuted": 3, "partial": 0},
        )
        prompt = _build_reasoning_prompt(_minimal_input(tmp_path, interp))
        assert "N=6" in prompt

    def test_n_zero_when_history_absent(self, tmp_path):
        interp = _minimal_interp(
            scientific_accuracy={"confirmed": 1.0, "refuted": 0.0, "partial": 0.0},
            # prediction_outcomes_history intentionally absent
        )
        prompt = _build_reasoning_prompt(_minimal_input(tmp_path, interp))
        assert "N=0" in prompt

    def test_ig_line_absent_when_not_in_interp(self, tmp_path):
        """scientific_accuracy present but no cumulative_information_gain → no IG line."""
        interp = _minimal_interp(
            scientific_accuracy={"confirmed": 0.8, "refuted": 0.2, "partial": 0.0}
        )
        prompt = _build_reasoning_prompt(_minimal_input(tmp_path, interp))
        assert "Prediction Track Record" in prompt
        assert "information gain" not in prompt.lower()


class TestBuildReasoningPromptVocabHealth:
    """Phase C vocabulary health section appears iff vocab_diversity_ratio is present."""

    def test_vocab_health_absent_when_no_diversity_ratio(self, tmp_path):
        inp = _minimal_input(tmp_path, _minimal_interp())
        prompt = _build_reasoning_prompt(inp)
        assert "Vocabulary Health" not in prompt

    def test_vocab_health_present_when_ratio_set(self, tmp_path):
        interp = _minimal_interp(vocab_diversity_ratio=0.15)
        prompt = _build_reasoning_prompt(_minimal_input(tmp_path, interp))
        assert "Vocabulary Health" in prompt

    def test_low_ratio_shows_low_warning(self, tmp_path):
        interp = _minimal_interp(vocab_diversity_ratio=0.05)
        prompt = _build_reasoning_prompt(_minimal_input(tmp_path, interp))
        assert "LOW" in prompt

    def test_ratio_at_threshold_is_ok(self, tmp_path):
        """Ratio exactly at 0.1 should be 'OK', not 'LOW'."""
        interp = _minimal_interp(vocab_diversity_ratio=0.1)
        prompt = _build_reasoning_prompt(_minimal_input(tmp_path, interp))
        assert "OK" in prompt
        assert "LOW" not in prompt

    def test_high_ratio_is_ok(self, tmp_path):
        interp = _minimal_interp(vocab_diversity_ratio=0.5)
        prompt = _build_reasoning_prompt(_minimal_input(tmp_path, interp))
        assert "OK" in prompt
        assert "LOW" not in prompt

    def test_ratio_value_formatted_to_two_decimals(self, tmp_path):
        interp = _minimal_interp(vocab_diversity_ratio=0.12345)
        prompt = _build_reasoning_prompt(_minimal_input(tmp_path, interp))
        assert "0.12" in prompt


# ===========================================================================
# Group 2 — _render_vocabulary: '→ enables:' and '← enabled by:' links
# ===========================================================================


class TestRenderVocabularyLinks:
    """Confirmed feature→capability links appear with directional arrows in the
    vocab block when related_to is non-empty."""

    def test_feature_no_related_to_has_no_arrow(self):
        vocab = [
            {
                "name": "dilated_causal_conv",
                "kind": "feature",
                "description": "Causal conv with dilation.",
                "related_to": [],
            }
        ]
        block = MLModelProposalAgent._render_vocabulary(vocab)
        assert "→ enables" not in block
        assert "← enabled by" not in block

    def test_feature_with_single_link_shows_enables(self):
        vocab = [
            {
                "name": "dilated_causal_conv",
                "kind": "feature",
                "description": "Causal conv with dilation.",
                "related_to": ["receptive_field"],
            }
        ]
        block = MLModelProposalAgent._render_vocabulary(vocab)
        assert "→ enables: receptive_field" in block

    def test_feature_with_multiple_links_comma_separated(self):
        vocab = [
            {
                "name": "dilated_causal_conv",
                "kind": "feature",
                "description": "Causal conv with dilation.",
                "related_to": ["receptive_field", "temporal_context"],
            }
        ]
        block = MLModelProposalAgent._render_vocabulary(vocab)
        assert "→ enables: receptive_field, temporal_context" in block

    def test_capability_with_single_link_shows_enabled_by(self):
        vocab = [
            {
                "name": "receptive_field",
                "kind": "capability",
                "description": "How far back the model can see.",
                "related_to": ["dilated_causal_conv"],
            }
        ]
        block = MLModelProposalAgent._render_vocabulary(vocab)
        assert "← enabled by: dilated_causal_conv" in block

    def test_capability_no_related_to_has_no_arrow(self):
        vocab = [
            {
                "name": "receptive_field",
                "kind": "capability",
                "description": "How far back the model can see.",
                "related_to": [],
            }
        ]
        block = MLModelProposalAgent._render_vocabulary(vocab)
        assert "← enabled by" not in block

    def test_none_related_to_treated_as_empty(self):
        """related_to=None should behave identically to related_to=[]."""
        vocab = [
            {
                "name": "dilated_causal_conv",
                "kind": "feature",
                "description": "Causal conv.",
                "related_to": None,
            }
        ]
        block = MLModelProposalAgent._render_vocabulary(vocab)
        assert "→ enables" not in block

    def test_pydantic_vocabentry_object_with_links(self):
        """_render_vocabulary must work with VocabEntry Pydantic objects, not only dicts."""
        entry = VocabEntry(
            name="spectral_conv",
            kind="feature",
            description="FFT-based learnable weights.",
            related_to=["frequency_resolution"],
        )
        block = MLModelProposalAgent._render_vocabulary([entry])
        assert "→ enables: frequency_resolution" in block

    def test_pydantic_vocabentry_capability_with_links(self):
        entry = VocabEntry(
            name="frequency_resolution",
            kind="capability",
            description="Ability to distinguish frequency bands.",
            related_to=["spectral_conv"],
        )
        block = MLModelProposalAgent._render_vocabulary([entry])
        assert "← enabled by: spectral_conv" in block

    def test_mixed_pydantic_and_dict_entries(self):
        """A list with both Pydantic objects and plain dicts must render both correctly."""
        pydantic_entry = VocabEntry(
            name="spectral_conv",
            kind="feature",
            description="FFT conv.",
            related_to=["frequency_resolution"],
        )
        dict_entry = {
            "name": "receptive_field",
            "kind": "capability",
            "description": "Temporal coverage.",
            "related_to": ["dilated_causal_conv"],
        }
        block = MLModelProposalAgent._render_vocabulary([pydantic_entry, dict_entry])
        assert "→ enables: frequency_resolution" in block
        assert "← enabled by: dilated_causal_conv" in block


# ===========================================================================
# Group 3 — n_confirmed_links: template variable computed from vocab_seed
# ===========================================================================


class TestNConfirmedLinksTemplateVar:
    """n_confirmed_links is substituted into the Stage 1 system prompt (exploit mode).
    The value must reflect the count of vocab_seed entries with non-empty related_to."""

    def _stage1_system_prompt(self, agent, mock_bridge, inp) -> str:
        agent.run(inp)
        # Stage 1 is the first generate() call; args are (system_prompt, user_prompt).
        return mock_bridge.generate.call_args_list[0][0][0]

    def test_n_confirmed_links_zero_when_no_related_to(self, tmp_path):
        vocab_seed = [
            {
                "name": "dilated_causal_conv",
                "kind": "feature",
                "description": "Causal conv.",
                "related_to": [],
            },
            {
                "name": "spectral_conv",
                "kind": "feature",
                "description": "FFT conv.",
                "related_to": [],
            },
        ]
        interp = _minimal_interp(
            model_types=["wavenet", "punet", "m1", "m2", "m3", "m4", "m5"],
        )
        agent, mock = _make_agent_with_mock()
        inp = _pipeline_input(tmp_path, interp, vocab_seed=vocab_seed, exploration_mode="exploit")
        sys_prompt = self._stage1_system_prompt(agent, mock, inp)
        assert "0 confirmed" in sys_prompt

    def test_n_confirmed_links_counts_entries_with_related_to(self, tmp_path):
        vocab_seed = [
            # 2 entries with confirmed links
            {
                "name": "dilated_causal_conv",
                "kind": "feature",
                "description": "Causal conv.",
                "related_to": ["receptive_field"],
            },
            {
                "name": "spectral_conv",
                "kind": "feature",
                "description": "FFT conv.",
                "related_to": ["frequency_resolution"],
            },
            # 1 entry without links
            {
                "name": "gated_activation",
                "kind": "feature",
                "description": "Gated activation.",
                "related_to": [],
            },
        ]
        interp = _minimal_interp(
            model_types=["wavenet", "punet", "m1", "m2", "m3", "m4", "m5"],
        )
        agent, mock = _make_agent_with_mock()
        inp = _pipeline_input(tmp_path, interp, vocab_seed=vocab_seed, exploration_mode="exploit")
        sys_prompt = self._stage1_system_prompt(agent, mock, inp)
        assert "2 confirmed" in sys_prompt

    def test_n_confirmed_links_works_with_pydantic_objects(self, tmp_path):
        """VocabEntry Pydantic objects must be counted correctly."""
        vocab_seed = [
            VocabEntry(
                name="spectral_conv",
                kind="feature",
                description="FFT conv.",
                related_to=["frequency_resolution"],
            ),
            VocabEntry(
                name="dilated_causal_conv",
                kind="feature",
                description="Causal conv.",
                related_to=[],
            ),
        ]
        interp = _minimal_interp(
            model_types=["wavenet", "punet", "m1", "m2", "m3", "m4", "m5"],
        )
        agent, mock = _make_agent_with_mock()
        inp = _pipeline_input(tmp_path, interp, vocab_seed=vocab_seed, exploration_mode="exploit")
        sys_prompt = self._stage1_system_prompt(agent, mock, inp)
        assert "1 confirmed" in sys_prompt

    def test_n_confirmed_links_mixed_pydantic_and_dict(self, tmp_path):
        vocab_seed = [
            VocabEntry(
                name="spectral_conv",
                kind="feature",
                description="FFT conv.",
                related_to=["frequency_resolution"],
            ),
            {
                "name": "dilated_causal_conv",
                "kind": "feature",
                "description": "Causal conv.",
                "related_to": ["receptive_field"],
            },
            {
                "name": "gated_activation",
                "kind": "feature",
                "description": "Gated.",
                "related_to": [],
            },
        ]
        interp = _minimal_interp(
            model_types=["wavenet", "punet", "m1", "m2", "m3", "m4", "m5"],
        )
        agent, mock = _make_agent_with_mock()
        inp = _pipeline_input(tmp_path, interp, vocab_seed=vocab_seed, exploration_mode="exploit")
        sys_prompt = self._stage1_system_prompt(agent, mock, inp)
        assert "2 confirmed" in sys_prompt
