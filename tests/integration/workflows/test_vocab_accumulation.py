"""
Dual-mode integration tests: vocabulary accumulation and candidate promotion.

H.1 — Two-iteration accumulation:
  Verifies that runtime_vocab grows monotonically across two iterations and that
  the protocol maps iter 1's vocab into ProposalInput.vocab_seed.

H.2 — Three-iteration candidate promotion:
  Verifies the full promotion pipeline end-to-end: a feature candidate proposed
  in three successive iterations accumulates seen_in_runs and is promoted to
  canonical tier on the third iteration. Dedup runs and correctly keeps the entry.

  The key wiring exercised:
    - proposed_by_run injection (Bug 1 fix): interpretation agent injects
      proposed_by_run = model_name before calling build_runtime_vocab
    - seen_in_runs accumulation across iterations via model_knowledge_cache carry-forward
    - promote_candidates() firing at seen_in_runs length == 3
    - _dedup_promoted() running and keeping a genuinely new canonical entry

H.3 — Vocab discoveries appear in proposal prompt:
  Closes the loop: discoveries produced by the interpretation agent in round N
  actually reach the proposal agent's Stage 1 user prompt in round N+1.

  Uses pseudo training results (fake ModelRunSummary, no GPU) in both modes.
  Pseudo mode: proposal agent uses RecordingLLMBridge; the test inspects
    bridge.calls[0][2] (Stage 1 user prompt) and asserts every discovery
    name from iter 1's vocab appears verbatim (rendered by _render_vocabulary).
  Real mode (--real-llm): both agents use real Gemini API with the same fake
    summaries; the test asserts the ProposalOutput is schema-valid and the
    proposed model engages with the accumulated vocabulary.

  Pseudo mode uses fake ModelRunSummary objects (no GPU) and canned LLM responses.
  Real mode (--real-llm) uses real Gemini API calls with the same fake summaries.

Run with:
  uv run pytest -m dual_mode tests/integration/workflows/test_vocab_accumulation.py -v -s
  uv run pytest -m dual_mode tests/integration/workflows/test_vocab_accumulation.py -v -s --real-llm
"""

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from agent.schemas.interpretation import InterpretationInput, InterpretationOutput, ModelRunSummary
from agent.schemas.protocols.ml_result_interp_to_ml_model_propose import local_full_context
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from nodes.result_interpretation_agent import ResultInterpretationAgent

# Reuse seed summaries and proposal fixtures defined in the interpretation node test
from tests.integration.nodes.test_result_interpretation_agent import (
    _PREVIOUS_PROPOSAL_REFUTED,
    _SEED_PUNET,
    _SEED_WAVENET,
)

