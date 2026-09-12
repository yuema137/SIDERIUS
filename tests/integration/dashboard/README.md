# tests/integration/dashboard

Dashboard integration exercises `dashboard.api` through FastAPI TestClient and
synthetic LocalJsonDataSource records. It catches route/status/serialization
regressions without a server, network, or live backend.

## Source and route

`.venv/bin/python -m pytest tests/integration/dashboard/test_api.py -q`

Owner: `src/dashboard/api` and `src/dashboard/data_sources/local_json.py`.
See the [integration map](../README.md).
