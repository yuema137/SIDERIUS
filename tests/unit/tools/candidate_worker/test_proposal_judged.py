"""B6-8b: N proposals -> LLM COMBINE -> one branch per output (``native-proposal-judged/v1``).

Offline pseudo integration: real proposer/implementor/validator bodies with the stub
provider, real readiness, the B6-8a executor and verifier replay. Only the judge
bridge is a stub. Each test names the defect it catches.
"""

import json
from pathlib import Path

import pytest

from tests.helpers.candidate_literature import proposal_judged_request
from tests.unit.workflows.test_debate_judge import DebateBridge
from tools.candidate_worker import adaptor_phase, graph, graph_evidence, phases, unit_dispatch
from tools.candidate_worker.graph_evidence import verify_graph_trace
from tools.workflow_preview import WorkflowPreviewRequest, preview_workflow
from workflows.definition import AdaptorSource

from .test_literature_adaptors import run, states
from .test_native import native_runner as native_runner


def debate_rank(**overrides):
    return {
        "kind": "debate-judge/v1",
        "route_slot": "debate",
        "max_calls": 4,
        "guidance": "none",
        "criterion": "Which proposal deserves an implementation?",
        "rounds": 1,
        "critic": False,
        "judge_output": "rank",
        **overrides,
    }


@pytest.fixture
def consumed(monkeypatch):
    """(implementation node, implemented candidate_id, seed owner), in run order.

    The seed owner is read from the seed's per-proposal debug path, so a branch that
    implements the right proposal with another proposal's task facts is visible.
    """
    seen: list[tuple[str, str | None, str]] = []
    original = phases.run_implementation

    def record(context, request, initial, inputs, config, proposal, blocks):
        owner = Path(inputs.proposal.debug_dump_proposing_prompt_path).parent.name
        seen.append((context.node_id, proposal.candidate_id, owner))
        return original(context, request, initial, inputs, config, proposal, blocks)

    monkeypatch.setattr(phases, "run_implementation", record)
    return seen


def candidate_ids(receipt) -> dict[str, str]:
    ids = {}
    for item in receipt.graph_trace.nodes:
        if item.capability == "proposal":
            ids[item.node_id] = json.loads(Path(item.record_path).read_bytes())["candidate_id"]
    return ids


def judged(prepared, **overrides):
    fields = {
        "combine": debate_rank(),
        "select": {"kind": "top-k/v1", "k": 2},
        "distribute": {"kind": "per-item/v1", "count": 2, "on_short": "fail"},
    }
    return proposal_judged_request(prepared, **{**fields, **overrides})


def test_top2_proposals_reach_their_branches_in_the_judges_order(
    prepared, native_runner, consumed, monkeypatch
):
    """Defect: branch i implements a proposal other than the judge's i-th choice (declared
    order, a sibling, or the proposal node with the same index), or readback re-runs."""
    bridge = DebateBridge(order=["proposals:2", "proposals:0", "proposals:1"])
    monkeypatch.setattr("agent.judge.call.bridge_for_route", lambda route: bridge)
    request = judged(prepared)
    receipt, parent = run(request)
    assert receipt.status == "accepted", receipt.error
    ids = candidate_ids(receipt)
    proposals = sorted(ids)
    implementations = sorted(node for node, _, _ in consumed)
    assert {node: (cid, owner) for node, cid, owner in consumed} == {
        implementations[0]: (ids[proposals[2]], proposals[2]),
        implementations[1]: (ids[proposals[0]], proposals[0]),
    }
    calls = len(bridge.calls)
    verify_graph_trace(request, parent, receipt)
    assert len(bridge.calls) == calls


def test_a_failed_judge_blocks_every_branch(prepared, native_runner, consumed, monkeypatch):
    """Defect: branches run on an undecided ranking (e.g. falling back to proposal order)."""
    bridge = DebateBridge(order=["proposals:0"])
    monkeypatch.setattr("agent.judge.call.bridge_for_route", lambda route: bridge)
    request = judged(prepared)
    receipt, parent = run(request)
    assert states(receipt)["rank"] == ("failed", "judge_failure")
    assert consumed == []
    verify_graph_trace(request, parent, receipt)


