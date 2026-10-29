"""Public durable admission and one detached dispatch; never replay an existing ID."""

import hashlib
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from tools.candidate_prepare import preflight_reusable_candidate
from tools.candidate_prepare.reusable_models import ReusablePreparationObservations
from tools.candidate_worker.loop_models import LoopStop
from tools.candidate_worker.preflight import fresh_preview, require_credentials
from tools.workflow_preview.models import FileObservation

from .expectation import compare_reusable_expectation
from .files import canonical, overlap, publish, read_bytes
from .host_admission import HostSlot, host_slot
from .host_ledger import HostScheduling
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
from .native_chain import review_native_chain_operation
from .native_chain_models import NativeChainAdmission
from .native_resume import review_native_chain_resume
from .native_resume_models import NativeResumeAdmission
from .process import environment, runtime_identity, spawn
from .read import releasable
from .reusable import verify_reusable_operation
from .seed_admission import admission_seed
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
    config: OperationStoreConfig,
    submission: OperationSubmission,
    chain_admission: NativeChainAdmission | None = None,
    resume_admission: NativeResumeAdmission | None = None,
) -> tuple[FileObservation, ...]:
    if submission.kind == "candidate_loop_resume":
        from .loop_resume import root_record
        from .store import load_record

        return root_record(load_record(config, submission.request.predecessor_operation_id)).inputs
    if submission.kind == "native_chain_resume":
        assert resume_admission is not None
        return resume_admission.root_admission.input_files
    if submission.kind == "native_chain":
        assert chain_admission is not None
        return chain_admission.input_files
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
    host: HostScheduling | None = None,
) -> OperationHandle:
    """Admit and dispatch one new operation; ``host`` selects the shared host ledger.

    Without ``host`` no ledger is read and the launch is the serial default.
    """
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
        with host_slot(host, config, submission) as slot:
            return _admit_new(
                root,
                config,
                submission,
                slot,
                slot.launch_environment(launch_environment),
                expected_reusable_inputs,
            )


def _admit_new(
    root: Path,
    config: OperationStoreConfig,
    submission: OperationSubmission,
    slot: HostSlot,
    launch_environment: Mapping[str, str],
    expected_reusable_inputs: ReusablePreparationExpectation | None,
) -> OperationHandle:
    """Native admission of a new ID; the slot already overlays any placed selector.

    A queued GPU child receives its selector only once placed (``host_queue``), so
    the slot's deferred names are neither checked here nor passed to the child.
    """
    deferred = slot.deferred_names()
    preparation_run_seed = None
    if submission.kind == "candidate":
        verified = verify_reusable_operation(config, submission)
        preparation_run_seed = None if verified is None else verified.receipt.run_seed
        try:
            observed = fresh_preview(submission.request)
        except (OSError, ValueError) as error:
            raise OperationFailure(
                "candidate_preflight", "candidate inputs or routes changed; review again"
            ) from error
        try:
            require_credentials(
                observed.selected_constructor_routes,
                _without(submission.request.environment_names, deferred),
                launch_environment,
            )
        except ValueError as error:
            # This boundary emits only names from the candidate credential policy.
            raise OperationFailure("credentials", str(error)) from error
    loop_names = None
    if submission.kind == "candidate_loop_resume":
        from .loop_resume import admit

        loop_names = admit(config, submission, launch_environment, deferred=deferred)
    chain_admission = None
    resume_admission = None
    if submission.kind == "native_chain_resume":
        review = review_native_chain_resume(
            config,
            submission.request.predecessor_operation_id,
            launch_environment=launch_environment,
        )
        if (
            review.eligibility != "ready"
            or review.review_digest != submission.request.expected_review_digest
        ):
            raise OperationFailure(
                "native_resume_review", "continuation is complete or the reviewed state changed"
            )
        resume_admission = review.admission
    if submission.kind == "native_chain":
        try:
            chain_admission = review_native_chain_operation(
                config,
                submission,
                launch_environment=launch_environment,
            )
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            raise OperationFailure(
                "native_chain_admission", "native chain capture or launch binding refused"
            ) from error
    names = (
        submission.request.environment_names
        if submission.kind == "candidate" or submission.kind == "native_chain"
        else resume_admission.root_request.environment_names
        if resume_admission is not None
        else ()
    )
    if loop_names is not None:
        names = loop_names
    env = environment(_without(names, deferred), launch_environment)
    return _claim_and_spawn(
        root,
        config,
        submission,
        slot,
        env,
        expected_reusable_inputs,
        chain_admission,
        resume_admission,
        preparation_run_seed,
    )


