"""Fresh capture admission and one native shell dispatch, never a scheduler."""

import hashlib
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

from tools.candidate_worker.preflight import credential_requirements, require_credentials
from tools.native_chain.models import NativeChainCapture
from tools.native_chain.observation import CURRENT_OBSERVATION_POLICY
from tools.native_chain.review import read_bytes as capture_bytes
from tools.workflow_preview.models import FileObservation
from tools.workspace_sandbox.profile import SandboxProfile, runtime_roots
from tools.workspace_sandbox.runner import (
    ObservedExecutionResult,
    ObservedSpawnFailure,
    run_observed,
)

from .files import JSON_LIMIT, canonical, directory, encode, overlap, publish, read_model
from .models import Completion, OperationFailure, OperationRecord, OperationStoreConfig
from .native_chain_models import (
    NativeChainAdmission,
    NativeChainFence,
    NativeChainOperation,
    NativeChainOperationRequest,
    NativeChainTerminal,
)
from .native_chain_read import chain_context, chain_evidence
from .process import environment, runtime_identity
from .store import digest, validate_config, validate_submission


def captured(request: NativeChainOperationRequest) -> NativeChainCapture:
    payload = capture_bytes(canonical(request.capture_path), request.input_max_bytes)
    if hashlib.sha256(payload).hexdigest() != request.capture_sha256:
        raise OperationFailure("capture", "capture digest changed")
    return NativeChainCapture.model_validate_json(payload)


def shell_arguments(
    request: NativeChainOperationRequest, capture: NativeChainCapture
) -> tuple[str, ...]:
    return (
        *capture.shell_argv,
        "--expected_chain_capture",
        request.capture_path,
        "--expected_chain_capture_sha256",
        request.capture_sha256,
        "--chain_capture_input_max_bytes",
        str(request.input_max_bytes),
    )


def _git_directory(checkout: Path, option: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", option],
        cwd=checkout,
        env=environment((), {}),
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    path = canonical(result.stdout.strip())
    if not path.is_dir():
        raise OperationFailure("git", "Git metadata directory unavailable")
    # External object stores are not admitted implicitly.
    if (path / "objects/info/alternates").exists():
        raise OperationFailure("git", "Git object alternates are unsupported")
    return str(path)


def sandbox_profile(
    request: NativeChainOperationRequest, admission: NativeChainAdmission
) -> SandboxProfile:
    roots = {
        canonical(value)
        for value in (
            request.capture_path,
            *request.read_only,
            admission.git_directory,
            admission.git_common_directory,
            *(item.path for item in admission.input_files),
        )
    }
    roots = {p for p in roots if not any(p != other and p.is_relative_to(other) for other in roots)}
    return SandboxProfile(
        workspace=canonical(request.envelope),
        read_only=tuple(sorted(roots)),
        network=request.network,
        devices=tuple(canonical(p) for p in request.devices),
        environment_names=request.environment_names,
        timeout_seconds=request.timeout_seconds,
    )


def require_empty(envelope: Path, *, claimed: bool = False) -> None:
    with directory(envelope) as descriptor, os.scandir(descriptor) as entries:
        expected = {".native-chain-operation"} if claimed else set()
        for entry in entries:
            if entry.name not in expected:
                raise OperationFailure(
                    "destination", "native chain requires a fresh empty envelope"
                )
            expected.remove(entry.name)
        if expected:
            raise OperationFailure("destination", "native chain claim disappeared")


def _review_native_chain_operation(
    config: OperationStoreConfig,
    submission: NativeChainOperation,
    *,
    launch_environment: Mapping[str, str] | None = None,
) -> NativeChainAdmission:
    """Read-only review; the CLI passes credentials explicitly, recovery never calls it."""
    validate_config(config)
    validate_submission(config, submission)
    request = submission.request
    envelope = canonical(request.envelope)
    require_empty(envelope)
    capture = captured(request)
    run = capture.declaration.run
    binding = capture.environment.launch_binding
    settings = capture.environment.saved_task_check.result.task_settings
    assert binding is not None and settings is not None
    runtime = runtime_identity()
    checkout = canonical(str(capture.declaration.working_directory))
    if (
        run.workspace != envelope / "workspace"
        or str(checkout) != runtime.source
        or binding.installation.source_root != runtime.source
        or binding.file_max_bytes != request.input_max_bytes
        or run.final_iteration > request.max_iterations_observed
    ):
        raise OperationFailure("capture", "capture runtime, destination or bounds disagree")
    routes = tuple(settings.llm_routes)
    policy = credential_requirements(routes, request.environment_names)
    if policy.omitted_names or policy.unresolved_routes:
        raise OperationFailure("credentials", "native chain credential routing is incomplete")
    if launch_environment is not None:
        require_credentials(routes, request.environment_names, launch_environment)
    # Execute A's real cwd-sensitive verifier; never mutate the server's cwd.
    subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.native_chain.check",
            "admit",
            "--capture",
            request.capture_path,
            "--sha256",
            request.capture_sha256,
            "--input-max-bytes",
            str(request.input_max_bytes),
            "--",
            *shell_arguments(request, capture),
        ],
        cwd=checkout,
        env=environment((), {}),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=60,
        check=True,
    )
    if captured(request) != capture:
        raise OperationFailure("capture", "capture changed during verification")
    files = (
        FileObservation(
            reference="native_chain.source",
            path=str(capture.source_path),
            sha256=capture.source_sha256,
            size_bytes=len(capture.source_text.encode()),
        ),
        *(
            FileObservation(
                reference="native_chain.input",
                path=item.pin.path,
                sha256=item.pin.sha256,
                size_bytes=item.pin.size,
            )
            for item in capture.input_files
        ),
    )
    admission = NativeChainAdmission(
        request_digest=digest(submission),
        capture_sha256=request.capture_sha256,
        workspace=str(run.workspace),
        final_iteration=run.final_iteration,
        run_name=run.run_name,
        recipe=capture.declaration.recipe,
        checkout=str(checkout),
        git_directory=_git_directory(checkout, "--absolute-git-dir"),
        git_common_directory=_git_directory(checkout, "--git-common-dir"),
        required_environment_names=policy.required_names,
        input_files=files,
    )
    profile = sandbox_profile(request, admission)
    state = canonical(config.state_root)
    for root in (*profile.read_only, *runtime_roots()):
        if overlap(envelope, root) or overlap(state, root):
            raise OperationFailure(
                "path", "chain mounts overlap writable envelope or operation state"
            )
    # Admission is also the fixed-size terminal identity budget; no captured bytes are copied.
    if (
        len(encode(admission)) + len(encode(submission)) + request.max_observation_bytes + 65536
        > JSON_LIMIT
    ):
        raise OperationFailure("record_size", "chain terminal metadata exceeds control budget")
    return admission


