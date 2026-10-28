"""Graph units in real child processes reproduce the in-process dispatch (B3-3).

Every other graph test runs units through the in-process seam installed by
`native_runner`. Here the real `spawn_unit` supervises real unit children; a
generated harness replaces only provider construction (and, per case, one
native phase) inside each child before running the actual `unit_child` entry.
The harness puts this checkout's `src` first on the child's `sys.path`, so a
copied checkout's children import that copy, and every child reports which
`unit_child` it imported.
"""

import inspect
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from tests.helpers.candidate_fanout import fanout_request
from tools.candidate_worker import launch_candidate
from tools.candidate_worker.graph_evidence import verify_graph_trace
from tools.candidate_worker.unit_runner import spawn_unit as real_spawn_unit

from .conftest import REPO
from .test_branch_isolation import another_prepared, stable
from .test_graph import initial
from .test_native import Provider, native_runner
from .test_readiness import UNROUTED_TRACE_SHA256, trace_sha256

PROBE = "b33_registry_probe"
HARNESS = """import json, os, runpy, subprocess, sys
sys.path[:0] = [{src!r}, {repo!r}]
from pathlib import Path
from typing import ClassVar
{provider}
CONFIG = json.loads(Path({config!r}).read_text())
LOG = Path(CONFIG["log"])
def log(**row):
    with LOG.open("a") as stream:
        stream.write(json.dumps(row) + "\\n")
Provider.reject = False
def recorded(method):
    def call(self, system, user, **kwargs):
        log(kind="prompt", call=[kwargs.get("label", ""), system, user])
        return method(self, system, user, **kwargs)
    return call
Provider.generate = recorded(Provider.generate)
Provider.generate_text = recorded(Provider.generate_text)
import importlib
for name in ("ml_model_proposal_agent", "ml_model_implementor", "ml_code_validator_agent"):
    importlib.import_module(f"nodes.{{name}}.{{name}}").LLMBridge = Provider
from ml_models import models_sandbox
from tools.candidate_worker import phases, unit_child
log(kind="unit", pid=os.getpid(), module=unit_child.__file__)
implementation, validation, proposal = (
    phases.run_implementation, phases.run_validation, phases.run_proposal
)
def implement(*args, **kwargs):
    if CONFIG["fail"] == "raise":
        raise RuntimeError("uncertain native failure")
    if CONFIG["fail"] == "crash":
        os._exit(9)
    models_sandbox.MODEL_REGISTRY[{probe!r}] = object
    return implementation(*args, **kwargs)
def validate(*args, **kwargs):
    log(kind="probe", visible={probe!r} in models_sandbox.MODEL_REGISTRY)
    return validation(*args, **kwargs)
def propose(*args, **kwargs):
    from core.runtime_control.observed_subprocess import supervise_subprocess
    from core.subprocess_env import subprocess_env
    inner = supervise_subprocess(
        [sys.executable, "-c", "pass"], env=subprocess_env(), preexec_fn=None,
        capture_stdout=False,
    )
    log(kind="inner", pid=inner.lifecycle.child_pid)
    return proposal(*args, **kwargs)
phases.run_implementation, phases.run_validation, phases.run_proposal = (
    implement, validate, propose
)
sys.argv = ["tools.candidate_worker.unit_child", sys.argv[1]]
runpy.run_module("tools.candidate_worker.unit_child", run_name="__main__")
"""


def run_real_units(request, monkeypatch, tmp_path, fail):
    """Launch through the worker with every graph unit in a real child process."""
    from tools.candidate_worker import unit_runner

    log = tmp_path / f"units_{fail}.jsonl"
    config = tmp_path / f"harness_{fail}.json"
    config.write_text(json.dumps({"fail": fail, "log": str(log)}))
    harness = tmp_path / f"unit_harness_{fail}.py"
    harness.write_text(
        HARNESS.format(
            src=str(REPO / "src"),
            repo=str(REPO),
            provider=inspect.getsource(Provider),
            config=str(config),
            probe=PROBE,
        )
    )
    monkeypatch.setattr(unit_runner, "spawn_unit", real_spawn_unit)
    monkeypatch.setattr(
        unit_runner, "unit_command", lambda path: [sys.executable, str(harness), path]
    )
    from core.runtime_control.observed_subprocess import observe_process_lifecycle

    observed = []
    with observe_process_lifecycle(observed.append):
        receipt = launch_candidate(request)
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    return receipt, rows, observed


