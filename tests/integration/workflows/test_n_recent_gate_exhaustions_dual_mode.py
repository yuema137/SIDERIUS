"""N.5 — dual-mode integration test for Phase N aggregate-window propagation.

Validates that the workflow's ``recent_tune_outputs`` deque → proposer
``recent_gate_exhaustions`` → rendered ``[RECENT GATE EXHAUSTIONS]`` prompt
block round-trip works end-to-end across a 3-iteration run where iter 2
succeeds in between two failing iterations.

Choreography (pseudo mode — the only mode supported by this test):

  Iter 1: tuner returns a populated ``gate_exhaustion`` (sentinel
          ``"ITER1-VRAM-GATE-EXHAUSTED"``) → deque: [iter1].
  Iter 2: tuner returns ``gate_exhaustion=None`` (a successful run) →
          deque after append: [iter1, iter2]. The protocol filters iter2
          out (None entries are dropped per §14.N.2), so iter 3's
          proposer sees ``recent_gate_exhaustions = [iter1's info]``.
  Iter 3: proposer runs. Its rendered proposing-stage system prompt
          (dumped via ``debug_dump_prompts=True``) must contain the
          ``[RECENT GATE EXHAUSTIONS`` header and iter 1's
          ``summary_message`` substring — even though iter 2 succeeded
          in between.

Light scope per §14.N.4:
- 4 of the 5 node agents (interp, impl, valid, tune) are ``MagicMock``'d
  with preset outputs — fast, deterministic.
- The proposer is *real* so the template-substitution + debug-dump
  machinery runs for real. Its ``LLMBridge`` is a ``MagicMock`` with
  canned pipeline-stage outputs (comparison + reasoning + proposing)
  via the agent's ``bridge_factory`` DI.
- No real LLM mode: a 3-iteration full workflow with real APIs would
  take hours and is covered by Tier 3 ``test_full_exploration_loop.py``
  separately. The unit tests in ``test_model_exploration.py`` already
  cover the workflow's deque propagation mechanics; this test's unique
  value is validating the end-to-end wiring from workflow → protocol →
  proposer → rendered prompt → dumped file.

Run with:
  .venv/bin/pytest tests/integration/workflows/test_n_recent_gate_exhaustions_dual_mode.py -v
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from agent.schemas.hyperparam_tuning import GateExhaustionInfo

# Reuse the unit-test factories — they produce schema-valid outputs with
# the minimum fields needed for the workflow to complete without errors.
from tests.unit.workflows.test_model_exploration import (
    _make_implementor_output,
    _make_interpretation_output,
    _make_proposal_output,
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

# ---------------------------------------------------------------------------
# Canned bridge output for the real proposer's 3-stage pipeline
# ---------------------------------------------------------------------------

_FAKE_COMPARISON = {
    "comparisons": [],
    "proposed_vocab_links": [],
    "proposed_vocab_candidates": [],
    "sota_model_type": "punet",
    "sota_score": 1.5,
    "sota_mechanism": "x",
}
_FAKE_REASONING = {
    "proposed_change": "x",
    "causal_hypothesis": "x",
    "falsifiable_prediction": {
        "metric": "denoising_score",
        "current_value": 1.5,
        "predicted_value": 2.5,
        "threshold_for_refutation": 1.0,
        "rationale": "x",
    },
    "predicted_failure_modes": [],
    "inherited_components": [],
    "proposed_vocab_candidates": [],
}
_FAKE_PROPOSING = {
    "model_name": "test_arch",
    "model_description": "x",
    "mathematical_definition": "x",
    "motivation": "x",
    "expert_advice": {
        "focus_areas": [],
        "constraints": ["VRAM<10", "params<50M"],
        "known_failures": [],
        "suggested_directions": [],
        "rationale": "x",
    },
    "baseline_config": {
        "model_config": {},
        "train_config": {},
        "loss_config": {},
    },
    "memo_consistency_notes": [],
}


def _make_canned_bridge_factory():
    """Return a bridge_factory that makes a fresh MagicMock per call, each
    preloaded with the 3-stage proposer pipeline outputs.

    The workflow creates a new ``MLModelProposalAgent`` (and therefore a
    new bridge) once per iteration. Each bridge needs exactly 3 generate
    calls' worth of preset data — comparison, reasoning, proposing."""

    def _factory(**kwargs):
        bridge = MagicMock()
        bridge.generate.side_effect = [
            _FAKE_COMPARISON,
            _FAKE_REASONING,
            _FAKE_PROPOSING,
        ]
        return bridge

    return _factory


