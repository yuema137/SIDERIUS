"""B-C2b — bounded GPU evidence around one phase.

Everything is injected: the sampler, the baseline sampler and the clock.
No GPU, no driver, no TIDMAD data, and no real threads waiting on real
intervals except where the thread itself is what is being tested.
"""

from __future__ import annotations

import ast
import threading
import time
from pathlib import Path

import pytest

from core.runtime_control.gpu_accounting import (
    DeviceBaselineSnapshot,
    DeviceIdentity,
    GpuAccountingSnapshot,
)
from core.runtime_control.gpu_observer import (
    GpuEvidenceBundle,
    GpuObservationPolicy,
    GpuPhaseObserver,
)

DEV = DeviceIdentity(uuid="GPU-aaaa-0000", physical_index=0)
SOURCE = Path(__file__).resolve().parents[3] / "core" / "runtime_control" / "gpu_observer.py"


def snap(own: int, other: int = 0, *, ok: bool = True) -> GpuAccountingSnapshot:
    if not ok:
        return GpuAccountingSnapshot(device=DEV, telemetry_available=False)
    return GpuAccountingSnapshot(
        device=DEV,
        telemetry_available=True,
        device_used_mib=own + other,
        device_total_mib=32607,
        own_tree_mib=own,
        other_mib=other,
        other_process_count=1 if other else 0,
        per_pid_total_mib=own + other,
        unattributed_mib=0,
        accounting_skew_mib=0,
    )


def baseline(free: int = 30000) -> DeviceBaselineSnapshot:
    return DeviceBaselineSnapshot(
        device=DEV,
        telemetry_available=True,
        sampled_at=1.0,
        device_used_mib=32607 - free,
        device_total_mib=32607,
        device_free_mib=free,
        processes=(),
        process_count=0,
    )


def scripted(*snaps):
    """A sampler that yields the given snapshots then repeats the last."""
    seq = list(snaps)

    def _s(_pid, _dev):
        return seq.pop(0) if len(seq) > 1 else seq[0]

    return _s


class TestPolicy:
    def test_cadence_is_fast_then_steady(self):
        p = GpuObservationPolicy()
        assert p.interval_ms_at(0) == p.fast_interval_ms
        assert p.interval_ms_at(p.fast_window_ms - 1) == p.fast_interval_ms
        assert p.interval_ms_at(p.fast_window_ms) == p.steady_interval_ms
        assert p.interval_ms_at(10**9) == p.steady_interval_ms

    def test_defaults_give_a_short_phase_useful_coverage(self):
        """A5's training phase was 8.0 s. At the opening cadence that is
        roughly 40 samples, not a handful."""
        p = GpuObservationPolicy()
        assert 8_000 / p.fast_interval_ms >= 30

    def test_it_is_configurable_not_constant(self):
        p = GpuObservationPolicy(fast_interval_ms=50, fast_window_ms=100, steady_interval_ms=500)
        assert p.interval_ms_at(0) == 50
        assert p.interval_ms_at(200) == 500

    def test_it_carries_no_admission_policy(self):
        """Cadence is observation policy. Ceilings are a different
        category with different authority (§1.4.2)."""
        fields = set(GpuObservationPolicy.model_fields)
        for forbidden in ("ceiling_gib", "pair_ceiling_gib", "vram_budget_gb", "host_quota_mib"):
            assert forbidden not in fields


class TestObservedPeak:
    def test_peak_is_one_whole_snapshot_not_a_fieldwise_max(self):
        """own peaks at t1 with other=100; other peaks at t2 with own=10.
        A per-field maximum would report own=500 alongside other=9000 —
        a state that never existed."""
        obs = GpuPhaseObserver(DEV, sampler=scripted(snap(500, 100), snap(10, 9000)))
        obs._started_at = 0.0
        obs._record(snap(500, 100))
        obs._record(snap(10, 9000))
        peak = obs.bundle().observed_peak
        assert peak is not None
        assert (peak.own_tree_mib, peak.other_mib) == (500, 100)

    def test_the_maximum_is_tracked_across_samples(self):
        obs = GpuPhaseObserver(DEV)
        obs._started_at = 0.0
        for own in (100, 900, 400):
            obs._record(snap(own))
        assert obs.bundle().observed_peak.own_tree_mib == 900

    def test_failed_samples_do_not_become_a_peak(self):
        obs = GpuPhaseObserver(DEV)
        obs._started_at = 0.0
        obs._record(snap(0, ok=False))
        obs._record(snap(300))
        b = obs.bundle()
        assert b.observed_peak.own_tree_mib == 300
        assert b.failed_sample_count == 1
        assert b.valid_sample_count == 1


