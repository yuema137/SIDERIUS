"""Unit tests for LLMBridge._record_usage and the per-call telemetry hooks.

Covers the Commit 1 scope of
docs/audit_and_optimize_token_usage_and_growth.md:

  - Positive: a successful generate() call writes one validated
    TokenUsageRow to the configured token_usage.jsonl.
  - No-op: with run-context unbound, no file is created and no row is
    written anywhere on disk (silent plumbing-only mode for Commit 1).
  - Graceful degradation: when response.usage is None (older API shape
    or stream mode), the row is still written, with token counts None
    and char counts populated.
  - Per-attempt (Q1): a multi-attempt _chat_json content-retry produces
    exactly N rows, where N is the number of attempts; each row carries
    extra={"attempt": k, "status": <classified>}.
  - Internal labels (Q2): plan() and reflect() do not emit the
    "unlabeled" warning; their rows are stamped tuner.planner /
    tuner.reflector.
  - generate_text() and tool_call() each write one row per call; the
    tool_call no-tool-call branch still writes (the API charged either
    way) before raising.

All tests mock the OpenAI SDK's chat.completions.create — no network.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent.llm_bridge import LLMBridge
from tests.helpers.metric_fixtures import shipped_spec
from tests.unit.agent.llm_bridge.test_step00_prompt_goldens import tidmad_task_render

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _usage(prompt: int, completion: int, total: int) -> SimpleNamespace:
    """Build a fake response.usage matching the OpenAI SDK shape."""
    return SimpleNamespace(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
    )


def _chat_response(content: str, usage=None) -> MagicMock:
    """Build a mock chat.completions.create return value."""
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = None
    choice = MagicMock()
    choice.message = msg
    response = MagicMock()
    response.choices = [choice]
    # SimpleNamespace-style usage so getattr() works as in production.
    response.usage = usage
    return response


def _tool_response(name: str, args: dict, usage=None) -> MagicMock:
    tc = MagicMock()
    tc.function.name = name
    tc.function.arguments = json.dumps(args)
    tc.id = "call_abc123"
    msg = MagicMock()
    msg.tool_calls = [tc]
    msg.content = None
    choice = MagicMock()
    choice.message = msg
    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    return response


def _make_bridge_with_path(
    tmp_path: Path, run_id: str = "test-run-id", run_name: str = "test_run", iteration: int = 1
) -> LLMBridge:
    """Construct a bridge with the OpenAI client mocked + run-context bound."""
    with patch("agent.llm_bridge.OpenAI"):
        bridge = LLMBridge(provider="openai", model_id="gpt-4o-mini")
    # Manually wire the Commit-2 fields the test needs. set_run_context
    # is wired in Commit 2; for Commit 1 unit tests we simulate a bound
    # context by writing the four fields directly.
    bridge._token_usage_path = tmp_path / "token_usage.jsonl"
    bridge._run_id = run_id
    bridge._run_name = run_name
    bridge._iter = iteration
    return bridge


def _read_rows(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


# ---------------------------------------------------------------------------
# (1) Positive: one row per successful generate() call
# ---------------------------------------------------------------------------


def test_generate_writes_one_row_with_correct_counts(tmp_path):
    bridge = _make_bridge_with_path(tmp_path)
    bridge.client.chat.completions.create.return_value = _chat_response(
        '{"hello": "world"}',
        usage=_usage(prompt=100, completion=50, total=150),
    )

    out = bridge.generate("sys", "user", label="proposer.proposing")

    assert out == {"hello": "world"}
    log_path = bridge._token_usage_path
    assert log_path.exists()
    rows = _read_rows(log_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["label"] == "proposer.proposing"
    assert row["model"] == "gpt-4o-mini"
    assert row["provider"] == "openai"
    assert row["run_id"] == "test-run-id"
    assert row["iter"] == 1
    assert row["tokens"] == {"prompt": 100, "completion": 50, "total": 150}
    assert row["chars"]["system"] == 3
    assert row["chars"]["user"] == 4
    assert row["chars"]["total"] == 7
    assert row["extra"] == {"attempt": 0, "status": "ok"}
    assert row["components"] == {}


# ---------------------------------------------------------------------------
# (2) No-op when run-context unset
# ---------------------------------------------------------------------------


def test_record_usage_noop_when_unbound(tmp_path):
    """With _token_usage_path=None, no row is written anywhere."""
    with patch("agent.llm_bridge.OpenAI"):
        bridge = LLMBridge(provider="openai", model_id="gpt-4o-mini")
    # Deliberately do NOT set _token_usage_path — verify default is None.
    assert bridge._token_usage_path is None
    bridge.client.chat.completions.create.return_value = _chat_response(
        '{"x": 1}',
        usage=_usage(10, 5, 15),
    )

    out = bridge.generate("sys", "user", label="proposer.proposing")
    assert out == {"x": 1}
    # Nothing under tmp_path should have been created.
    assert list(tmp_path.iterdir()) == []
    # And no other paths either — the helper just returns without writing.


# ---------------------------------------------------------------------------
# (3) Graceful degradation: response.usage is None
# ---------------------------------------------------------------------------


def test_record_usage_handles_missing_usage(tmp_path):
    bridge = _make_bridge_with_path(tmp_path)
    bridge.client.chat.completions.create.return_value = _chat_response(
        '{"k": "v"}',
        usage=None,  # provider returned no usage object
    )

    out = bridge.generate("sys-prompt", "the-user-prompt", label="proposer.proposing")
    assert out == {"k": "v"}
    rows = _read_rows(bridge._token_usage_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["tokens"] == {"prompt": None, "completion": None, "total": None}
    # Char counts must still be populated.
    assert row["chars"]["system"] == len("sys-prompt")
    assert row["chars"]["user"] == len("the-user-prompt")
    assert row["chars"]["total"] == len("sys-prompt") + len("the-user-prompt")


# ---------------------------------------------------------------------------
# (4) Per-attempt telemetry — multi-retry produces N rows (Q1)
# ---------------------------------------------------------------------------


def test_chat_json_writes_one_row_per_attempt(tmp_path, monkeypatch):
    """Three attempts (two malformed, one valid) → three rows with
    matching attempt indices and statuses."""
    bridge = _make_bridge_with_path(tmp_path)

    # Side-effect list: bad JSON, bad JSON, good JSON.
    bridge.client.chat.completions.create.side_effect = [
        _chat_response("not json at all", usage=_usage(10, 0, 10)),
        _chat_response("{ broken", usage=_usage(11, 0, 11)),
        _chat_response('{"ok": true}', usage=_usage(12, 4, 16)),
    ]

    # Stub out time.sleep so the test is fast.
    monkeypatch.setattr("agent.llm_bridge.time.sleep", lambda _: None)

    out = bridge.generate("s", "u", label="proposer.proposing")
    assert out == {"ok": True}

    rows = _read_rows(bridge._token_usage_path)
    assert len(rows) == 3, f"expected 3 rows (one per attempt), got {len(rows)}"
    assert [r["extra"]["attempt"] for r in rows] == [0, 1, 2]
    assert [r["extra"]["status"] for r in rows] == [
        "json_decode_error",
        "json_decode_error",
        "ok",
    ]
    # Token counts per attempt match the side_effect sequence.
    assert [r["tokens"]["prompt"] for r in rows] == [10, 11, 12]


def test_chat_json_writes_row_for_empty_content(tmp_path, monkeypatch):
    bridge = _make_bridge_with_path(tmp_path)
    # First attempt empty, second OK
    bridge.client.chat.completions.create.side_effect = [
        _chat_response("", usage=_usage(5, 0, 5)),
        _chat_response('{"ok": 1}', usage=_usage(6, 1, 7)),
    ]
    monkeypatch.setattr("agent.llm_bridge.time.sleep", lambda _: None)

    out = bridge.generate("s", "u", label="proposer.proposing")
    assert out == {"ok": 1}

    rows = _read_rows(bridge._token_usage_path)
    assert len(rows) == 2
    assert rows[0]["extra"]["status"] == "empty_content"
    assert rows[1]["extra"]["status"] == "ok"


# ---------------------------------------------------------------------------
# (5) generate_text() and tool_call() coverage
# ---------------------------------------------------------------------------


def test_generate_text_writes_one_row(tmp_path):
    bridge = _make_bridge_with_path(tmp_path)
    bridge.client.chat.completions.create.return_value = _chat_response(
        "free-form text response  \n",
        usage=_usage(20, 10, 30),
    )

    out = bridge.generate_text("sys", "user", label="proposer.causal_reasoning")
    assert out == "free-form text response"

    rows = _read_rows(bridge._token_usage_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["label"] == "proposer.causal_reasoning"
    assert row["tokens"] == {"prompt": 20, "completion": 10, "total": 30}
    assert row["extra"] == {"attempt": 0, "status": "ok"}


def test_tool_call_writes_one_row_on_success(tmp_path):
    bridge = _make_bridge_with_path(tmp_path)
    bridge.client.chat.completions.create.return_value = _tool_response(
        "do_thing",
        {"x": 1},
        usage=_usage(15, 5, 20),
    )
    tools = [{"type": "function", "function": {"name": "do_thing", "parameters": {}}}]
    result = bridge.tool_call("s", "u", tools, label="validator.code_review")
    assert result.name == "do_thing"
    assert result.arguments == {"x": 1}

    rows = _read_rows(bridge._token_usage_path)
    assert len(rows) == 1
    assert rows[0]["extra"] == {"attempt": 0, "status": "ok"}
    assert rows[0]["label"] == "validator.code_review"


def test_tool_call_writes_row_then_raises_when_no_tool_call(tmp_path):
    """Even when the model returns plain text instead of a tool call, the
    API charged for the tokens — telemetry must still record it."""
    bridge = _make_bridge_with_path(tmp_path)
    msg = MagicMock()
    msg.tool_calls = None
    msg.content = "I refuse to call a tool."
    choice = MagicMock()
    choice.message = msg
    response = MagicMock()
    response.choices = [choice]
    response.usage = _usage(8, 4, 12)
    bridge.client.chat.completions.create.return_value = response

    with pytest.raises(ValueError, match="did not return a tool call"):
        bridge.tool_call("s", "u", [], label="validator.code_review")

    rows = _read_rows(bridge._token_usage_path)
    assert len(rows) == 1
    assert rows[0]["extra"] == {"attempt": 0, "status": "no_tool_call"}


# ---------------------------------------------------------------------------
# (6) Internal labels — plan() / reflect() do not warn (Q2)
# ---------------------------------------------------------------------------


def test_plan_uses_tuner_planner_label(tmp_path, capsys):
    bridge = _make_bridge_with_path(tmp_path)
    bridge.client.chat.completions.create.return_value = _chat_response(
        '{"action": "tune", "params": {}}',
        usage=_usage(30, 10, 40),
    )
    # plan() needs a memory_history; an empty list exercises the prompt path.
    bridge.plan(
        memory_history=[],
        expert_advice="None",
        current_round=1,
        max_rounds=3,
        # Step 07 PR 07b — required at a real render; this test pins the LABEL.
        task_render=tidmad_task_render(),
        metric_spec=shipped_spec(),
    )

    rows = _read_rows(bridge._token_usage_path)
    assert len(rows) == 1
    assert rows[0]["label"] == "tuner.planner"
    captured = capsys.readouterr()
    assert "WARNING: called without label=" not in captured.err


def test_reflect_uses_tuner_reflector_label(tmp_path, capsys):
    bridge = _make_bridge_with_path(tmp_path)
    bridge.client.chat.completions.create.return_value = _chat_response(
        '{"updated_memory": []}',
        usage=_usage(25, 8, 33),
    )
    bridge.reflect(
        exp_id="exp1", hypothesis="h", actual_results={"score": 1.0}, metric_spec=shipped_spec()
    )

    rows = _read_rows(bridge._token_usage_path)
    assert len(rows) == 1
    assert rows[0]["label"] == "tuner.reflector"
    captured = capsys.readouterr()
    assert "WARNING: called without label=" not in captured.err


# ---------------------------------------------------------------------------
# (7) Default label fires the warning
# ---------------------------------------------------------------------------


def test_generate_default_label_emits_warning(tmp_path, capsys):
    bridge = _make_bridge_with_path(tmp_path)
    bridge.client.chat.completions.create.return_value = _chat_response(
        '{"x": 1}',
        usage=_usage(1, 1, 2),
    )
    bridge.generate("s", "u")  # no label= → default "unlabeled"

    captured = capsys.readouterr()
    assert "[LLMBridge.generate] WARNING: called without label=" in captured.err
    rows = _read_rows(bridge._token_usage_path)
    assert rows[0]["label"] == "unlabeled"