def _swapped_selection(real):
    """Runtime fault: each judged branch reads the other ranked output (0 <-> 1)."""

    def selected(shape, outcomes, node_id):
        source = shape.judged_source(node_id)
        if source is None:
            return real(shape, outcomes, node_id)
        index = 1 - source.index
        outcome = outcomes[source.adaptor]
        output = next(item for item in outcome.outputs if item.index == index)
        value = adaptor_phase.adaptor_value(
            outcome, AdaptorSource(adaptor=source.adaptor, index=index)
        )
        return value, output.inputs[0].source.node

    return selected


def test_a_swapped_judged_selection_fails_verification(prepared, native_runner, monkeypatch):
    """Defect: branch 0 implements the other ranked proposal (outputs swapped at runtime),
    yet the replay accepts it because it never checks which judged output a branch consumed."""
    bridge = DebateBridge(order=["proposals:2", "proposals:0", "proposals:1"])
    monkeypatch.setattr("agent.judge.call.bridge_for_route", lambda route: bridge)
    swapped = _swapped_selection(adaptor_phase.judged_proposal)
    monkeypatch.setattr(unit_dispatch, "judged_proposal", swapped)
    monkeypatch.setattr(graph, "judged_proposal", swapped)
    # Launch replays the same receipt on the same path; bypass only that call so the
    # replay under test (verify_graph_trace) is the one that refuses the swapped record.
    monkeypatch.setattr(graph_evidence, "verify_graph_trace", lambda *args, **kwargs: None)
    request = judged(prepared)
    receipt, parent = run(request)
    assert receipt.status == "accepted", receipt.error
    monkeypatch.undo()
    with pytest.raises(ValueError, match="consumed a proposal or seed other than"):
        verify_graph_trace(request, parent, receipt)


def _other_owner_seed(real):
    """Runtime fault: the branch runs on the seed of the other branch's owner."""

    def selected(shape, outcomes, node_id):
        selected = real(shape, outcomes, node_id)
        if selected is None:
            return None
        value, _owner = selected
        for implementation, _validation in shape.branches:
            if implementation != node_id and shape.judged_source(implementation) is not None:
                _, other = real(shape, outcomes, implementation)
                return value, other
        raise AssertionError("two judged branches are required")

    return selected


def test_a_branch_run_on_another_owners_seed_fails_verification(
    prepared, native_runner, monkeypatch
):
    """Defect: a branch implements its ranked proposal but on the seed of another proposal
    owner (the seed swap in graph dispatch is removed or misdirected); replay accepts it."""
    bridge = DebateBridge(order=["proposals:2", "proposals:0", "proposals:1"])
    monkeypatch.setattr("agent.judge.call.bridge_for_route", lambda route: bridge)
    monkeypatch.setattr(graph, "judged_proposal", _other_owner_seed(adaptor_phase.judged_proposal))
    monkeypatch.setattr(graph_evidence, "verify_graph_trace", lambda *args, **kwargs: None)
    request = judged(prepared)
    receipt, parent = run(request)
    assert receipt.status == "accepted", receipt.error
    monkeypatch.undo()
    with pytest.raises(ValueError, match="consumed a proposal or seed other than"):
        verify_graph_trace(request, parent, receipt)


def _nonfinite_variant(real):
    """Runtime fault: the branch implements its ranked proposal with an ``Any`` leaf
    turned from ``None`` into ``inf`` (eager JSON-mode dumps null both)."""

    def selected(shape, outcomes, node_id):
        selected = real(shape, outcomes, node_id)
        if selected is None:
            return None
        value, owner = selected
        baseline = {**value.baseline_config, "fixture_limit": float("inf")}
        return value.model_copy(update={"baseline_config": baseline}), owner

    return selected


