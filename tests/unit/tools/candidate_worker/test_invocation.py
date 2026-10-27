"""Production extraction witnesses: identity loss, transport loss and phase bypass."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from tools.candidate_worker import launch_candidate

from .conftest import refresh
from .test_native import native_runner as native_runner


def test_fixed_sequence_consumes_declared_invocations_and_native_context(
    prepared, native_runner, monkeypatch
):
    """Fails if the actual worker bypasses a phase, loses enrichment, or rewrites records."""
    from core.hardware_context import HardwareContext
    from tools.candidate_worker import inputs as materialization
    from tools.candidate_worker import phases
    from workflows.task_composition import (
        active_composition_fingerprint,
        active_task_manifest_path,
        compose_run_task_bindings,
    )

    project = Path(prepared.preview.project_root)
    seed = json.loads((project / "seed.json").read_text())
    seed["hardware_context"] = HardwareContext(
        device_name="cpu",
        total_memory_bytes=0,
        compute_capability=(0, 0),
        multiprocessor_count=0,
        torch_version="fixture",
        hostname="fixture",
        device_available=False,
        discovered_at="2026-01-01T00:00:00Z",
    ).model_dump(mode="json")
    seed["vram_budget_gb"] = 2.5
    seed["constraint_context"] = {
        "known_sections": ["objective"],
        "objective": seed["task_composition_ref"]["objective"],
    }
    seed["reasoning_pipeline"] = {
        "stages": [{"name": "causal_reasoning", "system_prompt_key": "CAUSAL_REASONING"}]
    }
    lineage = [
        {
            "component": "linear_projection",
            "source_type": "human",
            "source_id": "human:fixture",
            "contribution_evidence": "Preserve both output logits.",
        }
    ]
    generate = native_runner.generate

    def generate_with_lineage(self, system, user, **kwargs):
        if kwargs.get("label") == "proposer.causal_reasoning":
            self.calls.append((kwargs["label"], self.context))
            return {"inherited_components": lineage}
        return generate(self, system, user, **kwargs)

    monkeypatch.setattr(native_runner, "generate", generate_with_lineage)
    (project / "seed.json").write_text(json.dumps(seed))
    request = refresh(
        prepared.model_copy(
            update={
                "implementation_advice": "Keep the four feature interface.",
                "validation_advice": "Check both output logits.",
            }
        )
    )
    # Declaration IDs select instances; neither binding helper may assume role names.
    document = request.preview.document.model_dump(mode="json")
    renamed = {"propose": "idea_node", "implement": "build_node", "validate": "check_node"}
    for node in document["definition"]["nodes"]:
        node["id"] = renamed[node["id"]]
        for argument in node["request"].get("arguments", []):
            source = argument["source"]
            if source["kind"] == "result":
                source["node"] = renamed[source["node"]]
    changed = type(request.preview.document).model_validate_json(json.dumps(document))
    request = refresh(
        request.model_copy(
            update={"preview": request.preview.model_copy(update={"document": changed})}
        )
    )
    selected = {}
    proposal_binding = materialization.materialize_proposal
    protocol_binding = materialization.reconcile_protocol_inputs

    def proposal_inputs(payload, **kwargs):
        selected["proposal_storage"] = kwargs["proposal_storage"]
        selected["data_root"] = kwargs["data_root"]
        return proposal_binding(payload, **kwargs)

    def protocol_inputs(protocols, **kwargs):
        selected["protocol_sources"] = [
            argument.source.node
            for protocol in protocols
            for argument in protocol.arguments
            if argument.name == "output"
        ]
        selected["attempt"] = kwargs["attempt"]
        return protocol_binding(protocols, **kwargs)

    monkeypatch.setattr(materialization, "materialize_proposal", proposal_inputs)
    monkeypatch.setattr(materialization, "reconcile_protocol_inputs", protocol_inputs)
    composition = compose_run_task_bindings(request.preview.document.definition.task.manifest)
    seen, calls, originals = [], {}, {}
    for phase, agent_type in (
        ("proposal", phases.MLModelProposalAgent),
        ("implementation", phases.MLModelImplementor),
        ("validation", phases.MLCodeValidatorAgent),
    ):
        original_run = agent_type.run

        def observe(self, value, *, _phase=phase, _run=original_run):
            assert active_composition_fingerprint() == composition.semantic_fingerprint
            assert active_task_manifest_path() == composition.provenance.manifest_path
            calls[_phase] = value.model_copy(deep=True)
            output = _run(self, value)
            # Native nodes normally write first; the phase boundary must preserve those bytes.
            names = {
                "proposal": "proposal",
                "implementation": "implementor",
                "validation": "validation",
            }
            path = Path(value.storage.local.workspace) / f"{names[_phase]}_candidate.json"
            originals[_phase] = (path, path.read_bytes())
            return output

        monkeypatch.setattr(agent_type, "run", observe)
        original_phase = getattr(phases, f"run_{phase}")

        def invoke(context, *args, _phase=phase, _run=original_phase):
            seen.append((context, _phase))
            return _run(context, *args)

        monkeypatch.setattr(phases, f"run_{phase}", invoke)

    receipt = launch_candidate(request)
    assert receipt.status == "accepted", receipt.error
    assert [(context.node_id, phase) for context, phase in seen] == [
        ("idea_node", "proposal"),
        ("build_node", "implementation"),
        ("check_node", "validation"),
    ]
    assert all(
        (context.workspace, context.run_name, context.run_id, context.iteration, context.attempt)
        == (receipt.workspace, "candidate", receipt.run_id, 1, 1)
        for context, _ in seen
    )
    proposal, implementation, validation = (
        calls[name] for name in ("proposal", "implementation", "validation")
    )
    assert selected["protocol_sources"] == ["idea_node", "build_node"]
    assert selected["proposal_storage"] == proposal.storage
    assert selected["attempt"].storage == implementation.storage
    assert selected["data_root"] == project / "data"
    assert implementation.task_composition_ref == proposal.task_composition_ref
    assert implementation.task_description == proposal.task_description
    assert implementation.forward_contract == proposal.forward_contract
    assert implementation.implementor_blocks == composition.implementor_blocks
    assert implementation.hardware_context == proposal.hardware_context
    assert implementation.vram_budget_gb == 2.5
    assert (
        implementation.constraint_context
        == validation.constraint_context
        == proposal.constraint_context
    )
    assert implementation.human_advice == "Keep the four feature interface."
    assert (
        implementation.reference_code == {} and implementation.previous_validation_failure is None
    )
    assert validation.human_advice == "Check both output logits."
    assert [item.model_dump() for item in validation.inherited_components] == [
        {**lineage[0], "from_run": None}
    ]
    assert validation.model_io_contract == proposal.forward_contract.model_io
    assert (validation.llm_provider, validation.llm_model_id) == ("openai", "validate-test")
    assert implementation.storage == validation.storage
    assert [str(originals[phase][0]) for _, phase in seen] == list(receipt.native_output_paths)
    assert all(path.read_bytes() == content for path, content in originals.values())
    assert all(
        context is not None
        and context["run_id"] == receipt.run_id
        and context["run_name"] == "candidate"
        and context["iter"] == 1
        and str(context["workspace"]) == receipt.workspace
        for _, context in native_runner.calls
    )


@pytest.mark.parametrize("phase", ["proposal", "implementation", "validation"])
@pytest.mark.parametrize("fault", ["node", "phase", "run", "workspace", "storage", "storage_run"])
def test_phase_binding_refuses_before_native_call(
    prepared, native_runner, monkeypatch, phase, fault
):
    """Fails if a wrong invocation identity reaches construction or a paid native call."""
    from tools.candidate_worker import phases

    original = getattr(phases, f"run_{phase}")
    expected = {
        "node": "node/phase",
        "phase": "node/phase",
        "run": "run",
        "workspace": "run",
        "storage": "storage",
        "storage_run": "storage",
    }[fault]
    constructors = []
    agent_name = {
        "proposal": "MLModelProposalAgent",
        "implementation": "MLModelImplementor",
        "validation": "MLCodeValidatorAgent",
    }[phase]

    def constructed(**kwargs):
        constructors.append(kwargs)
        raise AssertionError("binding refusal happened after agent construction")

    monkeypatch.setattr(phases, agent_name, constructed)

    def corrupt(context, *args):
        changes = {
            "node": {"node_id": "foreign_node"},
            "phase": {"phase": "validation" if phase != "validation" else "implementation"},
            "run": {"run_id": "foreign_run"},
            "workspace": {"workspace": str(Path(context.workspace) / "other")},
            "storage": {"storage_workspace": str(Path(context.storage_workspace) / "other")},
            "storage_run": {"storage_run_name": "foreign_run"},
        }[fault]
        return original(replace(context, **changes), *args)

    monkeypatch.setattr(phases, f"run_{phase}", corrupt)
    receipt = launch_candidate(prepared)
    assert receipt.status == "failed"
    assert f"native invocation {expected} binding disagrees" in receipt.error
    assert constructors == []
    if phase == "proposal":
        assert not native_runner.calls


@pytest.mark.parametrize("fault", ["artifact", "record"])
def test_extracted_implementation_verification_precedes_validation(
    prepared, native_runner, monkeypatch, fault
):
    """Fails when relocation bypasses artifact/record owners or overwrites a native record."""
    from tools.candidate_worker import phases

    original = phases.MLModelImplementor.run
    recorded = []
    validators = []

    def implement(self, value):
        output = original(self, value)
        path = Path(value.storage.local.workspace) / "implementor_candidate.json"
        recorded.append((path, path.read_bytes()))
        field = "test_file_path" if fault == "artifact" else "model_description"
        changed = (
            str(Path(prepared.preview.project_root) / "foreign_test.py")
            if fault == "artifact"
            else "foreign description"
        )
        return output.model_copy(update={field: changed})

    def validator(**kwargs):
        validators.append(kwargs)
        raise AssertionError("unverified implementation reached validator construction")

    monkeypatch.setattr(phases.MLModelImplementor, "run", implement)
    monkeypatch.setattr(phases, "MLCodeValidatorAgent", validator)
    receipt = launch_candidate(prepared)
    assert receipt.status == "failed"
    expected = (
        "native artifact escapes declared roots"
        if fault == "artifact"
        else "native record disagrees with returned output"
    )
    assert expected in receipt.error
    assert len(recorded) == 1 and validators == []
    assert recorded[0][0].read_bytes() == recorded[0][1]


@pytest.mark.parametrize("graph", [False, True])
def test_native_proposal_iterations_preserve_records_and_accounting(
    prepared, native_runner, monkeypatch, graph
):
    """A second native phase must neither overwrite the first nor charge its iteration."""
    from agent.schemas.storage import LocalStorageConfig, StorageConfig
    from tests.helpers.candidate_fanout import fanout_request
    from tools.candidate_worker.inputs import NativeInputs, materialize_proposal
    from tools.candidate_worker.invocation import invocation_from_storage
    from tools.candidate_worker.layout import (
        candidate_proposal_dir,
        graph_instance_dir,
        proposal_debug_dir,
    )
    from tools.candidate_worker.phases import run_proposal
    from workflows.attempt_storage import impl_attempt_storage
    from workflows.llm_config import WorkflowLLMConfig
    from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

    from .test_graph import initial

    request = fanout_request(prepared) if graph else prepared
    receipt = initial(request)
    workspace = Path(receipt.workspace)
    project = Path(request.preview.project_root)
    composition = compose_run_task_bindings(request.preview.document.definition.task.manifest)
    config = WorkflowLLMConfig.model_validate_json((project / "llm.json").read_bytes())
    originals = {}
    with bind_run_task_composition(composition, physical_data_root=str(project / "data")):
        for iteration in (1, 2):
            directory = (
                graph_instance_dir(workspace, request.run_name, "propose", iteration=iteration)
                if graph
                else candidate_proposal_dir(workspace, request.run_name, iteration=iteration)
            )
            storage = StorageConfig(
                backend="local",
                local=LocalStorageConfig(workspace=str(directory), run_name=request.run_name),
            )
            # Build independent inputs from the declared seed, never retarget a capture.
            raw = json.loads((project / "seed.json").read_bytes())
            debug_root = proposal_debug_dir(
                workspace, request.preview.execution_profile, "propose", iteration=iteration
            )
            raw["debug_dump_proposing_prompt_path"] = str(debug_root / "prompt.md")
            seed, _ = materialize_proposal(
                json.dumps(raw).encode(),
                proposal_storage=storage,
                composition=composition,
                data_root=project / "data",
                control=workspace / "candidate_run",
                debug_root=debug_root,
            )
            inputs = NativeInputs(
                proposal=seed,
                attempt=impl_attempt_storage(str(directory), request.run_name, 1),
                validator_provider="openai",
                validator_model="validate-test",
            )
            context = invocation_from_storage(
                receipt, node_id="propose", phase="proposal", storage=storage, iteration=iteration
            )
            if iteration == 2:
                with monkeypatch.context() as patch:
                    patch.setattr(
                        "tools.candidate_worker.phases.MLModelProposalAgent",
                        lambda **kwargs: pytest.fail("crossed iteration reached constructor"),
                    )
                    with pytest.raises(ValueError, match="storage binding"):
                        run_proposal(
                            replace(context, iteration=1), request, receipt, inputs, config
                        )
                assert not directory.exists()
                assert not (workspace / "candidate_run/iteration_002").exists()
            _, record = run_proposal(context, request, receipt, inputs, config)
            diagnostic = workspace / "candidate_run"
            if iteration == 2:
                diagnostic /= "iteration_002"
            diagnostic /= "proposal_input.json"
            assert record == directory / "proposal_candidate.json"
            assert json.loads(diagnostic.read_bytes())["storage"] == storage.model_dump(mode="json")
            assert json.loads(diagnostic.read_bytes())["debug_dump_proposing_prompt_path"] == str(
                debug_root / "prompt.md"
            )
            assert all(path.read_bytes() == content for path, content in originals.items())
            originals.update({record: record.read_bytes(), diagnostic: diagnostic.read_bytes()})
    contexts = [context for _, context in native_runner.calls]
    assert {context["iter"] for context in contexts} == {1, 2}
    assert all(context["run_id"] == receipt.run_id for context in contexts)
    assert len(originals) == 4
