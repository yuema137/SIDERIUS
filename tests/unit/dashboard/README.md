# Dashboard tests

These tests check how the dashboard reads saved records and returns HTTP data.
They use synthetic files and FastAPI's in-process test client, so they need no
running server, network connection, or live backend.

With this checkout's development environment installed, run from the repository
root:

```bash
.venv/bin/python -m pytest tests/unit/dashboard/ -q
```

A successful run checks local JSON loading, settings/path defaults, and HTTP
responses for every persisted record status. For example, a saved
`failed_mode_collapse` record remains readable, with its non-finite score shown
as JSON `null` and its status preserved.

Source owners are the [local data reader](../../../src/dashboard/data_sources/local_json.py),
[settings](../../../src/dashboard/settings.py), and
[API response boundary](../../../src/dashboard/api/README.md).
See the [dashboard contract](../../../src/dashboard/dashboard-contract.md) for
status ownership and serialization details.

Ranking checks also cover records that lack metric identity (the metric name
and whether higher or lower scores are better). For example, a legacy score of
100 stays readable but receives `rank: null` with a reason. It cannot outrank
records whose metric identity is declared. Tests cover both ordering directions
and conflicting metric identities through the real HTTP app.
