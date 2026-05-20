"""Tests for ``LLMBridge.set_run_context`` and the four §1.4.1 per-row
pre-write invariant checks (Commit 2 of
``docs/audit_and_optimize_token_usage_and_growth.md``).

Coverage map:

    - happy path:               test_setter_happy_path
    - iter advancement flush:   test_setter_advance_iter_writes_flush_marker
    - same-iter re-entry:       test_setter_same_iter_no_flush
    - run_id mutation:          test_setter_rejects_run_id_mutation
    - backwards iter:           test_setter_rejects_backwards_iter
    - missing workspace:        test_setter_raises_oserror_on_missing_workspace
    - file-level run_id check:  test_record_usage_aborts_on_runid_mismatch
    - 5-iter quantitative:      test_5_iter_quantitative_and_linter_passes
    - linter — leak:            test_linter_detects_post_flush_leak
    - linter — run_id mismatch: test_linter_detects_run_id_mismatch
    - thread-safety:            test_setter_thread_safety
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent.llm_bridge import LLMBridge
from agent.schemas.telemetry import LLMBridgeContextError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _usage(p: int, c: int, t: int) -> SimpleNamespace:
    return SimpleNamespace(prompt_tokens=p, completion_tokens=c, total_tokens=t)


def _chat_response(content: str, usage=None) -> MagicMock:
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = None
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    return resp


def _make_bridge() -> LLMBridge:
    with patch("agent.llm_bridge.OpenAI"):
        return LLMBridge(provider="openai", model_id="gpt-4o-mini")


def _read_rows(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_setter_happy_path(tmp_path):
    bridge = _make_bridge()
    bridge.set_run_context(workspace=tmp_path, iter=0, run_name="r", run_id="r-001")
    assert bridge._token_usage_path == tmp_path / "token_usage.jsonl"
    assert bridge._iter == 0
    assert bridge._run_id == "r-001"
    assert bridge._run_name == "r"
    assert bridge._set_at_ts is not None

    bridge.client.chat.completions.create.return_value = _chat_response(
        '{"ok": 1}', usage=_usage(10, 5, 15)
    )
    out = bridge.generate("sys", "user", label="proposer.proposing")
    assert out == {"ok": 1}

    rows = _read_rows(bridge._token_usage_path)
    assert len(rows) == 1
    assert rows[0]["iter"] == 0
    assert rows[0]["run_id"] == "r-001"
    assert rows[0]["label"] == "proposer.proposing"


# ---------------------------------------------------------------------------
# Iter advancement → one _iter_flush marker for the prior iter
# ---------------------------------------------------------------------------


def test_setter_advance_iter_writes_flush_marker(tmp_path):
    bridge = _make_bridge()
    bridge.set_run_context(workspace=tmp_path, iter=3, run_name="r", run_id="r-001")
    bridge.client.chat.completions.create.return_value = _chat_response("{}", usage=_usage(1, 1, 2))
    bridge.generate("s", "u", label="lbl")

    bridge.set_run_context(workspace=tmp_path, iter=4, run_name="r", run_id="r-001")

    rows = _read_rows(bridge._token_usage_path)
    assert len(rows) == 2, rows
    assert rows[0]["label"] == "lbl" and rows[0]["iter"] == 3
    assert rows[1]["label"] == "_iter_flush"
    assert rows[1]["iter"] == 3
    assert rows[1]["extra"] == {"marker": "iter_end"}
    assert rows[1]["tokens"] == {"prompt": None, "completion": None, "total": None}
    assert rows[1]["chars"] == {"system": 0, "user": 0, "total": 0}


# ---------------------------------------------------------------------------
# Same-iter re-entry: no marker, state-update only
# ---------------------------------------------------------------------------


def test_setter_same_iter_no_flush(tmp_path):
    bridge = _make_bridge()
    bridge.set_run_context(workspace=tmp_path, iter=2, run_name="r", run_id="r-001")
    bridge.client.chat.completions.create.return_value = _chat_response("{}", usage=_usage(1, 1, 2))
    bridge.generate("s", "u", label="lbl")
    # Same-iter re-entry — represents a stage retry within iter 2.
    bridge.set_run_context(workspace=tmp_path, iter=2, run_name="r", run_id="r-001")
    bridge.generate("s", "u", label="lbl")

    rows = _read_rows(bridge._token_usage_path)
    assert len(rows) == 2
    assert all(r["label"] != "_iter_flush" for r in rows)


# ---------------------------------------------------------------------------
# Negative: run_id mutation
# ---------------------------------------------------------------------------


def test_setter_rejects_run_id_mutation(tmp_path):
    bridge = _make_bridge()
    bridge.set_run_context(workspace=tmp_path, iter=0, run_name="r", run_id="r-A")
    with pytest.raises(LLMBridgeContextError, match="run_id mutation forbidden"):
        bridge.set_run_context(workspace=tmp_path, iter=0, run_name="r", run_id="r-B")
    # The rejected call leaves the bridge bound to the original run_id.
    assert bridge._run_id == "r-A"


# ---------------------------------------------------------------------------
# Negative: backwards iter
# ---------------------------------------------------------------------------


def test_setter_rejects_backwards_iter(tmp_path):
    bridge = _make_bridge()
    bridge.set_run_context(workspace=tmp_path, iter=5, run_name="r", run_id="r-A")
    with pytest.raises(LLMBridgeContextError, match="backwards iter"):
        bridge.set_run_context(workspace=tmp_path, iter=3, run_name="r", run_id="r-A")
    assert bridge._iter == 5


# ---------------------------------------------------------------------------
# Negative: workspace dir does not exist (loud OSError, not silent swallow)
# ---------------------------------------------------------------------------


def test_setter_raises_oserror_on_missing_workspace(tmp_path):
    bridge = _make_bridge()
    missing = tmp_path / "doesnotexist"
    with pytest.raises(OSError, match="does not exist"):
        bridge.set_run_context(workspace=missing, iter=0, run_name="r", run_id="r-A")
    # Bridge state stays unbound after the failed setter.
    assert bridge._token_usage_path is None


def test_setter_raises_value_error_on_negative_iter(tmp_path):
    bridge = _make_bridge()
    with pytest.raises(ValueError, match="non-negative"):
        bridge.set_run_context(workspace=tmp_path, iter=-1, run_name="r", run_id="r-A")


# ---------------------------------------------------------------------------
# Negative: pre-existing JSONL with a different run_id aborts the write.
# ---------------------------------------------------------------------------


def test_record_usage_aborts_on_runid_mismatch(tmp_path):
    log = tmp_path / "token_usage.jsonl"
    pre_seeded_row = {
        "ts": "2026-05-04T00:00:00.000Z",
        "run_id": "OTHER-RUN",
        "run_name": "other",
        "iter": 0,
        "label": "lbl",
        "model": "m",
        "provider": "openai",
        "tokens": {"prompt": 1, "completion": 1, "total": 2},
        "chars": {"system": 1, "user": 1, "total": 2},
        "components": {},
        "extra": {},
    }
    log.write_text(json.dumps(pre_seeded_row) + "\n")

    bridge = _make_bridge()
    bridge.set_run_context(workspace=tmp_path, iter=0, run_name="r", run_id="r-MINE")
    bridge.client.chat.completions.create.return_value = _chat_response("{}", usage=_usage(1, 1, 2))
    with pytest.raises(LLMBridgeContextError, match="run_id mismatch"):
        bridge.generate("s", "u", label="lbl")
    # File is unchanged: still exactly the one pre-seeded row.
    rows = _read_rows(log)
    assert len(rows) == 1
    assert rows[0]["run_id"] == "OTHER-RUN"


# ---------------------------------------------------------------------------
# Quantitative: 5 iters * 12 calls = 60 rows + 4 flush markers (no final flush)
# ---------------------------------------------------------------------------


def test_5_iter_quantitative_and_linter_passes(tmp_path):
    bridge = _make_bridge()
    bridge.client.chat.completions.create.side_effect = [
        _chat_response("{}", usage=_usage(1, 1, 2)) for _ in range(60)
    ]
    for it in range(5):
        bridge.set_run_context(workspace=tmp_path, iter=it, run_name="r", run_id="r-001")
        for _ in range(12):
            bridge.generate("s", "u", label="lbl")

    rows = _read_rows(bridge._token_usage_path)
    flush_rows = [r for r in rows if r["label"] == "_iter_flush"]
    data_rows = [r for r in rows if r["label"] != "_iter_flush"]

    assert len(data_rows) == 60, f"expected 60 data rows, got {len(data_rows)}"
    assert len(flush_rows) == 4, f"expected 4 flush rows, got {len(flush_rows)}"
    assert [r["iter"] for r in flush_rows] == [0, 1, 2, 3]
    # No flush after the final iter (iter=4).
    assert all(r["iter"] != 4 or r["label"] != "_iter_flush" for r in rows)

    # Linter: file is clean.
    from tools.validate_token_usage_jsonl import lint

    errors, warnings = lint(bridge._token_usage_path)
    assert errors == [], f"linter found errors on a clean file: {errors}"


# ---------------------------------------------------------------------------
# Linter: detects post-flush leak
# ---------------------------------------------------------------------------


def _make_row(**overrides) -> dict:
    base = {
        "ts": "2026-05-04T00:00:00.000Z",
        "run_id": "r-001",
        "run_name": "r",
        "iter": 0,
        "label": "lbl",
        "model": "m",
        "provider": "openai",
        "tokens": {"prompt": 1, "completion": 1, "total": 2},
        "chars": {"system": 1, "user": 1, "total": 2},
        "components": {},
        "extra": {},
    }
    base.update(overrides)
    return base


def test_linter_detects_post_flush_leak(tmp_path):
    log = tmp_path / "token_usage.jsonl"
    rows = [
        _make_row(ts="2026-05-04T00:00:01.000Z", iter=4, label="lbl"),
        _make_row(
            ts="2026-05-04T00:00:02.000Z",
            iter=4,
            label="_iter_flush",
            tokens={"prompt": None, "completion": None, "total": None},
            chars={"system": 0, "user": 0, "total": 0},
            extra={"marker": "iter_end"},
        ),
        _make_row(ts="2026-05-04T00:00:03.000Z", iter=4, label="leak_row"),
    ]
    log.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    from tools.validate_token_usage_jsonl import lint, main

    errors, _ = lint(log)
    assert any("[LEAK]" in e for e in errors), errors
    assert main([str(log)]) == 1


def test_linter_detects_run_id_mismatch(tmp_path):
    log = tmp_path / "token_usage.jsonl"
    rows = [
        _make_row(ts="2026-05-04T00:00:01.000Z", run_id="r-OWNER"),
        _make_row(ts="2026-05-04T00:00:02.000Z", run_id="r-INTRUDER"),
    ]
    log.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    from tools.validate_token_usage_jsonl import lint

    errors, _ = lint(log)
    assert any("[RUN_ID_MISMATCH]" in e for e in errors), errors


def test_linter_warns_on_non_monotonic_ts(tmp_path):
    log = tmp_path / "token_usage.jsonl"
    rows = [
        _make_row(ts="2026-05-04T00:00:02.000Z"),
        _make_row(ts="2026-05-04T00:00:01.000Z"),  # earlier than prior
    ]
    log.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    from tools.validate_token_usage_jsonl import lint

    errors, warnings = lint(log)
    assert errors == []
    assert any("non-monotonic ts" in w for w in warnings), warnings


# ---------------------------------------------------------------------------
# Thread-safety: lock serializes set_run_context vs concurrent _record_usage
# ---------------------------------------------------------------------------


def test_setter_thread_safety_no_duplicate_flush(tmp_path):
    """Eight threads racing on set_run_context(iter=0) (same iter as the
    bridge's current state) must produce zero ``_iter_flush`` markers
    regardless of interleaving — the strict-greater-than guard prevents
    redundant markers."""
    bridge = _make_bridge()
    bridge.set_run_context(workspace=tmp_path, iter=0, run_name="r", run_id="r-001")
    bridge.client.chat.completions.create.return_value = _chat_response("{}", usage=_usage(1, 1, 2))

    barrier = threading.Barrier(8)
    errors: list[BaseException] = []

    def worker():
        barrier.wait()
        try:
            bridge.set_run_context(workspace=tmp_path, iter=0, run_name="r", run_id="r-001")
            bridge.generate("s", "u", label="lbl")
        except BaseException as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"thread errors: {errors}"
    rows = _read_rows(bridge._token_usage_path)
    flush_rows = [r for r in rows if r["label"] == "_iter_flush"]
    assert flush_rows == [], (
        f"expected no flush markers under same-iter contention, got {len(flush_rows)}: {flush_rows}"
    )
    # Eight threads each wrote one row → eight data rows total.
    assert len([r for r in rows if r["label"] != "_iter_flush"]) == 8
