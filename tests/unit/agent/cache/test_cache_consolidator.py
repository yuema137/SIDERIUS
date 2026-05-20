"""Commit 6.3 / C3 — unit tests for the LLM-powered semantic consolidator.

What this file pins (Rev 8.5):

  1. The four semantic merge rules (same-meaning, supersession, contradiction,
     distinct) — each tested with a hand-crafted mock-LLM JSON response so the
     Python routing/parsing logic is verified independently of any real LLM.
  2. Rank-prune: when survivors exceed ``LIST_FIELD_MAX_SURVIVORS``, the
     overflow is archived in a recoverable format.
  3. Fast paths bypass the LLM entirely:
       * both lists empty
       * empty prior + new statements (wrap as fresh findings)
       * prior + empty new (return unchanged)
     Each path is asserted to NOT call ``bridge.generate``.
  4. Bounded LLM-call-count: per ``consolidate()`` invocation, at most
     ``2 × |active_models|`` calls — one per list field, never more. The narrative
     and error-signature paths must not invoke the bridge at all.
  5. Deterministic-paths-untouched: ``_merge_narrative_field`` and
     ``_dedupe_error_signatures`` are invoked directly and asserted to take
     NO bridge argument; they cannot accidentally route through an LLM.
  6. Narrative replacement-with-history: ``latest`` updates monotonically;
     ``history`` accumulates prior values capped to the schema's max of 3;
     overflow archived.
  7. Error-signature strict set-merge (Gate G3 invariant): 12 distinct
     signatures preserved; 30 with duplicates dedupes correctly. NO numerical
     cap is applied at any point.
  8. Field-reconciliation: the 8-field flat dict emitted by
     ``PER_MODEL_SYSTEM_PROMPT`` parses cleanly into a ``CacheEntry`` via
     ``consolidate()``.
  9. Cache-hit-merge regression (Rev 8.2): a prior entry at iter 2 plus a new
     LLM response at iter 10 produces a merged entry where both findings
     survive when they are distinct, with correctly unioned ``evidence_iters``.
 10. Behavioural test (no signal loss): a ``strength="strong"`` finding present
     pre-consolidation is present post-consolidation.

Mock bridge protocol: tests inject a ``MockBridge`` instance that holds a
queue of pre-built JSON responses and a call counter. The consolidator's
``bridge.generate(...)`` is satisfied by duck-typing — the consolidator
never inspects anything else on the bridge object.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pytest

from agent.cache_consolidator import (
    LIST_FIELD_MAX_SURVIVORS,
    MAX_PRIOR_SUMMARY_CHARS,
    _LIST_MERGE_POLICY_EXAMPLES,
    _LIST_MERGE_SYSTEM_PROMPT,
    _build_list_merge_user_prompt,
    _dedupe_error_signatures,
    _merge_narrative_field,
    consolidate,
)
from agent.schemas.cache_entry import (
    FINDING_STATEMENT_MAX_CHARS,
    NARRATIVE_HISTORY_MAX_ENTRIES,
    CacheEntry,
    ConsolidatedFinding,
    ConsolidatedNarrative,
    ErrorSignature,
)


# ---------------------------------------------------------------------------
# Mock bridge — duck-typed; no inheritance from LLMBridge to keep tests light.
# ---------------------------------------------------------------------------


class MockBridge:
    """Replays a queue of canned JSON dicts as ``generate(...)`` responses.

    Each call pops the front of the queue, records the (system, user, label)
    triple, and returns the popped dict. If the queue is exhausted the test
    fails with a clear error — meaning the consolidator made more calls than
    the test anticipated.
    """

    def __init__(self, responses: Optional[List[Dict[str, Any]]] = None) -> None:
        self._queue: List[Dict[str, Any]] = list(responses or [])
        self.call_count: int = 0
        self.calls: List[Tuple[str, str, str]] = []

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        label: str = "unlabeled",
        components: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        self.call_count += 1
        self.calls.append((system_prompt, user_prompt, label))
        if not self._queue:
            raise AssertionError(
                f"MockBridge.generate called {self.call_count}× but the "
                f"response queue is empty (label={label!r}). The test under-"
                f"prepared the mock; pre-populate `responses=[...]` to match "
                f"the consolidator's expected call pattern."
            )
        return self._queue.pop(0)


def _bare_prior(model_type: str = "punet") -> CacheEntry:
    """A fresh empty CacheEntry — the typical 'first interpretation of a new
    model_type' state. All list fields empty; all narratives empty;
    error_signatures empty; stats empty."""
    return CacheEntry(model_type=model_type)


def _empty_new_response() -> Dict[str, Any]:
    """The 8-flat-field LLM response shape with everything blank — used to
    exercise the empty-new fast paths."""
    return {
        "key_findings": [],
        "bottlenecks": [],
        "best_config_analysis": "",
        "score_trend": "",
        "per_file_analysis": "",
        "data_sensitivity": "",
        "efficiency_assessment": "",
        "strategy_assessment": "",
        "error_signatures": [],
    }


# ===========================================================================
# Group A — Fast paths (no LLM call expected)
# ===========================================================================


def test_both_lists_empty_makes_no_llm_call() -> None:
    """Fast path: empty prior + empty new for both list fields → zero bridge
    calls; merged entry has empty list fields."""
    bridge = MockBridge(responses=[])  # No responses queued — proves no call
    prior = _bare_prior()

    merged, archived = consolidate(
        bridge,
        prior=prior,
        new_llm_response=_empty_new_response(),
        new_stats={},
        current_iter=1,
        prior_iter=0,
    )

    assert bridge.call_count == 0, (
        "Empty prior + empty new must skip the LLM merge entirely — there is "
        "nothing to classify."
    )
    assert merged.key_findings == []
    assert merged.bottlenecks == []
    assert archived == []


def test_empty_prior_with_new_statements_wraps_fresh_no_llm_call() -> None:
    """Fast path: empty prior + non-empty new → wrap each new statement as a
    fresh ConsolidatedFinding tagged with current_iter; no LLM call needed."""
    bridge = MockBridge(responses=[])
    prior = _bare_prior()
    new_resp = _empty_new_response()
    new_resp["key_findings"] = ["finding A", "finding B"]
    new_resp["bottlenecks"] = ["bottleneck X"]

    merged, archived = consolidate(
        bridge,
        prior=prior,
        new_llm_response=new_resp,
        new_stats={"best_denoising_score": -3.5},
        current_iter=5,
        prior_iter=0,
    )

    assert bridge.call_count == 0
    assert {f.statement for f in merged.key_findings} == {"finding A", "finding B"}
    assert all(f.evidence_iters == [5] for f in merged.key_findings)
    assert all(f.strength == "moderate" for f in merged.key_findings)
    assert len(merged.bottlenecks) == 1
    assert merged.bottlenecks[0].evidence_iters == [5]
    assert archived == []


def test_prior_findings_with_empty_new_returns_unchanged_no_llm_call() -> None:
    """Fast path: prior has findings, new has none → prior preserved verbatim;
    no LLM call needed."""
    bridge = MockBridge(responses=[])
    prior = CacheEntry(
        model_type="punet",
        key_findings=[
            ConsolidatedFinding(
                statement="ridge near 50 Hz dominates",
                evidence_iters=[2],
                strength="moderate",
            )
        ],
    )

    merged, archived = consolidate(
        bridge,
        prior=prior,
        new_llm_response=_empty_new_response(),
        new_stats={},
        current_iter=5,
        prior_iter=2,
    )

    assert bridge.call_count == 0
    assert len(merged.key_findings) == 1
    assert merged.key_findings[0].statement == "ridge near 50 Hz dominates"
    assert merged.key_findings[0].evidence_iters == [2]
    assert archived == []


def test_empty_prior_overflow_rank_prunes_without_llm() -> None:
    """When the fresh-wrap path produces more than MAX_SURVIVORS items, the
    deterministic rank-prune fallback fires — still no LLM call."""
    bridge = MockBridge(responses=[])
    prior = _bare_prior()
    new_resp = _empty_new_response()
    n_new = LIST_FIELD_MAX_SURVIVORS + 4
    new_resp["key_findings"] = [f"finding {i}" for i in range(n_new)]

    merged, archived = consolidate(
        bridge,
        prior=prior,
        new_llm_response=new_resp,
        new_stats={},
        current_iter=5,
        prior_iter=0,
    )

    assert bridge.call_count == 0
    assert len(merged.key_findings) == LIST_FIELD_MAX_SURVIVORS
    overflow = [a for a in archived if a.get("field") == "key_findings"]
    assert len(overflow) == 4
    assert all(a["reason"] == "rank_prune_cap_no_prior" for a in overflow)


# ===========================================================================
# Group B — The four semantic rules (mock LLM, one rule per test)
# ===========================================================================


def test_rule1_same_meaning_merge() -> None:
    """RULE 1 — paraphrases collapse into one survivor with unioned
    evidence_iters and max strength. Pinned with the spec's mandated example."""
    mock_response = {
        "survivors": [
            {
                "statement": "ridge near 50 Hz dominates",
                "evidence_iters": [2, 5],
                "strength": "moderate",
            }
        ],
        "archived": [],
    }
    bridge = MockBridge(responses=[mock_response, {"survivors": [], "archived": []}])
    prior = CacheEntry(
        model_type="punet",
        key_findings=[
            ConsolidatedFinding(
                statement="ridge near 50 Hz dominates",
                evidence_iters=[2],
                strength="moderate",
            )
        ],
    )
    new_resp = _empty_new_response()
    new_resp["key_findings"] = ["the 50 Hz ridge is the dominant feature"]

    merged, _ = consolidate(
        bridge,
        prior=prior,
        new_llm_response=new_resp,
        new_stats={},
        current_iter=5,
        prior_iter=2,
    )

    assert len(merged.key_findings) == 1
    f = merged.key_findings[0]
    assert f.statement == "ridge near 50 Hz dominates"
    assert f.evidence_iters == [2, 5]
    assert f.strength == "moderate"


