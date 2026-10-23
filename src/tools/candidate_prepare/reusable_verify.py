"""Parent verification against retained capture, never child-supplied authority."""

import hashlib
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from agent.schemas.output_types import OutputTypeName
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from tools.candidate_worker.layout import candidate_proposal_dir
from tools.candidate_worker.models import CandidateRunRequest, WorkflowSourceSnapshot
from tools.workflow_preview.models import FileObservation, WorkflowBindings
from workflows.attempt_storage import impl_attempt_storage
from workflows.definition import WorkflowDocument, render_workflow_source

from .bundle import build_candidate
from .models import CompositionIdentity, PreparedArtifacts
from .resolution import resolve_reusable_candidate
from .reusable_admission import observation, safe_bytes
from .reusable_models import ReusablePreparationControl, ReusablePreparationPlan, reusable_files


class AdviceProjection(BaseModel):
    source: str
    kind: str
    content: str
    source_ref: str


class ProposalProjection(BaseModel):
    """Only storage, identity and source-controlled options; native child owns science."""

    task_composition_ref: CompositionIdentity
    storage: StorageConfig
    expert_context: list[AdviceProjection]
    allowed_output_types: tuple[OutputTypeName, ...] | None


def encoded(model: BaseModel) -> bytes:
    return (model.model_dump_json(indent=2) + "\n").encode()


def verify_payloads(
    plan: ReusablePreparationPlan, fingerprint: str, read_bytes: Callable[[Path], bytes]
) -> None:
    request = plan.binding.request
    output = Path(request.output_dir)
    proposal = ProposalProjection.model_validate_json(read_bytes(output / "proposal.json"))
    proposal_dir = candidate_proposal_dir(Path(request.candidate_workspace), request.run_name)
    expected = StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace=str(proposal_dir), run_name=request.run_name),
    )
    if proposal.storage != expected:
        raise ValueError("proposal storage differs from selected native destination")
    storage = StorageConfig.model_validate_json(read_bytes(output / "storage.json"))
    if storage != impl_attempt_storage(str(proposal_dir), request.run_name, 1).storage:
        raise ValueError("attempt storage differs from selected native destination")
    if proposal.task_composition_ref.semantic_fingerprint != fingerprint:
        raise ValueError("child fingerprint disagrees with native proposal")
    advice = (
        [
            AdviceProjection(
                source="human",
                kind="human",
                content=request.proposal_advice,
                source_ref="human:human_advice",
            )
        ]
        if request.proposal_advice
        else []
    )
    if (
        proposal.expert_context != advice
        or proposal.allowed_output_types != request.allowed_output_types
    ):
        raise ValueError("native proposal options differ from captured source")


def verify_reusable_bundle(
    plan: ReusablePreparationPlan,
    source: bytes,
    control: ReusablePreparationControl,
    *,
    read_bytes: Callable[[Path], bytes] = safe_bytes,
) -> tuple[CandidateRunRequest, WorkflowBindings, str]:
    """Internal verifier requires independent in-memory parent capture."""
    binding = plan.binding
    output = Path(binding.request.output_dir)
    for path, expected in (
        (Path(control.binding_path), encoded(binding)),
        (Path(binding.snapshot_path), source),
        (output / "preparation/request.json", encoded(control)),
    ):
        if read_bytes(path) != expected:
            raise ValueError(f"parent capture changed: {path.name}")
    resolved = resolve_reusable_candidate(plan.document, binding.locations)
    options = resolved.preparation_options.model_dump()
    if binding.request.model_dump(include=set(options)) != options:
        raise ValueError("native options differ from authored preparation options")
    document = WorkflowDocument.model_validate_json(read_bytes(output / "workflow.json"))
    if document != resolved.document:
        raise ValueError("child changed resolved declaration")
    derived = render_workflow_source(resolved.document).encode()
    if read_bytes(output / "workflow.resolved.py") != derived:
        raise ValueError("child changed derived source")
    index = PreparedArtifacts.model_validate_json(read_bytes(output / "preparation/child.json"))
    if (
        index.preparation_id != control.preparation_id
        or index.control_sha256 != hashlib.sha256(encoded(control)).hexdigest()
    ):
        raise ValueError("child index disagrees with parent control identity")

    def observe(path: Path, reference: str) -> tuple[FileObservation, bytes]:
        payload = read_bytes(path)
        return observation(path, reference, payload), payload

    if index.files != tuple(
        observe(output / name, name)[0] for name in reusable_files(plan.document)
    ):
        raise ValueError("child index disagrees with exact reusable artifact set")
    profile = observe(output / "llm.json", "llm_config")[0]
    if (profile.sha256, profile.size_bytes) != (
        control.sources[1].sha256,
        control.sources[1].size_bytes,
    ):
        raise ValueError("saved profile differs from selected bytes")
    verify_payloads(plan, index.composition_fingerprint, read_bytes)
    from .reusable_training import verify_training_payloads

    verify_training_payloads(plan.document, output, read_bytes)
    candidate, bindings = build_candidate(binding.request, document, observe)
    values = candidate.model_dump()
    values["workflow_source"] = WorkflowSourceSnapshot(
        origin_path=str(output / "workflow.resolved.py"),
        sha256=hashlib.sha256(derived).hexdigest(),
        source=derived.decode(),
    ).model_dump()
    candidate = CandidateRunRequest.model_validate(values)
    return candidate, bindings, index.composition_fingerprint
