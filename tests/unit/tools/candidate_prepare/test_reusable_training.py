"""Native reusable preparation, independent regeneration and actual worker propagation."""

import hashlib
import importlib
import json
from pathlib import Path
from uuid import uuid4

import pytest

from tests.unit.tools.candidate_prepare.test_reusable_preparation import (
    direct_child as direct_child,
)
from tests.unit.tools.candidate_prepare.test_reusable_preparation import reusable as reusable
from tests.unit.tools.candidate_worker.test_native import native_runner as native_runner
from tests.unit.tools.candidate_worker.test_training import training_runner as training_runner
from tests.unit.workflows.test_reusable_training import training_document
from tools.candidate_prepare import prepare_reusable_candidate
from tools.candidate_prepare.reusable_selection import (
    select_reusable_preparation,
    verify_reusable_preparation,
)
from tools.candidate_worker import launch_candidate
from workflows.definition import (
    ReusableWorkflowDocument,
    parse_workflow_source,
    render_workflow_source,
)

SETTINGS = {
    "launch": {
        "trial_time_budget_minutes": 7.0,
        "formal_time_budget_minutes": 19.0,
        "trial_max_epochs": 3,
        "formal_max_epochs": 8,
        "trial_portion": 0.2,
        "train_portion": 0.3,
        "sampling_seed": 17,
        "train_base_seed": 23,
        "healthgate_mode": "observe_only",
        "result_authority": "diagnostic",
        "workflow_parameter_rules": {
            "rules": {
                "train_config.epochs": {"range": {"min": 1, "max": 3}},
                "train_config.lr_schedule": {"exact": None},
            }
        },
    }
}


def add_training(request):
    config_path = Path(request.llm_config_file)
    config = json.loads(config_path.read_bytes())
    config["tune"] = {
        "provider": "openai",
        "model_id": "offline-tuner",
        "planner_strategy": "native-timing-v1",
    }
    config_path.write_text(json.dumps(config))
    source = Path(request.source_path)
    payload = parse_workflow_source(source.read_text()).model_dump(mode="json")
    template = training_document().model_dump(mode="json")
    payload["definition"]["externals"].append(template["definition"]["externals"][-1])
    payload["definition"]["nodes"].append(template["definition"]["nodes"][-1])
    payload["training_settings"] = SETTINGS
    source.write_text(
        render_workflow_source(ReusableWorkflowDocument.model_validate_json(json.dumps(payload)))
    )
    return request.model_copy(
        update={"expected_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
    )


def test_two_reusable_runs_reach_native_proposal_and_tuner(
    reusable, direct_child, training_runner, monkeypatch
):
    """Dropped settings/seed hops fail at actual native calls, not a projection echo."""
    from tools.candidate_worker.training_evidence import verify_training_evidence

    monkeypatch.setenv("OPENAI_API_KEY", "offline-not-a-secret")
    request = add_training(
        reusable.model_copy(update={"candidate_environment_names": ("OPENAI_API_KEY",)})
    )
    original = Path(request.source_path).read_bytes()
    workspaces = []
    for selected in (request, request.model_copy(update={"run_id": uuid4(), "run_name": "second"})):
        prepared = prepare_reusable_candidate(selected)
        assert prepared.status == "prepared", prepared.error
        output = Path(prepared.envelope) / "inputs"
        assert not (output.parent / "workspace").exists()
        assert json.loads((output / "training_settings.json").read_text()) == {
            "launch": {**SETTINGS["launch"], "allowed_output_types": ["classifier"]}
        }
        seed = json.loads((output / "proposal.json").read_text())
        assert "hardware_context" not in seed and "constraint_context" not in seed
        assert seed["sampling_seed"] == 17 and seed["trial_portion"] == 0.2
        retained = select_reusable_preparation(prepared.envelope)
        candidate = verify_reusable_preparation(retained).request
        before = len(training_runner)
        receipt = launch_candidate(candidate)
        assert receipt.status == "completed", receipt.error
        calls = training_runner[before:]
        proposed = next(value for name, value in calls if name == "proposal")
        tuned = next(value for name, value in calls if name == "tuner")
        assert (proposed.trial_time_budget_minutes, proposed.formal_time_budget_minutes) == (7, 19)
        assert (tuned.trial_time_budget_minutes, tuned.formal_time_budget_minutes) == (7, 19)
        assert (tuned.sampling_seed, tuned.train_base_seed) == (17, 23)
        assert (tuned.trial_portion, tuned.train_portion) == (0.2, 0.3)
        verify_training_evidence(receipt)
        workspaces.append(receipt.workspace)
    assert workspaces[0] != workspaces[1]
    assert Path(request.source_path).read_bytes() == original


@pytest.mark.parametrize("change", ["settings", "seed", "runtime_fact"])
def test_parent_regenerates_training_inputs_despite_repaired_index(
    reusable, direct_child, monkeypatch, change
):
    """A child cannot substitute settings or seed facts and repair its own index."""
    request = add_training(reusable)

    def tamper(profile, argv):
        result = direct_child(profile, argv)
        path = profile.workspace / (
            "training_settings.json" if change == "settings" else "proposal.json"
        )
        value = json.loads(path.read_bytes())
        if change == "settings":
            value["launch"]["sampling_seed"] = 99
        elif change == "seed":
            value["sampling_seed"] = 99
        else:
            value["constraint_context"] = None
        path.write_text(json.dumps(value))
        index_path = profile.workspace / "preparation/child.json"
        index = json.loads(index_path.read_bytes())
        for item in index["files"]:
            payload = Path(item["path"]).read_bytes()
            item.update(sha256=hashlib.sha256(payload).hexdigest(), size_bytes=len(payload))
        index_path.write_text(json.dumps(index))
        return result

    monkeypatch.setattr(importlib.import_module("tools.candidate_prepare.launch"), "run", tamper)
    result = prepare_reusable_candidate(request)
    assert result.status == "failed" and result.candidate_request_path is None
    assert "training" in result.error or "runtime-owned" in result.error
