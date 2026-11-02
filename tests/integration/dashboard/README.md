# tests/integration/dashboard

Dashboard integration exercises `dashboard.api` through FastAPI TestClient and
synthetic LocalJsonDataSource records. It catches route/status/serialization
regressions without a server, network, or live backend.

## Source and route

`.venv/bin/python -m pytest tests/integration/dashboard/test_api.py -q`

Owner: `src/dashboard/api` and `src/dashboard/data_sources/local_json.py`.
See the [integration map](../README.md).

Run from the repository root with this checkout's development environment
installed. A successful run checks ranked records with an explicit metric name
and direction, plus legacy records without that identity. Legacy records remain
readable with `rank: null` and a reason; the overview does not invent a best
score. The matching HTTP witnesses in `tests/unit/dashboard/test_ranking_http.py`
also run in CI, which does not select this integration directory.