def test_rule2_supersession_replacement_preserves_prior_in_prefix() -> None:
    """RULE 2 — supersession survivor carries '[SUPERSEDES iter-N: <gist>]'
    prefix so the evolution trail is intact in a single statement field."""
    mock_response = {
        "survivors": [
            {
                "statement": "[SUPERSEDES iter-2: VRAM spike ~16 GB] VRAM ceiling measured at 15.8 GB",
                "evidence_iters": [2, 5],
                "strength": "moderate",
            }
        ],
        "archived": [],
    }
    bridge = MockBridge(responses=[mock_response, {"survivors": [], "archived": []}])
    prior = CacheEntry(
        model_type="punet",
        key_findings=[
            ConsolidatedFinding(
                statement="VRAM spike around 16 GB",
                evidence_iters=[2],
                strength="moderate",
            )
        ],
    )
    new_resp = _empty_new_response()
    new_resp["key_findings"] = ["VRAM ceiling measured at 15.8 GB"]

    merged, _ = consolidate(
        bridge,
        prior=prior,
        new_llm_response=new_resp,
        new_stats={},
        current_iter=5,
        prior_iter=2,
    )

    assert len(merged.key_findings) == 1
    f = merged.key_findings[0]
    assert f.statement.startswith("[SUPERSEDES iter-2:")
    assert "VRAM ceiling measured at 15.8 GB" in f.statement
    assert f.evidence_iters == [2, 5]


