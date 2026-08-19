"""End-to-end Pre-Commit Checklist tests for Commit 6.1 (T4 wiring).

Covers the four checks from
``docs/audit_and_optimize_token_usage_and_growth.md`` §8 Commit 6.1:

  1. **per_model call-count regression** (axis 2): with a 12-model cache
     where 9 models are stable, the dispatcher issues exactly 3 LLM
     calls labelled ``interpretation.per_model`` (matching the active
     set size), not 12.
  2. **Audit-log marker emission**: skipped per_model calls produce
     countable marker rows via ``bridge.emit_marker`` with label
     ``interpretation.per_model_skipped``. The savings are therefore
     measurable in ``tools/build_token_baseline_report.py``'s output.
  3. **Synthesis-prompt size regression** (axis 1): with a 13-model
     cache mimicking iter 13 of explore V12, the new synthesis user
     prompt is < 15 K chars (vs. the V12 baseline of ~40 K).
  4. **Behavioural test**: every model_type in the cache appears in the
     synthesis prompt at least once (active = full multi-section block,
     compressed = one-line takeaway under the historical-block header)
     — no model is silently dropped.

LLM calls are mocked via the same fixture pattern as
``test_interpretation_agent.py`` (system-prompt-routed dispatcher).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent.schemas.interpretation import (
    InterpretationInput,
    ModelRunSummary,
)
from nodes.result_interpretation_agent import ResultInterpretationAgent
from tests.helpers.metric_fixtures import shipped_spec

# ---------------------------------------------------------------------------
# Fixtures (mirror test_interpretation_agent.py patterns)
# ---------------------------------------------------------------------------

FAKE_PER_MODEL_RESPONSE = {
    "key_findings": [
        "focal loss with gamma=2 consistently outperforms ce by ~0.05",
        "increasing depth beyond 3 yields diminishing returns",
    ],
    "bottlenecks": [
        "architecture capacity ceiling at depth=3 — score plateaued",
    ],
    "best_config_analysis": "Depth 4 with focal loss gamma=2 yielded the best.",
    "score_trend": "Scores improved initially but plateaued after depth=3.",
}

FAKE_SYNTHESIS_RESPONSE = {
    "key_findings": ["multi-model finding"],
    "bottlenecks": ["multi-model bottleneck"],
    "take_home_message": "Synthesised conclusion across all models.",
}

# Commit 6.3 adds a third LLM call site — the cache consolidator's
# list-merge. Active-cache-hit dispatch in the agent invokes
# ``bridge.generate`` with the consolidator's system prompt for each
# non-empty (prior, new) list field. We return a minimal valid
# ``_MergeDecision`` JSON: one survivor (the first new statement) and an
# empty archive. The actual merge semantics are pinned by Commit 6.3's own
# unit tests; here we just need a schema-valid response so the dispatcher's
# call-count assertions stay clean.
FAKE_LIST_MERGE_RESPONSE = {
    "survivors": [
        {"statement": "consolidated", "evidence_iters": [1], "strength": "moderate"},
    ],
    "archived": [],
}


def _llm_dispatch(system_prompt: str, user_prompt: str, **kwargs) -> dict:
    """Route mock LLM calls to the right fake response."""
    if "ONE model architecture" in system_prompt:
        return FAKE_PER_MODEL_RESPONSE
    if "semantic merge engine" in system_prompt:
        return FAKE_LIST_MERGE_RESPONSE
    return FAKE_SYNTHESIS_RESPONSE


@pytest.fixture
def agent():
    with patch("nodes.result_interpretation_agent.LLMBridge") as MockBridge:
        MockBridge.return_value.generate.side_effect = _llm_dispatch
        a = ResultInterpretationAgent(provider="gemini", model_id="test-model")
        a.bridge = MockBridge.return_value
        yield a


# ---------------------------------------------------------------------------
# Cache builders
# ---------------------------------------------------------------------------


def _make_cache_entry(model_type: str, best_score: float, completed_rounds: int = 3) -> dict:
    """A self-sufficient cache entry mimicking what the agent writes after
    a per_model LLM call. Includes ``_stats.model_description`` so the
    description loader's Priority 2 path is taken — no filesystem hit."""
    return {
        "key_findings": [
            f"{model_type}: focal loss helps by ~0.05",
            f"{model_type}: depth>3 plateaus",
        ],
        "bottlenecks": [
            f"{model_type}: capacity ceiling at depth=3",
        ],
        "best_config_analysis": (f"{model_type}: best at depth=4 with focal loss gamma=2."),
        "score_trend": (f"{model_type}: scores improved initially, then plateau."),
        "_stats": {
            "best_denoising_score": best_score,
            "worst_denoising_score": best_score - 0.6,
            "best_file_vector": None,
            "best_score_table": None,
            "best_model_params": None,
            "completed_rounds": completed_rounds,
            "best_config": {"model_config": {}, "train_config": {}},
            "formal_score": None,
            "model_description": f"{model_type} description (synthetic).",
        },
    }


