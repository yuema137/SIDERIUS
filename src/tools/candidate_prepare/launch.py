"""Admission, offline supervision and publication; no native task imports."""

import hashlib
import sys
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, TypeAdapter

from core.durable_io import publish_bytes_write_once
from tools.candidate_worker.models import CandidateRunRequest
from tools.workflow_preview import WorkflowPreviewRequest, preview_workflow
from tools.workflow_preview.files import observe_file
from tools.workspace_sandbox.profile import SandboxProfile
from tools.workspace_sandbox.runner import run
from workflows.definition import WorkflowDocument

from .admission import absent_destination, admit, canonical, verify_sources
from .declaration import candidate_document
from .models import (
    NATIVE_FILES,
    CandidatePreparationReceipt,
    CandidatePreparationRequest,
    PreparationControl,
    PreparedArtifacts,
    ProposalIdentity,
)


def publish(path: Path, model: BaseModel) -> None:
    publish_bytes_write_once(str(path), (model.model_dump_json(indent=2) + "\n").encode())


def reconcile(
    control: PreparationControl, initial: CandidatePreparationReceipt
) -> CandidatePreparationReceipt:
    """Accept only the fixed artifact set bound to this control and native declaration."""
    request = control.request
    output = canonical(request.output_dir)
    canonical(str(output / "preparation"))
    verify_sources(control)
    absent_destination(canonical(request.candidate_workspace))
    payload = (output / "preparation/request.json").read_bytes()
    if PreparationControl.model_validate_json(payload) != control:
        raise ValueError("child changed preparation control")
    index = PreparedArtifacts.model_validate_json((output / "preparation/child.json").read_bytes())
    if (
        index.preparation_id != control.preparation_id
        or index.control_sha256 != hashlib.sha256(payload).hexdigest()
    ):
        raise ValueError("child index disagrees with preparation identity")
    expected = tuple(observe_file(canonical(str(output / name)), name)[0] for name in NATIVE_FILES)
    if index.files != expected:
        raise ValueError("child index disagrees with fixed artifact identities")
    identity = ProposalIdentity.model_validate_json((output / "proposal.json").read_bytes())
    if identity.task_composition_ref.semantic_fingerprint != index.composition_fingerprint:
        raise ValueError("child fingerprint disagrees with native proposal")
    profile, _ = observe_file(output / "llm.json", "llm_config")
    if (profile.sha256, profile.size_bytes) != (
        control.sources[1].sha256,
        control.sources[1].size_bytes,
    ):
        raise ValueError("saved profile differs from selected bytes")
    document = WorkflowDocument.model_validate_json((output / "workflow.json").read_bytes())
    if document != candidate_document(request):
        raise ValueError("child changed supported declaration")
    preview_request = WorkflowPreviewRequest(
        document=document, project_root=str(output), llm_config_file="llm.json"
    )
    preview = preview_workflow(preview_request)
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
    for name, record in (
        ("preview_request.json", preview_request),
        ("preview.json", preview),
        ("candidate_request.json", candidate),
    ):
        publish(output / name, record)
    verify_sources(control)
    absent_destination(canonical(request.candidate_workspace))
    return initial.model_copy(
        update={
            "status": "prepared",
            "composition_fingerprint": index.composition_fingerprint,
            "candidate_request_path": str(output / "candidate_request.json"),
            "preview_path": str(output / "preview.json"),
            "interpretation_path": str(output / "interpretation.json"),
            "proposal_path": str(output / "proposal.json"),
        }
    )


def prepare_candidate(
    request: CandidatePreparationRequest, *, invocation_id: UUID | None = None
) -> CandidatePreparationReceipt:
    """Prepare one fresh bundle; preserve partial files on failure and never launch it."""
    request = CandidatePreparationRequest.model_validate_json(request.model_dump_json())
    identity = (
        uuid4()
        if invocation_id is None
        else TypeAdapter(UUID).validate_python(invocation_id, strict=True)
    )
    captures = admit(request)
    output = Path(request.output_dir)
    control_dir = output / "preparation"
    control = PreparationControl(
        preparation_id=identity, request=request, sources=tuple(item for item, _ in captures)
    )
    initial = CandidatePreparationReceipt(
        preparation_id=control.preparation_id,
        status="failed",
        output_dir=str(output),
        request_path=str(control_dir / "request.json"),
        log_path=str(control_dir / "worker.log"),
        source_observations=control.sources,
    )
    output.mkdir()  # The losing caller must not publish any record.
    try:
        if canonical(str(output)) != output or next(output.iterdir(), None) is not None:
            raise ValueError("output directory changed before exclusive claim")
        absent_destination(canonical(request.candidate_workspace))
        verify_sources(control)
        control_dir.mkdir()
        publish(control_dir / "request.json", control)
        for name, (_, payload) in zip(("manifest.snapshot", "llm.snapshot"), captures, strict=True):
            publish_bytes_write_once(str(control_dir / name), payload)
        profile = SandboxProfile(
            workspace=output,
            read_only=tuple(
                Path(path)
                for path in sorted(
                    set(
                        (
                            request.data_root,
                            request.task_manifest,
                            request.llm_config_file,
                            *request.task_read_only,
                        )
                    )
                )
            ),
            network=False,
            devices=(),
            environment_names=(),
            timeout_seconds=request.preparation_timeout_seconds,
        )
        result = run(
            profile,
            [
                sys.executable,
                "-m",
                "tools.candidate_prepare.child",
                str(control_dir / "request.json"),
            ],
        )
        if result.status == "completed":
            terminal = reconcile(control, initial)
        else:
            terminal = initial.model_copy(
                update={
                    "status": result.status,
                    "error": f"preparation child exit {result.returncode}; inspect worker.log and declared source mounts",
                }
            )
    except KeyboardInterrupt:
        terminal = initial.model_copy(
            update={"status": "interrupted", "error": "preparation interrupted"}
        )
    except Exception as error:
        terminal = initial.model_copy(
            update={"status": "failed", "error": f"{type(error).__name__}: {error}"}
        )
    # Do not follow a replaced control directory when publishing from the parent.
    canonical(str(control_dir))
    publish(control_dir / "receipt.json", terminal)
    return terminal
