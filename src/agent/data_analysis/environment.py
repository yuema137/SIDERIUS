"""Verification of an optional declared analysis execution environment."""

from __future__ import annotations

import hashlib
import importlib.metadata
import sys
from pathlib import Path

from agent.schemas.data_analysis.common import CertifiedArtifactRef
from agent.schemas.data_analysis.environment import AnalysisEnvironmentLock


class AnalysisEnvironmentError(RuntimeError):
    """The active process does not satisfy a supplied environment lock."""


def verify_environment_lock(pack_root: Path, ref: CertifiedArtifactRef | None) -> bool:
    """Verify declared exact versions; never install or create an environment."""

    if ref is None:
        return False
    root = pack_root.resolve()
    path = (root / ref.logical_ref).resolve()
    if path == root or root not in path.parents:
        raise AnalysisEnvironmentError("environment lock path escapes the pack root")
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise AnalysisEnvironmentError(f"cannot read environment lock: {exc}") from exc
    if ref.byte_size is not None and len(payload) != ref.byte_size:
        raise AnalysisEnvironmentError("environment lock byte size mismatch")
    if hashlib.sha256(payload).hexdigest() != ref.sha256:
        raise AnalysisEnvironmentError("environment lock digest mismatch")
    try:
        lock = AnalysisEnvironmentLock.model_validate_json(payload)
    except ValueError as exc:
        raise AnalysisEnvironmentError(f"invalid environment lock: {exc}") from exc
    observed_python = ".".join(str(value) for value in sys.version_info[:3])
    if observed_python != lock.python_version:
        raise AnalysisEnvironmentError(
            f"environment requires Python {lock.python_version}, active runtime is {observed_python}"
        )
    for package in lock.packages:
        try:
            observed_version = importlib.metadata.version(package.name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise AnalysisEnvironmentError(
                f"required distribution {package.name!r} is not installed"
            ) from exc
        if observed_version != package.version:
            raise AnalysisEnvironmentError(
                f"distribution {package.name!r} requires {package.version}, "
                f"active runtime has {observed_version}"
            )
    return True
