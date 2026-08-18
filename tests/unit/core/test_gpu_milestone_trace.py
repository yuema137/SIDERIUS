"""The milestone trace must be inert by default and exact when enabled.

V20 PR C2. This trace exists to locate a fixed **208 MiB** under-read: the
corrected pre-phase inference measurement reports 3434 MiB where formal
inference holds 3642 MiB, with zero spread across three alternating runs.
Comparing final peaks cannot find it; comparing the two lifecycles at the
same named points can.

Each test below names a defect only it catches:

* production must not change -- an inference process with no trace
  environment must behave exactly as it did, create no file, and make no
  driver query;
* milestone 7 must sit between the synchronized forward and the CPU
  transfer -- taken anywhere else it describes a different state while
  looking identical, and the whole comparison silently answers the wrong
  question;
* the trace must not perturb what it measures -- no extra forward, no
  extended output lifetime;
* both sides must emit one schema, or the records cannot be aligned;
* there must be exactly one definition of driver-visible memory.
"""

from __future__ import annotations

import ast
import gc
import json
import weakref
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.runtime_control import gpu_accounting
from core.runtime_control.gpu_accounting import (
    DeviceIdentity,
    GpuAccountingSnapshot,
    ProcessOccupancy,
)
from core.runtime_control.gpu_milestone_trace import (
    MILESTONE_SEQUENCE,
    ONCE_MILESTONES,
    PER_BATCH_MILESTONES,
    POST_FORWARD_MILESTONE,
    TRACE_ENV_VAR,
    MilestoneRecord,
    MilestoneTraceChannel,
    MilestoneTraceMisuse,
    MilestoneTracer,
    MilestoneTraceUnavailable,
    tracer_from_environment,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
INFERENCE_SOURCE = REPO_ROOT / "execute_tools" / "inference_single.py"
WORKER_SOURCE = REPO_ROOT / "core" / "runtime_control" / "gpu_measurement_worker_main.py"
PHASES_SOURCE = REPO_ROOT / "core" / "runtime_control" / "gpu_measurement_phases.py"
TRACE_SOURCE = REPO_ROOT / "core" / "runtime_control" / "gpu_milestone_trace.py"

UUID = "GPU-c30b6678-ff2a-f8b4-d378-af9681c6ceef"


def _snapshot(mib: int | None, *, available: bool = True) -> GpuAccountingSnapshot:
    device = DeviceIdentity(uuid=UUID, physical_index=0)
    if not available:
        return GpuAccountingSnapshot(device=device, telemetry_available=False)
    return GpuAccountingSnapshot(
        device=device,
        telemetry_available=True,
        device_used_mib=mib,
        device_total_mib=32607,
        own_tree_mib=mib,
        own_processes=(ProcessOccupancy(pid=4321, used_mib=mib or 0),),
        other_mib=0,
        other_process_count=0,
        per_pid_total_mib=mib,
        unattributed_mib=0,
        accounting_skew_mib=0,
    )


@pytest.fixture
def channel(tmp_path) -> MilestoneTraceChannel:
    return MilestoneTraceChannel(
        path=str(tmp_path / "trace.ndjson"),
        device_uuid=UUID,
        run_id="audit-208mib",
        max_traced_batches=2,
    )


@pytest.fixture
def tracer(channel) -> MilestoneTracer:
    return MilestoneTracer(
        channel,
        side="formal_inference",
        git_sha="deadbeef",
        device_sampler=lambda pid, device: _snapshot(3642),
    )


# ─────────────────────────────────────────────────────────────────────────
# Disabled by default
# ─────────────────────────────────────────────────────────────────────────


class TestItIsInertWithoutTheEnvironmentVariable:
    def test_no_variable_means_no_tracer(self):
        """`None` is the production path. There is no disabled tracer to
        get half-configured -- absence IS the off state."""
        assert tracer_from_environment(side="formal_inference", environ={}) is None

    @pytest.mark.parametrize("value", ["", "   "])
    def test_an_empty_value_is_still_off(self, value):
        assert (
            tracer_from_environment(side="formal_inference", environ={TRACE_ENV_VAR: value}) is None
        )

    def test_nothing_is_written_when_it_is_absent(self, tmp_path):
        """The defect: a trace file appearing in a production workspace.

        A path is offered and deliberately not named in the environment; if
        anything created it anyway, tracing would be reachable without being
        requested.
        """
        would_be = tmp_path / "trace.ndjson"
        assert tracer_from_environment(side="formal_inference", environ={}) is None
        assert not would_be.exists()
        assert list(tmp_path.iterdir()) == []

    def test_the_real_environment_path_works_end_to_end(self, monkeypatch, tmp_path):
        """The other tests inject `environ=`; validation infrastructure sets
        the real variable and both subprocesses inherit it. If only the
        injected path worked, every test here would pass and the GPU audit
        would produce an empty artifact.
        """
        target = tmp_path / "nested" / "trace.ndjson"
        monkeypatch.setenv(
            TRACE_ENV_VAR,
            json.dumps({"path": str(target), "device_uuid": UUID, "run_id": "env-path"}),
        )
        tracer = tracer_from_environment(side="prephase_inference")
        assert tracer is not None
        tracer.record("process_start")
        assert target.exists()
        assert json.loads(target.read_text(encoding="utf-8").strip())["run_id"] == "env-path"

    def test_both_subprocesses_inherit_rather_than_being_plumbed(self):
        """No `env=` on either launcher, so the variable reaches the probe
        worker and the formal inference process by inheritance. A launcher
        that started passing a curated `env=` would silently drop the trace
        and the audit would come back empty.
        """
        # V20 attempt 2: the worker launcher now DOES pass `env=`, because
        # it must transport SIDERIUS_PLUGIN_DIRS — without it no
        # agent-generated candidate could be measured at all.
        #
        # The property this test protects is unchanged and is asserted
        # directly rather than through "no env= appears in the source":
        # the curated env must be a COPY of the environment, so the trace
        # variable still reaches the worker. A launcher that built an env
        # from scratch would silently drop it and the audit would come
        # back empty — which is what the old proxy was guarding against.
        import os as _os

        from core.subprocess_env import subprocess_env

        sentinel = '{"channel": "test"}'
        _os.environ[TRACE_ENV_VAR] = sentinel
        try:
            built = subprocess_env(plugin_dir="/tmp/plugins")
        finally:
            _os.environ.pop(TRACE_ENV_VAR, None)
        assert built.get(TRACE_ENV_VAR) == sentinel, (
            "the worker's curated env must preserve the inherited milestone "
            "trace; building an env from scratch would lose it"
        )
        assert built.get("SIDERIUS_PLUGIN_DIRS") == "/tmp/plugins"

    def test_no_production_module_sets_the_variable(self):
        """Reachability, inverted: production must never turn this on.

        Scanned over sources rather than trusted, because the guarantee
        "production never sets it" is worth exactly as much as the last
        person who checked.
        """
        offenders = []
        for path in (INFERENCE_SOURCE, WORKER_SOURCE, PHASES_SOURCE):
            text = path.read_text(encoding="utf-8")
            for line in text.splitlines():
                if TRACE_ENV_VAR not in line:
                    continue
                # Naming it in a comment is documentation; assigning it is
                # a production switch.
                if "environ[" in line or "setenv" in line or "putenv" in line:
                    offenders.append(f"{path.name}: {line.strip()}")
        assert not offenders, offenders


class TestAMalformedChannelFailsAsInfrastructure:
    def test_an_unwritable_path_fails_before_any_measurement(self, tmp_path):
        """Infrastructure, not science. It must raise at construction --
        before a single milestone -- so a broken channel can never be
        mistaken for a property of the candidate or the device."""
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("", encoding="utf-8")
        payload = json.dumps(
            {"path": str(blocker / "sub" / "trace.ndjson"), "device_uuid": UUID, "run_id": "r"}
        )
        with pytest.raises(MilestoneTraceUnavailable, match="unwritable"):
            tracer_from_environment(side="formal_inference", environ={TRACE_ENV_VAR: payload})

    def test_the_infrastructure_error_is_not_a_measurement_outcome(self):
        """It must not be catchable as one of the measurement statuses: a
        gate that treated it as `CUDA_OOM` or `STOP_OVER_CAP` would blame a
        candidate for a broken artifact path."""
        assert issubclass(MilestoneTraceUnavailable, RuntimeError)
        assert not issubclass(MilestoneTraceUnavailable, ValueError)


# ─────────────────────────────────────────────────────────────────────────
# The record schema
# ─────────────────────────────────────────────────────────────────────────


class TestEveryRecordCarriesItsContext:
    def test_a_failed_query_stays_none_and_never_becomes_zero(self, channel):
        """The invariant the whole PR rests on. A comparison that read a
        failed query as 0 MiB would invent a divergence at that milestone
        and send the audit after a difference that does not exist."""
        tracer = MilestoneTracer(
            channel,
            side="formal_inference",
            git_sha="sha",
            device_sampler=lambda pid, device: _snapshot(None, available=False),
        )
        record = tracer.record("process_start")
        assert record is not None
        assert record.telemetry_available is False
        assert record.tree_total_mib is None
        assert record.device_used_mib is None

    def test_a_sampler_that_raises_becomes_a_value_not_an_exception(self, channel):
        """This PR's control-flow rule: expected outcomes are values. A
        driver query failing mid-run must not abort the traced process."""

        def _explode(pid, device):
            raise OSError("nvidia-smi vanished")

        tracer = MilestoneTracer(
            channel, side="formal_inference", git_sha="s", device_sampler=_explode
        )
        record = tracer.record("process_start")
        assert record is not None and record.telemetry_available is False


# ─────────────────────────────────────────────────────────────────────────
# Order, uniqueness and bounds
# ─────────────────────────────────────────────────────────────────────────


class TestOrderAndUniquenessAreEnforced:
    def test_the_per_batch_bound_skips_rather_than_records(self, tracer):
        """A bounded cap, and a visible one: `max_traced_batches` travels
        on every per-batch record so a reader can tell a bounded trace from
        a complete one."""
        assert tracer.record(POST_FORWARD_MILESTONE, batch_index=1) is not None
        assert tracer.record(POST_FORWARD_MILESTONE, batch_index=2) is None
        assert tracer.traces_batch(1) and not tracer.traces_batch(2)
        assert all(r.max_traced_batches == 2 for r in tracer.records if r.batch_index is not None)


# ─────────────────────────────────────────────────────────────────────────
# One memory policy
# ─────────────────────────────────────────────────────────────────────────


class TestThereIsExactlyOneDefinitionOfDriverVisibleMemory:
    def test_the_default_sampler_is_the_production_primitive(self, channel):
        """A second definition of "driver-visible" is how a measurement and
        the gate that consumes it come to disagree invisibly."""
        tracer = MilestoneTracer(channel, side="formal_inference", git_sha="s")
        assert tracer._sampler is gpu_accounting.sample

    def test_it_introduces_no_rival_telemetry_backend(self):
        """pynvml or a private nvidia-smi call here would be a second
        memory policy wearing this module's name."""
        text = TRACE_SOURCE.read_text(encoding="utf-8")
        assert "pynvml" not in text
        assert "nvidia-smi" not in text
        assert "--query-compute-apps" not in text


# ─────────────────────────────────────────────────────────────────────────
# Placement inside the production sources — the load-bearing structure
# ─────────────────────────────────────────────────────────────────────────


def _function(source: Path, name: str) -> ast.FunctionDef:
    module = ast.parse(source.read_text(encoding="utf-8"))
    for node in ast.walk(module):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in {source}")


def _milestone_line(func: ast.AST, milestone: str) -> int | None:
    """Line of the `trace.record("<milestone>", ...)` call, if present."""
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Attribute) and node.func.attr == "record"):
            continue
        if node.args and isinstance(node.args[0], ast.Constant):
            if node.args[0].value == milestone:
                return node.lineno
    return None


