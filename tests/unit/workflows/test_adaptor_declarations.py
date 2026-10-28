"""Inert adaptor declarations (B6-1): format gate, validation table, catalogue and bytes.

Each refusal names the defect it catches. Expected documents and digests are authored
independently of the implementation; base identities were captured before B6-1.
"""

import hashlib
import importlib
import json
import typing

import pytest
from pydantic import ValidationError

from workflows.definition import (
    AdaptorInstance,
    AdaptorRequest,
    AdaptorSource,
    ArgumentBinding,
    AuthoredLoop,
    ExternalBinding,
    ExternalRequest,
    ExternalSource,
    FieldRankCombine,
    FirstAdmissibleSelect,
    InputPort,
    LoopFeedback,
    MetricThresholdStop,
    NodeInstance,
    NoImprovementStop,
    PassCombine,
    PortBinding,
    ProtocolRequest,
    ReplicateDistribute,
    ResultSource,
    SingleDistribute,
    SplitItemsDistribute,
    TaskReferences,
    TopKSelect,
    WorkflowDefinition,
    WorkflowDocument,
    adaptor_strategies,
    parse_workflow_source,
    render_workflow_source,
)
from workflows.definition.candidate import ADAPTORS_NOT_ADMITTED, candidate_nodes
from workflows.definition.catalog import (
    ADAPTOR_STRATEGIES,
    CONTRACTS,
    RANKABLE_FIELDS,
    SPLITTABLE_ITEMS,
)
from workflows.definition.fanout import execution_families

TASK = TaskReferences(manifest="task.json", data_root="data", workspace="run")
FORMAT = "siderius.adaptors/v1"


def _arg(name: str, source) -> ArgumentBinding:
    return ArgumentBinding(name=name, source=source)


def _implement(node_id: str) -> NodeInstance:
    return NodeInstance(
        id=node_id,
        capability="implementation",
        request=ProtocolRequest(
            protocol="proposal-to-implementation",
            arguments=(
                _arg("output", ResultSource(node="p")),
                _arg("storage", ExternalSource(binding="storage")),
            ),
        ),
    )


def _validate(node_id: str, implementation: str) -> NodeInstance:
    return NodeInstance(
        id=node_id,
        capability="validation",
        request=ProtocolRequest(
            protocol="implementation-to-validation",
            arguments=(
                _arg("output", ResultSource(node=implementation)),
                _arg("storage", ExternalSource(binding="storage")),
            ),
        ),
    )


def first_passing() -> WorkflowDefinition:
    """S1: two validated implementations of one proposal; train only the first passing."""
    return WorkflowDefinition(
        task=TASK,
        externals=(
            ExternalBinding(id="seed", contract="proposal.input", location="seed.json"),
            ExternalBinding(id="storage", contract="storage", location="storage.json"),
            ExternalBinding(id="settings", contract="native-training.settings", location="t.json"),
        ),
        nodes=(
            NodeInstance(id="p", capability="proposal", request=ExternalRequest(binding="seed")),
            _implement("i1"),
            _validate("v1", "i1"),
            _implement("i2"),
            _validate("v2", "i2"),
            NodeInstance(
                id="tune",
                capability="tuning",
                request=ProtocolRequest(
                    protocol="validated-candidate-to-tuning",
                    arguments=(
                        _arg("validation", AdaptorSource(adaptor="pick")),
                        _arg("proposal", ResultSource(node="p")),
                        _arg("settings", ExternalSource(binding="settings")),
                    ),
                ),
            ),
        ),
        adaptor_format=FORMAT,
        adaptors=(
            AdaptorInstance(
                id="pick",
                inputs=(
                    InputPort(name="checks", contract="validation.output", cardinality="many"),
                ),
                bindings=(
                    PortBinding(
                        port="checks",
                        sources=(ResultSource(node="v1"), ResultSource(node="v2")),
                    ),
                ),
                combine=PassCombine(),
                select=FirstAdmissibleSelect(),
                distribute=SingleDistribute(),
            ),
        ),
    )


