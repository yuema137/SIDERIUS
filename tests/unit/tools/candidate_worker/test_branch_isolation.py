"""Branch isolation: an independent family cannot observe a sibling's earlier effects.

B3 may dispatch independent graph units concurrently only if no unit reads
state an independent sibling wrote during the same body. Serial readiness
runs the first ready node in declaration order, so declaration order decides
whether family 1 runs before, between or after family 0's nodes. Family 1's
typed proposal input, every rendered prompt of its proposal, implementation
and validation nodes, its proposal debug dump and its normalized native
records must not depend on that order, and no node may change the process
model/loss registries a later sibling would read.

Native node bodies, plugin files, the workspace generated library and process
registries are real. ``LLMBridge`` is replaced by the scripted provider, so
this test does not exercise the token ledger; ledger isolation is established
by source reading (see the candidate-worker contract).
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from tests.helpers.candidate_fanout import families_request
from tools.candidate_worker import launch_candidate
from tools.workflow_preview import preview_workflow
from tools.workflow_preview.models import WorkflowPreviewRequest

from .conftest import QUICKSTART, _prepare_request
from .test_native import native_runner

SIBLING_FIRST = ("propose0", "build0", "check0", "propose1", "build1", "check1")
PROPOSALS_FIRST = ("propose0", "propose1", "build0", "check0", "build1", "check1")
FAMILY_FIRST = ("propose1", "build1", "check1", "propose0", "build0", "check0")
OBSERVED = ("propose1", "build1", "check1")
RECORDS = ("proposal_candidate.json", "implementor_candidate.json", "validation_candidate.json")
VOLATILE = frozenset(("candidate_id", "test_output", "created_at", "timestamp"))
PHASES = ("run_proposal", "run_implementation", "run_validation")


def registries() -> dict[str, dict]:
    """Every process-global plugin registry a later node could read."""
    from ml_models import (
        loss_models_sandbox,
        loss_plugin_loader,
        models_format_sandbox,
        models_sandbox,
        plugin_loader,
    )

    return {
        "MODEL_REGISTRY": models_sandbox.MODEL_REGISTRY,
        "PLUGIN_CONFIG_REGISTRY": models_format_sandbox.PLUGIN_CONFIG_REGISTRY,
        "PLUGIN_OUTPUT_TYPE_REGISTRY": plugin_loader.PLUGIN_OUTPUT_TYPE_REGISTRY,
        "_PLUGIN_MODEL_ORIGINS": plugin_loader._PLUGIN_MODEL_ORIGINS,
        "LOSS_REGISTRY": loss_models_sandbox.LOSS_REGISTRY,
        "LOSS_CONFIG_REGISTRY": loss_models_sandbox.LOSS_CONFIG_REGISTRY,
        "LOSS_CONTRACT_REGISTRY": loss_models_sandbox.LOSS_CONTRACT_REGISTRY,
        "LOSS_TARGET_DTYPE_REGISTRY": loss_plugin_loader.LOSS_TARGET_DTYPE_REGISTRY,
        "LOSS_REDUCTION_REGISTRY": loss_plugin_loader.LOSS_REDUCTION_REGISTRY,
    }


def registry_state() -> dict[str, dict]:
    return {name: dict(registry) for name, registry in registries().items()}


def restore(state: dict[str, dict]) -> None:
    """In place, so modules holding a direct reference see the reset."""
    for name, registry in registries().items():
        registry.clear()
        registry.update(state[name])


@pytest.fixture
def pristine_registries() -> Iterator[dict[str, dict]]:
    """One snapshot before the first run; each run is one worker process."""
    state = registry_state()
    try:
        yield state
    finally:
        restore(state)


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
    (root / "project" / "data").mkdir(parents=True)
    return _prepare_request(
        root / "project",
        root / "workspace",
        compose_run_task_bindings,
        build_task_composition_ref,
        ProposalInput,
        ProposerInterpretationEvidence,
    )


@contextmanager
def observed_run(monkeypatch, provider):
    """Track node identity, family-1 prompts, dispatch order and registry writes."""
    from tools.candidate_worker import phases

    seen: dict = {"node": None, "sequence": [], "prompts": [], "registry_writes": []}
    original_generate, original_text = provider.generate, provider.generate_text

    def record(system, user, kwargs):
        if seen["node"] in OBSERVED:
            seen["prompts"].append((seen["node"], kwargs.get("label", ""), system, user))

    def generate(self, system, user, **kwargs):
        record(system, user, kwargs)
        output = original_generate(self, system, user, **kwargs)
        if isinstance(output, dict) and "model_name" in output:
            family = seen["node"][-1]
            output = {
                **output,
                "model_name": f"worker_linear_{family}",
                "model_description": f"{output['model_description']} Family {family}.",
            }
        return output

    def generate_text(self, system, user, **kwargs):
        record(system, user, kwargs)
        return original_text(self, system, user, **kwargs)

    def tracked(phase):
        def run(context, *args, **kwargs):
            seen["node"] = context.node_id
            seen["sequence"].append(context.node_id)
            before = registry_state()
            try:
                return phase(context, *args, **kwargs)
            finally:
                if registry_state() != before:
                    seen["registry_writes"].append(context.node_id)
                seen["node"] = None

        return run

    with monkeypatch.context() as patch:
        patch.setattr(provider, "generate", generate)
        patch.setattr(provider, "generate_text", generate_text)
        for name in PHASES:
            patch.setattr(phases, name, tracked(getattr(phases, name)))
        yield seen


def stable(value, normalized):
    if isinstance(value, dict):
        return {
            key: stable(item, normalized)
            for key, item in value.items()
            if key not in VOLATILE and not key.endswith(("_path", "_dir", "_seconds"))
        }
    if isinstance(value, list):
        return [stable(item, normalized) for item in value]
    return normalized(value) if isinstance(value, str) else value


def observe_family(request, order, monkeypatch, provider, pristine):
    """Run one body from pristine registries; return family 1's normalized view."""
    restore(pristine)
    with observed_run(monkeypatch, provider) as seen:
        receipt = launch_candidate(declared_in(families_request(request), order))
    assert receipt.status == "accepted", receipt.error
    assert tuple(seen["sequence"]) == order
    assert seen["registry_writes"] == []
    workspace, project = receipt.workspace, request.preview.project_root
    control = Path(workspace) / "candidate_run"
    # Shared discovery roots a later sibling's proposer/implementor consults.
    library = Path(workspace) / "generated_library"
    assert not library.exists() or not any(library.rglob("*"))
    assert not (Path(workspace) / "plugins").exists()

    def normalized(text: str) -> str:
        return text.replace(workspace, "<workspace>").replace(project, "<project>")

    paths = {item.node_id: Path(item.record_path) for item in receipt.graph_trace.nodes}
    records = {node: stable(json.loads(paths[node].read_bytes()), normalized) for node in OBSERVED}
    assert sorted(paths[node].name for node in OBSERVED) == sorted(RECORDS)
    assert records["propose1"]["model_name"] == "worker_linear_1"
    return {
        "input": normalized((control / "proposal_inputs" / "propose1.json").read_text()),
        "prompts": [tuple(normalized(part) for part in call) for call in seen["prompts"]],
        "debug": normalized((control / "debug" / "propose1" / "prompt.md").read_text()),
        "records": records,
    }


def test_sibling_branch_effects_never_reach_an_independent_family(
    prepared, native_runner, monkeypatch, tmp_path, pristine_registries
):
    """Fails if family 0's effects (plugin files, descriptions, capability index,
    process registries) change what any family-1 node reads or records, or if
    any node leaves a process-registry write behind for a later sibling."""
    runs = [
        observe_family(prepared, SIBLING_FIRST, monkeypatch, native_runner, pristine_registries),
        *(
            observe_family(
                another_prepared(tmp_path, name),
                order,
                monkeypatch,
                native_runner,
                pristine_registries,
            )
            for name, order in (
                ("proposals_first", PROPOSALS_FIRST),
                ("family_first", FAMILY_FIRST),
            )
        ),
    ]
    assert {call[0] for call in runs[0]["prompts"]} == set(OBSERVED)
    assert runs[0] == runs[1]
    assert runs[0] == runs[2]
