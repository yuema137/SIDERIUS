# SIDERIUS Dashboard

A FastAPI-based live monitoring dashboard for SIDERIUS ML experiment runs.
Read-only observer — requires no changes to the experiment pipeline.

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

## Prerequisites

Dependencies are declared in `pyproject.toml` (`fastapi`, `uvicorn[standard]`,
`pyyaml`). Install with:

```bash
uv sync
```

## Configuration

Edit `dashboard_config.yaml` at the project root. The file is well-commented
and all fields have sensible defaults — the server starts even with an empty file.

Key settings to verify before first run:

```yaml
data_source:
  type: local
  local:
    root_data_dir: /home/klz/Data/SIDEREIS_DATA   # path to experiment outputs

server:
  host: 0.0.0.0    # 0.0.0.0 = accessible from other machines; 127.0.0.1 = local only
  port: 8000

dashboard:
  default_run_name: v1
  refresh_interval_seconds: 30
```

## Running the server

**From the project root:**

```bash
# Standard start
uv run python dashboard/main.py

# Custom config file
uv run python dashboard/main.py --config /path/to/config.yaml

# Override host/port without editing the config
uv run python dashboard/main.py --host 0.0.0.0 --port 9000

# Development mode (auto-reload on code changes)
uv run python dashboard/main.py --reload
```

**Or directly with uvicorn:**

```bash
uv run uvicorn dashboard.main:app --host 0.0.0.0 --port 8000
```

**Run in a detached screen session (recommended for long experiments):**

```bash
screen -S siderius-dashboard
uv run python dashboard/main.py
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
| GET | `/api/models/{model}/leaderboard` | Top N experiments ranked by score |

Query params for the runs endpoint: `?limit=50&offset=0&status=success`

## Running tests

```bash
# Dashboard unit tests only
uv run pytest tests/unit/dashboard/ -v

# Dashboard integration tests only (uses TestClient, no server needed)
uv run pytest tests/integration/dashboard/ -v

# All dashboard tests
uv run pytest tests/unit/dashboard/ tests/integration/dashboard/ -v

# Full test suite
uv run pytest tests/unit/ tests/integration/dashboard/
```

## Switching to PostgreSQL (future)

1. Update `dashboard_config.yaml`:
   ```yaml
   data_source:
     type: postgres
     postgres:
       connection_string: "postgresql+asyncpg://user:pass@host:5432/siderius"
   ```
2. Run `ingest.py` (not yet written) to load existing JSON records into the DB.
3. Restart the server — no code changes required.

The API layer depends only on the `DataSource` ABC, so the frontend and all
endpoints are unaffected by the backend switch.
