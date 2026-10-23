"""Explicit reusable-only offline child; legacy control bytes remain unchanged."""

import hashlib
import os
import sys
from pathlib import Path

from core.durable_io import publish_bytes_write_once
from core.generated_library import bind_generated_library_to_workspace
from workflows.definition import (
    ReusableWorkflowDocument,
    parse_workflow_source,
    render_workflow_source,
)

from .admission import verify_sources
from .models import PreparedArtifacts
from .resolution import resolve_reusable_candidate
from .reusable_admission import safe_bytes
from .reusable_models import REUSABLE_FILES, ReusableBindingCapture, ReusablePreparationControl


def execute(request_path: Path) -> None:
    payload = safe_bytes(request_path)
    control = ReusablePreparationControl.model_validate_json(payload)
    output = Path(control.request.output_dir)
    if (
        request_path != output / "preparation/request.json"
        or Path(control.binding_path) != output.parent / "binding.json"
    ):
        raise ValueError("reusable child control locations disagree")
    binding_bytes = safe_bytes(Path(control.binding_path))
    if hashlib.sha256(binding_bytes).hexdigest() != control.binding_sha256:
        raise ValueError("binding capture changed")
    binding = ReusableBindingCapture.model_validate_json(binding_bytes)
    if (
        binding.request != control.request
        or binding.sources != control.sources
        or binding.envelope != str(output.parent)
    ):
        raise ValueError("binding and child selections disagree")
    if binding.snapshot_path != str(output.parent / "workflow.py.snapshot"):
        raise ValueError("unexpected original snapshot path")
    source = safe_bytes(Path(binding.snapshot_path))
    if (hashlib.sha256(source).hexdigest(), len(source)) != (
        binding.original_source.sha256,
        binding.original_source.size_bytes,
    ):
        raise ValueError("original snapshot changed")
    document = parse_workflow_source(source.decode("utf-8"))
    if (
        not isinstance(document, ReusableWorkflowDocument)
        or document.declaration_digest() != binding.reusable_semantic_digest
    ):
        raise ValueError("original reusable identity changed")
    resolved = resolve_reusable_candidate(document, binding.locations)
    verify_sources(control)
    for expected, name in zip(control.sources, ("manifest.snapshot", "llm.snapshot"), strict=True):
        snapshot = safe_bytes(request_path.parent / name)
        if (hashlib.sha256(snapshot).hexdigest(), len(snapshot)) != (
            expected.sha256,
            expected.size_bytes,
        ):
            raise ValueError(f"changed input snapshot: {name}")
    bind_generated_library_to_workspace(str(output))
    from .native import prepare_payloads

    fingerprint = prepare_payloads(control.request)
    publish_bytes_write_once(
        str(output / "workflow.json"), (resolved.document.model_dump_json(indent=2) + "\n").encode()
    )
    publish_bytes_write_once(
        str(output / "workflow.resolved.py"), render_workflow_source(resolved.document).encode()
    )
    from .reusable_admission import observation

    index = PreparedArtifacts(
        preparation_id=control.preparation_id,
        control_sha256=hashlib.sha256(payload).hexdigest(),
        composition_fingerprint=fingerprint,
        files=tuple(
            observation(output / name, name, safe_bytes(output / name)) for name in REUSABLE_FILES
        ),
    )
    publish_bytes_write_once(
        str(output / "preparation/child.json"), index.model_dump_json(indent=2).encode()
    )


if __name__ == "__main__":
    request_path = Path(sys.argv[1])
    with (request_path.parent / "worker.log").open("x") as log:
        os.dup2(log.fileno(), 1)
        os.dup2(log.fileno(), 2)
        execute(request_path)
