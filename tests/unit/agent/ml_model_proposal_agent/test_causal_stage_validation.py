"""
P-1 retry-discard fix (PR 3 audit §13): causal-stage-owned field validation.

The proposing-stage assembly re-injects ``inherited_components`` and
``falsifiable_prediction`` from ``accumulated["causal_reasoning"]`` on every
structural attempt, so validation errors in those fields can only be
corrected at the causal stage. These tests pin the new bounded
causal-stage correction loop:

  1. malformed causal citation → focused correction retry → corrected
     citation reaches the final ProposalOutput → node succeeds;
  2. repeated malformed corrections exhaust the bounded retries and fail
     with a stage-naming error, BEFORE any proposing call is spent;
  3. valid causal data → behavior identical to pre-fix (no extra calls,
     no correction markers anywhere);
  4. falsifiable_prediction corrections flow through the same path;
  5. the proposing stage's own structural retry is unaffected;
  6. prompt contract: the causal correction reuses the IDENTICAL system
     prompt (feedback lives only in the user prompt) and no fix marker
     leaks into the proposing-stage prompts;
  7. a pipeline without a causal stage passes through unchanged.
"""

from unittest.mock import MagicMock

import pytest

from agent.schemas.proposal import (
    CausalStageOwnedContent,
    ProposalInput,
    ReasoningPipelineConfig,
    ReasoningStage,
)
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from nodes.ml_model_proposal_agent import (
    _MAX_CAUSAL_CORRECTION_RETRIES,
    MLModelProposalAgent,
)

from .test_pipeline_runner import (
    FAKE_COMPARISON_OUTPUT,
    FAKE_INTERPRETATION,
    FAKE_PROPOSING_OUTPUT,
    FAKE_REASONING_OUTPUT,
)

CORRECTION_MARKER = "## VALIDATION ERROR — CORRECT AND RESEND"

MALFORMED_CITATION = {
    # The exact class observed in the rev-3 pilot (S1_C_1) and the v16
    # production chain: an iteration tag as an external_agent source_id.
    "component": "ce_plus_hf_spectral_loss",
    "source_type": "external_agent",
    "source_id": "iter_004",
    "contribution_evidence": "Reuse the registry loss introduced in iteration 4.",
}

CORRECTED_CITATION = {
    "component": "ce_plus_hf_spectral_loss",
    "source_type": "external_agent",
    "source_id": "registry:ce_plus_hf_spectral_loss",
    "contribution_evidence": "Reuse the registry loss introduced in iteration 4.",
}

MALFORMED_REASONING = dict(FAKE_REASONING_OUTPUT, inherited_components=[MALFORMED_CITATION])
CORRECTED_REASONING = dict(FAKE_REASONING_OUTPUT, inherited_components=[CORRECTED_CITATION])

# predicted == current fires FalsifiablePrediction._prediction_differs_from_current.
DEGENERATE_PREDICTION = dict(
    FAKE_REASONING_OUTPUT["falsifiable_prediction"], predicted_value=5.5, current_value=5.5
)
MALFORMED_PREDICTION_REASONING = dict(
    FAKE_REASONING_OUTPUT, falsifiable_prediction=DEGENERATE_PREDICTION
)