def test_rule3_contradiction_preservation_emits_two_survivors() -> None:
    """RULE 3 — sign-flip is NEVER collapsed. Two survivors emitted; the new
    one's statement is prefixed '[CONFLICT iter-N vs iter-M]'.

    This is the load-bearing semantic-correctness test for Rev 8.5 — the
    rule that justifies the LLM pivot from deterministic similarity.
    """
    mock_response = {
        "survivors": [
            {
                "statement": "loss improved by 12% with dropout=0.3",
                "evidence_iters": [2],
                "strength": "moderate",
            },
            {
                "statement": "[CONFLICT iter-5 vs iter-2] loss degraded by 12% with dropout=0.3",
                "evidence_iters": [5],
                "strength": "moderate",
            },
        ],
        "archived": [],
    }
    bridge = MockBridge(responses=[mock_response, {"survivors": [], "archived": []}])
    prior = CacheEntry(
        model_type="punet",
        key_findings=[
            ConsolidatedFinding(
                statement="loss improved by 12% with dropout=0.3",
                evidence_iters=[2],
                strength="moderate",
            )
        ],
    )
    new_resp = _empty_new_response()
    new_resp["key_findings"] = ["loss degraded by 12% with dropout=0.3"]

    merged, _ = consolidate(
        bridge,
        prior=prior,
        new_llm_response=new_resp,
        new_stats={},
        current_iter=5,
        prior_iter=2,
    )

    assert len(merged.key_findings) == 2, (
        "Contradictions must NEVER collapse — both items must survive."
    )
    statements = [f.statement for f in merged.key_findings]
    assert "loss improved by 12% with dropout=0.3" in statements
    assert any(s.startswith("[CONFLICT iter-5 vs iter-2]") for s in statements)


