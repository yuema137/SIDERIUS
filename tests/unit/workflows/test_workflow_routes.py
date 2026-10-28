"""Inert route declarations (B1-PR2): catalog drift, refusals, admission and byte stability.

Expected documents and digests are authored independently of the implementation.
"""

import hashlib
import json
import typing
from pathlib import Path

import pytest
from pydantic import ValidationError

from workflows.definition import (
    AnyOf,
    ArgumentBinding,
    AuthoredLoop,
    BoolIs,
    Branch,
    EnumIn,
    ExternalBinding,
    ExternalRequest,
    ExternalSource,
    IsMissing,
    LoopFeedback,
    MetricAtLeast,
    NodeInstance,
    Not,
    ProtocolRequest,
    ResultSource,
    RouteCase,
    SelectedSource,
    TaskReferences,
    WorkflowDefinition,
    WorkflowDocument,
    parse_workflow_source,
    render_workflow_source,
)
from workflows.definition.candidate import ROUTING_NOT_ADMITTED, candidate_nodes
from workflows.definition.catalog import CONTRACTS, ROUTE_OBSERVABLES
from workflows.definition.fanout import execution_families

REPO = Path(__file__).resolve().parents[3]


def _validate(node_id: str, implementation: str) -> NodeInstance:
    return NodeInstance(
        id=node_id,
        capability="validation",
        request=ProtocolRequest(
            protocol="implementation-to-validation",
            arguments=(
                ArgumentBinding(name="output", source=ResultSource(node=implementation)),
                ArgumentBinding(name="storage", source=ExternalSource(binding="storage")),
            ),
        ),
    )


def _implement(node_id: str) -> NodeInstance:
    return NodeInstance(
        id=node_id,
        capability="implementation",
        request=ProtocolRequest(
            protocol="proposal-to-implementation",
            arguments=(
                ArgumentBinding(name="output", source=ResultSource(node="p")),
                ArgumentBinding(name="storage", source=ExternalSource(binding="storage")),
            ),
        ),
    )


def routed() -> WorkflowDefinition:
    """p -> i -> v; v routes to arm x (passed) or default arm y; tune merges the arms."""
    return WorkflowDefinition(
        task=TaskReferences(manifest="task.json", data_root="data", workspace="run"),
        externals=(
            ExternalBinding(id="seed", contract="proposal.input", location="seed.json"),
            ExternalBinding(id="storage", contract="storage", location="storage.json"),
            ExternalBinding(id="settings", contract="native-training.settings", location="t.json"),
        ),
        nodes=(
            NodeInstance(id="p", capability="proposal", request=ExternalRequest(binding="seed")),
            _implement("i"),
            _validate("v", "i"),
            _implement("ix"),
            _validate("vx", "ix"),
            _implement("iy"),
            _validate("vy", "iy"),
            NodeInstance(
                id="tune",
                capability="tuning",
                request=ProtocolRequest(
                    protocol="validated-candidate-to-tuning",
                    arguments=(
                        ArgumentBinding(
                            name="validation",
                            source=SelectedSource(
                                branch="gate",
                                candidates=(ResultSource(node="vx"), ResultSource(node="vy")),
                            ),
                        ),
                        ArgumentBinding(name="proposal", source=ResultSource(node="p")),
                        ArgumentBinding(name="settings", source=ExternalSource(binding="settings")),
                    ),
                ),
            ),
        ),
        routes=(
            Branch(
                id="gate",
                source=ResultSource(node="v"),
                cases=(
                    RouteCase(
                        when=Not(term=BoolIs(observable="validation.passed", value=False)),
                        targets=("ix",),
                    ),
                ),
                default=("iy",),
            ),
        ),
    )