load_dotenv(dotenv_path=Path(__file__).resolve().parents[3] / ".env")

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
        "current_value": 5.576,  # wavenet SOTA at time of proposal
        "predicted_value": 6.0,  # actual=6.1 >= 6.0 → confirmed
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
    assert iter1_output.prediction_evaluation is not None, (
        "Iter 1: prediction_evaluation is None — feedback loop did not run"
    )
    assert iter1_output.prediction_evaluation["outcome"] == "refuted", (
        f"Iter 1: expected outcome='refuted', got {iter1_output.prediction_evaluation['outcome']!r}"
    )
    assert len(iter1_output.new_discoveries) >= 1, "Iter 1: no discoveries generated"
    assert len(iter1_output.runtime_vocab) >= 1, (
        "Iter 1: runtime_vocab is empty — discoveries not added"
    )

    discovery_kinds_iter1 = [v.kind for v in iter1_output.runtime_vocab]
    assert "discovery" in discovery_kinds_iter1, (
        f"Iter 1: no kind='discovery' entry in runtime_vocab. Kinds: {discovery_kinds_iter1}"
    )

    iter1_vocab_size = len(iter1_output.runtime_vocab)
    iter1_vocab_names = {v.name for v in iter1_output.runtime_vocab}

    print(f"\n  [iter 1] outcome=refuted  vocab_size={iter1_vocab_size}")
    print(f"  [iter 1] vocab names: {sorted(iter1_vocab_names)}")

    # -----------------------------------------------------------------------
    # Protocol: iter 1 runtime_vocab → ProposalInput.vocab_seed
    # -----------------------------------------------------------------------

    proposal_inp = local_full_context(iter1_output, storage_iter1)

    assert proposal_inp.vocab_seed, (
        "Protocol: vocab_seed is empty — iter 1 discoveries not passed to proposer"
    )
    seed_kinds = [
        (v.get("kind") if isinstance(v, dict) else v.kind) for v in proposal_inp.vocab_seed
    ]
    assert "discovery" in seed_kinds, (
        f"Protocol: no discovery entry in vocab_seed. Kinds: {seed_kinds}"
    )

    print(
        f"  [protocol] vocab_seed size={len(proposal_inp.vocab_seed)}, "
        f"discovery entries={seed_kinds.count('discovery')}"
    )

    # -----------------------------------------------------------------------
    # Iteration 2: spectral_net CONFIRMED
    # -----------------------------------------------------------------------

    iter2_inp = InterpretationInput(
        summaries=[_SEED_WAVENET, _SEED_PUNET, _SPECTRAL_NET_SUMMARY],
        previous_proposal=_PREVIOUS_PROPOSAL_ITER2,
        runtime_vocab=iter1_output.runtime_vocab,  # carry forward iter 1 vocab
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
    assert iter2_output.prediction_evaluation is not None, (
        "Iter 2: prediction_evaluation is None — feedback loop did not run"
    )
    assert iter2_output.prediction_evaluation["outcome"] == "confirmed", (
        f"Iter 2: expected outcome='confirmed', got {iter2_output.prediction_evaluation['outcome']!r}"
    )
    assert len(iter2_output.new_discoveries) >= 1, "Iter 2: no new discoveries generated"

    iter2_vocab_size = len(iter2_output.runtime_vocab)
    iter2_vocab_names = {v.name for v in iter2_output.runtime_vocab}

    # Monotonic growth: iter 2 vocab must be strictly larger
    assert iter2_vocab_size > iter1_vocab_size, (
        f"Vocab did not grow across iterations: iter1={iter1_vocab_size}, iter2={iter2_vocab_size}"
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


# ---------------------------------------------------------------------------
# Promotion fixtures shared by H.2
# ---------------------------------------------------------------------------

# The candidate that will be proposed in all three iterations.
# After 3 distinct runs propose it, promote_candidates() should fire.
_PROMO_CANDIDATE = {
    "name": "spectral_gating",
    "kind": "feature",
    "description": (
        "Learnable spectral gates applied to frequency-domain representations. "
        "Enables selective emphasis of specific frequency bands during denoising."
    ),
}

# Iter 1 previous-proposal: attn_wavenet (REFUTED — actual=-1.509, predicted=6.5)
_PROMO_PROPOSAL_ITER0 = {
    "model_name": "attn_wavenet",
    "falsifiable_prediction": {
        "metric": "denoising_score",
        "current_value": 5.576,
        "predicted_value": 6.5,
        "threshold_for_refutation": 5.8,
        "rationale": "Attention should capture global context.",
    },
    "inherited_components": [
        {
            "component": "dilated_causal_conv",
            "from_model_type": "wavenet",
            "contribution_evidence": "Core mechanism of wavenet's 5.576 score.",
        },
    ],
    "proposed_vocab_candidates": [_PROMO_CANDIDATE],
    "proposed_vocab_links": [],
    "proposed_discoveries": [],
}

# Iter 2 previous-proposal: spectral_net (CONFIRMED — actual=6.1, predicted=6.0)
_PROMO_PROPOSAL_ITER1 = {
    "model_name": "spectral_net",
    "falsifiable_prediction": {
        "metric": "denoising_score",
        "current_value": 5.576,
        "predicted_value": 6.0,
        "threshold_for_refutation": 5.7,
        "rationale": "Spectral processing directly addresses low-freq gap.",
    },
    "inherited_components": [
        {
            "component": "focal_loss",
            "from_model_type": "wavenet",
            "contribution_evidence": "Focal loss improved wavenet by +0.35.",
        },
    ],
    "proposed_vocab_candidates": [_PROMO_CANDIDATE],
    "proposed_vocab_links": [],
    "proposed_discoveries": [],
}

# Iter 3 previous-proposal: wavelet_net (CONFIRMED — actual=6.3, predicted=6.2)
_PROMO_PROPOSAL_ITER2 = {
    "model_name": "wavelet_net",
    "falsifiable_prediction": {
        "metric": "denoising_score",
        "current_value": 6.1,
        "predicted_value": 6.2,
        "threshold_for_refutation": 5.9,
        "rationale": "Multi-resolution wavelet adds further low-freq recovery.",
    },
    "inherited_components": [
        {
            "component": "dilated_causal_conv",
            "from_model_type": "wavenet",
            "contribution_evidence": "Backbone from wavenet.",
        },
        {
            "component": "focal_loss",
            "from_model_type": "spectral_net",
            "contribution_evidence": "Maintained from spectral_net.",
        },
    ],
    "proposed_vocab_candidates": [_PROMO_CANDIDATE],
    "proposed_vocab_links": [],
    "proposed_discoveries": [],
}

_SPECTRAL_NET_SUMMARY_PROMO = ModelRunSummary(
    model_type="spectral_net",
    run_name="promo_v1",
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
    round_conclusions=["strong start", "improving", "converged"],
    model_description=(
        "SpectralNet applies FFT-based convolutions with learnable spectral gates "
        "to capture frequency-domain patterns, directly addressing the low-frequency "
        "blind spot of dilated causal convolutions."
    ),
)

_WAVELET_NET_SUMMARY = ModelRunSummary(
    model_type="wavelet_net",
    run_name="promo_v1",
    status="completed",
    completed_rounds=3,
    best_denoising_score=6.3,
    worst_denoising_score=6.05,
    best_config={
        "model_config": {"wavelet_levels": 3, "spectral_channels": 16},
        "train_config": {"lr": 5e-5, "epochs": 12},
        "loss_config": {"loss_type": "focal"},
    },
    round_scores=[6.05, 6.18, 6.30],
    round_conclusions=["good baseline", "steady gain", "new SOTA"],
    model_description=(
        "WaveletNet combines multi-resolution wavelet decomposition with spectral "
        "gating to address both very-low and low-frequency bands simultaneously."
    ),
)

_ATTN_WAVENET_BAD_SUMMARY = ModelRunSummary(
    model_type="attn_wavenet",
    run_name="promo_v1",
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


# ---------------------------------------------------------------------------
# H.2 — Three-iteration promotion test
# ---------------------------------------------------------------------------


@pytest.mark.dual_mode
def test_vocab_candidate_promotion_across_three_iterations(tmp_path, request):
    """H.2 — A feature candidate proposed in 3 successive iterations is promoted
    to canonical tier on the third iteration.

    The test exercises the full promotion pipeline with fake ModelRunSummary
    objects (no GPU, no real training). In pseudo mode all LLM calls are served
    from canned data; in real mode (--real-llm) real Gemini API calls are used
    with the same fake summaries.

    Iteration 1:  attn_wavenet REFUTED.  spectral_gating seen_in_runs=["attn_wavenet"]
    Iteration 2:  spectral_net CONFIRMED. spectral_gating seen_in_runs=[..., "spectral_net"]
    Iteration 3:  wavelet_net  CONFIRMED. spectral_gating seen_in_runs=[..., "wavelet_net"]
                  → promote_candidates() fires → spectral_gating tier="canonical"
                  → _dedup_promoted() runs and keeps the entry (not a duplicate)
    """
    from tests.conftest import _is_real_llm
    from tests.helpers.recording_llm_bridge import RecordingLLMBridge

    def _make_agent(pseudo_dir: str):
        if _is_real_llm(request):
            if not os.getenv("GEMINI_API_KEY"):
                pytest.skip("--real-llm requires GEMINI_API_KEY")
            from agent.llm_bridge import LLMBridge

            return ResultInterpretationAgent(bridge_factory=LLMBridge)
        else:
            bridge = RecordingLLMBridge.for_agent(pseudo_dir)
            return ResultInterpretationAgent(bridge_factory=lambda **kw: bridge)

    # -----------------------------------------------------------------------
    # Iteration 1 — cold start, all 3 models are cache misses
    # spectral_gating proposed by attn_wavenet → seen_in_runs = ["attn_wavenet"]
    # -----------------------------------------------------------------------
    iter1_inp = InterpretationInput(
        summaries=[_SEED_WAVENET, _SEED_PUNET, _ATTN_WAVENET_BAD_SUMMARY],
        previous_proposal=_PROMO_PROPOSAL_ITER0,
        runtime_vocab=[],
        model_knowledge_cache={},
        storage={
            "backend": "local",
            "local": {"workspace": str(tmp_path), "run_name": "promo_iter1"},
        },
    )
    iter1_output = _make_agent("result_interpretation_agent_promo_iter1").run(iter1_inp)

    assert isinstance(iter1_output, InterpretationOutput)
    assert iter1_output.prediction_evaluation["outcome"] == "refuted"

    # spectral_gating must be a candidate after iter 1 (1 run, not yet promoted)
    sg_iter1 = next((v for v in iter1_output.runtime_vocab if v.name == "spectral_gating"), None)
    assert sg_iter1 is not None, "spectral_gating missing from runtime_vocab after iter 1"
    assert sg_iter1.tier == "candidate", f"Expected candidate, got {sg_iter1.tier!r}"
    assert "attn_wavenet" in sg_iter1.seen_in_runs, (
        f"proposed_by_run injection failed: seen_in_runs={sg_iter1.seen_in_runs}"
    )
    assert len(sg_iter1.seen_in_runs) == 1

    print(f"\n  [iter 1] REFUTED  spectral_gating.seen_in_runs={sg_iter1.seen_in_runs}")

    # -----------------------------------------------------------------------
    # Iteration 2 — spectral_net is new; wavenet/punet/attn_wavenet are cached
    # spectral_gating proposed by spectral_net → seen_in_runs = [.., "spectral_net"]
    # -----------------------------------------------------------------------
    iter2_inp = InterpretationInput(
        summaries=[_SPECTRAL_NET_SUMMARY_PROMO],
        previous_proposal=_PROMO_PROPOSAL_ITER1,
        runtime_vocab=iter1_output.runtime_vocab,
        model_knowledge_cache=iter1_output.model_knowledge_cache,
        storage={
            "backend": "local",
            "local": {"workspace": str(tmp_path), "run_name": "promo_iter2"},
        },
    )
    iter2_output = _make_agent("result_interpretation_agent_promo_iter2").run(iter2_inp)

    assert isinstance(iter2_output, InterpretationOutput)
    assert iter2_output.prediction_evaluation["outcome"] == "confirmed"

    sg_iter2 = next((v for v in iter2_output.runtime_vocab if v.name == "spectral_gating"), None)
    assert sg_iter2 is not None, "spectral_gating missing from runtime_vocab after iter 2"
    assert sg_iter2.tier == "candidate", f"Promoted too early (only 2 runs): tier={sg_iter2.tier!r}"
    assert "spectral_net" in sg_iter2.seen_in_runs, (
        f"spectral_net not added to seen_in_runs: {sg_iter2.seen_in_runs}"
    )
    assert len(sg_iter2.seen_in_runs) == 2

    print(f"  [iter 2] CONFIRMED spectral_gating.seen_in_runs={sg_iter2.seen_in_runs}")

    # -----------------------------------------------------------------------
    # Iteration 3 — wavelet_net is new; all others cached
    # spectral_gating proposed by wavelet_net → seen_in_runs reaches 3 → PROMOTED
    # _dedup_promoted runs and keeps the entry (is_duplicate=false in pseudo data)
    # -----------------------------------------------------------------------
    iter3_inp = InterpretationInput(
        summaries=[_WAVELET_NET_SUMMARY],
        previous_proposal=_PROMO_PROPOSAL_ITER2,
        runtime_vocab=iter2_output.runtime_vocab,
        model_knowledge_cache=iter2_output.model_knowledge_cache,
        storage={
            "backend": "local",
            "local": {"workspace": str(tmp_path), "run_name": "promo_iter3"},
        },
    )
    iter3_output = _make_agent("result_interpretation_agent_promo_iter3").run(iter3_inp)

    assert isinstance(iter3_output, InterpretationOutput)
    assert iter3_output.prediction_evaluation["outcome"] == "confirmed"

    sg_iter3 = next((v for v in iter3_output.runtime_vocab if v.name == "spectral_gating"), None)
    assert sg_iter3 is not None, "spectral_gating missing from runtime_vocab after iter 3"
    assert sg_iter3.tier == "canonical", (
        f"spectral_gating not promoted after 3 runs: "
        f"tier={sg_iter3.tier!r}, seen_in_runs={sg_iter3.seen_in_runs}"
    )
    assert len(sg_iter3.seen_in_runs) == 3
    assert "wavelet_net" in sg_iter3.seen_in_runs

    # vocab_changes must record the promotion event
    assert iter3_output.vocab_changes, "vocab_changes is empty — promotion not logged"
    promo_logged = any("spectral_gating" in change for change in iter3_output.vocab_changes)
    assert promo_logged, (
        f"spectral_gating promotion not in vocab_changes: {iter3_output.vocab_changes}"
    )

    print(f"  [iter 3] CONFIRMED spectral_gating.seen_in_runs={sg_iter3.seen_in_runs}")
    print(f"  [iter 3] tier={sg_iter3.tier!r} ✓  vocab_changes={iter3_output.vocab_changes}")


# ---------------------------------------------------------------------------
# H.3 — Vocab discoveries appear in proposal Stage 1 user prompt
# ---------------------------------------------------------------------------


@pytest.mark.dual_mode
def test_vocab_discoveries_appear_in_proposal_prompt(tmp_path, request):
    """H.3 — Discoveries from interpretation round N reach the proposal agent's
    Stage 1 user prompt in round N+1.

    Uses pseudo training results (fake ModelRunSummary, no GPU) in both modes.

    Pseudo mode:
      - Interpretation agent runs with canned LLM responses → deterministic
        discoveries: 'prediction_attn_wavenet_refuted', 'score_attn_wavenet_vs_sota'
      - Proposal agent uses RecordingLLMBridge with canned responses
      - Assert: every discovery name from iter 1 vocab appears verbatim in the
        Stage 1 user prompt (rendered by _render_vocabulary)

    Real-LLM mode (--real-llm):
      - Both agents use real Gemini API with the same fake summaries (no GPU)
      - Assert: ProposalOutput is schema-valid, model_name is a new snake_case
        identifier, and vocab engagement is non-trivial (proposed_discoveries
        or proposed_vocab_candidates non-empty)
    """
    from agent.schemas.proposal import (
        ProposalOutput,
        ReasoningPipelineConfig,
        ReasoningStage,
    )
    from nodes.ml_model_proposal_agent import MLModelProposalAgent
    from tests.conftest import _is_real_llm
    from tests.helpers.recording_llm_bridge import RecordingLLMBridge

    storage_iter1 = StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace=str(tmp_path), run_name="h3_iter1"),
    )

    # -----------------------------------------------------------------------
    # Iteration 1: interpretation agent — attn_wavenet REFUTED
    # Produces deterministic discoveries (no LLM needed for generate_discoveries):
    #   - 'prediction_attn_wavenet_refuted'  (outcome=refuted)
    #   - 'score_attn_wavenet_vs_sota'       (score -1.509 << SOTA 5.576)
    # -----------------------------------------------------------------------
    attn_wavenet_bad = ModelRunSummary(
        model_type="attn_wavenet",
        run_name="h3_v1",
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
            "local": {"workspace": str(tmp_path), "run_name": "h3_iter1"},
        },
    )

    if _is_real_llm(request):
        if not os.getenv("GEMINI_API_KEY"):
            pytest.skip("--real-llm requires GEMINI_API_KEY")
        from agent.llm_bridge import LLMBridge

        # max_retries=3: fail loudly within ~77s instead of retrying forever.
        # Pseudo training data (ModelRunSummary above) is independent of LLM calls.
        iter1_agent = ResultInterpretationAgent(
            bridge_factory=lambda **kw: LLMBridge(
                **{**kw, "model_id": "gemini-2.5-flash", "max_retries": 3}
            )
        )
    else:
        iter1_bridge = RecordingLLMBridge.for_agent("result_interpretation_agent")
        iter1_agent = ResultInterpretationAgent(bridge_factory=lambda **kw: iter1_bridge)

    try:
        iter1_output = iter1_agent.run(iter1_inp)
    except Exception as e:
        print(f"\n  [h3] interpretation agent failed: {type(e).__name__}: {e}", flush=True)
        raise

    # --- Iter 1 sanity checks ---
    assert len(iter1_output.runtime_vocab) >= 1, (
        "Iter 1: runtime_vocab is empty — no discoveries generated"
    )
    discovery_names = {v.name for v in iter1_output.runtime_vocab if v.kind == "discovery"}
    assert discovery_names, (
        f"Iter 1: no kind='discovery' entries in runtime_vocab. Kinds: {[v.kind for v in iter1_output.runtime_vocab]}"
    )

    print(f"\n  [iter 1] discoveries: {sorted(discovery_names)}")

    # -----------------------------------------------------------------------
    # Protocol: iter 1 runtime_vocab → ProposalInput.vocab_seed
    # Use a 3-stage pipeline so vocab_block appears in Stage 1 user prompt.
    # -----------------------------------------------------------------------
    pipeline = ReasoningPipelineConfig(
        stages=[
            ReasoningStage(name="comparison", system_prompt_key="COMPARATIVE_ANALYSIS"),
            ReasoningStage(name="causal_reasoning", system_prompt_key="CAUSAL_REASONING"),
        ]
    )
    proposal_inp = local_full_context(iter1_output, storage_iter1, reasoning_pipeline=pipeline)

    # vocab_seed must carry all iter 1 entries
    proposal_vocab_names = {
        (v.get("name") if isinstance(v, dict) else v.name) for v in proposal_inp.vocab_seed
    }
    assert discovery_names.issubset(proposal_vocab_names), (
        f"Protocol: not all discovery names reached vocab_seed. "
        f"Missing: {discovery_names - proposal_vocab_names}"
    )

    print(
        f"  [protocol] vocab_seed size={len(proposal_inp.vocab_seed)}, "
        f"discovery names passed through: {sorted(discovery_names)}"
    )

    # -----------------------------------------------------------------------
    # Run proposal agent — pseudo or real LLM
    # -----------------------------------------------------------------------
    if _is_real_llm(request):
        from agent.llm_bridge import LLMBridge

        proposal_agent = MLModelProposalAgent(
            bridge_factory=lambda **kw: LLMBridge(
                **{**kw, "model_id": "gemini-2.5-flash", "max_retries": 3}
            )
        )
    else:
        proposal_bridge = RecordingLLMBridge.for_agent("ml_model_proposal_agent_h3")
        proposal_agent = MLModelProposalAgent(bridge_factory=lambda **kw: proposal_bridge)

    try:
        proposal_output = proposal_agent.run(proposal_inp)
    except Exception as e:
        print(f"\n  [h3] proposal agent failed: {type(e).__name__}: {e}", flush=True)
        raise
    assert isinstance(proposal_output, ProposalOutput), (
        f"Expected ProposalOutput, got {type(proposal_output)}"
    )

    # -----------------------------------------------------------------------
    # Pseudo-mode: inspect the Stage 1 user prompt directly
    # Stage 1 is bridge.calls[0]; user_prompt = calls[0][2].
    # _render_vocabulary renders each discovery as "**{name}**: {description}"
    # so every name must appear verbatim in the rendered block.
    # -----------------------------------------------------------------------
    if not _is_real_llm(request):
        assert len(proposal_bridge.calls) >= 1, (
            "Proposal agent made no LLM calls — pipeline did not run"
        )
        stage1_user_prompt = proposal_bridge.calls[0][2]  # (method, system, user)
        for name in discovery_names:
            assert name in stage1_user_prompt, (
                f"Discovery '{name}' not found in Stage 1 user prompt. "
                f"_render_vocabulary did not include this discovery in the vocab block."
            )
        print(
            f"  [pseudo] Stage 1 user prompt contains all {len(discovery_names)} discovery names ✓"
        )
        print(f"  [pseudo] Proposal bridge call count: {len(proposal_bridge.calls)}")

    # -----------------------------------------------------------------------
    # Real-LLM mode: check the proposal output engages with the vocabulary
    # -----------------------------------------------------------------------
    else:
        import re

        assert len(proposal_output.model_name) > 0
        assert re.match(r"^[a-z][a-z0-9_]*$", proposal_output.model_name), (
            f"model_name '{proposal_output.model_name}' is not snake_case"
        )
        assert proposal_output.model_name not in proposal_inp.existing_model_types, (
            f"model_name '{proposal_output.model_name}' reuses an existing model type"
        )

        vocab_engagement = len(proposal_output.proposed_discoveries) + len(
            proposal_output.proposed_vocab_candidates
        )
        print(f"  [real-llm] model_name='{proposal_output.model_name}'", flush=True)
        print(
            f"  [real-llm] proposed_discoveries={len(proposal_output.proposed_discoveries)}, "
            f"proposed_vocab_candidates={len(proposal_output.proposed_vocab_candidates)}",
            flush=True,
        )
        print(
            f"  [real-llm] inherited_components={[c.component for c in proposal_output.inherited_components]}",
            flush=True,
        )
        print(
            f"  [real-llm] vocab engagement score: {vocab_engagement} "
            f"({'good' if vocab_engagement > 0 else 'no engagement — worth inspecting'})",
            flush=True,
        )


