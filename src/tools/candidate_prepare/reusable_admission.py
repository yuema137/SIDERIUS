"""Read-once source capture and no-write reusable envelope admission."""

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from tools.workflow_preview.files import observe_file, resolve_location
from tools.workflow_preview.models import FileObservation
from workflows.definition import (
    ManagedCandidateBinding,
    ReusableWorkflowDocument,
    parse_workflow_source,
)
from workflows.definition.source import MAX_INPUT_BYTES

from .admission import absent_destination, admit, canonical, overlap
from .models import CandidatePreparationRequest
from .resolution import (
    ResolvedExternalLocation,
    ReusableCandidateLocations,
    resolve_reusable_candidate,
)
from .reusable_models import (
    ReusableBindingCapture,
    ReusableCandidatePreparationRequest,
    ReusablePreparationPlan,
)


def safe_bytes(path: Path, limit: int = 16 * 1024 * 1024) -> bytes:
    canonical(str(path))
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError(f"expected regular file: {path}")
        payload = stream.read(limit + 1)
    if len(payload) > limit:
        raise ValueError(f"file exceeds preparation read limit: {path}")
    return payload


def observation(path: Path, reference: str, payload: bytes) -> FileObservation:
    return FileObservation(
        reference=reference,
        path=str(path),
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
    )


@dataclass(frozen=True)
class CapturedPreparation:
    plan: ReusablePreparationPlan
    source: bytes
    inputs: tuple[tuple[FileObservation, bytes], ...]


def reusable_locations(
    document: ReusableWorkflowDocument, project: Path, envelope: Path
) -> ReusableCandidateLocations:
    """Map captured task references and managed roles to the fixed run layout."""
    if any(not isinstance(item, ManagedCandidateBinding) for item in document.definition.externals):
        raise ValueError(
            "reusable preparation supports managed externals only; literal externals are unsupported"
        )
    task = document.definition.task
    manifest = resolve_location(project, task.manifest, "task.manifest")
    data = resolve_location(project, task.data_root, "task.data_root")
    return ReusableCandidateLocations(
        manifest=str(manifest),
        data_root=str(data),
        workspace=str(envelope / "workspace"),
        externals=tuple(
            ResolvedExternalLocation(
                binding=item.id,
                location=str(
                    envelope
                    / "inputs"
                    / ("proposal.json" if item.contract == "proposal.input" else "storage.json")
                ),
            )
            for item in document.definition.externals
        ),
    )


def capture(request: ReusableCandidatePreparationRequest) -> CapturedPreparation:
    request = ReusableCandidatePreparationRequest.model_validate_json(request.model_dump_json())
    source, project, runs = map(
        canonical, (request.source_path, request.project_root, request.runs_root)
    )
    if not project.is_dir() or not runs.is_dir():
        raise ValueError("project_root and runs_root must be existing directories")
    envelope = canonical(str(runs / str(request.run_id)))
    absent_destination(envelope)
    payload = safe_bytes(source, MAX_INPUT_BYTES)
    observed = observation(source, "workflow.source", payload)
    if observed.sha256 != request.expected_source_sha256:
        raise ValueError("workflow source hash differs from expected_source_sha256")
    document = parse_workflow_source(payload.decode("utf-8"))
    if not isinstance(document, ReusableWorkflowDocument):
        raise ValueError("reusable preparation requires a v2 source")
    locations = reusable_locations(document, project, envelope)
    resolved = resolve_reusable_candidate(document, locations)
    native = CandidatePreparationRequest(
        task_manifest=locations.manifest,
        data_root=locations.data_root,
        output_dir=str(envelope / "inputs"),
        candidate_workspace=locations.workspace,
        **request.model_dump(
            include={
                "run_name",
                "llm_config_file",
                "preparation_timeout_seconds",
                "candidate_timeout_seconds",
                "task_read_only",
                "candidate_network",
                "candidate_devices",
                "candidate_environment_names",
            }
        ),
        **resolved.preparation_options.model_dump(),
    )
    captures = admit(native, future_parent=envelope)
    if overlap(envelope, source):
        raise ValueError("envelope overlaps authored source")
    binding = ReusableBindingCapture(
        run_id=request.run_id,
        envelope=str(envelope),
        project_root=str(project),
        original_source=observed,
        snapshot_path=str(envelope / "workflow.py.snapshot"),
        reusable_semantic_digest=document.declaration_digest(),
        request=native,
        locations=locations,
        sources=tuple(item for item, _ in captures),
    )
    return CapturedPreparation(
        ReusablePreparationPlan(
            binding=binding, document=document, resolved_document=resolved.document
        ),
        payload,
        captures,
    )


def preflight_reusable_candidate(
    request: ReusableCandidatePreparationRequest,
) -> ReusablePreparationPlan:
    """Return inert observations only; prepare always captures afresh."""
    return capture(request).plan


def verify_origin(binding: ReusableBindingCapture) -> None:
    payload = safe_bytes(Path(binding.original_source.path), MAX_INPUT_BYTES)
    if (
        observation(Path(binding.original_source.path), "workflow.source", payload)
        != binding.original_source
    ):
        raise ValueError("authored workflow source changed during preparation")
    for expected in binding.sources:
        actual, _ = observe_file(canonical(expected.path), expected.reference)
        if actual != expected:
            raise ValueError(f"selected input changed: {expected.reference}")
