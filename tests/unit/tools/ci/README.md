# tests/unit/tools/ci

These tests cover CI preflight, affected shard execution, and oversized-node
splitting. They exercise `src/tools/ci`'s selection/execution boundary without
authorizing a CI service run.

## Source and route

`.venv/bin/python -m pytest tests/unit/tools/ci/test_execution.py -q`

Owner: `src/tools/ci/`; tests construct local shard commands and never contact
a CI service. See the [tools map](../README.md).
