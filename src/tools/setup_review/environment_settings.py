"""Explicitly observe launch settings; never create a run or import its task."""

import os
from dataclasses import asdict
from pathlib import Path

from core.durable_io import publish_bytes_write_once
from core.hardware_context import inspect_gpu_runtime
from core.runtime_control.pair_admission import (
    HOST_VRAM_QUOTA_MIB_ENV,
    PAIR_CEILING_GIB_ENV,
    gib_from_bytes,
    resolve_gpu_ceiling,
)
from execute_tools.data_paths import resolve_dataset_dir
from tools.setup_review.composition_transport import manifest_digest
from tools.setup_review.environment import credential_name_checks
from tools.setup_review.environment_models import (
    EnvironmentPreviewReport,
    EnvironmentPreviewRequest,
)
from tools.setup_review.environment_render import render_environment_preview
from tools.setup_review.inspection import _json_value, inspect_parsed_declaration
from tools.setup_review.semantic_models import SavedTaskCheckSnapshot, SnapshotInputError
from tools.setup_review.snapshot_io import claim_snapshot_output, read_snapshot
from tools.setup_review.task_settings_models import FORMAL_DELTA_FIELDS, encode_formal_delta
from workflows.launch_identity import resolve_launch_identity
from workflows.run_config import validate_launch_trial_overrides
from workflows.runtime_settings import resolve_watchdog_policy
from workflows.standard_launch import build_standard_launch_config

_LIMITATIONS = (
    "Task composition, scope, Health configuration and task-dependent routes are saved observations; "
    "task implementations and plugins were not imported or rechecked in this operation.",
    "Only parsed declarations, selected declaration identities and manifest bytes were compared. "
    "This is not complete source freshness or a binding enforced by the ordinary launch command.",
    "Hardware properties and watchdog settings were observed now. Device availability is not "
    "proof of driver/accounting support, sufficient memory, timing, or successful execution. "
    "Untested hardware and missing accounting adapters are distinct unresolved questions.",
    "The physical data directory exists. Read permissions, dataset contents, splits and task "
    "compatibility were not tested; no dataset was loaded.",
    "The launch projection is the standard runner's transit configuration. Null values may "
    "delegate choices to downstream task/agent owners; they are not invented training defaults.",
    "Conditional execution, model-selected parameters, Health evaluations, authentication, "
    "budget enforcement and successful training remain unverified.",
    "No LLM review or explicit skip was performed here. Review/skip receipts for earlier "
    "snapshots do not automatically cover this new environment observation.",
    "Do not treat this report as launch approval. Configuration, code, environment and hardware "
    "can change after observation; ordinary launches do not consume this report.",
)


def inspect_environment(request: EnvironmentPreviewRequest) -> EnvironmentPreviewReport:
    """Reparse a saved task check, observe local facts and publish a new preview."""
    snapshot = read_snapshot(request)
    if (
        not isinstance(snapshot, SavedTaskCheckSnapshot)
        or snapshot.result.outcome != "passed"
        or snapshot.result.task_settings is None
    ):
        raise SnapshotInputError(
            "Provide a successful task check created with --resolve-task-settings"
        )
    current, args = inspect_parsed_declaration(
        snapshot.declaration.request,
        request.output,
        check_environment=False,
    )
    # Locations and optional key-name observations differ by operation. Every
    # other parsed value/selected identity must still match the saved declaration.
    excluded = {"output_directory", "environment_check_requested", "credentials"}
    if current.model_dump(exclude=excluded) != snapshot.declaration.model_dump(exclude=excluded):
        raise SnapshotInputError(
            "Current declarations differ from the saved task check; regenerate the task check"
        )
    if manifest_digest(current.task_manifest) != snapshot.result.manifest_sha256:
        raise SnapshotInputError("Task manifest changed; regenerate the task check")
    args.data_dir = resolve_dataset_dir(args.data_dir, purpose="setup environment preview")
    gpu_runtime = inspect_gpu_runtime()
    hardware = gpu_runtime.hardware
    aggregate = None
    if hardware.device_available:
        # Read only the two environment inputs owned by the aggregate resolver.
        # In particular, do not copy the complete credential-bearing environment.
        limits = {
            name: value
            for name in (HOST_VRAM_QUOTA_MIB_ENV, PAIR_CEILING_GIB_ENV)
            if (value := os.environ.get(name)) is not None
        }
        aggregate = resolve_gpu_ceiling(
            ceiling_gib=args.gpu_pair_ceiling_gib,
            measured_capacity_gib=gib_from_bytes(hardware.total_memory_bytes),
            environ=limits,
        )
    watchdog = resolve_watchdog_policy(args, device_name=hardware.device_name)
    launch = build_standard_launch_config(
        args, resolve_launch_identity(args), resolved_paths=[], fixed_candidate_plan=None
    )
    validate_launch_trial_overrides(launch)
    values = asdict(launch)
    for field in FORMAL_DELTA_FIELDS:
        values[field] = encode_formal_delta(values[field])
    report = EnvironmentPreviewReport(
        source_report=str(request.report),
        source_sha256=request.expected_sha256,
        input_max_bytes=request.input_max_bytes,
        output=str(request.output),
        saved_task_check=snapshot,
        current_declaration=current,
        environment_check_requested=request.check_environment,
        credentials=credential_name_checks(
            snapshot.result.task_settings.llm_routes, requested=request.check_environment
        ),
        gpu_runtime=gpu_runtime,
        aggregate_gpu_ceiling=aggregate,
        aggregate_gpu_ceiling_gib=aggregate.effective_gib if aggregate else None,
        per_candidate_usable_cap_bytes=hardware.usable_cap_bytes
        if hardware.device_available
        else None,
        watchdog=watchdog,
        dataset_directory=str(Path(args.data_dir).resolve()),
        launch_settings={name: _json_value(value) for name, value in values.items()},
        limitations=_LIMITATIONS,
    )
    claim_snapshot_output(request, snapshot)
    publish_bytes_write_once(
        str(request.output / "report.json"), (report.model_dump_json(indent=2) + "\n").encode()
    )
    publish_bytes_write_once(
        str(request.output / "index.html"), render_environment_preview(report).encode()
    )
    return report
