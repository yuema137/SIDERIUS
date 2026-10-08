"""Explicit local environment observations, distinct from saved task evidence."""

from typing import Literal

from pydantic import JsonValue

from core.hardware_context import HardwareContext
from core.runtime_control.watchdog_profile import ResolvedWatchdogSettings
from tools.setup_review.models import SetupDeclarationReport
from tools.setup_review.route_models import CredentialNameCheck
from tools.setup_review.semantic_models import (
    Digest,
    ReviewModel,
    SavedTaskCheckSnapshot,
    SnapshotOperation,
)


class EnvironmentPreviewRequest(SnapshotOperation):
    """Reading this request explicitly selects local property/profile inspection."""

    check_environment: bool = False


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
    hardware: HardwareContext
    watchdog: ResolvedWatchdogSettings
    dataset_directory: str
    launch_settings: dict[str, JsonValue]
    limitations: tuple[str, ...]
