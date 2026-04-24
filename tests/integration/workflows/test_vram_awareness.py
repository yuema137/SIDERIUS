"""B.5 — VRAM-Awareness end-to-end test (dual-mode, Tier 2).

Validates the full 5-Hop Wiring Plan landed by WS-B (B.1-B.4):

    VRAM skill -> tuner.physical_rejections -> orchestrator aggregation ->
    ProposalInput.previous_failures + hardware_context -> [PHYSICAL
    REJECTION] + [HARDWARE CONTEXT] blocks in the iter-2 Proposer prompt ->
    Proposer downsizes the architecture.

See docs/phase66_ws_b_proposer_hardening.md Section 5.3.

Choreography:
  Iter 1 - tuner returns a HyperparamTuningOutput with physical_rejections
           containing one oversized deep_punet attention config and
           best_denoising_score=None.
  Iter 2 - proposer runs. Pseudo mode asserts on the captured ProposalInput:
           previous_failures carries the [PHYSICAL REJECTION] string,
           hardware_context is plumbed, and the rendered reasoning prompt
           contains the [HARDWARE CONTEXT] block.
           Real mode additionally asserts the emitted ProposalOutput's
           baseline_config shrinks at least one dominant hyperparameter
           relative to iter-1's rejected config (behavioural trip-wire).

Run with:
  .venv/bin/pytest tests/integration/workflows/test_vram_awareness.py -v -s
  .venv/bin/pytest tests/integration/workflows/test_vram_awareness.py -v -s --real-llm
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from agent.schemas.hyperparam_tuning import (
    HyperparamTuningOutput,
    PhysicalRejection,
)
from core.hardware_context import HardwareContext
from workflows.llm_config import (
    NodeLLMConfig,
    ProposalLLMConfig,
    TunerLLMConfig,
    WorkflowLLMConfig,
)
from workflows.model_exploration import run_workflow

from tests.unit.workflows.test_model_exploration import (
    _make_implementor_output,
    _make_interpretation_output,
    _make_tuning_output,
    _make_validator_output,
    _write_tuning_output,
)


pytestmark = pytest.mark.dual_mode


# ---------------------------------------------------------------------------
# Stub hardware context - used in both modes so the [HARDWARE CONTEXT] block
# renders identically on CPU-only dev boxes and GPU hosts alike.
# ---------------------------------------------------------------------------

_STUB_TOTAL_BYTES = 32 * 1024 ** 3
_STUB_BUDGET_GB = 20.0  # < 0.80 * 32 = 25.6 GB cap -> BUDGET regime


def _stub_hardware_context() -> HardwareContext:
    return HardwareContext(
        device_name="stub-cuda-device",
        total_memory_bytes=_STUB_TOTAL_BYTES,
        compute_capability=(9, 0),
        multiprocessor_count=128,
        cuda_runtime_version="12.4",
        torch_version="2.5.1",
        hostname="test-host",
        device_available=True,
        discovered_at=datetime(2026, 4, 23, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# Iter-1 synthetic physical rejection - oversized deep_punet attention arch.
# The rejection ratio is 29.1 / 20.0 = 1.455 -> aggregator surfaces it as
# the sole worst offender.
# ---------------------------------------------------------------------------

_REJECTED_HIDDEN_DIM = 1024
_REJECTED_DEPTH = 9
_REJECTED_MODEL_TYPE = "deep_punet"
_REJECTED_DOMINANT_LAYER = "encoder.attention.block7.mha"


def _iter1_tuning_output_with_rejection() -> HyperparamTuningOutput:
    rej = PhysicalRejection(
        attempt_config={
            "model_type": _REJECTED_MODEL_TYPE,
            "batch_size": 16,
            "segmentation_size": 16384,
            "depth": _REJECTED_DEPTH,
            "hidden_dim": _REJECTED_HIDDEN_DIM,
        },
        binding_cap="vram",
        dominant_layer=_REJECTED_DOMINANT_LAYER,
        dominant_layer_gb=13.4,
        dominant_fraction=0.46,
        budget_gb=_STUB_BUDGET_GB,
        estimated_gb=29.1,
        suggestion=(
            "Attention head stack at hidden_dim=1024 is infeasible; drop "
            "hidden_dim to 512 or smaller, or reduce depth."
        ),
    )
    return HyperparamTuningOutput(
        run_name="iter_001_vram_b5",
        model_type=_REJECTED_MODEL_TYPE,
        file_index=0,
        status="failed",
        completed_rounds=0,
        total_attempts=1,
        best_exp_id=None,
        best_denoising_score=None,
        best_config=None,
        all_records=[],
        started_at="2026-04-23 12:00:00",
        finished_at="2026-04-23 12:05:00",
        physical_rejections=[rej],
    )


# ---------------------------------------------------------------------------
# Pseudo-mode canned bridge (3-stage pipeline: comparison + reasoning + proposing).
# One fresh MagicMock per iteration - the proposer's bridge_factory is called
# once per iteration by the workflow.
# ---------------------------------------------------------------------------

_FAKE_COMPARISON = {
    "comparisons": [],
    "proposed_vocab_links": [],
    "proposed_vocab_candidates": [],
    "sota_model_type": "punet",
    "sota_score": 1.5,
    "sota_mechanism": "baseline",
}
_FAKE_REASONING = {
    "proposed_change": (
        "Replace the depth-9 attention stack with a depth-4 dilated TCN."
    ),
    "causal_hypothesis": (
        "Iter-1 ran out of VRAM because attention at hidden_dim=1024 busted "
        "the budget. Shrinking the per-layer capacity keeps the model within "
        "the [HARDWARE CONTEXT] effective cap while preserving receptive field."
    ),
    "falsifiable_prediction": {
        "metric": "denoising_score",
        "current_value": 1.5,
        "predicted_value": 2.5,
        "threshold_for_refutation": 1.0,
        "rationale": "x",
    },
    "predicted_failure_modes": ["receptive field may be too small"],
    "inherited_components": [],
    "proposed_vocab_candidates": [],
}
def _make_fake_proposing(model_name: str) -> dict:
    return {
        "model_name": model_name,
        "model_description": "A depth-reduced TCN that fits in the effective cap.",
        "mathematical_definition": "[B, T] int64 -> [B, 256, T] float32",
        "motivation": "Respect the iter-1 VRAM rejection.",
        "expert_advice": {
            "focus_areas": [],
            "constraints": ["params<100M"],
            "known_failures": [],
            "suggested_directions": [],
            "rationale": "Within the effective cap.",
        },
        "baseline_config": {
            "model_config": {"hidden_dim": 256, "depth": 4},
            "train_config": {"batch_size": 4, "epochs": 10},
            "loss_config": {"loss_type": "focal"},
        },
        "memo_consistency_notes": [],
    }


def _make_canned_bridge_factory(model_name: str):
    """Each iteration gets a unique model_name so the workflow's
    duplicate-arch guard does not reject iter 2 (which would prevent
    the emitted_proposals capture the real-mode branch relies on)."""
    def _factory(**kwargs):
        bridge = MagicMock()
        # Pad the proposing stage so the internal pre-flight/structural
        # retry loop does not StopIteration the side_effect iterable.
        bridge.generate.side_effect = [
            _FAKE_COMPARISON,
            _FAKE_REASONING,
            _make_fake_proposing(model_name),
            _make_fake_proposing(model_name),
            _make_fake_proposing(model_name),
        ]
        return bridge
    return _factory


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

def test_vram_awareness_e2e_physical_rejection_reaches_iter2_proposer(
    tmp_path, request, capsys
):
    """End-to-end: iter-1's physical_rejection must reach iter-2's Proposer
    as a [PHYSICAL REJECTION] string inside previous_failures, the
    hardware_context must be plumbed, and the rendered reasoning prompt
    must carry the [HARDWARE CONTEXT] block. Real mode additionally
    asserts behavioural downsizing."""
    from tests.conftest import _is_real_llm

    real_mode = _is_real_llm(request)
    if real_mode and not os.getenv("OPENAI_API_KEY"):
        pytest.skip("--real-llm requires OPENAI_API_KEY for B.5")

    # Seed the workspace so the workflow bootstraps iteration 1.
    _write_tuning_output(tmp_path, "punet", run="v1", score=1.5)

    workspace = str(tmp_path / "workflow_output")
    data_dir = str(tmp_path / "data")
    run_name = "b5_vram_awareness"

    iter1_tune = _iter1_tuning_output_with_rejection()
    iter2_tune = _make_tuning_output(model_type="shrunk_tcn_iter2", score=1.7)

    # Capture the ProposalInput passed into the real proposer on every
    # iteration, plus every emitted ProposalOutput.
    captured_inputs: list = []
    emitted_proposals: list = []
    iter_counter = [0]

    from nodes.ml_model_proposal_agent import MLModelProposalAgent as _RealProposer

    class _CapturingProposer(_RealProposer):
        def run(self, inp, *args, **kwargs):
            captured_inputs.append(inp)
            out = super().run(inp, *args, **kwargs)
            emitted_proposals.append(out)
            return out

    def _proposer_ctor(**kwargs):
        iter_counter[0] += 1
        if not real_mode:
            kwargs["bridge_factory"] = _make_canned_bridge_factory(
                f"b5_arch_iter{iter_counter[0]}"
            )
        return _CapturingProposer(**kwargs)

    with patch(
        "workflows.model_exploration.get_or_create_hardware_context",
        return_value=_stub_hardware_context(),
    ), \
         patch("workflows.model_exploration.ResultInterpretationAgent") as MockInterp, \
         patch("workflows.model_exploration.MLModelImplementor") as MockImpl, \
         patch("workflows.model_exploration.MLCodeValidatorAgent") as MockValid, \
         patch("workflows.model_exploration.HyperparamTuningAgent") as MockTune, \
         patch("workflows.model_exploration.MLModelProposalAgent") as MockPropose:

        MockInterp.return_value.run.return_value = _make_interpretation_output()
        MockImpl.return_value.run.return_value = _make_implementor_output()
        MockValid.return_value.run.return_value = _make_validator_output(passed=True)
        MockTune.return_value.run.side_effect = [iter1_tune, iter2_tune]
        MockPropose.side_effect = _proposer_ctor

        # In pseudo mode the bridge is canned, so the provider/model fields
        # are placeholders. In real mode they must be real OpenAI IDs.
        propose_cfg = (
            ProposalLLMConfig(
                comparison=NodeLLMConfig(provider="openai", model_id="gpt-4o-mini"),
                reasoning=NodeLLMConfig(provider="openai", model_id="gpt-4o-mini"),
                proposing=NodeLLMConfig(provider="openai", model_id="gpt-4o-mini"),
            )
            if real_mode
            else ProposalLLMConfig()
        )
        llm_config = WorkflowLLMConfig(
            interpret=NodeLLMConfig(provider="openai", model_id="gpt-4o-mini"),
            propose=propose_cfg,
            implement=NodeLLMConfig(provider="openai", model_id="gpt-4o-mini"),
            validate_model=NodeLLMConfig(provider="openai", model_id="gpt-4o-mini"),
            tune=TunerLLMConfig(
                planner=NodeLLMConfig(provider="openai", model_id="gpt-5-mini"),
                reflector=NodeLLMConfig(provider="openai", model_id="gpt-5-mini"),
            ),
        )

        run_workflow(
            data_dir=data_dir,
            model_types=["punet"],
            source_run_name="v1",
            workspace=workspace,
            run_name=run_name,
            llm_config=llm_config,
            max_iterations=2,
            trial_vram_budget_gb=_STUB_BUDGET_GB,
            debug_dump_prompts=True,
        )

    # ------------------------------------------------------------------
    # Layer 1 - captured iter-2 ProposalInput
    # ------------------------------------------------------------------
    assert len(captured_inputs) >= 2, (
        f"Expected >=2 proposer invocations (iter 1 + iter 2); "
        f"got {len(captured_inputs)}."
    )
    iter2_input = captured_inputs[1]

    # (1) previous_failures carries exactly one [PHYSICAL REJECTION]
    rejection_strings = [
        s for s in iter2_input.previous_failures if "[PHYSICAL REJECTION]" in s
    ]
    assert len(rejection_strings) == 1, (
        f"Expected exactly 1 [PHYSICAL REJECTION] string in iter-2 "
        f"previous_failures; got {len(rejection_strings)}. "
        f"Full list: {iter2_input.previous_failures!r}"
    )
    rej_str = rejection_strings[0]
    assert _REJECTED_MODEL_TYPE in rej_str, (
        f"Rejection string must cite iter-1 arch {_REJECTED_MODEL_TYPE!r}; "
        f"got: {rej_str!r}"
    )
    assert _REJECTED_DOMINANT_LAYER in rej_str, (
        f"Rejection string must cite the dominant attention layer "
        f"{_REJECTED_DOMINANT_LAYER!r}; got: {rej_str!r}"
    )
    assert "29.10 GB" in rej_str, (
        f"Rejection string must cite the 29.10 GB overshoot; got: {rej_str!r}"
    )

    # (2) hardware_context is plumbed with device_available=True and the
    #     budget is the one the orchestrator forwarded.
    assert iter2_input.hardware_context is not None, (
        "Iter-2 ProposalInput.hardware_context must be populated "
        "(orchestrator called get_or_create)."
    )
    assert iter2_input.hardware_context.device_available is True
    assert iter2_input.vram_budget_gb == pytest.approx(_STUB_BUDGET_GB)

    # ------------------------------------------------------------------
    # Layer 2 - rendered reasoning prompt carries [HARDWARE CONTEXT] + the
    # [PHYSICAL REJECTION] block (belt-and-braces: string flow + render).
    # ------------------------------------------------------------------
    from nodes.ml_model_proposal_agent import _build_reasoning_prompt
    rendered = _build_reasoning_prompt(iter2_input)
    assert "[HARDWARE CONTEXT]" in rendered, (
        "Iter-2 reasoning prompt must carry a [HARDWARE CONTEXT] block. "
        f"Prompt tail:\n{rendered[-2000:]}"
    )
    assert "BUDGET" in rendered, (
        "Regime line should read BUDGET (budget=20 GB < usable_cap=25.6 GB)."
    )
    assert "[PHYSICAL REJECTION]" in rendered, (
        "Iter-2 reasoning prompt must surface the [PHYSICAL REJECTION] block "
        "inside the Previous Failed Proposals section."
    )

    # ------------------------------------------------------------------
    # Layer 3 - Real-mode behavioural trip-wire. One LLM sample is
    # probabilistic; the assertion passes if either dominant hyperparameter
    # strictly decreases. Failure here means the Proposer is not listening
    # to the rejection block.
    # ------------------------------------------------------------------
    if real_mode:
        assert len(emitted_proposals) >= 2, (
            f"Real-mode: expected >=2 emitted proposals; "
            f"got {len(emitted_proposals)}."
        )
        iter2_proposal = emitted_proposals[1]
        model_cfg = iter2_proposal.baseline_config.get("model_config", {})
        iter2_hidden = model_cfg.get("hidden_dim")
        iter2_depth = model_cfg.get("depth")

        hidden_ok = (
            iter2_hidden is not None and iter2_hidden < _REJECTED_HIDDEN_DIM
        )
        depth_ok = iter2_depth is not None and iter2_depth < _REJECTED_DEPTH
        shrunk = hidden_ok or depth_ok

        # Surface the reasoning snippet unconditionally so the human
        # reviewer can see the Proposer explicitly reacting to the
        # rejection - the audit requirement of directive Step 4.
        with capsys.disabled():
            print("\n" + "=" * 72)
            print("B.5 - ITER-2 REASONING SNIPPET (real-mode)")
            print("=" * 72)
            print(f"model_name:        {iter2_proposal.model_name}")
            print(f"proposed_change:   {iter2_proposal.proposed_change}")
            print("-" * 72)
            print(f"causal_hypothesis: {iter2_proposal.causal_hypothesis}")
            print("-" * 72)
            print(f"motivation:        {iter2_proposal.motivation}")
            print("-" * 72)
            print(f"baseline model_config: {model_cfg}")
            print(
                f"iter-1 rejected:   hidden_dim={_REJECTED_HIDDEN_DIM} "
                f"depth={_REJECTED_DEPTH} (arch={_REJECTED_MODEL_TYPE})"
            )
            print(
                f"iter-2 emitted:    hidden_dim={iter2_hidden} "
                f"depth={iter2_depth}"
            )
            print(f"shrunk (either knob): {shrunk}")
            print("=" * 72)

        assert shrunk, (
            f"Real-mode behavioural assertion failed: iter-2 did not shrink "
            f"either hidden_dim (iter-1 {_REJECTED_HIDDEN_DIM} -> iter-2 "
            f"{iter2_hidden}) or depth (iter-1 {_REJECTED_DEPTH} -> iter-2 "
            f"{iter2_depth}). The Proposer is ignoring [PHYSICAL REJECTION].\n"
            f"  proposed_change:   {iter2_proposal.proposed_change!r}\n"
            f"  causal_hypothesis: {iter2_proposal.causal_hypothesis!r}"
        )
