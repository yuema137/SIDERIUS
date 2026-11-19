"""A prepared worker request that trains, written with no GPU device (#1562, #1587).

Shared by the preparation advisory tests and the operations ``submit`` warning
tests, which check the same condition at two surfaces.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from tools.candidate_worker.models import CandidateRunRequest

REPO = Path(__file__).resolve().parents[2]


def write_training_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[CandidateRunRequest, Path]:
    """The shipped four-stage example's worker request, written with no GPU device."""
    spec = importlib.util.spec_from_file_location(
        "native_training_example", REPO / "examples/workflow_declarations/native_training.py"
    )
    assert spec is not None and spec.loader is not None
    example = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(example)
    monkeypatch.setattr(example, "host_gpu_devices", lambda: ())
    data = tmp_path / "data"
    data.mkdir()
    path = example.write_example(tmp_path / "inputs", data, tmp_path / "workspace")
    return CandidateRunRequest.model_validate_json(path.read_bytes()), path


def without_training(request: CandidateRunRequest) -> CandidateRunRequest:
    """``request`` with its tuning node removed, so the workflow no longer trains."""
    document = request.preview.document
    definition = document.definition.model_copy(
        update={"nodes": tuple(n for n in document.definition.nodes if n.capability != "tuning")}
    )
    preview = request.preview.model_copy(
        update={"document": document.model_copy(update={"definition": definition})}
    )
    return request.model_copy(update={"preview": preview})