def _proposer_any_leaf(monkeypatch, value):
    """Every generated proposal carries ``value`` in an ``Any`` field (``baseline_config``)."""
    from .test_native import Provider

    proposer = Provider.generate

    def generate(self, system, user, **kwargs):
        output = proposer(self, system, user, **kwargs)
        if "baseline_config" in output:
            output["baseline_config"] = {**output["baseline_config"], "fixture_limit": value}
        return output

    monkeypatch.setattr(Provider, "generate", generate)


@pytest.mark.parametrize("writer", ["current", "historical"])
def test_nonfinite_any_inputs_replay_under_their_recorded_encoding(
    prepared, native_runner, monkeypatch, writer
):
    """Defect (#1326): replay recomputes a stamp under an encoding other than the one
    that wrote it. An honest branch whose proposal has ``inf`` in an ``Any`` field is
    refused if the verifier ignores ``consumed_input_encoding`` (current writer) or
    always applies the current encoding (an archive written before the field, whose
    stamp is reproduced here with the pre-#1326 eager projection)."""
    from core.canonical_json import canonical_sha256

    _proposer_any_leaf(monkeypatch, float("inf"))
    if writer == "historical":
        monkeypatch.setattr(phases, "ENCODING_VERSION", None)
        monkeypatch.setattr(
            phases,
            "consumed_input_sha256",
            lambda seed, proposal, version: canonical_sha256(
                {"proposal": proposal.model_dump(mode="json"), "seed": seed.model_dump(mode="json")}
            ),
        )
    bridge = DebateBridge(order=["proposals:2", "proposals:0", "proposals:1"])
    monkeypatch.setattr("agent.judge.call.bridge_for_route", lambda route: bridge)
    monkeypatch.setattr(graph_evidence, "verify_graph_trace", lambda *args, **kwargs: None)
    request = judged(prepared)
    receipt, parent = run(request)
    assert receipt.status == "accepted", receipt.error
    monkeypatch.undo()
    records = [
        json.loads(Path(item.record_path).read_bytes())
        for item in receipt.graph_trace.nodes
        if item.capability == "implementation"
    ]
    assert len(records) == 2
    assert all(("consumed_input_encoding" in item) == (writer == "current") for item in records)
    verify_graph_trace(request, parent, receipt)


def _stripped_encoding_forgery(prepared, monkeypatch):
    """A verified judged run and its implementation record downgraded to the legacy digest.

    The forgery removes ``consumed_input_encoding`` (an ``inf`` sits in an ``Any``
    field) and rewrites the stamp to the legacy digest the historical verifier
    accepts, so only the trace's ``record_sha256`` anchor can refuse it.
    Returns ``(request, parent, receipt, path, forged bytes)``.
    """
    from core.canonical_json import canonical_sha256

    _proposer_any_leaf(monkeypatch, float("inf"))
    consumed: list[tuple] = []
    stamp = phases.consumed_input_sha256

    def recorded(seed, proposal, *, version):
        consumed.append((seed, proposal))
        return stamp(seed, proposal, version=version)

    monkeypatch.setattr(phases, "consumed_input_sha256", recorded)
    bridge = DebateBridge(order=["proposals:2", "proposals:0", "proposals:1"])
    monkeypatch.setattr("agent.judge.call.bridge_for_route", lambda route: bridge)
    monkeypatch.setattr(graph_evidence, "verify_graph_trace", lambda *args, **kwargs: None)
    request = judged(prepared)
    receipt, parent = run(request)
    assert receipt.status == "accepted", receipt.error
    monkeypatch.undo()
    verify_graph_trace(request, parent, receipt)

    node = next(item for item in receipt.graph_trace.nodes if item.capability == "implementation")
    path = Path(node.record_path)
    raw = json.loads(path.read_bytes())
    seed, proposal = next(
        (seed, proposal)
        for seed, proposal in consumed
        if stamp(seed, proposal, version="siderius.nonfinite/v1") == raw["consumed_input_sha256"]
    )
    legacy = canonical_sha256(
        {"proposal": proposal.model_dump(mode="json"), "seed": seed.model_dump(mode="json")}
    )
    assert legacy != raw["consumed_input_sha256"]
    del raw["consumed_input_encoding"]
    raw["consumed_input_sha256"] = legacy
    return request, parent, receipt, path, json.dumps(raw, indent=2).encode()


