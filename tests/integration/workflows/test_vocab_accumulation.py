"""
Phase 4 / H.1 — Dual-mode test: vocabulary accumulation across two iterations.

Verifies that:
1. Iteration 1: ResultInterpretationAgent evaluates a REFUTED previous proposal,
   generates discoveries, and returns a non-empty runtime_vocab.
2. Protocol: local_full_context maps iter 1's runtime_vocab into ProposalInput.vocab_seed.
3. Iteration 2: ResultInterpretationAgent receives iter 1's runtime_vocab, evaluates a
   CONFIRMED proposal, generates new discoveries, and returns a strictly larger
   runtime_vocab — with all iter 1 entries still present.

This test validates the wiring of build_runtime_vocab, the workflow's
current_runtime_vocab accumulation loop, and the protocol mapping end-to-end.

Pseudo mode (default): two separate RecordingLLMBridge instances, one per iteration,
each loaded from its own canned data directory. No API key needed.

Real mode (--real-llm): both iterations use real LLMBridge (Gemini). Skips if
GEMINI_API_KEY is not set.

Run with:
  uv run pytest -m dual_mode tests/integration/workflows/test_vocab_accumulation.py -v -s
  uv run pytest -m dual_mode tests/integration/workflows/test_vocab_accumulation.py -v -s --real-llm
"""
import os
import pytest
from dotenv import load_dotenv

from agent.schemas.interpretation import InterpretationInput, InterpretationOutput, ModelRunSummary
from agent.schemas.protocols.ml_result_interp_to_ml_model_propose import local_full_context
from agent.schemas.storage import StorageConfig, LocalStorageConfig
from nodes.result_interpretation_agent import ResultInterpretationAgent

# Reuse seed summaries and proposal fixtures defined in the interpretation node test
from tests.integration.nodes.test_result_interpretation_agent import (
    _SEED_WAVENET,
    _SEED_PUNET,
    _PREVIOUS_PROPOSAL_REFUTED,
)

load_dotenv()

pytestmark = pytest.mark.dual_mode


# ---------------------------------------------------------------------------
# Iteration 2 scenario fixtures
# ---------------------------------------------------------------------------

# spectral_net was proposed after iter 1's REFUTED discovery about attn_wavenet.
# It achieved 6.1 — beating wavenet SOTA (5.576) and exceeding the threshold (5.9).
_SPECTRAL_NET_SUMMARY = ModelRunSummary(
    model_type="spectral_net",
    run_name="adaptive_v2",
    status="completed",
    completed_rounds=3,
    best_denoising_score=6.1,
    worst_denoising_score=5.85,
    best_config={
        "model_config": {"spectral_channels": 32, "num_blocks": 4},
        "train_config": {"lr": 1e-4, "epochs": 10},
        "loss_config": {"loss_type": "focal"},
    },
    round_scores=[5.85, 5.98, 6.10],
    round_conclusions=[
        "Strong baseline — spectral convolutions immediately address low-freq gap.",
        "Score improved with more training data. Model not yet data-saturated.",
        "Converged at 6.1. Low-freq files 0-4 now score 1.5-2.5 (vs near-zero for wavenet).",
    ],
    model_description=(
        "SpectralNet applies 1D FFT-based convolutions to capture frequency-domain "
        "patterns directly, bypassing the spatial-domain limitations of dilated causal "
        "convolutions. Each block transforms the signal to frequency domain, applies "
        "learnable spectral filters, and transforms back — enabling global context "
        "without causality constraints."
    ),
)

# Previous proposal for iteration 2: spectral_net, predicted to beat SOTA by a margin.
# threshold_for_refutation=5.9, actual=6.1 → CONFIRMED (6.1 > 5.9).
_PREVIOUS_PROPOSAL_ITER2 = {
    "model_name": "spectral_net",
    "falsifiable_prediction": {
        "metric": "denoising_score",
        "current_value": 5.576,          # wavenet SOTA at time of proposal
        "predicted_value": 6.0,           # actual=6.1 >= 6.0 → confirmed
        "threshold_for_refutation": 5.7,  # actual=6.1 >> 5.7, so clearly not refuted
        "rationale": (
            "Frequency-domain convolutions directly address the low-frequency blind spot "
            "identified as a structural limitation of wavenet. A score above 5.9 would "
            "confirm that spectral processing resolves the root cause."
        ),
    },
    "inherited_components": [
        {
            "component": "focal_loss",
            "from_model_type": "wavenet",
            "contribution_evidence": "Focal loss improved wavenet score by +0.35 vs CE.",
        },
    ],
    "proposed_vocab_links": [],
    "proposed_discoveries": [],
}


