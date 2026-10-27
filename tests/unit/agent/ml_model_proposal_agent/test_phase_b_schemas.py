"""Custom prediction, source-identity, memo, and vocabulary coercion behavior."""

import pytest
from pydantic import ValidationError

from agent.schemas.proposal import (
    DiscoveryMemo,
    FalsifiablePrediction,
    InheritedComponent,
    ProposedVocabLink,
)


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


class TestFalsifiablePrediction:
    def test_valid(self, valid_prediction):
        fp = FalsifiablePrediction.model_validate(valid_prediction)
        assert fp.predicted_value == 2.0

    def test_predicted_equals_current_raises(self, valid_prediction):
        valid_prediction["predicted_value"] = valid_prediction["current_value"]
        with pytest.raises(ValidationError, match="predicted_value must differ"):
            FalsifiablePrediction.model_validate(valid_prediction)

    def test_boldness_property(self, valid_prediction):
        fp = FalsifiablePrediction.model_validate(valid_prediction)
        # current=1.5, predicted=2.0 → boldness = 0.5 / 1.5 = 0.333...
        expected = abs(2.0 - 1.5) / abs(1.5)
        assert abs(fp.boldness - expected) < 1e-10

    def test_boldness_with_zero_current(self):
        """When current_value is near zero, boldness uses 1e-6 as floor."""
        fp = FalsifiablePrediction.model_validate(
            {
                "metric": "score",
                "current_value": 0.0,
                "predicted_value": 0.5,
                "threshold_for_refutation": -0.1,
                "rationale": "test",
            }
        )
        assert fp.boldness == 0.5 / 1e-6  # very bold

    def test_boldness_timid_prediction(self):
        fp = FalsifiablePrediction.model_validate(
            {
                "metric": "score",
                "current_value": 10.0,
                "predicted_value": 10.01,
                "threshold_for_refutation": 9.9,
                "rationale": "test",
            }
        )
        assert fp.boldness < 0.01  # timid


class TestInheritedComponent:
    def test_valid_minimal_experiment(self):
        ic = InheritedComponent.model_validate(
            {
                "component": "dilated_causal_conv",
                "source_type": "experiment",
                "source_id": "wavenet",
                "contribution_evidence": "Gave wavenet a +0.15 lift on low_freq.",
            }
        )
        assert ic.from_run is None
        assert ic.source_type == "experiment"
        assert ic.source_id == "wavenet"

    def test_valid_external_agent_with_colon_format(self):
        """Happy-path for the regex-validated branch (source_type='external_agent')."""
        ic = InheritedComponent.model_validate(
            {
                "component": "composite_frequency_loss",
                "source_type": "external_agent",
                "source_id": "arxiv:2510.25800",
                "contribution_evidence": "FreLE composite loss closes spectral gap.",
            }
        )
        assert ic.source_id == "arxiv:2510.25800"

    @pytest.mark.parametrize(
        "bad_id",
        [
            "no_colon_at_all",  # missing colon entirely
            "prefix:",  # colon present but empty identifier
        ],
    )
    def test_external_source_id_regex_rejects_malformed(self, bad_id):
        with pytest.raises(ValidationError, match="does not match the required format"):
            InheritedComponent.model_validate(
                {
                    "component": "x",
                    "source_type": "external_agent",
                    "source_id": bad_id,
                    "contribution_evidence": "evidence",
                }
            )

    def test_experiment_source_id_skips_regex(self):
        """The conditional branch of the validator: source_type='experiment'
        accepts a bare token (no colon) — different code path from external_agent."""
        ic = InheritedComponent.model_validate(
            {
                "component": "x",
                "source_type": "experiment",
                "source_id": "wavenet",
                "contribution_evidence": "evidence",
            }
        )
        assert ic.source_id == "wavenet"


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


class TestProposedVocabLink:
    @pytest.mark.parametrize(
        "data_overrides,expected_status",
        [
            pytest.param(
                {
                    "feature": "dilated_causal_conv",
                    "capability": "receptive_field",
                    "evidence": ("Wavenet scores well on high-freq files and uses dilated convs."),
                },
                "proposed",
                id="default_status_is_proposed",
            ),
            pytest.param(
                {
                    "feature": "spectral_conv",
                    "capability": "frequency_resolution",
                    "evidence": "Confirmed in rounds 2 and 4.",
                    "status": "confirmed",
                },
                "confirmed",
                id="confirmed_status_passthrough",
            ),
            pytest.param(
                {
                    "feature": "bottleneck_compression",
                    "capability": "parameter_efficiency",
                    "evidence": "Smaller bottleneck did not improve score.",
                    "status": "refuted",
                },
                "refuted",
                id="refuted_status_passthrough",
            ),
            pytest.param(
                {
                    "feature": "test",
                    "capability": "test",
                    "evidence": "test",
                    "status": "maybe",
                },
                "proposed",
                id="invalid_status_coerced_to_proposed",
            ),
        ],
    )
    def test_status_resolution(self, data_overrides, expected_status):
        """Unknown LLM-invented status values are coerced to 'proposed' (not rejected)."""
        link = ProposedVocabLink.model_validate(data_overrides)
        assert link.status == expected_status
