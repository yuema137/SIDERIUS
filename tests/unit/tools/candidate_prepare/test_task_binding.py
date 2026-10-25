"""Captured task pins remain inert at inspection and independent in parent verification."""

import hashlib
import json
from pathlib import Path

import pytest

from agent.schemas.storage import LocalStorageConfig, StorageConfig
from tests.unit.tools.candidate_prepare.test_reusable_preparation import reusable as reusable
from tools.candidate_prepare import (
    inspect_reusable_source,
    preflight_reusable_candidate,
    reusable_admission,
)
from tools.candidate_prepare.reusable_verify import verify_payloads
from tools.candidate_worker.layout import candidate_proposal_dir
from workflows.attempt_storage import impl_attempt_storage
from workflows.definition import TaskBinding, parse_workflow_source, render_workflow_source


def bind_source(request, pin):
    source = Path(request.source_path)
    document = parse_workflow_source(source.read_text()).model_copy(update={"task_binding": pin})
    source.write_text(render_workflow_source(document))
    return request.model_copy(
        update={"expected_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
    )


def accepted_pin():
    return TaskBinding(
        package_id="synthetic",
        revision="one",
        task_data_path_id="synthetic_path",
        semantic_fingerprint="a" * 64,
    )


def test_bound_inspection_retains_pin_without_reading_external_contents(reusable, monkeypatch):
    """Removing A1's refusal must not turn source inspection into task/config admission."""
    request = bind_source(reusable, accepted_pin())
    reads = []
    original = reusable_admission.safe_bytes

    def read(path, *args):
        reads.append(path)
        return original(path, *args)

    monkeypatch.setattr(reusable_admission, "safe_bytes", read)
    monkeypatch.setattr(
        reusable_admission, "admit", lambda *args, **kwargs: pytest.fail("external admission")
    )
    inspected = inspect_reusable_source(request)
    assert inspected.document.task_binding == accepted_pin()
    assert reads == [Path(request.source_path)]
    assert not tuple(Path(request.runs_root).iterdir())


@pytest.mark.parametrize("fault", ["fingerprint", "data_path", "missing_data_path"])
def test_parent_rejects_forged_native_identity_even_when_child_stamp_agrees(reusable, fault):
    """A repaired child stamp/index cannot replace the parent's independently captured pin."""
    plan = preflight_reusable_candidate(bind_source(reusable, accepted_pin()))
    request = plan.binding.request
    proposal_dir = candidate_proposal_dir(Path(request.candidate_workspace), request.run_name)
    ref = {"semantic_fingerprint": "a" * 64, "task_data_path_id": "synthetic_path"}
    if fault == "fingerprint":
        ref["semantic_fingerprint"] = "b" * 64
    elif fault == "data_path":
        ref["task_data_path_id"] = "different_path"
    else:
        del ref["task_data_path_id"]
    proposal = {
        "task_composition_ref": ref,
        "storage": StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(proposal_dir), run_name=request.run_name),
        ).model_dump(mode="json"),
        "expert_context": [
            {
                "source": "human",
                "kind": "human",
                "content": request.proposal_advice,
                "source_ref": "human:human_advice",
            }
        ],
        "allowed_output_types": request.allowed_output_types,
    }
    records = {
        "proposal.json": json.dumps(proposal).encode(),
        "storage.json": impl_attempt_storage(str(proposal_dir), request.run_name, 1)
        .storage.model_dump_json()
        .encode(),
    }
    with pytest.raises(ValueError, match="parent-captured workflow task binding"):
        verify_payloads(plan, ref["semantic_fingerprint"], lambda path: records[path.name])
