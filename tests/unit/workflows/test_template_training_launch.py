"""User-task template settings must survive preparation and native tuner projection."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from agent import planner_strategy
from tests.unit.workflows import test_model_exploration as workflow_tests
from tests.unit.workflows.test_model_exploration import workflow_env as workflow_env
from tools.candidate_prepare.reusable_training import settings_payload
from tools.workflow_authoring.templates import instantiate, template_catalog, template_document
from workflows.candidate_training_settings import parse_training_settings
from workflows.definition import ReusableWorkflowDocument, parse_workflow_source
from workflows.llm_config import WorkflowLLMConfig


@pytest.mark.parametrize("template_id", [item.id for item in template_catalog().templates])
def test_template_settings_reach_native_tuner(workflow_env, monkeypatch, template_id):
    """Reverting template declarations would silently restore .1 / 10 at execution.

    Uses real source rendering/parsing, preparation payload admission, composed
    workflow startup and tuner projection. Only provider/trainer effects are fake.
    """
    native = planner_strategy.resolve_planner_strategy("native-timing-v1")
    monkeypatch.setattr(
        planner_strategy,
        "entry_points",
        lambda **_kwargs: [SimpleNamespace(name="fixture-default", load=lambda: lambda: native)],
    )
    document = parse_workflow_source(instantiate(template_id, template_document(template_id)))
    assert isinstance(document, ReusableWorkflowDocument)
    payload = settings_payload(document)
    assert payload is not None
    settings = parse_training_settings(payload)
    launch = replace(
        settings.launch,
        data_dir=workflow_env["data_dir"],
        model_types=["punet"],
        source_run_name="v1",
    )
    workflow_tests.run_workflow(
        launch=launch,
        workspace=workflow_env["workspace"],
        run_name="template_launch",
        llm_config=WorkflowLLMConfig(),
    )
    actual = workflow_env["tune"].return_value.run.call_args.args[0]
    assert (actual.formal_portion, actual.max_rounds) == (1.0, 2)
    assert actual.is_trial and actual.force_formal_round