# ---------------------------------------------------------------------------
# Gate-exhaustion sentinels
# ---------------------------------------------------------------------------

_ITER1_SENTINEL = "ITER1-VRAM-GATE-EXHAUSTED: all 9 attempts fell outside the 4 GB budget."


def _iter1_gate_exhaustion() -> GateExhaustionInfo:
    return GateExhaustionInfo(
        total_attempts=9,
        vram_gated_attempts=9,
        time_gated_attempts=0,
        other_failure_attempts=0,
        active_mode="trial",
        vram_budget_gb=4.0,
        time_budget_minutes=20.0,
        baseline_vram_estimate_gb=6.4,
        baseline_vram_factor=1.6,
        baseline_time_estimate_minutes=8.0,
        baseline_time_factor=0.4,
        worst_vram_factor=2.0,
        worst_time_factor=0.6,
        summary_message=_ITER1_SENTINEL,
    )


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.dual_mode


def test_iter3_prompt_carries_iter1_summary_through_succeeding_iter2(tmp_path):
    """End-to-end: workflow deque + protocol filter + proposer render +
    debug dump must round-trip iter 1's gate_exhaustion summary into
    iter 3's proposing-stage system prompt, even when iter 2 succeeds
    in between."""
    # Seed tuning data so the workflow can bootstrap iteration 1.
    _write_tuning_output(tmp_path, "punet", run="v1", score=1.5)

    workspace = str(tmp_path / "workflow_output")
    data_dir = str(tmp_path / "data")
    run_name = "n5_dual_mode"

    # Tune outputs: iter 1 carries gate_exhaustion (Trigger A simulated),
    # iter 2 succeeds (None), iter 3 is a filler (we only care about
    # what iter 3's proposer sees *before* iter 3's own tuner runs).
    iter1_tune = _make_tuning_output(model_type="m_iter1", score=1.6)
    iter1_tune.gate_exhaustion = _iter1_gate_exhaustion()
    iter2_tune = _make_tuning_output(model_type="m_iter2", score=1.7)
    assert iter2_tune.gate_exhaustion is None, (
        "sanity: default factory must produce None so iter 2 is filtered"
    )
    iter3_tune = _make_tuning_output(model_type="m_iter3", score=1.8)

    # Proposer produces a uniquely-named arch per iteration so the
    # workflow's existing_model_types bookkeeping stays sane.
    proposal_names = iter(["m_iter1", "m_iter2", "m_iter3"])
    proposal_factory = lambda inp: _make_proposal_output(next(proposal_names))

    # Patch 4 agents + wire the real proposer with a canned bridge.
    with (
        patch("workflows.model_exploration.ResultInterpretationAgent") as MockInterp,
        patch("workflows.model_exploration.MLModelImplementor") as MockImpl,
        patch("workflows.model_exploration.MLCodeValidatorAgent") as MockValid,
        patch("workflows.model_exploration.HyperparamTuningAgent") as MockTune,
        patch("workflows.model_exploration.MLModelProposalAgent") as MockPropose,
    ):
        MockInterp.return_value.run.return_value = _make_interpretation_output()
        MockImpl.return_value.run.return_value = _make_implementor_output()
        MockValid.return_value.run.return_value = _make_validator_output(passed=True)
        MockTune.return_value.run.side_effect = [iter1_tune, iter2_tune, iter3_tune]

        # Real proposer: when the workflow calls MLModelProposalAgent(**kwargs),
        # inject a bridge_factory so the real pipeline runs against a
        # canned bridge instead of a live LLM endpoint.
        from nodes.ml_model_proposal_agent import MLModelProposalAgent as _RealProposer

        def _proposer_ctor(**kwargs):
            # Drop the stage-specific kwargs that our canned bridge ignores —
            # we only need provider + model_id + bridge_factory to construct
            # the real agent. Flattened kwargs from ProposalLLMConfig.get()
            # include comparison_*, reasoning_*, proposing_* plus legacy
            # provider/model_id; the real constructor accepts them via **kwargs.
            kwargs["bridge_factory"] = _make_canned_bridge_factory()
            return _RealProposer(**kwargs)

        MockPropose.side_effect = _proposer_ctor

        # Build an LLM config that activates the proposer pipeline mode —
        # _get_reasoning_pipeline() only returns a non-None pipeline when
        # llm_config.propose is a ProposalLLMConfig.
        llm_config = WorkflowLLMConfig(
            interpret=NodeLLMConfig(provider="openai", model_id="test"),
            propose=ProposalLLMConfig(),  # defaults fine; bridge is mocked
            implement=NodeLLMConfig(provider="openai", model_id="test"),
            validate_model=NodeLLMConfig(provider="openai", model_id="test"),
            tune=TunerLLMConfig(
                planner=NodeLLMConfig(provider="openai", model_id="test"),
                reflector=NodeLLMConfig(provider="openai", model_id="test"),
            ),
        )

        run_workflow(
            data_dir=data_dir,
            model_types=["punet"],
            source_run_name="v1",
            workspace=workspace,
            run_name=run_name,
            llm_config=llm_config,
            max_iterations=3,
            debug_dump_prompts=True,
        )

    # --- Validate the dumped iter 3 proposing-stage system prompt ---
    # The workflow writes to {workspace}/{run_name}/debug/
    # iter{iter:03d}_attempt{attempt:03d}_proposing_system_prompt.md
    dump_path = os.path.join(
        workspace,
        run_name,
        "debug",
        "iter003_attempt001_proposing_system_prompt.md",
    )
    assert os.path.exists(dump_path), (
        f"iter 3 proposing prompt dump not found at {dump_path}. "
        f"Check that debug_dump_prompts=True was honored and that the "
        f"proposer ran in pipeline mode (requires ProposalLLMConfig)."
    )

    prompt = open(dump_path, encoding="utf-8").read()

    # Primary assertion (§14.N.4): iter 1's gate_exhaustion summary must
    # reach iter 3's proposer prompt even though iter 2 succeeded. This
    # is the full round-trip: workflow deque → protocol filter (drops
    # iter 2's None) → proposer list-based formatter → template
    # substitution → debug dump.
    assert "[RECENT GATE EXHAUSTIONS" in prompt, (
        "iter 3 proposing prompt must carry the [RECENT GATE EXHAUSTIONS "
        "header — workflow → proposer wiring is broken."
    )
    assert _ITER1_SENTINEL in prompt, (
        f"iter 3 prompt must contain iter 1's summary_message "
        f"'{_ITER1_SENTINEL}'. iter 2 succeeded (gate_exhaustion=None) "
        f"and must not have overwritten or evicted iter 1."
    )

    # Secondary — the block header reports exactly 1 iteration since iter 2
    # was filtered by the protocol. (If the filter were bypassed, the
    # header would incorrectly say "last 2 iterations".)
    assert "[RECENT GATE EXHAUSTIONS (last 1 iteration)]" in prompt, (
        "Header arithmetic broken — expected 1 iteration after iter 2 "
        "was filtered out, but the header disagrees."
    )

    # Sanity: iter 1 should NOT have seen a gate-exhaustion block (no
    # prior iterations).
    iter1_dump = os.path.join(
        workspace,
        run_name,
        "debug",
        "iter001_attempt001_proposing_system_prompt.md",
    )
    if os.path.exists(iter1_dump):
        iter1_prompt = open(iter1_dump, encoding="utf-8").read()
        assert "[RECENT GATE EXHAUSTIONS" not in iter1_prompt, (
            "iter 1 has no prior iterations — its prompt must not carry the gate-exhaustion block."
        )


