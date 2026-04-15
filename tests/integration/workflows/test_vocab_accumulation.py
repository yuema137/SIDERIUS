"""
Dual-mode integration tests: vocabulary accumulation and candidate promotion.

H.1 — Two-iteration accumulation (existing):
  Verifies that runtime_vocab grows monotonically across two iterations and that
  the protocol maps iter 1's vocab into ProposalInput.vocab_seed.

H.2 — Three-iteration candidate promotion (new):
  Verifies the full promotion pipeline end-to-end: a feature candidate proposed
  in three successive iterations accumulates seen_in_runs and is promoted to
  canonical tier on the third iteration. Dedup runs and correctly keeps the entry.

  The key wiring exercised:
    - proposed_by_run injection (Bug 1 fix): interpretation agent injects
      proposed_by_run = model_name before calling build_runtime_vocab
    - seen_in_runs accumulation across iterations via model_knowledge_cache carry-forward
    - promote_candidates() firing at seen_in_runs length == 3
    - _dedup_promoted() running and keeping a genuinely new canonical entry

  Pseudo mode uses fake ModelRunSummary objects (no GPU) and canned LLM responses.
  Real mode (--real-llm) uses real Gemini API calls with the same fake summaries.

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
        {"component": "dilated_causal_conv", "from_model_type": "wavenet",
         "contribution_evidence": "Core mechanism of wavenet's 5.576 score."},
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
        {"component": "focal_loss", "from_model_type": "wavenet",
         "contribution_evidence": "Focal loss improved wavenet by +0.35."},
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
        {"component": "dilated_causal_conv", "from_model_type": "wavenet",
         "contribution_evidence": "Backbone from wavenet."},
        {"component": "focal_loss", "from_model_type": "spectral_net",
         "contribution_evidence": "Maintained from spectral_net."},
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
    sg_iter1 = next(
        (v for v in iter1_output.runtime_vocab if v.name == "spectral_gating"), None
    )
    assert sg_iter1 is not None, "spectral_gating missing from runtime_vocab after iter 1"
    assert sg_iter1.tier == "candidate", f"Expected candidate, got {sg_iter1.tier!r}"
    assert "attn_wavenet" in sg_iter1.seen_in_runs, \
        f"proposed_by_run injection failed: seen_in_runs={sg_iter1.seen_in_runs}"
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

    sg_iter2 = next(
        (v for v in iter2_output.runtime_vocab if v.name == "spectral_gating"), None
    )
    assert sg_iter2 is not None, "spectral_gating missing from runtime_vocab after iter 2"
    assert sg_iter2.tier == "candidate", \
        f"Promoted too early (only 2 runs): tier={sg_iter2.tier!r}"
    assert "spectral_net" in sg_iter2.seen_in_runs, \
        f"spectral_net not added to seen_in_runs: {sg_iter2.seen_in_runs}"
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

    sg_iter3 = next(
        (v for v in iter3_output.runtime_vocab if v.name == "spectral_gating"), None
    )
    assert sg_iter3 is not None, "spectral_gating missing from runtime_vocab after iter 3"
    assert sg_iter3.tier == "canonical", (
        f"spectral_gating not promoted after 3 runs: "
        f"tier={sg_iter3.tier!r}, seen_in_runs={sg_iter3.seen_in_runs}"
    )
    assert len(sg_iter3.seen_in_runs) == 3
    assert "wavelet_net" in sg_iter3.seen_in_runs

    # vocab_changes must record the promotion event
    assert iter3_output.vocab_changes, \
        "vocab_changes is empty — promotion not logged"
    promo_logged = any("spectral_gating" in change for change in iter3_output.vocab_changes)
    assert promo_logged, (
        f"spectral_gating promotion not in vocab_changes: {iter3_output.vocab_changes}"
    )

    print(f"  [iter 3] CONFIRMED spectral_gating.seen_in_runs={sg_iter3.seen_in_runs}")
    print(f"  [iter 3] tier={sg_iter3.tier!r} ✓  vocab_changes={iter3_output.vocab_changes}")
