# tests/unit/dashboard

Dashboard unit tests pin local JSON loading and settings/path defaults; they
use temporary synthetic records and do not start a server.

## Source and route

`.venv/bin/python -m pytest tests/unit/dashboard/test_local_json.py -q`

Owner: `src/dashboard/data_sources/local_json.py` and `src/dashboard/settings.py`.