# ---------------------------------------------------------------------------
# Commit 8 — Triple-Guard regression test (Fix 1 blacklist + Fix 2 pre-flight)
# ---------------------------------------------------------------------------
#
# The existing N.5 test above covers only the narrative `[RECENT GATE
# EXHAUSTIONS]` channel. This test extends the same scaffolding to drive the
# two structural channels the branch introduced end-to-end at the workflow
# layer:
#
#   * Fix 1 — `disallowed_architectural_patterns` populated by the tuner →
#             rendered as `[DISALLOWED PATTERNS]` sub-block in the proposer's
#             system prompt (visible in the dumped .md).
#   * Fix 2 — over-budget draft rejected by the static pre-flight gate →
#             `[PRE-FLIGHT REJECTION]` block injected into the proposer's
#             **user** prompt for the next proposing-stage call (visible via
#             bridge.generate.call_args_list inspection, since the debug dump
#             captures only the system prompt).
#
# `num_params` calibration — the static formula is
# `num_params × seg × batch × 6e-10` for ms/step (training) plus an inference
# scaled by 1/3; scoring is an additive constant. At seg=40000, batch=1,
# epochs=10, train_portion=0.1, budget=20min:
#   * 50_000_000 params → factor ≈ 143.4× (OVER BUDGET, ~460× above the gate)
#   *    100_000 params → factor ≈ 0.31×  (FEASIBLE, ~3× below the gate)
# The ~460× spread gives deterministic verdict flips with wide headroom.

