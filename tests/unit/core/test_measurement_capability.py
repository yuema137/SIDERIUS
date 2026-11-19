"""A measurement path that can say why it is off.

V20 PR C1 / C-C3a, design §15.3.

`probe_runner_availability()` refused unless `TIDMAD_DATA_DIR` was a
readable directory, and the tuner consults it before any bounded live probe.
On any other task the entire measured-evidence path disabled itself and the
run continued on static priors -- the V19 posture the V20 launch gate exists
to end.

The failure mode worth naming: that is a task assumption expressed by
OMISSION inside generic infrastructure. There is no wrong constant to grep
for. It fails by returning False, which reads like a legitimate environment
answer.

So the replacement is generic, and it cannot be silent: an unavailable
capability without a reason is refused by a validator, not by convention.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.runtime_control.measurement_capability import (
    ResolvedMeasurementCapability,
    resolve_measurement_capability,
)

IDENTITY = {
    "task_identity": "tidmad_denoise",
    "dataset_adapter": "tidmad_hdf5",
    "data_shape_class": "seg40000_int8",
}


class TestUnavailabilityMustExplainItself:
    def test_a_reasonless_refusal_is_rejected(self):
        """The whole point. `probe_available=False` with no reason is the
        shape the old `(bool, str)` tuple allowed by convention and this
        model forbids by construction."""
        with pytest.raises(ValidationError, match="unavailability_reason"):
            ResolvedMeasurementCapability(**IDENTITY, probe_available=False)

    def test_a_blank_reason_is_rejected(self):
        with pytest.raises(ValidationError):
            ResolvedMeasurementCapability(
                **IDENTITY, probe_available=False, unavailability_reason="   "
            )

    def test_available_and_refused_cannot_both_be_true(self):
        with pytest.raises(ValidationError):
            ResolvedMeasurementCapability(
                **IDENTITY, probe_available=True, unavailability_reason="but also no"
            )

    def test_the_reason_survives_into_the_operator_line(self):
        cap = ResolvedMeasurementCapability(
            **IDENTITY,
            probe_available=False,
            unavailability_reason="no dataset root was supplied by the caller",
        )
        assert "not measurable" in cap.detail
        assert "no dataset root" in cap.detail


class TestIdentityTravelsWithTheVerdict:
    """A capability that says "yes" without saying what it would be
    measuring cannot supply a `MeasurementIdentity` later, and the identity
    is what PR C exists to establish."""

    @pytest.mark.parametrize("field", sorted(IDENTITY))
    def test_identity_is_required_even_when_unavailable(self, field):
        """ "We cannot measure task X" is a more useful fact than "we cannot
        measure"."""
        partial = {k: v for k, v in IDENTITY.items() if k != field}
        with pytest.raises(ValidationError):
            ResolvedMeasurementCapability(
                **partial, probe_available=False, unavailability_reason="r"
            )

    def test_no_identity_field_may_be_blank(self):
        """The concept, across every identity field at once.

        A blank passes `str` and reads as an answer, so each field carries
        `min_length=1`. Asserted here as ONE claim over the whole set rather
        than one case per field: the per-field form restated the same
        declaration `len(IDENTITY)` times and reported only the first field
        that regressed. This reports all of them.
        """
        accepted = []
        for field in sorted(IDENTITY):
            try:
                ResolvedMeasurementCapability(
                    **{**IDENTITY, field: ""},
                    probe_available=False,
                    unavailability_reason="r",
                )
            except ValidationError:
                continue
            accepted.append(field)
        assert not accepted, f"identity fields accepted a blank: {accepted}"


@pytest.fixture
def cuda_present(monkeypatch):
    """Make the DATASET branches reachable on any machine.

    The resolver checks the accelerator FIRST, so on a GPU-less host every
    call returns "no CUDA device is visible" and the dataset policy below is
    never evaluated. Without this, the two tests that follow assert a reason
    the code cannot produce there -- they passed only on a developer box with
    a GPU and failed on CI (found 2026-08-03, CI run 30838392820).

    Skipping instead would be worse: it would leave the dataset policy
    untested in the one environment that gates merges.
    """
    torch = pytest.importorskip("torch")
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    return torch


