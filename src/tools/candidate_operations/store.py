"""Store validation, immutable requests and serialized single-operation admission."""

import fcntl
import hashlib
import json
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from tools.candidate_prepare.admission import validate_destination_overlap
from tools.workflow_preview.files import resolve_location
from tools.workspace_sandbox.profile import SandboxProfile, runtime_roots

from .files import (
    canonical,
    directory,
    encode,
    overlap,
    private,
    private_directory,
    publish,
    publish_encoded,
    read_model,
)
from .models import (
    SUBMISSION,
    ActiveOperation,
    OperationFailure,
    OperationRecord,
    OperationStoreConfig,
    OperationSubmission,
)
from .reusable import validate_selection_root


def now() -> str:
    return datetime.now(UTC).isoformat()


def digest(submission: OperationSubmission) -> str:
    content = {"kind": submission.kind, "request": submission.request.model_dump(mode="json")}
    if submission.kind == "candidate" and submission.request.workflow_source is None:
        content["request"].pop("workflow_source")
    if submission.kind == "candidate" and submission.reusable_preparation is not None:
        content["reusable_preparation"] = submission.reusable_preparation.model_dump(mode="json")
    if submission.kind == "candidate" and submission.resources is not None:
        content["resources"] = submission.resources.model_dump(mode="json")
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def validate_config(config: OperationStoreConfig) -> OperationStoreConfig:
    config = OperationStoreConfig.model_validate_json(config.model_dump_json())
    state = canonical(config.state_root)
    roots = tuple(canonical(root) for root in (*config.preparation_roots, *config.candidate_roots))
    if not all(root.is_dir() for root in roots):
        raise OperationFailure("path", "allowed output roots must exist as directories")
    if any(overlap(state, root) for root in runtime_roots()):
        raise OperationFailure("path", "operation state overlaps runtime/source")
    return config


def is_authored_loop(record: OperationRecord) -> bool:
    """True for an authored-loop root candidate or any of its continuation segments."""
    submission = record.submission
    return submission.kind == "candidate_loop_resume" or (
        submission.kind == "candidate"
        and submission.request.preview.document.definition.loop is not None
    )


def native_directory(submission: OperationSubmission) -> Path:
    if submission.kind in {"native_chain", "native_chain_resume", "candidate_loop_resume"}:
        raise OperationFailure("kind", "continuation requires its resolved root record")
    if submission.kind == "prepare":
        return canonical(submission.request.output_dir) / "preparation"
    if submission.kind == "prepare_reusable":
        return (
            canonical(submission.request.runs_root)
            / str(submission.request.run_id)
            / "inputs/preparation"
        )
    assert submission.kind == "candidate"
    request = submission.request
    project = canonical(request.preview.project_root)
    workspace = resolve_location(
        project, request.preview.document.definition.task.workspace, "workspace"
    )
    canonical(str(workspace))
    # Check the original spelling as well: resolve_location alone follows aliases.
    original = project / request.preview.document.definition.task.workspace
    if original != workspace:
        raise OperationFailure("path", "candidate workspace must have canonical ancestry")
    return workspace / "candidate_run"


def validate_submission(
    config: OperationStoreConfig, submission: OperationSubmission
) -> OperationSubmission:
    submission = SUBMISSION.validate_json(SUBMISSION.dump_json(submission))
    if submission.kind in {"native_chain_resume", "candidate_loop_resume"}:
        # Syntax only: same-ID lookup precedes every mutable predecessor/input check.
        return submission
    state = canonical(config.state_root)
    if submission.kind == "native_chain":
        request = submission.request
        SandboxProfile.environment_keys(request.environment_names)
        if any(name.startswith("GIT_") for name in request.environment_names):
            raise OperationFailure("environment", "Git environment overrides are unsupported")
        outputs = ((canonical(request.envelope), config.candidate_roots),)
        inputs = (request.capture_path, *request.read_only)
    elif submission.kind == "prepare":
        request = submission.request
        SandboxProfile.environment_keys(request.candidate_environment_names)
        outputs = (
            (canonical(request.output_dir), config.preparation_roots),
            (canonical(request.candidate_workspace), config.candidate_roots),
        )
        inputs = (
            request.task_manifest,
            request.llm_config_file,
            request.data_root,
            *request.task_read_only,
        )
    elif submission.kind == "prepare_reusable":
        request = submission.request
        SandboxProfile.environment_keys(request.candidate_environment_names)
        envelope = canonical(request.runs_root) / str(request.run_id)
        canonical(request.project_root)
        outputs = (
            (envelope, config.preparation_roots),
            (envelope / "workspace", config.candidate_roots),
        )
        inputs = (request.source_path, request.llm_config_file, *request.task_read_only)
        validate_destination_overlap(envelope, tuple(canonical(value) for value in inputs))
    else:
        assert submission.kind == "candidate"
        if submission.reusable_preparation is not None:
            validate_selection_root(config, submission.reusable_preparation)
        request = submission.request
        SandboxProfile.environment_keys(request.environment_names)
        outputs = ((native_directory(submission).parent, config.candidate_roots),)
        project = canonical(request.preview.project_root)
        task = request.preview.document.definition.task
        inputs = (
            str(project),
            str(resolve_location(project, task.data_root, "data")),
            str(resolve_location(project, task.manifest, "manifest")),
            *(item.path for item in request.files),
            *request.read_only,
        )
    for output, roots in outputs:
        if not any(
            output.is_relative_to(canonical(root)) and output != canonical(root) for root in roots
        ):
            raise OperationFailure("path", "native destination is outside configured roots")
        if overlap(state, output):
            raise OperationFailure("path", "operation state overlaps native destination")
    if any(overlap(state, canonical(value)) for value in inputs):
        raise OperationFailure("path", "operation state overlaps selected inputs")
    return submission