def test_rule4_distinct_emits_both_unchanged() -> None:
    """RULE 4 — no match between any (prior, new) pair → both emitted as their
    own survivors, prior unchanged, new tagged with [current_iter]."""
    mock_response = {
        "survivors": [
            {
                "statement": "ridge near 50 Hz dominates",
                "evidence_iters": [2],
                "strength": "moderate",
            },
            {
                "statement": "training time scales linearly with batch_size",
                "evidence_iters": [5],
                "strength": "moderate",
            },
        ],
        "archived": [],
    }
    bridge = MockBridge(responses=[mock_response, {"survivors": [], "archived": []}])
    prior = CacheEntry(
        model_type="punet",
        key_findings=[
            ConsolidatedFinding(
                statement="ridge near 50 Hz dominates",
                evidence_iters=[2],
                strength="moderate",
            )
        ],
    )
    new_resp = _empty_new_response()
    new_resp["key_findings"] = ["training time scales linearly with batch_size"]

    merged, _ = consolidate(
        bridge,
        prior=prior,
        new_llm_response=new_resp,
        new_stats={},
        current_iter=5,
        prior_iter=2,
    )

    assert len(merged.key_findings) == 2
    statements = {f.statement for f in merged.key_findings}
    assert "ridge near 50 Hz dominates" in statements
    assert "training time scales linearly with batch_size" in statements


# ===========================================================================
# Group C — Rank-prune behaviour with LLM merge
# ===========================================================================


def test_rank_prune_caps_survivors_to_max_with_archive() -> None:
    """The LLM's `archived` list is captured into the returned archive
    payload. Pinned with 12 input findings → 8 survivors + 4 archived."""
    survivors = [
        {"statement": f"survivor finding {i}", "evidence_iters": [i + 1], "strength": "strong"}
        for i in range(LIST_FIELD_MAX_SURVIVORS)
    ]
    archived_items = [
        {"statement": f"archived finding {j}", "evidence_iters": [j + 1], "strength": "weak"}
        for j in range(4)
    ]
    mock_response = {"survivors": survivors, "archived": archived_items}
    bridge = MockBridge(
        responses=[mock_response, {"survivors": [], "archived": []}]
    )

    prior_findings = [
        ConsolidatedFinding(
            statement=f"prior finding {i}",
            evidence_iters=[i + 1],
            strength="moderate",
        )
        for i in range(6)
    ]
    prior = CacheEntry(model_type="punet", key_findings=prior_findings)
    new_resp = _empty_new_response()
    new_resp["key_findings"] = [f"new finding {i}" for i in range(6)]

    merged, archived = consolidate(
        bridge,
        prior=prior,
        new_llm_response=new_resp,
        new_stats={},
        current_iter=10,
        prior_iter=2,
    )

    assert len(merged.key_findings) == LIST_FIELD_MAX_SURVIVORS
    archived_kf = [a for a in archived if a.get("field") == "key_findings"]
    assert len(archived_kf) == 4
    assert all(a["reason"] == "llm_archive" for a in archived_kf)


def test_llm_oversized_survivors_get_deterministic_overflow_trim() -> None:
    """If the LLM ignores MAX_SURVIVORS and returns >8 survivors, the
    consolidator defensively rank-prunes the excess into the archive."""
    survivors = [
        {"statement": f"survivor {i}", "evidence_iters": [i + 1], "strength": "moderate"}
        for i in range(LIST_FIELD_MAX_SURVIVORS + 3)
    ]
    mock_response = {"survivors": survivors, "archived": []}
    bridge = MockBridge(
        responses=[mock_response, {"survivors": [], "archived": []}]
    )
    prior = CacheEntry(
        model_type="punet",
        key_findings=[
            ConsolidatedFinding(
                statement="prior x", evidence_iters=[1], strength="moderate"
            )
        ],
    )
    new_resp = _empty_new_response()
    new_resp["key_findings"] = ["new y"]

    merged, archived = consolidate(
        bridge,
        prior=prior,
        new_llm_response=new_resp,
        new_stats={},
        current_iter=5,
        prior_iter=2,
    )

    assert len(merged.key_findings) == LIST_FIELD_MAX_SURVIVORS
    overflow = [a for a in archived if a.get("reason") == "rank_prune_cap_overflow"]
    assert len(overflow) == 3


# ===========================================================================
# Group D — Narrative replacement-with-history (deterministic)
# ===========================================================================