def strongest_findings() -> WorkflowDefinition:
    """S3 + S8: a review's two strongest findings seed two proposals; a seed is replicated."""
    return WorkflowDefinition(
        task=TASK,
        externals=(
            ExternalBinding(id="review", contract="literature.input", location="review.json"),
            ExternalBinding(id="seed", contract="proposal.input", location="seed.json"),
        ),
        nodes=(
            NodeInstance(
                id="lit", capability="literature", request=ExternalRequest(binding="review")
            ),
            *(
                NodeInstance(
                    id=f"p{index}",
                    capability="proposal",
                    request=ProtocolRequest(
                        protocol="literature-to-proposal",
                        arguments=(
                            _arg("output", AdaptorSource(adaptor="top", index=index)),
                            _arg("proposal_input", ExternalSource(binding="seed")),
                        ),
                    ),
                )
                for index in range(2)
            ),
            *(
                NodeInstance(
                    id=f"copy{index}",
                    capability="proposal",
                    request=AdaptorRequest(source=AdaptorSource(adaptor="fan", index=index)),
                )
                for index in range(2)
            ),
        ),
        adaptor_format=FORMAT,
        adaptors=(
            AdaptorInstance(
                id="top",
                inputs=(InputPort(name="review", contract="literature.output", cardinality="one"),),
                bindings=(PortBinding(port="review", sources=(ResultSource(node="lit"),)),),
                combine=FieldRankCombine(field="confidence", order="descending"),
                select=TopKSelect(k=2),
                distribute=SplitItemsDistribute(field="findings", count=2, on_short="fail"),
            ),
            AdaptorInstance(
                id="fan",
                inputs=(InputPort(name="seed", contract="proposal.input", cardinality="one"),),
                bindings=(PortBinding(port="seed", sources=(ExternalSource(binding="seed"),)),),
                combine=PassCombine(),
                select=FirstAdmissibleSelect(),
                distribute=ReplicateDistribute(count=2),
            ),
        ),
    )


def best_run() -> WorkflowDefinition:
    """S5 shape: rank two trained runs by the run metric and keep the best one."""
    return WorkflowDefinition(
        task=TASK,
        externals=(ExternalBinding(id="tune", contract="tuning.input", location="tune.json"),),
        nodes=tuple(
            NodeInstance(id=name, capability="tuning", request=ExternalRequest(binding="tune"))
            for name in ("t1", "t2")
        ),
        adaptor_format=FORMAT,
        adaptors=(
            AdaptorInstance(
                id="best",
                inputs=(InputPort(name="runs", contract="tuning.output", cardinality="many"),),
                bindings=(
                    PortBinding(
                        port="runs", sources=(ResultSource(node="t1"), ResultSource(node="t2"))
                    ),
                ),
                combine={"kind": "metric-rank/v1", "score": "best_valid_formal"},
                select=TopKSelect(k=1),
                distribute=SingleDistribute(),
            ),
        ),
    )


@pytest.mark.parametrize("build", [first_passing, strongest_findings, best_run])
def test_adaptor_declarations_roundtrip_through_json_and_source(build):
    """A dropped constructor, field, index or ordering in either bridge breaks equality."""
    definition = build()
    document = WorkflowDocument(definition=definition)
    assert WorkflowDefinition.model_validate_json(definition.model_dump_json()) == definition
    source = render_workflow_source(document)
    assert parse_workflow_source(source) == document
    assert render_workflow_source(parse_workflow_source(source)) == source
    # Only constructors the document uses are imported.
    assert "    AdaptorInstance,\n" in source and "CollectCombine" not in source


def test_reusable_v2_declaration_accepts_adaptors_and_roundtrips_source():
    """B6-D2: v2 carries the same gated fields; a v1-only field or import would break this."""
    from workflows.definition import ReusableWorkflowDefinition, ReusableWorkflowDocument

    payload = strongest_findings().model_dump(mode="json")
    payload.update(schema_version=2, task={"manifest": "task.json", "data_root": "data"})
    definition = ReusableWorkflowDefinition.model_validate_json(json.dumps(payload))
    assert definition.adaptor_format == FORMAT and len(definition.adaptors) == 2
    document = ReusableWorkflowDocument(definition=definition)
    source = render_workflow_source(document)
    assert parse_workflow_source(source) == document
    assert "    SplitItemsDistribute,\n" in source
    payload.pop("adaptor_format")
    with pytest.raises(ValidationError, match="require adaptor_format"):
        ReusableWorkflowDefinition.model_validate_json(json.dumps(payload))