def _without(names: tuple[str, ...], deferred: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(name for name in names if name not in deferred)


def _claim_and_spawn(
    root: Path,
    config: OperationStoreConfig,
    submission: OperationSubmission,
    slot: HostSlot,
    env: dict[str, str],
    expected_reusable_inputs: ReusablePreparationExpectation | None,
    chain_admission: NativeChainAdmission | None,
    resume_admission: NativeResumeAdmission | None,
    preparation_run_seed: int | None,
) -> OperationHandle:
    loop_root = None
    if submission.kind == "candidate_loop_resume":
        from .loop_resume import root_record
        from .store import load_record

        loop_root = root_record(load_record(config, submission.request.predecessor_operation_id))
    # Issue #983 — bound under the store lock, before claim(): the record is the
    # durable seed authority the child executes.
    record = OperationRecord(
        native_id=uuid4(),
        submission=submission,
        request_digest=digest(submission),
        config=config,
        runtime=runtime_identity(),
        inputs=_admitted_inputs(config, submission, chain_admission, resume_admission),
        native_chain_admission=chain_admission,
        native_resume_admission=resume_admission,
        admitted_at=now(),
        run_seed=admission_seed(submission, loop_root),
        preparation_run_seed=preparation_run_seed,
    )
    compare_reusable_expectation(record, expected_reusable_inputs)
    path = claim(root, record)
    if submission.kind == "candidate_loop_resume":
        from .loop_resume import reserve

        reserve(record)
    slot.reserve(path, record)
    observation: Literal["starting", "queued", "operation_failed"] = slot.observation
    try:
        child = spawn(path, env)
    except BaseException as error:
        if not isinstance(error, OSError):
            # Interrupted before any child was bound: leave no ledger entry behind.
            slot.spawn_failed(submission.request_id)
            raise
        slot.spawn_failed(submission.request_id)
        # Popen failure means no executed child; any other ambiguous failure propagates
        # with the already-durable claim intact and is never retried automatically.
        publish(
            path / "spawn_failure.json",
            SpawnFailure(operation_id=submission.request_id, request_digest=record.request_digest),
        )
        observation = "operation_failed"
    else:
        slot.spawned(record, child)
    return OperationHandle(
        operation_id=submission.request_id,
        kind=submission.kind,
        request_digest=record.request_digest,
        observed_at=now(),
        observation=observation,
    )


def request_loop_stop(config: OperationStoreConfig, operation_id: UUID) -> LoopStop:
    """Request graceful Stop on a live loop or end its clean paused tail.

    This acknowledges the request, not termination. The active body finishes;
    read_operation reports whether the finite limit or Stop won the boundary.
    """
    from core.control_json import encode_control
    from core.durable_io import publish_bytes_write_once

    from .files import directory, read_model
    from .read import read_operation
    from .store import load_record, native_directory

    config = validate_config(config)
    with locked_store(config, create=False):
        record = load_record(config, operation_id)
        from .loop_resume import review_locked, root_inputs

        try:
            root_record, _, initial = root_inputs(record)
            assert root_record.submission.kind == "candidate"
            control = native_directory(root_record.submission)
        except FileNotFoundError as error:
            raise OperationFailure(
                "not_ready", "candidate worker has not claimed its workspace"
            ) from error
        marker = LoopStop(run_id=initial.run_id, declaration_digest=initial.declaration_digest)
        path = control / "stop.json"
        if path.exists():
            if read_model(path, LoopStop) != marker:
                raise OperationFailure("integrity", "Stop marker identity mismatch")
            return marker
        snapshot = read_operation(config, operation_id)
        if snapshot.receipt is not None and snapshot.receipt.status == "paused":
            # Same lock as Resume admission: only the clean paused tail can end,
            # never a historical checkpoint whose successor already continues it.
            review_locked(config, operation_id)
        elif snapshot.receipt_available or snapshot.process.status != "alive":
            raise OperationFailure("not_running", "candidate is terminal or not confirmed running")
        with directory(control) as descriptor:
            publish_bytes_write_once(
                f"/proc/self/fd/{descriptor}/stop.json", encode_control(marker)
            )
        return marker
