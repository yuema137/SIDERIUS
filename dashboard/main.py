# dashboard/main.py
"""
FastAPI application factory and uvicorn entrypoint for the SIDERIUS dashboard.

Usage:
    python dashboard/main.py                          # uses dashboard_config.yaml
    python dashboard/main.py --config /path/to/cfg   # custom config path
    uvicorn dashboard.main:app --reload               # development mode
"""

import argparse
import os
import sys

# Ensure the project root is on sys.path regardless of how this file is invoked
# (e.g. `python dashboard/main.py` from the project root)
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from dashboard.api.models import FrontendConfig
from dashboard.api.router import router, set_data_source, set_frontend_config
from dashboard.data_sources.local_json import LocalJsonDataSource
from dashboard.data_sources.postgres import PostgresDataSource
from dashboard.settings import DashboardSettings, get_settings

# ---------------------------------------------------------------------------
# Static files directory
# ---------------------------------------------------------------------------
_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(settings: DashboardSettings) -> FastAPI:
    """
    Build and configure the FastAPI application from a DashboardSettings object.
    Separated from the module-level `app` so tests can pass custom settings.
    """
    # Capture settings in closure for the lifespan handler
    _settings = settings

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        print(f"[dashboard] Data source : {ds_type}")
        if ds_type == "local":
            print(f"[dashboard] Root dir    : {_settings.data_source.local.root_data_dir}")
        print(f"[dashboard] Models      : {frontend_cfg.models}")
        print(f"[dashboard] Default run : {_settings.dashboard.default_run_name}")
        print(f"[dashboard] Refresh     : {_settings.dashboard.refresh_interval_seconds}s")
        print(f"[dashboard] API docs    : http://{_settings.server.host}:{_settings.server.port}/api/docs")
        print(f"[dashboard] Dashboard   : http://{_settings.server.host}:{_settings.server.port}/")
        yield

    app = FastAPI(
        title="SIDERIUS Dashboard",
        description="Live monitoring dashboard for SIDERIUS ML experiment runs.",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    # --- Data source ---
    ds_type = settings.data_source.type
    if ds_type == "local":
        ds_cfg = settings.data_source.local
        data_source = LocalJsonDataSource(
            root_data_dir=ds_cfg.root_data_dir,
            models=ds_cfg.models or None,
        )
    elif ds_type == "postgres":
        pg_cfg = settings.data_source.postgres
        data_source = PostgresDataSource(
            connection_string=pg_cfg.connection_string,
            schema=pg_cfg.schema_name,
        )
    else:
        raise ValueError(f"Unknown data_source.type '{ds_type}' in config.")

    # --- Frontend bootstrap config ---
    frontend_cfg = FrontendConfig(
        refresh_interval_seconds=settings.dashboard.refresh_interval_seconds,
        data_source_type=ds_type,
        models=data_source.list_models(),
        default_run_name=settings.dashboard.default_run_name,
        theme=settings.dashboard.theme,
    )

    # Inject into router (module-level, safe for single-process deployment)
    set_data_source(data_source)
    set_frontend_config(frontend_cfg)

    # --- Routes ---
    app.include_router(router, prefix="/api")

    # --- Static files (frontend UI) ---
    if os.path.isdir(_STATIC_DIR):
        app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
    else:
        print(f"[dashboard] Warning: static directory not found at {_STATIC_DIR}")

    # --- Root redirect ---
    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse(url="/static/index.html")

    return app


# ---------------------------------------------------------------------------
# Module-level app instance (used by `uvicorn dashboard.main:app`)
# ---------------------------------------------------------------------------

app = create_app(get_settings())


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="SIDERIUS Dashboard Server")
    parser.add_argument(
        "--config", type=str, default=None,
        help="Path to dashboard_config.yaml (default: project root).",
    )
    parser.add_argument(
        "--host", type=str, default=None,
        help="Override server host from config.",
    )
    parser.add_argument(
        "--port", type=int, default=None,
        help="Override server port from config.",
    )
    parser.add_argument(
        "--reload", action="store_true",
        help="Enable auto-reload for development.",
    )
    args = parser.parse_args()

    # Load settings (possibly from a custom path)
    if args.config:
        get_settings.cache_clear()
        settings = get_settings(args.config)
    else:
        settings = get_settings()

    host = args.host or settings.server.host
    port = args.port or settings.server.port

    print(f"[dashboard] Starting server on {host}:{port}")

    uvicorn.run(
        "dashboard.main:app",
        host=host,
        port=port,
        log_level=settings.server.log_level,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
