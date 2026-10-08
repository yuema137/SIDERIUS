# SIDERIUS Dashboard

A FastAPI-based live monitoring dashboard for SIDERIUS ML experiment runs.
Read-only observer — requires no changes to the experiment pipeline.

New here? Start from the user guide —
[browsing results with the dashboard](../../docs/guides/dashboard.md) — which
covers pointing it at your results, the layouts it understands, and the
known display caveats. The full defect ledger with post-PR-12e fix candidates
is the [dashboard UX audit](../../docs/agent-reference/dashboard_ux_audit.md).
This document is the technical reference: structure, configuration, endpoints
and tests. Start with the [directory guide](README.md) for navigation.

## Structure

```
dashboard/
├── main.py              # FastAPI app factory + uvicorn entrypoint
├── settings.py          # YAML config loader
├── data_sources/
│   ├── base.py          # DataSource ABC
│   ├── local_json.py    # Reads local JSON summary files (active)
│   └── postgres.py      # PostgreSQL backend (stub, future)
├── api/
│   ├── router.py        # REST endpoints
│   └── models.py        # Pydantic response models
└── static/              # Frontend (index.html, app.js, style.css)
```

The `static/` directory is a resource-only browser leaf; its files are served
by `main.py` and have no Python entrypoint of their own.

## Prerequisites

Dependencies are declared in `pyproject.toml` (`fastapi`, `uvicorn[standard]`,
`pyyaml`). Install with:

```bash
uv sync --group dev --frozen
```

## Configuration

Copy `dashboard_config.example.yaml` to a caller-selected configuration file
and set an explicit results root. Missing or empty settings use schema defaults;
that does not establish that a useful results directory was selected.

Key settings to verify before first run:

```yaml
data_source:
  type: local
  local:
    root_data_dir: /path/to/experiment/outputs   # the directory ABOVE your runs

server:
  host: 0.0.0.0    # 0.0.0.0 = accessible from other machines; 127.0.0.1 = local only
  port: 8000

dashboard:
  default_run_name: v1
  refresh_interval_seconds: 30
```

The current CLI uses a custom configuration for server host/port resolution,
but launches the module-level app created from default settings. For the data
source, follow the [documented configuration limitation](../../docs/guides/dashboard.md).
Do not treat `--config` as proof that the app reads that file's result root.

## Running the server

**From the project root:**

```bash
# Standard start
.venv/bin/python src/dashboard/main.py

# Custom config file
.venv/bin/python src/dashboard/main.py --config /path/to/config.yaml

# Override host/port without editing the config
.venv/bin/python src/dashboard/main.py --host 0.0.0.0 --port 9000

# Development mode (auto-reload on code changes)
.venv/bin/python src/dashboard/main.py --reload
```

**Or directly with uvicorn:**

```bash
.venv/bin/python -m uvicorn dashboard.main:app --host 0.0.0.0 --port 8000
```

**Run in a detached screen session (recommended for long experiments):**

```bash
screen -S siderius-dashboard
.venv/bin/python src/dashboard/main.py
# Ctrl+A D to detach
```

## Accessing the dashboard

There are two distinct pages served by the same server:

| Page | URL | Description |
|------|-----|-------------|
| **Live dashboard** | `http://<server-ip>:8000` | Visual charts — add series, plot scores and model params |
| **API explorer** | `http://<server-ip>:8000/api/docs` | Swagger UI — browse schemas, run API calls interactively |

Replace `<server-ip>` with `localhost` if accessing from the same machine, or with the server's IP address for remote access.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Server + data source health check |
| GET | `/api/config` | Frontend bootstrap (models, refresh interval) |
| GET | `/api/models` | List available models |
| GET | `/api/models/{model}` | Overview: baseline score, best score, counts |
| GET | `/api/models/{model}/runs` | List run names for a model |
| GET | `/api/models/{model}/runs/{run_name}` | Paginated experiment records |
| GET | `/api/models/{model}/runs/{run_name}/experiments/{exp_id}` | Full record detail |
| GET | `/api/models/{model}/leaderboard` | Top N experiments, ranked best-first on the metric the records declare |

Query params for the runs endpoint: `?limit=50&offset=0&status=success`

### Ranking and metric direction

Step 10 P2a: the dashboard does not assume that a larger score is better. Each
persisted record declares the metric it was scored under (`metric_result`:
`metric_id` + `direction`), and both the leaderboard and the model overview's
`best_agent_score` read that declaration.

Consequences an operator will actually see:

* a run scored on a **lower-is-better** metric ranks ascending, and its "best"
  is the smallest value;
* a record carrying **no** declared metric identity (a legacy artifact written
  before the field existed) is still listed with its raw score, but comes back
  with `rank: null` and a `metric_ranking` note, and can never be reported as
  best. One such record does not stop the others from ranking;
* if a view would have to rank **two different metrics** against each other,
  it refuses and names both — rather than silently picking one;
* when nothing in the corpus is rankable, `best_agent_score` is `null` and
  `metric_ranking_unavailable` says why. That is different from "there were no
  records".

## Running tests

```bash
# Dashboard unit tests only
.venv/bin/python -m pytest tests/unit/dashboard/ -v

# Dashboard integration tests only (uses TestClient, no server needed)
.venv/bin/python -m pytest tests/integration/dashboard/ -v

# All dashboard tests
.venv/bin/python -m pytest tests/unit/dashboard/ tests/integration/dashboard/ -v

# Affected dashboard route (the repository-wide suite is selected by CI)
.venv/bin/python -m pytest tests/unit/dashboard/ tests/integration/dashboard/ -v
```

## PostgreSQL is not implemented

`PostgresDataSource.__init__` raises `NotImplementedError`. Selecting
`data_source.type: postgres` cannot activate a working backend, and there is
no shipped ingestion command. Implementing that backend is future work.
