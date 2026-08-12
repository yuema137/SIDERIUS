"""C1 — static proposer pre-flight is ADVISORY ONLY (no blocking authority).

Contract (docs/design/runtime_estimation_and_calibration.md §23-C1,
operator-approved 2026-07-30, replacing the Fix 2 Commit 6 reject-revise
loop that caused the V19 wave-1 incident):

* an over-budget static estimate produces ONE proposing call — no
  revision request, no rejection text in any prompt, no
  ``PREFLIGHT_OVERBUDGET_EMITTED`` exhaustion path;
* the over-budget draft itself is emitted, carrying a LABELED advisory
  (``static_uncalibrated``, ``confidence=low``, ``blocking_eligible=no``,
  explicit "do not infer a parameter-count ceiling" language) in
  ``memo_consistency_notes``;
* ``preflight_factor`` / ``preflight_estimated_minutes`` remain
  populated for observability;
* skip paths (budget disabled, missing/non-positive parameter count)
  remain non-blocking and non-crashing;
* structural/schema retries are UNCHANGED — only runtime-estimate
  authority was removed.

Several tests here fail on the pre-C1 code by construction: pre-C1, an
over-budget draft triggered up to two revision calls and the revised
draft was emitted; post-C1 the first draft is emitted after exactly one
proposing call.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from agent.schemas.proposal import (
    ProposalInput,
    ReasoningPipelineConfig,
    ReasoningStage,
)
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from agent.schemas.task_config import ForwardContract
from nodes.ml_model_proposal_agent import (
    MLModelProposalAgent,
    _build_preflight_advisory_note,
)


# PR 01a: the commit-prompt render is FAIL-CLOSED on an empty contract
# (design rule 6.2-6); production always supplies one, so legacy-path
# fixtures declare it too. Hermetic (not loaded from configs/).
def _legacy_test_contract() -> ForwardContract:
    return ForwardContract(
        input_shape="[B, T] int64",
        input_description="per-timestep ADC class indices",
        output_shape="[B, 256, T] float32",
        output_description="per-timestep logits over 256 denoising classes",
        num_classes=256,
        task_type="classification",
    )


# ---------------------------------------------------------------------------
# Shared fixtures — minimal interpretation + canned stage outputs
# (harness carried over from the retired test_preflight_revision_loop.py)
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
    """Canned proposing-stage JSON. Defaults land well under a 20-min
    budget; overrides construct deliberately over-budget drafts."""
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
        forward_contract=_legacy_test_contract(),
        existing_model_types=["wavenet"],
        reasoning_pipeline=ReasoningPipelineConfig(
            stages=[
                ReasoningStage(
                    name="comparison",
                    system_prompt_key="COMPARATIVE_ANALYSIS",
                ),
                ReasoningStage(
                    name="causal_reasoning",
                    system_prompt_key="CAUSAL_REASONING",
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
        forward_contract=_legacy_test_contract(),
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
        provider="gemini",
        model_id="test",
        bridge_factory=lambda **kw: bridge,
    )


def _advisory_notes(output) -> list[str]:
    return [n for n in output.memo_consistency_notes if "PREFLIGHT_ADVISORY" in n]


# ---------------------------------------------------------------------------
# Pipeline mode — advisory path (regression: fails on pre-C1 blocking code)
# ---------------------------------------------------------------------------


class TestPipelineAdvisoryPath:
    def test_over_budget_draft_emitted_without_revision(self, tmp_path):
        """Pre-C1: the bad draft triggered a revision and FAKE_GOOD_DRAFT
        was emitted after 4 calls. Post-C1: the bad draft itself is emitted
        after exactly 3 calls (2 reasoning + 1 proposing)."""
        bridge = MagicMock()
        bridge.generate.side_effect = [
            FAKE_COMPARISON_OUTPUT,
            FAKE_REASONING_OUTPUT,
            FAKE_BAD_DRAFT,
            FAKE_GOOD_DRAFT,  # must never be consumed post-C1
        ]
        out = _agent(bridge).run(_pipeline_input(tmp_path))

        assert bridge.generate.call_count == 3
        assert out.parameter_count_estimate == 500_000_000
        assert out.preflight_factor is not None
        assert out.preflight_factor > 1.0

    def test_advisory_note_recorded_and_labeled(self, tmp_path):
        bridge = MagicMock()
        bridge.generate.side_effect = [
            FAKE_COMPARISON_OUTPUT,
            FAKE_REASONING_OUTPUT,
            FAKE_BAD_DRAFT,
        ]
        out = _agent(bridge).run(_pipeline_input(tmp_path))

        notes = _advisory_notes(out)
        assert len(notes) == 1
        note = notes[0]
        assert "static_uncalibrated" in note
        assert "confidence=low" in note
        assert "blocking_eligible=no" in note
        assert "Do not infer a parameter-count ceiling" in note
        assert "500,000,000" in note
        assert "20.0 min budget" in note
        joined = " ".join(out.memo_consistency_notes)
        assert "[PRE-FLIGHT REJECTION]" not in joined
        assert "PREFLIGHT_OVERBUDGET_EMITTED" not in joined

    def test_no_rejection_or_advisory_text_in_prompts(self, tmp_path):
        """Nothing pre-flight-related is ever injected into an LLM prompt
        in C1 (prompt labeling of advisory evidence is C2 scope)."""
        bridge = MagicMock()
        captured: list[str] = []
        responses = iter([FAKE_COMPARISON_OUTPUT, FAKE_REASONING_OUTPUT, FAKE_BAD_DRAFT])

        def capturing(system_prompt, user_prompt, **kw):
            captured.append(user_prompt)
            return next(responses)

        bridge.generate.side_effect = capturing
        _agent(bridge).run(_pipeline_input(tmp_path))

        assert len(captured) == 3
        for prompt in captured:
            assert "PRE-FLIGHT REJECTION" not in prompt
            assert "PREFLIGHT_ADVISORY" not in prompt

    def test_feasible_draft_behavior_unchanged(self, tmp_path):
        bridge = MagicMock()
        bridge.generate.side_effect = [
            FAKE_COMPARISON_OUTPUT,
            FAKE_REASONING_OUTPUT,
            FAKE_GOOD_DRAFT,
        ]
        out = _agent(bridge).run(_pipeline_input(tmp_path))

        assert bridge.generate.call_count == 3
        assert out.preflight_estimated_minutes is not None
        assert out.preflight_estimated_minutes > 0
        assert out.preflight_factor is not None
        assert 0 < out.preflight_factor <= 1.0
        assert _advisory_notes(out) == []


# ---------------------------------------------------------------------------
# Legacy mode — advisory path
# ---------------------------------------------------------------------------


class TestLegacyAdvisoryPath:
    def test_over_budget_draft_emitted_without_revision(self, tmp_path):
        """Pre-C1 legacy mode re-called commit with the rejection appended;
        post-C1 there is exactly one commit call and the draft is emitted."""
        bridge = MagicMock()
        bridge.generate_text.return_value = "reasoning text"
        bridge.generate.side_effect = [FAKE_BAD_DRAFT, FAKE_GOOD_DRAFT]
        out = _agent(bridge).run(_legacy_input(tmp_path))

        assert bridge.generate.call_count == 1
        assert out.parameter_count_estimate == 500_000_000
        assert len(_advisory_notes(out)) == 1

    def test_no_rejection_text_in_commit_prompt(self, tmp_path):
        bridge = MagicMock()
        bridge.generate_text.return_value = "reasoning text"
        captured: list[str] = []

        def capturing(system_prompt, user_prompt, **kw):
            captured.append(user_prompt)
            return FAKE_BAD_DRAFT

        bridge.generate.side_effect = capturing
        _agent(bridge).run(_legacy_input(tmp_path))

        (commit_prompt,) = captured
        assert "PRE-FLIGHT REJECTION" not in commit_prompt
        assert "PREFLIGHT_ADVISORY" not in commit_prompt


# ---------------------------------------------------------------------------
# Skip paths — unchanged, non-blocking, non-crashing
# ---------------------------------------------------------------------------


class TestSkipPaths:
    def test_trial_budget_none_skips_advisory(self, tmp_path):
        bridge = MagicMock()
        bridge.generate.side_effect = [
            FAKE_COMPARISON_OUTPUT,
            FAKE_REASONING_OUTPUT,
            FAKE_BAD_DRAFT,
        ]
        out = _agent(bridge).run(_pipeline_input(tmp_path, trial_budget=None))

        assert out.preflight_factor is None
        assert out.preflight_estimated_minutes is None
        assert _advisory_notes(out) == []

    def test_missing_parameter_count_adds_skip_note(self, tmp_path):
        bridge = MagicMock()
        bridge.generate.side_effect = [
            FAKE_COMPARISON_OUTPUT,
            FAKE_REASONING_OUTPUT,
            _proposing_output(num_params=None),
        ]
        out = _agent(bridge).run(_pipeline_input(tmp_path))

        assert any("PREFLIGHT_SKIPPED" in n for n in out.memo_consistency_notes)
        assert out.preflight_factor is None
        assert _advisory_notes(out) == []

    def test_zero_parameter_count_adds_skip_note(self, tmp_path):
        bridge = MagicMock()
        bridge.generate.side_effect = [
            FAKE_COMPARISON_OUTPUT,
            FAKE_REASONING_OUTPUT,
            _proposing_output(num_params=0),
        ]
        out = _agent(bridge).run(_pipeline_input(tmp_path))

        assert any("PREFLIGHT_SKIPPED" in n for n in out.memo_consistency_notes)
        assert out.preflight_factor is None


# ---------------------------------------------------------------------------
# Advisory note content
# ---------------------------------------------------------------------------


class TestAdvisoryNoteBlock:
    def test_contains_all_numbers_and_labels(self):
        note = _build_preflight_advisory_note(
            num_params=18_400_000,
            estimated_minutes=1692.8,
            factor=84.64,
            budget_minutes=20.0,
        )
        assert "18,400,000" in note
        assert "1692.8" in note
        assert "84.64x" in note
        assert "20.0 min budget" in note
        assert "static_uncalibrated" in note
        assert "confidence=low" in note
        assert "blocking_eligible=no" in note
        assert "Do not infer a parameter-count ceiling" in note

    def test_no_prescriptive_downsizing_language(self):
        """The old rejection block ordered the LLM to shrink the model —
        the advisory must not."""
        note = _build_preflight_advisory_note(
            num_params=18_400_000,
            estimated_minutes=1692.8,
            factor=84.64,
            budget_minutes=20.0,
        )
        for banned in (
            "simplify the architecture",
            "reduce parameter_count",
            "reduce depth/width",
            "lighter architectural class",
        ):
            assert banned not in note


# ---------------------------------------------------------------------------
# Structural retries — unchanged by C1
# ---------------------------------------------------------------------------


class TestStructuralRetriesUnchanged:
    def test_schema_retry_still_happens(self, tmp_path):
        """A structurally invalid draft (duplicate model name) still burns a
        structural-retry slot and the corrected draft is emitted — C1
        removed only runtime-estimate authority."""
        bridge = MagicMock()
        duplicate = _proposing_output(name="wavenet")  # exists → ValueError
        bridge.generate.side_effect = [
            FAKE_COMPARISON_OUTPUT,
            FAKE_REASONING_OUTPUT,
            duplicate,
            FAKE_GOOD_DRAFT,
        ]
        out = _agent(bridge).run(_pipeline_input(tmp_path))

        assert bridge.generate.call_count == 4  # 2 reasoning + 2 proposing
        assert out.model_name == "spectral_wavenet"
