"""B.5 — VRAM-Awareness end-to-end test (dual-mode, Tier 2).

Validates the full 5-Hop Wiring Plan landed by WS-B (B.1-B.4):

    VRAM skill -> tuner.physical_rejections -> orchestrator aggregation ->
    ProposalInput.previous_failures + hardware_context -> [PHYSICAL
    REJECTION] + [HARDWARE CONTEXT] blocks in the iter-2 Proposer prompt ->
    Proposer downsizes the architecture.

See docs/phase66_ws_b_proposer_hardening.md Section 5.3.

Parametrization (§5.3.1): the test runs once per budget in
``_BUDGETS_GB = (10.0, 20.0)`` so the Proposer must adapt architecture
complexity to the effective cap. Iter-1's seeded architecture overshoots
both budgets; the behavioural divergence shows up in the iter-2 emitted
baseline.

Tiered time budgets (§5.3.2): ``trial_time_budget_minutes=2.0`` and
``formal_time_budget_minutes=20.0`` flow through the workflow on every run.
Phase A does not consume wall-time (tuner mocked) but the kwargs reach the
planner's context in both phases.

Two-phase execution (§5.3.3):
    * Phase A (pseudo by default, ``--real-llm``): real LLM, mocked tuner.
      Verifies the LLM reads the rejection + hardware context and shrinks
      the dominant hyperparameter.
    * Phase B (``--real-llm --real-training`` on lilab only): real LLM, real
      tuner. Additionally asserts iter-2 reaches ``status='succeeded'``,
      proving the baseline fit in VRAM on the physical device.

Run with:
  .venv/bin/pytest tests/integration/workflows/test_vram_awareness.py -v -s
  .venv/bin/pytest tests/integration/workflows/test_vram_awareness.py -v -s --real-llm
  .venv/bin/pytest tests/integration/workflows/test_vram_awareness.py -v -s --real-llm --real-training
"""

from __future__ import annotations

import os
import re
from contextlib import ExitStack
from datetime import UTC, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.schemas.hyperparam_tuning import (
    HyperparamTuningOutput,
    PhysicalRejection,
)
from core.hardware_context import HardwareContext
from tests.unit.workflows.test_model_exploration import (
    _make_implementor_output,
    _make_interpretation_output,
    _make_tuning_output,
    _make_validator_output,
    _write_tuning_output,
)
from workflows.llm_config import (
    NodeLLMConfig,
    ProposalLLMConfig,
    TunerLLMConfig,
    WorkflowLLMConfig,
)
from workflows.model_exploration import run_workflow
from workflows.run_config import WorkflowLaunchConfig

pytestmark = pytest.mark.dual_mode


# ---------------------------------------------------------------------------
# Stub hardware context - used in both modes so the [HARDWARE CONTEXT] block
# renders identically on CPU-only dev boxes and GPU hosts alike.
# ---------------------------------------------------------------------------

_STUB_TOTAL_BYTES = 32 * 1024**3
# §5.3.1 multi-config stress. Phase A covers 10 + 20 GB against the stubbed
# 32 GB device (both below the 0.80 * 32 = 25.6 GB physical cap → BUDGET
# regime). Phase B (v9) runs **0.5 GB only** against the real RTX 5090 — a
# floor below which the model parameter footprint alone (gradients +
# optimizer state included) exceeds the cap, so the planner cannot escape
# the VRAM wall by shrinking trial_portion. v8 evidence (§5.3.8) showed the
# 1.5 GB cap was satisfied incidentally whenever the trial slice shrank to
# pass the TIME gate; v9 lifts the trial time budget to 60 min so TIME
# stops absorbing pressure that should land on VRAM.
_BUDGETS_GB: tuple[float, ...] = (10.0, 20.0, 0.5)
_PHASE_A_BUDGETS_GB: frozenset[float] = frozenset({10.0, 20.0})
_PHASE_B_BUDGETS_GB: frozenset[float] = frozenset({0.5})

# §5.3.2 tiered time budgets. Phase A (mocked tuner) threads them through
# for prompt-context parity; Phase B v9 raises the trial cap to 60 min so
# the TIME gate cannot intercept the OOM signal — VRAM becomes the only
# remaining wall.
_TRIAL_TIME_BUDGET_MIN = 2.0
_FORMAL_TIME_BUDGET_MIN = 120.0
_PHASE_B_TRIAL_TIME_BUDGET_MIN = 60.0

