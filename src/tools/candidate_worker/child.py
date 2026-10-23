"""Known sandbox child: bind workspace BEFORE importing native task consumers."""

import os
import sys
from pathlib import Path

from core.generated_library import bind_generated_library_to_workspace
from tools.workflow_preview.files import observe_file

from .launch import publish
from .models import CandidateRunReceipt, CandidateRunRequest
from .source import verify_snapshot


def execute(request_path: Path) -> CandidateRunReceipt:
    request = CandidateRunRequest.model_validate_json(request_path.read_bytes())
    control = request_path.parent
    initial = CandidateRunReceipt.model_validate_json((control / "launch.json").read_bytes())
    workspace = Path(initial.workspace)
    if request_path != workspace / "candidate_run" / "request.json":
        raise ValueError("child request path disagrees with claimed workspace")
    verify_snapshot(request, control)
    for index, expected in enumerate(request.files):
        current, _ = observe_file(Path(expected.path), expected.reference)
        snapshot, _ = observe_file(control / f"input_{index:03}.snapshot", expected.reference)
        if current != expected or (snapshot.sha256, snapshot.size_bytes) != (
            expected.sha256,
            expected.size_bytes,
        ):
            raise ValueError(f"selected input changed: {expected.reference}")
    bind_generated_library_to_workspace(str(workspace))
    # Import order is an execution invariant: registries can discover at import.
    from .native import execute_native

    receipt = execute_native(request, initial)
    publish(control / "child.json", receipt)
    return receipt


if __name__ == "__main__":
    request_path = Path(sys.argv[1])
    with (request_path.parent / "worker.log").open("x") as log:
        os.dup2(log.fileno(), 1)
        os.dup2(log.fileno(), 2)
        execute(request_path)