def normalized_view(receipt, project, prompts):
    def normalized(text):
        return text.replace(receipt.workspace, "<ws>").replace(project, "<project>")

    return {
        "prompts": [[normalized(part) for part in call] for call in prompts],
        "records": [
            stable(json.loads(Path(item.record_path).read_bytes()), normalized)
            for item in receipt.graph_trace.nodes
        ],
    }


def test_real_unit_processes_reproduce_the_in_process_body(
    prepared, native_runner, monkeypatch, tmp_path
):
    """Fails if the process boundary changes a prompt, record or trace byte, shares a
    process registry between units, or drops a unit's subprocess lifecycle evidence."""
    from ml_models import models_sandbox

    reference = fanout_request(another_prepared(tmp_path, "in_process"))
    prompts = []
    generate, generate_text = Provider.generate, Provider.generate_text

    def recorded(method):
        def call(self, system, user, **kwargs):
            prompts.append([kwargs.get("label", ""), system, user])
            return method(self, system, user, **kwargs)

        return call

    with monkeypatch.context() as patch:
        patch.setattr(Provider, "generate", recorded(generate))
        patch.setattr(Provider, "generate_text", recorded(generate_text))
        expected = launch_candidate(reference)
    assert expected.status == "accepted", expected.error

    request = fanout_request(prepared)
    receipt, rows, observed = run_real_units(request, monkeypatch, tmp_path, "none")
    assert receipt.status == "accepted", receipt.error
    assert trace_sha256(receipt) == UNROUTED_TRACE_SHA256["accepted"]
    assert normalized_view(
        receipt,
        request.preview.project_root,
        [row["call"] for row in rows if row["kind"] == "prompt"],
    ) == normalized_view(expected, reference.preview.project_root, prompts)

    units = [row for row in rows if row["kind"] == "unit"]
    assert len(units) == len(receipt.graph_trace.nodes)
    assert len({row["pid"] for row in units} | {os.getpid()}) == len(units) + 1
    assert {Path(row["module"]).resolve() for row in units} == {
        (REPO / "src/tools/candidate_worker/unit_child.py").resolve()
    }
    # Each implementation registered the probe in its own process only.
    assert [row["visible"] for row in rows if row["kind"] == "probe"] == [False, False]
    assert PROBE not in models_sandbox.MODEL_REGISTRY
    # The proposal unit's own supervised subprocess reached the parent's observer.
    inner = next(row["pid"] for row in rows if row["kind"] == "inner")
    assert inner in {lifecycle.child_pid for lifecycle in observed}
    verify_graph_trace(
        request, initial(request).model_copy(update={"run_id": receipt.run_id}), receipt
    )


@pytest.mark.parametrize("fail", ["raise", "crash"])
def test_failed_or_crashed_unit_keeps_the_serial_failure_stop(
    prepared, native_runner, monkeypatch, tmp_path, fail
):
    """Fails if a unit exception or a dead unit process is not the in-process native
    failure: the same failed node, blocked remainder and trace bytes."""
    request = fanout_request(prepared)
    receipt, rows, _ = run_real_units(request, monkeypatch, tmp_path, fail)
    assert receipt.status == "failed"
    assert trace_sha256(receipt) == UNROUTED_TRACE_SHA256["failed"]
    # No sibling dispatch after the failure: proposal and the first implementation only.
    assert len([row for row in rows if row["kind"] == "unit"]) == 2
    verify_graph_trace(
        request, initial(request).model_copy(update={"run_id": receipt.run_id}), receipt
    )


class Carrier(BaseModel):
    explicit: int = 0
    implicit: int = 0


class Holder(BaseModel):
    items: tuple[Carrier, ...]


class Opaque(BaseModel):
    payload: Any


def test_unit_transport_preserves_set_fields_and_refuses_drift():
    """Fails if transport widens a nested `model_fields_set` (read by LLM-config
    defaults, protocol mappings and reconciliation) or forwards a value the child
    would reconstruct differently (here a model typed `Any` decodes as a dict)."""
    from tools.candidate_worker.unit_transport import decode_transport, encode_transport

    decoded = decode_transport(Holder, encode_transport(Holder(items=(Carrier(explicit=0),))))
    assert decoded.items[0].model_fields_set == {"explicit"}
    with pytest.raises(ValueError, match="round-trip"):
        encode_transport(Opaque(payload=Carrier()))
