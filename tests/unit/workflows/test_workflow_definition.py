"""Declaration structure and native boundary drift checks, without execution."""

import inspect
import json
import subprocess
import sys
from collections.abc import Sequence
from typing import get_type_hints

import pytest
from pydantic import ValidationError

from workflows.definition import (
    ArgumentBinding,
    ExternalBinding,
    ExternalRequest,
    ExternalSource,
    NodeInstance,
    NodePosition,
    ProtocolRequest,
    ResultSource,
    TaskReferences,
    WorkflowDefinition,
    WorkflowDocument,
)
from workflows.definition.catalog import CAPABILITIES, CONTRACTS, PROTOCOLS


def definition():
    return WorkflowDefinition(
        task=TaskReferences(manifest="task/manifest.json", data_root="/data", workspace="runs/new"),
        externals=(
            ExternalBinding(id="seed", contract="proposal.input", location="inputs/proposal.json"),
            ExternalBinding(id="storage", contract="storage", location="inputs/storage.json"),
        ),
        nodes=(
            NodeInstance(
                id="propose", capability="proposal", request=ExternalRequest(binding="seed")
            ),
            NodeInstance(
                id="implement",
                capability="implementation",
                request=ProtocolRequest(
                    protocol="proposal-to-implementation",
                    arguments=(
                        ArgumentBinding(name="output", source=ResultSource(node="propose")),
                        ArgumentBinding(name="storage", source=ExternalSource(binding="storage")),
                    ),
                ),
            ),
            NodeInstance(
                id="validate",
                capability="validation",
                request=ProtocolRequest(
                    protocol="implementation-to-validation",
                    arguments=(
                        ArgumentBinding(name="output", source=ResultSource(node="implement")),
                        ArgumentBinding(name="storage", source=ExternalSource(binding="storage")),
                    ),
                ),
            ),
        ),
    )


def test_roundtrip_and_layout_independent_declaration_digest():
    graph = definition()
    document = WorkflowDocument(
        definition=graph, positions=(NodePosition(node="propose", x=1.0, y=2.0),)
    )
    assert WorkflowDocument.model_validate_json(document.model_dump_json()) == document
    layout_payload = document.model_dump(mode="json")
    layout_payload["positions"][0].update(x=500.0, y=-20.0)
    moved = WorkflowDocument.model_validate_json(json.dumps(layout_payload))
    assert moved.positions != document.positions
    assert moved.definition.declaration_digest() == document.definition.declaration_digest()
    payload = graph.model_dump(mode="json")
    payload["task"]["workspace"] = "runs/other"
    changed = WorkflowDefinition.model_validate_json(json.dumps(payload))
    assert changed.declaration_digest() != graph.declaration_digest()


def test_draft_optional_removal_and_external_disconnect_preserve_base():
    """Fails if optional disconnect nulls a payload, required external input survives, or base mutates."""
    from workflows.definition.draft import BindingPatch, WorkflowDraft, inspect_draft

    payload = WorkflowDocument(definition=definition()).model_dump(mode="json")
    payload["definition"]["externals"].append(
        {"id": "provider", "contract": "llm-provider", "location": "provider.json"}
    )
    payload["definition"]["nodes"][2]["request"]["arguments"].append(
        {"name": "llm_provider", "source": {"kind": "external", "binding": "provider"}}
    )
    base = WorkflowDocument.model_validate_json(json.dumps(payload))
    before = base.model_dump_json()
    optional = WorkflowDraft(
        base_document=base,
        bindings=(BindingPatch(node="validate", argument="llm_provider", source=None),),
    )
    result = inspect_draft(optional)
    assert result.status == "complete" and result.document is not None
    request = result.document.definition.nodes[2].request
    assert isinstance(request, ProtocolRequest)
    assert [item.name for item in request.arguments] == ["output", "storage"]
    required = inspect_draft(
        WorkflowDraft(
            base_document=base,
            bindings=(BindingPatch(node="propose", argument=None, source=None),),
        )
    )
    assert required.status == "incomplete" and required.document is None
    assert required.diagnostics == ("propose.request: required input is not connected",)
    assert base.model_dump_json() == before