def test_a_stripped_consumed_input_encoding_is_refused_by_the_record_anchor(
    prepared, native_runner, monkeypatch
):
    """Threat model (#1326): ``consumed_input_encoding`` is dispatch, not authentication.

    A forger downgrades a current judged record (``inf`` in an ``Any`` field) by
    removing its encoding and rewriting the stamp to the legacy digest the
    historical verifier would accept. The trace's unchanged ``record_sha256``
    anchor refuses it before any recomputation."""
    request, parent, receipt, path, forged = _stripped_encoding_forgery(prepared, monkeypatch)
    path.write_bytes(forged)
    with pytest.raises(ValueError, match="graph native record mismatch"):
        verify_graph_trace(request, parent, receipt)


def test_a_judged_record_swapped_after_its_digest_check_is_refused(
    prepared, native_runner, monkeypatch
):
    """#1407: ``verify_judged_branches`` re-read the implementation record after the
    trace's ``record_sha256`` check without re-hashing it, so the downgrade forgery
    above, written in that window, replayed against the legacy digest and was
    accepted. The judged read must re-hash the bytes it parses; without that
    ``pytest.raises`` fails."""
    from .test_graph_training import swap_after

    request, parent, receipt, path, forged = _stripped_encoding_forgery(prepared, monkeypatch)
    swapped = swap_after(monkeypatch, graph_evidence, "record_digest", path, forged)
    with pytest.raises(ValueError, match="graph native record mismatch"):
        verify_graph_trace(request, parent, receipt)
    assert swapped == [path]


def test_a_judged_validation_swapped_after_its_verdict_check_is_refused(
    prepared, native_runner, monkeypatch
):
    """#1407: ``verify_judged_branches`` re-read each validation record after its
    hashed verdict check and compared only ``candidate_id``, so a record relabelled
    ``passed: false`` in that window stood behind a ``succeeded`` trace entry.
    The judged read must re-hash the bytes it parses; without that ``pytest.raises``
    fails."""
    from .test_graph_training import swap_after

    bridge = DebateBridge(order=["proposals:2", "proposals:0", "proposals:1"])
    monkeypatch.setattr("agent.judge.call.bridge_for_route", lambda route: bridge)
    request = judged(prepared)
    receipt, parent = run(request)
    assert receipt.status == "accepted", receipt.error
    node = next(
        item
        for item in receipt.graph_trace.nodes
        if item.capability == "validation" and item.state == "succeeded"
    )
    path = Path(node.record_path)
    raw = json.loads(path.read_bytes())
    assert raw["passed"] is True
    forged = json.dumps({**raw, "passed": False}, indent=2).encode()
    swapped = swap_after(monkeypatch, graph_evidence, "_check_validation_verdict", path, forged)
    with pytest.raises(ValueError, match="graph native record mismatch"):
        verify_graph_trace(request, parent, receipt)
    assert swapped == [path]


