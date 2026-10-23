"""One optional source field cannot invalidate legacy operation identities."""

from pathlib import Path
from uuid import UUID

from tools.candidate_operations import CandidateOperation
from tools.candidate_operations.store import digest
from tools.candidate_worker.models import CandidateRunRequest


def test_pre_source_canonical_digest_is_unchanged():
    """Pinned canonical pre-field bytes catch accidental global exclude_none changes."""
    payload = (
        Path(__file__).resolve().parents[3] / "fixtures/candidate_operations/legacy-request.json"
    ).read_bytes()
    request = CandidateRunRequest.model_validate_json(payload)
    assert request.workflow_source is None
    submission = CandidateOperation(request_id=UUID(int=1), request=request)
    assert digest(submission) == "13a9163e2bff3294324753a29377a14310d7de7eeecb5f8fe2e293556d80fd63"
