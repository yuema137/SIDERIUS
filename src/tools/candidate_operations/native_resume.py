"""Review an exited native tail under the existing writer lock; no effects."""

import hashlib
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from uuid import UUID

from core.native_writer.resume import LockedWriter, locked_registered_writer
from tools.candidate_worker.preflight import credential_requirements, require_credentials
from tools.native_chain.resume_checks import append_boundary

from .files import JSON_LIMIT, encode
from .models import OperationFailure, OperationRecord, OperationStoreConfig
from .native_chain import captured
from .native_chain_read import chain_context
from .native_resume_lineage import read_lineage, require_closed
from .native_resume_models import NativeResumeAdmission, NativeResumeReview, review_digest
from .native_resume_read import verified_current
from .process import environment, runtime_identity
from .store import load_record, validate_config


def review_locked(
    config: OperationStoreConfig,
    predecessor: UUID,
    guard: LockedWriter,
    *,
    launch_environment: Mapping[str, str] | None = None,
    record: OperationRecord | None = None,
) -> NativeResumeReview:
    if record is None:
        record = load_record(config, predecessor)
    if record.config != config or record.submission.request_id != predecessor:
        raise ValueError("resume_selected_record_changed")
    lineage = read_lineage(record)
    head = lineage.head
    if head.id != predecessor:
        raise ValueError("resume_predecessor_is_not_tail")
    require_closed(head, lineage.adoptions[-1] if lineage.adoptions else None)
    request, admission = chain_context(record)
    owner = guard.snapshot()
    if (
        str(guard.state.workspace) != admission.workspace
        or owner.registration.capture_sha256 != request.capture_sha256
    ):
        raise ValueError("resume_owner_changed")
    baseline = next((node for node in reversed(lineage.nodes) if node.terminal is not None), None)
    if (
        baseline is None
        or baseline.terminal is None
        or baseline.completion is None
        or baseline.terminal.observation_policy not in (2, 3)
    ):
        raise ValueError("resume_verified_baseline_required")
    if head.terminal is None and (
        record.native_resume_admission is None or owner != record.native_resume_admission.owner
    ):
        raise ValueError("resume_no_child_owner_changed")
    evidence = verified_current(lineage)
    if evidence != baseline.terminal.evidence:
        raise ValueError("resume_baseline_changed")
    start = append_boundary(Path(admission.workspace), evidence, admission.final_iteration)
    capture = captured(request)
    if runtime_identity().source != admission.checkout:
        raise ValueError("resume_source_changed")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.native_chain.check",
            "verify",
            "--capture",
            request.capture_path,
            "--sha256",
            request.capture_sha256,
            "--input-max-bytes",
            str(request.input_max_bytes),
            "--",
        ],
        cwd=admission.checkout,
        env=environment((), {}),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=60,
        check=True,
    )
    if captured(request) != capture:
        raise ValueError("resume_capture_changed")
    settings = capture.environment.saved_task_check.result.task_settings
    assert settings is not None
    routes = tuple(settings.llm_routes)
    policy = credential_requirements(routes, request.environment_names)
    if (
        policy.omitted_names
        or policy.unresolved_routes
        or policy.required_names != admission.required_environment_names
    ):
        raise ValueError("resume_routes_changed")
    if launch_environment is not None:
        require_credentials(routes, request.environment_names, launch_environment)
    assert head.completion_digest is not None and baseline.completion.terminal_digest is not None
    admitted = NativeResumeAdmission(
        state_root=config.state_root,
        store_digest=hashlib.sha256(encode(config)).hexdigest(),
        root_operation_id=lineage.nodes[0].id,
        predecessor_operation_id=predecessor,
        predecessor_completion_digest=head.completion_digest,
        baseline_operation_id=baseline.id,
        baseline_terminal_digest=baseline.completion.terminal_digest,
        root_request=request,
        root_admission=admission,
        owner=owner,
        evidence=evidence,
        start_iteration=start,
    )
    if len(encode(admitted)) + request.max_observation_bytes + 65536 > JSON_LIMIT:
        raise ValueError("resume_control_limit")
    return NativeResumeReview(
        eligibility="ready" if start <= admission.final_iteration else "not_needed",
        review_digest=review_digest(admitted),
        admission=admitted,
    )


def review_native_chain_resume(
    config: OperationStoreConfig,
    predecessor: UUID,
    *,
    launch_environment: Mapping[str, str] | None = None,
) -> NativeResumeReview:
    try:
        config = validate_config(config)
        record = load_record(config, predecessor)
        with locked_registered_writer(Path(chain_context(record)[1].workspace)) as guard:
            return review_locked(
                config, predecessor, guard, launch_environment=launch_environment, record=record
            )
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        raise OperationFailure(
            "native_resume_admission",
            "native continuation refused; inspect lifecycle, capture and checkpoint evidence",
        ) from error
