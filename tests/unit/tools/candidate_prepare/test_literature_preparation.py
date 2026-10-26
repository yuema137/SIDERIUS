"""Captured native literature settings, exact census and parent reconstruction."""

import hashlib
import json
from pathlib import Path

import pytest

from agent.schemas.literature_review import LiteratureReviewInput
from tests.helpers.reusable_literature import reusable_literature
from tests.unit.tools.candidate_prepare.test_reusable_preparation import direct_child, reusable
from tools.candidate_prepare import (
    preflight_reusable_candidate,
    prepare_reusable_candidate,
    select_reusable_preparation,
)
from tools.candidate_prepare.reusable_models import ReusablePreparationControl
from tools.candidate_prepare.reusable_verify import verify_reusable_bundle
from workflows.definition import parse_workflow_source, render_workflow_source


def test_actual_native_review_and_exact_captured_projection(reusable, direct_child):
    request = reusable_literature(
        reusable,
        {
            "dynamic_search": {"enabled": False},
            "findings_verbosity": 0,
            "synthesis": {"transfer_tolerance": "strict"},
        },
    )
    source = Path(request.source_path).read_bytes()
    document = parse_workflow_source(source.decode())
    assert parse_workflow_source(render_workflow_source(document)) == document
    plan = preflight_reusable_candidate(request)
    receipt = prepare_reusable_candidate(request)
    assert receipt.status == "prepared", receipt.error
    output = Path(receipt.envelope) / "inputs"
    value = LiteratureReviewInput.model_validate_json(
        (output / "literature.review.json").read_bytes()
    )
    assert value.findings_verbosity == 0
    assert value.synthesis_config.transfer_tolerance == "strict"
    assert not value.dynamic_search.enabled
    seed = json.loads((output / "proposal.json").read_bytes())
    assert not seed.get("literature_review_evidence")
    assert value.task_description == seed["task_description"]
    assert value.interpretation_evidence
    assert value.storage.local.workspace.endswith(
        "graph_instances/review/iteration_001/attempt_001"
    )
    native_receipt = json.loads((output / "preparation/receipt.json").read_bytes())
    assert native_receipt["proposal_path"] == str(output / "proposal.json")
    control = ReusablePreparationControl.model_validate_json(
        (output / "preparation/request.json").read_bytes()
    )
    candidate, _, _ = verify_reusable_bundle(plan, source, control)
    assert candidate.preview.execution_profile == "native-literature-candidate/v1"
    index_path = output / "preparation/child.json"
    index_bytes = index_path.read_bytes()
    assert [item["reference"] for item in json.loads(index_bytes)["files"]] == [
        "preparation/interpretation_input.json",
        "interpretation.json",
        "proposal.json",
        "storage.build_left.json",
        "llm.json",
        "workflow.json",
        "workflow.resolved.py",
        "literature.review.json",
    ]
    for defect in ("settings", "evidence", "route", "storage", "seed", "missing", "extra"):
        path = output / ("proposal.json" if defect == "seed" else "literature.review.json")
        original = path.read_bytes()
        payload = json.loads(original)
        index = json.loads(index_bytes)
        if defect == "settings":
            payload["findings_verbosity"] = 1
        elif defect == "evidence":
            payload["interpretation_evidence"] = {}
        elif defect == "route":
            payload["llm_model_id"] = "forged"
        elif defect == "storage":
            payload["storage"]["local"]["workspace"] += "/forged"
        elif defect == "seed":
            payload["task_description"] += " changed"
        elif defect == "missing":
            index["files"].pop()
        else:
            index["files"].append(index["files"][-1])
        if defect not in {"missing", "extra"}:
            path.write_text(json.dumps(payload))
            for item in index["files"]:
                body = Path(item["path"]).read_bytes()
                item.update(sha256=hashlib.sha256(body).hexdigest(), size_bytes=len(body))
        index_path.write_text(json.dumps(index))
        with pytest.raises(ValueError, match=r"literature differs|artifact set"):
            verify_reusable_bundle(plan, source, control)
        path.write_bytes(original)
        index_path.write_bytes(index_bytes)
    select_reusable_preparation(receipt.envelope)


@pytest.mark.parametrize(
    "settings",
    [
        {"synthesis": None},
        {"advice": "change science"},
        {"synthesis_config": {}},
        {"llm_provider": "openai"},
    ],
)
def test_unknown_or_null_settings_refuse_before_envelope(reusable, settings):
    request = reusable_literature(reusable, settings)
    with pytest.raises(ValueError):
        preflight_reusable_candidate(request)
    assert not list(Path(request.runs_root).iterdir())


@pytest.mark.parametrize(
    "settings,message",
    [
        (
            {
                "root_papers": [{"source_type": "local", "identifier": "paper.pdf"}],
                "dynamic_search": {"enabled": False},
            },
            "local papers",
        ),
        ({}, "explicit network"),
    ],
)
def test_native_policy_refuses_before_payload_publication(
    reusable, direct_child, settings, message
):
    receipt = prepare_reusable_candidate(reusable_literature(reusable, settings))
    assert receipt.status == "failed"
    output = Path(receipt.envelope) / "inputs"
    assert message in (output / "preparation/worker.log").read_text()
    assert not (output / "proposal.json").exists()
    assert not (output / "interpretation.json").exists()
