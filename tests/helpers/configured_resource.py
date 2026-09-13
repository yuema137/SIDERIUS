"""Fail-closed admission for optional, externally configured test resources."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


def require_configured_directory(env_var: str, *, requested_by: str) -> Path:
    """Return a configured directory, skipping only when it is unconfigured.

    A caller that explicitly sets ``env_var`` has selected the corresponding
    qualification lane. Invalid selected resources are therefore failures, not
    skips: silently skipping them would turn broken coverage into a green run.
    """
    raw = os.environ.get(env_var)
    if raw is None:
        pytest.skip(
            f"{requested_by} requires the optional {env_var} resource; "
            "the environment variable is not configured"
        )
    if not raw.strip():
        pytest.fail(f"{requested_by}: {env_var} is configured but blank")

    path = Path(raw).expanduser()
    if not path.is_absolute():
        pytest.fail(f"{requested_by}: configured {env_var} must be an absolute path: {path}")
    if not path.exists():
        pytest.fail(f"{requested_by}: configured {env_var} does not exist: {path}")
    if not path.is_dir():
        pytest.fail(f"{requested_by}: configured {env_var} is not a directory: {path}")
    return path


def require_resource_file(root: Path, relative_path: str, *, requested_by: str) -> Path:
    """Return a required file below an admitted resource directory."""
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        pytest.fail(
            f"{requested_by}: required resource file must be relative to its configured root: "
            f"{relative_path}"
        )
    resolved_root = root.resolve()
    path = root / relative
    resolved_path = path.resolve()
    if not resolved_path.is_relative_to(resolved_root):
        pytest.fail(
            f"{requested_by}: required resource file resolves outside its configured root: {path}"
        )
    if not path.exists():
        pytest.fail(f"{requested_by}: required resource file does not exist: {path}")
    if not path.is_file():
        pytest.fail(f"{requested_by}: required resource path is not a file: {path}")
    return path
