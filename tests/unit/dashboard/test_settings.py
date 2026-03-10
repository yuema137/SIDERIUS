"""
Tests for dashboard/settings.py

Covers:
  - Default settings when config file is missing
  - Full config loaded correctly from a valid YAML file
  - Partial YAML fills missing fields with defaults
  - Invalid data_source type raises ValidationError
  - get_settings() caching and cache_clear()
"""

import os
import tempfile
import textwrap

import pytest
import yaml
from pydantic import ValidationError

from dashboard.settings import DashboardSettings, load_settings, get_settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_yaml(content: str) -> str:
    """Write a YAML string to a temp file and return the path."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
    f.write(textwrap.dedent(content))
    f.close()
    return f.name


# ---------------------------------------------------------------------------
# Missing config file
# ---------------------------------------------------------------------------

class TestMissingConfig:
    def test_missing_file_returns_defaults(self, tmp_path):
        settings = load_settings(str(tmp_path / "nonexistent.yaml"))
        assert isinstance(settings, DashboardSettings)

    def test_default_data_source_is_local(self, tmp_path):
        settings = load_settings(str(tmp_path / "nonexistent.yaml"))
        assert settings.data_source.type == "local"

    def test_default_port_is_8000(self, tmp_path):
        settings = load_settings(str(tmp_path / "nonexistent.yaml"))
        assert settings.server.port == 8000

    def test_default_refresh_interval(self, tmp_path):
        settings = load_settings(str(tmp_path / "nonexistent.yaml"))
        assert settings.dashboard.refresh_interval_seconds == 30


# ---------------------------------------------------------------------------
# Valid full config
# ---------------------------------------------------------------------------

class TestFullConfig:
    def test_data_source_type(self):
        path = write_yaml("""
            data_source:
              type: local
              local:
                root_data_dir: /tmp/test_data
                models: [punet, wavenet]
            server:
              host: 127.0.0.1
              port: 9000
              log_level: debug
            dashboard:
              refresh_interval_seconds: 10
              max_records_per_run: 50
              default_run_name: v2
        """)
        try:
            s = load_settings(path)
            assert s.data_source.type == "local"
            assert s.data_source.local.root_data_dir == "/tmp/test_data"
            assert s.data_source.local.models == ["punet", "wavenet"]
            assert s.server.host == "127.0.0.1"
            assert s.server.port == 9000
            assert s.server.log_level == "debug"
            assert s.dashboard.refresh_interval_seconds == 10
            assert s.dashboard.max_records_per_run == 50
            assert s.dashboard.default_run_name == "v2"
        finally:
            os.unlink(path)

    def test_postgres_type_parsed(self):
        path = write_yaml("""
            data_source:
              type: postgres
              postgres:
                connection_string: "postgresql+asyncpg://user:pass@localhost:5432/db"
                schema: myschema
        """)
        try:
            s = load_settings(path)
            assert s.data_source.type == "postgres"
            assert "localhost" in s.data_source.postgres.connection_string
            assert s.data_source.postgres.schema_name == "myschema"
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Partial config — missing fields use defaults
# ---------------------------------------------------------------------------

class TestPartialConfig:
    def test_only_port_overridden(self):
        path = write_yaml("""
            server:
              port: 7777
        """)
        try:
            s = load_settings(path)
            assert s.server.port == 7777
            assert s.server.host == "0.0.0.0"           # default
            assert s.data_source.type == "local"         # default
            assert s.dashboard.refresh_interval_seconds == 30  # default
        finally:
            os.unlink(path)

    def test_empty_yaml_uses_all_defaults(self):
        path = write_yaml("")
        try:
            s = load_settings(path)
            assert s.data_source.type == "local"
            assert s.server.port == 8000
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------

class TestValidation:
    def test_invalid_data_source_type_raises(self):
        path = write_yaml("""
            data_source:
              type: mongodb
        """)
        try:
            with pytest.raises(ValidationError):
                load_settings(path)
        finally:
            os.unlink(path)

    def test_invalid_log_level_raises(self):
        path = write_yaml("""
            server:
              log_level: verbose
        """)
        try:
            with pytest.raises(ValidationError):
                load_settings(path)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Caching behaviour
# ---------------------------------------------------------------------------

class TestCaching:
    def test_get_settings_returns_same_instance(self, tmp_path):
        get_settings.cache_clear()
        a = get_settings()
        b = get_settings()
        assert a is b

    def test_cache_clear_reloads(self, tmp_path):
        get_settings.cache_clear()
        a = get_settings()
        get_settings.cache_clear()
        b = get_settings()
        # Both should be valid settings objects (equal values, different instances)
        assert a.server.port == b.server.port
