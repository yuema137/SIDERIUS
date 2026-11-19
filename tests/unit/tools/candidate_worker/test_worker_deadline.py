"""The worker's wall budget reaches LLMBridge as the cooperative execution deadline (#1548),
and a stop by it is reported as running out of time (#1590).

``core.execution_deadline`` is the owner LLMBridge reads before each request,
each retry wait and each OpenAI background admission. These tests replace only
provider construction (``native_runner``) and observe the deadline every LLM
call would see, in the worker process and inside graph unit processes.
"""

import contextvars
import importlib
import math
from pathlib import Path

import pytest

from core.execution_deadline import (
    ExecutionDeadlineExceeded,
    execution_deadline,
    remaining_seconds,
)
from tests.helpers.candidate_fanout import fanout_request
from tools.candidate_worker import launch_candidate
from tools.candidate_worker.graph_evidence import read_graph_control
from tools.candidate_worker.unit_models import NodeInvocation
from tools.candidate_worker.unit_transport import decode_transport

from .test_native import Provider
from .test_native import native_runner as native_runner
from .test_training import training_runner as training_runner


def _observe_deadlines(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, float | None]]:
    """Record, per LLM call label, the remaining deadline the bridge would read."""
    seen: list[tuple[str, float | None]] = []
    generate, generate_text = Provider.generate, Provider.generate_text

    def observed(method):
        def call(self, system, user, **kwargs):
            seen.append((kwargs.get("label", ""), remaining_seconds("test.llm_call")))
            return method(self, system, user, **kwargs)

        return call

    monkeypatch.setattr(Provider, "generate", observed(generate))
    monkeypatch.setattr(Provider, "generate_text", observed(generate_text))
    return seen


def test_fixed_worker_llm_calls_see_the_worker_budget(prepared, native_runner, monkeypatch):
    """Defect #1548: the worker's timeout_seconds was enforced only by the sandbox kill,
    so LLMBridge saw no deadline (remaining_seconds() is None) and could start retry
    waits or background windows the worker could never finish. Fails if any LLM call
    in the worker process sees no deadline, or one longer than timeout_seconds."""
    seen = _observe_deadlines(monkeypatch)
    receipt = launch_candidate(prepared)
    assert receipt.status == "accepted", receipt.error
    assert seen
    assert all(
        value is not None and math.isfinite(value) and 0 < value <= prepared.timeout_seconds
        for _, value in seen
    ), seen


def test_graph_unit_processes_bind_the_dispatched_remaining_budget(
    prepared, native_runner, monkeypatch
):
    """Defect #1548: graph units are separate processes, and only the validation unit
    carried the worker's remaining budget (#984), so proposal and implementation calls
    ran without a deadline. Each unit here runs in an empty context, as a fresh process
    would, so only the unit's own binding can supply the deadline. Fails if any unit's
    LLM call sees no deadline, or if a unit invocation omits the remaining budget."""
    from tools.candidate_worker.unit_child import run_invocation_file

    def unit_in_fresh_context(invocation_path):
        contextvars.Context().run(run_invocation_file, Path(invocation_path))

    monkeypatch.setattr(
        importlib.import_module("tools.candidate_worker.unit_runner"),
        "spawn_unit",
        unit_in_fresh_context,
    )
    seen = _observe_deadlines(monkeypatch)
    request = fanout_request(prepared)
    receipt = launch_candidate(request)
    assert receipt.status == "accepted", receipt.error
    labels = {label for label, _ in seen}
    assert any(label.startswith("proposer") or "proposal" in label for label in labels), labels
    assert all(value is not None and 0 < value <= request.timeout_seconds for _, value in seen), (
        seen
    )
    invocations = list(Path(receipt.workspace).rglob("units/*/invocation.json"))
    assert invocations
    for path in invocations:
        invocation = decode_transport(NodeInvocation, read_graph_control(path))
        budget = invocation.worker_budget_seconds
        assert budget is not None and 0 < budget <= request.timeout_seconds, path


def _refuse_llm_calls(monkeypatch: pytest.MonkeyPatch, refusal) -> None:
    """Every LLM call raises what ``refusal()`` raises, inside the caller's context."""

    def call(self, system, user, **kwargs):
        refusal()
        raise AssertionError("refusal() must raise")

    monkeypatch.setattr(Provider, "generate", call)
    monkeypatch.setattr(Provider, "generate_text", call)