def test_draft_problems_locate_each_legacy_diagnostic():
    """Fails if a draft problem loses its node/socket, or drops the legacy string.

    The editor's problems list selects ``node`` and focuses ``field``; the legacy
    ``diagnostics`` strings stay the compatibility surface for the same problems.
    """
    from workflows.definition.draft import BindingPatch, WorkflowDraft, inspect_draft

    base = WorkflowDocument(definition=definition())
    incomplete = inspect_draft(
        WorkflowDraft(
            base_document=base,
            bindings=(
                BindingPatch(node="propose", argument=None, source=None),
                BindingPatch(node="validate", argument="output", source=None),
            ),
        )
    )
    assert [(p.code, p.node, p.field) for p in incomplete.problems] == [
        ("required_unbound", "propose", "request"),
        ("required_unbound", "validate", "output"),
    ]
    assert incomplete.diagnostics == tuple(p.message for p in incomplete.problems)
    wrong_kind = inspect_draft(
        WorkflowDraft(
            base_document=base,
            bindings=(
                BindingPatch(node="propose", argument=None, source=ResultSource(node="validate")),
            ),
        )
    )
    assert wrong_kind.status == "invalid"
    assert [(p.code, p.node, p.field) for p in wrong_kind.problems] == [
        ("external_binding_required", "propose", "request")
    ]
    # A cycle passes the socket checks and is refused by the native validator.
    cycle = inspect_draft(
        WorkflowDraft(
            base_document=base,
            bindings=(
                BindingPatch(
                    node="implement", argument="output", source=ResultSource(node="validate")
                ),
            ),
        )
    )
    assert cycle.status == "invalid" and cycle.problems
    assert all(p.code == "declaration_invalid" and p.node is None for p in cycle.problems)
    assert all(p.message in cycle.diagnostics[0] for p in cycle.problems)


@pytest.mark.parametrize(
    "change,match",
    [
        (lambda p: p["nodes"][0].update(capability="tuner"), "Unsupported capability"),
        (lambda p: p["nodes"][0].update(config={"model": "anything"}), "Extra inputs"),
        (lambda p: p["nodes"][0]["request"].update(binding="absent"), "Unknown external"),
        (lambda p: p["externals"][0].update(contract="storage"), "request requires"),
        (lambda p: p["externals"].append(p["externals"][0]), "unique"),
        (lambda p: p["nodes"].append(p["nodes"][0]), "unique"),
        (lambda p: p["nodes"][1]["request"].update(protocol="feedback"), "Unsupported protocol"),
        (
            lambda p: p["nodes"][1]["request"].update(protocol="implementation-to-validation"),
            "does not produce",
        ),
        (lambda p: p["nodes"][1]["request"]["arguments"].pop(), "missing protocol"),
        (
            lambda p: p["nodes"][1]["request"]["arguments"].append(
                p["nodes"][1]["request"]["arguments"][0]
            ),
            "duplicate protocol",
        ),
        (
            lambda p: p["nodes"][1]["request"]["arguments"][0].update(name="arbitrary"),
            "unknown protocol",
        ),
        (
            lambda p: p["nodes"][1]["request"]["arguments"][0]["source"].update(node="absent"),
            "Unknown source",
        ),
        (
            lambda p: p["nodes"][1]["request"]["arguments"][0]["source"].update(node="validate"),
            "requires proposal.output",
        ),
        (
            lambda p: p["nodes"][1]["request"]["arguments"][0]["source"].update(port="field"),
            "result",
        ),
        (lambda p: p["externals"][0].update(contract="custom.Import"), "Unsupported external"),
    ],
)
def test_invalid_declarations_fail_atomically(change, match):
    payload = definition().model_dump(mode="json")
    change(payload)
    with pytest.raises(ValidationError, match=match):
        WorkflowDefinition.model_validate_json(json.dumps(payload))


def test_optional_arguments_and_result_reuse():
    payload = definition().model_dump(mode="json")
    payload["externals"].append(
        {"id": "context", "contract": "optional.constraint-context", "location": "context.json"}
    )
    payload["nodes"][1]["request"]["arguments"].append(
        {"name": "constraint_context", "source": {"kind": "external", "binding": "context"}}
    )
    branch = dict(payload["nodes"][1], id="second_implementor")
    payload["nodes"].append(branch)
    assert len(WorkflowDefinition.model_validate_json(json.dumps(payload)).nodes) == 4


@pytest.mark.parametrize(
    "positions",
    [
        [{"node": "missing", "x": 0, "y": 0}],
        [{"node": "propose", "x": 0, "y": 0}] * 2,
    ],
)
def test_layout_references_are_checked(positions):
    with pytest.raises(ValidationError):
        WorkflowDocument.model_validate_json(
            json.dumps({"definition": definition().model_dump(mode="json"), "positions": positions})
        )


def test_import_does_not_load_native_runtime_or_resolve_external_files():
    program = """
import sys
from workflows.definition import WorkflowDefinition
WorkflowDefinition.model_validate_json(sys.argv[1])
assert not any(n.startswith(('agent.', 'nodes.', 'torch')) and n not in {'agent.schemas', 'agent.schemas.output_types'} for n in sys.modules)
"""
    subprocess.run([sys.executable, "-c", program, definition().model_dump_json()], check=True)


