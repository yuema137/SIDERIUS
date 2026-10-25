"""Read-only append-boundary checks shared by host admission and native adoption."""

import hashlib
import os
from pathlib import Path
from uuid import UUID

from core.iteration_manifest import restorable_manifest_status
from core.native_writer.models import WriterRefusal
from core.native_writer.resume import adoption_name, reservation_name
from core.native_writer.resume_models import ResumeAdoption, ResumeReservation
from core.native_writer.state import WriterState

from .inspection import next_chain_index
from .models import NativeChainRefusal
from .observation import NativeChainEvidence, ObservationBounds, observe_native_chain


def evidence_digest(evidence: NativeChainEvidence) -> str:
    return hashlib.sha256(evidence.model_dump_json().encode()).hexdigest()


def append_boundary(workspace: Path, evidence: NativeChainEvidence, final: int) -> int:
    """No mutation or plugin loading; existing native restoration has the final say."""
    if (
        evidence.availability != "available"
        or evidence.anomalies
        or not evidence.token_run_id
        or evidence.token_sidecar_sha256 is None
    ):
        raise NativeChainRefusal("resume_baseline_unverified")
    for marker in ("STOP", "chain_stopped.json", ".chain_halted"):
        if os.path.lexists(workspace / marker):
            raise NativeChainRefusal("resume_stop_state")
    rows = evidence.checkpoints
    # Missing entries are absent only if no directory exists, including empty slots.
    existing = [row for row in rows if os.path.lexists(workspace / f"iter_{row.iteration:03d}")]
    if not existing or [r.iteration for r in existing] != list(range(1, len(existing) + 1)):
        raise NativeChainRefusal("resume_prefix_required")
    if any(
        r.integrity != "verified" or not restorable_manifest_status(r.native_status)
        for r in existing
    ):
        raise NativeChainRefusal("resume_prefix_unrestorable")
    committed = [r.iteration for r in existing if r.native_status == "completed"]
    if not committed:
        raise NativeChainRefusal("resume_completed_prefix_required")
    start = next_chain_index(committed)
    if start != len(existing) + 1:
        raise NativeChainRefusal("resume_existing_slot_unsupported")
    if start > final:
        return start
    if any(os.path.lexists(workspace / f"iter_{index:03d}") for index in range(start, final + 1)):
        raise NativeChainRefusal("resume_existing_slot_unsupported")
    return start


def read_reservation(
    state: WriterState, predecessor: UUID, successor: UUID, expected_digest: str
) -> ResumeReservation:
    raw = state.read_bytes(reservation_name(predecessor))
    if raw is None or hashlib.sha256(raw).hexdigest() != expected_digest:
        raise WriterRefusal("resume_reservation_changed")
    value = ResumeReservation.model_validate_json(raw)
    if value.predecessor_operation_id != predecessor or value.successor_operation_id != successor:
        raise WriterRefusal("resume_reservation_changed")
    return value


def verify_baseline(workspace: Path, run_name: str, reservation: ResumeReservation) -> None:
    evidence = observe_native_chain(
        workspace,
        run_name,
        ObservationBounds(
            final_iteration=reservation.final_iteration,
            input_max_bytes=reservation.input_max_bytes,
            max_observation_bytes=reservation.max_observation_bytes,
        ),
        policy=reservation.observation_policy,
    )
    if (
        evidence_digest(evidence) != reservation.evidence_digest
        or append_boundary(workspace, evidence, reservation.final_iteration)
        != reservation.start_iteration
    ):
        raise NativeChainRefusal("resume_baseline_changed")


def verify_adoption(state: WriterState, reservation: ResumeReservation, digest: str) -> None:
    expected = ResumeAdoption(
        reservation_digest=digest,
        operation_id=reservation.successor_operation_id,
        claim_id=reservation.claim_id,
    )
    if state.read(adoption_name(reservation.successor_operation_id), ResumeAdoption) != expected:
        raise WriterRefusal("resume_adoption_changed")