def test_narrative_merge_score_trend_across_four_iters() -> None:
    """Pinned spec example: score_trend updated at iters 1, 4, 7, 10. After
    the iter-10 merge, `latest` = iter-10 text and `history` carries (7, ..),
    (4, ..), (1, ..) — capped to the schema's max of 3."""
    narr = ConsolidatedNarrative(latest="iter-1 narrative")
    narr, _ = _merge_narrative_field(narr, "iter-4 narrative", prior_iter=1)
    narr, _ = _merge_narrative_field(narr, "iter-7 narrative", prior_iter=4)
    narr, archived = _merge_narrative_field(narr, "iter-10 narrative", prior_iter=7)

    assert narr.latest == "iter-10 narrative"
    assert len(narr.history) == NARRATIVE_HISTORY_MAX_ENTRIES == 3
    history_iters = [iter_idx for iter_idx, _ in narr.history]
    history_texts = [text for _, text in narr.history]
    assert history_iters == [7, 4, 1]
    assert history_texts == ["iter-7 narrative", "iter-4 narrative", "iter-1 narrative"]
    assert archived == []  # exactly at cap, no overflow


def test_narrative_history_overflow_goes_to_archive() -> None:
    """A 5-update sequence puts iter-1 and iter-4 into the archive once the
    history cap is exceeded by the 5th merge."""
    narr = ConsolidatedNarrative(latest="iter-1 narrative")
    narr, arch1 = _merge_narrative_field(narr, "iter-2", prior_iter=1)
    narr, arch2 = _merge_narrative_field(narr, "iter-3", prior_iter=2)
    narr, arch3 = _merge_narrative_field(narr, "iter-4", prior_iter=3)
    narr, arch4 = _merge_narrative_field(narr, "iter-5", prior_iter=4)

    assert narr.latest == "iter-5"
    assert len(narr.history) == 3
    # After the 4th merge above, iter-1's narrative is the one that overflowed.
    overflowed_texts = [a["narrative"] for a in arch4]
    assert overflowed_texts == ["iter-1 narrative"]
    assert arch4[0]["reason"] == "narrative_history_cap"


def test_narrative_empty_new_with_empty_prior_is_noop() -> None:
    """An empty narrative on both sides is a no-op — common when the LLM had
    no signal for this field this iter."""
    narr = ConsolidatedNarrative(latest="")
    merged, archived = _merge_narrative_field(narr, "", prior_iter=3)
    assert merged is narr
    assert archived == []


def test_narrative_idempotent_when_new_equals_prior() -> None:
    """If new_text matches prior.latest byte-for-byte, it's a no-op — no
    history entry created, no archive churn."""
    narr = ConsolidatedNarrative(
        latest="identical narrative", history=[(3, "older")]
    )
    merged, archived = _merge_narrative_field(narr, "identical narrative", prior_iter=4)
    assert merged is narr
    assert archived == []


# ===========================================================================
# Group E — Error-signature preservation (Gate G3 invariant)
# ===========================================================================


def _make_sig(
    *,
    error_type: str,
    failure_class: str,
    top_frame: str,
    iters: List[int],
    short_message: str = "msg",
) -> ErrorSignature:
    return ErrorSignature(
        error_type=error_type,
        short_message=short_message,
        last_frames=[top_frame],
        failure_class=failure_class,
        top_user_frame=top_frame,
        evidence_iters=iters,
    )


def test_dedupe_preserves_twelve_distinct_signatures() -> None:
    """Twelve distinct (failure_class, top_user_frame, error_type) tuples must
    survive set-merge — no cap, no rank-prune."""
    sigs = [
        _make_sig(
            error_type=f"Error{i}",
            failure_class="training",
            top_frame=f"file_{i}.py:42",
            iters=[i + 1],
        )
        for i in range(12)
    ]
    merged = _dedupe_error_signatures(sigs, [])
    assert len(merged) == 12


def test_dedupe_preserves_thirty_distinct_signatures() -> None:
    """Gate G3 — even 30 distinct signatures must all survive."""
    sigs = [
        _make_sig(
            error_type=f"Error{i}",
            failure_class="training",
            top_frame=f"file_{i}.py:42",
            iters=[i + 1],
        )
        for i in range(30)
    ]
    merged = _dedupe_error_signatures(sigs, [])
    assert len(merged) == 30


def test_dedupe_unions_evidence_iters_for_duplicate_keys() -> None:
    """Two ErrorSignatures with identical key tuples merge into one with
    unioned evidence_iters (not concatenated, not the maximum — full union)."""
    sig_a = _make_sig(
        error_type="ValueError",
        failure_class="training",
        top_frame="train.py:99",
        iters=[2],
    )
    sig_b = _make_sig(
        error_type="ValueError",
        failure_class="training",
        top_frame="train.py:99",
        iters=[7, 10],
    )
    merged = _dedupe_error_signatures([sig_a], [sig_b])
    assert len(merged) == 1
    assert merged[0].evidence_iters == [2, 7, 10]


