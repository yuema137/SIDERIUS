"""Operation list: newest first, bounded, and honest about records it cannot verify."""

import os
from uuid import uuid4

import pytest

from tools.candidate_operations import list_operations
from tools.candidate_operations.models import OperationFailure
from tools.candidate_operations.store import claim, digest, locked_store


def admit(config, submission, record, admitted_at: str, run_name: str):
    """Claim one more immutable record; each carries its own UUID and admission time."""
    request = submission.request.model_copy(update={"run_name": run_name})
    changed = submission.model_copy(update={"request_id": uuid4(), "request": request})
    record = record.model_copy(
        update={
            "submission": changed,
            "request_digest": digest(changed),
            "admitted_at": admitted_at,
        }
    )
    with locked_store(config) as root:
        claim(root, record)
    return changed.request_id


def test_newest_first_bounded_and_named(admitted):
    """Fails if ordering follows UUID/directory order or the limit is ignored."""
    config, submission, record = admitted
    # UUIDs are random, so admission time is the only ordering signal.
    old = admit(config, submission, record, "2026-01-01T00:00:00+00:00", "first")
    new = admit(config, submission, record, "2026-03-01T00:00:00+00:00", "third")
    middle = admit(config, submission, record, "2026-02-01T00:00:00+00:00", "second")
    listing = list_operations(config, limit=2)
    assert [e.snapshot.operation_id for e in listing.entries] == [new, middle]
    assert [e.run_name for e in listing.entries] == ["third", "second"]
    assert listing.examined == 3 and listing.unreadable == 0 and not listing.incomplete
    assert [e.snapshot.operation_id for e in list_operations(config).entries][-1] == old
    with pytest.raises(OperationFailure):
        list_operations(config, limit=0)
    with pytest.raises(OperationFailure):
        list_operations(config, limit=201)


def test_unverifiable_records_are_counted_not_listed(admitted):
    """Fails if a corrupt or foreign directory is guessed into a row or aborts the list."""
    config, submission, record = admitted
    good = admit(config, submission, record, "2026-01-01T00:00:00+00:00", "good")
    operations = config.state_root + "/operations"
    corrupt = os.path.join(operations, str(uuid4()))
    os.mkdir(corrupt, 0o700)
    with open(os.path.join(corrupt, "request.json"), "w") as handle:
        handle.write("{not json")
    os.chmod(os.path.join(corrupt, "request.json"), 0o600)
    os.mkdir(os.path.join(operations, "not-a-uuid"), 0o700)
    listing = list_operations(config)
    assert [e.snapshot.operation_id for e in listing.entries] == [good]
    assert listing.unreadable == 2 and listing.examined == 3


def test_absent_store_lists_nothing_without_creating_it(admitted):
    """Fails if listing creates operation state (it must remain read-only)."""
    config, _, _ = admitted
    listing = list_operations(config)
    assert listing.entries == () and listing.examined == 0
    assert not os.path.lexists(config.state_root)