# ---------------------------------------------------------------------------
# H.1 — Dual-mode test
# ---------------------------------------------------------------------------

@pytest.mark.dual_mode
def test_vocab_grows_across_two_iterations(tmp_path, request):
    """H.1 — Vocabulary accumulates monotonically across two interpretation iterations.

    Iteration 1 (REFUTED):
      - attn_wavenet proposed, predicted score=6.5, actual=-1.509 → REFUTED
      - runtime_vocab gets: prediction_attn_wavenet_refuted + score_attn_wavenet_vs_sota
      - Expected: len(runtime_vocab) >= 1, at least one kind='discovery' entry

    Protocol check:
      - local_full_context maps iter 1's runtime_vocab → ProposalInput.vocab_seed
      - Expected: vocab_seed non-empty, contains at least one discovery entry

    Iteration 2 (CONFIRMED):
      - spectral_net proposed, predicted score=6.2, actual=6.1 > threshold 5.9 → CONFIRMED
      - Receives iter 1's runtime_vocab as incoming_vocab
      - runtime_vocab gets: iter 1 entries + prediction_spectral_net_confirmed + score_spectral_net_vs_sota
      - Expected: len(iter2.runtime_vocab) > len(iter1.runtime_vocab)
      - Expected: all iter 1 entries still present (monotonic accumulation)
    """
    from tests.conftest import _is_real_llm
    from tests.helpers.recording_llm_bridge import RecordingLLMBridge

    storage_iter1 = StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace=str(tmp_path), run_name="iter1"),
    )
    storage_iter2 = StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace=str(tmp_path), run_name="iter2"),
    )

    # -----------------------------------------------------------------------
    # Iteration 1: attn_wavenet REFUTED
    # -----------------------------------------------------------------------

    # attn_wavenet with bad score (actual=-1.509 << threshold 5.8 → REFUTED)
    attn_wavenet_bad = ModelRunSummary(
        model_type="attn_wavenet",
        run_name="adaptive_v1",
        status="completed",
        completed_rounds=3,
        best_denoising_score=-1.509,
        worst_denoising_score=-2.509,
        best_config={
            "model_config": {"attn_heads": 4},
            "train_config": {"lr": 1e-4},
            "loss_config": {"loss_type": "focal"},
        },
        round_scores=[-2.509, -2.0, -1.509],
        round_conclusions=["unstable", "partial recovery", "best achieved"],
        model_description="Wavenet with multi-head self-attention at the bottleneck.",
    )

    iter1_inp = InterpretationInput(
        summaries=[_SEED_WAVENET, _SEED_PUNET, attn_wavenet_bad],
        previous_proposal=_PREVIOUS_PROPOSAL_REFUTED,
        runtime_vocab=[],
        storage={
            "backend": "local",
            "local": {"workspace": str(tmp_path), "run_name": "iter1"},
        },
    )

    if _is_real_llm(request):
        if not os.getenv("GEMINI_API_KEY"):
            pytest.skip("--real-llm requires GEMINI_API_KEY")
        from agent.llm_bridge import LLMBridge
        iter1_bridge = None
        iter1_agent = ResultInterpretationAgent(bridge_factory=LLMBridge)
    else:
        iter1_bridge = RecordingLLMBridge.for_agent("result_interpretation_agent")
        iter1_agent = ResultInterpretationAgent(bridge_factory=lambda **kw: iter1_bridge)

    iter1_output = iter1_agent.run(iter1_inp)

    # --- Iter 1 assertions ---
    assert isinstance(iter1_output, InterpretationOutput)
    assert iter1_output.prediction_evaluation is not None, \
        "Iter 1: prediction_evaluation is None — feedback loop did not run"
    assert iter1_output.prediction_evaluation["outcome"] == "refuted", \
        f"Iter 1: expected outcome='refuted', got {iter1_output.prediction_evaluation['outcome']!r}"
    assert len(iter1_output.new_discoveries) >= 1, \
        "Iter 1: no discoveries generated"
    assert len(iter1_output.runtime_vocab) >= 1, \
        "Iter 1: runtime_vocab is empty — discoveries not added"

    discovery_kinds_iter1 = [v.kind for v in iter1_output.runtime_vocab]
    assert "discovery" in discovery_kinds_iter1, \
        f"Iter 1: no kind='discovery' entry in runtime_vocab. Kinds: {discovery_kinds_iter1}"

    iter1_vocab_size = len(iter1_output.runtime_vocab)
    iter1_vocab_names = {v.name for v in iter1_output.runtime_vocab}

    print(f"\n  [iter 1] outcome=refuted  vocab_size={iter1_vocab_size}")
    print(f"  [iter 1] vocab names: {sorted(iter1_vocab_names)}")

    # -----------------------------------------------------------------------
    # Protocol: iter 1 runtime_vocab → ProposalInput.vocab_seed
    # -----------------------------------------------------------------------

    proposal_inp = local_full_context(iter1_output, storage_iter1)

    assert proposal_inp.vocab_seed, \
        "Protocol: vocab_seed is empty — iter 1 discoveries not passed to proposer"
    seed_kinds = [
        (v.get("kind") if isinstance(v, dict) else v.kind)
        for v in proposal_inp.vocab_seed
    ]
    assert "discovery" in seed_kinds, \
        f"Protocol: no discovery entry in vocab_seed. Kinds: {seed_kinds}"

    print(f"  [protocol] vocab_seed size={len(proposal_inp.vocab_seed)}, "
          f"discovery entries={seed_kinds.count('discovery')}")

    # -----------------------------------------------------------------------
    # Iteration 2: spectral_net CONFIRMED
    # -----------------------------------------------------------------------

    iter2_inp = InterpretationInput(
        summaries=[_SEED_WAVENET, _SEED_PUNET, _SPECTRAL_NET_SUMMARY],
        previous_proposal=_PREVIOUS_PROPOSAL_ITER2,
        runtime_vocab=iter1_output.runtime_vocab,   # carry forward iter 1 vocab
        storage={
            "backend": "local",
            "local": {"workspace": str(tmp_path), "run_name": "iter2"},
        },
    )

    if _is_real_llm(request):
        from agent.llm_bridge import LLMBridge
        iter2_bridge = None
        iter2_agent = ResultInterpretationAgent(bridge_factory=LLMBridge)
    else:
        iter2_bridge = RecordingLLMBridge.for_agent("result_interpretation_agent_iter2")
        iter2_agent = ResultInterpretationAgent(bridge_factory=lambda **kw: iter2_bridge)

    iter2_output = iter2_agent.run(iter2_inp)

    # --- Iter 2 assertions ---
    assert isinstance(iter2_output, InterpretationOutput)
    assert iter2_output.prediction_evaluation is not None, \
        "Iter 2: prediction_evaluation is None — feedback loop did not run"
    assert iter2_output.prediction_evaluation["outcome"] == "confirmed", \
        f"Iter 2: expected outcome='confirmed', got {iter2_output.prediction_evaluation['outcome']!r}"
    assert len(iter2_output.new_discoveries) >= 1, \
        "Iter 2: no new discoveries generated"

    iter2_vocab_size = len(iter2_output.runtime_vocab)
    iter2_vocab_names = {v.name for v in iter2_output.runtime_vocab}

    # Monotonic growth: iter 2 vocab must be strictly larger
    assert iter2_vocab_size > iter1_vocab_size, (
        f"Vocab did not grow across iterations: "
        f"iter1={iter1_vocab_size}, iter2={iter2_vocab_size}"
    )

    # No entries dropped: iter 1 names must all appear in iter 2
    dropped = iter1_vocab_names - iter2_vocab_names
    assert not dropped, (
        f"Entries dropped from vocab in iteration 2: {dropped}. "
        f"build_runtime_vocab must preserve all incoming entries."
    )

    # New entries added in iter 2
    new_in_iter2 = iter2_vocab_names - iter1_vocab_names
    assert new_in_iter2, (
        "No new entries in iter 2 runtime_vocab — "
        "CONFIRMED discovery not added to accumulated vocab"
    )

    print(f"  [iter 2] outcome=confirmed  vocab_size={iter2_vocab_size}")
    print(f"  [iter 2] vocab names: {sorted(iter2_vocab_names)}")
    print(f"  [iter 2] new entries: {sorted(new_in_iter2)}")
    print(f"  [iter 2] vocab grew by {iter2_vocab_size - iter1_vocab_size} entries ✓")
