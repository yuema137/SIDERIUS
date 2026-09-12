# tests/unit/scripts

Script tests pin shell/Python argument parity, chain dry-run wiring, run-state
inspection, and campaign admission bookkeeping using inert subprocesses.

## Source and route


## Focused route

`.venv/bin/python -m pytest tests/unit/scripts/test_agent_environment_diagnostic.py -q`

Owner: `scripts/` and `src/workflows` launch adapters; no campaign is launched.