# Real TIDMAD dataset root on lilab (verified 2026-04-24: 862 GB of
# abra_science_*.h5). Consumed by Phase B only.
_TIDMAD_DATA_DIR = "/home/klz/Data/TIDMAD"

# Phase B v9 — iter-1 over-architect advice to force a real OOM at the
# 0.5 GB cap. Routed via run_workflow's `human_advice_propose`, then scrubbed
# from iter-2's ProposalInput inside _CapturingProposer so the advice cannot
# fight the MANDATORY rejection-acknowledgement clause on the second pass.
_PHASE_B_PROPOSE_ADVICE = (
    "MANDATORY: You must propose a high-capacity architecture (e.g., "
    "deep_punet with hidden_dim=1024). Do NOT optimize for memory "
    "efficiency in Iteration 1. We are intentionally stress-testing the "
    "hardware boundary to verify failure-handling logic."
)


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
        discovered_at=datetime(2026, 4, 23, tzinfo=UTC),
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

# §5.3.5 parameter-count behavioural assertion. Round upper bound on a
# 1024-hidden x 9-deep attention stack at seg_size=16384 — kept as a
# round constant so the test is immune to Implementor-side estimator drift.
_REJECTED_PARAM_COUNT_ESTIMATE = 100_000_000
_ITER2_PARAM_CEILING_FRAC = 0.50  # iter-2 must be < 50% of rejected scale

# §5.3.6 text-level audit — at least one VRAM-family keyword must appear in
# iter-2's causal_hypothesis. Keyword hits are case-insensitive.
_REJECTION_ACK_KEYWORDS: tuple[str, ...] = (
    "vram",
    "oom",
    "rejection",
    "cap",
    "overshoot",
    "budget",
    _REJECTED_MODEL_TYPE,  # literal citation of the rejected arch
)


def _iter1_tuning_output_with_rejection(budget_gb: float) -> HyperparamTuningOutput:
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
        budget_gb=budget_gb,
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
    "proposed_change": ("Replace the depth-9 attention stack with a depth-4 dilated TCN."),
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


