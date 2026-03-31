# dashboard/settings.py
"""
Loads dashboard_config.yaml from the project root and exposes a validated
DashboardSettings object. All other dashboard modules import from here.

Usage:
    from dashboard.settings import get_settings
    settings = get_settings()
"""

import os
from functools import lru_cache
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field, ConfigDict

# ---------------------------------------------------------------------------
# Project root = parent of this file's directory
# ---------------------------------------------------------------------------
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "dashboard_config.yaml")


# ---------------------------------------------------------------------------
# Nested settings models
# ---------------------------------------------------------------------------

class LocalDataSourceSettings(BaseModel):
    root_data_dir: str = ""  # Set via dashboard_config.yaml or tidmad_data_config.yaml
    # If empty, models are auto-discovered by scanning root_data_dir subdirectories.
    models: list[str] = Field(default_factory=list)


class PostgresDataSourceSettings(BaseModel):
    connection_string: str = "postgresql+asyncpg://user:password@localhost:5432/siderius"
    schema_name: str = Field(default="public", alias="schema")

    model_config = ConfigDict(populate_by_name=True)


class DataSourceSettings(BaseModel):
    type: Literal["local", "postgres"] = "local"
    local: LocalDataSourceSettings = Field(default_factory=LocalDataSourceSettings)
    postgres: PostgresDataSourceSettings = Field(default_factory=PostgresDataSourceSettings)


class ServerSettings(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: Literal["debug", "info", "warning", "error"] = "info"


class DashboardDisplaySettings(BaseModel):
    refresh_interval_seconds: int = 30
    max_records_per_run: int = 200
    default_run_name: str = "v1"
    theme: Literal["dark", "light"] = "dark"


class DashboardSettings(BaseModel):
    """
    Top-level settings object. Populated from dashboard_config.yaml.
    All fields have sensible defaults so the server starts even with a
    minimal or missing config file.
    """
    data_source: DataSourceSettings = Field(default_factory=DataSourceSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)
    dashboard: DashboardDisplaySettings = Field(default_factory=DashboardDisplaySettings)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def load_settings(config_path: Optional[str] = None) -> DashboardSettings:
    """
    Load and validate settings from a YAML file.

    Args:
        config_path: Path to the YAML config file. Defaults to
                     dashboard_config.yaml at the project root.
                     If the file does not exist, returns default settings
                     and prints a warning.

    Returns:
        A validated DashboardSettings instance.
    """
    path = config_path or DEFAULT_CONFIG_PATH

    if not os.path.exists(path):
        print(f"[dashboard] Config file not found at {path} — using defaults.")
        return DashboardSettings()

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    return DashboardSettings.model_validate(raw)


@lru_cache(maxsize=1)
def get_settings(config_path: Optional[str] = None) -> DashboardSettings:
    """
    Cached settings loader. Returns the same instance on repeated calls.
    Call get_settings.cache_clear() in tests to reload from a different file.
    """
    return load_settings(config_path)