def _worker_deadline_refusal() -> None:
    # Created where the bridge would raise it: inside the worker's own scope.
    raise ExecutionDeadlineExceeded("Execution deadline exhausted at llm.request")


def test_fixed_worker_deadline_stop_is_timed_out(prepared, native_runner, monkeypatch):
    """Defect #1590: since #1548 the worker deadline can stop a run before the sandbox
    kill, and that stop ended as `failed` (`worker exit 1`) although a kill at the same
    limit ends `timed_out`. Fails if the receipt is not `timed_out` with the
    worker-deadline error, or if it claims any native output."""
    _refuse_llm_calls(monkeypatch, _worker_deadline_refusal)
    receipt = launch_candidate(prepared)
    assert receipt.status == "timed_out", receipt.error
    assert (receipt.error or "").startswith("worker_deadline_exceeded: ")
    assert receipt.native_output_paths == () and receipt.validation_passed is None


def test_fixed_worker_shorter_nested_deadline_stays_failed(prepared, native_runner, monkeypatch):
    """Defect #1590 (scope): only the worker's own budget is reported as running out
    of time. A refusal by a shorter nested allocation, such as a Data Analysis
    wall-time budget, is an ordinary failure. Fails if it is reported `timed_out`."""

    def nested_refusal() -> None:
        with execution_deadline(1e-9):
            remaining_seconds("nested.request")

    _refuse_llm_calls(monkeypatch, nested_refusal)
    receipt = launch_candidate(prepared)
    assert receipt.status == "failed", receipt.error


def test_graph_unit_deadline_stop_closes_node_deadline_exceeded(
    prepared, native_runner, monkeypatch
):
    """Defect #1590 (graph): a graph unit stopped by the worker's remaining budget
    closed `failed`/`native_failure`, indistinguishable from a crash in the node. The
    unit runs in an empty context, as a fresh process would, so only its own binding
    can classify the stop. Fails if no node closes `failed`/`deadline_exceeded`."""
    from tools.candidate_worker.unit_child import run_invocation_file

    def unit_in_fresh_context(invocation_path):
        contextvars.Context().run(run_invocation_file, Path(invocation_path))

    monkeypatch.setattr(
        importlib.import_module("tools.candidate_worker.unit_runner"),
        "spawn_unit",
        unit_in_fresh_context,
    )
    _refuse_llm_calls(monkeypatch, _worker_deadline_refusal)
    receipt = launch_candidate(fanout_request(prepared))
    assert receipt.graph_trace is not None, receipt.error
    reasons = {(item.state, item.reason) for item in receipt.graph_trace.nodes}
    assert ("failed", "deadline_exceeded") in reasons, reasons
    assert ("failed", "native_failure") not in reasons, reasons


@pytest.mark.parametrize(
    ("raised", "reason"),
    [(_worker_deadline_refusal, "deadline_exceeded"), (None, "native_failure")],
    ids=["worker-stop", "ordinary-failure"],
)
def test_adaptor_stop_closes_deadline_exceeded_and_verifies(
    prepared, native_runner, training_runner, monkeypatch, raised, reason
):
    """Defect #1603 (Refs #1601 item 1): an adaptor stopped by the worker's budget
    closed `failed`/`native_failure`, indistinguishable from a broken adaptor. It now
    takes the native-node classifier's `deadline_exceeded`; any other exception stays
    `native_failure`. The verifier must accept either closure. Fails if the reasons
    are not distinct or the parent refuses the trace."""
    from tests.helpers.candidate_fanout import selection_request
    from tools.candidate_worker.graph_evidence import verify_graph_trace

    from .test_graph import initial

    def decide(*_args, **_kwargs):
        if raised is not None:
            raised()
        raise RuntimeError("adaptor implementation is broken")

    monkeypatch.setattr(
        importlib.import_module("tools.candidate_worker.adaptor_phase"), "decide", decide
    )
    request = selection_request(prepared)
    receipt = launch_candidate(request)
    assert receipt.graph_trace is not None, receipt.error
    (adaptor,) = receipt.graph_trace.adaptors
    assert (adaptor.state, adaptor.reason, adaptor.record_path) == ("failed", reason, None)
    parent = initial(request).model_copy(update={"run_id": receipt.run_id})
    verify_graph_trace(request, parent, receipt)
