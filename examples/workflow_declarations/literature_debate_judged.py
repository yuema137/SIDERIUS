"""Run A: write a concrete v1 request for three reviews and one debate synthesis.

From the checkout root, after the README's data/credential setup (SCENARIO is an
external directory, MODEL is an OpenAI model available to your account):

    .venv/bin/python examples/workflow_declarations/literature_debate_judged.py \
        --project "$SCENARIO/run-a-inputs" --data "$SCENARIO/data" \
        --workspace "$SCENARIO/run-a" --model "$MODEL"
    .venv/bin/python -m tools.candidate_worker \
        --request "$SCENARIO/run-a-inputs/candidate_request.json" \
        > "$SCENARIO/run-a-receipt.json"

Preparation is offline; the second command retrieves papers and calls providers.
The merged LiteratureReviewOutput is written to
$SCENARIO/run-a/candidate_run/adaptors/judge.out.result.json. Read its findings
array, preserve citations/caveats, and paste a trimmed summary into
preparation_options.proposal_advice in run B's workflow.py BEFORE preparing B.
Use at most 4000 characters in this example so the text also fits Resume advice.
There is no file-backed expert_context handoff. See README.md for extraction.

S2_API_KEY is optional: without a key, Semantic Scholar paper lookup uses the
unauthenticated pool and may be rate-limited. To use it, add "S2_API_KEY" to the
generated candidate_request.json's environment_names before launch and bind the
key in the launching shell; never put its value in the request. The generator
passes only OPENAI_API_KEY by default.

Run A has no authored loop and cannot pause/resume. For run B's preparation,
operation ID, pause and write-loop-resume --advice-file commands, follow
research_loop_request_input.py and the ordered recipe in README.md.
"""

import argparse
from pathlib import Path

from agent.schemas.literature_review import (
    DynamicSearchConfig,
    LiteratureReviewInput,
    LiteratureReviewInterpretationEvidence,
    PaperSource,
)
from agent.schemas.proposal import ProposalInput
from agent.schemas.proposer_evidence import ProposerInterpretationEvidence
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from tools.candidate_worker import CandidateRunRequest
from tools.candidate_worker.layout import graph_instance_dir
from tools.workflow_preview import WorkflowPreviewRequest, preview_workflow
from workflows.definition import (
    AdaptorInstance,
    AdaptorSource,
    AllSelect,
    ArgumentBinding,
    ExternalBinding,
    ExternalRequest,
    ExternalSource,
    InputPort,
    NodeInstance,
    PortBinding,
    ProtocolRequest,
    ResultSource,
    SingleDistribute,
    TaskReferences,
    WorkflowDefinition,
    WorkflowDocument,
)
from workflows.definition.llm_strategies import DebateJudgeStrategy
from workflows.llm_config import (
    JudgeLLMConfig,
    JudgeRouteConfig,
    LitReviewLLMConfig,
    NodeLLMConfig,
    ProposalLLMConfig,
    TunerLLMConfig,
    WorkflowLLMConfig,
)
from workflows.task_composition import build_task_composition_ref, compose_run_task_bindings


