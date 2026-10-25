"""Internal captured-resume entry; adopts once then runs the existing native shell."""

import argparse
import hashlib
import sys
from pathlib import Path
from uuid import UUID

from core.native_writer.launch import run_shell_with_lease
from core.native_writer.models import WriterRefusal
from core.native_writer.resume import adopt_reserved_writer, locked_registered_writer
from core.native_writer.resume_models import ResumeReservation
from tools.candidate_operations.files import read_model
from tools.candidate_operations.native_chain_models import NativeChainFence

from .check import CHECK_ERRORS, load_capture, print_refusal
from .models import NativeChainCapture, NativeChainCaptureReference, NativeChainRefusal
from .resume_checks import read_reservation, verify_baseline


def resume_arguments(
    capture: NativeChainCapture,
    reference: NativeChainCaptureReference,
    reservation: ResumeReservation,
    reservation_digest: str,
) -> tuple[str, ...]:
    return (
        *capture.declaration.shell_arguments(start_iteration=reservation.start_iteration),
        "--expected_chain_capture",
        str(reference.path),
        "--expected_chain_capture_sha256",
        reference.sha256,
        "--chain_capture_input_max_bytes",
        str(reference.input_max_bytes),
        "--chain_resume_predecessor",
        str(reservation.predecessor_operation_id),
        "--chain_resume_successor",
        str(reservation.successor_operation_id),
        "--chain_resume_reservation_sha256",
        reservation_digest,
    )


def verify_capture_reservation(
    capture: NativeChainCapture, reference: NativeChainCaptureReference, value: ResumeReservation
) -> None:
    run = capture.declaration.run
    fence = read_model(
        run.workspace.parent / ".native-chain-operation/binding.json",
        NativeChainFence,
        private_file=True,
    )
    if (
        value.capture_sha256 != reference.sha256
        or value.final_iteration != run.final_iteration
        or value.input_max_bytes != reference.input_max_bytes
        or value.start_iteration > value.final_iteration
        or fence.operation_id != value.root_operation_id
        or fence.capture_sha256 != reference.sha256
        or fence.envelope != str(run.workspace.parent)
    ):
        raise NativeChainRefusal("resume_capture_changed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", required=True, type=Path)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--input-max-bytes", required=True, type=int)
    parser.add_argument("--predecessor", required=True, type=UUID)
    parser.add_argument("--successor", required=True, type=UUID)
    parser.add_argument("--reservation-sha256", required=True)
    args = parser.parse_args()
    try:
        reference = NativeChainCaptureReference(
            path=args.capture, sha256=args.sha256, input_max_bytes=args.input_max_bytes
        )
        capture = load_capture(reference)
        workspace = capture.declaration.run.workspace
        with locked_registered_writer(workspace) as guard:
            value = read_reservation(
                guard.state, args.predecessor, args.successor, args.reservation_sha256
            )
            verify_capture_reservation(capture, reference, value)
            before = guard.snapshot()
            if (
                hashlib.sha256(before.model_dump_json().encode()).hexdigest()
                != value.snapshot_digest
            ):
                raise NativeChainRefusal("resume_snapshot_changed")
            verify_baseline(workspace, capture.declaration.run.run_name, value)
            argv = (
                "/bin/bash",
                str(capture.declaration.working_directory / "scripts/launch/run_chain.sh"),
                *resume_arguments(capture, reference, value, args.reservation_sha256),
            )
            lease = adopt_reserved_writer(guard, before, value)
            return run_shell_with_lease(lease, argv)
    except (*CHECK_ERRORS, WriterRefusal) as error:
        if isinstance(error, WriterRefusal):
            print("Native resume refused: writer_state_refused", file=sys.stderr)
        else:
            print_refusal(error)
        return 78


if __name__ == "__main__":
    raise SystemExit(main())
