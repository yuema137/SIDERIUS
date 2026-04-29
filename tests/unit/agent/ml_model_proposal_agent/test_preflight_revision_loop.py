"""Fix 2 Commit 6 — pre-flight revision loop integration tests.

Covers the outer pre-flight loop wired into both ``_run_legacy`` and
``_run_pipeline``:

* Success path: one over-budget draft → one feasible revision → feasible
  draft emitted with ``preflight_factor <= 1.0``.
* Exhaustion path: three over-budget drafts → lowest-factor candidate
  emitted with ``PREFLIGHT_OVERBUDGET_EMITTED`` memo note. Stages 1+2 are
  called exactly once each regardless of pre-flight attempt count.
* Skip paths: ``trial_time_budget_minutes=None`` disables the gate
  entirely; LLM-omitted ``parameter_count_estimate`` produces a
  ``PREFLIGHT_SKIPPED`` audit note without triggering revisions.
* Prescriptive rejection block: contains all four numeric substitutions
  (``num_params``, ``estimated_minutes``, ``factor``, ``budget``) plus a
  concrete remediation suggestion.
* Audit-field propagation: ``preflight_estimated_minutes`` +
  ``preflight_factor`` survive into the emitted ``ProposalOutput``.

See docs/reliable_resource_proposer.md §9 Commit 6.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

from ._prompt_utils import extract_accumulated_json

from agent.schemas.proposal import (
    ProposalInput,
    ReasoningPipelineConfig,
    ReasoningStage,
)
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from nodes.ml_model_proposal_agent import (
    _MAX_PREFLIGHT_ATTEMPTS,
    MLModelProposalAgent,
    _build_preflight_rejection_block,
)


# ---------------------------------------------------------------------------
# Shared fixtures — minimal interpretation + canned stage outputs
# ---------------------------------------------------------------------------


FAKE_INTERPRETATION = {
    "model_types": ["wavenet"],
    "total_experiments": 1,
    "per_model_best": {"wavenet": 5.5},
    "per_model_worst": {"wavenet": 3.0},
    "best_denoising_score": 5.5,
    "worst_denoising_score": 3.0,
    "key_findings": ["wavenet scores well"],
    "bottlenecks": ["low-freq coverage"],
    "take_home_message": "Wavenet wins; low-freq gap remains.",
    "model_descriptions": {"wavenet": "Dilated causal conv."},
    "model_knowledge_cache": {
        "wavenet": {
            "key_findings": ["Wide receptive field"],
            "bottlenecks": ["Misses low-freq"],
            "score_trend": "Steady up",
            "strategy_assessment": "Room for spectral",
            "_stats": {"best_denoising_score": 5.5},
        },
    },
}


FAKE_COMPARISON_OUTPUT = {
    "comparisons": [
        {
            "model_type": "wavenet",
            "source": "seed",
            "best_score": 5.5,
            "key_mechanism": "Dilated causal conv.",
            "strengths": ["high-freq"],
            "weaknesses": ["low-freq"],
            "lesson_for_next_proposal": "Add spectral path.",
        }
    ],
    "proposed_vocab_links": [],
    "proposed_vocab_candidates": [],
    "sota_model_type": "wavenet",
    "sota_score": 5.5,
    "sota_mechanism": "dilated",
}


FAKE_REASONING_OUTPUT = {
    "proposed_change": "Add FFT branch.",
    "causal_hypothesis": "Low-freq gap from missing spectral path.",
    "falsifiable_prediction": {
        "metric": "denoising_score",
        "current_value": 5.5,
        "predicted_value": 6.5,
        "threshold_for_refutation": 5.0,
        "rationale": "Spectral lifts low-freq.",
    },
    "predicted_failure_modes": ["FFT may exceed VRAM."],
    "inherited_components": [],
}


def _proposing_output(
    *,
    name: str = "spectral_wavenet",
    num_params: int | None = 500_000,
    epochs: int = 2,
    seg: int = 40_000,
) -> dict:
    """Canned proposing-stage JSON with a production-realistic baseline.

    Default values land the static-formula factor well below 1.0 at a
    20-min budget; callers override ``num_params`` + ``epochs`` to construct
    deliberately over-budget drafts without having to second-guess the
    formula internals.
    """
    return {
        "model_name": name,
        "model_description": "WaveNet + spectral branch.",
        "mathematical_definition": "Dilated causal conv + FFT mixer.",
        "motivation": (
            "Addresses the low-freq gap per the DiscoveryMemo. "
            "Tethered to proposed_change and causal_hypothesis."
        ),
        "expert_advice": {
            "focus_areas": ["low-freq recovery"],
            "constraints": ["VRAM < 10 GB", "params < 10M"],
            "known_failures": [],
            "suggested_directions": ["start with depth=2"],
            "rationale": "Conservative baseline for the first sweep.",
        },
        "baseline_config": {
            "model_config": {
                "segmentation_size": seg,
                "num_blocks": 6,
                "kernel_size": 3,
            },
            "train_config": {
                "lr": 1e-4,
                "epochs": epochs,
                "batch_size": 1,
                "optimizer_type": "adamw",
                "weight_decay": 1e-5,
                "device": "cuda",
            },
            "loss_config": {
                "loss_type": "focal",
                "alpha": 0.5,
                "gamma": 2.0,
                "reduction": "mean",
            },
        },
        "parameter_count_estimate": num_params,
        "memo_consistency_notes": [],
    }


FAKE_GOOD_DRAFT = _proposing_output(num_params=50_000, epochs=2)
FAKE_BAD_DRAFT = _proposing_output(num_params=500_000_000, epochs=10)


def _pipeline_input(
    tmp_path,
    *,
    is_trial: bool = True,
    trial_budget: float | None = 20.0,
    formal_budget: float | None = None,
) -> ProposalInput:
    return ProposalInput(
        interpretation=FAKE_INTERPRETATION,
        existing_model_types=["wavenet"],
        reasoning_pipeline=ReasoningPipelineConfig(
            stages=[
                ReasoningStage(
                    name="comparison", system_prompt_key="COMPARATIVE_ANALYSIS",
                ),
                ReasoningStage(
                    name="causal_reasoning", system_prompt_key="CAUSAL_REASONING",
                ),
            ],
        ),
        is_trial=is_trial,
        trial_time_budget_minutes=trial_budget,
        formal_time_budget_minutes=formal_budget,
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="test"),
        ),
    )


def _legacy_input(
    tmp_path,
    *,
    is_trial: bool = True,
    trial_budget: float | None = 20.0,
    formal_budget: float | None = None,
) -> ProposalInput:
    return ProposalInput(
        interpretation=FAKE_INTERPRETATION,
        existing_model_types=["wavenet"],
        is_trial=is_trial,
        trial_time_budget_minutes=trial_budget,
        formal_time_budget_minutes=formal_budget,
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="test"),
        ),
    )


def _agent(bridge: MagicMock) -> MLModelProposalAgent:
    return MLModelProposalAgent(
        provider="gemini", model_id="test",
        bridge_factory=lambda **kw: bridge,
    )


# ---------------------------------------------------------------------------
# Pipeline mode — success path
# ---------------------------------------------------------------------------


class TestPipelineSuccessPath:
    """Bad draft triggers one revision, second draft passes the gate."""

    def test_revised_draft_emitted(self, tmp_path):
        bridge = MagicMock()
        bridge.generate.side_effect = [
            FAKE_COMPARISON_OUTPUT,
            FAKE_REASONING_OUTPUT,
            FAKE_BAD_DRAFT,
            FAKE_GOOD_DRAFT,
        ]
        out = _agent(bridge).run(_pipeline_input(tmp_path))

        assert out.parameter_count_estimate == 50_000
        assert out.preflight_factor is not None
        assert out.preflight_factor <= 1.0

    def test_audit_fields_populated_on_first_try_pass(self, tmp_path):
        bridge = MagicMock()
        bridge.generate.side_effect = [
            FAKE_COMPARISON_OUTPUT,
            FAKE_REASONING_OUTPUT,
            FAKE_GOOD_DRAFT,
        ]
        out = _agent(bridge).run(_pipeline_input(tmp_path))

        assert out.preflight_estimated_minutes is not None
        assert out.preflight_estimated_minutes > 0
        assert out.preflight_factor is not None
        assert out.preflight_factor > 0
        # Only 3 LLM calls: 2 reasoning + 1 proposing.
        assert bridge.generate.call_count == 3

    def test_rejection_injected_into_proposing_errors(self, tmp_path):
        """The revision prompt must carry the prescriptive rejection block."""
        bridge = MagicMock()
        captured: list[str] = []
        responses = iter([
            FAKE_COMPARISON_OUTPUT,
            FAKE_REASONING_OUTPUT,
            FAKE_BAD_DRAFT,
            FAKE_GOOD_DRAFT,
        ])

        def capturing(system_prompt, user_prompt, **kw):
            captured.append(user_prompt)
            return next(responses)

        bridge.generate.side_effect = capturing
        _agent(bridge).run(_pipeline_input(tmp_path))

        revision_prompt = captured[3]
        revision_data = extract_accumulated_json(revision_prompt)
        errors = revision_data.get("proposing_stage_errors", [])
        assert any("[PRE-FLIGHT REJECTION]" in e for e in errors)
        rejection = next(e for e in errors if "[PRE-FLIGHT REJECTION]" in e)
        assert "500,000,000" in rejection
        assert "20.0 min budget" in rejection

    def test_stages_1_and_2_not_rerun_on_preflight_revision(self, tmp_path):
        bridge = MagicMock()
        bridge.generate.side_effect = [
            FAKE_COMPARISON_OUTPUT,
            FAKE_REASONING_OUTPUT,
            FAKE_BAD_DRAFT,
            FAKE_GOOD_DRAFT,
        ]
        _agent(bridge).run(_pipeline_input(tmp_path))
        # 2 reasoning + 2 proposing = 4
        assert bridge.generate.call_count == 4


# ---------------------------------------------------------------------------
# Pipeline mode — exhaustion path
# ---------------------------------------------------------------------------


class TestPipelineExhaustionPath:
    """Three consecutive over-budget drafts → emit best-factor candidate."""

    def test_emits_best_factor_candidate(self, tmp_path):
        drafts = [
            _proposing_output(num_params=1_000_000_000, epochs=10),  # worst
            _proposing_output(num_params=500_000_000,   epochs=10),
            _proposing_output(num_params=100_000_000,   epochs=10),  # best
        ]
        bridge = MagicMock()
        bridge.generate.side_effect = [
            FAKE_COMPARISON_OUTPUT,
            FAKE_REASONING_OUTPUT,
            *drafts,
        ]
        out = _agent(bridge).run(_pipeline_input(tmp_path))

        assert out.parameter_count_estimate == 100_000_000
        assert any(
            "PREFLIGHT_OVERBUDGET_EMITTED" in n
            for n in out.memo_consistency_notes
        )

    def test_call_count_equals_reasoning_plus_max_attempts(self, tmp_path):
        drafts = [
            _proposing_output(num_params=500_000_000, epochs=10)
            for _ in range(_MAX_PREFLIGHT_ATTEMPTS)
        ]
        bridge = MagicMock()
        bridge.generate.side_effect = [
            FAKE_COMPARISON_OUTPUT,
            FAKE_REASONING_OUTPUT,
            *drafts,
        ]
        _agent(bridge).run(_pipeline_input(tmp_path))
        # 2 reasoning + 3 proposing (one per pre-flight attempt)
        assert bridge.generate.call_count == 2 + _MAX_PREFLIGHT_ATTEMPTS

    def test_overbudget_note_names_best_factor(self, tmp_path):
        """The emitted warning must identify the winning factor explicitly."""
        drafts = [
            _proposing_output(num_params=1_000_000_000, epochs=10),
            _proposing_output(num_params=500_000_000,   epochs=10),
            _proposing_output(num_params=100_000_000,   epochs=10),
        ]
        bridge = MagicMock()
        bridge.generate.side_effect = [
            FAKE_COMPARISON_OUTPUT,
            FAKE_REASONING_OUTPUT,
            *drafts,
        ]
        out = _agent(bridge).run(_pipeline_input(tmp_path))

        note = next(
            n for n in out.memo_consistency_notes
            if "PREFLIGHT_OVERBUDGET_EMITTED" in n
        )
        assert "factor=" in note
        assert "20.0 min budget" in note


# ---------------------------------------------------------------------------
# Skip conditions — budget disabled OR num_params missing
# ---------------------------------------------------------------------------


class TestPreflightSkipped:

    def test_trial_budget_none_skips_gate(self, tmp_path):
        """trial_time_budget_minutes=None → pre-flight disabled entirely."""
        bridge = MagicMock()
        bridge.generate.side_effect = [
            FAKE_COMPARISON_OUTPUT,
            FAKE_REASONING_OUTPUT,
            FAKE_BAD_DRAFT,  # would be rejected if gate were active
        ]
        out = _agent(bridge).run(
            _pipeline_input(tmp_path, trial_budget=None),
        )
        assert out.preflight_estimated_minutes is None
        assert out.preflight_factor is None
        assert bridge.generate.call_count == 3  # no revision

    def test_formal_budget_none_skips_gate(self, tmp_path):
        """is_trial=False + formal_budget=None → gate skipped."""
        bridge = MagicMock()
        bridge.generate.side_effect = [
            FAKE_COMPARISON_OUTPUT,
            FAKE_REASONING_OUTPUT,
            FAKE_BAD_DRAFT,
        ]
        out = _agent(bridge).run(_pipeline_input(
            tmp_path, is_trial=False, trial_budget=20.0, formal_budget=None,
        ))
        assert out.preflight_factor is None
        assert bridge.generate.call_count == 3

    def test_missing_parameter_count_adds_skip_note(self, tmp_path):
        draft = _proposing_output(num_params=None)
        bridge = MagicMock()
        bridge.generate.side_effect = [
            FAKE_COMPARISON_OUTPUT,
            FAKE_REASONING_OUTPUT,
            draft,
        ]
        out = _agent(bridge).run(_pipeline_input(tmp_path))

        assert out.parameter_count_estimate is None
        assert out.preflight_factor is None
        assert any(
            "PREFLIGHT_SKIPPED" in n for n in out.memo_consistency_notes
        )
        # No revision loop: single proposing call.
        assert bridge.generate.call_count == 3

    def test_zero_parameter_count_adds_skip_note(self, tmp_path):
        draft = _proposing_output(num_params=0)
        bridge = MagicMock()
        bridge.generate.side_effect = [
            FAKE_COMPARISON_OUTPUT,
            FAKE_REASONING_OUTPUT,
            draft,
        ]
        out = _agent(bridge).run(_pipeline_input(tmp_path))
        assert any(
            "PREFLIGHT_SKIPPED" in n for n in out.memo_consistency_notes
        )

    def test_negative_parameter_count_adds_skip_note(self, tmp_path):
        draft = _proposing_output(num_params=-1)
        bridge = MagicMock()
        bridge.generate.side_effect = [
            FAKE_COMPARISON_OUTPUT,
            FAKE_REASONING_OUTPUT,
            draft,
        ]
        out = _agent(bridge).run(_pipeline_input(tmp_path))
        assert any(
            "PREFLIGHT_SKIPPED" in n for n in out.memo_consistency_notes
        )


# ---------------------------------------------------------------------------
# Rejection block shape
# ---------------------------------------------------------------------------


class TestRejectionBlock:

    def test_contains_all_prescriptive_numbers(self):
        block = _build_preflight_rejection_block(
            num_params=10_000_000,
            estimated_minutes=200.0,
            factor=10.0,
            budget_minutes=20.0,
        )
        assert "[PRE-FLIGHT REJECTION]" in block
        assert "10,000,000" in block       # num_params (thousands separator)
        assert "200.0 min" in block        # estimated_minutes
        assert "10.0x" in block            # factor multiplier
        assert "20.0 min budget" in block  # budget

    def test_contains_prescriptive_remediation(self):
        block = _build_preflight_rejection_block(
            num_params=1_000_000,
            estimated_minutes=50.0,
            factor=2.5,
            budget_minutes=20.0,
        )
        # Tell the LLM concretely what to change, not just "it's too slow".
        assert "parameter_count_estimate" in block
        assert any(tag in block for tag in ("TCN", "FFT", "windowed"))


# ---------------------------------------------------------------------------
# Legacy mode (2-call pattern)
# ---------------------------------------------------------------------------


class TestLegacyMode:

    def test_legacy_revises_on_preflight_rejection(self, tmp_path):
        bridge = MagicMock()
        bridge.generate_text.return_value = "reasoning text"
        bridge.generate.side_effect = [FAKE_BAD_DRAFT, FAKE_GOOD_DRAFT]

        out = _agent(bridge).run(_legacy_input(tmp_path))

        assert out.parameter_count_estimate == 50_000
        assert out.preflight_factor is not None
        assert out.preflight_factor <= 1.0
        assert bridge.generate_text.call_count == 1
        assert bridge.generate.call_count == 2

    def test_legacy_rejection_appended_to_commit_prompt(self, tmp_path):
        bridge = MagicMock()
        bridge.generate_text.return_value = "reasoning text"
        captured: list[str] = []
        responses = iter([FAKE_BAD_DRAFT, FAKE_GOOD_DRAFT])

        def capturing(system_prompt, user_prompt, **kw):
            captured.append(user_prompt)
            return next(responses)

        bridge.generate.side_effect = capturing
        _agent(bridge).run(_legacy_input(tmp_path))

        assert "[PRE-FLIGHT REJECTION]" not in captured[0]
        assert "[PRE-FLIGHT REJECTION]" in captured[1]

    def test_legacy_budget_none_skips_preflight(self, tmp_path):
        bridge = MagicMock()
        bridge.generate_text.return_value = "reasoning text"
        bridge.generate.return_value = FAKE_BAD_DRAFT  # would be rejected

        out = _agent(bridge).run(
            _legacy_input(tmp_path, trial_budget=None),
        )
        assert out.preflight_factor is None
        assert bridge.generate.call_count == 1

    def test_legacy_exhaustion_emits_best_factor(self, tmp_path):
        bridge = MagicMock()
        bridge.generate_text.return_value = "reasoning text"
        bridge.generate.side_effect = [
            _proposing_output(num_params=1_000_000_000, epochs=10),
            _proposing_output(num_params=500_000_000,   epochs=10),
            _proposing_output(num_params=100_000_000,   epochs=10),
        ]

        out = _agent(bridge).run(_legacy_input(tmp_path))

        assert out.parameter_count_estimate == 100_000_000
        assert any(
            "PREFLIGHT_OVERBUDGET_EMITTED" in n
            for n in out.memo_consistency_notes
        )
        assert bridge.generate.call_count == _MAX_PREFLIGHT_ATTEMPTS
