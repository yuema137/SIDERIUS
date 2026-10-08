"""Bind a disposable inference measurement to its complete request and sources.

No model is imported or instantiated here. The normal local-code transport
continues to own declared-package integrity; this records its identity rather
than providing another loader. Runtime hashes identify this observation, not a
portable cache or a guarantee about arbitrary installed plugin dependencies.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from core.runtime_control.gpu_measurement_spec import GpuMeasurementSpec


class MeasurementSources(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    assembly_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    plugin_sources_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    code_package_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class InferenceMeasurementBinding(MeasurementSources):
    version: Literal["inference-measurement-v1"] = "inference-measurement-v1"
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def measurement_sources(*, environ: Mapping[str, str] | None = None) -> MeasurementSources:
    """Observe the same execution sources before structural and GPU workers."""
    from core.local_code.binding import active_package
    from core.preflight_estimation import estimation_assembly_digest
    from ml_models.loss_plugin_loader import _resolve_loss_dirs
    from ml_models.plugin_loader import _resolve_plugin_dirs

    environment = os.environ if environ is None else environ
    roots = {
        "model": _resolve_plugin_dirs(environ=environment, declared_roots=()),
        "loss": _resolve_loss_dirs(environ=environment),
    }
    inventory = []
    for family, directories in roots.items():
        for directory in directories:
            root = Path(directory)
            inventory.append(
                {
                    "family": family,
                    "root": str(root.resolve()),
                    "exists": root.is_dir(),
                    "files": {
                        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in sorted(root.rglob("*.py"))
                        if path.is_file()
                    }
                    if root.is_dir()
                    else {},
                }
            )
    package = active_package()
    return MeasurementSources(
        assembly_sha256=estimation_assembly_digest(),
        plugin_sources_sha256=_digest(inventory),
        runtime_sha256=_digest(
            {
                "python": sys.version,
                "executable": sys.executable,
                "packages": {
                    name: importlib.metadata.version(name)
                    for name in ("torch", "numpy", "pydantic")
                },
                "cuda_visible_devices": environment.get("CUDA_VISIBLE_DEVICES"),
            }
        ),
        code_package_sha256=package.identity.digest if package is not None else None,
    )


def inference_measurement_binding(
    spec: GpuMeasurementSpec, *, environ: Mapping[str, str] | None = None
) -> InferenceMeasurementBinding:
    sources = measurement_sources(environ=environ)
    return InferenceMeasurementBinding(
        **sources.model_dump(),
        request_sha256=measurement_request_digest(spec, binding_field="inference_binding"),
    )


def measurement_request_digest(spec: GpuMeasurementSpec, *, binding_field: str) -> str:
    """Hash the complete request using the existing canonical representation."""
    return _digest(spec.model_dump(mode="json", exclude={binding_field}))


def verify_measurement_sources(expected: MeasurementSources) -> None:
    if measurement_sources() != expected:
        raise ValueError("candidate execution sources changed across resource inspection")