def test_adaptor_source_index_is_omitted_only_when_absent():
    """An index=None dumped into canonical JSON would differ from the rendered source."""
    payload = first_passing().model_dump(mode="json")
    assert payload["nodes"][5]["request"]["arguments"][0]["source"] == {
        "kind": "adaptor",
        "adaptor": "pick",
        "port": "result",
    }
    assert "max_items" not in payload["adaptors"][0]["inputs"][0]
    indexed = strongest_findings().model_dump(mode="json")
    assert indexed["nodes"][1]["request"]["arguments"][0]["source"]["index"] == 0


def _refused(build, change, match) -> None:
    payload = build().model_dump(mode="json")
    change(payload)
    with pytest.raises(ValidationError, match=match):
        WorkflowDefinition.model_validate_json(json.dumps(payload))


def _pick(payload) -> dict:
    return payload["adaptors"][0]


def _port(payload, adaptor: int = 0) -> dict:
    return payload["adaptors"][adaptor]["inputs"][0]


def _sources(payload, adaptor: int = 0) -> list:
    return payload["adaptors"][adaptor]["bindings"][0]["sources"]


def _consumer(payload) -> dict:
    return payload["nodes"][5]["request"]["arguments"][0]["source"]


def _to_result(source: dict, node: str) -> None:
    source.clear()
    source.update(kind="result", node=node, port="result")


def _cycle(payload) -> None:
    second = json.loads(json.dumps(_pick(payload)))
    second["id"] = "pick2"
    _sources(payload)[1] = {"kind": "adaptor", "adaptor": "pick2", "port": "result"}
    second["bindings"][0]["sources"][1] = {"kind": "adaptor", "adaptor": "pick", "port": "result"}
    payload["adaptors"].append(second)


S1_REFUSALS = [
    # Format gate: use without the format, and a format nothing uses.
    (lambda p: p.pop("adaptor_format"), "require adaptor_format"),
    (lambda p: (p.pop("adaptors"), _to_result(_consumer(p), "v1")), "no adaptor"),
    # Namespace and references.
    (lambda p: _pick(p).update(id="v1"), "distinct from node IDs"),
    (lambda p: _consumer(p).update(adaptor="ghost"), "Unknown adaptor"),
    (lambda p: _sources(p).append({"kind": "result", "node": "ghost"}), "Unknown source node"),
    # Exact contracts: a port source and an adaptor consumer.
    (lambda p: _sources(p)[0].update(node="i1"), r"checks\[0\]: requires validation.output"),
    (
        lambda p: _port(p).update(contract="proposal.output"),
        r"checks\[0\]: requires proposal.output, got validation.output",
    ),
    (lambda p: _port(p).update(contract="validation.later"), "Unsupported port contract"),
    # Ports, bindings and item bounds.
    (lambda p: _pick(p)["bindings"][0].update(port="other"), "exactly one binding"),
    (lambda p: _pick(p)["inputs"].append(dict(_port(p))), "duplicate input ports"),
    (lambda p: _port(p).update(cardinality="one"), "outside the declared item bounds"),
    (lambda p: _port(p).update(min_items=3), "outside the declared item bounds"),
    (lambda p: _port(p).update(max_items=1), "outside the declared item bounds"),
    # Indices: a single/v1 output has none.
    (lambda p: _consumer(p).update(index=0), "no indexed outputs"),
    # The strategy table.
    (lambda p: _pick(p).update(select={"kind": "top-k/v1", "k": 1}), "requires a ranking"),
    (
        lambda p: _pick(p).update(select={"kind": "all/v1"}),
        "all/v1 may keep 2 values; single/v1 accepts at most 1",
    ),
    (
        lambda p: _pick(p).update(combine={"kind": "metric-rank/v1", "score": "best_valid_formal"}),
        "metric-rank/v1 cannot rank validation.output",
    ),
    (lambda p: _pick(p).update(combine={"kind": "collect/v1"}), "not catalogued yet"),
    (
        lambda p: _pick(p).update(combine={"kind": "concat-items/v1", "field": "findings"}),
        "concat-items/v1 field 'findings' is not catalogued",
    ),
    (
        lambda p: _pick(p).update(
            distribute={"kind": "per-item/v1", "count": 3, "on_short": "fail"}
        ),
        "unsatisfiable cardinality",
    ),
    # A cycle through adaptors joins the same Kahn check as nodes.
    (_cycle, "Cycles"),
]


