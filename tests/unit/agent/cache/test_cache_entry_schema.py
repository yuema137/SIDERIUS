"""Commit 6.3 / C1 — schema validation tests for the consolidated cache entry.

Parametrized to keep the defensive shield intact (strict-mode rejections,
length-bound caps, extra='forbid') while contracting one-input-per-test
fixtures into single parametrized functions with explicit case IDs.

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
  6. ``CacheEntry.from_legacy_dict`` is zero-friction for pre-6.3 chains.
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


def test_finding_accepts_max_length_statement() -> None:
    """Boundary guard (off-by-one): exactly at the cap must succeed."""
    f = ConsolidatedFinding(
        statement="x" * FINDING_STATEMENT_MAX_CHARS,
        evidence_iters=[1],
        strength="moderate",
    )
    assert len(f.statement) == FINDING_STATEMENT_MAX_CHARS


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param(
            dict(statement="", evidence_iters=[1], strength="weak"),
            id="empty_statement",
        ),
        pytest.param(
            dict(
                statement="x" * (FINDING_STATEMENT_MAX_CHARS + 1),
                evidence_iters=[1],
                strength="moderate",
            ),
            id="oversized_statement",
        ),
        pytest.param(
            dict(statement="ok", evidence_iters=[], strength="weak"),
            id="empty_evidence_iters",
        ),
        pytest.param(
            dict(statement="ok", evidence_iters=[3, -1], strength="weak"),
            id="negative_iter",
        ),
        pytest.param(
            dict(statement="ok", evidence_iters=[1], strength="extreme"),
            id="unknown_strength",
        ),
        pytest.param(
            dict(statement="ok", evidence_iters=[1], strength="weak", unexpected="should fail"),
            id="extra_field_forbidden",
        ),
    ],
)
def test_finding_rejects_invalid_input(kwargs) -> None:
    """Defensive shield: every documented rejection must keep raising
    ValidationError. Covers empty/oversized text, evidence-iter constraints,
    closed-enum strength, and extra='forbid' against silent schema drift."""
    with pytest.raises(ValidationError):
        ConsolidatedFinding(**kwargs)  # type: ignore[arg-type]


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


@pytest.mark.parametrize(
    "kwargs, attr, expected_len",
    [
        pytest.param(
            dict(latest="x" * NARRATIVE_LATEST_MAX_CHARS),
            "latest",
            NARRATIVE_LATEST_MAX_CHARS,
            id="max_length_latest",
        ),
        pytest.param(
            dict(latest="ok", history=[(i, f"n{i}") for i in range(NARRATIVE_HISTORY_MAX_ENTRIES)]),
            "history",
            NARRATIVE_HISTORY_MAX_ENTRIES,
            id="max_history_entries",
        ),
    ],
)
def test_narrative_accepts_at_boundary(kwargs, attr, expected_len) -> None:
    """Boundary guards (off-by-one) for both string and list caps."""
    n = ConsolidatedNarrative(**kwargs)
    assert len(getattr(n, attr)) == expected_len


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param(
            dict(latest="x" * (NARRATIVE_LATEST_MAX_CHARS + 1)),
            id="oversized_latest",
        ),
        pytest.param(
            dict(
                latest="ok",
                history=[
                    (i, f"narrative iter {i}") for i in range(NARRATIVE_HISTORY_MAX_ENTRIES + 1)
                ],
            ),
            id="over_cap_history",
        ),
        pytest.param(
            dict(latest="ok", history=[(-1, "bad")]),
            id="negative_history_iter",
        ),
        pytest.param(
            dict(latest="ok", surprise="nope"),
            id="extra_field_forbidden",
        ),
    ],
)
def test_narrative_rejects_invalid_input(kwargs) -> None:
    """Defensive shield: every documented rejection still raises."""
    with pytest.raises(ValidationError):
        ConsolidatedNarrative(**kwargs)  # type: ignore[arg-type]


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
    assert sig.key() == ("vram", "ml_models/foo.py:42 in forward", "torch.cuda.OutOfMemoryError")


def test_error_sig_accepts_empty_last_frames() -> None:
    """Spec §2.2: last_frames may be empty for non-Python failure modes."""
    sig = _valid_error_sig(last_frames=[], top_user_frame="")
    assert sig.last_frames == []
    assert sig.top_user_frame == ""


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param(dict(failure_class="cosmic_ray"), id="unknown_failure_class"),
        pytest.param(
            dict(short_message="x" * (ERROR_SHORT_MESSAGE_MAX_CHARS + 1)),
            id="oversized_short_message",
        ),
        pytest.param(dict(evidence_iters=[]), id="empty_evidence_iters"),
        pytest.param(dict(error_type=""), id="empty_error_type"),
        pytest.param(dict(unexpected="nope"), id="extra_field_forbidden"),
    ],
)
def test_error_sig_rejects_invalid_input(overrides) -> None:
    """Defensive shield: every documented rejection still raises."""
    with pytest.raises(ValidationError):
        _valid_error_sig(**overrides)


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
            latest="d=6,w=128",
            history=[(2, "d=4 too shallow")],
        ),
        error_signatures=[_valid_error_sig()],
        stats={"best_score": 1.23, "completed_rounds": 4},
    )
    dumped = e.model_dump()
    re_parsed = CacheEntry.model_validate(dumped)
    assert re_parsed.error_signatures[0].key() == e.error_signatures[0].key()


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param({}, id="missing_model_type"),
        pytest.param({"model_type": ""}, id="empty_model_type"),
        pytest.param(
            {"model_type": "punet", "surprise_field": 1},
            id="extra_field_forbidden",
        ),
    ],
)
def test_cache_entry_rejects_invalid_input(kwargs) -> None:
    """Defensive shield: every documented rejection still raises.
    Pre-empts the LLM-output schema drift hazard the spec calls out."""
    with pytest.raises(ValidationError):
        CacheEntry(**kwargs)  # type: ignore[call-arg]


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
        _legacy_entry(),
        model_type="punet",
        current_iter=7,
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
        _legacy_entry(),
        model_type="punet",
        current_iter=7,
    )
    assert entry.best_config_analysis.latest == "depth=6, width=128 outperforms"
    assert entry.best_config_analysis.history == []
    assert entry.score_trend.latest.startswith("monotone improvement")
    # All 6 narrative fields populated by the lift, none left at default-empty.
    for field in (
        "best_config_analysis",
        "score_trend",
        "per_file_analysis",
        "data_sensitivity",
        "efficiency_assessment",
        "strategy_assessment",
    ):
        assert getattr(entry, field).latest != ""


def test_legacy_drops_empty_findings_strings() -> None:
    """A legacy entry with empty / whitespace-only findings would fail
    ConsolidatedFinding.statement's min_length=1. The adapter must drop
    them so chain resume does not crash."""
    legacy = _legacy_entry()
    legacy["key_findings"] = ["valid finding", "", "   ", "another valid one"]
    entry = CacheEntry.from_legacy_dict(
        legacy,
        model_type="punet",
        current_iter=7,
    )
    assert len(entry.key_findings) == 2
    assert all(f.statement.strip() for f in entry.key_findings)


@pytest.mark.parametrize(
    "legacy_field, overlong_value, target_attr_path, expected_len",
    [
        pytest.param(
            "key_findings",
            ["x" * (FINDING_STATEMENT_MAX_CHARS + 100)],
            "key_findings[0].statement",
            FINDING_STATEMENT_MAX_CHARS,
            id="oversized_finding_statement",
        ),
        pytest.param(
            "score_trend",
            "y" * (NARRATIVE_LATEST_MAX_CHARS + 100),
            "score_trend.latest",
            NARRATIVE_LATEST_MAX_CHARS,
            id="oversized_narrative_latest",
        ),
    ],
)
def test_legacy_truncates_oversized_inputs(
    legacy_field,
    overlong_value,
    target_attr_path,
    expected_len,
) -> None:
    """Adapter truncates legacy strings exceeding the new caps rather than
    raising — zero-friction chain resume."""
    legacy = _legacy_entry()
    legacy[legacy_field] = overlong_value
    entry = CacheEntry.from_legacy_dict(
        legacy,
        model_type="punet",
        current_iter=1,
    )
    # Resolve dotted/indexed path (e.g. "key_findings[0].statement").
    val = entry
    for part in target_attr_path.split("."):
        if "[" in part:
            name, idx = part[:-1].split("[")
            val = getattr(val, name)[int(idx)]
        else:
            val = getattr(val, part)
    assert len(val) == expected_len


@pytest.mark.parametrize(
    "stats_key, expected",
    [
        pytest.param(
            "_stats",
            {"best_score": 0.78, "completed_rounds": 3},
            id="underscored_legacy_key",
        ),
        pytest.param(
            "stats",
            {"best_score": 0.99},
            id="forward_canonical_key",
        ),
    ],
)
def test_legacy_accepts_stats_key_aliases(stats_key, expected) -> None:
    """Legacy code wrote ``_stats``; the new schema reads ``stats``. The
    adapter must accept both so we don't silently lose numerical context."""
    legacy = _legacy_entry()
    if stats_key == "stats":
        legacy.pop("_stats")
        legacy["stats"] = expected
    entry = CacheEntry.from_legacy_dict(
        legacy,
        model_type="punet",
        current_iter=1,
    )
    assert entry.stats == expected


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
        _legacy_entry(),
        model_type="punet",
        current_iter=7,
    )
    assert entry.error_signatures == []