def test_observable_catalog_matches_native_output_schemas():
    """A renamed/retyped native field or a widened status literal fails this drift check."""
    from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
    from agent.schemas.validator import ValidatorOutput

    natives = {"validation.output": ValidatorOutput, "tuning.output": HyperparamTuningOutput}
    assert {item.contract for item in ROUTE_OBSERVABLES.values()} <= natives.keys()
    for observable in ROUTE_OBSERVABLES.values():
        model = natives[observable.contract]
        owner, _, field = observable.field.rpartition(".")
        assert CONTRACTS[observable.contract] == owner == f"{model.__module__}.{model.__name__}"
        annotation = model.model_fields[field].annotation
        if observable.kind == "bool":
            assert annotation is bool and observable.values == ()
        elif observable.kind == "enum":
            assert typing.get_origin(annotation) is typing.Literal
            assert typing.get_args(annotation) == observable.values
        else:
            assert annotation == float | None and observable.values == ()


def test_routed_declaration_roundtrips_through_json_and_source():
    """A dropped constructor, field or ordering in either bridge breaks equality."""
    definition = routed()
    document = WorkflowDocument(definition=definition)
    assert WorkflowDefinition.model_validate_json(definition.model_dump_json()) == definition
    source = render_workflow_source(document)
    assert parse_workflow_source(source) == document
    assert render_workflow_source(parse_workflow_source(source)) == source
    assert "    SelectedSource,\n" in source and "MetricAtLeast" not in source
    metric = Branch(
        id="score",
        source=ResultSource(node="tune"),
        cases=(
            RouteCase(
                when=AnyOf(
                    terms=(
                        MetricAtLeast(
                            observable="tuning.valid_formal", metric_id="accuracy", threshold=-0.5
                        ),
                        EnumIn(observable="tuning.status", values=("completed",)),
                    )
                ),
                targets=("spare",),
            ),
            RouteCase(when=IsMissing(observable="tuning.valid_formal"), targets=("other",)),
            RouteCase(
                when=EnumIn(observable="tuning.status", values=("partial", "failed")),
                targets=("third",),
            ),
        ),
    )
    payload = definition.model_dump(mode="json")
    payload["nodes"] += [
        {"id": name, "capability": "proposal", "request": {"kind": "external", "binding": "seed"}}
        for name in ("spare", "other", "third")
    ]
    payload["routes"].append(metric.model_dump(mode="json"))
    extended = WorkflowDocument(
        definition=WorkflowDefinition.model_validate_json(json.dumps(payload))
    )
    assert parse_workflow_source(render_workflow_source(extended)) == extended


def _mutated(change) -> None:
    payload = routed().model_dump(mode="json")
    change(payload)
    WorkflowDefinition.model_validate_json(json.dumps(payload))


def _case(payload) -> dict:
    return payload["routes"][0]["cases"][0]


def _leaf(payload) -> dict:
    return _case(payload)["when"]["term"]


def _merge(payload) -> dict:
    return payload["nodes"][7]["request"]["arguments"][0]["source"]


def _add_spare(payload) -> None:
    payload["nodes"].append(
        {
            "id": "spare",
            "capability": "proposal",
            "request": {"kind": "external", "binding": "seed"},
        }
    )


def _tuning_branch(payload, when) -> None:
    _add_spare(payload)
    payload["routes"].append(
        {
            "id": "after",
            "source": {"kind": "result", "node": "tune", "port": "result"},
            "cases": [{"when": when, "targets": ["spare"]}],
        }
    )


def _both_arms_without_merge(payload) -> None:
    """tune reads arm x directly and is guarded by a branch inside arm y."""
    _merge(payload).clear()
    _merge(payload).update(kind="result", node="vx", port="result")
    payload["routes"].append(
        {
            "id": "inner",
            "source": {"kind": "result", "node": "vy", "port": "result"},
            "cases": [
                {
                    "when": {"kind": "bool_is", "observable": "validation.passed", "value": True},
                    "targets": ["tune"],
                }
            ],
        }
    )


def _merge_consumer_guarded_by_arm(payload) -> None:
    payload["routes"].append(
        {
            "id": "inner",
            "source": {"kind": "result", "node": "vx", "port": "result"},
            "cases": [
                {
                    "when": {"kind": "bool_is", "observable": "validation.passed", "value": True},
                    "targets": ["tune"],
                }
            ],
        }
    )