@pytest.mark.parametrize("change,match", S1_REFUSALS)
def test_invalid_first_passing_declarations_are_refused(change, match):
    _refused(first_passing, change, match)


def _top(payload) -> dict:
    return payload["adaptors"][0]


def _p0_source(payload) -> dict:
    return payload["nodes"][1]["request"]["arguments"][0]["source"]


S3_REFUSALS = [
    # k > M: two kept findings cannot split into one output.
    (
        lambda p: _top(p)["distribute"].update(count=1),
        "top-k/v1 k=2 exceeds split-items/v1 count",
    ),
    (lambda p: _p0_source(p).update(index=2), "index must be below 2"),
    (lambda p: _p0_source(p).pop("index"), "index must be below 2"),
    # One-value combines cannot feed per-item (B6-2 run-time rule, refused earlier).
    (
        lambda p: _top(p).update(
            distribute={"kind": "per-item/v1", "count": 2, "on_short": "fail"}
        ),
        "per-item/v1 cannot follow field-rank/v1",
    ),
    # Catalogue fields only.
    (lambda p: _top(p)["combine"].update(field="relevance"), "field-rank/v1 field"),
    (lambda p: _top(p)["distribute"].update(field="claims"), "split-items/v1 field"),
    # field-rank ranks the entries of exactly one value.
    (
        lambda p: (
            _port(p).update(cardinality="many"),
            _sources(p).append({"kind": "result", "node": "lit"}),
        ),
        "exactly one bound value",
    ),
    # Threshold reads only its own basis' ranking.
    (
        lambda p: _top(p).update(
            select={"kind": "threshold/v1", "basis": "metric", "metric_id": "m", "at_least": 0.5}
        ),
        "threshold/v1 basis 'metric' cannot read field-rank/v1",
    ),
    # A replicated proposal.input reaches only an exactly matching capability input.
    (
        lambda p: p["nodes"][3].update(capability="literature"),
        "request requires literature.input, got proposal.input",
    ),
    (lambda p: _port(p, 1).update(contract="literature.input"), "requires literature.input"),
]


@pytest.mark.parametrize("change,match", S3_REFUSALS)
def test_invalid_split_and_replicate_declarations_are_refused(change, match):
    _refused(strongest_findings, change, match)


S5_REFUSALS = [
    # k > M for whole values: three best runs cannot leave through one output.
    (lambda p: _top(p)["select"].update(k=2), "top-k/v1 k=2 exceeds the 1 single/v1 accepts"),
    # Q-B2-2 basis rule: a rubric threshold needs a rubric ranking, not the metric one.
    (
        lambda p: _top(p).update(select={"kind": "threshold/v1", "basis": "rubric", "at_least": 1}),
        "threshold/v1 basis 'rubric' cannot read metric-rank/v1",
    ),
    (lambda p: _top(p).update(select={"kind": "first-admissible/v1"}), "requires pass/v1"),
    # all/threshold may keep every bound source; three cannot fit two outputs.
    (
        lambda p: (
            _top(p).update(
                select={
                    "kind": "threshold/v1",
                    "basis": "metric",
                    "metric_id": "m",
                    "at_least": 0.5,
                },
                distribute={"kind": "per-item/v1", "count": 2, "on_short": "skip"},
            ),
            p["nodes"].append(dict(p["nodes"][0], id="t3")),
            _sources(p).append({"kind": "result", "node": "t3", "port": "result"}),
        ),
        "threshold/v1 may keep 3 values; per-item/v1 accepts at most 2",
    ),
]


@pytest.mark.parametrize("change,match", S5_REFUSALS)
def test_invalid_ranking_declarations_are_refused(change, match):
    _refused(best_run, change, match)


