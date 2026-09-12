# src/tools/runtime_replay

`.venv/bin/python -m tools.runtime_replay` dispatches executable and metadata replay.
[`executable_replay.py`](executable_replay.py), [`metadata_replay.py`](metadata_replay.py), and [`legacy_migration.py`](legacy_migration.py) consume
explicit evidence; replay modes may write outputs, so inspect the command
contract before use. Focused replay tests are under
[`test_c11_runtime_replay.py`](../../../tests/unit/scripts/test_c11_runtime_replay.py).

See [the parent guide](../README.md) for child ownership and the focused validation route.
