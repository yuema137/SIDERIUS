"""
Tier 2 integration test: result_interpretation_agent → ml_model_proposal_agent.

Exercises the full edge:
  1. Run result_interpretation_agent with synthetic summaries (real API)
  2. Apply protocol local_full_context to produce ProposalInput
  3. Run ml_model_proposal_agent (real API — two LLM calls: reasoning + commit)
  4. Validate ProposalOutput

No GPU or real TIDMAD data required — both nodes are LLM-only.

Requires:
  - GEMINI_API_KEY and/or OPENAI_API_KEY set in the environment (or .env file)

Run with:
  uv run pytest -m real_run tests/integration/protocols/test_interp_to_propose.py -v -s

DO NOT run in CI.
"""
import os
import re
import pytest
from dotenv import load_dotenv

from agent.schemas.interpretation import (
    InterpretationInput, InterpretationOutput, ModelRunSummary,
)
from agent.schemas.proposal import (
    ModelSelectionStrategy,
    ProposalOutput, ReasoningPipelineConfig, ReasoningStage,
)
from agent.schemas.hyperparam_tuning import ExpertAdvice
from agent.schemas.protocols.ml_result_interp_to_ml_model_propose import local_full_context
from agent.schemas.score_table import (
    AggregateScalars, PerFileRow, ScoreComparisonTable,
)
from agent.schemas.storage import StorageConfig, LocalStorageConfig
from execute_tools.scoring_helpers import render_comparison_table
from nodes.result_interpretation_agent import ResultInterpretationAgent
from nodes.ml_model_proposal_agent import MLModelProposalAgent

# Reuse the synthetic summaries defined in the node integration test
from tests.integration.nodes.test_result_interpretation_agent import (
    PUNET_SUMMARY, FCNET_SUMMARY,
    _SEED_WAVENET, _SEED_PUNET, _PREVIOUS_PROPOSAL_REFUTED,
)

load_dotenv()

pytestmark = pytest.mark.real_run


# ---------------------------------------------------------------------------
# Skip guard
# ---------------------------------------------------------------------------

def _skip_if_no_key(provider: str):
    key = "GEMINI_API_KEY" if provider == "gemini" else "OPENAI_API_KEY"
    if not os.getenv(key):
        pytest.skip(f"{key} not set — skipping real API test")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_interpretation(provider: str, model_id: str, tmp_path) -> "InterpretationOutput":
    """Run the interpretation agent over punet + fcnet synthetic summaries."""
    inp = InterpretationInput(
        summaries=[PUNET_SUMMARY, FCNET_SUMMARY],
        storage={
            "backend": "local",
            "local": {"workspace": str(tmp_path), "run_name": "interp_to_propose"},
        },
    )
    return ResultInterpretationAgent(provider=provider, model_id=model_id).run(inp)


