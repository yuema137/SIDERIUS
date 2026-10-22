"""Fixed offline child; generated-library binding precedes native imports."""

import hashlib
import os
import sys
from pathlib import Path

from core.durable_io import publish_bytes_write_once
from core.generated_library import bind_generated_library_to_workspace
from tools.workflow_preview.files import observe_file

from .admission import verify_sources
from .models import NATIVE_FILES, PreparationControl, PreparedArtifacts


def execute(request_path: Path) -> None:
    payload = request_path.read_bytes()
    control = PreparationControl.model_validate_json(payload)
    output = Path(control.request.output_dir)
    if request_path != output / "preparation/request.json":
        raise ValueError("child control path disagrees with selected output")
    verify_sources(control)
    for expected, name in zip(control.sources, ("manifest.snapshot", "llm.snapshot"), strict=True):
        snapshot, _ = observe_file(request_path.parent / name, expected.reference)
        if (snapshot.sha256, snapshot.size_bytes) != (expected.sha256, expected.size_bytes):
            raise ValueError(f"changed input snapshot: {name}")
    bind_generated_library_to_workspace(str(output))
    from .native import prepare_native

    fingerprint = prepare_native(control.request)
    files = tuple(observe_file(output / name, name)[0] for name in NATIVE_FILES)
    index = PreparedArtifacts(
        preparation_id=control.preparation_id,
        control_sha256=hashlib.sha256(payload).hexdigest(),
        composition_fingerprint=fingerprint,
        files=files,
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
