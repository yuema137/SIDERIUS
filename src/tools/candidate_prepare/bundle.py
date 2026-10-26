"""Inert prepared-bundle verification shared by publication and later readers."""

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from tools.candidate_worker.models import CandidateRunRequest
from tools.workflow_preview.models import FileObservation, WorkflowBindings, WorkflowPreviewRequest
from tools.workflow_preview.preview import observe_bindings
from workflows.definition import WorkflowDocument

from .admission import canonical
from .declaration import candidate_document
from .models import (
    NATIVE_FILES,
    CandidatePreparationRequest,
    PreparationControl,
    PreparedArtifacts,
    ProposalIdentity,
)


def verify_bundle(
    control: PreparationControl,
    *,
    read_bytes: Callable[[Path], bytes] = Path.read_bytes,
) -> tuple[CandidateRunRequest, WorkflowBindings, str]:
    """No publication, native imports or workspace admission; callers own safe reads."""
    request = control.request
    output = canonical(request.output_dir)

    def observe(path: Path, reference: str) -> tuple[FileObservation, bytes]:
        payload = read_bytes(path)
        return FileObservation(
            reference=reference,
            path=str(path),
            sha256=hashlib.sha256(payload).hexdigest(),
            size_bytes=len(payload),
        ), payload

    payload = read_bytes(output / "preparation/request.json")
    if PreparationControl.model_validate_json(payload) != control:
        raise ValueError("child changed preparation control")
    index = PreparedArtifacts.model_validate_json(read_bytes(output / "preparation/child.json"))
    if (
        index.preparation_id != control.preparation_id
        or index.control_sha256 != hashlib.sha256(payload).hexdigest()
    ):
        raise ValueError("child index disagrees with preparation identity")
    expected = tuple(observe(canonical(str(output / name)), name)[0] for name in NATIVE_FILES)
    if index.files != expected:
        raise ValueError("child index disagrees with fixed artifact identities")
    identity = ProposalIdentity.model_validate_json(read_bytes(output / "proposal.json"))
    if identity.task_composition_ref.semantic_fingerprint != index.composition_fingerprint:
        raise ValueError("child fingerprint disagrees with native proposal")
    profile, _ = observe(output / "llm.json", "llm_config")
    if (profile.sha256, profile.size_bytes) != (
        control.sources[1].sha256,
        control.sources[1].size_bytes,
    ):
        raise ValueError("saved profile differs from selected bytes")
    document = WorkflowDocument.model_validate_json(read_bytes(output / "workflow.json"))
    if document != candidate_document(request):
        raise ValueError("child changed supported declaration")
    candidate, preview = build_candidate(request, document, observe)
    return candidate, preview, index.composition_fingerprint


def build_candidate(
    request: CandidatePreparationRequest,
    document: WorkflowDocument,
    observe: Callable[[Path, str], tuple[FileObservation, bytes]],
    *,
    execution_profile: Literal[
        "native-proposal-fanout/v1", "native-proposal-families/v1", "native-literature-candidate/v1"
    ]
    | None = None,
) -> tuple[CandidateRunRequest, WorkflowBindings]:
    """Build the existing worker request from parent-verified declaration and observations."""
    output = canonical(request.output_dir)
    preview_request = WorkflowPreviewRequest(
        document=document,
        project_root=str(output),
        llm_config_file="llm.json",
        execution_profile=execution_profile,
    )
    preview = observe_bindings(preview_request, read_file=observe)
    candidate = CandidateRunRequest(
        preview=preview_request,
        declaration_digest=document.definition.declaration_digest(),
        files=preview.files,
        selected_constructor_routes=preview.selected_constructor_routes,
        storage_policy="managed_fresh",
        run_name=request.run_name,
        timeout_seconds=request.candidate_timeout_seconds,
        network=request.candidate_network,
        devices=request.candidate_devices,
        environment_names=request.candidate_environment_names,
        read_only=tuple(
            sorted(
                set(
                    (
                        request.output_dir,
                        request.data_root,
                        request.task_manifest,
                        *request.task_read_only,
                    )
                )
            )
        ),
        implementation_advice=request.implementation_advice,
        validation_advice=request.validation_advice,
    )
    return candidate, preview