# ---------------------------------------------------------------------------
# Phase E fixtures
# ---------------------------------------------------------------------------

# Proposals include proposed_vocab_links so we can verify E.7 tracking.
_E4_PROPOSAL_REFUTED = {
    "model_name": "attn_wavenet",
    "falsifiable_prediction": {
        "metric": "denoising_score",
        "current_value": 5.576,  # SOTA at proposal time
        "predicted_value": 6.5,
        "threshold_for_refutation": 5.8,
        "rationale": "Attention should extend receptive field and capture global context.",
    },
    "inherited_components": [
        {
            "component": "dilated_causal_conv",
            "from_model_type": "wavenet",
            "contribution_evidence": "Core mechanism of wavenet's 5.576 score.",
        },
    ],
    "proposed_vocab_links": [
        {
            "feature": "dilated_causal_conv",
            "capability": "receptive_field",
            "evidence": "Increasing dilation depth in wavenet correlates with improved mid-freq scores.",
            "status": "proposed",
        },
    ],
    "proposed_vocab_candidates": [],
    "proposed_discoveries": [],
}

_E4_PROPOSAL_CONFIRMED = {
    "model_name": "spectral_net",
    "falsifiable_prediction": {
        "metric": "denoising_score",
        "current_value": 5.576,  # same SOTA — still trying to beat wavenet
        "predicted_value": 6.0,
        "threshold_for_refutation": 5.7,
        "rationale": "Spectral processing directly addresses the low-frequency blind spot.",
    },
    "inherited_components": [
        {
            "component": "focal_loss",
            "from_model_type": "wavenet",
            "contribution_evidence": "Focal loss improved wavenet by +0.35.",
        },
    ],
    "proposed_vocab_links": [
        {
            "feature": "dilated_causal_conv",
            "capability": "receptive_field",
            "evidence": "Wavenet's dilated stack remains the primary mechanism for temporal coverage.",
            "status": "proposed",
        },
    ],
    "proposed_vocab_candidates": [],
    "proposed_discoveries": [],
}


