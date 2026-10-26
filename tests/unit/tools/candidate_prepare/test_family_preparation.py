"""Per-family publication authority and explicit-profile receipt semantics."""

import hashlib
import json
from pathlib import Path

import pytest

from tests.helpers.reusable_fanout import reusable_families, reusable_fanout
from tests.unit.tools.candidate_prepare.test_reusable_preparation import direct_child, reusable
from tools.candidate_prepare import (
    preflight_reusable_candidate,
    prepare_reusable_candidate,
    select_reusable_preparation,
)
from tools.candidate_prepare.reusable_models import (
    ReusablePreparationControl,
    ReusablePreparationObservations,
)
from tools.candidate_prepare.reusable_terminal import read_reusable_terminal
from tools.candidate_prepare.reusable_verify import verify_reusable_bundle
from workflows.definition import (
    ReusableWorkflowDocument,
    parse_workflow_source,
    render_workflow_source,
)


def test_every_family_seed_is_independently_verified_against_capture(reusable, direct_child):
    """Re-signing a changed child index must not authorize swapped storage/pins/options."""
    request = reusable_families(reusable)
    source = Path(request.source_path).read_bytes()
    plan = preflight_reusable_candidate(request)
    receipt = prepare_reusable_candidate(request)
    assert receipt.status == "prepared", receipt.error
    output = Path(receipt.envelope) / "inputs"
    control = ReusablePreparationControl.model_validate_json(
        (output / "preparation/request.json").read_bytes()
    )
    index_path = output / "preparation/child.json"
    index_bytes = index_path.read_bytes()
    assert [item["reference"] for item in json.loads(index_bytes)["files"]] == [
        "preparation/interpretation_input.json",
        "interpretation.json",
        "proposal.hypothesis.json",
        "proposal.alternate.json",
        "storage.build_left.json",
        "storage.build_right.json",
        "storage.build_other.json",
        "llm.json",
        "workflow.json",
        "workflow.resolved.py",
    ]
    assert not (output / "proposal.json").exists()
    candidate, _, _ = verify_reusable_bundle(plan, source, control)
    assert candidate.preview.execution_profile == "native-proposal-families/v1"
    path = output / "proposal.alternate.json"
    original = path.read_bytes()
    for defect in ("storage", "fingerprint", "options", "missing", "extra", "profile"):
        changed = json.loads(index_bytes)
        seed = json.loads(original)
        if defect == "storage":
            seed["storage"] = json.loads((output / "proposal.hypothesis.json").read_bytes())[
                "storage"
            ]
        elif defect == "fingerprint":
            seed["task_composition_ref"]["semantic_fingerprint"] = "f" * 64
        elif defect == "options":
            seed["expert_context"] = []
        elif defect == "missing":
            changed["files"] = [item for item in changed["files"] if item["reference"] != path.name]
        elif defect == "extra":
            changed["files"].append(changed["files"][2])
        else:
            from tools.candidate_prepare.resolution import resolve_reusable_candidate

            with pytest.raises(ValueError):
                resolve_reusable_candidate(
                    plan.document.model_copy(
                        update={"execution_profile": "native-proposal-fanout/v1"}
                    ),
                    plan.binding.locations,
                )
            continue
        if defect in ("storage", "fingerprint", "options"):
            path.write_text(json.dumps(seed))
            for item in changed["files"]:
                payload = Path(item["path"]).read_bytes()
                item.update(sha256=hashlib.sha256(payload).hexdigest(), size_bytes=len(payload))
        index_path.write_text(json.dumps(changed))
        with pytest.raises(ValueError, match=r"storage|fingerprint|options|artifact set"):
            verify_reusable_bundle(plan, source, control)
        path.write_bytes(original)
        index_path.write_bytes(index_bytes)
    select_reusable_preparation(receipt.envelope)


@pytest.mark.parametrize("families", [False, True])
def test_scalar_receipt_is_profile_owned_in_full_and_terminal_readers(
    reusable, direct_child, families
):
    """Prepared null is success only with explicit family source; a first seed is not a scalar substitute."""
    request = reusable_families(reusable) if families else reusable_fanout(reusable)
    plan = preflight_reusable_candidate(request)
    receipt = prepare_reusable_candidate(request)
    assert receipt.status == "prepared"
    path = Path(receipt.envelope) / "inputs/preparation/receipt.json"
    native = json.loads(path.read_bytes())
    observations = ReusablePreparationObservations.from_binding(plan.binding)
    assert (
        read_reusable_terminal(request, observations, receipt.preparation_id)[0].status
        == "prepared"
    )
    assert native["proposal_path"] == (None if families else str(path.parents[1] / "proposal.json"))
    native["proposal_path"] = (
        str(path.parents[1] / "proposal.hypothesis.json") if families else None
    )
    path.write_text(json.dumps(native))
    with pytest.raises(ValueError, match="native receipt"):
        select_reusable_preparation(receipt.envelope)
    with pytest.raises(ValueError, match="artifact references"):
        read_reusable_terminal(request, observations, receipt.preparation_id)


def test_shared_managed_proposal_alias_refuses_before_envelope_claim(reusable):
    """Schema-valid shared external cannot stand for two prepared native storage identities."""
    request = reusable_families(reusable)
    path = Path(request.source_path)
    raw = parse_workflow_source(path.read_text()).model_dump(mode="json")
    definition = raw["definition"]
    first = next(
        node["request"]["binding"] for node in definition["nodes"] if node["id"] == "hypothesis"
    )
    for node in definition["nodes"]:
        if node["id"] == "alternate":
            node["request"]["binding"] = first
    definition["externals"] = [
        item for item in definition["externals"] if item["id"] != "alternate_seed"
    ]
    path.write_text(
        render_workflow_source(ReusableWorkflowDocument.model_validate_json(json.dumps(raw)))
    )
    request = request.model_copy(
        update={"expected_source_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    )
    with pytest.raises(ValueError, match=r"shared across|one managed proposal"):
        preflight_reusable_candidate(request)
    assert not list(Path(request.runs_root).iterdir())


def test_parent_checks_accepted_task_path_on_later_family(reusable):
    """A matching fingerprint/index stamp cannot authorize a later seed's wrong task path."""
    from tests.unit.tools.candidate_prepare.test_task_binding import accepted_pin, bind_source
    from tools.candidate_prepare.layout import preparation_layout
    from tools.candidate_prepare.reusable_verify import verify_payloads

    pin = accepted_pin()
    plan = preflight_reusable_candidate(bind_source(reusable_families(reusable), pin))
    request = plan.binding.request
    layout = preparation_layout(plan.document, Path(request.candidate_workspace), request.run_name)
    records = {
        item.filename: item.storage.model_dump_json().encode() for item in layout.storage_records
    }
    for item in layout.proposal_records:
        records[item.filename] = json.dumps(
            {
                "storage": {
                    "backend": "local",
                    "local": {"workspace": item.directory, "run_name": request.run_name},
                },
                "task_composition_ref": {
                    "semantic_fingerprint": pin.semantic_fingerprint,
                    "task_data_path_id": pin.task_data_path_id
                    if item.owner == "hypothesis"
                    else "forged_later_path",
                },
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
        ).encode()
    with pytest.raises(ValueError, match="parent-captured workflow task binding"):
        verify_payloads(plan, pin.semantic_fingerprint, lambda path: records[path.name])