def _make_summary(model_type: str, best_score: float, completed_rounds: int) -> ModelRunSummary:
    return ModelRunSummary(
        model_type=model_type,
        run_name="vtest",
        status="completed",
        completed_rounds=completed_rounds,
        best_denoising_score=best_score,
        worst_denoising_score=best_score - 0.6,
        best_config={"model_config": {}, "train_config": {}, "loss_config": {}},
        round_scores=[best_score - 0.5, best_score - 0.2, best_score],
        round_conclusions=["s1", "s2", "s3"],
        model_description=f"{model_type} description (synthetic).",
    )


def _make_input(
    *,
    cache: dict,
    summaries: list,
    workspace: str,
    top_k: int = 3,
    last_n: int = 0,
    score_delta: float = 999.0,
) -> InterpretationInput:
    """Build an InterpretationInput with explicit Stability Filter knobs.

    Defaults disable Last-N (``last_n=0``) and Delta-Δ (``score_delta=999``)
    so the active set reduces to Top-K — making the call-count assertion
    deterministic.
    """
    return InterpretationInput(
        summaries=summaries,
        model_knowledge_cache=cache,
        # Step 09a C2 — a score-bearing interpretation REQUIRES the run's
        # bound MetricSpec; ordering direction is never assumed. The shipped
        # TIDMAD spec is `higher`, so every assertion below is unchanged.
        metric_spec=shipped_spec(),
        active_model_top_k=top_k,
        active_model_last_n=last_n,
        active_model_score_delta=score_delta,
        storage={
            "backend": "local",
            "local": {"workspace": workspace, "run_name": "rdisp"},
        },
    )


# ---------------------------------------------------------------------------
# (1) per_model call-count regression — axis 2
# ---------------------------------------------------------------------------


def test_per_model_call_count_equals_active_set_size(agent, tmp_path):
    """12-model cache, 9 stable, 3 active → exactly 3 per_model LLM calls.

    Setup:
      - 12 cache entries with distinct best_scores (m00 highest, m11 lowest).
      - top_k=3, last_n=0, score_delta=999 → active set = top 3 by cached
        score = {m00, m01, m02}.
      - Pass current summaries for m00/m01/m02 with new completed_rounds
        > cached, so should_recall_per_model returns True for them.
      - The other 9 (m03..m11) have cache + no current summary +
        not-in-active-set → should_recall_per_model returns False → skip.
    Expected: 3 ``interpretation.per_model`` calls + 1
    ``interpretation.synthesis`` call = 4 total bridge.generate calls.
    """
    cache = {
        f"m{i:02d}": _make_cache_entry(f"m{i:02d}", best_score=10.0 - i, completed_rounds=3)
        for i in range(12)
    }
    # Pass new summaries ONLY for the top-3 (m00, m01, m02), each with
    # completed_rounds=4 (one more than cached) so should_recall returns True.
    active_mts = ["m00", "m01", "m02"]
    summaries = [
        _make_summary(mt, best_score=10.0 - i, completed_rounds=4)
        for i, mt in enumerate(active_mts)
    ]

    inp = _make_input(cache=cache, summaries=summaries, workspace=str(tmp_path))
    agent.run(inp)

    # Split the recorded LLM calls by label kwarg.
    calls = agent.bridge.generate.call_args_list
    per_model_calls = [c for c in calls if c.kwargs.get("label") == "interpretation.per_model"]
    synthesis_calls = [c for c in calls if c.kwargs.get("label") == "interpretation.synthesis"]

    assert len(per_model_calls) == 3, (
        f"expected 3 per_model LLM calls (one per active model), "
        f"got {len(per_model_calls)}; 9-of-12 stable models must be skipped"
    )
    assert len(synthesis_calls) == 1, (
        f"expected exactly 1 synthesis call, got {len(synthesis_calls)}"
    )
    # Commit 6.3: each active-cache-hit also invokes the consolidator's
    # list-merge for both non-empty list fields (key_findings + bottlenecks)
    # = 2 calls per active model. Total: 3 per_model + 3×2 consolidator + 1
    # synthesis = 10.
    consolidator_calls = [
        c for c in calls if c.kwargs.get("label") == "cache_consolidator.list_merge"
    ]
    assert len(consolidator_calls) == 6, (
        f"expected 6 consolidator list-merge calls (2 per active model), "
        f"got {len(consolidator_calls)}"
    )
    assert agent.bridge.generate.call_count == 10


