"""Branch isolation: an independent family cannot observe a sibling's earlier effects.

B3 may dispatch independent graph units concurrently only if no unit reads
state an independent sibling wrote during the same body. Serial readiness
runs the first ready node in declaration order, so declaration order decides
whether family 1 runs before, between or after family 0's nodes. Family 1's
typed proposal input, every rendered prompt of its proposal, implementation
and validation nodes, and its proposal debug dump must not depend on that
order. Only the provider is scripted; node bodies, plugin files, the
workspace generated library and process registries are real.
"""

import json
from pathlib import Path

from tests.helpers.candidate_fanout import families_request
from tools.candidate_worker import launch_candidate
from tools.workflow_preview import preview_workflow
from tools.workflow_preview.models import WorkflowPreviewRequest

from .conftest import _prepare_request
from .test_native import native_runner

SIBLING_FIRST = ("propose0", "build0", "check0", "propose1", "build1", "check1")
PROPOSALS_FIRST = ("propose0", "propose1", "build0", "check0", "build1", "check1")
FAMILY_FIRST = ("propose1", "build1", "check1", "propose0", "build0", "check0")
OBSERVED = ("propose1", "build1", "check1")


def declared_in(request, order):
    """Reorder declared nodes only; readiness edges and bindings are unchanged."""
    raw = request.preview.model_dump(mode="json")
    nodes = {node["id"]: node for node in raw["document"]["definition"]["nodes"]}
    raw["document"]["definition"]["nodes"] = [nodes[node_id] for node_id in order]
    preview = WorkflowPreviewRequest.model_validate_json(json.dumps(raw))
    observed = preview_workflow(preview)
    return request.model_copy(
        update={
            "preview": preview,
            "files": observed.files,
            "declaration_digest": preview.document.definition.declaration_digest(),
            "selected_constructor_routes": observed.selected_constructor_routes,
        }
    )


def another_prepared(tmp_path, name):
    from agent.schemas.proposal import ProposalInput
    from agent.schemas.proposer_evidence import ProposerInterpretationEvidence
    from workflows.task_composition import build_task_composition_ref, compose_run_task_bindings

    root = tmp_path / name
    (root / "project").mkdir(parents=True)
    (root / "project" / "data").mkdir()
    return _prepare_request(
        root / "project",
        root / "workspace",
        compose_run_task_bindings,
        build_task_composition_ref,
        ProposalInput,
        ProposerInterpretationEvidence,
    )


def observe_family(request, order, monkeypatch, provider):
    """Run one body; return family 1's input, prompts and debug dump, path-normalized."""
    from ml_models import models_format_sandbox, models_sandbox, plugin_loader
    from tools.candidate_worker import phases

    # One candidate run is one worker process; reset process registries so
    # the two runs in this test cannot leak into each other.
    for module, name in (
        (models_format_sandbox, "PLUGIN_CONFIG_REGISTRY"),
        (models_sandbox, "MODEL_REGISTRY"),
        (plugin_loader, "PLUGIN_OUTPUT_TYPE_REGISTRY"),
    ):
        monkeypatch.setattr(module, name, dict(getattr(module, name)))
    prompts: list[tuple[str, str, str, str]] = []
    original_generate, original_text = provider.generate, provider.generate_text
    current: dict[str, str | None] = {"node": None}

    def record(system, user, kwargs):
        if current["node"] in OBSERVED:
            prompts.append((current["node"], kwargs.get("label", ""), system, user))

    def generate(self, system, user, **kwargs):
        record(system, user, kwargs)
        return original_generate(self, system, user, **kwargs)

    def generate_text(self, system, user, **kwargs):
        record(system, user, kwargs)
        return original_text(self, system, user, **kwargs)

    def tracked(phase):
        def run(context, *args, **kwargs):
            current["node"] = context.node_id
            try:
                return phase(context, *args, **kwargs)
            finally:
                current["node"] = None

        return run

    with monkeypatch.context() as patch:
        patch.setattr(provider, "generate", generate)
        patch.setattr(provider, "generate_text", generate_text)
        for name in ("run_proposal", "run_implementation", "run_validation"):
            patch.setattr(phases, name, tracked(getattr(phases, name)))
        receipt = launch_candidate(declared_in(families_request(request), order))
    assert receipt.status == "accepted", receipt.error
    ran = [item.node_id for item in receipt.graph_trace.nodes]
    assert sorted(ran) == sorted(order)
    workspace, project = receipt.workspace, request.preview.project_root
    control = Path(workspace) / "candidate_run"

    def normalized(text: str) -> str:
        return text.replace(workspace, "<workspace>").replace(project, "<project>")

    return {
        "input": normalized((control / "proposal_inputs" / "propose1.json").read_text()),
        "prompts": [tuple(normalized(part) for part in call) for call in prompts],
        "debug": normalized((control / "debug" / "propose1" / "prompt.md").read_text()),
    }


def test_sibling_branch_effects_never_reach_an_independent_family(
    prepared, native_runner, monkeypatch, tmp_path
):
    """Fails if family 0's effects (plugin files, descriptions, capability index,
    process registries, ledger) change what any family-1 node reads."""
    after_sibling = observe_family(prepared, SIBLING_FIRST, monkeypatch, native_runner)
    before_sibling_build = observe_family(
        another_prepared(tmp_path, "proposals_first"), PROPOSALS_FIRST, monkeypatch, native_runner
    )
    before_sibling = observe_family(
        another_prepared(tmp_path, "family_first"), FAMILY_FIRST, monkeypatch, native_runner
    )
    assert {call[0] for call in after_sibling["prompts"]} == set(OBSERVED)
    assert after_sibling == before_sibling_build
    assert after_sibling == before_sibling