@pytest.mark.parametrize(
    "change,match",
    [
        # Free field names and fields of another contract are not readable.
        (lambda p: _leaf(p).update(observable="passed"), "not catalogued"),
        (lambda p: _leaf(p).update(observable="tuning.status"), "not catalogued"),
        # A comparison must fit the observable's catalogued kind.
        (
            lambda p: _case(p).update(
                when={"kind": "is_missing", "observable": "validation.passed"}
            ),
            "cannot read a bool",
        ),
        (
            lambda p: _tuning_branch(
                p, {"kind": "enum_in", "observable": "tuning.status", "values": ["done"]}
            ),
            "enum values",
        ),
        (
            lambda p: _tuning_branch(
                p,
                {"kind": "enum_in", "observable": "tuning.status", "values": ["failed"] * 2},
            ),
            "enum values",
        ),
        # Targets: declared, never an ancestor of (or equal to) the branch source.
        (lambda p: _case(p).update(targets=["absent"]), "Unknown route node"),
        (lambda p: _case(p).update(targets=["i"]), "Cycles"),
        (lambda p: _case(p).update(targets=["v"]), "Cycles"),
        # Exclusive arms and target ownership.
        (lambda p: p["routes"][0].update(default=["ix"]), "one target of one branch"),
        (
            lambda p: p["routes"].append(dict(p["routes"][0], id="again")),
            "one target of one branch",
        ),
        (lambda p: p["routes"].append(p["routes"][0]), "Branch IDs must be unique"),
        # Merges: known branch, one candidate in every runnable arm, consumer outside arms.
        (lambda p: _merge(p).update(branch="absent"), "unknown branch"),
        (lambda p: _merge(p)["candidates"][1].update(node="v"), "every branch arm"),
        (lambda p: _merge(p)["candidates"][1].update(node="ix"), "differ in contract"),
        (lambda p: _merge(p)["candidates"].append(_merge(p)["candidates"][0]), "every branch arm"),
        # Without a default no arm may run, starving the merge.
        (lambda p: p["routes"][0].pop("default"), "requires a default arm"),
        # The merge consumer is also guarded from inside arm x.
        (_merge_consumer_guarded_by_arm, "also depends on one arm it merges"),
        (lambda p: p["routes"][0].update(default=["iy", "tune"]), "also depends on one arm"),
        # A plain (non-merge) dependency on both arms of one branch.
        (_both_arms_without_merge, "two exclusive arms without a merge"),
    ],
)
def test_invalid_routes_are_refused(change, match):
    with pytest.raises(ValidationError, match=match):
        _mutated(change)


def loop_definition(target: str) -> WorkflowDefinition:
    """Four external nodes; train is the feedback source and check guards ``target``."""
    return WorkflowDefinition(
        task=TaskReferences(manifest="task.json", data_root="data", workspace="run"),
        externals=(
            ExternalBinding(id="seed", contract="interpretation.input", location="seed.json"),
            ExternalBinding(id="check", contract="validation.input", location="check.json"),
            ExternalBinding(id="tune", contract="tuning.input", location="tune.json"),
        ),
        nodes=(
            NodeInstance(
                id="interpret", capability="interpretation", request=ExternalRequest(binding="seed")
            ),
            NodeInstance(
                id="check", capability="validation", request=ExternalRequest(binding="check")
            ),
            NodeInstance(
                id="audit", capability="validation", request=ExternalRequest(binding="check")
            ),
            NodeInstance(id="train", capability="tuning", request=ExternalRequest(binding="tune")),
        ),
        routes=(
            Branch(
                id="guard",
                source=ResultSource(node="check"),
                cases=(
                    RouteCase(
                        when=BoolIs(observable="validation.passed", value=True), targets=(target,)
                    ),
                ),
            ),
        ),
        loop=AuthoredLoop(
            final_iteration=2,
            feedback=LoopFeedback(
                source=ResultSource(node="train"),
                target="interpret",
                protocol="tuning-to-interpretation",
                history="native-research/v1",
            ),
        ),
    )


