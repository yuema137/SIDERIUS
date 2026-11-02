"""Offline executability checks for the shipped two-step scenario examples."""

import hashlib
import runpy
import socket
from pathlib import Path
from uuid import uuid4

import pytest

from agent.schemas.literature_review import LiteratureReviewInput
from execute_tools.task_registration_scope import run_registration_scope
from tools.candidate_prepare import (
    ReusableCandidatePreparationRequest,
    preflight_reusable_candidate,
)
from tools.candidate_worker import CandidateRunRequest
from tools.candidate_worker.adaptor_llm import admit_llm_adaptors
from tools.candidate_worker.fanout_inputs import materialize_fanout
from tools.candidate_worker.preflight import fresh_preview
from workflows.definition import (
    ExternalSource,
    NoImprovementStop,
    ProtocolRequest,
    ReusableWorkflowDocument,
    WorkflowDocument,
    inspect_declaration,
    parse_workflow_source,
)
from workflows.definition.fanout import execution_families
from workflows.definition.llm_strategies import DebateJudgeStrategy
from workflows.llm_config import WorkflowLLMConfig, locked_judge_routes
from workflows.task_composition import compose_run_task_bindings

REPO = Path(__file__).resolve().parents[3]
EXAMPLES = REPO / "examples/workflow_declarations"


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("scenario declaration checks must never use the network")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def test_literature_example_writes_an_admissible_request(tmp_path: Path) -> None:
    """Defect: the example's graph, native payloads or routes drift out of agreement.

    Import/write, JSON validation, preview and real worker input reconciliation
    fail before any provider or sandbox effect if the shipped recipe breaks.
    """
    module = runpy.run_path(str(EXAMPLES / "literature_debate_judged.py"))
    data = tmp_path / "data"
    data.mkdir()
    with run_registration_scope():
        path = module["write_example"](
            tmp_path / "inputs", data, tmp_path / "workspace", "offline-test-model"
        )
        request = CandidateRunRequest.model_validate_json(path.read_bytes())
        document = WorkflowDocument.model_validate_json(request.preview.document.model_dump_json())
        assert inspect_declaration(document).status == "declaration_validated"
        fresh_preview(request)
        shape = execution_families(document.definition, request.preview.execution_profile)
        assert len(shape.families) == 1
        assert shape.literature_adaptor is not None
        assert len(shape.literature_adaptor.reviews) == 3
        config = WorkflowLLMConfig.model_validate_json((path.parent / "llm.json").read_bytes())
        strategy = document.definition.adaptors[0].combine
        assert isinstance(strategy, DebateJudgeStrategy)
        assert strategy.judge_output == "synthesize" and strategy.synthesize_count == 1
        routes = locked_judge_routes(config.judge)
        assert routes is not None
        admit_llm_adaptors(document.definition.adaptors, routes, None, bodies=1, stop_calls=0)
        composition = compose_run_task_bindings(document.definition.task.manifest)
        control = tmp_path / "workspace/candidate_run"
        control.mkdir(parents=True)
        for index, observation in enumerate(request.files):
            (control / f"input_{index:03}.snapshot").write_bytes(
                Path(observation.path).read_bytes()
            )
        inputs = materialize_fanout(request, tmp_path / "workspace", composition, config)
        reviews = [item for item in inputs.values() if isinstance(item, LiteratureReviewInput)]
        assert len(reviews) == 3
        assert (
            len(
                {
                    (tuple(p.identifier for p in r.root_papers), r.dynamic_search.enabled)
                    for r in reviews
                }
            )
            == 3
        )
        assert not (tmp_path / "workspace" / request.run_name).exists()


def test_research_loop_example_resolves_with_declared_advice(tmp_path: Path) -> None:
    """Defect: editable source validates but cannot prepare, or advice has no socket.

    The source parser and reusable preflight must preserve the advice through the
    real generated protocol binding; no generated expert_context file is needed.
    """
    source = (EXAMPLES / "research_loop_request_input.py").read_text(encoding="utf-8")
    document = parse_workflow_source(source)
    assert isinstance(document, ReusableWorkflowDocument)
    imported = runpy.run_path(str(EXAMPLES / "research_loop_request_input.py"))["document"]
    assert imported == document
    assert inspect_declaration(document).status == "declaration_validated"
    (tmp_path / "workflow.py").write_text(source, encoding="utf-8")
    (tmp_path / "task.yaml").symlink_to(REPO / "configs/task_composition/quickstart.yaml")
    (tmp_path / "data").mkdir()
    (tmp_path / "runs").mkdir()
    (tmp_path / "llm.json").write_text('{"tune":{"planner_strategy":"native-timing-v1"}}')
    request = ReusableCandidatePreparationRequest(
        source_path=str(tmp_path / "workflow.py"),
        project_root=str(tmp_path),
        expected_source_sha256=hashlib.sha256(source.encode()).hexdigest(),
        runs_root=str(tmp_path / "runs"),
        run_id=uuid4(),
        run_name="research_loop",
        llm_config_file=str(tmp_path / "llm.json"),
        preparation_timeout_seconds=120,
        candidate_timeout_seconds=3600,
        task_read_only=(str(REPO),),
        candidate_network=True,
        candidate_devices=(),
        candidate_environment_names=("OPENAI_API_KEY",),
    )
    plan = preflight_reusable_candidate(request)
    assert plan.binding.request.proposal_advice == document.preparation_options.proposal_advice
    assert plan.binding.request.proposal_advice
    resolved = plan.resolved_document.definition
    shape = execution_families(resolved, document.execution_profile)
    assert shape.tuning == "tuning" and shape.interpretation is not None
    assert resolved.loop is not None and resolved.loop.final_iteration == 3
    stop = resolved.loop.stop_conditions[0]
    assert isinstance(stop, NoImprovementStop)
    assert stop.on_met == "request_input" and stop.completed_bodies == 1
    advice = next(binding for binding in resolved.externals if binding.id == "advice")
    assert advice.location.endswith("/inputs/external.advice.json")
    proposal = next(node for node in resolved.nodes if node.id == "proposal")
    assert isinstance(proposal.request, ProtocolRequest)
    arguments = {argument.name: argument.source for argument in proposal.request.arguments}
    assert arguments["human_advice"] == ExternalSource(binding=advice.id)
    assert "expert_context" not in arguments
