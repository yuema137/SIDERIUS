"""Tier-1 integration test for Commit 6.3 — the Knowledge Accumulator at iter 14.

Drives a 14-iteration mock-LLM chain through ``result_interpretation_agent``
to verify the three Pre-Commit Checklist targets in §8 Commit 6.3 of
``docs/audit_and_optimize_token_usage_and_growth.md``:

  1. **Frozen-cache regression** — 9 of 12 model_types are stable for all 14
     iters. Each should incur exactly one per_model LLM call (iter 1 cache
     miss) and zero consolidator calls. Iter 2..14 must reuse the cached
     entry verbatim.
  2. **Bounded-size targets (Gate G1.5c)** at iter 14:
        ``model_knowledge_cache``        ≤ 60 KB
        derived ``expert_context_block`` ≤ 12 KB
        derived ``non_candidates_overview`` ≤ 30 KB
  3. **Memory retention (Gate G3 prereq)** — a *strong* key finding and a
     unique ``ErrorSignature`` seeded at iter 2 must both survive to iter 14
     and remain citable in m00's final cache entry.

The test uses a system-prompt-routed mock bridge (same pattern as
``tests/unit/agent/result_interpretation_agent/test_dispatcher_wiring.py``).
The consolidator mock parses the prompt's PRIOR / NEW items and emits a
schema-valid ``_MergeDecision`` so the production code path (including the
strength-ranked overflow cap) is exercised end-to-end.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from agent.prompt_templates.proposal import render_expert_context
from agent.schemas.cache_entry import CacheEntry
from agent.schemas.interpretation import (
    InterpretationInput,
    InterpretationOutput,
    ModelRunSummary,
)
from agent.schemas.proposal import ExpertContextItem
from nodes.result_interpretation_agent import ResultInterpretationAgent


# ---------------------------------------------------------------------------
# Test constants
# ---------------------------------------------------------------------------

N_ITERS = 14
MODEL_TYPES = [f"m{i:02d}" for i in range(12)]
ACTIVE = MODEL_TYPES[:3]    # top-3 by best_score → always re-summarised
FROZEN = MODEL_TYPES[3:]    # m03..m11 → cache-miss only at iter 1, frozen after

# Memory-retention seed (Gate G3 prereq). Must persist from iter 2 to iter 14.
SEED_FINDING = "SEED2: lr>5e-3 explodes when batch_size<8 (3 confirmed runs)"
SEED_ERR_TYPE = "torch.cuda.OutOfMemoryError"
SEED_ERR_FRAME = "training.py:42:forward"
SEED_ERR_MSG = "CUDA OOM at batch_size=64 lr=7e-3"

# Size targets — Gate G1.5c.
MAX_CACHE_BYTES = 60 * 1024
MAX_EXPERT_CTX_BYTES = 12 * 1024
MAX_NON_CANDIDATES_BYTES = 30 * 1024

# A compact ~280-char fake description per model so non_candidates_overview
# reconstruction includes a realistic description-size contribution.
def _fake_description(mt: str) -> str:
    return (
        f"### {mt}\n"
        f"Architecture {mt} is a synthetic test fixture used by the Knowledge\n"
        f"Accumulator integration suite. It mimics a small CNN-style denoiser\n"
        f"with hidden_dim=8 and forward shape [B, T] int -> [B, 256, T] float."
    )


# Regex patterns matching the consolidator's user prompt format produced by
# ``_format_prior_for_prompt`` / ``_format_new_for_prompt`` in
# ``agent/cache_consolidator.py``.
_PRIOR_RE = re.compile(
    r"P\d+\. statement=(\".*?(?<!\\)\") evidence_iters=\[([^\]]*)\] strength='(\w+)'"
)
_NEW_RE = re.compile(
    r"N\d+\. statement=(\".*?(?<!\\)\") current_iter=(\d+)"
)


# ---------------------------------------------------------------------------
# Mock-bridge dispatch
# ---------------------------------------------------------------------------


def _per_model_response(iter_n: int, mt: str) -> Dict[str, Any]:
    """Mock per_model LLM response for one (iter, mt).

    Sizes are kept tight so the cumulative cache stays under the 60 KB budget
    even after 14 iters of accumulation across 12 model_types. The iter-2
    seed for m00 plants both a unique key_findings statement and a unique
    error_signature — the consolidator mock below promotes that finding to
    strength=strong so it survives the rank-prune across the remaining 12
    iters.
    """
    base_finding = f"{mt}-i{iter_n}: minor trial gain"
    key_findings: List[str] = [base_finding]
    err_sigs: List[Dict[str, Any]] = []
    if iter_n == 2 and mt == "m00":
        # Seed the strong finding (first slot) + the unique error signature.
        key_findings = [SEED_FINDING, base_finding]
        err_sigs = [
            {
                "error_type": SEED_ERR_TYPE,
                "short_message": SEED_ERR_MSG,
                "last_frames": [SEED_ERR_FRAME, "model.py:18:_forward"],
                "failure_class": "vram",
                "top_user_frame": SEED_ERR_FRAME,
                "evidence_iters": [iter_n],
            }
        ]
    return {
        "key_findings": key_findings,
        "bottlenecks": [f"{mt}-i{iter_n}: capacity ceiling at depth=3"],
        "best_config_analysis": f"{mt} i{iter_n}: depth=4, focal gamma=2",
        "score_trend": f"{mt} i{iter_n}: trending flat",
        "per_file_analysis": f"{mt} i{iter_n}: file-7 lags",
        "data_sensitivity": f"{mt} i{iter_n}: stable across seeds",
        "efficiency_assessment": f"{mt} i{iter_n}: 200ms/seg",
        "strategy_assessment": f"{mt} i{iter_n}: keep current strategy",
        "take_home_message": f"{mt} i{iter_n}: incremental",
        "error_signatures": err_sigs,
    }


def _synthesis_response() -> Dict[str, Any]:
    return {
        "key_findings": ["cross-model: m00 leads"],
        "bottlenecks": ["cross-model: shared VRAM ceiling"],
        "per_file_comparison": "file-7 across all candidates",
        "efficiency_comparison": "m00 highest score-per-param",
        "take_home_message": "iterate on m00",
    }


def _consolidator_response(user_prompt: str) -> Dict[str, Any]:
    """Mock the ``cache_consolidator.list_merge`` LLM call.

    Strategy: echo every PRIOR item verbatim (preserving its evidence_iters
    and strength), append every NEW item with current_iter as evidence. The
    SEED_FINDING statement is promoted to strength=``strong`` so it ranks #1
    under the consolidator's deterministic _rank_findings tie-breaker
    (strength desc, evidence_len desc, recency desc) — the >8 overflow
    cap therefore prunes other items first, never the seed.
    """
    survivors: List[Dict[str, Any]] = []
    for stmt_json, iters_str, strength in _PRIOR_RE.findall(user_prompt):
        stmt = json.loads(stmt_json)
        iters = [int(x) for x in iters_str.split(",") if x.strip()]
        if SEED_FINDING in stmt:
            strength = "strong"
        survivors.append(
            {
                "statement": stmt,
                "evidence_iters": iters or [0],
                "strength": strength,
            }
        )
    for stmt_json, current_iter in _NEW_RE.findall(user_prompt):
        stmt = json.loads(stmt_json)
        strength = "strong" if SEED_FINDING in stmt else "moderate"
        survivors.append(
            {
                "statement": stmt,
                "evidence_iters": [int(current_iter)],
                "strength": strength,
            }
        )
    return {"survivors": survivors, "archived": []}


def _build_dispatch(bridge):
    """Build the system-prompt-routed dispatch closure.

    Reads ``bridge._current_iter`` (set by the harness before each
    ``agent.run`` call) and ``bridge._call_log`` (a list of per-call
    metadata used by the test assertions).
    """

    def _dispatch(system_prompt: str, user_prompt: str, **kwargs) -> Dict[str, Any]:
        label = kwargs.get("label", "")
        if "semantic merge engine" in system_prompt:
            bridge._call_log.append(
                {"kind": "consolidator", "iter": bridge._current_iter, "prompt": user_prompt}
            )
            return _consolidator_response(user_prompt)
        if label == "interpretation.synthesis":
            bridge._call_log.append(
                {"kind": "synthesis", "iter": bridge._current_iter}
            )
            return _synthesis_response()
        if label == "interpretation.per_model":
            # Extract model_type from the prompt's "## Model: {mt}" header.
            mt = None
            for candidate in MODEL_TYPES:
                if f"## Model: {candidate}" in user_prompt:
                    mt = candidate
                    break
            assert mt is not None, "per_model prompt missing '## Model: <mt>' header"
            bridge._call_log.append(
                {"kind": "per_model", "iter": bridge._current_iter, "model_type": mt}
            )
            return _per_model_response(bridge._current_iter, mt)
        return {"key_findings": [], "bottlenecks": []}

    return _dispatch


# ---------------------------------------------------------------------------
# Harness helpers
# ---------------------------------------------------------------------------


def _make_summary(mt: str, best_score: float, completed_rounds: int) -> ModelRunSummary:
    return ModelRunSummary(
        model_type=mt,
        run_name="vacc",
        status="completed",
        completed_rounds=completed_rounds,
        best_denoising_score=best_score,
        worst_denoising_score=best_score - 0.6,
        best_config={"model_config": {}, "train_config": {}, "loss_config": {}},
        round_scores=[best_score - 0.5, best_score - 0.2, best_score],
        round_conclusions=["s1", "s2", "s3"],
        model_description=_fake_description(mt),
    )


def _make_input(
    *,
    summaries: List[ModelRunSummary],
    cache: Dict[str, Any],
    iteration: int,
    workspace: str,
) -> InterpretationInput:
    return InterpretationInput(
        summaries=summaries,
        model_knowledge_cache=cache,
        model_types=MODEL_TYPES,  # all 12 every iter — keeps frozen models in the loop
        iteration=iteration,
        active_model_top_k=3,
        active_model_last_n=0,
        active_model_score_delta=999.0,
        storage={
            "backend": "local",
            "local": {"workspace": workspace, "run_name": "racc"},
        },
    )


# ---------------------------------------------------------------------------
# non_candidates_overview reconstruction (mirrors ml_model_proposal_agent.py
# lines 1043-1061; copied verbatim to keep this test independent of the
# proposer agent's wiring while measuring the same on-the-wire payload).
# ---------------------------------------------------------------------------

_CACHE_TEXT_FIELDS = ("key_findings", "bottlenecks", "score_trend", "strategy_assessment")


def _reconstruct_non_candidates_overview(
    cache: Dict[str, Any],
    descriptions: Dict[str, str],
    per_best: Dict[str, Any],
    candidate_names: set,
) -> List[Dict[str, Any]]:
    overview: List[Dict[str, Any]] = []
    for mt in MODEL_TYPES:
        if mt in candidate_names:
            continue
        entry = cache.get(mt) or {}
        item: Dict[str, Any] = {
            "model_type": mt,
            "best_score": per_best.get(mt),
            "description": descriptions.get(mt),
        }
        for field in _CACHE_TEXT_FIELDS:
            if entry.get(field):
                item[field] = entry[field]
        overview.append(item)
    return overview


def _reconstruct_expert_context_block(cache: Dict[str, Any]) -> str:
    """Build a synthetic expert_context_block from the 12 cache entries' top
    key_finding each. This is the same wiring shape the workflow eventually
    builds — one ExpertContextItem per model surfaced as an empirical finding.
    Source-level dehydration (Commit 6.3) bounds this block by bounding the
    cache itself.
    """
    items: List[ExpertContextItem] = []
    for mt in MODEL_TYPES:
        entry = cache.get(mt) or {}
        findings = entry.get("key_findings") or []
        if not findings:
            continue
        first = findings[0]
        if isinstance(first, str):
            statement = first
        elif isinstance(first, dict) and isinstance(first.get("statement"), str):
            statement = first["statement"]
        else:
            continue
        items.append(
            ExpertContextItem(
                source="result_interpretation_agent",
                kind="empirical",
                content=statement,
                cite_id=f"cache:{mt}",
                confidence=0.7,
            )
        )
    return render_expert_context(items)


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.fixture
def chain_run(tmp_path):
    """Run the 14-iter chain and return final state + audit data."""
    with patch("nodes.result_interpretation_agent.LLMBridge") as MockBridge:
        bridge = MockBridge.return_value
        bridge._current_iter = 0
        bridge._call_log = []
        bridge.generate.side_effect = _build_dispatch(bridge)
        bridge.emit_marker = MagicMock()

        agent = ResultInterpretationAgent(provider="gemini", model_id="test")
        agent.bridge = bridge

        cache: Dict[str, Any] = {}

        # Use a stable descending score vector so the active set
        # (top_k=3) is always m00, m01, m02 across all 14 iters.
        base_scores = {mt: 10.0 - i for i, mt in enumerate(MODEL_TYPES)}

        for iter_n in range(1, N_ITERS + 1):
            bridge._current_iter = iter_n

            if iter_n == 1:
                # Cold start: every model needs a summary so cache-miss
                # builds an entry for all 12.
                summaries = [
                    _make_summary(
                        mt,
                        best_score=base_scores[mt],
                        completed_rounds=1,
                    )
                    for mt in MODEL_TYPES
                ]
            else:
                # Active models get fresh summaries with one extra
                # completed_round so should_recall_per_model returns True
                # via the round-count delta. Frozen models get nothing.
                summaries = [
                    _make_summary(
                        mt,
                        best_score=base_scores[mt],
                        completed_rounds=iter_n,
                    )
                    for mt in ACTIVE
                ]

            inp = _make_input(
                summaries=summaries,
                cache=cache,
                iteration=iter_n,
                workspace=str(tmp_path),
            )
            out: InterpretationOutput = agent.run(inp)
            cache = out.model_knowledge_cache  # carry forward

        return {
            "agent": agent,
            "bridge": bridge,
            "final_cache": cache,
            "workspace": str(tmp_path),
        }


def test_frozen_cache_skips_llm_and_consolidator(chain_run):
    """9 stable models incur exactly 1 per_model call (iter-1 cache miss)
    and zero consolidator calls across all 14 iters."""
    call_log = chain_run["bridge"]._call_log

    per_model_calls_by_mt: Dict[str, List[int]] = {mt: [] for mt in MODEL_TYPES}
    for c in call_log:
        if c["kind"] == "per_model":
            per_model_calls_by_mt[c["model_type"]].append(c["iter"])

    for mt in FROZEN:
        assert per_model_calls_by_mt[mt] == [1], (
            f"frozen model {mt} should only be summarised once (iter 1), "
            f"got iters: {per_model_calls_by_mt[mt]}"
        )

    # Active models: per_model fires once at iter 1 (cache miss) plus
    # once for every iter 2..14 (cache-hit-with-active-recall) = 14 calls.
    for mt in ACTIVE:
        assert per_model_calls_by_mt[mt] == list(range(1, N_ITERS + 1)), (
            f"active model {mt} should be re-summarised every iter, "
            f"got iters: {per_model_calls_by_mt[mt]}"
        )

    # Consolidator must NEVER reference a frozen model: the consolidator
    # only fires inside the active-cache-hit branch, and frozen mts skip
    # that branch entirely.
    for c in call_log:
        if c["kind"] != "consolidator":
            continue
        for mt in FROZEN:
            assert f"MODEL_TYPE: {mt}" not in c["prompt"], (
                f"consolidator unexpectedly invoked for frozen model {mt} "
                f"at iter {c['iter']}"
            )


def test_memory_retention_seed_survives_to_iter_14(chain_run):
    """The strong finding + unique error signature seeded at iter 2 must
    still be present and citable in m00's final cache entry."""
    cache = chain_run["final_cache"]
    m00 = cache["m00"]

    # Validate the modern CacheEntry shape — Pydantic enforces every
    # invariant we rely on (non-empty evidence_iters, strength enum, ...).
    entry = CacheEntry.model_validate(_strip_stats(m00) | {"model_type": "m00"})

    # 1. Strong finding still there.
    statements = [f.statement for f in entry.key_findings]
    assert any(SEED_FINDING in s for s in statements), (
        f"seed strong finding lost between iter 2 and iter {N_ITERS}; "
        f"surviving key_findings statements: {statements}"
    )
    seed_idx = next(
        i for i, f in enumerate(entry.key_findings) if SEED_FINDING in f.statement
    )
    assert entry.key_findings[seed_idx].strength == "strong", (
        "seed finding lost its strong-strength promotion"
    )
    assert 2 in entry.key_findings[seed_idx].evidence_iters, (
        "seed finding lost its iter-2 evidence origin"
    )

    # 2. Unique error signature still there (Gate G3 set-merge invariant).
    sig_keys = [(s.failure_class, s.top_user_frame, s.error_type) for s in entry.error_signatures]
    assert ("vram", SEED_ERR_FRAME, SEED_ERR_TYPE) in sig_keys, (
        f"seed ErrorSignature missing at iter {N_ITERS}; surviving keys: {sig_keys}"
    )