def _assert_proposal_output(output: ProposalOutput, existing_types: list):
    assert isinstance(output, ProposalOutput)

    # model_name: non-empty, snake_case, not reusing an existing type
    assert len(output.model_name) > 0
    assert re.match(r'^[a-z][a-z0-9_]*$', output.model_name), (
        f"model_name '{output.model_name}' is not snake_case"
    )
    assert output.model_name not in existing_types, (
        f"model_name '{output.model_name}' reuses an existing model type"
    )

    # Substantive text fields
    assert len(output.model_description) > 20
    assert len(output.mathematical_definition) > 50
    assert len(output.motivation) > 20

    # expert_advice is a valid ExpertAdvice instance with non-empty guidance
    assert isinstance(output.expert_advice, ExpertAdvice)
    assert len(output.expert_advice.constraints) > 0, "expert_advice.constraints is empty"
    assert len(output.expert_advice.focus_areas) > 0, "expert_advice.focus_areas is empty"
    assert len(output.expert_advice.suggested_directions) > 0, (
        "expert_advice.suggested_directions is empty"
    )

    # baseline_config has all required keys
    assert "model_config" in output.baseline_config
    assert "train_config" in output.baseline_config
    assert "loss_config"  in output.baseline_config


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestInterpToProposalGemini:

    def setup_method(self):
        _skip_if_no_key("gemini")

    def test_interp_to_proposal_full_chain(self, tmp_path):
        """
        Full edge: interpretation agent → local_full_context protocol → proposal agent.
        """
        provider  = "gemini"
        model_id  = "gemini-3.1-flash-lite-preview"
        storage   = StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="interp_to_propose"),
        )

        # Step 1: run interpretation agent (real API)
        interp_output = _run_interpretation(provider, model_id, tmp_path)
        assert len(interp_output.key_findings) > 0
        assert len(interp_output.take_home_message) > 10

        # Step 2: apply protocol
        proposal_input = local_full_context(interp_output, storage)
        assert set(proposal_input.existing_model_types) == {"punet", "fcnet"}
        assert "take_home_message" in proposal_input.interpretation

        # Step 3: run proposal agent (real API — two LLM calls)
        output = MLModelProposalAgent(provider=provider, model_id=model_id).run(proposal_input)

        # Step 4: validate
        _assert_proposal_output(output, existing_types=["punet", "fcnet"])
        assert (tmp_path / "proposal_interp_to_propose.json").exists()

        print(f"\n  take_home_message : {interp_output.take_home_message}")
        print(f"  proposed model    : {output.model_name}")
        print(f"  motivation        : {output.motivation[:200]}...")
        print(f"  math_definition   : {output.mathematical_definition[:300]}...")
        print(f"  constraints       : {output.expert_advice.constraints}")


class TestInterpToProposalOpenAI:

    def setup_method(self):
        _skip_if_no_key("openai")

    def test_interp_to_proposal_full_chain(self, tmp_path):
        """
        Full edge via OpenAI: interpretation agent → local_full_context → proposal agent.
        """
        provider  = "openai"
        model_id  = "gpt-4o-mini"
        storage   = StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="interp_to_propose"),
        )

        interp_output = _run_interpretation(provider, model_id, tmp_path)
        assert len(interp_output.take_home_message) > 10

        proposal_input = local_full_context(interp_output, storage)
        output = MLModelProposalAgent(provider=provider, model_id=model_id).run(proposal_input)

        _assert_proposal_output(output, existing_types=["punet", "fcnet"])
        assert (tmp_path / "proposal_interp_to_propose.json").exists()

        print(f"\n  proposed model : {output.model_name}")
        print(f"  motivation     : {output.motivation[:200]}...")


# ---------------------------------------------------------------------------
# F.5 — Dual-mode Tier 2 test: discoveries reach the proposer prompt
# ---------------------------------------------------------------------------

# Default pipeline config matching the workflow (2 stages + final proposing call)
_PIPELINE_CFG = ReasoningPipelineConfig(stages=[
    ReasoningStage(name="comparison",      system_prompt_key="COMPARATIVE_ANALYSIS"),
    ReasoningStage(name="causal_reasoning", system_prompt_key="CAUSAL_REASONING"),
])