def test_dedupe_is_pure_no_bridge_argument() -> None:
    """The dedup function's signature must NOT accept a bridge — pinning that
    error_signature merging can never accidentally trigger an LLM call."""
    import inspect

    sig_params = inspect.signature(_dedupe_error_signatures).parameters
    assert "bridge" not in sig_params, (
        "Error-signature dedup must remain LLM-free (Gate G3). Adding a "
        "bridge parameter would risk routing forensic primary sources "
        "through a stochastic merge."
    )


# ===========================================================================
# Group F — Bounded LLM-call-count and deterministic-paths-untouched
# ===========================================================================


def test_consolidate_calls_bridge_at_most_twice_per_invocation() -> None:
    """Per `consolidate()` invocation, at most 2 LLM calls — one for
    key_findings, one for bottlenecks. Narrative + error_sig paths never
    touch the bridge."""
    # Both list fields populated on both sides → 2 LLM calls expected.
    mock_resp_kf = {
        "survivors": [
            {"statement": "merged kf", "evidence_iters": [1, 5], "strength": "moderate"}
        ],
        "archived": [],
    }
    mock_resp_bn = {
        "survivors": [
            {"statement": "merged bn", "evidence_iters": [1, 5], "strength": "moderate"}
        ],
        "archived": [],
    }
    bridge = MockBridge(responses=[mock_resp_kf, mock_resp_bn])
    prior = CacheEntry(
        model_type="punet",
        key_findings=[
            ConsolidatedFinding(statement="prior kf", evidence_iters=[1], strength="moderate")
        ],
        bottlenecks=[
            ConsolidatedFinding(statement="prior bn", evidence_iters=[1], strength="moderate")
        ],
        # Populate every narrative + an error_signature to prove they don't
        # bump the call count.
        best_config_analysis=ConsolidatedNarrative(latest="prior cfg analysis"),
        score_trend=ConsolidatedNarrative(latest="prior trend"),
        per_file_analysis=ConsolidatedNarrative(latest="prior pfa"),
        data_sensitivity=ConsolidatedNarrative(latest="prior ds"),
        efficiency_assessment=ConsolidatedNarrative(latest="prior eff"),
        strategy_assessment=ConsolidatedNarrative(latest="prior strat"),
        error_signatures=[
            _make_sig(
                error_type="RuntimeError",
                failure_class="training",
                top_frame="t.py:1",
                iters=[1],
            )
        ],
    )
    new_resp = {
        "key_findings": ["new kf"],
        "bottlenecks": ["new bn"],
        "best_config_analysis": "new cfg analysis",
        "score_trend": "new trend",
        "per_file_analysis": "new pfa",
        "data_sensitivity": "new ds",
        "efficiency_assessment": "new eff",
        "strategy_assessment": "new strat",
        "error_signatures": [],
    }

    consolidate(
        bridge,
        prior=prior,
        new_llm_response=new_resp,
        new_stats={},
        current_iter=5,
        prior_iter=1,
    )

    assert bridge.call_count == 2, (
        f"Expected exactly 2 LLM calls (one per list field). "
        f"Got {bridge.call_count}. Narrative/error_sig paths must not "
        f"invoke the bridge."
    )
    # Each call must carry the consolidator label.
    labels = [c[2] for c in bridge.calls]
    assert all(label == "cache_consolidator.list_merge" for label in labels)


def test_consolidate_bridge_call_count_zero_when_both_lists_empty() -> None:
    """The cost bound is `≤ 2`, not exactly 2 — empty lists must short-circuit
    to zero calls."""
    bridge = MockBridge(responses=[])
    consolidate(
        bridge,
        prior=_bare_prior(),
        new_llm_response=_empty_new_response(),
        new_stats={},
        current_iter=1,
        prior_iter=0,
    )
    assert bridge.call_count == 0


def test_merge_narrative_field_has_no_bridge_parameter() -> None:
    """Static guard: the narrative merge function must not accept a bridge.
    If anyone ever wires an LLM into narrative consolidation, this fails."""
    import inspect

    params = inspect.signature(_merge_narrative_field).parameters
    assert "bridge" not in params


# ===========================================================================
# Group G — Cache-hit-merge regression (Rev 8.2 specific)
# ===========================================================================