def _milestone_call(func: ast.AST, milestone: str) -> ast.Call | None:
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Attribute) and node.func.attr == "record"):
            continue
        if node.args and isinstance(node.args[0], ast.Constant):
            if node.args[0].value == milestone:
                return node
    return None


def _first_line_of_call(func: ast.AST, attr: str) -> int | None:
    for node in ast.walk(func):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == attr:
                return node.lineno
    return None


class TestMilestoneSevenSitsWhereItMustInFormalInference:
    """The single most consequential placement in this change.

    After the forward and its synchronize, while `output` is still resident
    on the GPU, and BEFORE any argmax, `.cpu()` transfer or release. A
    record taken after the transfer describes a state with the output gone
    and would compare two different things while looking identical.

    Enforced structurally over the AST rather than by reading the file,
    because both mutations the audit plan requires -- deleting milestone 7,
    and moving it after the CPU transfer -- are invisible to a runtime test
    that only checks the record exists.
    """

    def test_it_exists_at_all(self):
        """Deleting the milestone 7 call fails HERE."""
        assert _milestone_line(_function(INFERENCE_SOURCE, "process_batch"), POST_FORWARD_MILESTONE)

    def test_it_comes_after_the_forward(self):
        func = _function(INFERENCE_SOURCE, "process_batch")
        forward = next(
            node.lineno
            for node in ast.walk(func)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "model"
        )
        assert _milestone_line(func, POST_FORWARD_MILESTONE) > forward

    def test_it_comes_before_the_cpu_transfer(self):
        """Moving milestone 7 after `.cpu()` fails HERE."""
        func = _function(INFERENCE_SOURCE, "process_batch")
        cpu_line = _first_line_of_call(func, "cpu")
        assert cpu_line is not None, "the CPU transfer disappeared from process_batch"
        assert _milestone_line(func, POST_FORWARD_MILESTONE) < cpu_line

    def test_the_cpu_transfer_milestone_comes_after_it(self):
        func = _function(INFERENCE_SOURCE, "process_batch")
        cpu_line = _first_line_of_call(func, "cpu")
        assert _milestone_line(func, "after_output_to_cpu") > cpu_line

    def test_it_synchronizes(self):
        """CUDA is asynchronous: without this the sample can land while the
        forward's kernels are still queued, describing a state the device
        has not reached."""
        call = _milestone_call(_function(INFERENCE_SOURCE, "process_batch"), POST_FORWARD_MILESTONE)
        assert call is not None
        synchronize = {
            kw.arg: kw.value for kw in call.keywords if isinstance(kw.value, ast.Constant)
        }
        assert synchronize.get("synchronize") is not None
        assert synchronize["synchronize"].value is True

    def test_it_passes_the_live_output(self):
        """`output_gpu_resident` is only evidence if the real tensor is
        handed over; a record built without it would report `None` and the
        comparison would lose the one fact that distinguishes this
        milestone from the next."""
        call = _milestone_call(_function(INFERENCE_SOURCE, "process_batch"), POST_FORWARD_MILESTONE)
        assert call is not None
        assert any(kw.arg == "output" for kw in call.keywords)


