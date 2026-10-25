"""Authenticate the native shell's controlled resume projection before any writes."""

import os
from uuid import UUID

from core.native_writer.ownership import TRANSPORT_ENV, inherit

from .check import load_capture
from .models import NativeChainCaptureReference, NativeChainRefusal
from .resume_checks import read_reservation, verify_adoption, verify_baseline
from .resume_entry import resume_arguments, verify_capture_reservation


def admit_resume(reference: NativeChainCaptureReference, argv: tuple[str, ...]) -> None:
    capture = load_capture(reference)
    controls = {}
    for name in (
        "--chain_resume_predecessor",
        "--chain_resume_successor",
        "--chain_resume_reservation_sha256",
    ):
        if argv.count(name) != 1:
            raise NativeChainRefusal("resume_controls_changed")
        index = argv.index(name)
        if index + 1 == len(argv):
            raise NativeChainRefusal("resume_controls_changed")
        controls[name] = argv[index + 1]
    payload = os.environ.get(TRANSPORT_ENV)
    if payload is None:
        raise NativeChainRefusal("resume_writer_required")
    lease = inherit(capture.declaration.run.workspace, payload)
    try:
        digest = controls["--chain_resume_reservation_sha256"]
        reservation = read_reservation(
            lease.state,
            UUID(controls["--chain_resume_predecessor"]),
            UUID(controls["--chain_resume_successor"]),
            digest,
        )
        verify_capture_reservation(capture, reference, reservation)
        verify_adoption(lease.state, reservation, digest)
        if lease.claim is None or lease.claim.claim_id != reservation.claim_id:
            raise NativeChainRefusal("resume_claim_changed")
        if argv != resume_arguments(capture, reference, reservation, digest):
            raise NativeChainRefusal("resume_arguments_changed")
        verify_baseline(
            capture.declaration.run.workspace, capture.declaration.run.run_name, reservation
        )
    finally:
        lease.close(clean=False)
