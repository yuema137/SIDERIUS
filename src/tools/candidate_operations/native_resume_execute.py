"""Reserve one explicit successor, then reuse the observed sandbox/native owners."""

import hashlib
import os
from pathlib import Path

from core.native_writer.resume import adoption_name, locked_registered_writer, reservation_name
from tools.native_chain.resume_checks import verify_baseline
from tools.workspace_sandbox.runner import ObservedSpawnFailure, run_observed

from .models import Completion, OperationRecord
from .native_chain import publish_chain_terminal, sandbox_profile
from .native_resume import review_locked
from .native_resume_models import reservation_for


def execute_native_resume(record: OperationRecord, path: Path) -> Completion:
    admitted = record.native_resume_admission
    assert record.submission.kind == "native_chain_resume" and admitted is not None
    request = admitted.root_request
    reservation = reservation_for(
        admitted, record.submission.request_id, record.native_id, record.request_digest
    )
    uncertain = False
    try:
        workspace = Path(admitted.root_admission.workspace)
        with locked_registered_writer(workspace) as guard:
            reviewed = review_locked(
                record.config,
                admitted.predecessor_operation_id,
                guard,
                launch_environment=os.environ,
            )
            if reviewed.admission != admitted or reviewed.eligibility != "ready":
                raise ValueError("resume_review_changed")
            name = reservation_name(admitted.predecessor_operation_id)
            if guard.state.read_bytes(name) is not None:
                raise ValueError("resume_predecessor_reserved")
            uncertain = True  # publication may succeed before an fsync/error reaches us
            guard.state.publish(name, reservation)
            raw = guard.state.read_bytes(name)
            assert raw is not None
            reservation_digest = hashlib.sha256(raw).hexdigest()
        argv = [
            "/bin/bash",
            "-c",
            'cd -- "$1" && shift && exec "$@"',
            "native-resume",
            admitted.root_admission.checkout,
            record.runtime.executable,
            "-m",
            "tools.native_chain.resume_entry",
            "--capture",
            request.capture_path,
            "--sha256",
            request.capture_sha256,
            "--input-max-bytes",
            str(request.input_max_bytes),
            "--predecessor",
            str(admitted.predecessor_operation_id),
            "--successor",
            str(record.submission.request_id),
            "--reservation-sha256",
            reservation_digest,
        ]
        try:
            supervision = run_observed(sandbox_profile(request, admitted.root_admission), argv)
        except ObservedSpawnFailure:
            with locked_registered_writer(workspace) as guard:
                if (
                    guard.state.read_bytes(name) != raw
                    or guard.state.read_bytes(adoption_name(record.submission.request_id))
                    is not None
                    or guard.snapshot() != admitted.owner
                ):
                    raise ValueError("resume_spawn_failure_uncertain") from None
                verify_baseline(workspace, admitted.root_admission.run_name, reservation)
            return Completion(
                operation_id=record.submission.request_id,
                request_digest=record.request_digest,
                outcome="pre_dispatch_failure",
                reason="native_resume_spawn_failed",
            )
        return publish_chain_terminal(record, path, supervision)
    except (Exception, KeyboardInterrupt):
        return Completion(
            operation_id=record.submission.request_id,
            request_digest=record.request_digest,
            outcome="unknown" if uncertain else "pre_dispatch_failure",
            reason="native_resume_supervision_unresolved"
            if uncertain
            else "native_resume_admission_failed",
        )
