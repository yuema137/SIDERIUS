# agent/schemas/storage.py
"""
Storage configuration schema shared across all SIDERIUS nodes.

Every node's input schema includes a StorageConfig field that specifies:
  - which backend handles persistence (local files now, database later)
  - where the node reads its input data when running standalone
  - where the node writes its output

This makes every node self-sufficient: it can be run individually without
an orchestrator by pointing its storage config at the right paths.

Backend support:
  - "local"    : JSON files on the local filesystem. Fully implemented.
  - "postgres" : PostgreSQL database. PLACEHOLDER — not yet implemented.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Local filesystem backend
# ---------------------------------------------------------------------------


class LocalStorageConfig(BaseModel):
    """
    Storage configuration for the local filesystem backend.

    `workspace` is the root directory for this node's files.
    `run_name` namespaces all output files within that workspace,
    allowing multiple runs to coexist without overwriting each other.

    Example layout produced by tune_ml_hyperparam_agent:
        {workspace}/
        ├── summary_{run_name}.json        (derived view — projection of records.jsonl)
        ├── run_output_{run_name}.json
        ├── run_config_{run_name}.json
        ├── configs/{run_name}/
        ├── records/{run_name}/
        │   └── records.jsonl              (canonical append-only record history)
        └── cached_models/
    """

    workspace: str = Field(
        description="Root directory for all files read and written by this node.",
    )
    run_name: str = Field(
        default="v1",
        description="Identifier that namespaces output files within the workspace. "
        "Use a descriptive name to distinguish runs "
        "(e.g. 'baseline', 'attn_unet_v1').",
    )


# ---------------------------------------------------------------------------
# Database backend — PLACEHOLDER
# ---------------------------------------------------------------------------


class PostgresStorageConfig(BaseModel):
    """
    Storage configuration for the PostgreSQL backend.

    PLACEHOLDER — not yet implemented. Fields are defined so the schema
    is stable and agents can be written to reference this config today.
    Implementation will replace local file reads/writes with DB queries
    without changing any agent input/output schema.
    """

    connection_string: str = Field(
        description="SQLAlchemy-compatible PostgreSQL connection string. "
        "e.g. 'postgresql+asyncpg://user:pass@localhost:5432/siderius'",
    )
    schema_name: str = Field(
        default="public",
        description="PostgreSQL schema name where SIDERIUS tables live.",
    )
    run_name: str = Field(
        default="v1",
        description="Identifier that namespaces rows within the database, "
        "equivalent to run_name in LocalStorageConfig.",
    )


# ---------------------------------------------------------------------------
# Unified storage config — one field in every node's input schema
# ---------------------------------------------------------------------------


class StorageConfig(BaseModel):
    """
    Unified storage configuration included in every node's input schema.

    Usage:
        class MyNodeInput(BaseModel):
            ...
            storage: StorageConfig

    The node reads `storage.backend` to decide which sub-config to use.
    Only the matching sub-config needs to be populated.

    Example (local):
        StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace="/data/runs/punet", run_name="v1")
        )

    Example (postgres, future):
        StorageConfig(
            backend="postgres",
            postgres=PostgresStorageConfig(
                connection_string="postgresql+asyncpg://...",
                run_name="v1"
            )
        )
    """

    backend: Literal["local", "postgres"] = Field(
        default="local",
        description="Storage backend to use. "
        "'local' reads/writes JSON files on the filesystem. "
        "'postgres' uses a shared PostgreSQL database (not yet implemented).",
    )
    local: LocalStorageConfig | None = Field(
        default=None,
        description="Local filesystem config. Required when backend='local'.",
    )
    postgres: PostgresStorageConfig | None = Field(
        default=None,
        description="PostgreSQL config. Required when backend='postgres'. "
        "PLACEHOLDER — implementation pending.",
    )