def test_cache_hit_merge_low_similarity_preserves_both_findings() -> None:
    """Rev 8.2 regression — when prior iter-2 carries a finding and the new
    iter-10 LLM response emits a structurally different finding, BOTH must
    survive. The verbatim-copy bug that Commit 6.3 fixes would have dropped
    the iter-2 finding entirely."""
    mock_response = {
        "survivors": [
            {
                "statement": "VRAM spike at 16 GB",
                "evidence_iters": [2],
                "strength": "moderate",
            },
            {
                "statement": "model OOMs at 18 GB on long sequences",
                "evidence_iters": [10],
                "strength": "moderate",
            },
        ],
        "archived": [],
    }
    bridge = MockBridge(
        responses=[mock_response, {"survivors": [], "archived": []}]
    )
    prior = CacheEntry(
        model_type="punet",
        key_findings=[
            ConsolidatedFinding(
                statement="VRAM spike at 16 GB",
                evidence_iters=[2],
                strength="moderate",
            )
        ],
    )
    new_resp = _empty_new_response()
    new_resp["key_findings"] = ["model OOMs at 18 GB on long sequences"]

    merged, _ = consolidate(
        bridge,
        prior=prior,
        new_llm_response=new_resp,
        new_stats={},
        current_iter=10,
        prior_iter=2,
    )

    statements = {f.statement for f in merged.key_findings}
    assert "VRAM spike at 16 GB" in statements
    assert "model OOMs at 18 GB on long sequences" in statements


def test_strong_finding_survives_consolidation() -> None:
    """Behavioural guard — a strength='strong' finding pre-consolidation must
    not vanish post-consolidation. Confirms the rank-prune does not silently
    demote load-bearing observations."""
    mock_response = {
        "survivors": [
            {
                "statement": "this is a strong finding",
                "evidence_iters": [2, 5],
                "strength": "strong",
            }
        ],
        "archived": [],
    }
    bridge = MockBridge(
        responses=[mock_response, {"survivors": [], "archived": []}]
    )
    prior = CacheEntry(
        model_type="punet",
        key_findings=[
            ConsolidatedFinding(
                statement="this is a strong finding",
                evidence_iters=[2],
                strength="strong",
            )
        ],
    )
    new_resp = _empty_new_response()
    new_resp["key_findings"] = ["this is a strong finding"]

    merged, _ = consolidate(
        bridge,
        prior=prior,
        new_llm_response=new_resp,
        new_stats={},
        current_iter=5,
        prior_iter=2,
    )

    strong = [f for f in merged.key_findings if f.strength == "strong"]
    assert len(strong) >= 1


# ===========================================================================
# Group H — Field reconciliation (8-flat-field LLM shape)
# ===========================================================================


def test_field_reconciliation_eight_flat_fields_parse_into_cache_entry() -> None:
    """The 8 flat fields PER_MODEL_SYSTEM_PROMPT emits must flow into a
    CacheEntry without rejection. error_signatures absent → defaults to []."""
    bridge = MockBridge(responses=[])
    prior = _bare_prior()
    new_resp = {
        "key_findings": [],
        "bottlenecks": [],
        "best_config_analysis": "best config so far is dropout=0.3",
        "score_trend": "scores improving steadily",
        "per_file_analysis": "file 2 is the hardest",
        "data_sensitivity": "moderate sensitivity to noise",
        "efficiency_assessment": "throughput at 800 samples/s",
        "strategy_assessment": "current strategy is sound",
        # No error_signatures key on purpose — must default to [].
    }
    stats = {"best_denoising_score": -3.5, "completed_rounds": 10}

    merged, _ = consolidate(
        bridge,
        prior=prior,
        new_llm_response=new_resp,
        new_stats=stats,
        current_iter=5,
        prior_iter=0,
    )

    assert merged.model_type == "punet"
    assert merged.best_config_analysis.latest == "best config so far is dropout=0.3"
    assert merged.score_trend.latest == "scores improving steadily"
    assert merged.per_file_analysis.latest == "file 2 is the hardest"
    assert merged.data_sensitivity.latest == "moderate sensitivity to noise"
    assert merged.efficiency_assessment.latest == "throughput at 800 samples/s"
    assert merged.strategy_assessment.latest == "current strategy is sound"
    assert merged.error_signatures == []
    assert merged.stats == stats


