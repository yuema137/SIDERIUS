"""
Tests for agent/schemas/storage.py

Covers:
  - LocalStorageConfig validation
  - PostgresStorageConfig validation (placeholder — schema only)
  - StorageConfig: valid local, valid postgres, default backend, missing sub-config
"""

import pytest
from pydantic import ValidationError

from agent.schemas.storage import LocalStorageConfig, PostgresStorageConfig, StorageConfig


class TestLocalStorageConfig:
    def test_valid(self):
        cfg = LocalStorageConfig(workspace="/data/runs", run_name="v1")
        assert cfg.workspace == "/data/runs"
        assert cfg.run_name == "v1"

    def test_default_run_name(self):
        cfg = LocalStorageConfig(workspace="/data/runs")
        assert cfg.run_name == "v1"

    def test_missing_workspace_raises(self):
        with pytest.raises(ValidationError) as exc:
            LocalStorageConfig()
        assert "workspace" in str(exc.value)


class TestPostgresStorageConfig:
    def test_valid(self):
        cfg = PostgresStorageConfig(
            connection_string="postgresql+asyncpg://user:pass@localhost/siderius"
        )
        assert cfg.schema_name == "public"
        assert cfg.run_name == "v1"

    def test_custom_schema_and_run_name(self):
        cfg = PostgresStorageConfig(
            connection_string="postgresql+asyncpg://user:pass@localhost/siderius",
            schema_name="research",
            run_name="exp_42",
        )
        assert cfg.schema_name == "research"
        assert cfg.run_name == "exp_42"

    def test_missing_connection_string_raises(self):
        with pytest.raises(ValidationError) as exc:
            PostgresStorageConfig()
        assert "connection_string" in str(exc.value)


class TestStorageConfig:
    def test_valid_local(self):
        cfg = StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace="/data/runs", run_name="v1"),
        )
        assert cfg.backend == "local"
        assert cfg.local.workspace == "/data/runs"
        assert cfg.postgres is None

    def test_valid_postgres_placeholder(self):
        cfg = StorageConfig(
            backend="postgres",
            postgres=PostgresStorageConfig(
                connection_string="postgresql+asyncpg://user:pass@localhost/siderius"
            ),
        )
        assert cfg.backend == "postgres"
        assert cfg.local is None
        assert cfg.postgres.connection_string == "postgresql+asyncpg://user:pass@localhost/siderius"

    def test_default_backend_is_local(self):
        cfg = StorageConfig(
            local=LocalStorageConfig(workspace="/data/runs", run_name="v1"),
        )
        assert cfg.backend == "local"

    def test_invalid_backend_raises(self):
        with pytest.raises(ValidationError) as exc:
            StorageConfig(backend="redis")
        assert "backend" in str(exc.value)

    def test_local_sub_config_is_optional(self):
        # StorageConfig itself does not enforce that local is set when backend=local
        # — that enforcement is the agent's responsibility at runtime
        cfg = StorageConfig(backend="local")
        assert cfg.local is None

    def test_nested_dict_construction(self):
        # Verify that dict-based construction works (used in model_validate calls)
        cfg = StorageConfig.model_validate(
            {
                "backend": "local",
                "local": {"workspace": "/data/runs", "run_name": "v2"},
            }
        )
        assert cfg.local.workspace == "/data/runs"
        assert cfg.local.run_name == "v2"
