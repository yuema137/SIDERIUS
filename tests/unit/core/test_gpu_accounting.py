"""B-C1 — driver-visible GPU accounting.

Every test is synthetic: nvidia-smi and /proc are injected, so nothing
here needs a GPU, a driver, or TIDMAD data. That is not only convenience
— it is the property under test. A generic runtime module that could
only be tested on this one workstation would already have failed the
genericization requirement it exists under.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.runtime_control.gpu_accounting import (
    DeviceBaselineSnapshot,
    DeviceIdentity,
    GpuAccountingSnapshot,
    is_descendant_of,
    sample,
    sample_device_baseline,
)

UUID_A = "GPU-aaaaaaaa-0000-0000-0000-000000000000"
UUID_B = "GPU-bbbbbbbb-1111-1111-1111-111111111111"

DEV_A = DeviceIdentity(uuid=UUID_A, physical_index=0)
DEV_B = DeviceIdentity(uuid=UUID_B, physical_index=1, logical_index=0)


class _Completed:
    def __init__(self, stdout: str) -> None:
        self.stdout = stdout


def make_runner(gpu_rows: str, app_rows: str, *, fail: str | None = None):
    """Fake nvidia-smi. ``fail`` names a query kind that should blow up."""

    def _run(cmd, **_kw):
        query = next(a for a in cmd if a.startswith("--query-"))
        kind = "gpu" if query.startswith("--query-gpu") else "compute-apps"
        if fail == kind:
            raise OSError("synthetic telemetry failure")
        return _Completed(gpu_rows if kind == "gpu" else app_rows)

    return _run


def make_proc(tree: dict[int, int]):
    """``/proc/<pid>/status`` from a {pid: ppid} map. Missing = exited."""

    def _read(pid: int) -> str | None:
        if pid not in tree:
            return None
        return f"Name:\tfake\nPPid:\t{tree[pid]}\n"

    return _read


GPU_ONE = f"0, {UUID_A}, 4096, 32607\n"
GPU_TWO = f"0, {UUID_A}, 4096, 32607\n1, {UUID_B}, 9000, 32607\n"


class TestOwnership:
    """Ancestry, because a session test would miss the pre-flight worker."""

    def test_direct_child_is_owned(self):
        assert is_descendant_of(200, 100, proc_reader=make_proc({200: 100, 100: 1}))

    def test_grandchild_is_owned(self):
        tree = {300: 200, 200: 100, 100: 1}
        assert is_descendant_of(300, 100, proc_reader=make_proc(tree))

    def test_a_child_in_its_own_session_is_still_owned(self):
        """The pre-flight worker runs with start_new_session=True, so it
        leads its own session while remaining our child. Keying on the
        process group would drop exactly this process — and its memory
        would go missing from the total the guard depends on."""
        assert is_descendant_of(555, 100, proc_reader=make_proc({555: 100, 100: 1}))

    def test_unrelated_process_is_not_owned(self):
        tree = {900: 800, 800: 1, 100: 1}
        assert not is_descendant_of(900, 100, proc_reader=make_proc(tree))

    def test_init_is_not_owned(self):
        assert not is_descendant_of(1, 100, proc_reader=make_proc({100: 1}))

    def test_a_process_that_exited_mid_walk_is_simply_not_claimed(self):
        assert not is_descendant_of(300, 100, proc_reader=make_proc({}))

    def test_a_cycle_terminates(self):
        """A malformed tree must not spin the sampler on the hot path."""
        assert not is_descendant_of(10, 999, proc_reader=make_proc({10: 11, 11: 10}))

    @pytest.mark.parametrize("pid,root", [(0, 100), (-1, 100), (100, 0), (100, -5)])
    def test_invalid_pids_are_rejected_not_raised(self, pid, root):
        assert is_descendant_of(pid, root, proc_reader=make_proc({})) is False


class TestDeviceScoping:
    def test_only_the_requested_device_is_counted(self):
        """Occupancy on a second GPU is not headroom on this one."""
        apps = f"200, 1000, {UUID_A}\n900, 8000, {UUID_B}\n"
        snap = sample(
            100,
            DEV_A,
            runner=make_runner(GPU_TWO, apps),
            proc_reader=make_proc({200: 100, 900: 1, 100: 1}),
        )
        assert snap.own_tree_mib == 1000
        assert snap.other_mib == 0
        assert snap.per_pid_total_mib == 1000
        assert snap.device_used_mib == 4096

    def test_devices_are_never_summed(self):
        snap = sample(100, DEV_B, runner=make_runner(GPU_TWO, ""), proc_reader=make_proc({}))
        assert snap.device_used_mib == 9000
        assert snap.device_used_mib != 4096 + 9000

    def test_an_absent_uuid_is_unavailable_not_the_first_row(self):
        """The failure this guards is capture_contention_snapshot's
        .splitlines()[0], which silently means 'whichever GPU came
        first'. Answering about the wrong device is worse than not
        answering."""
        missing = DeviceIdentity(uuid="GPU-cccccccc-2222-2222-2222-222222222222", physical_index=7)
        snap = sample(100, missing, runner=make_runner(GPU_TWO, ""), proc_reader=make_proc({}))
        assert snap.telemetry_available is False
        assert snap.device_used_mib is None

    def test_the_snapshot_records_which_device_it_describes(self):
        snap = sample(100, DEV_B, runner=make_runner(GPU_TWO, ""), proc_reader=make_proc({}))
        assert snap.device.uuid == UUID_B
        assert snap.device.physical_index == 1
        assert snap.device.logical_index == 0


class TestAttribution:
    def test_own_and_other_split(self):
        apps = f"200, 3000, {UUID_A}\n300, 500, {UUID_A}\n900, 2000, {UUID_A}\n"
        snap = sample(
            100,
            DEV_A,
            runner=make_runner(GPU_ONE, apps),
            proc_reader=make_proc({200: 100, 300: 200, 900: 1, 100: 1}),
        )
        assert snap.own_tree_mib == 3500
        assert {p.pid for p in snap.own_processes} == {200, 300}
        assert snap.other_mib == 2000
        assert snap.other_process_count == 1

    def test_idle_device_is_zero_and_available(self):
        """Zero held is a measurement. It must not look like a gap."""
        snap = sample(100, DEV_A, runner=make_runner(GPU_ONE, ""), proc_reader=make_proc({}))
        assert snap.telemetry_available is True
        assert snap.own_tree_mib == 0
        assert snap.other_mib == 0

    def test_a_pid_that_exits_between_listing_and_proc_read_is_dropped(self):
        apps = f"200, 1000, {UUID_A}\n"
        snap = sample(100, DEV_A, runner=make_runner(GPU_ONE, apps), proc_reader=make_proc({}))
        assert snap.own_tree_mib == 0
        assert snap.other_mib == 1000
        assert snap.telemetry_available is True

    def test_unreadable_proc_counts_as_other_not_as_ours(self):
        """Conservative direction: overstating the peer never manufactures
        headroom, understating it would."""
        apps = f"200, 4000, {UUID_A}\n"
        snap = sample(100, DEV_A, runner=make_runner(GPU_ONE, apps), proc_reader=lambda _p: None)
        assert snap.other_mib == 4000
        assert snap.own_tree_mib == 0


class TestAccountingSkew:
    def test_unattributed_memory_is_surfaced(self):
        apps = f"200, 1000, {UUID_A}\n"
        snap = sample(
            100, DEV_A, runner=make_runner(GPU_ONE, apps), proc_reader=make_proc({200: 100, 100: 1})
        )
        assert snap.per_pid_total_mib == 1000
        assert snap.accounting_skew_mib == 3096
        assert snap.unattributed_mib == 3096

    def test_negative_skew_stays_visible(self):
        """The driver can transiently report per-PID above the device
        total. Clamping that away hides that the two accounts disagree."""
        gpu = f"0, {UUID_A}, 100, 32607\n"
        apps = f"200, 900, {UUID_A}\n"
        snap = sample(
            100, DEV_A, runner=make_runner(gpu, apps), proc_reader=make_proc({200: 100, 100: 1})
        )
        assert snap.accounting_skew_mib == -800
        assert snap.unattributed_mib == 0


class TestTelemetryGaps:
    @pytest.mark.parametrize("which", ["gpu", "compute-apps"])
    def test_a_failed_query_is_a_gap(self, which):
        snap = sample(
            100, DEV_A, runner=make_runner(GPU_ONE, "", fail=which), proc_reader=make_proc({})
        )
        assert snap.telemetry_available is False
        assert snap.own_tree_mib is None
        assert snap.other_mib is None
        assert snap.device_used_mib is None

    def test_nvidia_smi_absent_is_a_gap(self):
        def _missing(*_a, **_k):
            raise FileNotFoundError("nvidia-smi")

        snap = sample(100, DEV_A, runner=_missing, proc_reader=make_proc({}))
        assert snap.telemetry_available is False

    def test_a_timeout_is_a_gap(self):
        def _slow(*_a, **_k):
            raise TimeoutError("nvidia-smi timed out")

        assert sample(100, DEV_A, runner=_slow, proc_reader=make_proc({})).telemetry_available is (
            False
        )

    def test_the_query_is_bounded(self):
        seen: dict = {}

        def _capture(cmd, **kw):
            seen.update(kw)
            return _Completed(GPU_ONE)

        sample(100, DEV_A, runner=_capture, proc_reader=make_proc({}))
        assert seen.get("timeout") is not None and seen["timeout"] > 0

    @pytest.mark.parametrize("bad", ["not,csv\n", "0\n", f"0, {UUID_A}, notanumber, 32607\n", ""])
    def test_malformed_device_output_is_a_gap(self, bad):
        snap = sample(100, DEV_A, runner=make_runner(bad, ""), proc_reader=make_proc({}))
        assert snap.telemetry_available is False

    def test_malformed_app_rows_are_skipped_not_fatal(self):
        apps = f"garbage\n200, 1000, {UUID_A}\nx, y, {UUID_A}\n"
        snap = sample(
            100, DEV_A, runner=make_runner(GPU_ONE, apps), proc_reader=make_proc({200: 100, 100: 1})
        )
        assert snap.telemetry_available is True
        assert snap.own_tree_mib == 1000

    def test_a_gap_cannot_carry_numbers(self):
        with pytest.raises(ValidationError, match="must stay None"):
            GpuAccountingSnapshot(device=DEV_A, telemetry_available=False, own_tree_mib=0)


class TestGenericity:
    """§1.4 — the module must not know what task it is serving."""

    SOURCE = (
        Path(__file__).resolve().parents[3] / "src/core" / "runtime_control" / "gpu_accounting.py"
    )

    def test_imports_no_task_specific_module(self):
        tree = ast.parse(self.SOURCE.read_text(encoding="utf-8"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        forbidden = ("execute_tools", "ml_models", "nodes", "agent", "workflows", "torch")
        offenders = [m for m in imported if any(m.startswith(f) for f in forbidden)]
        assert not offenders, (
            f"generic GPU accounting imports task/ML modules: {offenders}. "
            "This primitive must be usable by a task that is not denoising."
        )

    @staticmethod
    def _code_tokens(source: str) -> list[str]:
        """Identifiers and runtime strings, excluding docstrings.

        A raw text scan is too blunt here: this module's own docstring
        *states* the boundary ("knows nothing about TIDMAD, denoising"),
        and a substring search cannot tell a prohibition from a
        violation. It is the same trap as PR A's `"wrapper"` scan, which
        matched a comment citing the file it forbade. So walk the AST and
        look at what the code does, not at what the prose says about it.
        """
        tree = ast.parse(source)
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef))
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        }
        tokens: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                tokens.append(node.id)
            elif isinstance(node, ast.Attribute):
                tokens.append(node.attr)
            elif isinstance(node, ast.arg):
                tokens.append(node.arg)
            elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                tokens.append(node.name)
            elif isinstance(node, ast.Constant) and id(node) not in docstrings:
                tokens.append(str(node.value))
        return tokens

    def test_code_names_no_task_vocabulary(self):
        """No training/inference/segmentation/TIDMAD identifier or runtime
        string: phases are the caller's business, and this module has no
        phase parameter precisely because it does not need one."""
        tokens = [t.lower() for t in self._code_tokens(self.SOURCE.read_text(encoding="utf-8"))]
        for term in ("tidmad", "denois", "segmentation", "batch_size", "training", "inference"):
            offenders = [t for t in tokens if term in t]
            assert not offenders, f"task vocabulary {term!r} in executable code: {offenders}"

    def test_no_hardware_policy_constant(self):
        """12/28 GiB and the host quota are configured policy, not
        properties of a measuring primitive. Checked against numeric
        literals in code, so a GiB figure quoted in prose does not
        register as an embedded constant."""
        tree = ast.parse(self.SOURCE.read_text(encoding="utf-8"))
        numbers = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float))
        }
        for forbidden in (12, 12.0, 28, 28.0, 29000, 30000):
            assert forbidden not in numbers, (
                f"hardware policy constant {forbidden!r} embedded in a generic "
                "measuring primitive; caps and ceilings are configuration"
            )


class TestDeviceBaseline:
    """B-C2b's `baseline_before_spawn` slot.

    A separate type from GpuAccountingSnapshot on purpose: before Popen
    there is no child PID, so the model must be unable to express
    candidate ownership rather than merely discouraged from it.
    """

    def test_it_cannot_express_candidate_ownership(self):
        """The structural guarantee. Reusing the attributed snapshot with
        own_tree_mib=0 would conflate 'the candidate holds nothing' with
        'the candidate does not exist yet'."""
        fields = set(DeviceBaselineSnapshot.model_fields)
        for forbidden in ("own_tree_mib", "own_processes", "other_mib", "root_pid"):
            assert forbidden not in fields, (
                f"{forbidden!r} on the baseline model would let a pre-spawn "
                "sample claim something about a process that does not exist"
            )

    def test_reports_what_is_already_present(self):
        apps = f"900, 2000, {UUID_A}\n901, 500, {UUID_A}\n950, 7000, {UUID_B}\n"
        snap = sample_device_baseline(DEV_A, runner=make_runner(GPU_TWO, apps), clock=lambda: 123.0)
        assert snap.telemetry_available is True
        assert snap.device_used_mib == 4096
        assert snap.device_total_mib == 32607
        assert snap.device_free_mib == 32607 - 4096
        assert snap.process_count == 2
        assert {p.pid for p in snap.processes} == {900, 901}
        assert snap.sampled_at == 123.0

    def test_other_devices_are_not_counted(self):
        apps = f"950, 7000, {UUID_B}\n"
        snap = sample_device_baseline(DEV_A, runner=make_runner(GPU_TWO, apps))
        assert snap.process_count == 0
        assert snap.device_used_mib == 4096

    def test_an_absent_uuid_is_unavailable_not_the_first_row(self):
        missing = DeviceIdentity(uuid="GPU-dddddddd-3333-3333-3333-333333333333", physical_index=9)
        snap = sample_device_baseline(missing, runner=make_runner(GPU_TWO, ""))
        assert snap.telemetry_available is False
        assert snap.device_free_mib is None

    def test_an_idle_device_is_a_measurement_not_a_gap(self):
        snap = sample_device_baseline(DEV_A, runner=make_runner(GPU_ONE, ""))
        assert snap.telemetry_available is True
        assert snap.process_count == 0
        assert snap.device_free_mib == 32607 - 4096

    @pytest.mark.parametrize("which", ["gpu", "compute-apps"])
    def test_a_failed_query_is_a_gap(self, which):
        snap = sample_device_baseline(DEV_A, runner=make_runner(GPU_ONE, "", fail=which))
        assert snap.telemetry_available is False
        assert snap.device_used_mib is None
        assert snap.processes == ()

    def test_a_gap_cannot_carry_numbers(self):
        with pytest.raises(ValidationError, match="must stay None"):
            DeviceBaselineSnapshot(
                device=DEV_A, telemetry_available=False, sampled_at=1.0, device_used_mib=0
            )

    def test_free_is_clamped_when_the_driver_reports_used_above_total(self):
        gpu = f"0, {UUID_A}, 40000, 32607\n"
        snap = sample_device_baseline(DEV_A, runner=make_runner(gpu, ""))
        assert snap.device_free_mib == 0
