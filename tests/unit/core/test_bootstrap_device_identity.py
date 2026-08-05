"""FU-C-1 — the bootstrap probe path must name its device.

**Found by the Gate 2 Case B audit, not by any test.** V20 PR C makes
blocking authority depend on a `MeasurementValidity` verdict, and that
verdict exists only when an occupancy window was built — which happens only
when the probe is told WHICH device to account for.

PR C threaded the device identity through the tuner path and stopped there.
`core/runtime_control/bootstrap.py` is a second, production-supported probe
entry (`scripts/runtime_bootstrap.py`), and it called `run_bounded_probe`
without an identity. So on that path every measurement came back
`measurement_validity=None` and fell back to the conservative pre-PR-C rule:
a stable neighbour would still deny it blocking authority, and PR C's rule
was unreachable from a real entry point.

Not unsafe — `None` means "no window observed" and fails closed — but it is
the same defect class as PR D's three silent schema drops and PR C's own
`extrapolate_probe` gap: **a value is produced and the consumer never
receives it.** Third occurrence in this PR family, which is why it gets a
reachability test rather than a comment.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.runtime_control.gpu_accounting import DeviceIdentity, device_identity_from_hardware


def _hardware(uuid: str | None, *, physical_index: int = 3) -> SimpleNamespace:
    """A hardware record shaped like the one bootstrap collects."""
    devices = []
    if uuid:
        devices = [SimpleNamespace(uuid=uuid, physical_index=physical_index, logical_index=0)]
    return SimpleNamespace(
        active_device_uuid=uuid,
        devices=devices,
        cuda_visible_devices="0",
        accelerator_model="NVIDIA GeForce RTX 5090",
        gpu_count=1,
        vram_gb=31.34,
        torch_version="2.7.0",
    )


class TestTheProbeCallSiteNamesTheDevice:
    def test_bootstrap_passes_a_device_identity_to_the_probe(self):
        """MUTATION TARGET: dropping `device_identity=` from the call.

        Checked per CALL NODE via AST. A substring search would pass on the
        assignment line alone, leaving the argument unpassed — which is
        exactly the state this test exists to forbid.
        """
        import ast
        from pathlib import Path

        src = Path(__file__).resolve().parents[3] / "core" / "runtime_control" / "bootstrap.py"
        tree = ast.parse(src.read_text(encoding="utf-8"))

        calls = 0
        undeclared: list[int] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr != "run_probe":
                continue
            calls += 1
            if "device_identity" not in {kw.arg for kw in node.keywords}:
                undeclared.append(node.lineno)

        assert calls >= 1, "bootstrap no longer calls deps.run_probe"
        assert undeclared == [], (
            f"deps.run_probe called without device_identity at lines {undeclared}; "
            f"the probe then builds no occupancy window and every measurement "
            f"falls back to the conservative pre-PR-C rule"
        )

    def test_the_production_runner_forwards_it_to_run_bounded_probe(self):
        """MUTATION TARGET: accepting the argument and dropping it."""
        import ast
        from pathlib import Path

        src = Path(__file__).resolve().parents[3] / "core" / "runtime_control" / "bootstrap.py"
        tree = ast.parse(src.read_text(encoding="utf-8"))

        forwarded = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name != "run_bounded_probe":
                continue
            if "device_identity" in {kw.arg for kw in node.keywords}:
                forwarded = True

        assert forwarded, (
            "the bootstrap probe runner does not forward device_identity to "
            "run_bounded_probe, so naming the device at the call site achieves "
            "nothing"
        )


class TestIdentityResolutionFailsClosed:
    """A degraded identity must stay degraded. The alternative — guessing —
    silently attributes every measurement to the wrong card."""

    def test_a_cpu_host_yields_no_identity_rather_than_device_zero(self):
        """MUTATION TARGET: defaulting to `DeviceIdentity(physical_index=0)`.

        A record with no UUID means telemetry is unavailable. Repairing it
        by assuming device 0 would conflate two cards of the same model, and
        every misattributed measurement would look perfectly valid.
        """
        assert device_identity_from_hardware(_hardware(None)) is None

    def test_no_identity_means_no_window_not_a_valid_verdict(self):
        """The consequence, stated where it can fail: absent identity must
        leave validity unestablished, never asserted valid."""
        from core.runtime_control.estimate_types import make_estimate

        estimate = make_estimate(
            provenance="bounded_live_probe",
            confidence="medium",
            expected_seconds=10.0,
            concurrency_identity="foreign_contended",
            measurement_validity=None,
        )
        # No window was observed, so the conservative rule applies.
        assert estimate.measurement_validity is None
        assert estimate.blocking_eligible is False

    def test_the_uuid_not_the_index_identifies_the_device(self):
        """A multi-GPU host must not be keyed on position. `physical_index`
        is descriptive; the UUID is the identity."""
        identity = device_identity_from_hardware(_hardware("GPU-abc", physical_index=3))
        assert isinstance(identity, DeviceIdentity)
        assert identity.uuid == "GPU-abc"
        assert identity.physical_index == 3, "must not be flattened to 0"


class TestTheWindowIsActuallyBuiltWhenNamed:
    """End of the chain: naming the device must produce a real verdict."""

    @pytest.mark.parametrize(
        ("named", "expected"),
        [(True, "valid_current_conditions"), (False, None)],
        ids=["named-device-builds-a-window", "unnamed-device-builds-none"],
    )
    def test_naming_the_device_decides_whether_a_verdict_exists(self, named, expected):
        from core.runtime_control.calibration_policy import sample_contention_window
        from core.runtime_control.gpu_accounting import (
            GpuAccountingSnapshot,
            ProcessOccupancy,
        )
        from core.runtime_control.probe import ContentionSnapshot

        dev = DeviceIdentity(uuid="GPU-abc", physical_index=0)

        def _account(_root, _dev):
            other = (ProcessOccupancy(pid=999, used_mib=20_000),)
            return GpuAccountingSnapshot(
                device=dev,
                telemetry_available=True,
                device_used_mib=20_000,
                device_total_mib=81_920,
                own_tree_mib=0,
                own_processes=(),
                other_mib=20_000,
                other_process_count=1,
                other_processes=other,
                per_pid_total_mib=20_000,
                unattributed_mib=0,
                accounting_skew_mib=0,
            )

        window = sample_contention_window(
            device_vram_gb=80.0,
            device=dev if named else None,
            root_pid=1,
            account=_account,
            capture=lambda *a, **k: ContentionSnapshot(telemetry_available=True),
            sleep=lambda _s: None,
        )
        assert window.measurement_validity == expected
