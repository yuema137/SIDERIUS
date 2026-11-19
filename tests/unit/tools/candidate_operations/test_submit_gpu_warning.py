"""Issue #1587: `candidate_operations submit` warns, never refuses, for a GPU-less training run."""

from __future__ import annotations

import argparse
from uuid import uuid4

import pytest

from tests.unit.tools.candidate_prepare import test_gpu_warning as preparation
from tools.candidate_operations import __main__ as cli
from tools.candidate_operations.models import CandidateOperation, OperationStoreConfig

#: The shipped four-stage example written with no GPU device (shared fixture).
training_request = preparation.training_request


def _submit(tmp_path, monkeypatch, request) -> object:
    """Run the CLI's submit path with admission replaced by a sentinel handle."""
    handle = object()
    monkeypatch.setattr(cli, "submit_operation", lambda *_args, **_kwargs: handle)
    submission = CandidateOperation(request_id=uuid4(), request=request)
    path = tmp_path / "submission.json"
    path.write_text(submission.model_dump_json())
    args = argparse.Namespace(
        command="submit", request=str(path), run_seed=None, host_ledger=None, host_budget=None
    )
    config = OperationStoreConfig(
        state_root=str(tmp_path / "state"),
        preparation_roots=(str(tmp_path),),
        candidate_roots=(str(tmp_path),),
    )
    assert cli.run_request(config, args) is handle, "submit must return admission's handle"
    return handle


def test_training_candidate_without_a_gpu_node_warns_once_on_stderr(
    training_request, tmp_path, monkeypatch, capsys
):
    """Defect #1587: a candidate prepared elsewhere and submitted through the
    operations CLI got no warning and was refused at its tuning node after the
    paid LLM steps. Fails if stderr lacks exactly one warning, if stdout gains
    output, or if the handle (and so the JSON and exit status) changes."""
    request, _ = training_request
    _submit(tmp_path, monkeypatch, request)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.count("Warning: ") == 1
    assert "refused when it reaches training" in captured.err


@pytest.mark.parametrize("case", ["gpu_node", "no_training"])
def test_gpu_node_or_no_training_stays_silent(
    training_request, tmp_path, monkeypatch, capsys, case
):
    """Defect: a run that can train (a GPU node) or does not train is warned.
    Fails if either prints anything."""
    request, _ = training_request
    if case == "gpu_node":
        request = request.model_copy(update={"devices": ("/dev/nvidia0",)})
    else:
        request = preparation._without_training(request)
    _submit(tmp_path, monkeypatch, request)
    assert capsys.readouterr().err == ""