def test_a_branch_run_on_a_nonfinite_variant_fails_verification(
    prepared, native_runner, monkeypatch
):
    """Defect (#1326): the consumed-input digest projects ``Any`` fields through
    ``model_dump(mode="json")``, so a branch that ran on ``inf`` where the ranked
    proposal says ``None`` shares its identity and replay accepts it. With the eager
    projection restored, ``verify_graph_trace`` passes and ``pytest.raises`` fails;
    without the worker's version stamp the record replays as historical and passes."""
    from agent.schemas.implementor import ImplementorOutput
    from core.record_encoding import ENCODING_VERSION

    _proposer_any_leaf(monkeypatch, None)
    bridge = DebateBridge(order=["proposals:2", "proposals:0", "proposals:1"])
    monkeypatch.setattr("agent.judge.call.bridge_for_route", lambda route: bridge)
    variant = _nonfinite_variant(adaptor_phase.judged_proposal)
    monkeypatch.setattr(unit_dispatch, "judged_proposal", variant)
    monkeypatch.setattr(graph, "judged_proposal", variant)
    monkeypatch.setattr(graph_evidence, "verify_graph_trace", lambda *args, **kwargs: None)
    request = judged(prepared)
    receipt, parent = run(request)
    assert receipt.status == "accepted", receipt.error
    monkeypatch.undo()
    implemented = [
        ImplementorOutput.model_validate_json(Path(item.record_path).read_bytes())
        for item in receipt.graph_trace.nodes
        if item.capability == "implementation"
    ]
    assert {item.consumed_input_encoding for item in implemented} == {ENCODING_VERSION}
    with pytest.raises(ValueError, match="consumed a proposal or seed other than"):
        verify_graph_trace(request, parent, receipt)