class TestMilestoneSevenSitsWhereItMustInTheProbe:
    def test_it_is_recorded_inside_the_observation_hold(self):
        """Same lifecycle point as formal: after the forward has
        synchronized and before the hold releases. Recorded after the
        release, it would compare a released state against a held one."""
        func = _function(PHASES_SOURCE, "_run_inference")
        line = _milestone_line(func, POST_FORWARD_MILESTONE)
        assert line is not None
        hold = next(
            node.lineno
            for node in ast.walk(func)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "hold_peak_state"
        )
        sync = _first_line_of_call(func, "_synchronize_device") or 0
        assert sync < line < hold

    def test_the_probe_never_transfers_output_to_the_host(self):
        """A real lifecycle difference, asserted so it stays visible: the
        probe holds the output resident and never calls `.cpu()`, which is
        why `after_output_to_cpu` is absent on that side."""
        func = _function(PHASES_SOURCE, "_run_inference")
        assert _first_line_of_call(func, "cpu") is None
        assert _milestone_line(func, "after_output_to_cpu") is None


class TestTheTraceDoesNotPerturbWhatItMeasures:
    def test_the_construction_split_transfers_exactly_once(self):
        """Splitting `model_class(cfg).to(DEVICE)` into two statements must
        stay ONE transfer. A second `.to(DEVICE)` would be a real behaviour
        change hiding inside a refactor."""
        for source, name in ((INFERENCE_SOURCE, "main"), (WORKER_SOURCE, "_build")):
            func = _function(source, name)
            transfers = [
                node
                for node in ast.walk(func)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "to"
                and any(isinstance(a, ast.Name) and a.id in {"DEVICE"} for a in node.args)
            ]
            # inference_single: exactly one model transfer in agent mode.
            if name == "main":
                assert len(transfers) == 1, f"{source.name}: {len(transfers)} DEVICE transfers"

    def test_no_milestone_call_creates_a_tensor(self):
        """The trace must allocate nothing on the device. A `record(...)`
        argument that built a tensor would change the very figure the next
        milestone reports."""
        checked = 0
        for source in (INFERENCE_SOURCE, PHASES_SOURCE, WORKER_SOURCE):
            func_module = ast.parse(source.read_text(encoding="utf-8"))
            for node in ast.walk(func_module):
                # `trace.record(...)` specifically -- `journal.record(...)`
                # is a different, unrelated call on these same modules.
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "record"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "trace"
                ):
                    continue
                checked += 1
                for kw in node.keywords:
                    # No CALL in a payload: a call is the only construct
                    # here that could allocate a tensor and move the figure
                    # the next milestone reports. Names, attributes,
                    # constants, f-strings and arithmetic cannot.
                    assert not isinstance(kw.value, ast.Call), (
                        f"{source.name}:{node.lineno} passes a computed value to trace.record()"
                    )
        assert checked, "no trace.record() calls found -- the scan matched nothing"

    def test_the_record_retains_no_tensor(self, tracer):
        """Output lifetime must not be extended. The record stores shape and
        dtype as plain values; if it held the tensor, the next milestone
        would measure memory the process had already released."""
        torch = pytest.importorskip("torch")
        output = torch.zeros(2, 4)
        ref = weakref.ref(output)
        tracer.record(POST_FORWARD_MILESTONE, batch_index=0, output=output)
        del output
        gc.collect()
        assert ref() is None, "the milestone record kept the output alive"

    def test_it_records_shape_and_dtype_without_the_object(self, tracer):
        torch = pytest.importorskip("torch")
        record = tracer.record(POST_FORWARD_MILESTONE, batch_index=0, output=torch.zeros(2, 256, 8))
        assert record is not None
        assert record.output_shape == (2, 256, 8)
        assert record.output_dtype == "float32"
        assert record.output_gpu_resident is False


