"""Post-invariant restoration of current declared or historical generated source."""

from __future__ import annotations

import os
import warnings
from collections.abc import Callable

from core.local_code import CapturedCodePackage, LocalCodeError, bind_code_package
from ml_models.plugin_binding import (
    RunModelPluginBinding,
    bind_run_model_plugins,
    declared_package_model,
    require_declared_model_source,
)


def _register_source(
    path: str, iteration: int, register: Callable[[str], str | None]
) -> str | None:
    registered = register(path)
    if registered is None:
        warnings.warn(
            f"[resume] iter {iteration:03d}: plugin file at {path} failed _load_plugin validation. "
            "Continuing with JSON-only history; model class is unavailable for any retraining.",
            UserWarning,
            stacklevel=4,
        )
    else:
        print(f"[resume] iter {iteration:03d}: restored plugin '{registered}' from {path}")
    return registered


def restore_model_plugin(
    *,
    model_type: str,
    generated_path: str,
    iteration: int,
    binding: RunModelPluginBinding | None,
    package: CapturedCodePackage | None,
    register: Callable[[str], str | None],
) -> str | None:
    """The caller must finish all existing invariant checks before this mutation."""
    declared = declared_package_model(model_type, binding)
    if declared is not None:
        if package is None:
            raise LocalCodeError(
                f"declared package model {model_type!r} requires its current capture"
            )
        with bind_code_package(package), bind_run_model_plugins(binding):
            require_declared_model_source(declared, declared.absolute_path)
            return _register_source(declared.absolute_path, iteration, register)
    if os.path.isfile(generated_path):
        with bind_run_model_plugins(binding):
            return _register_source(generated_path, iteration, register)
    warnings.warn(
        f"[resume] iter {iteration:03d}: plugin file not found at {generated_path}. "
        "JSON record is kept (memory_history is still reconstructible); "
        "model class is unavailable for any retraining.",
        UserWarning,
        stacklevel=3,
    )
    return None