@pytest.mark.dual_mode
def test_interp_to_propose_feedback_loop(tmp_path, request):
    """F.5 — Tier 2 dual-mode test: a REFUTED discovery from interpretation
    reaches the proposer's LLM prompt end-to-end.

    Chain:
      ResultInterpretationAgent.run(input with previous_proposal)
        → local_full_context (protocol) → ProposalInput with vocab containing discovery
          → MLModelProposalAgent.run() → proposer prompt contains 'REFUTED'

    Pseudo mode (default): both agents use RecordingLLMBridge. No API calls.
    Real mode (--real-api-call): uses real Gemini API. Skips if key not set.
    """
    from tests.conftest import _is_real_llm
    from tests.helpers.recording_llm_bridge import RecordingLLMBridge

    if _is_real_llm(request):
        if not os.getenv("GEMINI_API_KEY"):
            pytest.skip("GEMINI_API_KEY not set")

    storage = StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace=str(tmp_path), run_name="feedback_chain"),
    )

    # Proposed model summary with a bad score → triggers REFUTED outcome
    proposed_summary = ModelRunSummary(
        model_type="attn_wavenet",
        run_name="adaptive_v1",
        status="completed",
        completed_rounds=3,
        best_denoising_score=-1.509,
        worst_denoising_score=-2.509,
        best_config={"model_config": {"attn_heads": 4},
                     "train_config": {"lr": 1e-4},
                     "loss_config": {"loss_type": "focal"}},
        round_scores=[-2.509, -2.0, -1.509],
        round_conclusions=["unstable", "partial recovery", "best achieved"],
        model_description="Wavenet with multi-head self-attention at the bottleneck.",
    )

    interp_inp = InterpretationInput(
        summaries=[_SEED_WAVENET, _SEED_PUNET, proposed_summary],
        previous_proposal=_PREVIOUS_PROPOSAL_REFUTED,
        runtime_vocab=[],
        storage={
            "backend": "local",
            "local": {"workspace": str(tmp_path), "run_name": "feedback_chain"},
        },
    )

    if _is_real_llm(request):
        interp_bridge  = None
        propose_bridge = None
        interp_agent   = ResultInterpretationAgent(provider="gemini",
                                                    model_id="gemini-3.1-flash-lite-preview")
        propose_agent  = MLModelProposalAgent(provider="gemini",
                                              model_id="gemini-3.1-flash-lite-preview")
    else:
        interp_bridge  = RecordingLLMBridge.for_agent("result_interpretation_agent")
        propose_bridge = RecordingLLMBridge.for_agent("ml_model_proposal_agent")
        interp_agent   = ResultInterpretationAgent(bridge_factory=lambda **kw: interp_bridge)
        propose_agent  = MLModelProposalAgent(bridge_factory=lambda **kw: propose_bridge)

    # Step 1: run interpretation — produces REFUTED discovery in runtime_vocab
    interp_output = interp_agent.run(interp_inp)
    assert interp_output.prediction_evaluation is not None
    assert interp_output.prediction_evaluation["outcome"] == "refuted"
    assert len(interp_output.runtime_vocab) >= 1

    # Step 2: apply protocol — runtime_vocab (with discovery) flows to vocab_seed
    proposal_input = local_full_context(
        interp_output, storage, reasoning_pipeline=_PIPELINE_CFG,
    )
    assert proposal_input.vocab_seed, "vocab_seed is empty — discovery not passed to proposer"

    # Confirm discovery is in vocab_seed
    discovery_in_seed = any(
        (v.get("kind") if isinstance(v, dict) else v.kind) == "discovery"
        for v in proposal_input.vocab_seed
    )
    assert discovery_in_seed, "No discovery entry in proposal_input.vocab_seed"

    # Step 3: run proposal agent
    propose_output = propose_agent.run(proposal_input)
    assert isinstance(propose_output, ProposalOutput)

    # Step 4 (pseudo mode only): assert "REFUTED" appears in a generate() user prompt
    if propose_bridge is not None:
        generate_calls = [(call[1], call[2]) for call in propose_bridge.calls
                          if call[0] == "generate"]
        user_prompts = [user for _, user in generate_calls]
        discovery_prompt = next((p for p in user_prompts if "Discoveries" in p), None)
        assert discovery_prompt is not None, (
            "No generate() call contained 'Discoveries' — "
            "vocab discovery not rendered in proposer prompt"
        )
        assert "REFUTED" in discovery_prompt, (
            "REFUTED discovery text not present in proposer prompt — "
            "feedback loop broken end-to-end"
        )
        print(f"\n  [pseudo] REFUTED discovery confirmed in proposer prompt ✓")
        print(f"  [pseudo] vocab_seed entries: {len(proposal_input.vocab_seed)}")
        print(f"  [pseudo] proposed model: {propose_output.model_name}")


# ---------------------------------------------------------------------------
# F.6 — Phase 6 B: score_table markdown signature reaches proposer prompt
# ---------------------------------------------------------------------------

