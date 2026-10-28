"""S1 selection profile: fanout branches -> first-admissible adaptor -> one tuner (B6-3).

Offline pseudo integration: real native node bodies with a stub provider, real
readiness, adaptor execution and verifier recomputation; only the tuner is stubbed.
"""

import json
from pathlib import Path

import pytest

from tests.helpers.candidate_fanout import selection_request
from tools.candidate_worker import graph, launch_candidate
from tools.candidate_worker.graph_evidence import verify_graph_trace
from tools.candidate_worker.layout import adaptor_output_path, adaptor_record_path
from workflows.definition import WorkflowDefinition
from workflows.definition.candidate import ADAPTORS_NOT_ADMITTED
from workflows.definition.fanout import SELECTION_PROFILE, execution_families

from .test_graph import initial
from .test_native import Provider
from .test_native import native_runner as native_runner
from .test_training import training_runner as training_runner


@pytest.fixture
def rejecting(native_runner, monkeypatch):
    """Reject the reviews whose execution ordinals are in the returned set.

    Under the default declaration order, review 0 is check0 and review 1 is check1.
    """
    rejected: set[int] = set()
    reviews = []
    original = Provider.generate

    def generate(self, system, user, **kwargs):
        result = original(self, system, user, **kwargs)
        if "review" in kwargs.get("label", ""):
            if len(reviews) in rejected:
                result.update(passed=False, implementation_issues=["rejected branch"])
            reviews.append(result["passed"])
        return result

    monkeypatch.setattr(Provider, "generate", generate)
    return rejected


@pytest.fixture
def trained(monkeypatch):
    """The implementation each tuner dispatch actually received."""
    seen = []
    real = graph.run_training

    def observe(context, proposal, implementation, validation, *args, **kwargs):
        seen.append((implementation, validation))
        return real(context, proposal, implementation, validation, *args, **kwargs)

    monkeypatch.setattr(graph, "run_training", observe)
    return seen


def run(request):
    receipt = launch_candidate(request)
    parent = initial(request).model_copy(update={"run_id": receipt.run_id})
    return receipt, parent


def record(receipt) -> dict:
    (entry,) = receipt.graph_trace.adaptors
    return json.loads(Path(entry.record_path).read_bytes())


def states(receipt) -> dict[str, tuple[str, str | None]]:
    trace = receipt.graph_trace
    return {item.node_id: (item.state, item.reason) for item in (*trace.nodes, *trace.adaptors)}


def test_first_admissible_trains_the_second_branch_when_the_first_is_rejected(
    prepared, training_runner, rejecting, trained
):
    """Fails if the tuner trains branch 0 regardless of the adaptor (old `branches[0]`)."""
    rejecting.add(0)
    request = selection_request(prepared)
    receipt, parent = run(request)
    assert states(receipt)["check0"] == ("rejected", "validation_rejected")
    assert states(receipt)["pick"] == ("succeeded", None)
    assert states(receipt)["train"] == ("succeeded", None)
    ((implementation, validation),) = trained
    assert "/build1/" in implementation.model_file_path and validation.passed
    picked = record(receipt)
    assert [item["admission"] for item in picked["admissible"]] == ["rejected", "admissible"]
    assert picked["contributions"][0]["inputs"][0]["source"]["node"] == "check1"
    # The absorbed sibling rejection is neutral: the selected path decides the body.
    assert (receipt.status, receipt.validation_passed) == ("completed", True), receipt.error
    verify_graph_trace(request, parent, receipt)
    for forged in ({"status": "rejected"}, {"validation_passed": False}):
        with pytest.raises(ValueError, match="aggregate outcome mismatch"):
            verify_graph_trace(request, parent, receipt.model_copy(update=forged))


def test_all_rejected_closes_the_adaptor_and_blocks_tuning(
    prepared, training_runner, rejecting, trained
):
    rejecting.update((0, 1))
    request = selection_request(prepared)
    receipt, parent = run(request)
    assert states(receipt)["pick"] == ("rejected", "no_admissible_input")
    assert states(receipt)["train"] == ("blocked", "dependency_not_successful")
    assert trained == [] and not any(name == "tuner" for name, _ in training_runner)
    assert record(receipt)["outputs"] == []
    assert (receipt.status, receipt.validation_passed) == ("rejected", False)
    verify_graph_trace(request, parent, receipt)


def test_declared_binding_order_not_execution_order_decides(
    prepared, training_runner, native_runner, trained
):
    """check1 executes first (declared first) yet the binding order keeps check0.

    Fails if items are built in completion order: check1 would be selected.
    """
    order = ["propose", "build1", "check1", "build0", "check0", "train"]
    request = selection_request(prepared, node_order=order)
    receipt, parent = run(request)
    assert [item.node_id for item in receipt.graph_trace.nodes][:3] == order[:3]
    assert receipt.status == "completed", receipt.error
    ((implementation, _),) = trained
    assert "/build0/" in implementation.model_file_path
    verify_graph_trace(request, parent, receipt)