def test_iter_14_size_targets(chain_run, capsys):
    """All three downstream block sizes must stay under their Gate G1.5c
    budgets after 14 iters of accumulation."""
    cache = chain_run["final_cache"]

    # 1. model_knowledge_cache — directly measure JSON-dump size.
    cache_bytes = len(json.dumps(cache, default=str).encode("utf-8"))

    # 2. non_candidates_overview — reconstruct via the proposer's logic.
    descriptions = {mt: _fake_description(mt) for mt in MODEL_TYPES}
    per_best = {mt: 10.0 - i for i, mt in enumerate(MODEL_TYPES)}
    nco = _reconstruct_non_candidates_overview(
        cache=cache,
        descriptions=descriptions,
        per_best=per_best,
        candidate_names=set(ACTIVE),
    )
    nco_bytes = len(json.dumps(nco, default=str).encode("utf-8"))

    # 3. expert_context_block — synthesise from cache top-findings and
    # run through render_expert_context.
    ecb = _reconstruct_expert_context_block(cache)
    ecb_bytes = len(ecb.encode("utf-8"))

    # Report — surfaced to the user via -s.
    print(
        f"\n[iter {N_ITERS} payload sizes — Gate G1.5c budgets]\n"
        f"  model_knowledge_cache    : {cache_bytes:>6} B  "
        f"({cache_bytes / 1024:5.2f} KB)   budget ≤ {MAX_CACHE_BYTES // 1024} KB\n"
        f"  non_candidates_overview  : {nco_bytes:>6} B  "
        f"({nco_bytes / 1024:5.2f} KB)   budget ≤ {MAX_NON_CANDIDATES_BYTES // 1024} KB\n"
        f"  expert_context_block     : {ecb_bytes:>6} B  "
        f"({ecb_bytes / 1024:5.2f} KB)   budget ≤ {MAX_EXPERT_CTX_BYTES // 1024} KB"
    )

    assert cache_bytes <= MAX_CACHE_BYTES, (
        f"model_knowledge_cache = {cache_bytes} B > {MAX_CACHE_BYTES} B budget"
    )
    assert nco_bytes <= MAX_NON_CANDIDATES_BYTES, (
        f"non_candidates_overview = {nco_bytes} B > {MAX_NON_CANDIDATES_BYTES} B budget"
    )
    assert ecb_bytes <= MAX_EXPERT_CTX_BYTES, (
        f"expert_context_block = {ecb_bytes} B > {MAX_EXPERT_CTX_BYTES} B budget"
    )


# ---------------------------------------------------------------------------
# Local helpers used only by the assertions above
# ---------------------------------------------------------------------------


def _strip_stats(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Remove the legacy ``_stats`` key + the modern ``model_type`` so
    :meth:`CacheEntry.model_validate` accepts the remainder directly. The
    caller re-injects ``model_type``."""
    return {k: v for k, v in entry.items() if k not in {"_stats", "model_type"}}