_SCAN_OVER_T_ENGLISH = (
    "Avoid selective-scan / SSM / Mamba-style sequential state recurrence over the time dimension"
)

_PREFLIGHT_TRIAL_BUDGET_MIN = 20.0
_OVERBUDGET_PARAM_COUNT = 50_000_000
_FEASIBLE_PARAM_COUNT = 100_000


def _triple_guard_iter1_gate_exhaustion() -> GateExhaustionInfo:
    """Like `_iter1_gate_exhaustion` but additionally populates Fix 1's
    structured channel so the renderer emits a `[DISALLOWED PATTERNS]`
    sub-block in iter-2's proposer system prompt."""
    info = _iter1_gate_exhaustion()
    info.disallowed_architectural_patterns = ["scan_over_T"]
    return info


def _make_fake_proposing(
    model_name: str,
    parameter_count_estimate: int | None = None,
) -> dict:
    """Build a proposing-stage bridge output with the baseline keys the
    pre-flight helper consumes (segmentation_size, batch_size, epochs,
    loss_type) and a caller-supplied `parameter_count_estimate`."""
    fake = {
        "model_name": model_name,
        "model_description": "x",
        "mathematical_definition": "x",
        "motivation": "x",
        "expert_advice": {
            "focus_areas": [],
            "constraints": ["VRAM<10", "params<50M"],
            "known_failures": [],
            "suggested_directions": [],
            "rationale": "x",
        },
        "baseline_config": {
            "model_config": {"segmentation_size": 40000},
            "train_config": {
                "lr": 1e-4,
                "epochs": 10,
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
        "memo_consistency_notes": [],
    }
    if parameter_count_estimate is not None:
        fake["parameter_count_estimate"] = parameter_count_estimate
    return fake


def test_iter2_triple_guard_blacklist_and_preflight(tmp_path):
    """End-to-end: iter-1's `disallowed_architectural_patterns` must reach
    iter-2's proposer system prompt AS a `[DISALLOWED PATTERNS]` block
    (Fix 1); an over-budget draft must be rejected by the pre-flight gate
    and `[PRE-FLIGHT REJECTION]` must surface in the next proposing call's
    user prompt (Fix 2); the eventually-emitted proposal must carry
    audit fields proving the gate ran and passed on the retry.

    Per Decision 6 (design doc §9 Commit 6): Stages 1–2 must NOT be re-run
    on pre-flight rejection. Bridge call count for iter-2 is therefore
    exactly 4 — comparison + reasoning + draft-1 + draft-2."""
    # Seed tuning data so the workflow can bootstrap iteration 1.
    _write_tuning_output(tmp_path, "punet", run="v1", score=1.5)

    workspace = str(tmp_path / "workflow_output")
    data_dir = str(tmp_path / "data")
    run_name = "triple_guard"

    # --- Tuner outputs (unique model_types per iteration so the workflow's
    # duplicate-name guard does not silently skip iter 2 the way it does in
    # the existing N.5 scenario above) ---
    iter1_tune = _make_tuning_output(model_type="arch_iter1", score=1.6)
    iter1_tune.gate_exhaustion = _triple_guard_iter1_gate_exhaustion()
    iter2_tune = _make_tuning_output(model_type="arch_iter2_draft2", score=1.7)

    # Per-iteration state captured for post-workflow assertions.
    emitted_proposals: list = []
    bridges_by_iter: dict[int, MagicMock] = {}
    iter_counter = [0]

    def _bridge_factory_for_iter(iter_n: int):
        """Return a bridge_factory that emits a schedule tailored to the
        current iteration. Iter 1 has 3 outputs (standard single-draft run);
        iter 2 has 4 outputs (one over-budget draft + one feasible retry),
        proving Stages 1–2 are invoked exactly once per iteration."""

        def _factory(**kwargs):
            bridge = MagicMock()
            if iter_n == 1:
                bridge.generate.side_effect = [
                    _FAKE_COMPARISON,
                    _FAKE_REASONING,
                    _make_fake_proposing("arch_iter1"),
                ]
            elif iter_n == 2:
                bridge.generate.side_effect = [
                    _FAKE_COMPARISON,
                    _FAKE_REASONING,
                    _make_fake_proposing("arch_iter2_draft1", _OVERBUDGET_PARAM_COUNT),
                    _make_fake_proposing("arch_iter2_draft2", _FEASIBLE_PARAM_COUNT),
                ]
            else:
                raise AssertionError(f"triple-guard test only expects 2 iterations; got {iter_n}")
            bridges_by_iter[iter_n] = bridge
            return bridge

        return _factory

    with (
        patch("workflows.model_exploration.ResultInterpretationAgent") as MockInterp,
        patch("workflows.model_exploration.MLModelImplementor") as MockImpl,
        patch("workflows.model_exploration.MLCodeValidatorAgent") as MockValid,
        patch("workflows.model_exploration.HyperparamTuningAgent") as MockTune,
        patch("workflows.model_exploration.MLModelProposalAgent") as MockPropose,
    ):
        MockInterp.return_value.run.return_value = _make_interpretation_output()
        MockImpl.return_value.run.return_value = _make_implementor_output()
        MockValid.return_value.run.return_value = _make_validator_output(passed=True)
        MockTune.return_value.run.side_effect = [iter1_tune, iter2_tune]

        from nodes.ml_model_proposal_agent import MLModelProposalAgent as _RealProposer

        class _TrackingProposer(_RealProposer):
            """Thin wrapper capturing every emitted ProposalOutput so the
            test can assert on audit fields (preflight_factor etc.) after
            the workflow finishes."""

            def run(self, *args, **kwargs):
                out = super().run(*args, **kwargs)
                emitted_proposals.append(out)
                return out

        def _proposer_ctor(**kwargs):
            iter_counter[0] += 1
            kwargs["bridge_factory"] = _bridge_factory_for_iter(iter_counter[0])
            return _TrackingProposer(**kwargs)

        MockPropose.side_effect = _proposer_ctor

        llm_config = WorkflowLLMConfig(
            interpret=NodeLLMConfig(provider="openai", model_id="test"),
            propose=ProposalLLMConfig(),
            implement=NodeLLMConfig(provider="openai", model_id="test"),
            validate_model=NodeLLMConfig(provider="openai", model_id="test"),
            tune=TunerLLMConfig(
                planner=NodeLLMConfig(provider="openai", model_id="test"),
                reflector=NodeLLMConfig(provider="openai", model_id="test"),
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
            debug_dump_prompts=True,
            is_trial=True,
            trial_time_budget_minutes=_PREFLIGHT_TRIAL_BUDGET_MIN,
        )

    # === Guard 1 — Narrative channel (regression guard) ===
    # Also serves as the [DISALLOWED PATTERNS] host block; both are rendered
    # into the SYSTEM prompt via the proposer's template_vars.
    dump_path = os.path.join(
        workspace,
        run_name,
        "debug",
        "iter002_attempt001_proposing_system_prompt.md",
    )
    assert os.path.exists(dump_path), (
        f"iter-2 prompt dump not found at {dump_path}; debug_dump_prompts "
        "did not fire or the proposer did not reach iter 2."
    )
    iter2_prompt = open(dump_path, encoding="utf-8").read()

    assert "[RECENT GATE EXHAUSTIONS" in iter2_prompt, (
        "Narrative channel broken: iter-2 system prompt must carry "
        "[RECENT GATE EXHAUSTIONS (regression guard for N.5)."
    )

    # === Guard 2 — Fix 1 structured blacklist ===
    assert "[DISALLOWED PATTERNS]" in iter2_prompt, (
        "Fix 1 broken: iter-2 system prompt must carry a [DISALLOWED "
        "PATTERNS] sub-block populated from iter-1's "
        "disallowed_architectural_patterns=['scan_over_T']."
    )
    assert _SCAN_OVER_T_ENGLISH in iter2_prompt, (
        "Fix 1 broken: iter-2 system prompt must carry the English "
        f"description for scan_over_T; got:\n{iter2_prompt[-2000:]}"
    )

    # === Guard 3 — Fix 2 pre-flight revision loop ===
    iter2_bridge = bridges_by_iter.get(2)
    assert iter2_bridge is not None, "iter-2 bridge was not captured"
    # Decision 6 invariant — Stages 1+2 are NOT re-run on pre-flight
    # rejection; the outer loop only re-runs Stage 3.
    assert iter2_bridge.generate.call_count == 4, (
        f"Decision 6 broken: iter-2 bridge.generate should be called "
        f"exactly 4 times (comparison + reasoning + draft-1 + draft-2), "
        f"got {iter2_bridge.generate.call_count}."
    )

    # call_args_list[N][0] is the positional args tuple; bridge.generate
    # is called as (system_prompt, user_prompt), so [1] is the user prompt.
    fourth_call_user_prompt = iter2_bridge.generate.call_args_list[3][0][1]
    assert "[PRE-FLIGHT REJECTION]" in fourth_call_user_prompt, (
        "Fix 2 broken: iter-2's 4th bridge call (proposing retry) must "
        "carry [PRE-FLIGHT REJECTION] in its USER prompt. "
        f"Got user prompt tail:\n{fourth_call_user_prompt[-1500:]}"
    )
    # Decision 7 — all four prescriptive numeric substitutions must appear.
    assert f"{_OVERBUDGET_PARAM_COUNT:,}" in fourth_call_user_prompt, (
        "Fix 2 broken: rejection block missing num_params substitution "
        f"({_OVERBUDGET_PARAM_COUNT:,})."
    )
    # factor ≈ 143.4×; the rendered "{factor:.1f}x" is "143.4x".
    assert "143.4x" in fourth_call_user_prompt, (
        "Fix 2 broken: rejection block missing factor=143.4x substitution "
        "(derived from 50M params × seg=40000 × 10 epochs vs 20-min budget)."
    )
    assert f"{_PREFLIGHT_TRIAL_BUDGET_MIN:.1f} min budget" in fourth_call_user_prompt, (
        "Fix 2 broken: rejection block missing budget_minutes substitution "
        f"({_PREFLIGHT_TRIAL_BUDGET_MIN:.1f} min)."
    )

    # === Emitted ProposalOutput — audit fields + success-path sanity ===
    assert len(emitted_proposals) == 2, (
        f"expected 2 proposer emissions (iter 1 + iter 2), got {len(emitted_proposals)}."
    )
    iter2_proposal = emitted_proposals[1]
    assert iter2_proposal.model_name == "arch_iter2_draft2", (
        f"Success path should emit the feasible draft "
        f"(arch_iter2_draft2); got '{iter2_proposal.model_name}'."
    )
    assert iter2_proposal.preflight_factor is not None, (
        "Audit broken: preflight_factor not populated on emitted "
        "ProposalOutput (pre-flight did not run?)."
    )
    assert iter2_proposal.preflight_factor <= 1.0, (
        f"Emitted draft should be feasible (factor <= 1.0); got "
        f"preflight_factor={iter2_proposal.preflight_factor}."
    )
    assert (
        iter2_proposal.preflight_estimated_minutes is not None
        and iter2_proposal.preflight_estimated_minutes > 0
    ), "Audit broken: preflight_estimated_minutes not populated."
    assert not any(
        "PREFLIGHT_OVERBUDGET_EMITTED" in note for note in iter2_proposal.memo_consistency_notes
    ), (
        "Success path (not exhaustion) — memo_consistency_notes must NOT "
        f"carry PREFLIGHT_OVERBUDGET_EMITTED. Got: "
        f"{iter2_proposal.memo_consistency_notes}"
    )
