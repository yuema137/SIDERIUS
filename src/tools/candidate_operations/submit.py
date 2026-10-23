"""Public durable admission and one detached dispatch; never replay an existing ID."""

import hashlib
from collections.abc import Mapping
from pathlib import Path
from uuid import uuid4

from tools.candidate_prepare import preflight_reusable_candidate
from tools.candidate_prepare.reusable_models import ReusablePreparationObservations
from tools.candidate_worker.preflight import fresh_preview, require_credentials
from tools.workflow_preview.models import FileObservation

from .expectation import compare_reusable_expectation
from .files import canonical, overlap, publish, read_bytes
from .models import (
    CandidateOperation,
    OperationFailure,
    OperationHandle,
    OperationRecord,
    OperationStoreConfig,
    OperationSubmission,
    PrepareOperation,
    ReusablePreparationExpectation,
    SpawnFailure,
)
from .process import environment, runtime_identity, spawn
from .read import releasable
from .reusable import verify_reusable_operation
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


def capture_inputs(
    submission: PrepareOperation | CandidateOperation,
) -> tuple[FileObservation, ...]:
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


def _admitted_inputs(
    config: OperationStoreConfig, submission: OperationSubmission
) -> tuple[FileObservation, ...]:
    if submission.kind != "prepare_reusable":
        return capture_inputs(submission)
    try:
        plan = preflight_reusable_candidate(submission.request)
    except (OSError, ValueError) as error:
        raise OperationFailure(
            "reusable_preflight", "reusable inputs changed or are unavailable; review again"
        ) from error
    state = canonical(config.state_root)
    if any(
        overlap(state, canonical(value))
        for value in (
            plan.binding.request.task_manifest,
            plan.binding.request.data_root,
            plan.binding.request.llm_config_file,
        )
    ):
        raise OperationFailure("path", "operation state overlaps selected inputs")
    return ReusablePreparationObservations.from_binding(plan.binding).as_inputs()


def submit_operation(
    config: OperationStoreConfig,
    submission: OperationSubmission,
    *,
    launch_environment: Mapping[str, str],
    expected_reusable_inputs: ReusablePreparationExpectation | None = None,
) -> OperationHandle:
    config = validate_config(config)
    submission = validate_submission(config, submission)
    if expected_reusable_inputs is not None and submission.kind != "prepare_reusable":
        raise OperationFailure("kind", "reusable expectation requires prepare_reusable")
    # Validate names before claim; values are needed only for a genuinely new launch.
    with locked_store(config) as root:
        prior = existing(config, submission)
        if prior is not None:
            compare_reusable_expectation(prior, expected_reusable_inputs)
            return OperationHandle(
                operation_id=submission.request_id,
                kind=submission.kind,
                request_digest=prior.request_digest,
                observed_at=now(),
                observation="existing",
            )
        require_available(root, lambda operation_id: releasable(config, operation_id))
        if submission.kind == "candidate":
            verify_reusable_operation(config, submission)
            try:
                observed = fresh_preview(submission.request)
            except (OSError, ValueError) as error:
                raise OperationFailure(
                    "candidate_preflight", "candidate inputs or routes changed; review again"
                ) from error
            try:
                require_credentials(
                    observed.selected_constructor_routes,
                    submission.request.environment_names,
                    launch_environment,
                )
            except ValueError as error:
                # This boundary emits only names from the candidate credential policy.
                raise OperationFailure("credentials", str(error)) from error
        names = submission.request.environment_names if submission.kind == "candidate" else ()
        env = environment(names, launch_environment)
        record = OperationRecord(
            native_id=uuid4(),
            submission=submission,
            request_digest=digest(submission),
            config=config,
            runtime=runtime_identity(),
            inputs=_admitted_inputs(config, submission),
            admitted_at=now(),
        )
        compare_reusable_expectation(record, expected_reusable_inputs)
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