class TestTheResolverIsGeneric:
    def test_the_accelerator_is_checked_before_the_dataset(self, monkeypatch):
        """Pins the ordering that made the two tests below machine-dependent.

        It is deliberate -- no dataset makes a probe runnable without an
        accelerator -- but it is load-bearing for every caller reading the
        reason string, so it is asserted rather than assumed.
        """
        torch = pytest.importorskip("torch")
        monkeypatch.setattr(torch.cuda, "is_available", lambda: False)

        cap = resolve_measurement_capability(**IDENTITY, dataset_root=None)

        assert cap.probe_available is False
        assert "CUDA" in (cap.unavailability_reason or ""), (
            "with no accelerator the resolver must refuse on the accelerator, not on the dataset"
        )

    def test_a_missing_dataset_root_is_refused_not_defaulted(self, cuda_present):
        """The defect, inverted. The old code reached for `TIDMAD_DATA_DIR`
        when it needed a dataset; this refuses and says so, because a
        default here would be exactly the task assumption being removed."""
        cap = resolve_measurement_capability(
            **IDENTITY, dataset_root=None, supported_phases=("training",)
        )
        assert cap.probe_available is False
        assert "no dataset root" in (cap.unavailability_reason or "")

    def test_a_nonexistent_root_names_the_path(self, cuda_present, tmp_path):
        cap = resolve_measurement_capability(**IDENTITY, dataset_root=str(tmp_path / "absent"))
        assert cap.probe_available is False
        assert "absent" in (cap.unavailability_reason or "")

    def test_the_resolver_never_raises(self, tmp_path):
        """Same contract the `(bool, str)` version had: the CALLER decides
        whether unavailability is fatal. A real formal launch treats it as
        fatal; a CPU or pseudo run expects it."""
        for root in (None, "", str(tmp_path), "/definitely/not/here"):
            cap = resolve_measurement_capability(**IDENTITY, dataset_root=root)
            assert isinstance(cap, ResolvedMeasurementCapability)

    def test_no_task_specific_import_remains_in_the_module(self):
        """The module must not reach for a task's dataset constant.

        Checked through the AST, not the text. This module's own docstring
        NAMES `TIDMAD_DATA_DIR` while explaining the defect it removes, so a
        substring search matches the prose and fails on a module that is
        entirely correct -- which is exactly what happened when this test
        was first written. Imports are the thing to assert on; commentary
        about imports is not.
        """
        import ast
        from pathlib import Path

        import core.runtime_control.measurement_capability as mod

        tree = ast.parse(Path(mod.__file__).read_text())
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported.add(node.module)
                imported.update(f"{node.module}.{a.name}" for a in node.names)

        offenders = sorted(
            name
            for name in imported
            if "data_paths" in name or "dataset_config" in name or "TIDMAD" in name
        )
        assert offenders == [], (
            f"generic measurement capability imports task-owned modules: {offenders}"
        )

    def test_the_task_identity_is_carried_not_assumed(self):
        """Two tasks resolve to two capabilities. If the module had a
        default task, they would not."""
        a = resolve_measurement_capability(**IDENTITY, dataset_root=None)
        b = resolve_measurement_capability(
            task_identity="some_other_task",
            dataset_adapter="other_adapter",
            data_shape_class="other_shape",
            dataset_root=None,
        )
        assert a.task_identity != b.task_identity
        assert a.dataset_adapter != b.dataset_adapter