def review_native_chain_operation(
    config: OperationStoreConfig,
    submission: NativeChainOperation,
    *,
    launch_environment: Mapping[str, str] | None = None,
) -> NativeChainAdmission:
    """Public bounded refusal; subprocess exceptions may contain scientific argv."""
    try:
        return _review_native_chain_operation(
            config, submission, launch_environment=launch_environment
        )
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise OperationFailure(
            "native_chain_admission", "native chain capture or launch binding refused"
        ) from error


def _fence(record: OperationRecord) -> None:
    assert record.submission.kind == "native_chain"
    request = record.submission.request
    envelope = canonical(request.envelope)
    require_empty(envelope)
    path = envelope / ".native-chain-operation"
    with directory(envelope) as descriptor:
        os.mkdir(path.name, mode=0o700, dir_fd=descriptor)
    fence = NativeChainFence(
        operation_id=record.submission.request_id,
        request_digest=record.request_digest,
        capture_sha256=request.capture_sha256,
        envelope=request.envelope,
    )
    publish(path / "binding.json", fence)
    require_empty(envelope, claimed=True)
    if read_model(path / "binding.json", NativeChainFence, private_file=True) != fence:
        raise OperationFailure("claim", "native envelope claim changed")


def execute_native_chain(record: OperationRecord, path: Path) -> Completion:
    """Fence first, then native shell; host terminal never enters sandbox mounts."""
    assert record.submission.kind == "native_chain"
    entered = False
    try:
        fresh = review_native_chain_operation(
            record.config, record.submission, launch_environment=os.environ
        )
        if fresh != record.native_chain_admission:
            raise OperationFailure("capture", "native admission changed")
        capture = captured(record.submission.request)
        profile = sandbox_profile(record.submission.request, fresh)
        _fence(record)
        argv = [
            "/bin/bash",
            "-c",
            'cd -- "$1" && shift && exec /bin/bash "$@"',
            "native-chain",
            fresh.checkout,
            str(Path(fresh.checkout) / "scripts/launch/run_chain.sh"),
            *shell_arguments(record.submission.request, capture),
        ]
        entered = True
        try:
            supervision = run_observed(profile, argv)
        except ObservedSpawnFailure:
            entered = False
            raise
        return publish_chain_terminal(record, path, supervision)
    except (Exception, KeyboardInterrupt):
        return Completion(
            operation_id=record.submission.request_id,
            request_digest=record.request_digest,
            outcome="unknown" if entered else "pre_dispatch_failure",
            reason="native_chain_supervision_unresolved"
            if entered
            else "native_chain_admission_failed",
        )


def publish_chain_terminal(
    record: OperationRecord, path: Path, supervision: ObservedExecutionResult
) -> Completion:
    request, fresh = chain_context(record)
    terminal = NativeChainTerminal(
        operation_id=record.submission.request_id,
        request_digest=record.request_digest,
        capture_sha256=fresh.capture_sha256,
        envelope=request.envelope,
        workspace=fresh.workspace,
        runtime_digest=hashlib.sha256(encode(record.runtime)).hexdigest(),
        supervision=supervision,
        observation_policy=CURRENT_OBSERVATION_POLICY,
        evidence=chain_evidence(record),
    )
    payload = encode(terminal)
    publish(path / "native-chain-terminal.json", terminal)
    return Completion(
        operation_id=record.submission.request_id,
        request_digest=record.request_digest,
        outcome="native_chain",
        terminal_digest=hashlib.sha256(payload).hexdigest(),
        reason="native_chain_terminal",
    )
