"""Graph units in real child processes reproduce the in-process dispatch (B3-3).

Every other graph test runs units through the in-process seam installed by
`native_runner`. Here the real `spawn_unit` supervises real unit children; a
generated harness replaces only provider construction (and, per case, one
native phase) inside each child before running the actual `unit_child` entry.
The harness puts this checkout's `src` first on the child's `sys.path` (the
child environment drops `PYTHONPATH`), so a copied checkout's children import
that copy, and every child reports which `unit_child` it imported.
"""

import inspect
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from tests.helpers.candidate_fanout import (
    UNROUTED_TRACE_SHA256,
    fanout_request,
    selection_request,
    trace_projection,
)
from tools.candidate_worker import launch_candidate
from tools.candidate_worker.graph_evidence import verify_graph_trace
from tools.candidate_worker.unit_runner import spawn_unit as real_spawn_unit

from .conftest import QUICKSTART, REPO, _prepare_request
from .test_graph import initial
from .test_native import Provider, native_runner
from .test_training import training_runner

PROBE = "b33_registry_probe"
HARNESS = """import json, os, runpy, subprocess, sys
sys.path.insert(0, {src!r})
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
validator_module = importlib.import_module("nodes.ml_code_validator_agent.ml_code_validator_agent")
real_pytest = validator_module.run_generated_pytest
def bounded_pytest(test_file_path, env, *, limit=None):
    log(kind="pytest", limit=None if limit is None else limit.model_dump())
    return real_pytest(test_file_path, env, limit=limit)
validator_module.run_generated_pytest = bounded_pytest
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
if CONFIG["tuner"]:
    # The offline tuner of test_training.training_runner, and the lineage it got.
    sys.path.insert(1, {repo!r})
    from tests.unit.workflows.test_model_exploration import _make_tuning_output
    from tools.candidate_worker import training
    class Tuner:
        def set_run_context(self, **kwargs):
            pass
        def run(self, value):
            output = _make_tuning_output(
                model_type=value.model_type, run_name=value.storage.local.run_name
            )
            return output.model_copy(update=dict(
                candidate_id=value.candidate_id,
                task_composition_fingerprint=value.task_composition_ref.semantic_fingerprint,
            ))
    training.HyperparamTuningAgent = Tuner
    real_training = training.run_training
    def observed_training(context, proposal, implementation, validation, *args, **kwargs):
        log(kind="trained", model_file_path=implementation.model_file_path)
        return real_training(context, proposal, implementation, validation, *args, **kwargs)
    training.run_training = observed_training
sys.argv = ["tools.candidate_worker.unit_child", sys.argv[1]]
runpy.run_module("tools.candidate_worker.unit_child", run_name="__main__")
"""


def trace_sha256(receipt):
    import hashlib

    return hashlib.sha256(trace_projection(receipt).encode()).hexdigest()


def separate_request(tmp_path, name):
    """A second synthetic project and workspace for the in-process reference run."""
    from agent.schemas.proposal import ProposalInput
    from agent.schemas.proposer_evidence import ProposerInterpretationEvidence
    from workflows.task_composition import build_task_composition_ref, compose_run_task_bindings

    root = tmp_path / name
    (root / "project" / "data").mkdir(parents=True)
    return _prepare_request(
        QUICKSTART,
        root / "project",
        root / "workspace",
        compose_run_task_bindings,
        build_task_composition_ref,
        ProposalInput,
        ProposerInterpretationEvidence,
    )


def stable(value, normalized):
    """Drop per-run noise (identities, timings, absolute paths) from a native record."""
    volatile = {"candidate_id", "test_output", "created_at", "timestamp"}
    if isinstance(value, dict):
        return {
            key: stable(item, normalized)
            for key, item in value.items()
            if key not in volatile and not key.endswith(("_path", "_dir", "_seconds"))
        }
    if isinstance(value, list):
        return [stable(item, normalized) for item in value]
    return normalized(value) if isinstance(value, str) else value


def run_real_units(request, monkeypatch, tmp_path, fail, *, tuner=False):
    """Launch through the worker with every graph unit in a real child process."""
    from tools.candidate_worker import unit_runner

    log = tmp_path / f"units_{fail}.jsonl"
    config = tmp_path / f"harness_{fail}.json"
    config.write_text(json.dumps({"fail": fail, "log": str(log), "tuner": tuner}))
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

    reference = fanout_request(separate_request(tmp_path, "in_process"))
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


