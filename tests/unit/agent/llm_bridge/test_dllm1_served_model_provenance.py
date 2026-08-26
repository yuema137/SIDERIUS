"""D-LLM-1 / 66b — persisted provenance records what the provider SERVED.

**The defect.** ``agent/llm_bridge.py`` captured ``response.usage`` and
discarded the response's model identity entirely — ``response.model`` appeared
nowhere in the file. The persisted ``token_usage`` row's ``model`` field is
the value the CALLER passed in, so it is the CONFIGURED id echoed back.

**Why that is not provenance.** After 66a pins the config to
``gpt-5.5-2026-04-23``, the row reads ``gpt-5.5-2026-04-23``. If the provider
served something else, the row would read *exactly the same*. A field that
records what you asked for rather than what you got cannot discriminate the
two cases — so it can never fail, and a check that cannot fail is not a check.

The contrast that makes it concrete: the config ``sha256`` in the parameter
table IS an observation — computed from bytes, so it moves when the file
moves. ``served_model`` has to be an observation in the same sense.

**Scope.** Recording only. These tests deliberately do NOT assert that the
served and configured values agree — whether a mismatch should refuse is a
separate decision, and recording is its prerequisite, not its implementation.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agent.llm_bridge import LLMBridge

CONFIGURED = "gpt-5.5-2026-04-23"
SERVED = "gpt-5.5-2026-09-99-hotfix"


def _usage() -> SimpleNamespace:
    return SimpleNamespace(prompt_tokens=11, completion_tokens=7, total_tokens=18)


def _chat_response(content: str, *, served: str | None) -> MagicMock:
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = None
    choice = MagicMock()
    choice.message = msg
    response = MagicMock()
    response.choices = [choice]
    response.usage = _usage()
    # A MagicMock would auto-create `.model` as a Mock, which is exactly the
    # non-string case production guards against — set it explicitly so the
    # test controls what the "provider" reported.
    response.model = served
    return response


def _bridge(tmp_path: Path) -> LLMBridge:
    with patch("agent.llm_bridge.OpenAI"):
        bridge = LLMBridge(provider="openai", model_id=CONFIGURED)
    bridge._token_usage_path = tmp_path / "token_usage.jsonl"
    bridge._run_id = "dllm1-run"
    bridge._run_name = "dllm1"
    bridge._iter = 1
    return bridge


def _rows(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def test_the_row_records_the_served_model_distinctly_from_the_configured_one(tmp_path):
    """The load-bearing witness.

    RED before 66b: the row carries only ``model``, and no field anywhere
    distinguishes a provider that honoured the request from one that did not.
    """
    bridge = _bridge(tmp_path)
    bridge.client.chat.completions.create.return_value = _chat_response(
        '{"ok": true}', served=SERVED
    )
    bridge.generate_text("sys", "usr", label="dllm1.probe")

    rows = _rows(bridge._token_usage_path)
    assert len(rows) == 1, rows
    row = rows[0]

    assert row["model"] == CONFIGURED, "the configured value must still be recorded"
    assert row["served_model"] == SERVED, "the SERVED value must be recorded too"
    assert row["served_model"] != row["model"], (
        "the two must be able to disagree — a field that always equals the "
        "configured value cannot discriminate honoured from substituted"
    )


def test_a_provider_reporting_nothing_records_none_rather_than_the_request(tmp_path):
    """Absence must read as absence.

    Falling back to ``model_name`` here would reintroduce the exact defect:
    the row would look like a confirmation while observing nothing.
    """
    bridge = _bridge(tmp_path)
    bridge.client.chat.completions.create.return_value = _chat_response('{"ok": 1}', served=None)
    bridge.generate_text("sys", "usr", label="dllm1.probe")

    row = _rows(bridge._token_usage_path)[0]
    assert row["served_model"] is None
    assert row["model"] == CONFIGURED


def test_a_non_string_model_field_is_not_persisted_as_provenance(tmp_path):
    """SDK objects and mocks expose attributes that are not strings.

    Persisting a repr of some object would put a value in the field that
    looks like an observation and is not one.
    """
    bridge = _bridge(tmp_path)
    response = _chat_response('{"ok": 1}', served=None)
    response.model = object()
    bridge.client.chat.completions.create.return_value = response
    bridge.generate_text("sys", "usr", label="dllm1.probe")

    assert _rows(bridge._token_usage_path)[0]["served_model"] is None


def test_recording_does_not_refuse_a_mismatch(tmp_path):
    """Scope pin, and it protects a DELIBERATE non-behaviour.

    Whether a served/configured mismatch should refuse is a separate open
    decision. If someone later adds that validation here, this call starts
    raising and the test says why it was left out rather than leaving the
    next reader to guess it was an oversight.
    """
    bridge = _bridge(tmp_path)
    bridge.client.chat.completions.create.return_value = _chat_response('{"ok": 1}', served=SERVED)
    bridge.generate_text("sys", "usr", label="dllm1.probe")  # must not raise

    assert _rows(bridge._token_usage_path)[0]["served_model"] == SERVED
