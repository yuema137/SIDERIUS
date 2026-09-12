# tests/integration/runner

Runner integration checks token-log iteration/roll-up bookkeeping at the
workflow boundary using synthetic records; it does not launch training or an
LLM.

## Source and route

`.venv/bin/python -m pytest tests/integration/runner/test_token_log_iter_rollup.py -q`

Owner: `src/workflows` run bookkeeping and token-log readers. See the
[integration map](../README.md).