def write_example(project: Path, data: Path, workspace: Path, model: str) -> Path:
    """Write fresh inputs and an observed request; never call a provider or launch."""
    project, data, workspace = (path.resolve() for path in (project, data, workspace))
    if workspace.is_relative_to(project) or project.is_relative_to(workspace):
        raise ValueError("project inputs and workspace must be separate directories")
    if not data.is_dir():
        raise ValueError("data must be an existing Quickstart dataset directory")
    repo = Path(__file__).resolve().parents[2]
    manifest = repo / "configs/task_composition/quickstart.yaml"
    composition = compose_run_task_bindings(str(manifest))
    seed = ProposalInput(
        interpretation_evidence=ProposerInterpretationEvidence(),
        cold_start=True,
        task_description=composition.task_description,
        forward_contract=composition.forward_contract,
        proposal_blocks=composition.proposal_blocks,
        task_composition_ref=build_task_composition_ref(composition),
        data_dir=str(data),
        allowed_output_types=("classifier",),
        trial_time_budget_minutes=2.0,
        formal_time_budget_minutes=5.0,
    )
    route = NodeLLMConfig(provider="openai", model_id=model, max_retries=1)
    judge_route = JudgeRouteConfig(
        provider="openai", model_id=model, max_output_tokens=8192, max_retries=1
    )
    config = WorkflowLLMConfig(
        interpret=route,
        propose=ProposalLLMConfig(comparison=route, reasoning=route, proposing=route),
        implement=route,
        validate=route,
        tune=TunerLLMConfig(planner_strategy="native-timing-v1", planner=route, reflector=route),
        lit_review=LitReviewLLMConfig(main=route, search=route),
        # One round: three advocates + one critic + one synthesis verdict = five.
        judge=JudgeLLMConfig(debate=judge_route, max_judge_calls=5),
    )
    run_name = "literature_debate"

    def storage(node: str, *, implementation: bool = False) -> StorageConfig:
        path = graph_instance_dir(workspace, run_name, node)
        if implementation:
            path /= "impl_001"
        return StorageConfig(
            backend="local", local=LocalStorageConfig(workspace=str(path), run_name=run_name)
        )

    # Distinct evidence searches, not unsupported per-review advice prompts.
    review_settings = (
        ("optimization", [PaperSource(source_type="arxiv", identifier="1412.6980")], False),
        ("regularization", [PaperSource(source_type="arxiv", identifier="1711.05101")], False),
        ("search", [], True),
    )
    payloads = {
        "seed": seed.model_dump_json(indent=2, exclude={"storage"}),
        "storage": storage("implementation", implementation=True).model_dump_json(indent=2),
        "llm": config.model_dump_json(indent=2, by_alias=True),
    }
    externals = [
        ExternalBinding(id="seed", contract="proposal.input", location="seed.json"),
        ExternalBinding(id="storage", contract="storage", location="storage.json"),
    ]
    nodes = []
    for name, papers, search in review_settings:
        review = LiteratureReviewInput(
            interpretation_evidence=LiteratureReviewInterpretationEvidence(cold_start=True),
            root_papers=papers,
            dynamic_search=DynamicSearchConfig(
                enabled=search, max_rounds=1, results_per_query=3, escalation_allowed=False
            ),
            storage=storage(name),
            run_name=run_name,
            task_description=composition.task_description,
            constraint_context=seed.constraint_context,
            llm_provider="openai",
            llm_model_id=model,
            llm_max_retries=1,
            search_llm_provider="openai",
            search_llm_model_id=model,
        )
        payloads[name] = review.model_dump_json(indent=2)
        externals.append(
            ExternalBinding(id=name, contract="literature.input", location=f"{name}.json")
        )
        nodes.append(
            NodeInstance(id=name, capability="literature", request=ExternalRequest(binding=name))
        )
    nodes.extend(
        (
            NodeInstance(
                id="proposal",
                capability="proposal",
                request=ProtocolRequest(
                    protocol="literature-to-proposal",
                    arguments=(
                        ArgumentBinding(name="output", source=AdaptorSource(adaptor="judge")),
                        ArgumentBinding(
                            name="proposal_input", source=ExternalSource(binding="seed")
                        ),
                    ),
                ),
            ),
            NodeInstance(
                id="implementation",
                capability="implementation",
                request=ProtocolRequest(
                    protocol="proposal-to-implementation",
                    arguments=(
                        ArgumentBinding(name="output", source=ResultSource(node="proposal")),
                        ArgumentBinding(name="storage", source=ExternalSource(binding="storage")),
                    ),
                ),
            ),
            NodeInstance(
                id="validation",
                capability="validation",
                request=ProtocolRequest(
                    protocol="proposed-implementation-to-validation",
                    arguments=(
                        ArgumentBinding(name="proposal", source=ResultSource(node="proposal")),
                        ArgumentBinding(
                            name="implementation", source=ResultSource(node="implementation")
                        ),
                        ArgumentBinding(name="storage", source=ExternalSource(binding="storage")),
                    ),
                ),
            ),
        )
    )
    document = WorkflowDocument(
        definition=WorkflowDefinition(
            task=TaskReferences(
                manifest=str(manifest), data_root=str(data), workspace=str(workspace)
            ),
            externals=tuple(externals),
            nodes=tuple(nodes),
            adaptor_format="siderius.adaptors/v1",
            adaptors=(
                AdaptorInstance(
                    id="judge",
                    inputs=(
                        InputPort(
                            name="reviews",
                            contract="literature.output",
                            cardinality="many",
                            max_items=3,
                        ),
                    ),
                    bindings=(
                        PortBinding(
                            port="reviews",
                            sources=tuple(
                                ResultSource(node=name) for name, _, _ in review_settings
                            ),
                        ),
                    ),
                    combine=DebateJudgeStrategy(
                        route_slot="debate",
                        max_calls=5,
                        guidance="none",
                        criterion="Synthesize one merged set of key findings for the four-feature Quickstart classifier. Retain source references, disagreements and transfer caveats; prioritize actionable, bounded changes.",
                        rounds=1,
                        critic=True,
                        judge_output="synthesize",
                        synthesize_count=1,
                    ),
                    select=AllSelect(),
                    distribute=SingleDistribute(),
                ),
            ),
        )
    )
    payloads["workflow"] = document.model_dump_json(indent=2)
    project.mkdir(parents=True, exist_ok=True)
    for name, payload in payloads.items():
        with (project / f"{name}.json").open("x", encoding="utf-8") as stream:
            stream.write(payload + "\n")
    preview = WorkflowPreviewRequest(
        document=document,
        project_root=str(project),
        llm_config_file="llm.json",
        execution_profile="native-literature-judged/v1",
    )
    observed = preview_workflow(preview)
    request = CandidateRunRequest(
        preview=preview,
        declaration_digest=document.definition.declaration_digest(),
        files=observed.files,
        selected_constructor_routes=observed.selected_constructor_routes,
        storage_policy="managed_fresh",
        run_name=run_name,
        timeout_seconds=3600.0,
        network=True,
        devices=(),
        read_only=(str(project), str(data), str(repo)),
        environment_names=("OPENAI_API_KEY",),
    )
    path = project / "candidate_request.json"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(request.model_dump_json(indent=2) + "\n")
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("project", "data", "workspace"):
        parser.add_argument(f"--{flag}", required=True, type=Path)
    parser.add_argument("--model", required=True, help="OpenAI model ID for every LLM route")
    args = parser.parse_args()
    print(write_example(args.project, args.data, args.workspace, args.model))
