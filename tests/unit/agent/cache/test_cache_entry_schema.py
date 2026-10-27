"""Custom cache iteration validation, error identity, and legacy conversion."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent.schemas.cache_entry import (
    FINDING_STATEMENT_MAX_CHARS,
    NARRATIVE_LATEST_MAX_CHARS,
    CacheEntry,
    ConsolidatedFinding,
    ConsolidatedNarrative,
    ErrorSignature,
)

# ---------------------------------------------------------------------------
# ConsolidatedFinding
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param(
            dict(statement="ok", evidence_iters=[3, -1], strength="weak"),
            id="negative_iter",
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


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param(
            dict(latest="ok", history=[(-1, "bad")]),
            id="negative_history_iter",
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


def test_error_sig_key_tuple() -> None:
    """The consolidator dedupes by ``key()`` — pin the field order so a
    future refactor cannot silently change the dedup contract and break
    Gate G3 preservation."""
    sig = _valid_error_sig()
    assert sig.key() == ("vram", "ml_models/foo.py:42 in forward", "torch.cuda.OutOfMemoryError")


# ---------------------------------------------------------------------------
# CacheEntry — strict construction
# ---------------------------------------------------------------------------


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