def _make_score_table(fv: list[float], model_scalar: float) -> ScoreComparisonTable:
    """Build a realistic ScoreComparisonTable from a length-20 file vector.

    Uses the real ``render_comparison_table`` so ``rendered_markdown`` carries
    the canonical 3-column header the proposer prompt should pick up verbatim.
    """
    raw_baseline_per_file = [0.2] * 20
    ground_truth_per_file = [9.5] * 20
    rows = [
        PerFileRow(
            file_index=i,
            raw_baseline=raw_baseline_per_file[i],
            ground_truth=ground_truth_per_file[i],
            model=v,
            gain_vs_raw=v - raw_baseline_per_file[i],
            headroom_vs_gt=ground_truth_per_file[i] - v,
        )
        for i, v in enumerate(fv)
    ]
    aggregate = AggregateScalars(
        raw_baseline_scalar=0.2,
        ground_truth_scalar=9.5,
        model_scalar=model_scalar,
        percent_of_ceiling_log=model_scalar / 9.5,
        num_sampled_files=20,
    )
    table = ScoreComparisonTable(
        rows=rows, aggregate=aggregate,
        s_max_global=5.27, reference_source="test_fixture",
        rendered_markdown="",
    )
    return table.model_copy(update={"rendered_markdown": render_comparison_table(table)})


# Three distinct file vectors so the top_n=2 cut produces a deterministic
# candidate / non-candidate split (punet + wavenet in, fcnet out).
_FV_STRONG = [0.1, 0.1, 0.1, 0.1, 0.1, 4.2, 4.5, 5.1, 5.8, 6.2, 6.7,
              7.1, 7.5, 7.9, 8.2, 8.5, 8.7, 8.9, 9.0, 9.1]
_FV_MID    = [0.1, 0.1, 0.1, 0.1, 0.1, 3.2, 3.5, 4.1, 4.5, 4.8, 5.0,
              5.2, 5.4, 5.6, 5.8, 6.0, 6.1, 6.2, 6.3, 6.4]
_FV_LOW    = [0.1, 0.1, 0.1, 0.1, 0.1, 1.8, 2.0, 2.2, 2.5, 2.7, 2.9,
              3.0, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8]