def test_reversed_binding_order_selects_the_other_branch(
    prepared, training_runner, native_runner, trained
):
    """Same execution order, bindings reversed: check1 is first, so build1 trains."""
    request = selection_request(prepared, bindings=["check1", "check0"])
    receipt, parent = run(request)
    assert receipt.status == "completed", receipt.error
    ((implementation, _),) = trained
    assert "/build1/" in implementation.model_file_path
    verify_graph_trace(request, parent, receipt)


@pytest.fixture
def distinct_branches(native_runner, monkeypatch):
    """Each implementation call emits different model bytes (branch ordinal comment)."""
    original = Provider.generate
    count = []

    def generate(self, system, user, **kwargs):
        result = original(self, system, user, **kwargs)
        if kwargs.get("label") == "implementor.code":
            count.append(1)
            result["forward_body"] += f"  # branch {len(count)}"
        return result

    monkeypatch.setattr(Provider, "generate", generate)


def test_verifier_refuses_a_relabelled_validator_verdict(
    prepared, training_runner, native_runner, trained
):
    """Review F1(a): both validators passed; the trace claims check0 rejected and the
    adaptor record/output are recomputed self-consistently to select check1. Model
    bytes are equal across branches, so only the verdict check can refuse.
    """
    from core.canonical_json import canonical_json_bytes
    from tools.candidate_worker.graph_evidence import record_digest
    from workflows.adaptors import (
        AdaptorInputRef,
        AdaptorItem,
        build_adaptor_record,
        run_deterministic_adaptor,
    )
    from workflows.definition import ResultSource

    request = selection_request(prepared)
    receipt, parent = run(request)
    assert receipt.status == "completed", receipt.error
    nodes = {item.node_id: item for item in receipt.graph_trace.nodes}
    adaptor = request.preview.document.definition.adaptors[0]
    items = []
    for position, node in enumerate(("check0", "check1")):
        entry = nodes[node]
        value = None
        if node == "check1":
            from agent.schemas.validator import ValidatorOutput

            value = ValidatorOutput.model_validate_json(Path(entry.record_path).read_bytes())
        items.append(
            AdaptorItem(
                ref=AdaptorInputRef(
                    port="checks",
                    position=position,
                    source=ResultSource(node=node),
                    record_sha256=entry.record_sha256,
                ),
                contract="validation.output",
                state="rejected" if node == "check0" else "succeeded",
                value=value,
            )
        )
    outcome = run_deterministic_adaptor(
        tuple(items),
        combine_strategy=adaptor.combine,
        select_strategy=adaptor.select,
        distribute_strategy=adaptor.distribute,
        metric=None,
    )
    forged_record = build_adaptor_record(
        adaptor_id="pick",
        iteration=1,
        combine=adaptor.combine,
        select=adaptor.select,
        distribute=adaptor.distribute,
        outcome=outcome,
    )
    workspace = Path(receipt.workspace)
    record_path = adaptor_record_path(workspace, "pick")
    output_path = adaptor_output_path(workspace, "pick", "result", None)
    for path, value in ((record_path, forged_record), (output_path, outcome.outputs[0].value)):
        path.unlink()
        path.write_bytes(canonical_json_bytes(value))
    trace = receipt.graph_trace
    forged = receipt.model_copy(
        update={
            "graph_trace": trace.model_copy(
                update={
                    "nodes": tuple(
                        item.model_copy(
                            update={"state": "rejected", "reason": "validation_rejected"}
                        )
                        if item.node_id == "check0"
                        else item
                        for item in trace.nodes
                    ),
                    "adaptors": (
                        trace.adaptors[0].model_copy(
                            update={"record_sha256": record_digest(str(record_path))}
                        ),
                    ),
                }
            ),
            "status": "completed",
        }
    )
    with pytest.raises(ValueError, match="contradicts its native verdict"):
        verify_graph_trace(request, parent, forged)


def test_verifier_binds_the_tuner_to_the_selected_branch_bytes(
    prepared, training_runner, rejecting, distinct_branches, trained
):
    """Review F1(b): the staged model must be the selected implementation's bytes."""
    from core.sandbox_executor import get_plugin_dir

    rejecting.add(0)
    request = selection_request(prepared)
    receipt, parent = run(request)
    assert receipt.status == "completed", receipt.error
    verify_graph_trace(request, parent, receipt)
    nodes = {item.node_id: item for item in receipt.graph_trace.nodes}
    sibling = json.loads(Path(nodes["build0"].record_path).read_bytes())["model_file_path"]
    staged = Path(get_plugin_dir(nodes["train"].storage, receipt.run_name)) / "worker_linear.py"
    assert staged.read_bytes() != Path(sibling).read_bytes()
    staged.write_bytes(Path(sibling).read_bytes())
    with pytest.raises(ValueError, match="staged model differs"):
        verify_graph_trace(request, parent, receipt)


