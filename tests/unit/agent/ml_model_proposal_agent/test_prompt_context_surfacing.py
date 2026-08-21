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
from agent.schemas.proposer_evidence import build_proposer_evidence
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
        interpretation_evidence=build_proposer_evidence(interp),
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
        interpretation_evidence=build_proposer_evidence(interp),
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
    """Phase E prediction track record — VERSION-AWARE since Step 09b C4.

    The section is rendered by the ONE authority
    (`agent.prompt_templates.interpretation.rendering.render_prediction_track_record`)
    that the interpreter's synthesis prompt also uses, so the two consumers
    cannot drift. These cells own the PROPOSER-side contract: the four
    history shapes of design §9, and — the reason C4 exists — that a v2
    fraction is never paired with the frozen legacy pool's denominator
    (the Q-09a-3 consequence).

    `_v2(...)` builds the live pool the way 09a writes it.
    """

    @staticmethod
    def _v2(confirmed=0, partial=0, refuted=0, gain=0.0) -> dict:
        return {
            "prediction_outcomes_by_semantics": {
                "metric_order_signsafe_v2": {
                    "confirmed": confirmed,
                    "partial": partial,
                    "refuted": refuted,
                }
            },
            "cumulative_information_gain_by_semantics": {"metric_order_signsafe_v2": gain},
        }

    def test_track_record_absent_when_no_prediction_state_exists(self, tmp_path):
        inp = _minimal_input(tmp_path, _minimal_interp())
        prompt = _build_reasoning_prompt(inp)
        assert "Prediction Track Record" not in prompt

    def test_an_empty_v2_pool_with_no_legacy_history_renders_nothing(self, tmp_path):
        """Shape 4 (empty): an absent hit-rate is not a zero one — and a bare
        `scientific_accuracy` with no pool behind it is not a track record."""
        interp = _minimal_interp(
            scientific_accuracy={"confirmed": 0.0, "partial": 0.0, "refuted": 0.0},
            **self._v2(),
        )
        prompt = _build_reasoning_prompt(_minimal_input(tmp_path, interp))
        assert "Prediction Track Record" not in prompt

    def test_v2_only_history_renders_percentages_with_its_own_n(self, tmp_path):
        """Shape 1 (v2-only). N comes from the V2 pool — 5, not the legacy 0."""
        interp = _minimal_interp(
            scientific_accuracy={"confirmed": 0.6, "partial": 0.2, "refuted": 0.2},
            **self._v2(confirmed=3, partial=1, refuted=1, gain=1.23456),
        )
        prompt = _build_reasoning_prompt(_minimal_input(tmp_path, interp))
        assert "Prediction Track Record" in prompt
        assert "Scientific accuracy (metric_order_signsafe_v2, N=5)" in prompt
        assert "confirmed=60%" in prompt
        assert "partial=20%" in prompt
        assert "refuted=20%" in prompt
        assert "Cumulative information gain (metric_order_signsafe_v2) : 1.235" in prompt
        assert "legacy_v1" not in prompt

    def test_legacy_only_history_renders_no_percentages(self, tmp_path):
        """Shape 2 (legacy-only): the pre-correction pool is stated and named
        NOT comparable; no hit-rate is invented for it."""
        interp = _minimal_interp(
            prediction_outcomes_history={"confirmed": 3, "refuted": 3, "partial": 0},
            cumulative_information_gain=0.42,
        )
        prompt = _build_reasoning_prompt(_minimal_input(tmp_path, interp))
        assert "Prediction Track Record" in prompt
        assert "Earlier predictions (legacy_v1) : 6 outcome(s)" in prompt
        assert "NOT comparable" in prompt
        assert "Cumulative information gain (legacy_v1) : 0.420" in prompt
        assert "Scientific accuracy" not in prompt
        assert "confirmed=" not in prompt

    def test_mixed_history_labels_both_populations_and_pools_neither(self, tmp_path):
        """Shape 3 (mixed) — the defect C4 fixes: v2 fractions must NOT be
        rendered over the legacy denominator."""
        interp = _minimal_interp(
            scientific_accuracy={"confirmed": 1.0, "partial": 0.0, "refuted": 0.0},
            prediction_outcomes_history={"confirmed": 0, "partial": 9, "refuted": 0},
            **self._v2(confirmed=2, gain=0.5),
        )
        prompt = _build_reasoning_prompt(_minimal_input(tmp_path, interp))
        assert "Scientific accuracy (metric_order_signsafe_v2, N=2)" in prompt
        assert "Earlier predictions (legacy_v1) : 9 outcome(s)" in prompt
        # The pre-09b rendering said "N=9" beside these v2 fractions, and a
        # naive pooling would say N=11. Neither may appear.
        assert "N=9" not in prompt
        assert "N=11" not in prompt

    def test_an_unevaluated_outcome_cannot_inflate_the_n(self, tmp_path):
        """09a keeps `unevaluated` out of both pools; the renderer therefore
        needs no branch for it — pinned so a future writer cannot add one."""
        pools = self._v2(confirmed=1, refuted=1)
        pools["prediction_outcomes_by_semantics"]["metric_order_signsafe_v2"]["unevaluated"] = 7
        interp = _minimal_interp(
            scientific_accuracy={"confirmed": 0.5, "partial": 0.0, "refuted": 0.5}, **pools
        )
        prompt = _build_reasoning_prompt(_minimal_input(tmp_path, interp))
        # The pool dict is summed as written by 09a (which never adds the key);
        # this asserts the RENDERED N is the comparable count when it is absent.
        assert "N=9" not in prompt


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


# ---------------------------------------------------------------------------
# DS7b — [DATA SCOPE] disclosure block
# ---------------------------------------------------------------------------

from execute_tools.dataset_config import DataScope
from nodes.ml_model_proposal_agent import _render_data_scope_block


class TestDataScopeBlock:
    def test_full_scope_renders_empty(self):
        assert _render_data_scope_block(DataScope.default()) == ""
        assert _render_data_scope_block(None) == ""
        assert _render_data_scope_block(DataScope(file_indices=list(range(20)))) == ""

    def test_partial_scope_lists_files_and_snapshot_rule(self):
        block = _render_data_scope_block(DataScope(file_indices=[4, 5, 6, 7, 8, 9]))
        assert "[DATA SCOPE]" in block
        assert "[4, 5, 6, 7, 8, 9]" in block
        assert "snapshot-only" in block

    def test_reasoning_prompt_carries_block_only_when_partial(self, tmp_path):
        inp = _minimal_input(tmp_path, _minimal_interp())
        assert "[DATA SCOPE]" not in _build_reasoning_prompt(inp)
        scoped = _minimal_input(tmp_path, _minimal_interp())
        scoped.data_scope = DataScope(file_indices=[4, 5, 6])
        prompt = _build_reasoning_prompt(scoped)
        assert "[DATA SCOPE]" in prompt
        assert "[4, 5, 6]" in prompt