def test_validation_unit_bounds_pytest_by_the_remaining_worker_budget(
    prepared, native_runner, monkeypatch, tmp_path
):
    """Fails if the worker budget does not cross into a real validation unit process
    (issue #984): the unit's real validator must launch generated pytest with a
    `worker_budget` limit no larger than the request's timeout, never unbounded."""
    request = fanout_request(prepared)
    receipt, rows, _ = run_real_units(request, monkeypatch, tmp_path, "none")
    assert receipt.status == "accepted", receipt.error
    limits = [row["limit"] for row in rows if row["kind"] == "pytest"]
    assert len(limits) == 2  # one per validation branch, each in its own unit
    assert all(
        limit is not None
        and limit["source"] == "worker_budget"
        and 0 < limit["seconds"] <= request.timeout_seconds
        for limit in limits
    ), limits


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


def test_unit_transport_keeps_nonfinite_floats_and_validator_filled_fields_set():
    """Fails if a -inf scoring sentinel or a -inf launch knob cannot cross the
    boundary (the node would fail), or if a nested validator-filled field (the
    metric's scoreability contract) changes its `model_fields_set`."""
    from tests.unit.workflows.test_model_exploration import _make_tuning_output
    from tools.candidate_worker.unit_transport import decode_transport, encode_transport
    from workflows.candidate_training_settings import CandidateTrainingSettings

    output = _make_tuning_output(score=float("-inf"))
    decoded = decode_transport(type(output), encode_transport(output))
    assert decoded.best_denoising_score == float("-inf")
    assert output.metric_spec is not None and decoded.metric_spec is not None
    nested = output.metric_spec.scoreability
    assert decoded.metric_spec.scoreability.model_fields_set == nested.model_fields_set
    assert decoded.metric_spec.scoreability == nested
    settings = CandidateTrainingSettings.model_validate_json(
        '{"launch": {"skip_formal_min_delta": -Infinity}}'
    )
    restored = decode_transport(type(settings), encode_transport(settings))
    assert restored.launch.skip_formal_min_delta == float("-inf")
    # NaN is not equal to itself; the round-trip check must still accept it.
    nan = decode_transport(
        type(output),
        encode_transport(output.model_copy(update={"best_denoising_score": float("nan")})),
    )
    assert math.isnan(nan.best_denoising_score)


def test_unit_child_never_imports_workspace_shadows(tmp_path, monkeypatch, capfd):
    """Fails if a unit started with `-m` from the writable workspace imports a
    planted `tools` package or `json` module instead of the framework/stdlib."""
    from core.generated_library import bind_generated_library_to_workspace

    workspace = tmp_path / "workspace"
    marker = tmp_path / "shadow_imported"
    (workspace / "tools/candidate_worker").mkdir(parents=True)
    shadow = f"open({str(marker)!r}, 'a').write(__name__ + '\\n')\n"
    for name in (
        "json.py",
        "tools/__init__.py",
        "tools/candidate_worker/__init__.py",
        "tools/candidate_worker/unit_child.py",
    ):
        (workspace / name).write_text(shadow)
    environment: dict[str, str] = {}
    bind_generated_library_to_workspace(str(workspace), environ=environment)
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(workspace)
    with pytest.raises(subprocess.CalledProcessError):
        # The real entry runs and refuses the absent invocation.
        real_spawn_unit(str(workspace / "candidate_run/units/node/invocation.json"))
    assert not marker.exists(), marker.read_text()
    assert "FileNotFoundError" in capfd.readouterr().out


def test_adaptor_selected_branch_trains_in_a_real_tuning_unit(
    prepared, training_runner, monkeypatch, tmp_path
):
    """Fails if the worker-side adaptor selection does not reach the tuning unit
    process: with reversed bindings check1 is first admissible, so the real tuning
    unit must receive build1 (the in-process default would train build0). The
    verifier also rechecks verdicts and the staged bytes the unit wrote."""
    request = selection_request(prepared, bindings=["check1", "check0"])
    receipt, rows, _ = run_real_units(request, monkeypatch, tmp_path, "none", tuner=True)
    assert receipt.status == "completed", receipt.error
    (trained,) = [row for row in rows if row["kind"] == "trained"]
    assert "/build1/" in trained["model_file_path"]
    assert len([row for row in rows if row["kind"] == "unit"]) == len(receipt.graph_trace.nodes)
    verify_graph_trace(
        request, initial(request).model_copy(update={"run_id": receipt.run_id}), receipt
    )
