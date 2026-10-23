"""Explicit native selections for operation tests."""

from uuid import uuid4

import pytest

from tests.unit.tools.candidate_prepare.conftest import selection
from tools.candidate_operations import OperationStoreConfig, PrepareOperation
from tools.candidate_operations.models import OperationRecord, RuntimeIdentity
from tools.candidate_operations.store import digest, now


@pytest.fixture
def admitted(selection, tmp_path):
    config = OperationStoreConfig(
        state_root=str(tmp_path / "state"),
        preparation_roots=(str(tmp_path),),
        candidate_roots=(str(tmp_path),),
    )
    submission = PrepareOperation(request_id=uuid4(), request=selection)
    record = OperationRecord(
        submission=submission,
        request_digest=digest(submission),
        config=config,
        runtime=RuntimeIdentity(
            executable="test",
            resolved_executable="test",
            environment="test",
            source="test",
            revision=None,
        ),
        inputs=(),
        admitted_at=now(),
    )
    return config, submission, record
