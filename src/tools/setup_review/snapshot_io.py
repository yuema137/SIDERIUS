"""Bounded saved-report reads and exclusive output claims; no historical path replay."""

import hashlib
import json
import os
from pathlib import Path

from core.execution_deadline import remaining_seconds
from core.file_identity import open_identity_file, regular_file_snapshot
from core.layout import checkout_root, package_root
from tools.setup_review.environment_models import EnvironmentPreviewReport
from tools.setup_review.models import SetupDeclarationReport
from tools.setup_review.semantic_models import (
    SavedTaskCheckSnapshot,
    SnapshotInputError,
    SnapshotOperation,
)
from tools.setup_review.semantic_packet import Snapshot, declaration_of


def read_snapshot(operation: SnapshotOperation) -> Snapshot:
    decoded = read_verified_json(
        operation.report, operation.expected_sha256, operation.input_max_bytes
    )
    version = decoded.get("schema_version")
    if version == "siderius.setup-declaration/v2":
        return SetupDeclarationReport.model_validate(decoded)
    if version == "siderius.task-composition-check/v1":
        return SavedTaskCheckSnapshot.model_validate(decoded)
    if version == "siderius.setup-environment/v1":
        return EnvironmentPreviewReport.model_validate(decoded)
    raise SnapshotInputError(
        "Unsupported report schema; provide a standard declaration, task check or environment report"
    )


def read_verified_json(report: Path, expected_sha256: str, input_max_bytes: int) -> dict:
    """The shared bounded saved-artifact reader, without path-wrapper reconstruction."""
    if not report.is_absolute():
        raise SnapshotInputError("report must be an absolute path to an existing report.json")
    with open_identity_file(str(report), require_no_follow=True) as handle:
        before = regular_file_snapshot(handle)
        if before.size > input_max_bytes:
            raise SnapshotInputError(
                "Report exceeds input_max_bytes; inspect it before increasing the limit"
            )
        payload = handle.read(input_max_bytes + 1)
        if len(payload) > input_max_bytes or regular_file_snapshot(handle) != before:
            raise SnapshotInputError("Report changed or exceeded input_max_bytes during reading")
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise SnapshotInputError(
            "Report SHA-256 differs from expected_sha256; inspect the selected snapshot"
        )
    remaining_seconds("setup_review.report_read")
    decoded = json.loads(payload)
    if not isinstance(decoded, dict):
        raise SnapshotInputError("Report must be a supported JSON object")
    return decoded


def claim_snapshot_output(operation: SnapshotOperation, snapshot: Snapshot) -> None:
    output = operation.output
    if not output.is_absolute() or output != output.resolve():
        raise SnapshotInputError("output must be a canonical absolute path without symlink aliases")
    if os.path.lexists(output) or not output.parent.is_dir():
        raise SnapshotInputError("output must be new and its parent directory must already exist")
    protected = (
        checkout_root() or package_root(),
        Path(declaration_of(snapshot).workspace).resolve(),
        operation.report.resolve(),
    )
    if any(output.is_relative_to(path) or path.is_relative_to(output) for path in protected):
        raise SnapshotInputError(
            "output must be separate from the installation, run workspace and report"
        )
    output.mkdir(mode=0o700)
