"""Public confined access to a fully bound prepared native candidate request."""

import hashlib
from pathlib import Path
from uuid import UUID

from tools.candidate_prepare.bundle import verify_bundle
from tools.candidate_prepare.models import CandidatePreparationReceipt, PreparationControl
from tools.candidate_worker.models import CandidateRunRequest

from .files import read_bytes, read_model
from .models import OperationFailure, OperationStoreConfig, PreparedCandidate
from .read import read_operation
from .store import load_record, validate_config


def read_prepared_candidate(config: OperationStoreConfig, operation_id: UUID) -> PreparedCandidate:
    config = validate_config(config)
    record = load_record(config, operation_id)
    snapshot = read_operation(config, operation_id)
    receipt = snapshot.receipt
    if (
        record.submission.kind != "prepare"
        or snapshot.state != "completed"
        or not isinstance(receipt, CandidatePreparationReceipt)
        or receipt.status != "prepared"
    ):
        raise OperationFailure("not_prepared", "operation has no verified prepared candidate")
    request = record.submission.request
    output = Path(request.output_dir)
    if (
        receipt.candidate_request_path != str(output / "candidate_request.json")
        or receipt.preview_path != str(output / "preview.json")
        or receipt.interpretation_path != str(output / "interpretation.json")
        or receipt.proposal_path != str(output / "proposal.json")
    ):
        raise OperationFailure("integrity", "prepared artifact locations changed")
    try:
        control = read_model(output / "preparation/request.json", PreparationControl)
        if (
            control.request != request
            or control.preparation_id != record.native_id
            or control.sources != record.inputs
        ):
            raise ValueError("preparation control changed")
        for source in control.sources:
            current = read_bytes(Path(source.path))
            if (
                len(current) != source.size_bytes
                or hashlib.sha256(current).hexdigest() != source.sha256
            ):
                raise ValueError("selected preparation source changed")
        expected, _, fingerprint = verify_bundle(control, read_bytes=read_bytes)
        payload = read_bytes(output / "candidate_request.json")
        candidate = CandidateRunRequest.model_validate_json(payload)
        if candidate != expected or fingerprint != receipt.composition_fingerprint:
            raise ValueError("prepared request differs from native binding")
    except (OSError, ValueError) as error:
        raise OperationFailure("integrity", "prepared candidate binding failed") from error
    return PreparedCandidate(
        prepare_operation_id=operation_id,
        preparation_request=request,
        request=candidate,
        request_sha256=hashlib.sha256(payload).hexdigest(),
        preparation_id=receipt.preparation_id,
        receipt_sha256=snapshot.receipt_digest,
        composition_fingerprint=fingerprint,
    )
