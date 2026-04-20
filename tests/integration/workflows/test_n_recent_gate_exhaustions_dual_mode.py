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
import pytest
from unittest.mock import MagicMock, patch

from agent.schemas.hyperparam_tuning import GateExhaustionInfo
from workflows.llm_config import (
    NodeLLMConfig,
    ProposalLLMConfig,
    TunerLLMConfig,
    WorkflowLLMConfig,
)
from workflows.model_exploration import run_workflow

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
        "focus_areas": [], "constraints": ["VRAM<10", "params<50M"],
        "known_failures": [], "suggested_directions": [], "rationale": "x",
    },
    "baseline_config": {
        "model_config": {}, "train_config": {}, "loss_config": {},
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

_ITER1_SENTINEL = (
    "ITER1-VRAM-GATE-EXHAUSTED: all 9 attempts fell outside the 4 GB budget."
)


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
    with patch("workflows.model_exploration.ResultInterpretationAgent") as MockInterp, \
         patch("workflows.model_exploration.MLModelImplementor") as MockImpl, \
         patch("workflows.model_exploration.MLCodeValidatorAgent") as MockValid, \
         patch("workflows.model_exploration.HyperparamTuningAgent") as MockTune, \
         patch("workflows.model_exploration.MLModelProposalAgent") as MockPropose:

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
        workspace, run_name, "debug",
        "iter003_attempt001_proposing_system_prompt.md",
    )
    assert os.path.exists(dump_path), (
        f"iter 3 proposing prompt dump not found at {dump_path}. "
        f"Check that debug_dump_prompts=True was honored and that the "
        f"proposer ran in pipeline mode (requires ProposalLLMConfig)."
    )

    prompt = open(dump_path, "r", encoding="utf-8").read()

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
        workspace, run_name, "debug",
        "iter001_attempt001_proposing_system_prompt.md",
    )
    if os.path.exists(iter1_dump):
        iter1_prompt = open(iter1_dump, "r", encoding="utf-8").read()
        assert "[RECENT GATE EXHAUSTIONS" not in iter1_prompt, (
            "iter 1 has no prior iterations — its prompt must not carry "
            "the gate-exhaustion block."
        )