@contextmanager
def locked_store(config: OperationStoreConfig, *, create: bool = True) -> Iterator[Path]:
    root = canonical(config.state_root)
    private_directory(root, create=create)
    private_directory(root / "operations", create=create)
    with directory(root) as descriptor:
        lock = os.open(
            "admission.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=descriptor
        )
    try:
        private(os.fstat(lock), directory=False)
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield root
    finally:
        os.close(lock)


def operation_path(config: OperationStoreConfig, operation_id: UUID) -> Path:
    if not isinstance(operation_id, UUID):
        raise OperationFailure("operation_id", "operation_id must be a UUID")
    root = canonical(config.state_root)
    private_directory(root)
    private_directory(root / "operations")
    path = root / "operations" / str(operation_id)
    private_directory(path)
    return path


def operation_admitted(config: OperationStoreConfig, operation_id: UUID) -> bool:
    """False only after the private store root was opened and lists no such operation.

    A missing or non-private store root raises instead: an unavailable store never
    proves absence. A present entry (even one still being admitted) returns True.
    """
    if not isinstance(operation_id, UUID):
        raise OperationFailure("operation_id", "operation_id must be a UUID")
    root = canonical(validate_config(config).state_root)
    private_directory(root)
    operations = root / "operations"
    with directory(root) as descriptor:
        try:
            os.stat("operations", dir_fd=descriptor, follow_symlinks=False)
        except FileNotFoundError:
            return False
    private_directory(operations)
    with directory(operations) as descriptor:
        try:
            os.stat(str(operation_id), dir_fd=descriptor, follow_symlinks=False)
        except FileNotFoundError:
            return False
    return True


def load_record(config: OperationStoreConfig, operation_id: UUID) -> OperationRecord:
    path = operation_path(config, operation_id)
    record = read_model(path / "request.json", OperationRecord, private_file=True)
    return validate_record(config, operation_id, record)


def validate_record(
    config: OperationStoreConfig, operation_id: UUID, record: OperationRecord
) -> OperationRecord:
    """Validate already bounded bytes without a second filesystem read."""
    if record.submission.request_id != operation_id or record.request_digest != digest(
        record.submission
    ):
        raise OperationFailure("integrity", "operation request identity mismatch")
    if record.config != config:
        raise OperationFailure(
            "integrity", "store configuration differs from admitted configuration"
        )
    validate_submission(config, record.submission)
    return record


def existing(
    config: OperationStoreConfig, submission: OperationSubmission
) -> OperationRecord | None:
    path = Path(config.state_root) / "operations" / str(submission.request_id)
    if not os.path.lexists(path):
        return None
    record = load_record(config, submission.request_id)
    if record.request_digest != digest(submission):
        raise OperationFailure("conflict", "request_id already identifies different content")
    return record


def claim(root: Path, record: OperationRecord) -> Path:
    payload = encode(record)
    path = root / "operations" / str(record.submission.request_id)
    with directory(path.parent) as descriptor:
        os.mkdir(path.name, 0o700, dir_fd=descriptor)
    publish_encoded(path / "request.json", payload)
    publish(
        root / "active.json",
        ActiveOperation(operation_id=record.submission.request_id),
        replace=True,
    )
    return path


def require_available(root: Path, releasable: Callable[[UUID], bool]) -> None:
    """Check all claims, including a crash before publishing the derived active pointer."""
    with directory(root / "operations") as descriptor:
        names = os.listdir(descriptor)
    for name in names:
        try:
            operation_id = UUID(name)
        except ValueError as error:
            raise OperationFailure("integrity", "unrecognized operation directory") from error
        if str(operation_id) != name or not releasable(operation_id):
            raise OperationFailure("busy", "store has an active or unresolved operation")
