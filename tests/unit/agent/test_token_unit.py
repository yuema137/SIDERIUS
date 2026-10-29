"""Token-ledger unit attribution under parallel dispatch (B3-4b)."""

from agent.schemas.telemetry.token_usage import TokenUsageChars, TokenUsageRow
from agent.token_unit import bind_token_unit, token_unit_fields


def _row(**fields) -> TokenUsageRow:
    return TokenUsageRow(
        ts="2026-10-28T00:00:00.000Z",
        run_id="r",
        run_name="r",
        label="proposer.causal_reasoning",
        chars=TokenUsageChars(system=1, user=1, total=2),
        **fields,
    )


def test_rows_of_one_unit_share_one_sequence_across_bridges_and_serial_rows_are_unchanged():
    """A per-bridge counter would restart at 1 for the unit's second bridge.

    Concurrent units append to one ledger in arbitrary order; (unit_id,
    unit_sequence) must still order each unit's rows.
    """
    serial = _row(**token_unit_fields()).model_dump_json()
    assert "unit_id" not in serial and "unit_sequence" not in serial
    with bind_token_unit("build0"):
        first_bridge = _row(**token_unit_fields())
        second_bridge = _row(**token_unit_fields())
    assert [(r.unit_id, r.unit_sequence) for r in (first_bridge, second_bridge)] == [
        ("build0", 1),
        ("build0", 2),
    ]
    assert token_unit_fields() == {}


def test_llm_bridge_rows_carry_the_bound_unit_and_its_own_sequence(monkeypatch, tmp_path):
    """Through the real bridge write path: two bridges of one unit share its counter.

    Fails if ``LLMBridge`` stops reading the bound unit, or if each bridge keeps
    its own counter (both rows would be sequence 1).
    """
    import json
    from types import SimpleNamespace
    from unittest.mock import Mock

    import httpx

    from agent.llm_bridge import LLMBridge

    monkeypatch.setattr("agent.llm_bridge.load_dotenv", lambda: None)
    monkeypatch.setenv("OPENAI_API_KEY", "offline-fixture")
    client = Mock(timeout=httpx.Timeout(600))
    client.chat.completions.create.return_value = SimpleNamespace(
        model="served-fixture",
        usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2, total_tokens=5),
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}', tool_calls=None))],
    )
    monkeypatch.setattr("agent.llm_bridge.OpenAI", Mock(return_value=client))

    def bridge():
        value = LLMBridge(provider="openai", model_id="main-fixture", max_retries=1)
        value.set_run_context(workspace=tmp_path, iter=1, run_name="fixture", run_id="fixture")
        return value

    bridge().generate("system", "user", label="serial.call")
    with bind_token_unit("build0"):
        bridge().generate("system", "user", label="unit.first")
        bridge().generate("system", "user", label="unit.second")
    rows = [json.loads(line) for line in (tmp_path / "token_usage.jsonl").read_text().splitlines()]
    calls = [row for row in rows if row["label"] != "_iter_flush"]
    assert [(r["label"], r.get("unit_id"), r.get("unit_sequence")) for r in calls] == [
        ("serial.call", None, None),
        ("unit.first", "build0", 1),
        ("unit.second", "build0", 2),
    ]