class TestCoverage:
    def test_counts_and_offsets_are_recorded(self):
        ticks = iter([0.0, 0.5, 1.5, 2.0])
        obs = GpuPhaseObserver(DEV, clock=lambda: next(ticks))
        obs._started_at = 0.0
        obs._record(snap(10))
        obs._record(snap(20))
        b = obs.bundle()
        assert b.valid_sample_count == 2
        assert b.first_valid_offset_ms == 0.0
        assert b.last_valid_offset_ms == 500.0

    def test_thin_coverage_is_flagged(self):
        obs = GpuPhaseObserver(DEV)
        obs._started_at = 0.0
        obs._record(snap(10))
        assert obs.bundle().coverage_is_thin is True

    def test_no_samples_at_all_is_thin(self):
        assert GpuPhaseObserver(DEV).bundle().coverage_is_thin is True

    def test_adequate_coverage_is_not_flagged(self):
        obs = GpuPhaseObserver(DEV)
        obs._started_at = 0.0
        for own in (10, 20, 30):
            obs._record(snap(own))
        assert obs.bundle().coverage_is_thin is False


class TestDeviceIdentityRequired:
    def test_no_identity_disables_observation_without_rediscovery(self):
        """A missing identity means telemetry is unavailable, not that a
        device should be found. Rediscovery is how GPU 0 gets assumed."""
        called = {"n": 0}

        def _never(*_a, **_k):
            called["n"] += 1
            raise AssertionError("observer tried to sample without an identity")

        obs = GpuPhaseObserver(None, sampler=_never, baseline_sampler=_never)
        assert obs.enabled is False
        obs.capture_baseline()
        obs.start(1234)
        obs.stop(child_pid=1234, failed=True)
        b = obs.bundle()
        assert called["n"] == 0
        assert b.device is None
        assert b.baseline_before_spawn is None
        assert b.observed_peak is None
        assert b.sampling_policy is None

    def test_the_bundle_records_which_device_it_describes(self):
        obs = GpuPhaseObserver(DEV, baseline_sampler=lambda _d: baseline())
        obs.capture_baseline()
        assert obs.bundle().device is DEV
        assert obs.bundle().baseline_before_spawn.device is DEV


class TestBaselineSlot:
    def test_baseline_is_captured_before_any_child_exists(self):
        obs = GpuPhaseObserver(DEV, baseline_sampler=lambda _d: baseline(free=12345))
        obs.capture_baseline()
        b = obs.bundle().baseline_before_spawn
        assert b is not None
        assert b.device_free_mib == 12345

    def test_a_failing_baseline_does_not_raise(self):
        def _boom(_d):
            raise OSError("nvidia-smi gone")

        obs = GpuPhaseObserver(DEV, baseline_sampler=_boom)
        obs.capture_baseline()
        assert obs.bundle().baseline_before_spawn is None
        assert "OSError" in (obs.bundle().observer_error or "")