def test_metric_threshold_within_the_bound_sources_is_accepted():
    """Capacity is the bound source count: a generous max_items must not cause a false refusal."""
    payload = best_run().model_dump(mode="json")
    _top(payload).update(
        select={"kind": "threshold/v1", "basis": "metric", "metric_id": "m", "at_least": 0.5},
        distribute={"kind": "per-item/v1", "count": 2, "on_short": "skip"},
    )
    _port(payload).update(max_items=5)
    WorkflowDefinition.model_validate_json(json.dumps(payload))


def test_split_wider_than_top_k_is_refused_only_under_a_fail_policy():
    """At most k entries survive top-k, so count > k with on_short='fail' can only fail."""
    payload = strongest_findings().model_dump(mode="json")
    _top(payload)["distribute"].update(count=3, on_short="skip")
    WorkflowDefinition.model_validate_json(json.dumps(payload))
    _top(payload)["distribute"].update(on_short="fail")
    with pytest.raises(ValidationError, match="can never be filled by top-k/v1 k=2"):
        WorkflowDefinition.model_validate_json(json.dumps(payload))


def routed_pick() -> dict:
    """v0 gates a passing arm (ix -> vx) against a default arm (iy -> vy)."""
    payload = first_passing().model_dump(mode="json")
    payload["nodes"][1:5] = [
        _implement("i0").model_dump(mode="json"),
        _validate("v0", "i0").model_dump(mode="json"),
        _implement("ix").model_dump(mode="json"),
        _validate("vx", "ix").model_dump(mode="json"),
        _implement("iy").model_dump(mode="json"),
        _validate("vy", "iy").model_dump(mode="json"),
    ]
    payload["routes"] = [
        {
            "id": "gate",
            "source": {"kind": "result", "node": "v0", "port": "result"},
            "cases": [
                {
                    "when": {"kind": "bool_is", "observable": "validation.passed", "value": True},
                    "targets": ["ix"],
                }
            ],
            "default": ["iy"],
        }
    ]
    merge = {
        "kind": "selected",
        "branch": "gate",
        "candidates": [
            {"kind": "result", "node": "vx", "port": "result"},
            {"kind": "result", "node": "vy", "port": "result"},
        ],
    }
    _sources(payload)[:] = [merge, {"kind": "result", "node": "v0", "port": "result"}]
    return payload


def test_route_merge_into_an_adaptor_port_resolves():
    """Lead decision 2026-10-28: a port may bind a SelectedSource (one validation.output)."""
    WorkflowDefinition.model_validate_json(json.dumps(routed_pick()))


def test_an_adaptor_may_read_both_exclusive_arms_without_a_merge():
    """B6-3 (B6-D8): a skipped adaptor input is inadmissible, never inherited.

    Fails if the adaptor is refused like a node (nodes keep the rule:
    ``test_workflow_routes``). The tuner downstream of the adaptor carries no arm
    label, so it is not refused either.
    """
    payload = routed_pick()
    _sources(payload)[0] = {"kind": "result", "node": "vx", "port": "result"}
    _sources(payload).append({"kind": "result", "node": "vy", "port": "result"})
    _pick(payload)["select"] = {"kind": "first-admissible/v1"}
    WorkflowDefinition.model_validate_json(json.dumps(payload))


def test_a_merge_into_an_adaptor_needs_a_candidate_in_every_arm():
    payload = routed_pick()
    _sources(payload)[0]["candidates"][1]["node"] = "v0"
    with pytest.raises(ValidationError, match="every branch arm"):
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
def test_every_execution_admission_refuses_adaptor_declarations(profile):
    """Adaptors are declaration-only until B6-3; no shape check may match one."""
    with pytest.raises(ValueError, match=ADAPTORS_NOT_ADMITTED):
        if profile is None:
            candidate_nodes(first_passing())
        else:
            execution_families(first_passing(), profile)


