"""B-C3b — attribution runs where the evidence still exists.

The executor's failure handler is the only point where the child's full
stderr (carrying the attempted-allocation size), the live evidence
bundle, and the return code coexist. Downstream the message is cut to
its last 500 characters, and because stdout is appended after stderr
that window normally holds trainer progress output rather than the
allocation line — so attribution rebuilt from a stored record would be
attribution built on the wrong text.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

from core.runtime_control.gpu_accounting import (
    DeviceBaselineSnapshot,
    DeviceIdentity,
    GpuAccountingSnapshot,
)
from core.runtime_control.gpu_observer import GpuEvidenceBundle, GpuObservationPolicy
from core.sandbox_executor import _has_host_memory_evidence, _with_failure_attribution

EXECUTOR_SOURCE = Path(__file__).resolve().parents[3] / "core" / "sandbox_executor.py"
DEV = DeviceIdentity(uuid="GPU-aaaa-0000", physical_index=0)
OOM_STDERR = (
    "torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 11.31 GiB "
    "(GPU 0; 31.75 GiB total capacity)"
)


def _error(returncode=1, stderr=""):
    return subprocess.CalledProcessError(returncode, ["train"], output="", stderr=stderr)


class _Observer:
    """Minimal stand-in — the executor only ever calls `.bundle()`."""

    def __init__(self, *, total=32_000, used=30_000, other=0, unattr=0, raises=False):
        self._raises = raises
        snap = GpuAccountingSnapshot(
            device=DEV,
            telemetry_available=True,
            device_total_mib=total,
            device_used_mib=used,
            own_tree_mib=1_000,
            other_mib=other,
            other_process_count=1 if other else 0,
            per_pid_total_mib=1_000 + other,
            unattributed_mib=unattr,
            accounting_skew_mib=unattr,
        )
        self._bundle = GpuEvidenceBundle(
            device=DEV,
            sampling_policy=GpuObservationPolicy(),
            baseline_before_spawn=DeviceBaselineSnapshot(
                device=DEV,
                telemetry_available=True,
                sampled_at=1.0,
                device_total_mib=total,
                device_used_mib=0,
                device_free_mib=total,
                processes=(),
                process_count=0,
            ),
            observed_peak=snap,
            last_while_alive=snap,
            valid_sample_count=10,
            child_runtime_ms=10_000.0,
            last_valid_offset_ms=9_900.0,
        )

    def bundle(self):
        if self._raises:
            raise RuntimeError("telemetry exploded")
        return self._bundle


class TestHostMemoryEvidence:
    def test_a_memory_error_is_genuine_corroboration(self):
        """RLIMIT_AS caught the allocation and Python raised — measured."""
        assert _has_host_memory_evidence(_error(1, "MemoryError: out of memory")) is True

    def test_a_bare_sigkill_is_not_evidence_of_host_pressure(self):
        """The whole point. A -9 is compatible with a kernel OOM kill, a
        quota watchdog and an operator, and cannot distinguish them.
        Feeding it in here would let the signal launder itself into a
        verdict — the inference B-C3 exists to refuse."""
        assert _has_host_memory_evidence(_error(-9, "Killed")) is False

    @pytest.mark.parametrize("stderr", ["", "torch.OutOfMemoryError: CUDA out of memory."])
    def test_neither_silence_nor_a_device_oom_counts(self, stderr):
        assert _has_host_memory_evidence(_error(-9, stderr)) is False


class TestExecutorAttribution:
    def test_a_device_oom_is_attributed_from_the_full_stderr(self):
        """9.4 GiB free, nothing else on the card, 11.31 GiB attempted."""
        result = _with_failure_attribution(
            {}, _error(1, OOM_STDERR), _Observer(total=32_607, used=23_187)
        )
        verdict = result["failure_attribution"]
        assert verdict["attribution"] == "candidate_gpu_capacity"
        assert verdict["may_recommend_resource_reduction"] is True
        assert verdict["evidence"]["attempted_allocation_mib"] == pytest.approx(11.31 * 1024)

    def test_a_peer_holding_the_card_does_not_blame_the_candidate(self):
        """The V19 shape, end to end through the executor seam.

        126 MiB free, a peer holding 25 GiB, 11.31 GiB attempted: the
        allocation would have fitted had the peer not been there, so the
        candidate is not at fault.
        """
        result = _with_failure_attribution(
            {},
            _error(1, OOM_STDERR),
            _Observer(total=32_607, used=32_481, other=25_000),
        )
        verdict = result["failure_attribution"]
        assert verdict["attribution"] == "gpu_contention"
        assert verdict["may_recommend_resource_reduction"] is False

    def test_a_peer_too_small_to_have_saved_it_still_blames_the_candidate(self):
        """The rule is arithmetic, not "a peer was present".

        Same 126 MiB free, but the peer holds only 9,222 MiB — removing
        it yields 9,348 MiB, still short of the 11.31 GiB attempted. The
        candidate really was too large for this device.
        """
        result = _with_failure_attribution(
            {},
            _error(1, OOM_STDERR),
            _Observer(total=32_607, used=32_481, other=9_222),
        )
        assert result["failure_attribution"]["attribution"] == "candidate_gpu_capacity"

    def test_unattributed_memory_withholds_the_verdict(self):
        """Between the two bounds, who owns the memory decides it."""
        result = _with_failure_attribution(
            {},
            _error(1, OOM_STDERR),
            _Observer(total=32_607, used=32_481, other=9_222, unattr=4_000),
        )
        verdict = result["failure_attribution"]
        assert verdict["attribution"] == "unknown"
        assert verdict["may_recommend_resource_reduction"] is False

    def test_a_device_oom_without_evidence_is_unknown(self):
        result = _with_failure_attribution({}, _error(1, OOM_STDERR), None)
        assert result["failure_attribution"]["attribution"] == "unknown"
        assert result["failure_attribution"]["may_recommend_resource_reduction"] is False

    def test_a_host_memory_error_is_attributed_to_host_pressure(self):
        result = _with_failure_attribution({}, _error(-9, "MemoryError"), _Observer())
        assert result["failure_attribution"]["attribution"] == "host_memory_pressure"

    def test_a_bare_kill_stays_unknown(self):
        result = _with_failure_attribution({}, _error(-9, "Killed"), _Observer())
        verdict = result["failure_attribution"]
        assert verdict["attribution"] == "unknown"
        assert verdict["evidence"]["returncode"] == -9

    def test_telemetry_failure_never_fails_the_phase(self):
        """A classifier that raises would turn a diagnosed failure into an
        undiagnosed crash — telemetry must not break the thing it watches."""
        result = _with_failure_attribution(
            {"status": "error"}, _error(1, OOM_STDERR), _Observer(raises=True)
        )
        assert result["status"] == "error"
        assert "failure_attribution" not in result

    def test_the_original_result_is_preserved(self):
        result = _with_failure_attribution(
            {"status": "error", "message": "m"}, _error(1, OOM_STDERR), _Observer()
        )
        assert result["status"] == "error"
        assert result["message"] == "m"


class TestProductionReachability:
    """Both failure handlers must actually call it.

    Attribution that exists but is never invoked is the recurring defect
    in this codebase, and it is invisible to every behavioural test.
    """

    def test_both_subprocess_failure_handlers_attribute(self):
        tree = ast.parse(EXECUTOR_SOURCE.read_text())
        callers = {
            fn.name
            for fn in ast.walk(tree)
            if isinstance(fn, ast.FunctionDef)
            and any(
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id == "_with_failure_attribution"
                for n in ast.walk(fn)
            )
        }
        assert {"execute_training", "execute_inference"} <= callers

    def test_the_signal_is_not_used_as_host_evidence(self):
        """`_is_oom_failure` also returns True for -9. Passing it as
        corroboration would recreate the inference this commit removes."""
        tree = ast.parse(EXECUTOR_SOURCE.read_text())
        fn = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "_with_failure_attribution"
        )
        names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
        assert "_is_oom_failure" not in names
        assert "_has_host_memory_evidence" in names
