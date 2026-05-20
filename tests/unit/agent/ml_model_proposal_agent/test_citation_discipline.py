"""
Unit tests for _check_citation_discipline and its integration into the pipeline.

Group 1 — pure function tests: _check_citation_discipline returns the correct
  violation list for a variety of citation / reasoning-text combinations.

Group 2 — pipeline integration: violations produced by the check are appended
  to ProposalOutput.memo_consistency_notes; the proposal is not rejected.

No LLM calls in either group — bridge.generate is mocked where needed.
"""

from unittest.mock import MagicMock

import pytest

from agent.schemas.proposal import (
    ProposalInput,
    ProposalOutput,
    ReasoningPipelineConfig,
    ReasoningStage,
)
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from nodes.ml_model_proposal_agent import MLModelProposalAgent, _check_citation_discipline

# ===========================================================================
# Group 1 — pure function tests
# ===========================================================================


class TestCheckCitationDiscipline:
    def test_empty_citation_list_returns_no_violations(self):
        violations = _check_citation_discipline(
            citation_sources=[],
            causal_hypothesis="Spectral conv addresses the low-frequency gap.",
            proposed_change="Add a spectral conv layer after the dilated stack.",
        )
        assert violations == []

    def test_cite_id_present_in_causal_hypothesis(self):
        violations = _check_citation_discipline(
            citation_sources=["data_psd_50hz"],
            causal_hypothesis="The data_psd_50hz finding shows a 50 Hz artifact.",
            proposed_change="Add a notch filter.",
        )
        assert violations == []

    def test_cite_id_present_in_proposed_change(self):
        violations = _check_citation_discipline(
            citation_sources=["data_psd_50hz"],
            causal_hypothesis="A 50 Hz artifact was found in the data.",
            proposed_change="Based on data_psd_50hz, add a notch filter.",
        )
        assert violations == []

    def test_cite_id_absent_from_both_fields_returns_violation(self):
        violations = _check_citation_discipline(
            citation_sources=["data_psd_50hz"],
            causal_hypothesis="Spectral processing addresses the low-freq gap.",
            proposed_change="Add a spectral conv layer.",
        )
        assert len(violations) == 1
        assert "data_psd_50hz" in violations[0]
        assert "CITATION_NOT_REFERENCED" in violations[0]

    def test_violation_message_names_the_cite_id(self):
        violations = _check_citation_discipline(
            citation_sources=["phys_axion_mass_bound"],
            causal_hypothesis="Spectral conv addresses the low-freq gap.",
            proposed_change="Add a spectral layer.",
        )
        assert "phys_axion_mass_bound" in violations[0]

    def test_multiple_citations_all_present(self):
        violations = _check_citation_discipline(
            citation_sources=["cite_a", "cite_b"],
            causal_hypothesis="cite_a finding motivates the change.",
            proposed_change="Based on cite_b, we add a layer.",
        )
        assert violations == []

    def test_multiple_citations_one_absent(self):
        violations = _check_citation_discipline(
            citation_sources=["cite_a", "cite_b"],
            causal_hypothesis="cite_a finding motivates the change.",
            proposed_change="Add a spectral layer.",  # cite_b not referenced
        )
        assert len(violations) == 1
        assert "cite_b" in violations[0]

    def test_multiple_citations_all_absent(self):
        violations = _check_citation_discipline(
            citation_sources=["cite_a", "cite_b"],
            causal_hypothesis="Spectral conv addresses the gap.",
            proposed_change="Add a spectral layer.",
        )
        assert len(violations) == 2
        cited_ids = [v for v in violations if "cite_a" in v or "cite_b" in v]
        assert len(cited_ids) == 2

    def test_empty_hypothesis_and_change_produces_violation(self):
        violations = _check_citation_discipline(
            citation_sources=["data_psd"],
            causal_hypothesis="",
            proposed_change="",
        )
        assert len(violations) == 1
        assert "data_psd" in violations[0]

    def test_cite_id_must_match_verbatim(self):
        """Partial substring of a cite_id does not count as a reference."""
        violations = _check_citation_discipline(
            citation_sources=["data_psd_50hz_peak"],
            causal_hypothesis="The data_psd_50hz finding is relevant.",  # shorter id
            proposed_change="Add a filter.",
        )
        assert len(violations) == 1  # full id not present


# ===========================================================================
# Group 2 — pipeline integration
# ===========================================================================