def test_catalog_matches_exact_native_protocol_signatures():
    """Catch missing native arguments, including the validation join's human_advice."""
    from agent.llm_settings import ProviderName
    from agent.schemas.constraint_disclosure import ConstraintContext
    from agent.schemas.hyperparam_tuning import (
        ExpertAdviceInput,
        HyperparamTuningInput,
        HyperparamTuningOutput,
        TaskCompositionRef,
    )
    from agent.schemas.implementor import ImplementorInput, ImplementorOutput
    from agent.schemas.interpretation import InterpretationInput, InterpretationOutput
    from agent.schemas.literature_review import LiteratureReviewInput, LiteratureReviewOutput
    from agent.schemas.parameter_rules import ParameterRules
    from agent.schemas.proposal import ExpertContextItem, ProposalInput, ProposalOutput
    from agent.schemas.protocols.ml_literature_review_to_ml_model_propose import (
        NamedLiteratureReviewOutput,
        local_typed_evidence,
        local_typed_evidence_many,
    )
    from agent.schemas.protocols.ml_model_impl_to_ml_model_valid import local_all_fields
    from agent.schemas.protocols.ml_model_propose_to_ml_model_impl import local_full_spec
    from agent.schemas.protocols.ml_result_interp_to_ml_model_propose import local_full_context
    from agent.schemas.storage import StorageConfig
    from agent.schemas.validator import ValidatorInput, ValidatorOutput
    from workflows.candidate_training_settings import CandidateTrainingSettings
    from workflows.candidate_validation_join import proposed_implementation_to_validation

    native = {
        "interpretation.input": InterpretationInput,
        "interpretation.output": InterpretationOutput,
        "optional.text": str | None,
        "optional.expert-advice": ExpertAdviceInput | None,
        "optional.expert-context": list[ExpertContextItem] | None,
        "optional.parameter-rules": ParameterRules | None,
        "literature.input": LiteratureReviewInput,
        "literature.output": LiteratureReviewOutput,
        "literature.collection": list[NamedLiteratureReviewOutput],
        "tuning.input": HyperparamTuningInput,
        "tuning.output": HyperparamTuningOutput,
        "native-training.settings": CandidateTrainingSettings,
        "proposal.input": ProposalInput,
        "proposal.output": ProposalOutput,
        "implementation.input": ImplementorInput,
        "implementation.output": ImplementorOutput,
        "validation.input": ValidatorInput,
        "validation.output": ValidatorOutput,
        "storage": StorageConfig,
        "optional.constraint-context": ConstraintContext | None,
        "optional.task-composition-ref": TaskCompositionRef | None,
        "llm-provider": ProviderName,
        "optional.model-id": str | None,
    }
    assert native.keys() == CONTRACTS.keys()
    for capability in CAPABILITIES.values():
        for contract in (capability.input, capability.output):
            cls = native[contract]
            assert CONTRACTS[contract] == f"{cls.__module__}.{cls.__name__}"
    named = NamedLiteratureReviewOutput
    assert CONTRACTS["literature.collection"] == f"list[{named.__module__}.{named.__name__}]"
    for key, function in [
        ("interpretation-to-proposal", local_full_context),
        ("literature-to-proposal", local_typed_evidence),
        ("literature-collection-to-proposal", local_typed_evidence_many),
        ("proposal-to-implementation", local_full_spec),
        ("proposed-implementation-to-validation", proposed_implementation_to_validation),
        ("implementation-to-validation", local_all_fields),
    ]:
        descriptor = PROTOCOLS[key]
        assert descriptor.owner == f"{function.__module__}.{function.__name__}"
        signature = inspect.signature(function)
        # Resolve forward references imported only under TYPE_CHECKING by native owners.
        hints = get_type_hints(function, localns=locals())
        if key == "interpretation-to-proposal":
            # This profile exposes an explicit subset, not an alternative adapter.
            assert {arg.name for arg in descriptor.arguments} <= signature.parameters.keys()
        else:
            assert tuple(signature.parameters) == tuple(arg.name for arg in descriptor.arguments)
        assert hints["return"] is native[descriptor.output]
        for argument in descriptor.arguments:
            # The collection owner reads any Sequence; the catalogued value is its list.
            expected = native[argument.contract]
            if hints[argument.name] == Sequence[NamedLiteratureReviewOutput]:
                assert expected == list[NamedLiteratureReviewOutput]
            else:
                assert hints[argument.name] == expected
            assert argument.required == (
                signature.parameters[argument.name].default is inspect.Parameter.empty
            )


def test_report_is_not_runtime_readiness_and_revalidates_unchecked_updates():
    from workflows.definition import inspect_declaration

    document = WorkflowDocument(definition=definition())
    report = inspect_declaration(document)
    assert report.status == "declaration_validated"
    assert report.execution_ready is False
    assert len(report.unresolved) == 4
    broken = document.model_copy(update={"positions": (NodePosition(node="absent", x=0.0, y=0.0),)})
    with pytest.raises(ValidationError, match="layout node"):
        inspect_declaration(broken)


def test_many_instances_have_no_prototype_node_count_limit():
    graph = definition()
    # This subset has three semantic layers; independent repeated instances are valid.
    nodes = tuple(
        NodeInstance(
            id=f"proposal_{i}", capability="proposal", request=ExternalRequest(binding="seed")
        )
        for i in range(1500)
    )
    assert (
        len(WorkflowDefinition(task=graph.task, externals=graph.externals, nodes=nodes).nodes)
        == 1500
    )