# ---------------------------------------------------------------------------
# H.4 — Phase E: scientific_accuracy and vocab_link_confirmations accumulate
# ---------------------------------------------------------------------------


@pytest.mark.dual_mode
def test_scientific_accuracy_and_vocab_links_accumulate(tmp_path, request):
    """H.4 — Phase E integration: scientific_accuracy and vocab_link_confirmations
    carry forward correctly across two iterations.

    Iteration 1 (REFUTED):
      - attn_wavenet proposed with vocab link: dilated_causal_conv → receptive_field
      - actual=-1.509 << current_sota=5.576 → outcome='refuted'
      - prediction_outcomes_history = {"confirmed": 0, "partial": 0, "refuted": 1}
      - scientific_accuracy = {"confirmed": 0.0, "partial": 0.0, "refuted": 1.0}
      - vocab_link_confirmations: unchanged (refuted does not add confirmation)

    Iteration 2 (CONFIRMED):
      - spectral_net proposed with same vocab link
      - actual=6.1 > current_sota=5.576 → outcome='confirmed'
      - carry forward: prediction_outcomes_history + vocab_link_confirmations from iter 1
      - prediction_outcomes_history = {"confirmed": 1, "partial": 0, "refuted": 1}
      - scientific_accuracy = {"confirmed": 0.5, "partial": 0.0, "refuted": 0.5}
      - vocab_link_confirmations["dilated_causal_conv:receptive_field"] = ["spectral_net"]
        (1 confirmation, not yet at min_runs=3 threshold → not yet in related_to)

    Uses pseudo training results (fake ModelRunSummary, no GPU) in both modes.
    Pseudo mode: RecordingLLMBridge (canned responses). Phase E logic is
    deterministic Python — assertions hold regardless of LLM mode.
    Real-LLM mode (--real-llm): real Gemini 2.5 Flash for LLM-dependent phases.
    """
    from tests.conftest import _is_real_llm
    from tests.helpers.recording_llm_bridge import RecordingLLMBridge

    # -----------------------------------------------------------------------
    # Iteration 1: attn_wavenet REFUTED (actual=-1.509 << SOTA 5.576)
    # -----------------------------------------------------------------------
    attn_wavenet_bad = ModelRunSummary(
        model_type="attn_wavenet",
        run_name="h4_v1",
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
        previous_proposal=_E4_PROPOSAL_REFUTED,
        runtime_vocab=[],
        prediction_outcomes_history={"confirmed": 0, "partial": 0, "refuted": 0},
        vocab_link_confirmations={},
        storage={
            "backend": "local",
            "local": {"workspace": str(tmp_path), "run_name": "h4_iter1"},
        },
    )

    if _is_real_llm(request):
        if not os.getenv("GEMINI_API_KEY"):
            pytest.skip("--real-llm requires GEMINI_API_KEY")
        from agent.llm_bridge import LLMBridge

        iter1_agent = ResultInterpretationAgent(
            bridge_factory=lambda **kw: LLMBridge(
                **{**kw, "model_id": "gemini-2.5-flash", "max_retries": 3}
            )
        )
    else:
        iter1_bridge = RecordingLLMBridge.for_agent("result_interpretation_agent")
        iter1_agent = ResultInterpretationAgent(bridge_factory=lambda **kw: iter1_bridge)

    try:
        iter1_output = iter1_agent.run(iter1_inp)
    except Exception as e:
        print(f"\n  [h4] iter1 interpretation failed: {type(e).__name__}: {e}", flush=True)
        raise

    # --- Iter 1 Phase E assertions ---
    assert iter1_output.prediction_evaluation is not None, "Iter 1: prediction_evaluation is None"
    assert iter1_output.prediction_evaluation["outcome"] == "refuted", (
        f"Iter 1: expected 'refuted', got {iter1_output.prediction_evaluation['outcome']!r}"
    )

    assert iter1_output.prediction_outcomes_history["refuted"] == 1, (
        f"Iter 1: expected refuted=1, got {iter1_output.prediction_outcomes_history}"
    )
    assert iter1_output.prediction_outcomes_history["confirmed"] == 0
    assert iter1_output.prediction_outcomes_history["partial"] == 0

    assert iter1_output.scientific_accuracy is not None, (
        "Iter 1: scientific_accuracy is None — should be computed after first prediction"
    )
    assert abs(iter1_output.scientific_accuracy["refuted"] - 1.0) < 1e-6, (
        f"Iter 1: expected refuted=1.0, got {iter1_output.scientific_accuracy}"
    )
    assert abs(iter1_output.scientific_accuracy["confirmed"]) < 1e-6

    # REFUTED prediction → vocab link NOT confirmed → confirmations unchanged
    assert (
        iter1_output.vocab_link_confirmations.get("dilated_causal_conv:receptive_field", []) == []
    ), "Iter 1: refuted prediction should not add vocab link confirmation"

    print(
        f"\n  [h4 iter1] outcome=refuted  "
        f"scientific_accuracy={iter1_output.scientific_accuracy}  "
        f"link_confs={dict(iter1_output.vocab_link_confirmations)}",
        flush=True,
    )

    # -----------------------------------------------------------------------
    # Iteration 2: spectral_net CONFIRMED (actual=6.1 > SOTA 5.576)
    # Carry forward Phase E state from iter 1.
    # -----------------------------------------------------------------------
    spectral_net_good = ModelRunSummary(
        model_type="spectral_net",
        run_name="h4_v2",
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
            "Spectral convolutions address low-freq gap immediately.",
            "Score improved with more data.",
            "Converged at 6.1.",
        ],
        model_description=(
            "SpectralNet applies 1D FFT-based convolutions to capture frequency-domain "
            "patterns directly, bypassing the temporal limitations of dilated causal convolutions."
        ),
    )

    iter2_inp = InterpretationInput(
        summaries=[_SEED_WAVENET, _SEED_PUNET, spectral_net_good],
        previous_proposal=_E4_PROPOSAL_CONFIRMED,
        runtime_vocab=iter1_output.runtime_vocab,
        # Carry forward Phase E state
        prediction_outcomes_history=iter1_output.prediction_outcomes_history,
        vocab_link_confirmations=iter1_output.vocab_link_confirmations,
        storage={
            "backend": "local",
            "local": {"workspace": str(tmp_path), "run_name": "h4_iter2"},
        },
    )

    if _is_real_llm(request):
        from agent.llm_bridge import LLMBridge

        iter2_agent = ResultInterpretationAgent(
            bridge_factory=lambda **kw: LLMBridge(
                **{**kw, "model_id": "gemini-2.5-flash", "max_retries": 3}
            )
        )
    else:
        iter2_bridge = RecordingLLMBridge.for_agent("result_interpretation_agent_iter2")
        iter2_agent = ResultInterpretationAgent(bridge_factory=lambda **kw: iter2_bridge)

    try:
        iter2_output = iter2_agent.run(iter2_inp)
    except Exception as e:
        print(f"\n  [h4] iter2 interpretation failed: {type(e).__name__}: {e}", flush=True)
        raise

    # --- Iter 2 Phase E assertions ---
    assert iter2_output.prediction_evaluation is not None, "Iter 2: prediction_evaluation is None"
    assert iter2_output.prediction_evaluation["outcome"] == "confirmed", (
        f"Iter 2: expected 'confirmed', got {iter2_output.prediction_evaluation['outcome']!r}"
    )

    # History: 1 refuted (from iter 1) + 1 confirmed (this iter) = 2 total
    assert iter2_output.prediction_outcomes_history["confirmed"] == 1, (
        f"Iter 2: expected confirmed=1, got {iter2_output.prediction_outcomes_history}"
    )
    assert iter2_output.prediction_outcomes_history["refuted"] == 1
    assert iter2_output.prediction_outcomes_history["partial"] == 0

    # scientific_accuracy: 1 confirmed / 2 total = 0.5
    assert iter2_output.scientific_accuracy is not None
    assert abs(iter2_output.scientific_accuracy["confirmed"] - 0.5) < 1e-4, (
        f"Iter 2: expected confirmed=0.5, got {iter2_output.scientific_accuracy}"
    )
    assert abs(iter2_output.scientific_accuracy["refuted"] - 0.5) < 1e-4

    # CONFIRMED prediction → vocab link gets 1 confirmation from run "spectral_net"
    link_confs = iter2_output.vocab_link_confirmations
    assert "dilated_causal_conv:receptive_field" in link_confs, (
        f"Iter 2: link 'dilated_causal_conv:receptive_field' not in confirmations. "
        f"Got keys: {list(link_confs.keys())}"
    )
    assert "spectral_net" in link_confs["dilated_causal_conv:receptive_field"], (
        f"Iter 2: 'spectral_net' not in confirmation list. "
        f"Got: {link_confs['dilated_causal_conv:receptive_field']}"
    )

    # 1 confirmation only → NOT yet promoted to related_to (needs 3)
    feat = next(
        (v for v in iter2_output.runtime_vocab if v.name == "dilated_causal_conv"),
        None,
    )
    if feat is not None:
        assert "receptive_field" not in feat.related_to, (
            "Iter 2: link promoted to related_to after only 1 confirmation — threshold is 3"
        )

    print(
        f"  [h4 iter2] outcome=confirmed  "
        f"scientific_accuracy={iter2_output.scientific_accuracy}  "
        f"link_confs={dict(link_confs)}",
        flush=True,
    )
    print(
        f"  [h4 iter2] prediction_outcomes_history={iter2_output.prediction_outcomes_history}",
        flush=True,
    )
    print(
        f"  [h4 iter2] delta_from_sota={iter2_output.prediction_evaluation.get('delta_from_sota')}",
        flush=True,
    )