@pytest.mark.parametrize("vram_budget_gb", _BUDGETS_GB)
def test_vram_awareness_e2e_physical_rejection_reaches_iter2_proposer(
    vram_budget_gb, tmp_path, request, capsys
):
    """End-to-end: iter-1's physical_rejection must reach iter-2's Proposer
    as a [PHYSICAL REJECTION] string inside previous_failures, the
    hardware_context must be plumbed, and the rendered reasoning prompt
    must carry the [HARDWARE CONTEXT] block. Real mode additionally
    asserts behavioural downsizing. Phase B (--real-training) lifts the
    heavy-node patches so the real RTX 5090 earns iter-1's OOM (§5.3.7)."""
    from tests.conftest import _is_real_llm, _is_real_training

    real_mode = _is_real_llm(request)
    real_training = _is_real_training(request)

    if real_mode and not os.getenv("OPENAI_API_KEY"):
        pytest.skip("--real-llm requires OPENAI_API_KEY for B.5")

    # Phase-partitioned parametrize filter: Phase A runs 10 / 20 GB against
    # the stubbed device; Phase B runs 8 GB only against the real GPU.
    if real_training:
        if vram_budget_gb not in _PHASE_B_BUDGETS_GB:
            pytest.skip(
                f"Phase B runs only {sorted(_PHASE_B_BUDGETS_GB)} GB per directive; "
                f"skipping {vram_budget_gb} GB."
            )
        import torch

        if not torch.cuda.is_available():
            pytest.skip("Phase B requires CUDA (RTX 5090).")
        if not Path(_TIDMAD_DATA_DIR).exists():
            pytest.skip(f"Phase B requires TIDMAD data at {_TIDMAD_DATA_DIR}.")
    else:
        if vram_budget_gb not in _PHASE_A_BUDGETS_GB:
            pytest.skip(
                f"Phase A runs only {sorted(_PHASE_A_BUDGETS_GB)} GB; "
                f"skipping {vram_budget_gb} GB (reserved for Phase B)."
            )

    # Seed the workspace so the workflow bootstraps iteration 1. Required
    # for both phases — the orchestrator reads it to build iter-1's
    # interpretation input.
    _write_tuning_output(tmp_path, "punet", run="v1", score=0.01)

    workspace = str(tmp_path / "workflow_output")
    # Seed + data-dir wiring (B.6f v6 — TimeEval correctness).
    #
    # The workflow's `data_dir` arg is overloaded: (i) seed-discovery for
    # `load_tuning_outputs(data_dir, model_types, source_run_name)`, (ii)
    # forwarded to the tuner's evaluate_time_skill, which scans the dir for
    # `abra_training_*.h5` to build a real PSD sample for the time estimator.
    # v5 set `data_dir = SIDERIUS_DATA_DIR` (no .h5 under it), so the time
    # estimator's `sample_set` came back None and every attempt died on
    # `AttributeError: 'NoneType' object has no attribute 'values'`.
    #
    # v6 fix: data_dir = _TIDMAD_DATA_DIR (raw .h5 root) so TimeEval works.
    # Seed discovery is bypassed via `source_paths=[seed_under_tmp_path]` —
    # the `source_paths is not None` branch in run_workflow short-circuits
    # the legacy load_tuning_outputs() lookup, so the FileNotFoundError that
    # killed v1 cannot return.
    if real_training:
        data_dir = _TIDMAD_DATA_DIR
        source_paths: list[str] | None = [
            str(tmp_path / "data" / "punet" / "v1" / "agent" / "run_output_v1_agent.json")
        ]
        source_run_name_arg: str | None = None
    else:
        data_dir = str(tmp_path / "data")
        source_paths = None
        source_run_name_arg = "v1"
    run_name = f"b5_vram_awareness_budget{int(vram_budget_gb)}gb"

    # Phase A seeds synthetic tuning outputs; Phase B earns real ones on
    # the physical GPU — zero-seed policy per directive.
    iter1_tune = None
    iter2_tune = None
    if not real_training:
        iter1_tune = _iter1_tuning_output_with_rejection(budget_gb=vram_budget_gb)
        iter2_tune = _make_tuning_output(model_type="shrunk_tcn_iter2", score=1.7)

    # Trial-round time cap — Phase B is tightened per directive.
    trial_time_budget_min = (
        _PHASE_B_TRIAL_TIME_BUDGET_MIN if real_training else _TRIAL_TIME_BUDGET_MIN
    )

    # Capture the ProposalInput passed into the real proposer on every
    # iteration, plus every emitted ProposalOutput, plus every LLM stage
    # output (so the reasoning-stage snippet — causal_hypothesis +
    # proposed_change — is available post-run even though those fields
    # never reach ProposalOutput).
    captured_inputs: list = []
    emitted_proposals: list = []
    captured_bridge_calls: list = []
    iter_counter = [0]

    from agent.llm_bridge import LLMBridge
    from nodes.ml_model_proposal_agent import MLModelProposalAgent as _RealProposer

    class _CapturingProposer(_RealProposer):
        def run(self, inp, *args, **kwargs):
            # Phase B v8 — iter-1 carries over-architect advice to force OOM.
            # On iter-2 (signalled by a non-empty previous_failures list, which
            # is where the real PhysicalRejection lands) we scrub the advice so
            # it cannot pull the LLM away from the MANDATORY rejection-
            # acknowledgement clause in causal_reasoning_stage.md.
            if real_training and inp.previous_failures:
                inp.human_advice = None
                inp.expert_context = [
                    item for item in inp.expert_context if getattr(item, "source", None) != "human"
                ]
            captured_inputs.append(inp)
            out = super().run(inp, *args, **kwargs)
            emitted_proposals.append(out)
            return out

    def _real_capturing_bridge_factory(**bridge_kwargs):
        bridge = LLMBridge(**bridge_kwargs)
        original_generate = bridge.generate

        def _capturing_generate(*args, **kwargs):
            result = original_generate(*args, **kwargs)
            captured_bridge_calls.append(
                {
                    "args": args,
                    "kwargs": kwargs,
                    "result": result,
                }
            )
            return result

        bridge.generate = _capturing_generate
        return bridge

    def _proposer_ctor(**kwargs):
        iter_counter[0] += 1
        if real_mode:
            kwargs["bridge_factory"] = _real_capturing_bridge_factory
        else:
            kwargs["bridge_factory"] = _make_canned_bridge_factory(f"b5_arch_iter{iter_counter[0]}")
        return _CapturingProposer(**kwargs)

    # Conditional patch stack (§5.3.7 B.6f). MLModelProposalAgent stays
    # wrapped in BOTH phases — it is the capture layer for iter-2 behavioral
    # assertions. In Phase A the rest of the graph is mocked for speed. In
    # Phase B every other node is the real thing so iter-1 can actually OOM
    # on the RTX 5090 and iter-2 can actually train to 'succeeded'.
    with ExitStack() as stack:
        MockPropose = stack.enter_context(patch("workflows.model_exploration.MLModelProposalAgent"))
        MockPropose.side_effect = _proposer_ctor

        if not real_training:
            # Phase A — full mock stack.
            stack.enter_context(
                patch(
                    "workflows.model_exploration.get_or_create_hardware_context",
                    return_value=_stub_hardware_context(),
                )
            )
            MockInterp = stack.enter_context(
                patch("workflows.model_exploration.ResultInterpretationAgent")
            )
            MockImpl = stack.enter_context(patch("workflows.model_exploration.MLModelImplementor"))
            MockValid = stack.enter_context(
                patch("workflows.model_exploration.MLCodeValidatorAgent")
            )
            MockTune = stack.enter_context(
                patch("workflows.model_exploration.HyperparamTuningAgent")
            )

            MockInterp.return_value.run.return_value = _make_interpretation_output()
            MockImpl.return_value.run.return_value = _make_implementor_output()
            MockValid.return_value.run.return_value = _make_validator_output(passed=True)
            MockTune.return_value.run.side_effect = [iter1_tune, iter2_tune]
        # else Phase B: real Interpreter + Implementor + Validator + Tuner +
        # real HardwareContext. Only MockPropose is wrapped (for capture).

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
            implement=NodeLLMConfig(provider="openai", model_id="gpt-5-mini"),
            validate_model=NodeLLMConfig(provider="openai", model_id="gpt-4o-mini"),
            tune=TunerLLMConfig(
                planner=NodeLLMConfig(provider="openai", model_id="gpt-5-mini"),
                reflector=NodeLLMConfig(provider="openai", model_id="gpt-5-mini"),
            ),
        )

        iteration_results = run_workflow(
            launch=WorkflowLaunchConfig(
                data_dir=data_dir,
                model_types=["punet"],
                source_run_name=source_run_name_arg,
                source_paths=source_paths,
                max_iterations=2,
                max_rounds=2,
                is_trial=True,
                trial_vram_budget_gb=vram_budget_gb,
                formal_vram_budget_gb=vram_budget_gb,
                trial_time_budget_minutes=trial_time_budget_min,
                formal_time_budget_minutes=_FORMAL_TIME_BUDGET_MIN,
                human_advice_propose=_PHASE_B_PROPOSE_ADVICE if real_training else None,
                debug_dump_prompts=True,
            ),
            workspace=workspace,
            run_name=run_name,
            llm_config=llm_config,
        )

    # ------------------------------------------------------------------
    # Layer 1 - captured iter-2 ProposalInput
    # ------------------------------------------------------------------
    assert len(captured_inputs) >= 2, (
        f"Expected >=2 proposer invocations (iter 1 + iter 2); got {len(captured_inputs)}."
    )
    iter2_input = captured_inputs[1]

    # (1) previous_failures carries at least one [PHYSICAL REJECTION].
    # Phase A: exactly 1 synthetic rejection (seeded). Phase B: two valid
    # Hardware-Aware paths per §7.2 of the design doc:
    #   (a) Failure-Rejection-Correction — iter-1 earns a [PHYSICAL REJECTION]
    #       at the configured cap, the rejection reaches iter-2's prompt,
    #       and iter-2's reasoning cites a VRAM-family keyword.
    #   (b) Successful Auto-Shrink (the "v9 discovery") — the Tuner planner
    #       downsizes the Proposer's baseline_config to fit the budget
    #       without earning a formal rejection, producing a valid trial
    #       score. Iter-2 then builds on that score normally.
    # Either path passes; failing both is the regression signal.
    rejection_strings = [s for s in iter2_input.previous_failures if "[PHYSICAL REJECTION]" in s]
    iter1_auto_shrunk = False
    if real_training:
        iter1_tuning = iteration_results[0] if iteration_results else None
        iter1_auto_shrunk = (
            len(rejection_strings) == 0
            and iter1_tuning is not None
            and iter1_tuning.status in ("completed", "partial")
            and iter1_tuning.best_denoising_score is not None
        )
        assert len(rejection_strings) >= 1 or iter1_auto_shrunk, (
            f"Phase B: iter-1 must follow either the "
            f"Failure-Rejection-Correction path (>=1 [PHYSICAL REJECTION]) "
            f"OR the Successful Auto-Shrink path (status in "
            f"('completed','partial') with a numeric best_denoising_score). "
            f"Got rejection_count="
            f"{len(rejection_strings)}, iter1_status="
            f"{iter1_tuning.status if iter1_tuning else 'NO_RESULT'}, "
            f"iter1_score="
            f"{iter1_tuning.best_denoising_score if iter1_tuning else 'NO_RESULT'}. "
            f"previous_failures={iter2_input.previous_failures!r}"
        )
    else:
        assert len(rejection_strings) == 1, (
            f"Phase A: expected exactly 1 [PHYSICAL REJECTION] string in iter-2 "
            f"previous_failures; got {len(rejection_strings)}. "
            f"Full list: {iter2_input.previous_failures!r}"
        )
    rej_str = rejection_strings[0] if rejection_strings else None

    if real_training and iter1_auto_shrunk:
        # Phase B path (b) — Tuner planner adapted; no rejection earned.
        # Surface iter-1's outcome so the human reviewer can audit the shrink.
        with capsys.disabled():
            print("\n" + "=" * 72)
            print(
                f"B.5 Phase B - ITER-1 AUTO-SHRINK SUCCESS "
                f"(budget={vram_budget_gb} GB, no PhysicalRejection earned)"
            )
            print("=" * 72)
            print(f"status:               {iter1_tuning.status}")
            print(f"best_denoising_score: {iter1_tuning.best_denoising_score}")
            print(f"best_exp_id:          {iter1_tuning.best_exp_id}")
            print(f"best_config:          {iter1_tuning.best_config}")
            print(
                "Tuner planner downsized the Proposer's baseline_config to "
                "fit the budget — see §7.1 of the design doc."
            )
            print("=" * 72)
    elif real_training:
        # Phase B path (a) — real rejection content is proposal-dependent;
        # surface it for human review but don't assert on specific
        # model/layer strings.
        with capsys.disabled():
            print("\n" + "=" * 72)
            print(f"B.5 Phase B - ITER-1 REAL PHYSICAL REJECTION (budget={vram_budget_gb} GB)")
            print("=" * 72)
            print(rej_str)
            print("=" * 72)
    else:
        # Phase A — synthetic rejection content is known; assert verbatim.
        assert _REJECTED_MODEL_TYPE in rej_str, (
            f"Rejection string must cite iter-1 arch {_REJECTED_MODEL_TYPE!r}; got: {rej_str!r}"
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
    assert iter2_input.vram_budget_gb == pytest.approx(vram_budget_gb)

    # ------------------------------------------------------------------
    # Layer 2 - rendered reasoning prompt carries [HARDWARE CONTEXT]; the
    # [PHYSICAL REJECTION] block must be present iff iter-1 earned a
    # rejection (skipped on the auto-shrink path).
    # ------------------------------------------------------------------
    from nodes.ml_model_proposal_agent import _build_reasoning_prompt

    rendered = _build_reasoning_prompt(iter2_input)
    assert "[HARDWARE CONTEXT]" in rendered, (
        "Iter-2 reasoning prompt must carry a [HARDWARE CONTEXT] block. "
        f"Prompt tail:\n{rendered[-2000:]}"
    )
    if vram_budget_gb < 25.6:
        assert "BUDGET" in rendered, (
            f"Regime line should read BUDGET (budget={vram_budget_gb} GB < usable_cap=25.6 GB)."
        )
    assert f"{vram_budget_gb:.2f} GB" in rendered, (
        f"Effective-cap line must render the parametrized budget "
        f"{vram_budget_gb:.2f} GB verbatim; prompt tail:\n{rendered[-2000:]}"
    )
    if not iter1_auto_shrunk:
        assert "[PHYSICAL REJECTION]" in rendered, (
            "Iter-2 reasoning prompt must surface the [PHYSICAL REJECTION] block "
            "inside the Previous Failed Proposals section."
        )

    # ------------------------------------------------------------------
    # Layer 3 - Real-mode Cognitive Hardening trip-wires (B.6c + B.6d).
    # Two independent behavioural gates run in real mode:
    #
    #   (a) §5.3.5 parameter-count ceiling - architecture-agnostic, catches
    #       cross-architecture-class regressions the narrow hidden_dim/depth
    #       check missed (Phase A 10 GB run, 2026-04-24).
    #   (b) §5.3.6 causal_hypothesis keyword audit - asserts the LLM used
    #       VRAM-family vocabulary, i.e. it reasoned *against* the rejection
    #       rather than pivoting around it by coincidence.
    #
    # Both are one-sample probabilistic; together they form the "acknowledges
    # its sins" contract set by the §3.4 MANDATORY clause.
    # ------------------------------------------------------------------
    if real_mode:
        assert len(emitted_proposals) >= 2, (
            f"Real-mode: expected >=2 emitted proposals; got {len(emitted_proposals)}."
        )
        iter2_proposal = emitted_proposals[1]
        model_cfg = iter2_proposal.baseline_config.get("model_config", {})

        # Extract iter-2's reasoning-stage output (stage 2 of the 3-stage
        # pipeline: comparison -> causal_reasoning -> proposing). The
        # proposer makes 3 generate() calls per invocation; iter-2's
        # reasoning is the first post-iter-1 call with causal_hypothesis.
        iter2_reasoning: dict = {}
        iter2_reasoning_call: dict = {}
        if len(captured_bridge_calls) >= 5:
            for call in captured_bridge_calls[3:]:
                result = call.get("result")
                if isinstance(result, dict) and "causal_hypothesis" in result:
                    iter2_reasoning = result
                    iter2_reasoning_call = call
                    break

        # §5.3.5 param-count gate.
        iter2_params = iter2_proposal.parameter_count_estimate
        param_ceiling = int(_REJECTED_PARAM_COUNT_ESTIMATE * _ITER2_PARAM_CEILING_FRAC)
        param_count_ok = iter2_params is not None and iter2_params < param_ceiling

        # §5.3.6 keyword-audit gate (case-insensitive, WORD-BOUNDARY regex).
        # Substring matching was a false-positive farm: "cap" hit "capture",
        # "capabilities"; "oom" would hit "zoom"; "budget" would hit "budgetary".
        # \b anchors force the keyword to be its own token.
        causal_text = str(iter2_reasoning.get("causal_hypothesis", ""))
        causal_lower = causal_text.lower()
        keyword_hits = [
            kw
            for kw in _REJECTION_ACK_KEYWORDS
            if re.search(rf"\b{re.escape(kw.lower())}\b", causal_lower)
        ]
        keyword_ok = len(keyword_hits) >= 1

        # Extract the stage-2 system prompt that carried the MANDATORY
        # Integrated-Reasoning clause to the LLM. B.6e v4 evidence gate:
        # proves the v4 port reached the wire, not just the .md on disk.
        stage2_system_prompt = ""
        r_args = iter2_reasoning_call.get("args", ())
        r_kwargs = iter2_reasoning_call.get("kwargs", {})
        if r_args:
            stage2_system_prompt = str(r_args[0])
        elif "system_prompt" in r_kwargs:
            stage2_system_prompt = str(r_kwargs["system_prompt"])

        # Surface the reasoning snippet unconditionally so the human
        # reviewer can see the Proposer explicitly reacting to the
        # rejection - the audit requirement of directive Step 4.
        with capsys.disabled():
            print("\n" + "=" * 72)
            print(f"B.5 Phase A - ITER-2 REASONING SNIPPET (budget={vram_budget_gb} GB)")
            print("=" * 72)
            print(f"model_name:        {iter2_proposal.model_name}")
            print("-" * 72)
            print("[stage-2 SYSTEM PROMPT - first 80 lines]")
            if stage2_system_prompt:
                _sp_lines = stage2_system_prompt.splitlines()
                for _ln in _sp_lines[:80]:
                    print(_ln)
                if len(_sp_lines) > 80:
                    print(f"... (truncated, {len(_sp_lines) - 80} more lines)")
            else:
                print("<NOT CAPTURED>")
            print("-" * 72)
            print("[reasoning stage - causal_hypothesis]")
            print(causal_text or "<NOT CAPTURED>")
            print("-" * 72)
            print("[reasoning stage - proposed_change]")
            print(iter2_reasoning.get("proposed_change", "<NOT CAPTURED>"))
            print("-" * 72)
            print("[proposal stage - motivation]")
            print(iter2_proposal.motivation)
            print("-" * 72)
            print("[proposal stage - mathematical_definition (head 400 chars)]")
            print(iter2_proposal.mathematical_definition[:400])
            print("-" * 72)
            print(f"baseline model_config:     {model_cfg}")
            print(
                f"iter-1 rejected scale:     ~{_REJECTED_PARAM_COUNT_ESTIMATE:,} "
                f"params (arch={_REJECTED_MODEL_TYPE})"
            )
            print(f"iter-2 param estimate:     {iter2_params:,}")
            print(
                f"param ceiling (50%):       {param_ceiling:,}  -> param_count_ok={param_count_ok}"
            )
            print(f"effective cap:             {vram_budget_gb:.2f} GB (BUDGET regime)")
            print(f"keyword hits:              {keyword_hits}  -> keyword_ok={keyword_ok}")
            print("=" * 72)

        # §5.3.5 — param-count gate. Only asserts on the
        # Failure-Rejection-Correction path; on the Auto-Shrink path there
        # is no rejected scale to compare against (iter-1 succeeded), so
        # the ceiling is meaningless.
        if not iter1_auto_shrunk:
            assert param_count_ok, (
                f"Real-mode param-count assertion failed: iter-2 "
                f"parameter_count_estimate={iter2_params:,} is not < "
                f"{param_ceiling:,} ({_ITER2_PARAM_CEILING_FRAC:.0%} of the "
                f"{_REJECTED_PARAM_COUNT_ESTIMATE:,}-param rejected scale). "
                f"The Proposer re-proposed a scale comparable to the rejected "
                f"{_REJECTED_MODEL_TYPE} architecture.\n"
                f"  motivation: {iter2_proposal.motivation!r}"
            )

            # §5.3.6 — keyword-audit gate. VRAM-family vocabulary is only
            # expected when there was a rejection to acknowledge.
            assert keyword_ok, (
                f"Real-mode keyword-audit assertion failed: iter-2 "
                f"causal_hypothesis contains NONE of the VRAM-family keywords "
                f"{list(_REJECTION_ACK_KEYWORDS)!r}. The LLM did not "
                f"acknowledge the [PHYSICAL REJECTION] block in its reasoning.\n"
                f"  causal_hypothesis: {causal_text!r}"
            )

    # ------------------------------------------------------------------
    # Layer 4 — Phase B only: iter-2 real-training success gate (§5.3.7).
    # ------------------------------------------------------------------
    if real_training:
        assert len(iteration_results) >= 2, (
            f"Phase B: expected >=2 iteration_results from run_workflow; "
            f"got {len(iteration_results)}."
        )
        iter2_tuning = iteration_results[1]

        with capsys.disabled():
            print("\n" + "=" * 72)
            print(f"B.5 Phase B - ITER-2 REAL TRAINING SUMMARY (budget={vram_budget_gb} GB)")
            print("=" * 72)
            print(f"model_type:           {iter2_tuning.model_type}")
            print(f"status:               {iter2_tuning.status}")
            print(f"best_denoising_score: {iter2_tuning.best_denoising_score}")
            print(f"best_exp_id:          {iter2_tuning.best_exp_id}")
            print(f"completed_rounds:     {iter2_tuning.completed_rounds}")
            print(f"best_config:          {iter2_tuning.best_config}")
            print(
                f"iter-2 rejections:    {len(iter2_tuning.physical_rejections)} "
                f"(non-zero = iter-2 Proposer's baseline itself tripped the cap)"
            )
            print("=" * 72)

        assert iter2_tuning.status in ("completed", "partial"), (
            f"Phase B iter-2 tuning did not succeed: status={iter2_tuning.status!r}. "
            f"The shrunk baseline failed to train on the RTX 5090 under the "
            f"{vram_budget_gb} GB cap.\n"
            f"  best_denoising_score: {iter2_tuning.best_denoising_score!r}\n"
            f"  completed_rounds:     {iter2_tuning.completed_rounds}\n"
            f"  physical_rejections:  {len(iter2_tuning.physical_rejections)}"
        )
        assert iter2_tuning.best_denoising_score is not None, (
            "Phase B iter-2: best_denoising_score is None — the tuner "
            "reported success but produced no numerical score."
        )
