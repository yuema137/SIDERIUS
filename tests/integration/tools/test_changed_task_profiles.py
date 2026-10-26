"""All seeds and prior captures remain owned during a checked profile task update."""

import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest

from tests.helpers.reusable_fanout import reusable_families, reusable_fanout
from tests.integration.tools.test_changed_task_candidate import (
    changed_candidate,
    pytestmark,
    reviewed_request,
)
from tools.candidate_prepare import prepare_reusable_candidate
from tools.candidate_worker import CandidateRunRequest
from tools.workflow_authoring.service import AuthoringError
from workflows.definition import (
    ReusableWorkflowDocument,
    parse_workflow_source,
    render_workflow_source,
)


@pytest.fixture
def profile_candidate(changed_candidate, request):
    author, targets, preparation = changed_candidate
    transform = (
        reusable_fanout if getattr(request, "param", "families") == "fanout" else reusable_families
    )
    return author, targets, transform(preparation)


def files(root):
    return {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


@pytest.mark.parametrize("profile_candidate", ("fanout", "families"), indirect=True)
def test_every_profile_seed_uses_changed_task_and_old_capture_stays_unchanged(profile_candidate):
    author, targets, preparation = profile_candidate
    old_document = parse_workflow_source(author.read().source)
    old = prepare_reusable_candidate(preparation)
    assert old.status == "prepared", old.error
    old_files = files(Path(old.envelope))
    reviewed, save = reviewed_request(author, targets[1])
    task = reviewed.task_reference_update
    assert task.save_supported, task.findings
    assert any(item.reference == "task.primary_metric" for item in task.findings)
    assert any("families" in item.message and "branches" in item.message for item in task.findings)
    author.save(save)
    document = parse_workflow_source(author.read().source)
    assert document.definition.nodes == old_document.definition.nodes
    assert document.definition.externals == old_document.definition.externals
    assert document.positions == old_document.positions
    assert document.preparation_options == old_document.preparation_options
    assert document.execution_profile == old_document.execution_profile
    result = prepare_reusable_candidate(
        preparation.model_copy(
            update={
                "run_id": uuid4(),
                "expected_source_sha256": hashlib.sha256(
                    author.project.source_file.read_bytes()
                ).hexdigest(),
            }
        )
    )
    assert result.status == "prepared", result.error
    output = Path(result.envelope) / "inputs"
    families = document.execution_profile == "native-proposal-families/v1"
    seeds = (
        ["proposal.hypothesis.json", "proposal.alternate.json"] if families else ["proposal.json"]
    )
    assert sorted(path.name for path in output.glob("proposal*.json")) == sorted(seeds)
    assert sorted(path.name for path in output.glob("storage.*.json")) == sorted(
        [
            "storage.build_left.json",
            "storage.build_right.json",
            *(["storage.build_other.json"] if families else []),
        ]
    )
    storage = []
    for owner, name in zip(("hypothesis", "alternate"), seeds, strict=False):
        seed = json.loads((output / name).read_bytes())
        assert (
            seed["task_composition_ref"]["semantic_fingerprint"]
            == targets[1].binding.semantic_fingerprint
        )
        assert (
            seed["task_composition_ref"]["task_data_path_id"]
            == targets[1].binding.task_data_path_id
        )
        assert seed["allowed_output_types"] == ["classifier"]
        assert [item["content"] for item in seed["expert_context"]] == [
            document.preparation_options.proposal_advice
        ]
        storage.append(seed["storage"]["local"]["workspace"])
        assert f"/graph_instances/{owner}/" in storage[-1]
    assert len(set(storage)) == len(seeds)
    branch_storage = ["storage.build_left.json", "storage.build_right.json"]
    if families:
        branch_storage.append("storage.build_other.json")
    for name in branch_storage:
        branch = name.removeprefix("storage.").removesuffix(".json")
        payload = json.loads((output / name).read_bytes())
        assert f"/graph_instances/{branch}/" in payload["local"]["workspace"]
    index = json.loads((output / "preparation/child.json").read_bytes())
    assert [item["reference"] for item in index["files"]] == [
        "preparation/interpretation_input.json",
        "interpretation.json",
        *seeds,
        *branch_storage,
        "llm.json",
        "workflow.json",
        "workflow.resolved.py",
    ]
    candidate = CandidateRunRequest.model_validate_json(
        Path(result.candidate_request_path).read_bytes()
    )
    assert candidate.implementation_advice == document.preparation_options.implementation_advice
    assert candidate.validation_advice == document.preparation_options.validation_advice
    assert candidate.preview.execution_profile == document.execution_profile
    assert not (Path(result.envelope) / "workspace").exists()
    assert files(Path(old.envelope)) == old_files


@pytest.mark.parametrize("defect", ("proposal_alias", "storage_alias", "profile", "cross_family"))
def test_schema_valid_profile_mapping_defects_block_publication(profile_candidate, defect):
    author, targets, _ = profile_candidate
    raw = parse_workflow_source(author.read().source).model_dump(mode="json")
    if defect == "profile":
        # A two-family graph cannot be admitted as the single-family profile.
        raw["execution_profile"] = "native-proposal-fanout/v1"
    elif defect == "cross_family":
        validation = next(
            node for node in raw["definition"]["nodes"] if node["id"] == "check_other"
        )
        for argument in validation["request"]["arguments"]:
            if argument["name"] == "proposal":
                argument["source"]["node"] = "hypothesis"
    else:
        definition = raw["definition"]
        old, replacement = (
            ("alternate_seed", "proposal")
            if defect == "proposal_alias"
            else ("slot_other", "slot_left")
        )
        if defect == "proposal_alias":
            replacement = next(
                node["request"]["binding"]
                for node in definition["nodes"]
                if node["id"] == "hypothesis"
            )
        for node in definition["nodes"]:
            if node["request"]["kind"] == "external" and node["request"]["binding"] == old:
                node["request"]["binding"] = replacement
            for argument in node["request"].get("arguments", ()):
                if argument["source"].get("binding") == old:
                    argument["source"]["binding"] = replacement
        definition["externals"] = [item for item in definition["externals"] if item["id"] != old]
    document = ReusableWorkflowDocument.model_validate_json(json.dumps(raw))
    author.project.source_file.write_text(render_workflow_source(document))
    original = author.read().source
    reviewed, save = reviewed_request(author, targets[1])
    assert not reviewed.task_reference_update.save_supported
    assert any(
        item.state == "blocked" and item.reference == "source"
        for item in reviewed.task_reference_update.findings
    )
    with pytest.raises(AuthoringError, match="publication is blocked"):
        author.save(save)
    assert author.read().source == original


def test_later_task_drift_keeps_profile_source_unchanged(profile_candidate):
    author, targets, _ = profile_candidate
    reviewed, save = reviewed_request(author, targets[1])
    assert reviewed.task_reference_update.save_supported
    original = author.read().source
    plugin = targets[1].manifest.parent / "plugins/_quickstart_task.py"
    plugin.write_text(plugin.read_text() + "\n# changed after family review\n")
    with pytest.raises(AuthoringError, match="publication is blocked"):
        author.save(save)
    assert author.read().source == original
