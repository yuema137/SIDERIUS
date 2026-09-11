"""FU-C-1 — the bootstrap probe path must name its device.

**Found by the Gate 2 Case B audit, not by any test.** V20 PR C makes
blocking authority depend on a `MeasurementValidity` verdict, and that
verdict exists only when an occupancy window was built — which happens only
when the probe is told WHICH device to account for.

PR C threaded the device identity through the tuner path and stopped there.
`core/runtime_control/bootstrap.py` is a second, production-supported probe
entry, and its historical task-aware launcher called `run_bounded_probe`
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

        src = Path(__file__).resolve().parents[3] / "src/core" / "runtime_control" / "bootstrap.py"
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

        src = Path(__file__).resolve().parents[3] / "src/core" / "runtime_control" / "bootstrap.py"
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


class TestTheIdentityIsResolvedBeforeTheWindowIsSampled:
    """Found by real-GPU Case B1, not by a test.

    The first B1 run reported `activity: "unknown"` with empty PID lists
    while a 5,104 MiB holder was demonstrably present. Two causes, in order:

    1. the hardware COMPATIBILITY profile carries no device UUID, so
       `device_identity_from_hardware` returned `None`;
    2. even once discovery supplied one, the contention window was sampled
       BEFORE the identity was resolved, so no occupancy snapshots were
       collected and the observation could only honestly say `unknown`.

    The compatibility profile is deliberately NOT extended to carry a UUID:
    it is hashed into `hardware_compatibility_id`, so adding fields would
    change every historical calibration bucket's identity and silently
    invalidate accumulated evidence.
    """

    def test_discovery_supplies_a_uuid_through_the_one_adapter(self):
        """MUTATION TARGET: constructing a DeviceIdentity directly.

        The record is duck-typed for `device_identity_from_hardware`, which
        remains the only translation point.
        """
        from core.runtime_control.probe_production import discover_active_device_record

        rec = discover_active_device_record()
        # On a CPU host or unreadable driver this is None — a gap, never a
        # guessed device 0.
        assert hasattr(rec, "active_device_uuid")
        assert hasattr(rec, "devices")
        if rec.active_device_uuid is not None:
            ident = device_identity_from_hardware(rec)
            assert ident is not None
            assert ident.uuid == rec.active_device_uuid

    def test_an_unreadable_driver_yields_no_identity(self):
        """Fail closed: a gap stays a gap."""
        from types import SimpleNamespace

        assert (
            device_identity_from_hardware(
                SimpleNamespace(active_device_uuid=None, devices=(), cuda_visible_devices=None)
            )
            is None
        )

    def test_the_window_is_sampled_WITH_the_device(self):
        """MUTATION TARGET: sampling the window before resolving identity.

        Ordering is the whole defect: an unnamed device builds no occupancy
        snapshots, so external activity can only be reported as `unknown`
        however present a neighbour is.
        """
        import ast
        from pathlib import Path

        src = (
            Path(__file__).resolve().parents[3] / "src/core" / "runtime_control" / "bootstrap.py"
        ).read_text(encoding="utf-8")

        resolve_at = src.index("_identity = device_identity_from_hardware(hardware)")
        sample_at = src.index("window = deps.sample_contention(")
        assert resolve_at < sample_at, (
            "the device identity must be resolved BEFORE the contention "
            "window is sampled, or no occupancy snapshots are collected"
        )

        tree = ast.parse(src)
        carried = [
            n.lineno
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and getattr(n.func, "attr", None) == "sample_contention"
            and "device" in {kw.arg for kw in n.keywords}
        ]
        assert carried, "sample_contention is called without device="

    def test_the_compatibility_profile_is_NOT_extended(self):
        """Guard the reason the discovery record exists at all.

        Adding a UUID field to `HardwareCompatibilityProfile` would change
        `hardware_compatibility_id` and invalidate every historical
        calibration bucket.
        """
        from core.runtime_control.registry_schemas import HardwareCompatibilityProfile

        for forbidden in ("active_device_uuid", "devices", "device_uuid"):
            assert forbidden not in HardwareCompatibilityProfile.model_fields, (
                f"{forbidden} was added to the hashed compatibility profile; "
                f"this changes hardware_compatibility_id and invalidates "
                f"historical calibration buckets"
            )