def test_preview_refuses_an_adaptor_document_before_reading_files(tmp_path):
    """Production-path witness: preview is the first admission of a launch."""
    from tools.workflow_preview.models import WorkflowPreviewRequest
    from tools.workflow_preview.preview import observe_bindings

    def never_read(*_):
        raise AssertionError("an adaptor declaration reached file observation")

    request = WorkflowPreviewRequest(
        document=WorkflowDocument(definition=first_passing()), project_root=str(tmp_path)
    )
    with pytest.raises(ValueError, match=ADAPTORS_NOT_ADMITTED):
        observe_bindings(request, read_file=never_read)


def _union_kinds(union) -> dict[str, type]:
    members = typing.get_args(typing.get_args(union)[0])
    return {typing.get_args(model.model_fields["kind"].annotation)[0]: model for model in members}


def test_strategy_catalogue_matches_the_declarable_strategy_models():
    """A kind added to a union without a catalogue row (or the reverse) fails here."""
    stages = {
        "combine": _union_kinds(adaptor_strategies.DeterministicCombine),
        "select": _union_kinds(adaptor_strategies.SelectStrategy),
        "distribute": _union_kinds(adaptor_strategies.DistributeStrategy),
    }
    declared = {
        kind: (stage, model) for stage, kinds in stages.items() for kind, model in kinds.items()
    }
    assert declared.keys() == ADAPTOR_STRATEGIES.keys()
    for kind, entry in ADAPTOR_STRATEGIES.items():
        stage, model = declared[kind]
        module, _, name = entry.declaration.rpartition(".")
        assert entry.stage == stage and getattr(importlib.import_module(module), name) is model
        module, _, name = entry.owner.rpartition(".")
        assert callable(getattr(importlib.import_module(module), name))


def test_item_and_rank_fields_match_the_native_schemas():
    """A renamed or retyped native list/entry field fails this drift check."""
    from agent.schemas.literature_review import LiteratureReviewOutput

    natives = {"literature.output": LiteratureReviewOutput}
    assert set(SPLITTABLE_ITEMS) | set(RANKABLE_FIELDS) <= natives.keys()
    for contract, field in SPLITTABLE_ITEMS.items():
        model = natives[contract]
        assert CONTRACTS[contract] == f"{model.__module__}.{model.__name__}"
        assert typing.get_origin(model.model_fields[field].annotation) is list
    for contract, rankable in RANKABLE_FIELDS.items():
        assert SPLITTABLE_ITEMS[contract] == rankable.list_field
        (entry,) = typing.get_args(natives[contract].model_fields[rankable.list_field].annotation)
        annotation = entry.model_fields[rankable.item_field].annotation
        assert set(typing.get_args(annotation)) <= {float, int, type(None)}


def loop_document() -> WorkflowDocument:
    return WorkflowDocument(
        definition=WorkflowDefinition(
            task=TASK,
            externals=(
                ExternalBinding(id="seed", contract="interpretation.input", location="seed.json"),
                ExternalBinding(id="tune", contract="tuning.input", location="tune.json"),
            ),
            nodes=(
                NodeInstance(
                    id="interpret",
                    capability="interpretation",
                    request=ExternalRequest(binding="seed"),
                ),
                NodeInstance(
                    id="train", capability="tuning", request=ExternalRequest(binding="tune")
                ),
            ),
            loop=AuthoredLoop(
                final_iteration=3,
                feedback=LoopFeedback(
                    source=ResultSource(node="train"),
                    target="interpret",
                    protocol="tuning-to-interpretation",
                    history="native-research/v1",
                ),
                stop_conditions=(
                    MetricThresholdStop(metric_id="accuracy", threshold=0.9),
                    NoImprovementStop(completed_bodies=2),
                ),
            ),
        )
    )


def test_loop_document_keeps_canonical_bytes_and_digest():
    """Pinned on base 8f2aabd6 before B6-1; an always-dumped adaptor field changes these.

    The shipped example declarations are pinned in ``test_workflow_routes.py``.
    """
    document = loop_document()
    source = render_workflow_source(document)
    assert (
        hashlib.sha256(source.encode()).hexdigest(),
        document.definition.declaration_digest(),
    ) == (
        "7ad0f88538831fa12d45d6214adbcbf982f11035176cd9c43920d39857f3c883",
        "f444e7ea6b5b6ea70b7d6c5edb25fa6cb93f2767718c2c2de39781ee0694a117",
    )
