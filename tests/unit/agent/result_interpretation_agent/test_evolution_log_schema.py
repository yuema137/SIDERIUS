"""Unit tests for ``_append_evolution_log`` in
``nodes/result_interpretation_agent.py``.

Pre-4.3.4 the chain's evolution observability surface was the legacy
runner's ``_append_evolution_failure`` helper, with a tight schema
(``kind="iteration_failure"`` + ``termination_reason`` fallback from
``run_output_iter_NNN.json``). Both the helper and the runner that called
it were retired in Commit 4.3.4. The interpretation agent's
``_append_evolution_log`` is now the *only* writer of
``evolution_log.jsonl`` and the only schema the dashboard consumes.

Until now this schema was exercised only indirectly via
``tests/integration/workflows/test_v8_certification_smoke.py`` which is
``@real_run`` and expensive. Per Phase 1 §4.3.4 Gap #2 of
``docs/audit_and_optimize_token_usage_and_growth.md``, this file pins
the JSONL contract via fast unit tests:

  - file is created at ``{workspace_root}/evolution_log.jsonl``
  - each call appends exactly one well-formed JSON line
  - the writer prepends a ``timestamp`` field (ISO-8601, seconds)
  - all caller-supplied payload keys reach disk verbatim
  - non-JSON-native payload values fall back to ``default=str``
  - missing workspace_root is created (mkdirs(exist_ok=True))
  - IO errors are swallowed — observability never breaks the pipeline
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from unittest.mock import patch

from nodes.result_interpretation_agent import _append_evolution_log


_ISO_SECONDS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")


def _read_lines(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(ln) for ln in f if ln.strip()]


# ---------------------------------------------------------------------------
# 1. Basic write contract
# ---------------------------------------------------------------------------

def test_first_call_creates_file_with_one_line(tmp_path):
    """First call lands a single JSONL row at the canonical path."""
    _append_evolution_log(str(tmp_path), {"iteration": 1})
    log_path = tmp_path / "evolution_log.jsonl"
    assert log_path.exists()
    lines = _read_lines(str(log_path))
    assert len(lines) == 1


def test_caller_payload_fields_reach_disk(tmp_path):
    """The four production payload fields (iteration, evolution_stats,
    best_score_so_far, take_home_message — see callsites in
    ``result_interpretation_agent.py:1177`` and ``:1246``) must round-trip
    through json.dumps unchanged."""
    payload = {
        "iteration":         3,
        "evolution_stats":   {"vocab_total": 12, "promoted_this_iter": 2,
                              "is_degraded": False},
        "best_score_so_far": -2.4321,
        "take_home_message": "wavelet branch outperforms cnn on iter 3",
    }
    _append_evolution_log(str(tmp_path), payload)
    [row] = _read_lines(str(tmp_path / "evolution_log.jsonl"))
    for k, v in payload.items():
        assert row[k] == v, f"field {k!r} mismatch: {row.get(k)!r} != {v!r}"


def test_writer_prepends_timestamp(tmp_path):
    """``timestamp`` is added by the writer, not the caller. Shape is the
    ``datetime.isoformat(timespec='seconds')`` form (no microseconds)."""
    _append_evolution_log(str(tmp_path), {"iteration": 1})
    [row] = _read_lines(str(tmp_path / "evolution_log.jsonl"))
    assert "timestamp" in row
    assert _ISO_SECONDS.match(row["timestamp"]), (
        f"timestamp shape: {row['timestamp']!r}"
    )
    # And it is parseable.
    datetime.fromisoformat(row["timestamp"])


def test_caller_supplied_timestamp_is_overwritten(tmp_path):
    """If a caller passes ``timestamp`` in the payload, the writer's
    auto-generated one wins — order in the dict literal is
    ``{"timestamp": ..., **payload}`` so payload entries OVERRIDE.

    This test pins the *current* contract — it is documenting actual
    behaviour, not a wish. If the writer's behaviour changes (e.g., to
    refuse to overwrite), this test will catch it loudly."""
    _append_evolution_log(
        str(tmp_path),
        {"iteration": 1, "timestamp": "1999-12-31T23:59:59"},
    )
    [row] = _read_lines(str(tmp_path / "evolution_log.jsonl"))
    assert row["timestamp"] == "1999-12-31T23:59:59"


# ---------------------------------------------------------------------------
# 2. Append-only growth
# ---------------------------------------------------------------------------

def test_repeated_calls_append_distinct_rows(tmp_path):
    """The file is opened in 'a' mode — N calls must produce N rows in
    order, never overwriting prior content."""
    for i in range(1, 5):
        _append_evolution_log(str(tmp_path), {"iteration": i})
    rows = _read_lines(str(tmp_path / "evolution_log.jsonl"))
    assert [r["iteration"] for r in rows] == [1, 2, 3, 4]


def test_smoke_extension_keys_pass_through(tmp_path):
    """V8 smoke test (``test_v8_certification_smoke.py``) appends
    ``is_degraded`` and ``_smoke_marker`` alongside the production keys.
    The writer must not filter unknown keys — it is a transparent passthrough.
    """
    _append_evolution_log(str(tmp_path), {
        "iteration":     7,
        "is_degraded":   True,
        "_smoke_marker": "iter_7",
    })
    [row] = _read_lines(str(tmp_path / "evolution_log.jsonl"))
    assert row["is_degraded"] is True
    assert row["_smoke_marker"] == "iter_7"


# ---------------------------------------------------------------------------
# 3. Workspace bootstrap + IO robustness
# ---------------------------------------------------------------------------

def test_missing_workspace_is_created(tmp_path):
    """The interpretation agent calls this helper before its own iter dir
    exists; the writer must mkdirs(exist_ok=True) before opening the file."""
    deep = tmp_path / "nested" / "fresh_chain" / "agent_ws"
    assert not deep.exists()
    _append_evolution_log(str(deep), {"iteration": 1})
    assert deep.is_dir()
    assert (deep / "evolution_log.jsonl").exists()


def test_default_str_fallback_for_non_json_native_values(tmp_path):
    """A datetime in the payload should not crash json.dumps — the writer
    passes ``default=str`` so any non-native value is coerced to its repr.

    This matters because callsites occasionally include objects (e.g.,
    Pydantic ``EvolutionStats``) that json.dumps cannot serialise natively,
    and we never want the observability layer to raise."""
    when = datetime(2026, 5, 6, 12, 0, 0)
    _append_evolution_log(str(tmp_path), {
        "iteration": 1,
        "started_at": when,
    })
    [row] = _read_lines(str(tmp_path / "evolution_log.jsonl"))
    assert row["started_at"] == str(when)


def test_io_error_is_swallowed_not_raised(tmp_path, capsys):
    """If the underlying open() raises (disk full, permission denied,
    workspace removed mid-flight), the writer must NOT propagate.
    Observability is best-effort; a logger crash cannot break the chain."""
    with patch(
        "nodes.result_interpretation_agent.open",
        side_effect=OSError("simulated disk-full"),
    ):
        # Must not raise.
        _append_evolution_log(str(tmp_path), {"iteration": 1})
    err = capsys.readouterr().out
    assert "[evolution_log] WARN" in err
    assert "OSError" in err
    assert "simulated disk-full" in err
