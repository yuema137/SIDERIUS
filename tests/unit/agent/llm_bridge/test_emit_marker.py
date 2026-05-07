"""Unit tests for ``LLMBridge.emit_marker``.

Covers Commit 6.1 (Stability Filter) audit-log support:

  - Successful emit: a synthetic row with zeroed token/char counts is
    appended to ``token_usage.jsonl`` with the caller-provided label
    and extra dict round-tripped verbatim.
  - Silent no-op when the bridge has no run-context bound (mirrors
    ``_record_usage`` behaviour — Commit 1).
  - Empty ``label`` rejected with ``ValueError`` so a corrupt marker
    never reaches disk.
  - Multiple emits preserve JSONL ordering and each row carries its own
    ``extra`` payload (no payload bleed between rows).

These are pure-bridge tests — no LLM call, no agent. The OpenAI client
is patched out because ``LLMBridge.__init__`` instantiates it.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.llm_bridge import LLMBridge


def _make_bridge_with_path(tmp_path: Path,
                           run_id: str = "marker-run-id",
                           run_name: str = "marker_run",
                           iteration: int = 1) -> LLMBridge:
    """Construct a bridge with the OpenAI client mocked + run-context bound.

    Mirrors the helper in ``test_record_usage.py`` so the two suites share
    the same setup contract.
    """
    with patch("agent.llm_bridge.OpenAI"):
        bridge = LLMBridge(provider="openai", model_id="gpt-4o-mini")
    bridge._token_usage_path = tmp_path / "token_usage.jsonl"
    bridge._run_id = run_id
    bridge._run_name = run_name
    bridge._iter = iteration
    return bridge


def _read_rows(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


# ---------------------------------------------------------------------------
# (1) Successful emit — one zeroed row
# ---------------------------------------------------------------------------

def test_emit_marker_writes_zeroed_row(tmp_path):
    bridge = _make_bridge_with_path(tmp_path)

    bridge.emit_marker(
        label="interpretation.per_model_skipped",
        extra={"reason": "stable", "model_type": "punet"},
    )

    rows = _read_rows(bridge._token_usage_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["label"] == "interpretation.per_model_skipped"
    assert row["model"] is None
    assert row["provider"] is None
    # tokens: TokenCounts() defaults are all None
    assert row["tokens"] == {"prompt": None, "completion": None, "total": None}
    # chars: explicit zeros (the marker has no prompt content)
    assert row["chars"] == {"system": 0, "user": 0, "total": 0}
    assert row["components"] == {}
    assert row["extra"] == {"reason": "stable", "model_type": "punet"}
    # iter / run identity propagate from the bound context
    assert row["iter"] == 1
    assert row["run_id"] == "marker-run-id"
    assert row["run_name"] == "marker_run"


# ---------------------------------------------------------------------------
# (2) Silent no-op when run-context is unset
# ---------------------------------------------------------------------------

def test_emit_marker_noop_when_unbound(tmp_path):
    """With ``_token_usage_path=None``, emit_marker writes nothing."""
    with patch("agent.llm_bridge.OpenAI"):
        bridge = LLMBridge(provider="openai", model_id="gpt-4o-mini")
    assert bridge._token_usage_path is None

    bridge.emit_marker(
        label="interpretation.per_model_skipped",
        extra={"reason": "stable", "model_type": "punet"},
    )

    # No file under tmp_path was created; the helper returned silently.
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------------
# (3) Empty label rejected
# ---------------------------------------------------------------------------

def test_emit_marker_rejects_empty_label(tmp_path):
    bridge = _make_bridge_with_path(tmp_path)

    with pytest.raises(ValueError, match="non-empty label"):
        bridge.emit_marker(label="", extra={"reason": "stable"})

    # Rejection happens before any file write.
    assert not bridge._token_usage_path.exists()


# ---------------------------------------------------------------------------
# (4) extra dict round-trips intact
# ---------------------------------------------------------------------------

def test_emit_marker_extra_round_trips(tmp_path):
    bridge = _make_bridge_with_path(tmp_path)

    payload = {
        "reason": "stable",
        "model_type": "wavenet_dilated",
        "nested": [1, 2, 3],
        "scalar": 0.05,
    }
    bridge.emit_marker(
        label="interpretation.per_model_skipped",
        extra=payload,
    )

    rows = _read_rows(bridge._token_usage_path)
    assert rows[0]["extra"] == payload


# ---------------------------------------------------------------------------
# (5) JSONL ordering preserved across multiple emits
# ---------------------------------------------------------------------------

def test_emit_marker_jsonl_ordering(tmp_path):
    bridge = _make_bridge_with_path(tmp_path)

    for i in range(1, 4):
        bridge.emit_marker(
            label="interpretation.per_model_skipped",
            extra={"reason": "stable", "model_type": f"m{i}", "ord": i},
        )

    rows = _read_rows(bridge._token_usage_path)
    assert len(rows) == 3
    # Rows appear in the order of emission (append-only JSONL).
    assert [r["extra"]["ord"] for r in rows] == [1, 2, 3]
    assert [r["extra"]["model_type"] for r in rows] == ["m1", "m2", "m3"]
    # Each row independently carries label + zeroed counts.
    for row in rows:
        assert row["label"] == "interpretation.per_model_skipped"
        assert row["chars"] == {"system": 0, "user": 0, "total": 0}


# ---------------------------------------------------------------------------
# (6) None extra is allowed and serialises to {}
# ---------------------------------------------------------------------------

def test_emit_marker_accepts_none_extra(tmp_path):
    bridge = _make_bridge_with_path(tmp_path)

    bridge.emit_marker(label="interpretation.per_model_skipped")
    rows = _read_rows(bridge._token_usage_path)
    assert len(rows) == 1
    assert rows[0]["extra"] == {}