# ---------------------------------------------------------------------------
# (2) Audit-log: skipped calls produce countable marker rows
# ---------------------------------------------------------------------------


def test_skipped_calls_emit_audit_marker(agent, tmp_path):
    """Each skipped per_model call must call ``bridge.emit_marker`` with
    label ``interpretation.per_model_skipped`` and the right reason/mt
    extra payload, so build_token_baseline_report.py can count savings."""
    cache = {f"m{i:02d}": _make_cache_entry(f"m{i:02d}", best_score=10.0 - i) for i in range(12)}
    active_mts = ["m00", "m01", "m02"]
    summaries = [
        _make_summary(mt, best_score=10.0 - i, completed_rounds=4)
        for i, mt in enumerate(active_mts)
    ]

    inp = _make_input(cache=cache, summaries=summaries, workspace=str(tmp_path))
    agent.run(inp)

    # 9 stable models → 9 emit_marker calls.
    marker_calls = agent.bridge.emit_marker.call_args_list
    assert len(marker_calls) == 9, (
        f"expected 9 skip markers (12 cache - 3 active), got {len(marker_calls)}"
    )
    # Every marker carries the correct label + reason.
    for call in marker_calls:
        assert call.kwargs["label"] == "interpretation.per_model_skipped"
        assert call.kwargs["extra"]["reason"] == "stable"
        assert call.kwargs["extra"]["model_type"].startswith("m")
    # Each of the 9 skipped model_types is represented exactly once.
    skipped_mts = {c.kwargs["extra"]["model_type"] for c in marker_calls}
    assert skipped_mts == {f"m{i:02d}" for i in range(3, 12)}


# ---------------------------------------------------------------------------
# (3) Synthesis-prompt size regression — axis 1
# ---------------------------------------------------------------------------


def test_synthesis_prompt_size_under_15k_for_13_models(agent, tmp_path):
    """13-model cache (iter-13 of V12 mimicry): synthesis user prompt < 15 K
    chars. V12 baseline was ~40 K → target is at least a 2.6× compression.
    """
    cache = {f"m{i:02d}": _make_cache_entry(f"m{i:02d}", best_score=10.0 - i) for i in range(13)}
    # No current summaries → active set = top-3 by cached score
    # (= {m00, m01, m02}); the other 10 are compressed.
    inp = _make_input(
        cache=cache, summaries=[], workspace=str(tmp_path), top_k=3, last_n=0, score_delta=999.0
    )
    agent.run(inp)

    # Find the synthesis call's user prompt.
    synthesis_calls = [
        c
        for c in agent.bridge.generate.call_args_list
        if c.kwargs.get("label") == "interpretation.synthesis"
    ]
    assert len(synthesis_calls) == 1
    user_prompt = synthesis_calls[0].args[1]

    prompt_chars = len(user_prompt)
    v12_baseline = 40_000  # docs/audit Rev 7 measurement
    compression_ratio = v12_baseline / max(prompt_chars, 1)
    assert prompt_chars < 15_000, (
        f"synthesis user prompt is {prompt_chars} chars, "
        f"target < 15000 (V12 baseline ~40000); "
        f"compression ratio achieved: {compression_ratio:.2f}×"
    )


# ---------------------------------------------------------------------------
# (4) Behavioural — every model_type appears in the synthesis prompt
# ---------------------------------------------------------------------------


def test_synthesis_prompt_mentions_every_model_type(agent, tmp_path):
    """Active = full block; compressed = one-liner under the historical
    header. Either way, every model_type must be visible in the synthesis
    prompt at least once — no model is silently dropped from context."""
    cache = {
        f"arch_{i:02d}": _make_cache_entry(f"arch_{i:02d}", best_score=5.0 - i * 0.1)
        for i in range(13)
    }
    inp = _make_input(
        cache=cache, summaries=[], workspace=str(tmp_path), top_k=3, last_n=0, score_delta=999.0
    )
    agent.run(inp)

    synthesis_calls = [
        c
        for c in agent.bridge.generate.call_args_list
        if c.kwargs.get("label") == "interpretation.synthesis"
    ]
    assert len(synthesis_calls) == 1
    user_prompt = synthesis_calls[0].args[1]

    missing = [mt for mt in cache if mt not in user_prompt]
    assert not missing, f"these model_types are missing from the synthesis prompt: {missing}"

    # The historical-block header is also present (T4 spec: a single line
    # at the top of the historical block).
    assert "compressed for context budget" in user_prompt
    # Active-set models render as full "## Model: arch_XX" blocks; we
    # expect 3 of those.
    full_block_count = user_prompt.count("## Model: ")
    assert full_block_count == 3, (
        f"expected 3 full-block ## Model: headers (one per active), got {full_block_count}"
    )