class TestLifecycle:
    def test_the_thread_samples_while_the_child_is_alive_then_stops(self):
        seen = threading.Event()
        count = {"n": 0}

        def _s(_pid, _dev):
            count["n"] += 1
            seen.set()
            return snap(100 + count["n"])

        obs = GpuPhaseObserver(
            DEV,
            policy=GpuObservationPolicy(fast_interval_ms=5, fast_window_ms=10_000),
            sampler=_s,
        )
        obs.start(4321)
        assert seen.wait(timeout=5.0), "observer never sampled"
        obs.stop(child_pid=4321)
        assert obs._thread is None
        b = obs.bundle()
        assert b.valid_sample_count >= 1
        assert b.child_runtime_ms is not None

        # The thread must not outlive stop(). Sample the counter, give a
        # still-running thread several of its own intervals to tick, and
        # require it not to have moved.
        after = count["n"]
        time.sleep(0.05)
        assert count["n"] == after, "observer kept sampling after stop()"

    def test_stop_is_idempotent_and_safe_without_start(self):
        obs = GpuPhaseObserver(DEV)
        obs.stop()
        obs.stop(child_pid=1, failed=True)

    def test_a_sampler_that_raises_never_escapes(self):
        def _boom(_pid, _dev):
            raise RuntimeError("telemetry exploded")

        obs = GpuPhaseObserver(DEV, policy=GpuObservationPolicy(fast_interval_ms=5), sampler=_boom)
        obs.start(1)
        obs.stop(child_pid=1)
        assert obs.bundle().failed_sample_count >= 1

    def test_a_join_timeout_is_recorded_not_waited_out(self):
        """Telemetry must never hold up the child's cleanup."""
        wedged = threading.Event()

        class _Wedged(GpuPhaseObserver):
            def _loop(self, child_pid):  # never returns until released
                wedged.wait(timeout=10.0)

        obs = _Wedged(DEV, policy=GpuObservationPolicy(join_timeout_ms=50))
        obs.start(7)
        obs.stop(child_pid=7)
        assert obs.bundle().observer_join_timed_out is True
        wedged.set()

    def test_post_failure_is_taken_only_on_failure(self):
        obs = GpuPhaseObserver(DEV, sampler=lambda _p, _d: snap(42))
        obs.stop(child_pid=9, failed=False)
        assert obs.bundle().post_failure is None

        obs2 = GpuPhaseObserver(DEV, sampler=lambda _p, _d: snap(42))
        obs2.stop(child_pid=9, failed=True)
        assert obs2.bundle().post_failure.own_tree_mib == 42


class TestBoundedness:
    def test_the_bundle_holds_four_snapshots_regardless_of_runtime(self):
        obs = GpuPhaseObserver(DEV)
        obs._started_at = 0.0
        for i in range(500):
            obs._record(snap(i))
        b = obs.bundle()
        assert b.valid_sample_count == 500

        # Exactly four snapshot slots, and no field that grows with the
        # sample count — the whole point of a bounded bundle.
        snapshot_fields = [
            n for n, f in GpuEvidenceBundle.model_fields.items() if "Snapshot" in str(f.annotation)
        ]
        assert len(snapshot_fields) == 4, snapshot_fields
        for name, value in b:
            assert not isinstance(value, (list, tuple)), (
                f"{name} is a sequence; the bundle must stay fixed-size "
                "regardless of how long the phase ran"
            )


class TestGenericity:
    """§1.4 — the observer must not know what task it serves."""

    def test_imports_no_task_module(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        forbidden = ("execute_tools", "ml_models", "nodes", "agent", "workflows", "torch")
        offenders = [m for m in imported if any(m.startswith(f) for f in forbidden)]
        assert not offenders, f"observer imports task modules: {offenders}"

    def test_code_names_no_task_or_phase_vocabulary(self):
        """The caller names the phase; this module never does."""
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        docstrings = {
            id(n.body[0].value)
            for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef))
            and n.body
            and isinstance(n.body[0], ast.Expr)
            and isinstance(n.body[0].value, ast.Constant)
            and isinstance(n.body[0].value.value, str)
        }
        tokens = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                tokens.append(node.id)
            elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                tokens.append(node.name)
            elif isinstance(node, ast.arg):
                tokens.append(node.arg)
            elif isinstance(node, ast.Constant) and id(node) not in docstrings:
                tokens.append(str(node.value))
        joined = " ".join(tokens).lower()
        for term in ("tidmad", "denois", "segmentation", "training", "inference"):
            assert term not in joined, f"task vocabulary {term!r} in executable code"

    def test_no_hardware_ceiling_constant(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        numbers = {
            n.value
            for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, (int, float))
        }
        for forbidden in (12, 12.0, 28, 28.0, 29000, 30000):
            assert forbidden not in numbers, f"admission constant {forbidden!r} in observer"


class TestNoPromotion:
    def test_the_bundle_declares_no_cross_run_authority(self):
        """D-B5: B-C2b produces evidence, not authoritative measurements.
        A field claiming applicability or promotion would create the
        second measurement authority PR C exists to own."""
        fields = set(GpuEvidenceBundle.model_fields)
        for forbidden in ("authoritative", "promoted", "applicable_to", "registry_key"):
            assert forbidden not in fields

    @pytest.mark.parametrize("attr", ["coverage_is_thin"])
    def test_thinness_is_exposed_so_bc3_can_refuse(self, attr):
        assert hasattr(GpuEvidenceBundle(), attr)
