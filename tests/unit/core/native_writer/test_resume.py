"""Adoption cannot replay, release an old claim implicitly, or bypass a live writer."""

import hashlib
from uuid import uuid4

import pytest

from core.native_writer.models import Claim, Participation, WriterRefusal
from core.native_writer.ownership import acquire, inherit
from core.native_writer.resume import (
    adopt_reserved_writer,
    adoption_name,
    locked_registered_writer,
    reservation_name,
)
from core.native_writer.resume_models import ResumeReservation
from core.native_writer.state import WriterState

DIGEST = "a" * 64


def reservation(snapshot):
    return ResumeReservation(
        state_root="/external/store",
        store_digest=DIGEST,
        root_operation_id=uuid4(),
        predecessor_operation_id=uuid4(),
        successor_operation_id=uuid4(),
        successor_request_digest=DIGEST,
        claim_id=uuid4(),
        predecessor_completion_digest=DIGEST,
        baseline_operation_id=uuid4(),
        baseline_terminal_digest=DIGEST,
        capture_sha256=DIGEST,
        snapshot_digest=hashlib.sha256(snapshot.model_dump_json().encode()).hexdigest(),
        evidence_digest=DIGEST,
        start_iteration=2,
        final_iteration=2,
        input_max_bytes=4096,
        max_observation_bytes=4096,
    )


def retained_owner(workspace):
    lease = acquire(workspace, capture_sha256=DIGEST)
    assert lease.claim is not None
    lease.state.publish(
        "iteration.active", Participation(claim_id=lease.claim.claim_id, participant_id=uuid4())
    )
    lease.mark_unresolved("process_cleanup")
    claim = lease.claim
    lease.close(clean=False)
    return claim


def test_guard_never_reclaims_and_adoption_transfers_real_description(tmp_path):
    workspace = tmp_path / "run"
    old = retained_owner(workspace)
    with locked_registered_writer(workspace) as guard:
        before = guard.snapshot()
        value = reservation(before)
        guard.state.publish(reservation_name(value.predecessor_operation_id), value)
    with locked_registered_writer(workspace) as guard:
        assert guard.snapshot() == before
        lease = adopt_reserved_writer(guard, before, value)
        try:
            assert lease.claim != old and lease.claim.claim_id == value.claim_id
            assert lease.state.read_bytes("iteration.active") is None
            assert lease.state.read_bytes("unresolved") is None
            with pytest.raises(WriterRefusal, match="writer_active"):
                with locked_registered_writer(workspace):
                    pass
            delegated = inherit(workspace, lease.transport.model_dump_json())
            delegated.close(clean=False)
        finally:
            lease.close(clean=True)
    with locked_registered_writer(workspace) as guard:
        assert guard.snapshot().claim is None
        assert guard.state.read_bytes(adoption_name(value.successor_operation_id)) is not None
        # Even after clean release this UUID can never adopt a second time.
        changed = reservation(guard.snapshot()).model_copy(
            update={
                "predecessor_operation_id": value.predecessor_operation_id,
                "successor_operation_id": value.successor_operation_id,
            }
        )
        with pytest.raises(WriterRefusal, match="resume_reservation_changed"):
            adopt_reserved_writer(guard, guard.snapshot(), changed)
    assert not workspace.exists()


@pytest.mark.parametrize(
    "boundary", ["adoption", "participant", "unresolved", "claim", "new_claim"]
)
def test_interrupted_adoption_retains_single_use_fence(tmp_path, monkeypatch, boundary):
    """Crashing each metadata transition must never permit the same adoption again."""
    workspace = tmp_path / "run"
    retained_owner(workspace)
    with locked_registered_writer(workspace) as guard:
        before = guard.snapshot()
        value = reservation(before)
        guard.state.publish(reservation_name(value.predecessor_operation_id), value)
        publish, remove = WriterState.publish, WriterState.remove

        def crash_publish(state, name, model):
            publish(state, name, model)
            if (boundary == "adoption" and name.startswith("adopted.")) or (
                boundary == "new_claim" and name == "claim.json"
            ):
                raise RuntimeError("injected crash after durable publication")

        def crash_remove(state, name, model):
            remove(state, name, model)
            if name == {
                "participant": "iteration.active",
                "unresolved": "unresolved",
                "claim": "claim.json",
            }.get(boundary):
                raise RuntimeError("injected crash after durable removal")

        with monkeypatch.context() as patch:
            patch.setattr(WriterState, "publish", crash_publish)
            patch.setattr(WriterState, "remove", crash_remove)
            with pytest.raises(RuntimeError, match="injected crash"):
                adopt_reserved_writer(guard, before, value)
        assert guard.state.read_bytes(adoption_name(value.successor_operation_id)) is not None
        with pytest.raises((WriterRefusal, FileExistsError)):
            adopt_reserved_writer(guard, before, value)
    assert not workspace.exists()


def test_changed_snapshot_refuses_before_consuming_reservation(tmp_path):
    workspace = tmp_path / "run"
    retained_owner(workspace)
    with locked_registered_writer(workspace) as guard:
        before = guard.snapshot()
        value = reservation(before)
        guard.state.publish(reservation_name(value.predecessor_operation_id), value)
        assert before.claim is not None
        guard.state.remove("iteration.active", before.participant)
        with pytest.raises(WriterRefusal, match="resume_snapshot_changed"):
            adopt_reserved_writer(guard, before, value)
        assert guard.state.read_bytes(adoption_name(value.successor_operation_id)) is None
        assert guard.state.read("claim.json", Claim) == before.claim
