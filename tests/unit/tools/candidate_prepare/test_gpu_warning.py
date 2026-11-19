"""Issue #1562: preparation warns, never refuses, when a training run has no GPU node."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest

from tools.candidate_prepare import ReusablePreparationReceipt, prepared_gpu_warning
from tools.candidate_prepare.__main__ import finish
from tools.candidate_worker.models import CandidateRunRequest

REPO = Path(__file__).resolve().parents[4]


@pytest.fixture
def training_request(tmp_path, monkeypatch) -> tuple[CandidateRunRequest, Path]:
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


def _without_training(request: CandidateRunRequest) -> CandidateRunRequest:
    document = request.preview.document
    definition = document.definition.model_copy(
        update={"nodes": tuple(n for n in document.definition.nodes if n.capability != "tuning")}
    )
    preview = request.preview.model_copy(
        update={"document": document.model_copy(update={"definition": definition})}
    )
    return request.model_copy(update={"preview": preview})


def test_training_request_without_a_gpu_node_gets_one_warning(training_request):
    """Defect #1562: a workflow with a tuning node prepared with no GPU device node was
    prepared silently and only refused when the run reached training, after paid LLM
    steps. Fails if no warning is produced, or if it stops naming the consequence
    (refused at training) and the fix (host_gpu_devices / add-task)."""
    request, _ = training_request
    warning = prepared_gpu_warning(request)
    assert warning is not None
    assert "refused when it reaches training" in warning
    assert "host_gpu_devices()" in warning and "add-task" in warning


@pytest.mark.parametrize("device", ["/dev/nvidia0", "/dev/dxg"])
def test_training_request_with_any_provider_gpu_node_is_silent(training_request, device):
    """Defect: a WSL2 run (/dev/dxg, core.gpu_devices provider) or a native NVIDIA run
    is warned as GPU-less. Fails if a node of either provider still yields a warning."""
    request, _ = training_request
    assert prepared_gpu_warning(request.model_copy(update={"devices": (device,)})) is None


def test_workflow_without_training_is_silent_with_no_devices(training_request):
    """Defect: a three-stage or literature workflow, which needs no GPU, is warned.
    Fails if a request without a tuning node and with no devices yields a warning."""
    request, _ = training_request
    assert prepared_gpu_warning(_without_training(request)) is None


def test_cli_prints_the_warning_on_stderr_and_still_succeeds(training_request, tmp_path, capsys):
    """Defect #1562 at the CLI: the advisory must reach the operator, yet preparation
    must not fail and stdout must stay the receipt JSON alone (callers redirect it to a
    file). Fails if exit status is not 0, if stdout gains anything but the receipt, or if
    stderr lacks the warning."""
    _, path = training_request
    receipt = ReusablePreparationReceipt(
        run_id=uuid4(),
        envelope=str(tmp_path / "runs" / "envelope"),
        status="prepared",
        binding_path=str(tmp_path / "binding.json"),
        binding_sha256="0" * 64,
        candidate_request_path=str(path),
    )
    assert finish(receipt) == 0
    out, err = capsys.readouterr()
    assert ReusablePreparationReceipt.model_validate_json(out) == receipt
    assert err.startswith("Warning: This workflow trains")
    assert err.count("Warning:") == 1
