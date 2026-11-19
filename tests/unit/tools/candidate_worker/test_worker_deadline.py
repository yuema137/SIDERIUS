"""The worker's wall budget reaches LLMBridge as the cooperative execution deadline (#1548).

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

from core.execution_deadline import remaining_seconds
from tests.helpers.candidate_fanout import fanout_request
from tools.candidate_worker import launch_candidate
from tools.candidate_worker.graph_evidence import read_graph_control
from tools.candidate_worker.unit_models import NodeInvocation
from tools.candidate_worker.unit_transport import decode_transport

from .test_native import Provider
from .test_native import native_runner as native_runner


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
