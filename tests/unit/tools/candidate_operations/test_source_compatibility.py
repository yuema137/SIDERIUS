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


def test_prepare_digest_matches_pre_b2_witness():
    """Fixed baseline at 4131a74d protects prepare-kind hashing from carrier changes."""
    from tools.candidate_operations import PrepareOperation
    from tools.candidate_prepare import CandidatePreparationRequest

    request = CandidatePreparationRequest(
        task_manifest="/legacy/task.yaml",
        data_root="/legacy/data",
        llm_config_file="/legacy/llm.json",
        output_dir="/legacy/inputs",
        candidate_workspace="/legacy/workspace",
        run_name="legacy",
        preparation_timeout_seconds=30.0,
        candidate_timeout_seconds=60.0,
        task_read_only=(),
        candidate_network=False,
        candidate_devices=(),
        candidate_environment_names=(),
    )
    assert (
        digest(PrepareOperation(request_id=UUID(int=1), request=request))
        == "c02f34ed2e6af53125c21f78b72cac4cea4be99937c2a7f6db120d6ce75caa9d"
    )


def test_pre_b2_record_loads_without_rewriting_or_digest_change(tmp_path):
    """Existing request.json without the carrier survives reads; null also preserves identity."""
    import json

    from tools.candidate_operations import OperationStoreConfig
    from tools.candidate_operations.files import read_bytes
    from tools.candidate_operations.models import OperationRecord, RuntimeIdentity
    from tools.candidate_operations.store import claim, load_record, locked_store

    payload = (
        Path(__file__).resolve().parents[3] / "fixtures/candidate_operations/legacy-request.json"
    ).read_bytes()
    request = CandidateRunRequest.model_validate_json(payload)
    config = OperationStoreConfig(
        state_root=str(tmp_path / "state"), preparation_roots=("/",), candidate_roots=("/",)
    )
    submission = CandidateOperation(request_id=UUID(int=1), request=request)
    record = OperationRecord(
        native_id=UUID(int=2),
        submission=submission,
        request_digest="13a9163e2bff3294324753a29377a14310d7de7eeecb5f8fe2e293556d80fd63",
        config=config,
        runtime=RuntimeIdentity(
            executable="test",
            resolved_executable="test",
            environment="test",
            source="test",
            revision=None,
        ),
        inputs=(),
        admitted_at="2026-10-01T00:00:00Z",
    )
    with locked_store(config) as root:
        path = claim(root, record) / "request.json"
    old = json.loads(path.read_bytes())
    old["submission"].pop("reusable_preparation")
    old["submission"]["request"] = json.loads(payload)
    original = json.dumps(old).encode()
    path.write_bytes(original)
    loaded = load_record(config, submission.request_id)
    assert loaded.submission.reusable_preparation is None
    assert (
        loaded.request_digest == "13a9163e2bff3294324753a29377a14310d7de7eeecb5f8fe2e293556d80fd63"
    )
    assert digest(loaded.submission) == loaded.request_digest
    assert read_bytes(path) == original
    assert (
        digest(
            CandidateOperation(request_id=UUID(int=1), request=request, reusable_preparation=None)
        )
        == "13a9163e2bff3294324753a29377a14310d7de7eeecb5f8fe2e293556d80fd63"
    )