@pytest.mark.dual_mode
def test_proposer_prompt_carries_score_tables(tmp_path, request):
    """F.6 — Phase 6 B: the Phase 5-C markdown signature reaches the proposer.

    Builds an ``InterpretationOutput`` with 3 models × full
    ``ScoreComparisonTable``, applies ``local_full_context`` with a
    ``top_n=2`` selection strategy (so fcnet drops to the non-candidate
    overview), runs the proposal agent, and captures the stage user prompts
    via ``RecordingLLMBridge.calls``.

    Hard-asserts the Phase 5-C contract on captured prompts:
      - ``## Candidate Models — detailed view`` (top-level markdown heading)
      - ``| file | raw_baseline | ground_truth |`` (rendered_markdown header
        from the real ``render_comparison_table``)
      - ``score_summary`` / ``log_scalar=`` — non-candidate one-liner emitted
        by ``build_score_summary_line`` into the JSON region.

    Pseudo-only: skipped under ``--real-llm`` because bridge-capture
    assertions are only meaningful against ``RecordingLLMBridge``.
    """
    from tests.conftest import _is_real_llm
    from tests.helpers.recording_llm_bridge import RecordingLLMBridge

    if _is_real_llm(request):
        pytest.skip("bridge-capture assertions only meaningful in pseudo mode")

    storage = StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace=str(tmp_path), run_name="score_tables_chain"),
    )

    punet_tbl   = _make_score_table(_FV_STRONG, model_scalar=5.6)
    wavenet_tbl = _make_score_table(_FV_MID,    model_scalar=4.0)
    fcnet_tbl   = _make_score_table(_FV_LOW,    model_scalar=2.5)

    interp_output = InterpretationOutput(
        model_types=["punet", "wavenet", "fcnet"],
        model_descriptions={
            "punet":   "Positional U-Net with sinusoidal positional encoding.",
            "wavenet": "Causal dilated-conv stack with residual + skip connections.",
            "fcnet":   "Fully-connected autoencoder with a narrow bottleneck.",
        },
        total_experiments=6,
        key_findings=["punet dominates mid/high frequencies",
                      "low-freq bands (files 0-4) weak across all 3"],
        bottlenecks=["structural low-freq blindness across model families"],
        take_home_message="Low-freq gap is architectural — needs spectral processing.",
        per_model_best={"punet": 5.6, "wavenet": 4.0, "fcnet": 2.5},
        per_model_worst={"punet": 5.0, "wavenet": 3.5, "fcnet": 2.0},
        best_denoising_score=5.6,
        worst_denoising_score=2.5,
        per_model_score_tables={
            "punet":   punet_tbl,
            "wavenet": wavenet_tbl,
            "fcnet":   fcnet_tbl,
        },
    )

    # top_n=2 → punet + wavenet candidates, fcnet forced into the
    # non-candidate overview so the score_summary one-liner is exercised.
    pipeline_cfg = ReasoningPipelineConfig(
        stages=[
            ReasoningStage(name="comparison",       system_prompt_key="COMPARATIVE_ANALYSIS"),
            ReasoningStage(name="causal_reasoning", system_prompt_key="CAUSAL_REASONING"),
        ],
        model_selection=ModelSelectionStrategy(params={"n": 2}),
    )

    proposal_input = local_full_context(
        interp_output, storage, reasoning_pipeline=pipeline_cfg,
    )

    bridge = RecordingLLMBridge.for_agent("ml_model_proposal_agent")
    agent  = MLModelProposalAgent(bridge_factory=lambda **kw: bridge)
    output = agent.run(proposal_input)

    assert isinstance(output, ProposalOutput)

    # --- Capture every generate() user prompt the proposer sent ---
    user_prompts = [call[2] for call in bridge.calls if call[0] == "generate"]
    assert user_prompts, (
        "Proposer made no generate() calls — stage pipeline did not execute. "
        f"Bridge calls recorded: {[c[0] for c in bridge.calls]}"
    )

    # --- Visual signature #1: top-level markdown heading ---
    candidate_prompts = [p for p in user_prompts
                         if "## Candidate Models — detailed view" in p]
    assert candidate_prompts, (
        "No captured proposer prompt contained the Phase 5-C heading "
        "'## Candidate Models — detailed view'. build_candidate_markdown_block "
        "is not being threaded into _render_stage_user_prompt. "
        f"Captured {len(user_prompts)} prompt(s)."
    )

    # --- Visual signature #2: render_comparison_table canonical header ---
    for prompt in candidate_prompts:
        assert "| file | raw_baseline | ground_truth |" in prompt, (
            "Candidate markdown block is missing the render_comparison_table "
            "canonical 3-column header — ScoreComparisonTable.rendered_markdown "
            "is not being embedded verbatim in the stage prompt."
        )

    # --- Logic check: non-candidate one-liner present in the JSON region ---
    # build_score_summary_line emits 'log_scalar=...' and the overview field
    # is called 'score_summary'. Both must appear for fcnet.
    summary_prompts = [p for p in user_prompts
                       if "score_summary" in p and "log_scalar=" in p]
    assert summary_prompts, (
        "No captured prompt contains a non-candidate score_summary one-liner. "
        "Either the non-candidates overview is empty (top_n too permissive) or "
        "build_score_summary_line is not being called on excluded models. "
        f"Captured {len(user_prompts)} prompt(s)."
    )

    # Belt-and-braces: the fcnet one-liner specifically should be in the prompt
    # (fcnet has model_scalar=2.5, recovery=26.3%, so the literal substring is
    # stable and easy to grep for).
    fcnet_line = "log_scalar=2.50, recovery=26.3% on 20 files"
    assert any(fcnet_line in p for p in summary_prompts), (
        f"Expected non-candidate fcnet one-liner '{fcnet_line}' in at least "
        f"one captured prompt. build_score_summary_line output drifted from "
        f"the documented format, or fcnet was not excluded."
    )

    print(f"\n  [F.6] generate() calls captured      : {len(user_prompts)}")
    print(f"  [F.6] prompts w/ candidate heading   : {len(candidate_prompts)}")
    print(f"  [F.6] prompts w/ score_summary line  : {len(summary_prompts)}")
    print(f"  [F.6] proposed model                 : {output.model_name}")