class ProposalMergeBridge:
    """Merges by returning one proposal record a proposal node persisted, with every
    framework-owned field left unset (the author contract of ``proposal.output``)."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.calls: list[str] = []

    def set_run_context(self, **kwargs) -> None:
        pass

    def generate(self, system_prompt: str, user_prompt: str, *, label: str):
        self.calls.append(label)
        facts = json.loads(user_prompt.split("Facts (JSON):\n", 1)[1])
        record = next(self.workspace.rglob("graph_instances/propose0/**/proposal_*.json"))
        value = json.loads(record.read_bytes())
        for field in (
            "candidate_id",
            "observed_prediction_reference",
            "preflight_estimated_minutes",
            "preflight_factor",
        ):
            value[field] = None
        value["proposed_discoveries"] = []
        parents = [item["item_id"] for item in facts["items"]]
        return {
            "kind": "synthesis",
            "items": [{"parents": parents, "value": value}],
            "rationale": "fixture",
        }


def test_a_merged_proposal_gets_a_replayable_system_identity_and_verifies(
    prepared, native_runner, consumed, monkeypatch
):
    """Defect: a judge-merge proposal (no LLM candidate_id) is refused by the validation
    join, gets a non-deterministic identity that replay cannot reproduce, or its branch
    implements another proposal."""
    from agent.schemas.proposal import mint_candidate_id

    workspace = Path(prepared.preview.document.definition.task.workspace)
    bridge = ProposalMergeBridge(workspace)
    monkeypatch.setattr("agent.judge.call.bridge_for_route", lambda route: bridge)
    merge = {
        "kind": "judge-merge/v1",
        "route_slot": "aggregate",
        "max_calls": 1,
        "guidance": "none",
        "criterion": "Merge the proposals into one.",
        "synthesize_count": 1,
        "min_parents": 2,
    }
    request = judged(
        prepared,
        combine=merge,
        select={"kind": "all/v1"},
        distribute={"kind": "single/v1"},
    )
    receipt, parent = run(request)
    assert receipt.status == "accepted", receipt.error
    record = json.loads(Path(receipt.graph_trace.adaptors[0].record_path).read_bytes())
    output = record["outputs"][0]
    expected = mint_candidate_id(
        json.loads(next(workspace.rglob("**/rank.judge/strategy.json")).read_bytes())["outcome"][
            "combined"
        ]["items"][0]["value_sha256"]
    )
    assert output["status"] == "emitted"
    assert [cid for _, cid, _ in consumed] == [expected]
    assert expected not in candidate_ids(receipt).values()
    verify_graph_trace(request, parent, receipt)


def _refused(request, change, match):
    raw = request.preview.model_dump(mode="json")
    change(raw)
    with pytest.raises(ValueError, match=match):
        preview_workflow(WorkflowPreviewRequest.model_validate_json(json.dumps(raw)))


def test_profile_admission_refusals(prepared):
    """Defect: a judged branch reads a proposal node directly, two branches read one output,
    or the profile admits a deterministic COMBINE."""
    request = judged(prepared)

    def nodes(raw):
        return raw["document"]["definition"]["nodes"]

    def implementation(raw, position):
        return sorted(
            (node for node in nodes(raw) if node["capability"] == "implementation"),
            key=lambda node: node["id"],
        )[position]

    def output(node):
        return next(arg for arg in node["request"]["arguments"] if arg["name"] == "output")

    def direct(raw):
        output(implementation(raw, 0))["source"] = {"kind": "result", "node": "propose0"}

    def duplicate(raw):
        for node in nodes(raw):  # branch 1 (implementation and validation) reads output 0
            for arg in node["request"]["arguments"] if "arguments" in node["request"] else ():
                if arg["source"].get("adaptor") == "rank":
                    arg["source"]["index"] = 0

    def deterministic(raw):
        adaptor = raw["document"]["definition"]["adaptors"][0]
        adaptor["combine"] = {"kind": "pass/v1"}
        adaptor["select"] = {"kind": "all/v1"}
        adaptor["distribute"] = {"kind": "per-item/v1", "count": 3, "on_short": "skip"}

    for change, match in (
        (direct, "unsupported source|AdaptorSource|adaptor output"),
        (duplicate, "one branch per adaptor output index"),
        (deterministic, "requires an LLM COMBINE kind"),
    ):
        _refused(request, change, match)


@pytest.fixture
def executed(monkeypatch):
    """Validation protocol ids the validation units actually executed, in run order."""
    from workflows.candidate_validation_join import VALIDATION_PROTOCOLS

    seen: list[str] = []

    def spy(protocol, function):
        def run(*args, **kwargs):
            seen.append(protocol)
            return function(*args, **kwargs)

        return run

    monkeypatch.setattr(
        phases,
        "VALIDATION_PROTOCOLS",
        {protocol: spy(protocol, function) for protocol, function in VALIDATION_PROTOCOLS.items()},
    )
    return seen


def _implementation_only_validators(request):
    """Rewrite every judged validator to ``implementation-to-validation(output=<impl>)``."""
    raw = request.preview.model_dump(mode="json")
    for node in raw["document"]["definition"]["nodes"]:
        if node["capability"] != "validation":
            continue
        request_ = node["request"]
        arguments = {arg["name"]: arg for arg in request_["arguments"]}
        implementation = arguments.pop("implementation")
        arguments.pop("proposal", None)
        request_["protocol"] = "implementation-to-validation"
        request_["arguments"] = [
            {"name": "output", "source": implementation["source"]},
            *(arg for name, arg in arguments.items() if name in ("storage", "constraint_context")),
        ]
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


@pytest.mark.parametrize(
    "protocol", ["proposed-implementation-to-validation", "implementation-to-validation"]
)
def test_a_judged_validator_executes_the_protocol_it_declares(
    prepared, native_runner, executed, monkeypatch, protocol
):
    """Defect: the validation unit runs proposed-implementation-to-validation whatever
    the declaration names, so a declared implementation-to-validation never executes."""
    bridge = DebateBridge(order=["proposals:2", "proposals:0", "proposals:1"])
    monkeypatch.setattr("agent.judge.call.bridge_for_route", lambda route: bridge)
    request = judged(prepared)
    if protocol == "implementation-to-validation":
        request = _implementation_only_validators(request)
    receipt, parent = run(request)
    assert receipt.status == "accepted", receipt.error
    assert executed == [protocol, protocol]
    verify_graph_trace(request, parent, receipt)


def test_every_catalog_validation_protocol_has_an_executor():
    """Defect: a catalog validation protocol is declarable but no executor runs it."""
    from workflows.candidate_validation_join import VALIDATION_PROTOCOLS
    from workflows.definition.catalog import PROTOCOLS

    declared = {key for key, value in PROTOCOLS.items() if value.output == "validation.input"}
    assert set(VALIDATION_PROTOCOLS) == declared
