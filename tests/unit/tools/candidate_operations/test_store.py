"""Local admission failure classes; no simulated native execution claims."""

import os
from pathlib import Path
from uuid import uuid4

import pytest

from tests.unit.tools.candidate_prepare.conftest import selection
from tools.candidate_operations import OperationStoreConfig, PrepareOperation
from tools.candidate_operations.files import JSON_LIMIT, read_bytes
from tools.candidate_operations.models import OperationFailure, OperationRecord, RuntimeIdentity
from tools.candidate_operations.store import (
    claim,
    digest,
    existing,
    load_record,
    locked_store,
    now,
    require_available,
    validate_config,
    validate_submission,
)


def test_immutable_idempotency_conflict_and_unknown_slot(admitted):
    """Lost active pointer must not allow another dispatch; same ID retains saved identity."""
    config, submission, record = admitted
    validate_submission(validate_config(config), submission)
    with locked_store(config) as root:
        path = claim(root, record)
        assert existing(config, submission) == record
        changed = submission.model_copy(
            update={"request": submission.request.model_copy(update={"run_name": "other"})}
        )
        with pytest.raises(OperationFailure, match="different content"):
            existing(config, changed)
        (root / "active.json").unlink()
        with pytest.raises(OperationFailure, match="unresolved"):
            require_available(root, lambda _: False)
        assert require_available(root, lambda _: True) is None
        assert path.stat().st_mode & 0o777 == 0o700
        assert (path / "request.json").stat().st_mode & 0o777 == 0o600


def test_permissions_symlink_and_bounded_records(admitted, tmp_path):
    """Publicly readable state and swapped symlink records cannot be trusted."""
    config, _, record = admitted
    with locked_store(config) as root:
        path = claim(root, record)
    os.chmod(root, 0o755)
    with pytest.raises(OperationFailure, match="700"):
        load_record(config, record.submission.request_id)
    os.chmod(root, 0o700)
    saved = path / "request.json"
    saved.unlink()
    saved.symlink_to(tmp_path / "outside")
    with pytest.raises(OSError):
        load_record(config, record.submission.request_id)
    saved.unlink()
    with saved.open("wb") as stream:
        stream.truncate(JSON_LIMIT + 1)
    with pytest.raises(OperationFailure, match="4 MiB"):
        read_bytes(saved)


def test_boundaries_are_checked_before_store_effects(admitted):
    """State cannot hide under selected input or use a destination outside allowed roots."""
    config, submission, _ = admitted
    changed = config.model_copy(
        update={"state_root": str(Path(submission.request.data_root) / "state")}
    )
    with pytest.raises(OperationFailure, match="selected inputs"):
        validate_submission(changed, submission)
    changed = config.model_copy(update={"preparation_roots": (submission.request.data_root,)})
    with pytest.raises(OperationFailure, match="outside"):
        validate_submission(changed, submission)
    assert not Path(config.state_root).exists()


def test_reserved_future_environment_is_rejected_without_store(admitted):
    config, submission, _ = admitted
    changed = submission.model_copy(
        update={
            "request": submission.request.model_copy(
                update={"candidate_environment_names": ("PYTHONPATH",)}
            )
        }
    )
    with pytest.raises(ValueError, match="reserved"):
        validate_submission(config, changed)
    assert not Path(config.state_root).exists()
