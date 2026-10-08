"""Opt-in finite launch-input pins; ordinary launches never call this owner."""

from __future__ import annotations

import argparse
import platform
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from core.file_identity import open_identity_file, path_matches_snapshot, regular_file_snapshot
from core.layout import checkout_root, require_checkout
from core.stream_identity import stream_file_identity

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class ReviewedLaunchRefusal(ValueError):
    """Safe named refusal; never include raw configuration or credentials."""


class BindingModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class InputFilePin(BindingModel):
    path: str
    sha256: Digest
    size: int = Field(ge=0, strict=True)


class InstallationPin(BindingModel):
    source_root: str
    source_head: str
    interpreter: str
    prefix: str
    python_version: str


class LaunchInputBinding(BindingModel):
    version: Literal["standard-launch-inputs/v1"] = "standard-launch-inputs/v1"
    installation: InstallationPin
    files: tuple[InputFilePin, ...]
    file_max_bytes: int = Field(gt=0, strict=True)


def installation_pin() -> InstallationPin:
    """Explicit reviewed-launch mode requires an identifiable clean source checkout."""
    root = require_checkout(checkout_root())
    dirty = subprocess.check_output(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=normal"], text=True
    )
    if dirty:
        raise ReviewedLaunchRefusal("installation_not_clean")
    head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    return InstallationPin(
        source_root=str(root),
        source_head=head,
        interpreter=sys.executable,
        prefix=sys.prefix,
        python_version=platform.python_version(),
    )


def file_pin(path: str, max_bytes: int) -> InputFilePin:
    # Keep the lexical final component so O_NOFOLLOW can reject a symlink.
    absolute = str(Path(path).absolute())
    with open_identity_file(absolute, require_no_follow=True) as handle:
        before = regular_file_snapshot(handle)
        if before.size > max_bytes:
            raise ReviewedLaunchRefusal("input_file_too_large")
        digest, size = stream_file_identity(handle, byte_limit=max_bytes)
        if regular_file_snapshot(handle) != before or not path_matches_snapshot(absolute, before):
            raise ReviewedLaunchRefusal("input_file_changed")
    return InputFilePin(path=absolute, sha256=digest, size=size)


def declared_input_paths(args: argparse.Namespace) -> tuple[str, ...]:
    """Explicit configuration locators only; inline prompts/rules are NOT filenames."""
    from workflows.advice import resolve_advice_artifact
    from workflows.literature_config import resolve_lit_review_config_path

    values = [
        args.task_composition,
        args.llm_config,
        args.health_checks_config,
        args.required_runtime_profile_path,
    ]
    advice = resolve_advice_artifact(args)
    if advice is not None:
        values.append(advice.path)
    if args.ml_lit_review_config is not None:
        values.append(resolve_lit_review_config_path(args.ml_lit_review_config))
    return tuple(sorted({str(Path(value).absolute()) for value in values if value is not None}))


def capture_binding(
    args: argparse.Namespace, max_bytes: int, *, source_paths: dict[str, str]
) -> LaunchInputBinding:
    # These are declaration-file roles produced by task composition, not arbitrary
    # returned paths. Plugin directory roots remain under their content owners.
    import re

    if "task_config" not in source_paths:
        raise ReviewedLaunchRefusal("task_declaration_source_missing")
    roles = {
        "dataset_profile",
        "metric_declaration",
        "task_config",
        "objective",
        "task_health",
        "interpretation_blocks",
        "proposal_blocks",
        "implementor_blocks",
        "data_analysis",
    }
    paths = set(declared_input_paths(args))
    paths.update(
        path
        for role, path in source_paths.items()
        if role in roles or re.fullmatch(r"secondary_metric_declaration\[\d+\]", role)
    )
    return LaunchInputBinding(
        installation=installation_pin(),
        file_max_bytes=max_bytes,
        files=tuple(file_pin(path, max_bytes) for path in sorted(paths)),
    )


def verify_binding(binding: LaunchInputBinding) -> None:
    if installation_pin() != binding.installation:
        raise ReviewedLaunchRefusal("installation_changed")
    from workflows.task_config import assert_cached_task_config_source

    for pin in binding.files:
        current = file_pin(pin.path, binding.file_max_bytes)
        if current != pin:
            raise ReviewedLaunchRefusal("input_file_changed")
        try:
            assert_cached_task_config_source(pin.path, current.sha256)
        except ValueError as error:
            raise ReviewedLaunchRefusal(str(error)) from error


def stable_hardware(runtime) -> dict[str, JsonValue]:
    """No timestamp, host-name heuristic, transient occupancy or invented identity."""
    hardware = runtime.hardware
    return {
        "installed_backend": runtime.installed_backend,
        "runtime_version": runtime.runtime_version,
        "device_available": hardware.device_available,
        "active_device_uuid": hardware.active_device_uuid,
        "total_memory_bytes": hardware.total_memory_bytes,
        "implemented_accounting_adapter": runtime.implemented_accounting_adapter,
    }