def test_unrouted_loop_with_unknown_feedback_source_keeps_its_validation_error():
    """Route checks must not run first and turn the declared loop error into a KeyError."""
    from workflows.definition import WorkflowSourceError

    payload = loop_definition("audit").model_dump(mode="json")
    del payload["routes"]
    payload["loop"]["feedback"]["source"]["node"] = "ghost"
    with pytest.raises(ValidationError, match="loop feedback requires declared tuning"):
        WorkflowDefinition.model_validate_json(json.dumps(payload))
    source = render_workflow_source(
        WorkflowDocument(
            definition=WorkflowDefinition.model_validate_json(
                json.dumps(
                    dict(payload, loop=loop_definition("audit").loop.model_dump(mode="json"))
                )
            )
        )
    )
    with pytest.raises(WorkflowSourceError) as caught:
        parse_workflow_source(source.replace("node='train'", "node='ghost'"))
    assert caught.value.diagnostics[0].code == "validation"


def test_routes_may_not_skip_the_loop_feedback_path():
    """Decision Q5(a): a guard on the feedback source would end loop bodies without feedback."""
    assert loop_definition("audit").routes
    with pytest.raises(ValidationError, match="loop feedback source"):
        loop_definition("train")
    # Predecessors count too, including merge candidates (v1 is conservative).
    payload = routed().model_dump(mode="json")
    payload["externals"].append(
        {"id": "seed2", "contract": "interpretation.input", "location": "seed2.json"}
    )
    payload["nodes"].append(
        {
            "id": "interpret",
            "capability": "interpretation",
            "request": {"kind": "external", "binding": "seed2"},
        }
    )
    payload["loop"] = loop_definition("audit").loop.model_dump(mode="json")
    payload["loop"]["feedback"]["source"]["node"] = "tune"
    with pytest.raises(ValidationError, match="loop feedback source"):
        WorkflowDefinition.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize(
    "profile",
    [
        None,
        "native-proposal-fanout/v1",
        "native-proposal-families/v1",
        "native-literature-candidate/v1",
        "native-interpretation-candidate/v1",
    ],
)
def test_every_execution_admission_refuses_routed_declarations(profile):
    """A routed document reaching any shape check must be refused before shape matching."""
    with pytest.raises(ValueError, match=ROUTING_NOT_ADMITTED):
        if profile is None:
            candidate_nodes(routed())
        else:
            execution_families(routed(), profile)


def test_preview_refuses_a_routed_document_before_reading_files(tmp_path):
    """Production-path witness: preview is the first admission of a launch."""
    from tools.workflow_preview.models import WorkflowPreviewRequest
    from tools.workflow_preview.preview import observe_bindings

    def never_read(*_):
        raise AssertionError("a routed declaration reached file observation")

    request = WorkflowPreviewRequest(
        document=WorkflowDocument(definition=routed()), project_root=str(tmp_path)
    )
    with pytest.raises(ValueError, match=ROUTING_NOT_ADMITTED):
        observe_bindings(request, read_file=never_read)


# Pinned on base 69a9d81a before route support: (canonical source sha256, declaration digest).
EXAMPLE_IDENTITIES = {
    "managed_reusable_candidate.py": (
        "16e814a81d1a139c9fa566186d46c16b118978e1ac3fdf420a612e23be681994",
        "7586a72ae6e6c6f61c1f494ebcf80888ad9a09142cd218d752883f3f8099fab9",
    ),
    "reusable_candidate.py": (
        "f0717cfc5640874bcefa38e8e88e1e490189a5099aebbb79b3a17bec42cde53e",
        "f07f0263ece5eb02fa16da9c368f8845c2cf8ee1d700031f8d86dbd803c4c2e8",
    ),
    "reusable_training.py": (
        "6cfb35fdc76bb92b67250b084b7e49c751fb219a29f8960a33973694c1d09e93",
        "2420ac1bf7b4d87be1b2f1112e577e7d3c580e1677fc5325deef4c6e93da7d9d",
    ),
}


@pytest.mark.parametrize("name", sorted(EXAMPLE_IDENTITIES))
def test_shipped_declarations_keep_canonical_bytes_and_digests(name):
    """An always-dumped routes field or an unconditional route import changes these hashes."""
    document = parse_workflow_source((REPO / "examples/workflow_declarations" / name).read_text())
    source = render_workflow_source(document)
    assert (hashlib.sha256(source.encode()).hexdigest(), document.declaration_digest()) == (
        EXAMPLE_IDENTITIES[name]
    )
