"""
Unit tests for Phase B Group 1 schemas in agent/schemas/proposal.py.

Tests validators and cross-field checks for:
  - FalsifiablePrediction
  - InheritedComponent
  - ExpertContextItem
  - ModelComparison
  - DiscoveryMemo
  - ProposedVocabLink
  - ReasoningStage, ModelSelectionStrategy, ReasoningPipelineConfig
  - VocabEntry
"""
import pytest
from pydantic import ValidationError

from agent.schemas.proposal import (
    FalsifiablePrediction,
    InheritedComponent,
    ExpertContextItem,
    ModelComparison,
    DiscoveryMemo,
    ProposedVocabLink,
    ReasoningStage,
    ModelSelectionStrategy,
    ReasoningPipelineConfig,
    VocabEntry,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def valid_prediction():
    return {
        "metric": "denoising_score",
        "current_value": 1.5,
        "predicted_value": 2.0,
        "threshold_for_refutation": 1.3,
        "rationale": "Wider receptive field should improve low-freq recovery.",
    }


@pytest.fixture
def valid_comparison():
    return {
        "model_type": "wavenet",
        "source": "seed",
        "best_score": 5.57,
        "key_mechanism": "Dilated causal convolutions give exponential receptive field growth.",
        "strengths": ["Strong high-freq recovery (files 10-19)"],
        "weaknesses": ["Weak low-freq recovery (files 0-4)"],
        "lesson_for_next_proposal": "Inherit dilation pattern, add spectral processing for low-freq.",
    }


@pytest.fixture
def valid_memo(valid_prediction, valid_comparison):
    return {
        "comparative_analysis": [valid_comparison],
        "sota_model_type": "wavenet",
        "sota_score": 5.57,
        "sota_mechanism": "Dilated causal convolutions provide wide receptive field.",
        "proposed_change": "Add FNO spectral layer after the dilated conv stack.",
        "causal_hypothesis": (
            "WaveNet's dilated convolutions capture temporal patterns but miss "
            "low-frequency components. Adding an FNO layer provides direct spectral "
            "processing, relaxing the receptive field bottleneck for files 0-4."
        ),
        "falsifiable_prediction": valid_prediction,
        "predicted_failure_modes": ["FNO layer may double VRAM usage beyond budget."],
    }


# ---------------------------------------------------------------------------
# FalsifiablePrediction
# ---------------------------------------------------------------------------

class TestFalsifiablePrediction:

    def test_valid(self, valid_prediction):
        fp = FalsifiablePrediction.model_validate(valid_prediction)
        assert fp.predicted_value == 2.0

    def test_predicted_equals_current_raises(self, valid_prediction):
        valid_prediction["predicted_value"] = valid_prediction["current_value"]
        with pytest.raises(ValidationError, match="predicted_value must differ"):
            FalsifiablePrediction.model_validate(valid_prediction)

    def test_missing_metric_raises(self, valid_prediction):
        del valid_prediction["metric"]
        with pytest.raises(ValidationError):
            FalsifiablePrediction.model_validate(valid_prediction)

    def test_missing_rationale_raises(self, valid_prediction):
        del valid_prediction["rationale"]
        with pytest.raises(ValidationError):
            FalsifiablePrediction.model_validate(valid_prediction)


# ---------------------------------------------------------------------------
# InheritedComponent
# ---------------------------------------------------------------------------

class TestInheritedComponent:

    def test_valid_minimal(self):
        ic = InheritedComponent.model_validate({
            "component": "dilated_causal_conv",
            "from_model_type": "wavenet",
            "contribution_evidence": "Gave wavenet a +0.15 lift on low_freq.",
        })
        assert ic.from_run is None
        assert ic.citation_source is None

    def test_valid_full(self):
        ic = InheritedComponent.model_validate({
            "component": "gated_activation",
            "from_model_type": "wavenet",
            "from_run": "hpt_full_v1",
            "contribution_evidence": "Gating improved selectivity by 20%.",
            "citation_source": "human_advice_001",
        })
        assert ic.from_run == "hpt_full_v1"
        assert ic.citation_source == "human_advice_001"

    def test_missing_component_raises(self):
        with pytest.raises(ValidationError):
            InheritedComponent.model_validate({
                "from_model_type": "wavenet",
                "contribution_evidence": "something",
            })

    def test_evidence_max_length(self):
        """contribution_evidence has max_length=300."""
        with pytest.raises(ValidationError):
            InheritedComponent.model_validate({
                "component": "test",
                "from_model_type": "wavenet",
                "contribution_evidence": "x" * 301,
            })


# ---------------------------------------------------------------------------
# ExpertContextItem
# ---------------------------------------------------------------------------

class TestExpertContextItem:

    def test_valid(self):
        eci = ExpertContextItem.model_validate({
            "source": "human",
            "kind": "human",
            "content": "Focus on low-frequency recovery.",
            "cite_id": "human_001",
        })
        assert eci.confidence is None
        assert eci.produced_at is None

    def test_all_kinds_accepted(self):
        for kind in ["empirical", "theoretical", "literature", "human", "narrative"]:
            eci = ExpertContextItem.model_validate({
                "source": "test",
                "kind": kind,
                "content": "test content",
                "cite_id": f"test_{kind}",
            })
            assert eci.kind == kind

    def test_invalid_kind_raises(self):
        with pytest.raises(ValidationError):
            ExpertContextItem.model_validate({
                "source": "test",
                "kind": "invalid_kind",
                "content": "test",
                "cite_id": "test_001",
            })

    def test_confidence_range(self):
        """confidence must be 0.0-1.0 when provided."""
        with pytest.raises(ValidationError):
            ExpertContextItem.model_validate({
                "source": "test",
                "kind": "empirical",
                "content": "test",
                "cite_id": "test_001",
                "confidence": 1.5,
            })

    def test_content_max_length(self):
        with pytest.raises(ValidationError):
            ExpertContextItem.model_validate({
                "source": "test",
                "kind": "human",
                "content": "x" * 4001,
                "cite_id": "test_001",
            })


# ---------------------------------------------------------------------------
# ModelComparison
# ---------------------------------------------------------------------------

class TestModelComparison:

    def test_valid(self, valid_comparison):
        mc = ModelComparison.model_validate(valid_comparison)
        assert mc.model_type == "wavenet"
        assert mc.best_score == 5.57

    def test_key_mechanism_max_length(self, valid_comparison):
        valid_comparison["key_mechanism"] = "x" * 301
        with pytest.raises(ValidationError):
            ModelComparison.model_validate(valid_comparison)

    def test_missing_strengths_raises(self, valid_comparison):
        del valid_comparison["strengths"]
        with pytest.raises(ValidationError):
            ModelComparison.model_validate(valid_comparison)


# ---------------------------------------------------------------------------
# DiscoveryMemo
# ---------------------------------------------------------------------------

class TestDiscoveryMemo:

    def test_valid(self, valid_memo):
        memo = DiscoveryMemo.model_validate(valid_memo)
        assert memo.sota_model_type == "wavenet"
        assert len(memo.comparative_analysis) == 1
        assert len(memo.predicted_failure_modes) >= 1

    def test_empty_causal_hypothesis_raises(self, valid_memo):
        valid_memo["causal_hypothesis"] = "   "
        with pytest.raises(ValidationError, match="causal_hypothesis cannot be empty"):
            DiscoveryMemo.model_validate(valid_memo)

    def test_no_failure_modes_raises(self, valid_memo):
        valid_memo["predicted_failure_modes"] = []
        with pytest.raises(ValidationError):
            DiscoveryMemo.model_validate(valid_memo)

    def test_too_many_failure_modes_raises(self, valid_memo):
        valid_memo["predicted_failure_modes"] = ["a", "b", "c", "d"]
        with pytest.raises(ValidationError):
            DiscoveryMemo.model_validate(valid_memo)

    def test_optional_fields_default_empty(self, valid_memo):
        memo = DiscoveryMemo.model_validate(valid_memo)
        assert memo.inherited_components == []
        assert memo.proposed_vocab_candidates == []
        assert memo.citation_sources == []

    def test_with_inherited_components(self, valid_memo):
        valid_memo["inherited_components"] = [{
            "component": "dilated_causal_conv",
            "from_model_type": "wavenet",
            "contribution_evidence": "Core mechanism of wavenet's success.",
        }]
        memo = DiscoveryMemo.model_validate(valid_memo)
        assert len(memo.inherited_components) == 1
        assert memo.inherited_components[0].component == "dilated_causal_conv"

    def test_with_vocab_candidates(self, valid_memo):
        valid_memo["proposed_vocab_candidates"] = [
            {"name": "log_spaced_fno_gates", "kind": "feature",
             "description": "Gated FNO with log-spaced frequency bins."},
        ]
        memo = DiscoveryMemo.model_validate(valid_memo)
        assert len(memo.proposed_vocab_candidates) == 1

    def test_with_proposed_vocab_links(self, valid_memo):
        valid_memo["proposed_vocab_links"] = [
            {"feature": "dilated_causal_conv", "capability": "receptive_field",
             "evidence": "Wavenet uses dilated convs and scores well on high-freq files."},
        ]
        memo = DiscoveryMemo.model_validate(valid_memo)
        assert len(memo.proposed_vocab_links) == 1
        assert memo.proposed_vocab_links[0].status == "proposed"

    def test_proposed_vocab_links_default_empty(self, valid_memo):
        memo = DiscoveryMemo.model_validate(valid_memo)
        assert memo.proposed_vocab_links == []

    def test_sota_mechanism_max_length(self, valid_memo):
        valid_memo["sota_mechanism"] = "x" * 601
        with pytest.raises(ValidationError):
            DiscoveryMemo.model_validate(valid_memo)

    def test_proposed_change_max_length(self, valid_memo):
        valid_memo["proposed_change"] = "x" * 401
        with pytest.raises(ValidationError):
            DiscoveryMemo.model_validate(valid_memo)


# ---------------------------------------------------------------------------
# ReasoningStage / ModelSelectionStrategy / ReasoningPipelineConfig
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ProposedVocabLink
# ---------------------------------------------------------------------------

class TestProposedVocabLink:

    def test_valid(self):
        link = ProposedVocabLink.model_validate({
            "feature": "dilated_causal_conv",
            "capability": "receptive_field",
            "evidence": "Wavenet scores well on high-freq files and uses dilated convs.",
        })
        assert link.status == "proposed"  # default

    def test_confirmed_status(self):
        link = ProposedVocabLink.model_validate({
            "feature": "spectral_conv",
            "capability": "frequency_resolution",
            "evidence": "Confirmed in rounds 2 and 4.",
            "status": "confirmed",
        })
        assert link.status == "confirmed"

    def test_refuted_status(self):
        link = ProposedVocabLink.model_validate({
            "feature": "bottleneck_compression",
            "capability": "parameter_efficiency",
            "evidence": "Smaller bottleneck did not improve score.",
            "status": "refuted",
        })
        assert link.status == "refuted"

    def test_invalid_status_raises(self):
        with pytest.raises(ValidationError):
            ProposedVocabLink.model_validate({
                "feature": "test",
                "capability": "test",
                "evidence": "test",
                "status": "maybe",
            })

    def test_evidence_max_length(self):
        with pytest.raises(ValidationError):
            ProposedVocabLink.model_validate({
                "feature": "test",
                "capability": "test",
                "evidence": "x" * 301,
            })

    def test_missing_feature_raises(self):
        with pytest.raises(ValidationError):
            ProposedVocabLink.model_validate({
                "capability": "receptive_field",
                "evidence": "test",
            })


# ---------------------------------------------------------------------------
# ReasoningStage / ModelSelectionStrategy / ReasoningPipelineConfig
# ---------------------------------------------------------------------------

class TestReasoningPipelineConfig:

    def test_default_pipeline(self):
        config = ReasoningPipelineConfig()
        assert len(config.stages) == 2
        assert config.stages[0].name == "comparison"
        assert config.stages[1].name == "causal_reasoning"
        assert config.exploration_mode == "auto"

    def test_custom_stages(self):
        config = ReasoningPipelineConfig(stages=[
            ReasoningStage(name="physics_check", system_prompt_key="PHYSICS_REVIEW"),
        ])
        assert len(config.stages) == 1
        assert config.stages[0].name == "physics_check"

    def test_disable_stage(self):
        config = ReasoningPipelineConfig(stages=[
            ReasoningStage(name="comparison", system_prompt_key="COMP", enabled=False),
            ReasoningStage(name="reasoning", system_prompt_key="REASON"),
        ])
        enabled = [s for s in config.stages if s.enabled]
        assert len(enabled) == 1

    def test_output_mode_options(self):
        s1 = ReasoningStage(name="t", system_prompt_key="T", output_mode="json")
        s2 = ReasoningStage(name="t", system_prompt_key="T", output_mode="text")
        assert s1.output_mode == "json"
        assert s2.output_mode == "text"

    def test_invalid_output_mode_raises(self):
        with pytest.raises(ValidationError):
            ReasoningStage(name="t", system_prompt_key="T", output_mode="xml")

    def test_exploration_mode_options(self):
        for mode in ["auto", "explore", "exploit"]:
            config = ReasoningPipelineConfig(exploration_mode=mode)
            assert config.exploration_mode == mode

    def test_invalid_exploration_mode_raises(self):
        with pytest.raises(ValidationError):
            ReasoningPipelineConfig(exploration_mode="invalid")

    def test_model_selection_defaults(self):
        config = ReasoningPipelineConfig()
        assert config.model_selection.method == "top_n"
        assert config.model_selection.params == {"n": 10}

    def test_custom_model_selection(self):
        config = ReasoningPipelineConfig(
            model_selection=ModelSelectionStrategy(
                method="human_specified",
                params={"models": ["wavenet", "gated_fno"]},
            )
        )
        assert config.model_selection.method == "human_specified"
        assert config.model_selection.params["models"] == ["wavenet", "gated_fno"]


# ---------------------------------------------------------------------------
# VocabEntry
# ---------------------------------------------------------------------------

class TestVocabEntry:

    def test_valid_feature(self):
        ve = VocabEntry.model_validate({
            "name": "dilated_causal_conv",
            "kind": "feature",
            "description": "Causal convolution with exponentially increasing dilation.",
            "related_to": ["receptive_field"],
            "tier": "canonical",
            "pattern": r"dilation\s*=",
        })
        assert ve.tier == "canonical"
        assert ve.pattern is not None

    def test_valid_capability(self):
        ve = VocabEntry.model_validate({
            "name": "receptive_field",
            "kind": "capability",
            "description": "How far back in time the model can see per layer.",
            "related_to": ["dilated_causal_conv", "depth"],
        })
        assert ve.tier == "candidate"  # default
        assert ve.pattern is None  # capabilities don't have patterns

    def test_candidate_with_run(self):
        ve = VocabEntry.model_validate({
            "name": "log_spaced_fno_gates",
            "kind": "feature",
            "description": "Gated FNO with log-spaced frequency bins.",
            "proposed_by_run": "exploration_v3_iter_5",
            "seen_in_runs": ["exploration_v3_iter_5", "exploration_v3_iter_7"],
        })
        assert ve.tier == "candidate"
        assert len(ve.seen_in_runs) == 2

    def test_description_max_length(self):
        with pytest.raises(ValidationError):
            VocabEntry.model_validate({
                "name": "test",
                "kind": "feature",
                "description": "x" * 201,
            })

    def test_invalid_tier_raises(self):
        with pytest.raises(ValidationError):
            VocabEntry.model_validate({
                "name": "test",
                "kind": "feature",
                "description": "test",
                "tier": "promoted",  # not a valid tier
            })

    def test_aliases_default_empty(self):
        ve = VocabEntry.model_validate({
            "name": "test",
            "kind": "feature",
            "description": "test",
        })
        assert ve.aliases == []
        assert ve.related_to == []
        assert ve.seen_in_runs == []
