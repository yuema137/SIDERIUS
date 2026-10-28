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
    # The sibling rejection still counts in the existing body aggregate.
    assert (receipt.status, receipt.validation_passed) == ("rejected", False)
    verify_graph_trace(request, parent, receipt)


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
    assert receipt.status == "rejected"
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
