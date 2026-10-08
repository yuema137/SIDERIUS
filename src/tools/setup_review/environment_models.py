"""Explicit local environment observations, distinct from saved task evidence."""

from typing import Literal

from pydantic import Field, JsonValue

from core.hardware_context import GpuRuntimeFacts
from core.runtime_control.pair_admission import ResolvedGpuCeiling
from core.runtime_control.watchdog_profile import ResolvedWatchdogSettings
from tools.setup_review.models import SetupDeclarationReport
from tools.setup_review.route_models import CredentialNameCheck
from tools.setup_review.semantic_models import (
    Digest,
    ReviewModel,
    SavedTaskCheckSnapshot,
    SnapshotOperation,
)
from workflows.reviewed_launch_binding import LaunchInputBinding


class EnvironmentPreviewRequest(SnapshotOperation):
    """Reading this request explicitly selects local property/profile inspection."""

    check_environment: bool = False
    bind_launch: bool = Field(default=False, exclude_if=lambda value: not value)


class EnvironmentPreviewReport(ReviewModel):
    schema_version: Literal["siderius.setup-environment/v1"] = "siderius.setup-environment/v1"
    outcome: Literal["settings_observed"] = "settings_observed"
    source_report: str
    source_sha256: Digest
    input_max_bytes: int
    output: str
    saved_task_check: SavedTaskCheckSnapshot
    current_declaration: SetupDeclarationReport
    environment_check_requested: bool
    credentials: list[CredentialNameCheck]
    gpu_runtime: GpuRuntimeFacts
    aggregate_gpu_ceiling: ResolvedGpuCeiling | None
    aggregate_gpu_ceiling_gib: float | None
    per_candidate_usable_cap_bytes: int | None
    watchdog: ResolvedWatchdogSettings
    dataset_directory: str
    launch_settings: dict[str, JsonValue]
    limitations: tuple[str, ...]
    launch_binding: LaunchInputBinding | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
