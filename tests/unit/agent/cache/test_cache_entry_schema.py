"""Commit 6.3 / C1 — schema validation tests for the consolidated cache entry.

What this file pins:

  1. Strict-mode (``extra="forbid"``) is on for every model — unknown keys are
     rejected immediately. Caught at instantiation, no silent drift.
  2. Length / non-empty constraints from the spec:
       * statement: non-empty, <= 500 chars
       * latest:    <= 800 chars
       * short_message: <= 120 chars
       * history:   <= 3 entries
  3. Closed-enum fields (``strength``, ``failure_class``) reject unknown values.
  4. ``evidence_iters`` is non-empty and entries are >= 0 (set-union semantics
     have no meaning for a finding that has never been observed).
  5. ``ErrorSignature.key()`` returns the (failure_class, top_user_frame,
     error_type) tuple — the dedup contract the consolidator relies on.
  6. ``CacheEntry.from_legacy_dict`` is zero-friction for pre-6.3 chains:
     legacy ``list[str]`` lifts to ``list[ConsolidatedFinding]`` carrying
     ``evidence_iters=[current_iter]``, and legacy ``str`` narratives lift
     to ``ConsolidatedNarrative(latest=str, history=[])`` — even when the
     legacy strings would individually fail the schema (oversized statements
     truncate, empty findings drop, both ``_stats`` and ``stats`` keys map
     to the new ``stats`` field).
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent.schemas.cache_entry import (
    ERROR_SHORT_MESSAGE_MAX_CHARS,
    FINDING_STATEMENT_MAX_CHARS,
    NARRATIVE_HISTORY_MAX_ENTRIES,
    NARRATIVE_LATEST_MAX_CHARS,
    CacheEntry,
    ConsolidatedFinding,
    ConsolidatedNarrative,
    ErrorSignature,
)


# ---------------------------------------------------------------------------
# ConsolidatedFinding
# ---------------------------------------------------------------------------

def test_finding_valid_construction() -> None:
    f = ConsolidatedFinding(
        statement="ridge near 50 Hz dominates",
        evidence_iters=[2, 5],
        strength="strong",
    )
    assert f.statement == "ridge near 50 Hz dominates"
    assert f.evidence_iters == [2, 5]
    assert f.strength == "strong"


def test_finding_rejects_empty_statement() -> None:
    with pytest.raises(ValidationError):
        ConsolidatedFinding(statement="", evidence_iters=[1], strength="weak")


def test_finding_rejects_oversized_statement() -> None:
    """Spec line 2515: statement max 500 chars."""
    with pytest.raises(ValidationError):
        ConsolidatedFinding(
            statement="x" * (FINDING_STATEMENT_MAX_CHARS + 1),
            evidence_iters=[1],
            strength="moderate",
        )


def test_finding_accepts_max_length_statement() -> None:
    """Exactly at the boundary must succeed (off-by-one guard)."""
    f = ConsolidatedFinding(
        statement="x" * FINDING_STATEMENT_MAX_CHARS,
        evidence_iters=[1],
        strength="moderate",
    )
    assert len(f.statement) == FINDING_STATEMENT_MAX_CHARS


def test_finding_rejects_empty_evidence_iters() -> None:
    with pytest.raises(ValidationError):
        ConsolidatedFinding(statement="ok", evidence_iters=[], strength="weak")


def test_finding_rejects_negative_iter() -> None:
    with pytest.raises(ValidationError):
        ConsolidatedFinding(
            statement="ok", evidence_iters=[3, -1], strength="weak",
        )


def test_finding_rejects_unknown_strength() -> None:
    with pytest.raises(ValidationError):
        ConsolidatedFinding(
            statement="ok", evidence_iters=[1], strength="extreme",  # type: ignore[arg-type]
        )


def test_finding_rejects_extra_field() -> None:
    """extra='forbid' guards against silent schema drift if the LLM adds a
    field we did not anticipate."""
    with pytest.raises(ValidationError):
        ConsolidatedFinding(
            statement="ok",
            evidence_iters=[1],
            strength="weak",
            unexpected="should fail",  # type: ignore[call-arg]
        )


# ---------------------------------------------------------------------------
# ConsolidatedNarrative
# ---------------------------------------------------------------------------

def test_narrative_valid_construction() -> None:
    n = ConsolidatedNarrative(
        latest="best config is depth=6, width=128",
        history=[(2, "depth=4 was too shallow"), (5, "depth=5 still bottlenecked")],
    )
    assert n.latest.startswith("best config")
    assert len(n.history) == 2


def test_narrative_accepts_empty_latest() -> None:
    """Empty latest is intentional — the LLM may have no signal for a field
    this iter; the consolidator still needs a placeholder entry."""
    n = ConsolidatedNarrative(latest="")
    assert n.latest == ""
    assert n.history == []


def test_narrative_rejects_oversized_latest() -> None:
    """Spec checklist line 2591: 'narrative latest over 800 chars' must be
    rejected by Pydantic."""
    with pytest.raises(ValidationError):
        ConsolidatedNarrative(latest="x" * (NARRATIVE_LATEST_MAX_CHARS + 1))


def test_narrative_accepts_max_length_latest() -> None:
    n = ConsolidatedNarrative(latest="x" * NARRATIVE_LATEST_MAX_CHARS)
    assert len(n.latest) == NARRATIVE_LATEST_MAX_CHARS


def test_narrative_rejects_over_cap_history() -> None:
    """Spec line 2521: history capped to last 3. Schema enforces upper bound;
    the consolidator is responsible for pruning before construction."""
    with pytest.raises(ValidationError):
        ConsolidatedNarrative(
            latest="ok",
            history=[
                (i, f"narrative iter {i}")
                for i in range(NARRATIVE_HISTORY_MAX_ENTRIES + 1)
            ],
        )


def test_narrative_accepts_max_history() -> None:
    n = ConsolidatedNarrative(
        latest="ok",
        history=[(i, f"n{i}") for i in range(NARRATIVE_HISTORY_MAX_ENTRIES)],
    )
    assert len(n.history) == NARRATIVE_HISTORY_MAX_ENTRIES


def test_narrative_rejects_negative_history_iter() -> None:
    with pytest.raises(ValidationError):
        ConsolidatedNarrative(latest="ok", history=[(-1, "bad")])


def test_narrative_rejects_extra_field() -> None:
    with pytest.raises(ValidationError):
        ConsolidatedNarrative(latest="ok", surprise="nope")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# ErrorSignature
# ---------------------------------------------------------------------------

def _valid_error_sig(**overrides):
    base = dict(
        error_type="torch.cuda.OutOfMemoryError",
        short_message="CUDA out of memory at 16.0 GB",
        last_frames=["ml_models/foo.py:42 in forward"],
        failure_class="vram",
        top_user_frame="ml_models/foo.py:42 in forward",
        evidence_iters=[3],
    )
    base.update(overrides)
    return ErrorSignature(**base)


def test_error_sig_valid_construction() -> None:
    sig = _valid_error_sig()
    assert sig.failure_class == "vram"
    assert sig.evidence_iters == [3]


def test_error_sig_key_tuple() -> None:
    """The consolidator dedupes by ``key()`` — pin the field order so a
    future refactor cannot silently change the dedup contract and break
    Gate G3 preservation."""
    sig = _valid_error_sig()
    assert sig.key() == ("vram", "ml_models/foo.py:42 in forward",
                         "torch.cuda.OutOfMemoryError")


def test_error_sig_rejects_unknown_failure_class() -> None:
    """Spec checklist line 2591: unknown failure_class must be rejected."""
    with pytest.raises(ValidationError):
        _valid_error_sig(failure_class="cosmic_ray")


def test_error_sig_rejects_oversized_short_message() -> None:
    with pytest.raises(ValidationError):
        _valid_error_sig(
            short_message="x" * (ERROR_SHORT_MESSAGE_MAX_CHARS + 1),
        )


def test_error_sig_rejects_empty_evidence_iters() -> None:
    """An ErrorSignature must have been observed at least once."""
    with pytest.raises(ValidationError):
        _valid_error_sig(evidence_iters=[])


def test_error_sig_rejects_empty_error_type() -> None:
    with pytest.raises(ValidationError):
        _valid_error_sig(error_type="")


def test_error_sig_accepts_empty_last_frames() -> None:
    """Spec §2.2: last_frames may be empty for non-Python failure modes."""
    sig = _valid_error_sig(last_frames=[], top_user_frame="")
    assert sig.last_frames == []
    assert sig.top_user_frame == ""


def test_error_sig_rejects_extra_field() -> None:
    with pytest.raises(ValidationError):
        _valid_error_sig(unexpected="nope")


# ---------------------------------------------------------------------------
# CacheEntry — strict construction
# ---------------------------------------------------------------------------

def test_cache_entry_minimal_valid() -> None:
    """Only model_type is required; all 8 LLM-flat fields default to empty
    accumulator shells. error_signatures defaults to []."""
    e = CacheEntry(model_type="punet")
    assert e.model_type == "punet"
    assert e.key_findings == []
    assert e.bottlenecks == []
    assert e.best_config_analysis.latest == ""
    assert e.score_trend.history == []
    assert e.error_signatures == []
    assert e.stats == {}


def test_cache_entry_rejects_missing_model_type() -> None:
    with pytest.raises(ValidationError):
        CacheEntry()  # type: ignore[call-arg]


def test_cache_entry_rejects_empty_model_type() -> None:
    with pytest.raises(ValidationError):
        CacheEntry(model_type="")


def test_cache_entry_rejects_extra_field() -> None:
    """Pre-empts the LLM-output schema drift hazard the spec calls out."""
    with pytest.raises(ValidationError):
        CacheEntry(model_type="punet", surprise_field=1)  # type: ignore[call-arg]


def test_cache_entry_full_payload_round_trip() -> None:
    """End-to-end smoke: build a fully-populated entry and confirm every
    nested type validates together (catches missing-field-in-narrative cases
    that a per-class test would miss)."""
    e = CacheEntry(
        model_type="punet",
        key_findings=[
            ConsolidatedFinding(
                statement="ridge near 50 Hz",
                evidence_iters=[2, 5],
                strength="strong",
            ),
        ],
        bottlenecks=[
            ConsolidatedFinding(
                statement="VRAM spike at 16 GB",
                evidence_iters=[3],
                strength="moderate",
            ),
        ],
        best_config_analysis=ConsolidatedNarrative(
            latest="d=6,w=128", history=[(2, "d=4 too shallow")],
        ),
        error_signatures=[_valid_error_sig()],
        stats={"best_score": 1.23, "completed_rounds": 4},
    )
    dumped = e.model_dump()
    re_parsed = CacheEntry.model_validate(dumped)
    assert re_parsed.error_signatures[0].key() == e.error_signatures[0].key()


# ---------------------------------------------------------------------------
# CacheEntry.from_legacy_dict — zero-friction chain resume (Q2(a))
# ---------------------------------------------------------------------------

def _legacy_entry() -> dict:
    """A minimal pre-6.3 flat-dict shape, modelled on what the live
    PER_MODEL_SYSTEM_PROMPT emits."""
    return {
        "key_findings": [
            "ridge near 50 Hz dominates",
            "model latency stable at 35 ms",
        ],
        "bottlenecks": ["VRAM spike at 16 GB"],
        "best_config_analysis": "depth=6, width=128 outperforms",
        "score_trend": "monotone improvement 0.71 -> 0.78",
        "per_file_analysis": "file 6 hardest, file 19 easiest",
        "data_sensitivity": "robust to file ordering",
        "efficiency_assessment": "balanced FLOPs/score ratio",
        "strategy_assessment": "continue widening before deepening",
        "_stats": {"best_score": 0.78, "completed_rounds": 3},
    }


def test_legacy_lifts_list_str_to_findings_with_current_iter() -> None:
    """Q2(a): list[str] -> list[ConsolidatedFinding] with
    evidence_iters=[current_iter]."""
    entry = CacheEntry.from_legacy_dict(
        _legacy_entry(), model_type="punet", current_iter=7,
    )
    assert len(entry.key_findings) == 2
    for f in entry.key_findings:
        assert f.evidence_iters == [7]
        assert f.strength == "moderate"
    assert entry.key_findings[0].statement.startswith("ridge near 50 Hz")
    assert len(entry.bottlenecks) == 1
    assert entry.bottlenecks[0].statement == "VRAM spike at 16 GB"


def test_legacy_lifts_str_to_narrative_with_empty_history() -> None:
    """Q2(a): str narratives -> ConsolidatedNarrative(latest=str, history=[])."""
    entry = CacheEntry.from_legacy_dict(
        _legacy_entry(), model_type="punet", current_iter=7,
    )
    assert entry.best_config_analysis.latest == "depth=6, width=128 outperforms"
    assert entry.best_config_analysis.history == []
    assert entry.score_trend.latest.startswith("monotone improvement")
    # All 6 narrative fields populated by the lift, none left at default-empty.
    for field in (
        "best_config_analysis", "score_trend", "per_file_analysis",
        "data_sensitivity", "efficiency_assessment", "strategy_assessment",
    ):
        assert getattr(entry, field).latest != ""


def test_legacy_drops_empty_findings_strings() -> None:
    """A legacy entry with empty / whitespace-only findings would fail
    ConsolidatedFinding.statement's min_length=1. The adapter must drop
    them so chain resume does not crash."""
    legacy = _legacy_entry()
    legacy["key_findings"] = ["valid finding", "", "   ", "another valid one"]
    entry = CacheEntry.from_legacy_dict(
        legacy, model_type="punet", current_iter=7,
    )
    assert len(entry.key_findings) == 2
    assert all(f.statement.strip() for f in entry.key_findings)


def test_legacy_truncates_oversized_finding_statements() -> None:
    """Legacy entries can carry strings longer than the new 500-char cap.
    Adapter truncates rather than raises — zero-friction resume."""
    legacy = _legacy_entry()
    legacy["key_findings"] = ["x" * (FINDING_STATEMENT_MAX_CHARS + 100)]
    entry = CacheEntry.from_legacy_dict(
        legacy, model_type="punet", current_iter=1,
    )
    assert len(entry.key_findings[0].statement) == FINDING_STATEMENT_MAX_CHARS


def test_legacy_truncates_oversized_narrative_latest() -> None:
    legacy = _legacy_entry()
    legacy["score_trend"] = "y" * (NARRATIVE_LATEST_MAX_CHARS + 100)
    entry = CacheEntry.from_legacy_dict(
        legacy, model_type="punet", current_iter=1,
    )
    assert len(entry.score_trend.latest) == NARRATIVE_LATEST_MAX_CHARS


def test_legacy_accepts_underscored_stats_key() -> None:
    """Legacy code wrote ``_stats``; the new schema reads ``stats``. The
    adapter must accept both so we don't silently lose numerical context."""
    legacy = _legacy_entry()
    entry = CacheEntry.from_legacy_dict(
        legacy, model_type="punet", current_iter=1,
    )
    assert entry.stats == {"best_score": 0.78, "completed_rounds": 3}


def test_legacy_accepts_forward_stats_key() -> None:
    legacy = _legacy_entry()
    legacy.pop("_stats")
    legacy["stats"] = {"best_score": 0.99}
    entry = CacheEntry.from_legacy_dict(
        legacy, model_type="punet", current_iter=1,
    )
    assert entry.stats == {"best_score": 0.99}


def test_legacy_defaults_missing_fields() -> None:
    """A truly minimal legacy dict (only ``key_findings``) must still lift —
    older chains may have crashed before writing every field."""
    entry = CacheEntry.from_legacy_dict(
        {"key_findings": ["lone finding"]},
        model_type="punet",
        current_iter=1,
    )
    assert entry.key_findings[0].statement == "lone finding"
    assert entry.bottlenecks == []
    assert entry.best_config_analysis.latest == ""
    assert entry.error_signatures == []
    assert entry.stats == {}


def test_legacy_error_signatures_default_empty() -> None:
    """Pre-6.3 chains never wrote error_signatures. The adapter must seed []
    (not None) so the consolidator's set-merge has a valid iterable."""
    entry = CacheEntry.from_legacy_dict(
        _legacy_entry(), model_type="punet", current_iter=7,
    )
    assert entry.error_signatures == []