class TestAMissingCudaDeviceNamesItsCause:
    """Walkthrough N2: a sandbox given /dev/nvidia* without /sys failed with CUDA
    error 304, and the refusal told the operator to pass the device nodes they had
    already passed. The cause is classified from filesystem facts, never driver text."""

    @staticmethod
    def _roots(tmp_path, *, node: bool, pci: bool):
        dev, sys_root = tmp_path / "dev", tmp_path / "sys"
        dev.mkdir()
        (dev / "nvidiactl").symlink_to("/dev/null")  # a control node alone is not a GPU
        if node:
            (dev / "nvidia0").symlink_to("/dev/null")  # a character device
        if pci:
            (sys_root / "bus" / "pci" / "devices").mkdir(parents=True)
        return dev, sys_root

    @pytest.mark.parametrize(
        "node,pci,cause",
        [
            (False, True, "no_device_nodes"),
            (True, False, "sys_not_mounted"),
            (True, True, "cuda_init_failed"),
        ],
    )
    def test_the_observed_prerequisite_decides_the_cause(self, tmp_path, node, pci, cause):
        """Fails if a device-node or /sys fact is misread (for example nvidiactl
        counted as a GPU, or a missing /sys reported as a driver failure)."""
        from core.gpu_requirement import observe_gpu_unavailable_cause

        dev, sys_root = self._roots(tmp_path, node=node, pci=pci)
        assert observe_gpu_unavailable_cause(dev=dev, sys_root=sys_root) == cause

    def test_a_regular_file_named_like_a_gpu_node_is_not_a_device(self, tmp_path):
        """Fails if a plain file /dev/nvidia0 (no device passed) counts as a node."""
        from core.gpu_requirement import observe_gpu_unavailable_cause

        dev, sys_root = self._roots(tmp_path, node=False, pci=True)
        (dev / "nvidia0").write_text("")
        assert observe_gpu_unavailable_cause(dev=dev, sys_root=sys_root) == "no_device_nodes"

    @pytest.mark.parametrize("pci,cause", [(False, "sys_not_mounted"), (True, "cuda_init_failed")])
    def test_a_wsl2_dxg_node_counts_as_a_passed_gpu(self, tmp_path, pci, cause):
        """#1524: under WSL2 the GPU node is /dev/dxg. Fails if a sandbox given
        /dev/dxg is told no device node was passed (the operator would re-list the
        node they already listed instead of fixing /sys or the driver)."""
        from core.gpu_requirement import observe_gpu_unavailable_cause

        dev, sys_root = self._roots(tmp_path, node=False, pci=pci)
        (dev / "dxg").symlink_to("/dev/null")  # a character device
        assert observe_gpu_unavailable_cause(dev=dev, sys_root=sys_root) == cause

    def test_a_cuda_init_failure_is_fixed_for_the_visible_provider(self, tmp_path):
        """#1577: with GPU nodes and /sys visible but CUDA failing, the fix told every
        host to run nvidia-smi or nvidia-modprobe and to look for /dev/nvidia-uvm. A
        WSL2 host has none of these (its nvidia-smi is /usr/lib/wsl/lib/nvidia-smi and
        its driver is the Windows NVIDIA driver). Fails if a WSL2-only /dev gets the
        native NVIDIA remedy, if a native NVIDIA /dev loses it, or if either remedy
        names the other provider."""
        from core.gpu_requirement import gpu_required_message

        (tmp_path / "native").mkdir()
        (tmp_path / "wsl").mkdir()
        native, _ = self._roots(tmp_path / "native", node=True, pci=True)
        wsl, _ = self._roots(tmp_path / "wsl", node=False, pci=True)
        (wsl / "dxg").symlink_to("/dev/null")  # a character device
        native_fix = gpu_required_message("d", "cuda_init_failed", dev=native)
        wsl_fix = gpu_required_message("d", "cuda_init_failed", dev=wsl)
        assert "nvidia-modprobe -u -c=0" in native_fix and "/usr/lib/wsl" not in native_fix
        assert "/usr/lib/wsl/lib/nvidia-smi" in wsl_fix and "Windows" in wsl_fix
        assert "nvidia-modprobe" not in wsl_fix and "/dev/nvidia-uvm is missing" not in wsl_fix
        for fix in (native_fix, wsl_fix):
            assert "CUDA failed to initialize" in fix and "CUDA_VISIBLE_DEVICES" in fix

    def test_recorded_no_cuda_reasons_keep_their_identity(self):
        """#1577 identity: these reasons are recorded (the capability travels in
        tuning inputs and unit invocations; the tuner persists it as
        probe_capability_reason) and are mapped back to a cause by exact text. The
        provider-aware wording lives in the never-recorded fix. Fails if a reason's
        text changes, which would strand the cause of every record written before."""
        from core.runtime_control.measurement_capability import NO_CUDA_REASONS

        assert NO_CUDA_REASONS == {
            "no_device_nodes": (
                "no CUDA device is visible: no /dev/nvidia<N> device node is present"
            ),
            "sys_not_mounted": (
                "no CUDA device is visible: NVIDIA device nodes are present but /sys is not mounted"
            ),
            "cuda_init_failed": (
                "no CUDA device is visible: NVIDIA device nodes and /sys are present, "
                "but CUDA failed to initialize"
            ),
        }

    @pytest.mark.parametrize("cause", ["no_device_nodes", "sys_not_mounted", "cuda_init_failed"])
    def test_the_resolver_carries_the_cause_to_the_capability(self, monkeypatch, cause):
        """Production reachability: the reason the resolver records must map back to
        the observed cause and stay an accelerator reason (the launch guard's GPU
        wording depends on both)."""
        torch = pytest.importorskip("torch")
        monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
        monkeypatch.setattr(
            "core.runtime_control.measurement_capability.observe_gpu_unavailable_cause",
            lambda: cause,
        )
        capability = resolve_measurement_capability(**IDENTITY, dataset_root=None)
        assert capability.accelerator_unavailable is True
        assert capability.gpu_unavailable_cause == cause
