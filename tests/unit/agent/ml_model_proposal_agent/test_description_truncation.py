"""Unit tests for _truncate_description (Phase 6.8 Commit 10).

Validates that model descriptions are capped at 1500 characters for prompt
injection while leaving the original disk artifacts intact.
"""
from __future__ import annotations

from nodes.ml_model_proposal_agent import _truncate_description


def test_short_description_unchanged():
    text = "A simple wavenet model with dilated convolutions."
    assert _truncate_description(text) == text


def test_exact_limit_unchanged():
    text = "x" * 1500
    assert _truncate_description(text) == text


def test_over_limit_truncated_with_marker():
    text = "x" * 7000
    result = _truncate_description(text)
    assert len(result) == 1500 + len("\n[...truncated]")
    assert result.endswith("\n[...truncated]")
    assert result[:1500] == "x" * 1500


def test_custom_limit():
    text = "abcdef" * 100  # 600 chars
    result = _truncate_description(text, max_chars=200)
    assert result[:200] == text[:200]
    assert result.endswith("\n[...truncated]")


def test_7kb_description_capped():
    """The design doc example: 7KB description → 1500 chars + marker."""
    text = "A" * 7168  # 7 KB
    result = _truncate_description(text)
    assert len(result) < 1600
    assert result.startswith("A" * 1500)
    assert "[...truncated]" in result
