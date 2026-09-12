# tests/unit/execute_tools/health_checks

Health-check tests pin declaration/config loading, applicability, verdict
schemas, aggregation, and task/plugin binding. Synthetic views and fixtures
exercise failure classification without a campaign.

## Focused route

`.venv/bin/python -m pytest tests/unit/execute_tools/health_checks/test_after_round_schema.py -q`

Owner: `src/execute_tools/health_checks/`; see the [execute_tools map](../README.md).
The nested `goldens/` directory retains pre-08a verdict parity material for
the health regression suite; it is static evidence, not a second policy owner.
