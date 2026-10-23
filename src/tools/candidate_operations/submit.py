"""Public durable admission and one detached dispatch; never replay an existing ID."""

import hashlib
from collections.abc import Mapping
from pathlib import Path
from uuid import uuid4

from tools.workflow_preview.models import FileObservation

from .files import publish, read_bytes
from .models import (
    OperationHandle,
    OperationRecord,
    OperationStoreConfig,
    OperationSubmission,
    SpawnFailure,
)
from .process import environment, runtime_identity, spawn
from .read import releasable
from .store import (
    claim,
    digest,
    existing,
    locked_store,
    now,
    require_available,
    validate_config,
    validate_submission,
)


def capture_inputs(submission: OperationSubmission) -> tuple[FileObservation, ...]:
    if submission.kind == "candidate":
        return submission.request.files
    request = submission.request
    result = []
    for name, value in (
        ("task.manifest", request.task_manifest),
        ("llm_config", request.llm_config_file),
    ):
        payload = read_bytes(Path(value))
        result.append(
            FileObservation(
                reference=name,
                path=value,
                sha256=hashlib.sha256(payload).hexdigest(),
                size_bytes=len(payload),
            )
        )
    return tuple(result)


def submit_operation(
    config: OperationStoreConfig,
    submission: OperationSubmission,
    *,
    launch_environment: Mapping[str, str],
) -> OperationHandle:
    config = validate_config(config)
    submission = validate_submission(config, submission)
    # Validate names before claim; values are needed only for a genuinely new launch.
    with locked_store(config) as root:
        prior = existing(config, submission)
        if prior is not None:
            return OperationHandle(
                operation_id=submission.request_id,
                kind=submission.kind,
                request_digest=prior.request_digest,
                observed_at=now(),
                observation="existing",
            )
        require_available(root, lambda operation_id: releasable(config, operation_id))
        names = submission.request.environment_names if submission.kind == "candidate" else ()
        env = environment(names, launch_environment)
        record = OperationRecord(
            native_id=uuid4(),
            submission=submission,
            request_digest=digest(submission),
            config=config,
            runtime=runtime_identity(),
            inputs=capture_inputs(submission),
            admitted_at=now(),
        )
        path = claim(root, record)
        observation = "starting"
        try:
            spawn(path, env)
        except OSError:
            # Popen failure means no executed child; any other ambiguous failure propagates
            # with the already-durable claim intact and is never retried automatically.
            publish(
                path / "spawn_failure.json",
                SpawnFailure(
                    operation_id=submission.request_id, request_digest=record.request_digest
                ),
            )
            observation = "operation_failed"
        return OperationHandle(
            operation_id=submission.request_id,
            kind=submission.kind,
            request_digest=record.request_digest,
            observed_at=now(),
            observation=observation,
        )