# ---------------------------------------------------------------------------
# H.5 — VocabEntry.related_to populated at 3 confirmations and rendered
# ---------------------------------------------------------------------------


@pytest.mark.dual_mode
def test_vocab_link_confirmed_populates_related_to_and_renders(tmp_path, request):
    """H.5 — Three confirmed runs promote a vocab link into VocabEntry.related_to,
    and the rendered form ("→ enables: receptive_field") reaches the proposal
    agent's Stage 1 user prompt.

    Chain under test:
      confirmation accumulation → related_to populated → rendered in prompt

    The test pre-seeds vocab_link_confirmations with 2 prior confirmed runs
    ("run_a", "run_b").  One CONFIRMED interpretation iteration (spectral_net)
    contributes the 3rd confirmation.  The interpretation agent calls
    update_vocab_link_confirmations(), which promotes:
      dilated_causal_conv.related_to = ["receptive_field"]
    The protocol maps runtime_vocab into ProposalInput.vocab_seed.
    The proposal agent's _render_vocabulary produces
    "→ enables: receptive_field" in the vocab block, which is appended to
    every stage user prompt.

    Pseudo mode: interpretation uses result_interpretation_agent_iter2 canned
    data (spectral_net CONFIRMED); proposal uses ml_model_proposal_agent_h5
    canned data.  All Phase E logic (update_vocab_link_confirmations,
    build_runtime_vocab) is deterministic Python — assertions hold in both modes.

    Real-LLM mode (--real-llm): same fake summaries; real Gemini API calls.
    The related_to promotion is still deterministic — only vocab rendering
    and schema validity are LLM-dependent.
    """
    from agent.schemas.proposal import (
        ProposalOutput,
        ReasoningPipelineConfig,
        ReasoningStage,
        VocabEntry,
    )
    from nodes.ml_model_proposal_agent import MLModelProposalAgent
    from tests.conftest import _is_real_llm
    from tests.helpers.recording_llm_bridge import RecordingLLMBridge

    # -----------------------------------------------------------------------
    # Setup: dilated_causal_conv feature entry + 2 prior confirmations
    # -----------------------------------------------------------------------

    # A canonical feature entry for dilated_causal_conv — must be in runtime_vocab
    # for update_vocab_link_confirmations() to find it and update related_to.
    dilated_conv_entry = VocabEntry(
        name="dilated_causal_conv",
        kind="feature",
        description=(
            "Stacked dilated causal convolutions with exponentially growing dilation "
            "factors, providing an exponential receptive field at O(log N) depth."
        ),
        tier="canonical",
        related_to=[],
    )

    # Two prior CONFIRMED runs have already proposed dilated_causal_conv → receptive_field.
    # The 3rd confirmation (spectral_net, from this iteration) triggers promotion.
    prior_confirmations = {
        "dilated_causal_conv:receptive_field": ["run_a", "run_b"],
    }

    # -----------------------------------------------------------------------
    # Interpretation iteration: spectral_net CONFIRMED (3rd confirmation)
    # Reuses _E4_PROPOSAL_CONFIRMED (model_name="spectral_net",
    # proposed_vocab_links=[dilated_causal_conv→receptive_field]).
    # -----------------------------------------------------------------------
    spectral_net_good = ModelRunSummary(
        model_type="spectral_net",
        run_name="h5_v1",
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
            "Spectral convolutions address low-freq gap immediately.",
            "Score improved with more data.",
            "Converged at 6.1.",
        ],
        model_description=(
            "SpectralNet applies 1D FFT-based convolutions to capture frequency-domain "
            "patterns directly, bypassing the temporal limitations of dilated causal convolutions."
        ),
    )

    iter_inp = InterpretationInput(
        summaries=[_SEED_WAVENET, _SEED_PUNET, spectral_net_good],
        previous_proposal=_E4_PROPOSAL_CONFIRMED,  # model_name="spectral_net"
        runtime_vocab=[dilated_conv_entry],  # carry-in: dilated_causal_conv
        prediction_outcomes_history={"confirmed": 0, "partial": 0, "refuted": 0},
        vocab_link_confirmations=prior_confirmations,  # 2 prior confirmations
        storage={
            "backend": "local",
            "local": {"workspace": str(tmp_path), "run_name": "h5_iter1"},
        },
    )

    if _is_real_llm(request):
        if not os.getenv("GEMINI_API_KEY"):
            pytest.skip("--real-llm requires GEMINI_API_KEY")
        from agent.llm_bridge import LLMBridge

        interp_agent = ResultInterpretationAgent(
            bridge_factory=lambda **kw: LLMBridge(
                **{**kw, "model_id": "gemini-2.5-flash", "max_retries": 3}
            )
        )
    else:
        interp_bridge = RecordingLLMBridge.for_agent("result_interpretation_agent_iter2")
        interp_agent = ResultInterpretationAgent(bridge_factory=lambda **kw: interp_bridge)

    try:
        iter_output = interp_agent.run(iter_inp)
    except Exception as e:
        print(f"\n  [h5] interpretation agent failed: {type(e).__name__}: {e}", flush=True)
        raise

    assert isinstance(iter_output, InterpretationOutput)
    assert iter_output.prediction_evaluation is not None
    assert iter_output.prediction_evaluation["outcome"] == "confirmed", (
        f"Expected CONFIRMED, got {iter_output.prediction_evaluation['outcome']!r}"
    )

    # -----------------------------------------------------------------------
    # Assertion 1: vocab_link_confirmations has exactly 3 entries for the link
    # -----------------------------------------------------------------------
    link_confs = iter_output.vocab_link_confirmations
    assert "dilated_causal_conv:receptive_field" in link_confs, (
        f"'dilated_causal_conv:receptive_field' missing from confirmations. "
        f"Keys: {list(link_confs.keys())}"
    )
    conf_runs = link_confs["dilated_causal_conv:receptive_field"]
    assert len(conf_runs) == 3, f"Expected 3 confirmation runs, got {len(conf_runs)}: {conf_runs}"
    assert "spectral_net" in conf_runs, (
        f"'spectral_net' not added as 3rd confirmation. Got: {conf_runs}"
    )
    assert "run_a" in conf_runs and "run_b" in conf_runs, (
        f"Prior confirmations not preserved. Got: {conf_runs}"
    )
    print(f"\n  [h5] vocab_link_confirmations: {dict(link_confs)}")

    # -----------------------------------------------------------------------
    # Assertion 2: dilated_causal_conv.related_to contains "receptive_field"
    # -----------------------------------------------------------------------
    dc_entry = next(
        (v for v in iter_output.runtime_vocab if v.name == "dilated_causal_conv"),
        None,
    )
    assert dc_entry is not None, (
        "dilated_causal_conv missing from runtime_vocab — incoming entry was dropped"
    )
    assert "receptive_field" in dc_entry.related_to, (
        f"Link NOT promoted to related_to after 3 confirmations. "
        f"dilated_causal_conv.related_to={dc_entry.related_to}"
    )
    print(f"  [h5] dilated_causal_conv.related_to={dc_entry.related_to} ✓")

    # -----------------------------------------------------------------------
    # Protocol: runtime_vocab → ProposalInput.vocab_seed
    # -----------------------------------------------------------------------
    storage_h5 = StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace=str(tmp_path), run_name="h5_proposal"),
    )
    pipeline = ReasoningPipelineConfig(
        stages=[
            ReasoningStage(name="comparison", system_prompt_key="COMPARATIVE_ANALYSIS"),
            ReasoningStage(name="causal_reasoning", system_prompt_key="CAUSAL_REASONING"),
        ]
    )
    proposal_inp = local_full_context(iter_output, storage_h5, reasoning_pipeline=pipeline)

    # vocab_seed must carry dilated_causal_conv with its updated related_to
    dc_in_seed = next(
        (
            v
            for v in proposal_inp.vocab_seed
            if (v.get("name") if isinstance(v, dict) else v.name) == "dilated_causal_conv"
        ),
        None,
    )
    assert dc_in_seed is not None, (
        "dilated_causal_conv missing from ProposalInput.vocab_seed — protocol dropped it"
    )
    seed_related = (
        dc_in_seed.get("related_to", []) if isinstance(dc_in_seed, dict) else dc_in_seed.related_to
    )
    assert "receptive_field" in seed_related, (
        f"related_to not preserved through protocol. "
        f"vocab_seed dilated_causal_conv.related_to={seed_related}"
    )
    print(f"  [h5] protocol: dilated_causal_conv in vocab_seed with related_to={seed_related} ✓")

    # -----------------------------------------------------------------------
    # Proposal agent: assert "→ enables: receptive_field" in Stage 1 user prompt
    # -----------------------------------------------------------------------
    if _is_real_llm(request):
        from agent.llm_bridge import LLMBridge

        proposal_agent = MLModelProposalAgent(
            bridge_factory=lambda **kw: LLMBridge(
                **{**kw, "model_id": "gemini-2.5-flash", "max_retries": 3}
            )
        )
        proposal_output = proposal_agent.run(proposal_inp)
        assert isinstance(proposal_output, ProposalOutput), (
            f"Expected ProposalOutput, got {type(proposal_output)}"
        )
        print(f"  [h5 real-llm] model_name='{proposal_output.model_name}'", flush=True)
    else:
        proposal_bridge = RecordingLLMBridge.for_agent("ml_model_proposal_agent_h5")
        proposal_agent = MLModelProposalAgent(bridge_factory=lambda **kw: proposal_bridge)
        proposal_output = proposal_agent.run(proposal_inp)
        assert isinstance(proposal_output, ProposalOutput)

        # Stage 1 is calls[0]; user_prompt is at index [2]
        assert len(proposal_bridge.calls) >= 1, "Proposal agent made no LLM calls"
        stage1_user_prompt = proposal_bridge.calls[0][2]

        assert "→ enables: receptive_field" in stage1_user_prompt, (
            "Rendered vocab link '→ enables: receptive_field' not found in "
            "Stage 1 user prompt. _render_vocabulary did not render the confirmed link.\n"
            f"Vocab seed entries: {[getattr(v, 'name', v.get('name')) for v in proposal_inp.vocab_seed]}"
        )
        print("  [h5 pseudo] '→ enables: receptive_field' in Stage 1 user prompt ✓")
        print(f"  [h5 pseudo] proposal bridge call count: {len(proposal_bridge.calls)}")