def test_stats_field_passes_through_untouched() -> None:
    """The consolidator must NOT mutate, drop, or filter the stats dict —
    Phase-2 §6.1 reads from this field to reconstruct numerical context for
    cached models."""
    bridge = MockBridge(responses=[])
    stats = {
        "best_denoising_score": -3.7,
        "worst_denoising_score": -5.1,
        "completed_rounds": 12,
        "best_config": {"lr": 1e-3, "dropout": 0.3},
        "best_model_params": 1_234_567,
        "formal_score": -3.65,
        "model_description": "test description",
    }
    merged, _ = consolidate(
        bridge,
        prior=_bare_prior(),
        new_llm_response=_empty_new_response(),
        new_stats=stats,
        current_iter=5,
        prior_iter=0,
    )
    assert merged.stats == stats


# ===========================================================================
# Group I — Prompt structure invariants
# ===========================================================================


def test_system_prompt_has_no_hardcoded_numerical_caps() -> None:
    """Per the Rev 8.5 hybrid design, the system prompt must reference caps
    by name (MAX_SURVIVORS, MAX_PRIOR_SUMMARY_CHARS, MAX_STATEMENT_CHARS)
    and NOT hardcode their numerical values. This pin protects the
    Principle-#4 separation: tuning a knob is a Python edit, not a
    system-prompt rewrite."""
    forbidden_numbers = [" 8 ", " 80 ", " 500 "]
    for needle in forbidden_numbers:
        assert needle not in _LIST_MERGE_SYSTEM_PROMPT, (
            f"System prompt contains hardcoded numeric value {needle!r}. "
            f"Move it to POLICY PARAMETERS in the user prompt."
        )
    assert "MAX_SURVIVORS" in _LIST_MERGE_SYSTEM_PROMPT
    assert "MAX_PRIOR_SUMMARY_CHARS" in _LIST_MERGE_SYSTEM_PROMPT
    assert "MAX_STATEMENT_CHARS" in _LIST_MERGE_SYSTEM_PROMPT


def test_user_prompt_carries_policy_parameters_and_examples_and_data() -> None:
    """The user prompt must contain all three named sections: POLICY
    PARAMETERS, POLICY EXAMPLES, DATA."""
    prompt = _build_list_merge_user_prompt(
        model_type="punet",
        field_name="key_findings",
        prior=[],
        new_statements=["x"],
        current_iter=5,
    )
    assert "POLICY PARAMETERS" in prompt
    assert "POLICY EXAMPLES" in prompt
    assert "DATA:" in prompt
    assert "MAX_SURVIVORS = 8" in prompt
    assert f"MAX_PRIOR_SUMMARY_CHARS = {MAX_PRIOR_SUMMARY_CHARS}" in prompt
    assert f"MAX_STATEMENT_CHARS = {FINDING_STATEMENT_MAX_CHARS}" in prompt
    assert "MODEL_TYPE: punet" in prompt
    assert "CURRENT_ITER: 5" in prompt


def test_user_prompt_overrides_take_effect() -> None:
    """The hybrid design hinges on the user-prompt builder honoring per-call
    overrides for the caps. If overrides silently fell back to the module
    defaults, the whole flexibility argument collapses."""
    prompt = _build_list_merge_user_prompt(
        model_type="punet",
        field_name="key_findings",
        prior=[],
        new_statements=["x"],
        current_iter=5,
        max_survivors=12,
        max_prior_summary_chars=60,
        max_statement_chars=300,
    )
    assert "MAX_SURVIVORS = 12" in prompt
    assert "MAX_PRIOR_SUMMARY_CHARS = 60" in prompt
    assert "MAX_STATEMENT_CHARS = 300" in prompt


# ===========================================================================
# Group J — Malformed LLM response
# ===========================================================================


def test_malformed_llm_response_raises_with_helpful_message() -> None:
    """If the LLM returns JSON that doesn't match the _MergeDecision schema
    (e.g. missing 'survivors' is fine since it defaults, but wrong type for
    'strength' is not), the consolidator must fail loudly so the caller can
    surface the broken contract."""
    bad_response = {
        "survivors": [
            {
                "statement": "ok",
                "evidence_iters": [1],
                "strength": "extra-strong",  # not in the enum
            }
        ],
        "archived": [],
    }
    bridge = MockBridge(responses=[bad_response])

    prior = CacheEntry(
        model_type="punet",
        key_findings=[
            ConsolidatedFinding(
                statement="prior", evidence_iters=[1], strength="moderate"
            )
        ],
    )
    new_resp = _empty_new_response()
    new_resp["key_findings"] = ["new"]

    with pytest.raises(RuntimeError, match="malformed merge decision"):
        consolidate(
            bridge,
            prior=prior,
            new_llm_response=new_resp,
            new_stats={},
            current_iter=5,
            prior_iter=2,
        )