def test_verifier_refuses_an_extra_adaptor_output_file(prepared, training_runner, native_runner):
    request = selection_request(prepared)
    receipt, parent = run(request)
    adaptor_output_path(Path(receipt.workspace), "pick", "result", 0).write_bytes(b"{}")
    with pytest.raises(ValueError, match="outputs its record does not derive"):
        verify_graph_trace(request, parent, receipt)


def _with_adaptor(receipt, entry):
    trace = receipt.graph_trace.model_copy(update={"adaptors": (entry,)})
    return receipt.model_copy(update={"graph_trace": trace})


@pytest.mark.parametrize("target", ["record", "output"])
def test_verifier_refuses_a_tampered_adaptor_record_or_output(
    prepared, training_runner, rejecting, trained, target
):
    rejecting.add(0)
    request = selection_request(prepared)
    receipt, parent = run(request)
    workspace = Path(receipt.workspace)
    if target == "record":
        # A self-consistent rewrite (trace digest updated too) is still recomputed.
        from tools.candidate_worker.graph_evidence import record_digest

        path = adaptor_record_path(workspace, "pick")
        forged = record(receipt)
        forged["admissible"][0]["admission"] = "admissible"
        path.unlink()
        path.write_bytes(json.dumps(forged, sort_keys=True, separators=(",", ":")).encode())
        (entry,) = receipt.graph_trace.adaptors
        receipt = _with_adaptor(
            receipt, entry.model_copy(update={"record_sha256": record_digest(str(path))})
        )
        match = "record does not match its recomputation"
    else:
        path = adaptor_output_path(workspace, "pick", "result", None)
        path.write_bytes(path.read_bytes().replace(b'"passed":true', b'"passed":false'))
        match = "output does not match its recomputation"
    with pytest.raises(ValueError, match=match):
        verify_graph_trace(request, parent, receipt)


def test_verifier_refuses_an_adaptor_closure_its_record_does_not_derive(
    prepared, training_runner, rejecting
):
    """Same state, other reason: readiness replay agrees, only recomputation can refuse."""
    rejecting.update((0, 1))
    request = selection_request(prepared)
    receipt, parent = run(request)
    (entry,) = receipt.graph_trace.adaptors
    forged = _with_adaptor(receipt, entry.model_copy(update={"reason": "insufficient_items"}))
    with pytest.raises(ValueError, match="terminal state does not match its record"):
        verify_graph_trace(request, parent, forged)


def _definition(request) -> dict:
    return request.preview.document.definition.model_dump(mode="json")


@pytest.mark.parametrize(
    "change,match",
    [
        (lambda d: d["adaptors"][0]["bindings"][0]["sources"].pop(), "every validator"),
        (
            lambda d: d["adaptors"][0]["bindings"][0]["sources"].append(
                {"kind": "result", "node": "check0"}
            ),
            "every validator",
        ),
        (
            lambda d: d["nodes"][-1]["request"]["arguments"][1].update(
                source={"kind": "result", "node": "check0"}
            ),
            None,
        ),
    ],
    ids=["unbound_validator", "duplicate_validator", "tuner_bypasses_adaptor"],
)
def test_selection_admission_refuses_other_shapes(prepared, change, match):
    """Only S1 is admitted: one adaptor over every validator, the S1 triple, tuner via adaptor."""
    request = selection_request(prepared)
    payload = _definition(request)
    change(payload)
    with pytest.raises(ValueError, match=match):
        execution_families(
            WorkflowDefinition.model_validate_json(json.dumps(payload)), SELECTION_PROFILE
        )


def test_selection_admits_only_the_s1_strategy_triple(prepared):
    """One branch makes all/v1 declarable (capacity 1); the profile still refuses it."""
    payload = _definition(selection_request(prepared, branches=1))
    payload["adaptors"][0]["select"] = {"kind": "all/v1"}
    definition = WorkflowDefinition.model_validate_json(json.dumps(payload))
    with pytest.raises(ValueError, match="pass/v1, first-admissible/v1 and single/v1"):
        execution_families(definition, SELECTION_PROFILE)


def test_other_profiles_still_refuse_the_selection_document(prepared):
    definition = selection_request(prepared).preview.document.definition
    assert execution_families(definition, SELECTION_PROFILE).selection is not None
    with pytest.raises(ValueError, match=ADAPTORS_NOT_ADMITTED):
        execution_families(definition, "native-proposal-fanout/v1")


def test_a_skipped_adaptor_input_is_refused_with_a_typed_error(prepared):
    """Unreachable until routed execution: no skip record exists for provenance."""
    from tools.candidate_worker.adaptor_phase import SkippedAdaptorInputError, adaptor_items
    from tools.candidate_worker.graph_models import GraphNodeEvidence

    definition = selection_request(prepared).preview.document.definition
    entries = {
        node: GraphNodeEvidence(
            node_id=node,
            capability="validation",
            predecessors=(),
            storage="/s",
            state="skipped",
            reason="route_not_selected",
        )
        for node in ("check0", "check1")
    }
    with pytest.raises(SkippedAdaptorInputError, match="B1-PR5"):
        adaptor_items(definition.adaptors[0], entries)
