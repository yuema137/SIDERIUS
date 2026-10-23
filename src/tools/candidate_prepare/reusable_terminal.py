"""Inert terminal identity checks against admission, never fresh launch eligibility."""

import hashlib
from pathlib import Path
from uuid import UUID

from .admission import canonical
from .models import CandidatePreparationReceipt
from .reusable_admission import captured_request
from .reusable_models import (
    ReusableBindingCapture,
    ReusableCandidatePreparationRequest,
    ReusablePreparationControl,
    ReusablePreparationObservations,
    ReusablePreparationReceipt,
)
from .reusable_selection import CapturedBytes, captured_plan


def _binding(
    request: ReusableCandidatePreparationRequest,
    observations: ReusablePreparationObservations,
    receipt: ReusablePreparationReceipt,
    envelope: Path,
    reader: CapturedBytes,
) -> ReusableBindingCapture:
    payload = reader(envelope / "binding.json")
    if hashlib.sha256(payload).hexdigest() != receipt.binding_sha256:
        raise ValueError("terminal binding digest mismatch")
    binding = ReusableBindingCapture.model_validate_json(payload)
    if (
        binding.run_id != request.run_id
        or binding.envelope != str(envelope)
        or binding.project_root != request.project_root
        or binding.snapshot_path != str(envelope / "workflow.py.snapshot")
        or binding.original_source.path != request.source_path
        or binding.original_source.sha256 != request.expected_source_sha256
        or ReusablePreparationObservations.from_binding(binding) != observations
    ):
        raise ValueError("terminal binding differs from admitted reusable capture")
    plan, _ = captured_plan(envelope, binding, reader)
    if binding.request != captured_request(request, plan.document, binding.locations):
        raise ValueError("terminal native request differs from admitted parameters and source")
    return binding


def _native(
    receipt: ReusablePreparationReceipt,
    binding: ReusableBindingCapture,
    invocation_id: UUID,
    reader: CapturedBytes,
) -> None:
    output = Path(binding.envelope) / "inputs"
    directory = output / "preparation"
    try:
        payload = reader(directory / "request.json")
    except FileNotFoundError:
        control = None
    else:
        control = ReusablePreparationControl.model_validate_json(payload)
        if (
            control.preparation_id != invocation_id
            or control.request != binding.request
            or control.sources != binding.sources
            or control.binding_path != receipt.binding_path
            or control.binding_sha256 != receipt.binding_sha256
        ):
            raise ValueError("terminal control identity mismatch")
    try:
        payload = reader(directory / "receipt.json")
    except FileNotFoundError:
        if receipt.preparation_receipt_path is not None or receipt.status != "failed":
            raise ValueError("terminal receipt references missing native evidence") from None
        return  # Explicit failure before native receipt publication; any control was checked.
    native = CandidatePreparationReceipt.model_validate_json(payload)
    if (
        control is None
        or receipt.preparation_receipt_path != str(directory / "receipt.json")
        or native.preparation_id != invocation_id
        or native.output_dir != str(output)
        or native.request_path != str(directory / "request.json")
        or native.log_path != str(directory / "worker.log")
        or native.source_observations != binding.sources
        or native.status != receipt.status
        or native.error != receipt.error
    ):
        raise ValueError("terminal native receipt identity or outcome mismatch")
    if receipt.status == "prepared" and (
        native.candidate_request_path != str(output / "candidate_request.json")
        or native.preview_path != str(output / "preview.json")
        or native.interpretation_path != str(output / "interpretation.json")
        or native.proposal_path != str(output / "proposal.json")
        or native.composition_fingerprint is None
    ):
        raise ValueError("prepared native receipt lacks fixed artifact references")


def read_reusable_terminal(
    request: ReusableCandidatePreparationRequest,
    observations: ReusablePreparationObservations,
    invocation_id: UUID,
    *,
    expected_receipt_sha256: str | None = None,
) -> tuple[ReusablePreparationReceipt, str] | None:
    """Read fixed capture files only; missing top receipt never implies completion.

    This authenticates retained identity and terminal consistency, not current
    task/config inputs or launch eligibility. Selection still uses the full verifier.
    """
    envelope = canonical(str(Path(request.runs_root) / str(request.run_id)))
    reader = CapturedBytes()
    try:
        payload = reader(envelope / "receipt.json")
    except FileNotFoundError:
        if expected_receipt_sha256 is not None:
            raise ValueError("completed top receipt vanished") from None
        return None
    digest = hashlib.sha256(payload).hexdigest()
    if expected_receipt_sha256 is not None and digest != expected_receipt_sha256:
        raise ValueError("completed top receipt changed")
    receipt = ReusablePreparationReceipt.model_validate_json(payload)
    if (
        receipt.preparation_id != invocation_id
        or receipt.run_id != request.run_id
        or receipt.envelope != str(envelope)
        or receipt.binding_path != str(envelope / "binding.json")
    ):
        raise ValueError("terminal reusable invocation identity mismatch")
    binding = _binding(request, observations, receipt, envelope, reader)
    _native(receipt, binding, invocation_id, reader)
    if receipt.status == "prepared":
        if receipt.error is not None or receipt.candidate_request_path != str(
            envelope / "inputs/candidate_request.json"
        ):
            raise ValueError("prepared top receipt lacks artifact references")
        for name, expected in (
            ("candidate_request.json", receipt.candidate_request_sha256),
            ("preview.json", receipt.preview_sha256),
        ):
            if (
                expected is None
                or hashlib.sha256(reader(envelope / "inputs" / name)).hexdigest() != expected
            ):
                raise ValueError("prepared artifact digest mismatch")
    return receipt, digest