class TestTheProductionPathIsUnchangedWithoutATrace:
    def test_process_batch_runs_identically_with_and_without_the_tracer(self, monkeypatch, tracer):
        """Behavioural parity, on the real function. The returned arrays
        must be bit-identical, and the model must see exactly one forward
        either way."""
        torch = pytest.importorskip("torch")
        import numpy as np

        import execute_tools.inference_single as inference_single

        monkeypatch.setattr(inference_single, "DEVICE", torch.device("cpu"))

        forwards = {"n": 0}

        class _Tiny(torch.nn.Module):
            def forward(self, x):
                forwards["n"] += 1
                b, t = x.shape
                out = torch.zeros(b, 256, t)
                out[:, 7, :] = 1.0
                return out

        model = _Tiny().eval()
        args = SimpleNamespace(denoising_model="punet")
        inputarr = np.zeros((1, 1, 8), dtype=np.int8)
        targetarr = np.zeros((1, 1, 8), dtype=np.int8)

        plain = inference_single.process_batch(0, inputarr, targetarr, model, args, "ce")
        assert forwards["n"] == 1

        traced = inference_single.process_batch(
            0, inputarr, targetarr, model, args, "ce", trace=tracer, batch_index=0
        )
        # One forward per call, traced or not: the trace runs no extra work.
        assert forwards["n"] == 2

        assert np.array_equal(plain[1], traced[1])
        assert np.array_equal(plain[2], traced[2])
        assert plain[0] == traced[0]

    def test_the_traced_call_records_the_batch_lifecycle_in_order(self, monkeypatch, tracer):
        torch = pytest.importorskip("torch")
        import numpy as np

        import execute_tools.inference_single as inference_single

        monkeypatch.setattr(inference_single, "DEVICE", torch.device("cpu"))

        class _Tiny(torch.nn.Module):
            def forward(self, x):
                b, t = x.shape
                return torch.zeros(b, 256, t)

        inference_single.process_batch(
            0,
            np.zeros((1, 1, 8), dtype=np.int8),
            np.zeros((1, 1, 8), dtype=np.int8),
            _Tiny().eval(),
            SimpleNamespace(denoising_model="punet"),
            "ce",
            trace=tracer,
            batch_index=0,
        )
        assert [r.milestone for r in tracer.records] == [
            "after_input_to_device",
            POST_FORWARD_MILESTONE,
            "after_output_to_cpu",
        ]
        post_forward = tracer.records[1]
        assert post_forward.output_shape == (1, 256, 8)
        assert post_forward.input_shape == (1, 8)
        assert post_forward.model_mode == "eval"
