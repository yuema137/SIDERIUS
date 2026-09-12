# src/dashboard/data_sources

Read-only backend boundary: [`base.py`](base.py) defines `DataSource`,
[`local_json.py`](local_json.py) reads the active workspace JSON layout, and
[`postgres.py`](postgres.py) is a stub adapter. Configuration selects the
backend; this layer does not ingest or score runs. Focused checks are in
`tests/unit/dashboard/`.

See [the parent guide](../README.md) for child ownership and the focused validation route.