def _pipeline_input(tmp_path):
    return ProposalInput(
        interpretation=FAKE_INTERPRETATION,
        existing_model_types=["punet", "wavenet", "fcnet", "gated_fno"],
        reasoning_pipeline=ReasoningPipelineConfig(
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


def _agent(mock_bridge):
    return MLModelProposalAgent(
        provider="gemini",
        model_id="test",
        bridge_factory=lambda **kw: mock_bridge,
    )


class TestCausalCitationCorrection:
    def test_malformed_citation_corrected_and_preserved(self, tmp_path):
        """The corrected retry response — not the stale original — is what the
        final ProposalOutput validates and carries."""
        mock_bridge = MagicMock()
        mock_bridge.generate.side_effect = [
            FAKE_COMPARISON_OUTPUT,
            MALFORMED_REASONING,  # causal attempt: malformed source_id
            CORRECTED_REASONING,  # correction retry: legal source_id
            FAKE_PROPOSING_OUTPUT,
        ]
        output = _agent(mock_bridge).run(_pipeline_input(tmp_path))

        assert output.model_name == "spectral_wavenet"
        assert len(output.inherited_components) == 1
        assert output.inherited_components[0].source_id == "registry:ce_plus_hf_spectral_loss"
        # comparison(1) + causal(1) + correction(1) + proposing(1)
        assert mock_bridge.generate.call_count == 4

    def test_correction_call_has_focused_feedback_and_label(self, tmp_path):
        mock_bridge = MagicMock()
        mock_bridge.generate.side_effect = [
            FAKE_COMPARISON_OUTPUT,
            MALFORMED_REASONING,
            CORRECTED_REASONING,
            FAKE_PROPOSING_OUTPUT,
        ]
        _agent(mock_bridge).run(_pipeline_input(tmp_path))

        correction_call = mock_bridge.generate.call_args_list[2]
        correction_user = correction_call[0][1]
        assert CORRECTION_MARKER in correction_user
        assert "inherited_components" in correction_user
        assert "iter_004" in correction_user  # the offending value is quoted
        assert correction_call.kwargs["label"] == "proposer.causal_reasoning.correction"

    def test_repeated_malformed_exhausts_before_any_proposing_call(self, tmp_path):
        """Bounded exhaustion: 1 causal attempt + _MAX_CAUSAL_CORRECTION_RETRIES
        corrections, then a stage-naming RuntimeError. The proposing stage is
        never called — no budget is burned on unfixable attempts."""
        mock_bridge = MagicMock()
        mock_bridge.generate.side_effect = [FAKE_COMPARISON_OUTPUT] + [MALFORMED_REASONING] * (
            _MAX_CAUSAL_CORRECTION_RETRIES + 1
        )

        with pytest.raises(RuntimeError, match=r"Causal-reasoning stage.*correction retries"):
            _agent(mock_bridge).run(_pipeline_input(tmp_path))

        # comparison(1) + causal(1) + corrections(_MAX)
        assert mock_bridge.generate.call_count == 2 + _MAX_CAUSAL_CORRECTION_RETRIES


class TestPredictionCorrection:
    def test_degenerate_prediction_corrected_same_path(self, tmp_path):
        """predicted == current fails the FalsifiablePrediction validator; the
        correction path fixes it and the corrected prediction reaches the
        final output."""
        mock_bridge = MagicMock()
        mock_bridge.generate.side_effect = [
            FAKE_COMPARISON_OUTPUT,
            MALFORMED_PREDICTION_REASONING,
            FAKE_REASONING_OUTPUT,  # correction: valid 5.5 → 6.5 prediction
            FAKE_PROPOSING_OUTPUT,
        ]
        output = _agent(mock_bridge).run(_pipeline_input(tmp_path))

        assert output.falsifiable_prediction is not None
        assert output.falsifiable_prediction.predicted_value == 6.5
        assert mock_bridge.generate.call_count == 4

        correction_user = mock_bridge.generate.call_args_list[2][0][1]
        assert CORRECTION_MARKER in correction_user
        assert "falsifiable_prediction" in correction_user


class TestExistingBehaviorPreserved:
    def test_valid_causal_output_no_extra_calls_no_markers(self, tmp_path):
        """Pre-fix behavior byte-for-byte on the happy path: 3 calls, no
        correction label, no correction marker in any prompt."""
        mock_bridge = MagicMock()
        mock_bridge.generate.side_effect = [
            FAKE_COMPARISON_OUTPUT,
            FAKE_REASONING_OUTPUT,
            FAKE_PROPOSING_OUTPUT,
        ]
        output = _agent(mock_bridge).run(_pipeline_input(tmp_path))

        assert output.model_name == "spectral_wavenet"
        assert mock_bridge.generate.call_count == 3
        for call in mock_bridge.generate.call_args_list:
            assert call.kwargs.get("label") != "proposer.causal_reasoning.correction"
            assert CORRECTION_MARKER not in call[0][0]  # system prompt
            assert CORRECTION_MARKER not in call[0][1]  # user prompt

    def test_proposing_structural_retry_unaffected(self, tmp_path):
        """The proposing stage's own retry (duplicate model name) still works
        with the causal validation block active."""
        mock_bridge = MagicMock()
        duplicate = dict(FAKE_PROPOSING_OUTPUT, model_name="wavenet")
        mock_bridge.generate.side_effect = [
            FAKE_COMPARISON_OUTPUT,
            FAKE_REASONING_OUTPUT,
            duplicate,  # proposing attempt 1: duplicate name
            FAKE_PROPOSING_OUTPUT,  # proposing attempt 2: success
        ]
        output = _agent(mock_bridge).run(_pipeline_input(tmp_path))

        assert output.model_name == "spectral_wavenet"
        assert mock_bridge.generate.call_count == 4

    def test_correction_reuses_identical_causal_system_prompt(self, tmp_path):
        """Prompt contract: the focused feedback lives ONLY in the user
        prompt — the correction call's system prompt is byte-identical to
        the original causal-stage system prompt, and the proposing-stage
        system prompt carries no fix marker."""
        mock_bridge = MagicMock()
        mock_bridge.generate.side_effect = [
            FAKE_COMPARISON_OUTPUT,
            MALFORMED_REASONING,
            CORRECTED_REASONING,
            FAKE_PROPOSING_OUTPUT,
        ]
        _agent(mock_bridge).run(_pipeline_input(tmp_path))

        causal_system = mock_bridge.generate.call_args_list[1][0][0]
        correction_system = mock_bridge.generate.call_args_list[2][0][0]
        proposing_system = mock_bridge.generate.call_args_list[3][0][0]
        assert correction_system == causal_system
        assert CORRECTION_MARKER not in proposing_system
        assert "causal-owned" not in proposing_system

    def test_disabled_causal_stage_passes_through(self, tmp_path):
        """No causal stage → empty defaults validate, no correction, no
        causal_reasoning key inserted into accumulated (2 calls as before)."""
        mock_bridge = MagicMock()
        mock_bridge.generate.side_effect = [
            FAKE_COMPARISON_OUTPUT,
            FAKE_PROPOSING_OUTPUT,
        ]
        inp = _pipeline_input(tmp_path)
        inp.reasoning_pipeline.stages[1].enabled = False
        output = _agent(mock_bridge).run(inp)

        assert output.model_name == "spectral_wavenet"
        assert mock_bridge.generate.call_count == 2
        # The proposing prompt must not have gained a null causal_reasoning key.
        proposing_user = mock_bridge.generate.call_args_list[1][0][1]
        assert '"causal_reasoning": null' not in proposing_user


class TestPartialSchemaScope:
    def test_schema_mirrors_proposal_output_contract(self):
        """CausalStageOwnedContent accepts exactly what ProposalOutput accepts
        for these fields: empty components + absent prediction are legal
        (legacy allowance), malformed citations are not."""
        CausalStageOwnedContent.model_validate({})
        CausalStageOwnedContent.model_validate(
            {"inherited_components": [], "falsifiable_prediction": None}
        )
        CausalStageOwnedContent.model_validate(
            {
                "inherited_components": [CORRECTED_CITATION],
                "falsifiable_prediction": FAKE_REASONING_OUTPUT["falsifiable_prediction"],
            }
        )
        with pytest.raises(Exception, match="source_id"):
            CausalStageOwnedContent.model_validate({"inherited_components": [MALFORMED_CITATION]})
        with pytest.raises(Exception, match="predicted"):
            CausalStageOwnedContent.model_validate(
                {"falsifiable_prediction": DEGENERATE_PREDICTION}
            )
