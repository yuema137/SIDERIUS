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
        ("propose", "proposal"),
        ("implement", "implementation"),
        ("validate", "validation"),
    ]
    assert all(
        (context.workspace, context.run_name, context.run_id, context.iteration, context.attempt)
        == (receipt.workspace, "candidate", receipt.run_id, 1, 1)
        for context, _ in seen
    )
    proposal, implementation, validation = (
        calls[name] for name in ("proposal", "implementation", "validation")
    )
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
