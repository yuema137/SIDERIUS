"""Read-only retained selection verification; no allocation, task imports or launch."""

import hashlib
from pathlib import Path
from uuid import UUID

from tools.candidate_worker.models import CandidateRunRequest
from tools.workflow_preview.models import FileObservation, WorkflowPreview
from workflows.definition import ReusableWorkflowDocument, parse_workflow_source
from workflows.definition.source import MAX_INPUT_BYTES

from .admission import canonical, verify_sources
from .models import CandidatePreparationReceipt
from .resolution import resolve_reusable_candidate
from .reusable_admission import observation, reusable_locations, safe_bytes
from .reusable_models import (
    ReusableBindingCapture,
    ReusablePreparationControl,
    ReusablePreparationPlan,
    ReusablePreparationReceipt,
    ReusablePreparedSelection,
    VerifiedReusablePreparation,
)
from .reusable_verify import verify_reusable_bundle


class CapturedBytes:
    """One bounded read per path in one pass; never shared across launch boundaries."""

    def __init__(self) -> None:
        self._payloads: dict[Path, bytes] = {}

    def __call__(self, path: Path) -> bytes:
        if path not in self._payloads:
            self._payloads[path] = safe_bytes(path)
        return self._payloads[path]

    def observe(self, path: Path, reference: str) -> tuple[FileObservation, bytes]:
        payload = self(path)
        return observation(path, reference, payload), payload


def _hashed(reader: CapturedBytes, path: Path, expected: str | None) -> bytes:
    payload = reader(path)
    if expected is None or hashlib.sha256(payload).hexdigest() != expected:
        raise ValueError(f"retained preparation digest mismatch: {path.name}")
    return payload


def _plan(
    envelope: Path, receipt: ReusablePreparationReceipt, reader: CapturedBytes
) -> tuple[ReusablePreparationPlan, bytes]:
    binding = ReusableBindingCapture.model_validate_json(
        _hashed(reader, envelope / "binding.json", receipt.binding_sha256)
    )
    if (
        binding.run_id != receipt.run_id
        or binding.envelope != str(envelope)
        or binding.snapshot_path != str(envelope / "workflow.py.snapshot")
        or binding.request.output_dir != str(envelope / "inputs")
        or binding.request.candidate_workspace != str(envelope / "workspace")
    ):
        raise ValueError("binding disagrees with fixed envelope identity or destinations")
    source = reader(envelope / "workflow.py.snapshot")
    if len(source) > MAX_INPUT_BYTES:
        raise ValueError("captured source exceeds source limit")
    original = binding.original_source
    if observation(canonical(original.path), "workflow.source", source) != original:
        raise ValueError("snapshot differs from captured original observation")
    document = parse_workflow_source(source.decode("utf-8"))
    if not isinstance(document, ReusableWorkflowDocument):
        raise ValueError("captured source must be reusable v2")
    if document.declaration_digest() != binding.reusable_semantic_digest:
        raise ValueError("captured reusable semantic identity differs")
    locations = reusable_locations(document, canonical(binding.project_root), envelope)
    if (
        locations != binding.locations
        or binding.request.task_manifest != locations.manifest
        or binding.request.data_root != locations.data_root
    ):
        raise ValueError("captured locations differ from original task and fixed layout")
    resolved = resolve_reusable_candidate(document, locations)
    return ReusablePreparationPlan(
        binding=binding, document=document, resolved_document=resolved.document
    ), source


def _verify(
    selection: ReusablePreparedSelection, reader: CapturedBytes
) -> VerifiedReusablePreparation:
    envelope = canonical(selection.envelope)
    run_id = UUID(envelope.name)
    if str(run_id) != envelope.name:
        raise ValueError("envelope must have canonical UUID name")
    receipt = ReusablePreparationReceipt.model_validate_json(
        _hashed(reader, envelope / "receipt.json", selection.expected_receipt_sha256)
    )
    output = envelope / "inputs"
    if (
        receipt.status != "prepared"
        or receipt.run_id != run_id
        or receipt.envelope != str(envelope)
        or receipt.binding_path != str(envelope / "binding.json")
        or receipt.preparation_receipt_path != str(output / "preparation/receipt.json")
        or receipt.candidate_request_path != str(output / "candidate_request.json")
        or receipt.candidate_request_sha256 is None
        or receipt.preview_sha256 is None
        or receipt.error is not None
    ):
        raise ValueError("receipt is not a complete prepared selection at fixed paths")
    plan, source = _plan(envelope, receipt, reader)
    control = ReusablePreparationControl.model_validate_json(
        reader(output / "preparation/request.json")
    )
    if (
        control.request != plan.binding.request
        or control.sources != plan.binding.sources
        or control.binding_path != receipt.binding_path
        or control.binding_sha256 != receipt.binding_sha256
    ):
        raise ValueError("saved preparation control disagrees with pinned binding")
    verify_sources(control, read_file=reader.observe)
    expected, bindings, fingerprint = verify_reusable_bundle(
        plan, source, control, read_bytes=reader
    )
    candidate = CandidateRunRequest.model_validate_json(
        _hashed(reader, output / "candidate_request.json", receipt.candidate_request_sha256)
    )
    if candidate != expected:
        raise ValueError("published candidate request differs from independently verified inputs")
    preview = WorkflowPreview.model_validate_json(
        _hashed(reader, output / "preview.json", receipt.preview_sha256)
    )
    if preview != WorkflowPreview(**bindings.model_dump(), workspace_state="absent"):
        raise ValueError("published preparation preview differs from verified bindings")
    # Diagnostic native receipt is checked for consistency, not independently authenticated.
    native = CandidatePreparationReceipt.model_validate_json(
        reader(output / "preparation/receipt.json")
    )
    if native != CandidatePreparationReceipt(
        preparation_id=control.preparation_id,
        status="prepared",
        output_dir=str(output),
        request_path=str(output / "preparation/request.json"),
        log_path=str(output / "preparation/worker.log"),
        candidate_request_path=str(output / "candidate_request.json"),
        preview_path=str(output / "preview.json"),
        interpretation_path=str(output / "interpretation.json"),
        proposal_path=str(output / "proposal.json"),
        composition_fingerprint=fingerprint,
        source_observations=control.sources,
    ):
        raise ValueError("native receipt disagrees with verified preparation")
    return VerifiedReusablePreparation(
        selection=selection,
        request=candidate,
        binding=plan.binding,
        receipt=receipt,
        preparation_id=control.preparation_id,
        composition_fingerprint=fingerprint,
    )


def verify_reusable_preparation(
    selection: ReusablePreparedSelection,
) -> VerifiedReusablePreparation:
    """Verify a caller-retained receipt identity with fresh bounded reads and no writes."""
    selection = ReusablePreparedSelection.model_validate_json(selection.model_dump_json())
    return _verify(selection, CapturedBytes())


def select_reusable_preparation(envelope: str) -> ReusablePreparedSelection:
    """Select current published bytes; retain the result outside the mutable envelope.

    This is an explicit current-file selection, not historical authentication or
    reconstruction of the original publication event. Operations enforce root policy.
    """
    reader = CapturedBytes()
    path = canonical(envelope)
    selection = ReusablePreparedSelection(
        envelope=str(path),
        expected_receipt_sha256=hashlib.sha256(reader(path / "receipt.json")).hexdigest(),
    )
    _verify(selection, reader)
    return selection
