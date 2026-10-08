"""Compare opt-in setup expectations at the standard runner's existing owners."""

from __future__ import annotations

import argparse
from pathlib import Path

from pydantic import JsonValue

from core.durable_io import publish_bytes_write_once
from workflows.launch_projection import json_launch_values
from workflows.reviewed_launch_binding import (
    BindingModel,
    Digest,
    LaunchInputBinding,
    ReviewedLaunchRefusal,
    stable_hardware,
    verify_binding,
)


class ReviewedLaunchContext(BindingModel):
    """Validated expected facts, without tools-package or saved sandbox objects."""

    binding: LaunchInputBinding
    working_directory: str
    manifest: str
    workspace: str
    manifest_sha256: Digest
    composition_fingerprint: Digest
    code_package_identity: dict[str, JsonValue] | None
    planner_identity: dict[str, JsonValue]
    health_config_sha256: str | None
    llm_config: dict[str, JsonValue]
    launch_identity: dict[str, JsonValue]
    launch_settings: dict[str, JsonValue]
    hardware: dict[str, JsonValue]
    watchdog: dict[str, JsonValue]
    aggregate_ceiling: dict[str, JsonValue] | None
    receipt_path: str
    receipt_fields: dict[str, JsonValue]

    def check_entry(self, args: argparse.Namespace) -> None:
        if Path.cwd() != Path(self.working_directory):
            raise ReviewedLaunchRefusal("working_directory_changed")
        if Path(args.task_composition).resolve() != Path(self.manifest).resolve():
            raise ReviewedLaunchRefusal("manifest_locator_changed")
        if Path(args.workspace).resolve() != Path(self.workspace).resolve():
            raise ReviewedLaunchRefusal("workspace_changed")
        verify_binding(self.binding)

    def check_composition(self, composition) -> None:
        if composition is None or composition.semantic_fingerprint != self.composition_fingerprint:
            raise ReviewedLaunchRefusal("task_identity_changed")
        package = composition.code_package
        actual = package.identity.model_dump(mode="json") if package is not None else None
        if actual != self.code_package_identity:
            raise ReviewedLaunchRefusal("task_code_package_changed")

    def resolve_watchdog(self, args: argparse.Namespace):
        import os

        from core.hardware_context import inspect_gpu_runtime
        from core.runtime_control.pair_admission import (
            HOST_VRAM_QUOTA_MIB_ENV,
            PAIR_CEILING_GIB_ENV,
            gib_from_bytes,
            resolve_gpu_ceiling,
        )
        from workflows.runtime_settings import resolve_watchdog_policy

        runtime = inspect_gpu_runtime()
        if stable_hardware(runtime) != self.hardware:
            raise ReviewedLaunchRefusal("hardware_identity_changed")
        resolved = resolve_watchdog_policy(args, device_name=runtime.hardware.device_name)
        if resolved.model_dump(mode="json") != self.watchdog:
            raise ReviewedLaunchRefusal("watchdog_settings_changed")
        aggregate = None
        if runtime.hardware.device_available:
            aggregate = resolve_gpu_ceiling(
                ceiling_gib=args.gpu_pair_ceiling_gib,
                measured_capacity_gib=gib_from_bytes(runtime.hardware.total_memory_bytes),
                environ={
                    name: os.environ[name]
                    for name in (HOST_VRAM_QUOTA_MIB_ENV, PAIR_CEILING_GIB_ENV)
                    if name in os.environ
                },
            ).model_dump(mode="json")
        if aggregate != self.aggregate_ceiling:
            raise ReviewedLaunchRefusal("aggregate_ceiling_changed")
        return resolved

    def check_invariants(self, invariants, llm_config, identity) -> None:
        planner = invariants.planner_strategy_identity
        if planner is None or planner.model_dump(mode="json") != self.planner_identity:
            raise ReviewedLaunchRefusal("planner_identity_changed")
        if invariants.health_config_sha256 != self.health_config_sha256:
            raise ReviewedLaunchRefusal("health_settings_changed")
        if llm_config.model_dump(mode="json", by_alias=True) != self.llm_config:
            raise ReviewedLaunchRefusal("llm_settings_changed")
        if json_launch_values(identity) != self.launch_identity:
            raise ReviewedLaunchRefusal("launch_identity_changed")

    def check_launch(self, launch) -> None:
        actual = json_launch_values(launch)
        if actual != self.launch_settings:
            raise ReviewedLaunchRefusal("launch_settings_changed")
        verify_binding(self.binding)
        self.publish("matched")

    def publish(self, outcome: str, reason: str | None = None) -> None:
        import json

        payload = {**self.receipt_fields, "outcome": outcome, "reason": reason}
        publish_bytes_write_once(self.receipt_path, (json.dumps(payload, indent=2) + "\n").encode())