def _make_pipeline_input(tmp_path, reasoning_output: dict) -> ProposalInput:
    return ProposalInput(
        interpretation={
            "model_types": ["wavenet"],
            "total_experiments": 3,
            "best_denoising_score": 5.5,
            "worst_denoising_score": 1.0,
            "key_findings": ["wavenet wins"],
            "bottlenecks": ["low-freq gap"],
            "take_home_message": "Wavenet dominates.",
        },
        existing_model_types=["wavenet"],
        reasoning_pipeline=ReasoningPipelineConfig(
            exploration_mode="exploit",
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


def _make_comparison_output():
    return {
        "comparisons": [],
        "proposed_vocab_links": [],
        "proposed_vocab_candidates": [],
        "sota_model_type": "wavenet",
        "sota_score": 5.5,
        "sota_mechanism": "Dilated causal conv.",
    }


def _make_proposing_output(memo_consistency_notes=None):
    return {
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
        "memo_consistency_notes": memo_consistency_notes or [],
    }


def _make_agent(responses: list) -> tuple[MLModelProposalAgent, MagicMock]:
    mock = MagicMock()
    mock.generate.side_effect = responses
    agent = MLModelProposalAgent(
        provider="gemini",
        model_id="test",
        bridge_factory=lambda **kw: mock,
    )
    return agent, mock


class TestCitationDisciplinePipelineIntegration:
    def test_violations_appended_to_memo_consistency_notes(self, tmp_path):
        """When a cite_id is not referenced in the reasoning text, the violation
        is appended to output.memo_consistency_notes (not a hard failure)."""
        reasoning = {
            "proposed_change": "Add a spectral conv layer.",
            "causal_hypothesis": "Spectral processing addresses the low-freq gap.",
            "citation_sources": ["data_psd_50hz"],  # not referenced in either text
            "falsifiable_prediction": {
                "metric": "denoising_score",
                "current_value": 5.5,
                "predicted_value": 6.5,
                "threshold_for_refutation": 5.0,
                "rationale": "Spectral should help.",
            },
            "predicted_failure_modes": ["VRAM overflow."],
            "inherited_components": [],
            "proposed_vocab_candidates": [],
        }
        agent, _ = _make_agent(
            [
                _make_comparison_output(),
                reasoning,
                _make_proposing_output(),
            ]
        )
        output = agent.run(_make_pipeline_input(tmp_path, reasoning))

        assert isinstance(output, ProposalOutput)
        violation_notes = [
            n for n in output.memo_consistency_notes if "CITATION_NOT_REFERENCED" in n
        ]
        assert len(violation_notes) == 1
        assert "data_psd_50hz" in violation_notes[0]

    def test_no_violations_when_all_citations_referenced(self, tmp_path):
        """When every cite_id appears in the reasoning text, memo_consistency_notes
        contains no CITATION_NOT_REFERENCED entries."""
        reasoning = {
            "proposed_change": "Based on data_psd_50hz, add a notch filter.",
            "causal_hypothesis": "Spectral processing addresses the low-freq gap.",
            "citation_sources": ["data_psd_50hz"],
            "falsifiable_prediction": {
                "metric": "denoising_score",
                "current_value": 5.5,
                "predicted_value": 6.5,
                "threshold_for_refutation": 5.0,
                "rationale": "Spectral should help.",
            },
            "predicted_failure_modes": ["VRAM overflow."],
            "inherited_components": [],
            "proposed_vocab_candidates": [],
        }
        agent, _ = _make_agent(
            [
                _make_comparison_output(),
                reasoning,
                _make_proposing_output(),
            ]
        )
        output = agent.run(_make_pipeline_input(tmp_path, reasoning))

        violation_notes = [
            n for n in output.memo_consistency_notes if "CITATION_NOT_REFERENCED" in n
        ]
        assert violation_notes == []

    def test_existing_memo_consistency_notes_preserved(self, tmp_path):
        """Citation violations are appended; notes from the proposing stage LLM
        are not overwritten."""
        reasoning = {
            "proposed_change": "Add a spectral layer.",
            "causal_hypothesis": "Spectral addresses gap.",
            "citation_sources": ["missing_cite"],
            "falsifiable_prediction": {
                "metric": "denoising_score",
                "current_value": 5.5,
                "predicted_value": 6.5,
                "threshold_for_refutation": 5.0,
                "rationale": "Should help.",
            },
            "predicted_failure_modes": ["VRAM overflow."],
            "inherited_components": [],
            "proposed_vocab_candidates": [],
        }
        agent, _ = _make_agent(
            [
                _make_comparison_output(),
                reasoning,
                _make_proposing_output(
                    memo_consistency_notes=["LLM noted: slight deviation from memo."]
                ),
            ]
        )
        output = agent.run(_make_pipeline_input(tmp_path, reasoning))

        assert "LLM noted: slight deviation from memo." in output.memo_consistency_notes
        violation_notes = [
            n for n in output.memo_consistency_notes if "CITATION_NOT_REFERENCED" in n
        ]
        assert len(violation_notes) == 1

    def test_empty_citation_sources_no_notes_added(self, tmp_path):
        """No citations → no CITATION_NOT_REFERENCED notes added."""
        reasoning = {
            "proposed_change": "Add a spectral layer.",
            "causal_hypothesis": "Spectral addresses gap.",
            "citation_sources": [],
            "falsifiable_prediction": {
                "metric": "denoising_score",
                "current_value": 5.5,
                "predicted_value": 6.5,
                "threshold_for_refutation": 5.0,
                "rationale": "Should help.",
            },
            "predicted_failure_modes": ["VRAM overflow."],
            "inherited_components": [],
            "proposed_vocab_candidates": [],
        }
        agent, _ = _make_agent(
            [
                _make_comparison_output(),
                reasoning,
                _make_proposing_output(),
            ]
        )
        output = agent.run(_make_pipeline_input(tmp_path, reasoning))

        violation_notes = [
            n for n in output.memo_consistency_notes if "CITATION_NOT_REFERENCED" in n
        ]
        assert violation_notes == []
