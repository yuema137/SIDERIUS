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
