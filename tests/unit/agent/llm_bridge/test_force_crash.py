"""Stage 4 / Commit 4.6 — env-var ``SIDERIUS_STUB_FORCE_CRASH`` hook.

The brake-stress hook lets us exercise the consecutive-iter failure
brake (added in C1 + C2) end-to-end without burning real tokens. When
the env var is set to the exact string ``"1"`` at the time
``StubLLMBridge.__init__`` runs, the three entry-point overrides
(``_chat_json`` / ``generate_text`` / ``tool_call``) must raise
``RuntimeError`` on every call — simulating an LLM-pipeline crash that
propagates up through the workflow into ``run_one_iteration.main()``'s
bare-except handler, which writes ``manifest.status="failed"`` and
exits 1. Three such iters trip the brake.

What this file pins:

  1. Default is off — bare ``StubLLMBridge()`` with no env set behaves
     normally (no surprise crashes for unit tests that exercise the
     stub for unrelated reasons).
  2. Each of the three entry points raises ``RuntimeError`` when the
     hook is on — covers the DoD spec ("Dedicated unit test verifies
     that setting the env var forces the stub bridge to raise a
     ``RuntimeError`` on generation calls").
  3. ``_record_usage`` is intentionally NOT hooked — telemetry must
     finalize during a forced crash. If we ever accidentally added the
     hook to ``_record_usage``, ``write_manifest(crashed=True)``'s
     finalization path could re-raise and corrupt the audit trail.
  4. Exact-string matching: only ``"1"`` triggers; ``""`` / ``"0"`` /
     ``"true"`` / ``"yes"`` all stay off. Prevents accidental
     activation by half-set shell defaults.
  5. The ``RuntimeError`` message includes the label — forensic
     visibility when a chain halts mid-run.
"""

from __future__ import annotations

import pytest

from agent.llm_bridge import StubLLMBridge


# ---------------------------------------------------------------------
# Default-off behaviour
# ---------------------------------------------------------------------
def test_force_crash_default_false_when_env_unset(monkeypatch) -> None:
    """Bare ``StubLLMBridge()`` with no env var → ``_force_crash`` is False,
    and the entry points behave normally (do not raise)."""
    monkeypatch.delenv("SIDERIUS_STUB_FORCE_CRASH", raising=False)
    bridge = StubLLMBridge()
    assert bridge._force_crash is False
    # Sanity: a valid label round-trips through _synthesise_json without
    # raising. This guards against accidental always-on regression.
    result = bridge._chat_json(
        None,
        "stub_model",
        "sys",
        "user",
        label="tuner.planner",
    )
    assert isinstance(result, dict)


# ---------------------------------------------------------------------
# DoD spec: env="1" forces RuntimeError on every entry point
# ---------------------------------------------------------------------
def test_force_crash_raises_on_chat_json(monkeypatch) -> None:
    """``_chat_json`` is the JSON-mode entry that catches ``generate`` /
    ``plan`` / ``reflect`` — the load-bearing path for 10 of 14 cognitive
    labels. Must crash when the hook is on."""
    monkeypatch.setenv("SIDERIUS_STUB_FORCE_CRASH", "1")
    bridge = StubLLMBridge()
    assert bridge._force_crash is True
    with pytest.raises(RuntimeError, match=r"force_crash.*tuner\.planner"):
        bridge._chat_json(
            None,
            "stub_model",
            "sys",
            "user",
            label="tuner.planner",
        )


def test_force_crash_raises_on_generate_text(monkeypatch) -> None:
    """``generate_text`` is the text-mode entry that catches
    ``proposer.legacy_reasoning`` / ``implementor.reasoning``. Must
    crash when the hook is on."""
    monkeypatch.setenv("SIDERIUS_STUB_FORCE_CRASH", "1")
    bridge = StubLLMBridge()
    with pytest.raises(RuntimeError, match=r"force_crash.*implementor\.reasoning"):
        bridge.generate_text("sys", "user", label="implementor.reasoning")


def test_force_crash_raises_on_tool_call(monkeypatch) -> None:
    """``tool_call`` already raises ``NotImplementedError`` today (no
    production label uses it), but when the brake-stress hook is on the
    ``RuntimeError`` must fire FIRST — guarantees the ordering matches
    the other two entry points and there is no accidental escape route
    for a future label that does use tool_call."""
    monkeypatch.setenv("SIDERIUS_STUB_FORCE_CRASH", "1")
    bridge = StubLLMBridge()
    with pytest.raises(RuntimeError, match=r"force_crash"):
        bridge.tool_call("sys", "user", tools=[], label="future.label")


# ---------------------------------------------------------------------
# Telemetry must NOT crash
# ---------------------------------------------------------------------
def test_force_crash_does_not_break_record_usage(monkeypatch) -> None:
    """``_record_usage`` is intentionally NOT hooked: when the bare-except
    handler in ``run_one_iteration.main()`` catches the forced crash and
    calls ``write_manifest(crashed=True)``, telemetry finalization must
    succeed — otherwise the audit trail would be corrupt at the very
    moment the brake needs it to be readable."""
    monkeypatch.setenv("SIDERIUS_STUB_FORCE_CRASH", "1")
    bridge = StubLLMBridge()
    # _record_usage is a no-op in the stub; with force_crash=True it must
    # still no-op (returning None), NOT raise.
    assert bridge._record_usage(response=object(), label="anything") is None


# ---------------------------------------------------------------------
# Exact-string matching: only "1" triggers
# ---------------------------------------------------------------------
@pytest.mark.parametrize("value", ["", "0", "true", "True", "yes", "on", "2"])
def test_force_crash_only_triggers_on_exact_string_1(monkeypatch, value) -> None:
    """Half-set shell defaults (``true``, ``yes``, ``on``) must not
    silently activate brake-stress mode. The exact-match contract makes
    accidental activation by a misconfigured launcher impossible."""
    monkeypatch.setenv("SIDERIUS_STUB_FORCE_CRASH", value)
    bridge = StubLLMBridge()
    assert bridge._force_crash is False
    # And a generation call returns normally.
    result = bridge._chat_json(
        None,
        "stub_model",
        "sys",
        "user",
        label="tuner.planner",
    )
    assert isinstance(result, dict)


# ---------------------------------------------------------------------
# Forensic visibility
# ---------------------------------------------------------------------
def test_force_crash_error_message_includes_label(monkeypatch) -> None:
    """When a chain halts mid-run, the operator's first move is to read
    ``chain_log.txt`` to learn *which* call site crashed. The label name
    must be embedded in the ``RuntimeError`` message so the trail is
    readable without rerunning under a debugger."""
    monkeypatch.setenv("SIDERIUS_STUB_FORCE_CRASH", "1")
    bridge = StubLLMBridge()
    with pytest.raises(RuntimeError) as excinfo:
        bridge._chat_json(
            None,
            "stub_model",
            "sys",
            "user",
            label="interpretation.synthesis",
        )
    message = str(excinfo.value)
    assert "interpretation.synthesis" in message
    assert "force_crash" in message
    assert "Commit 4.6" in message
