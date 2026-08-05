"""The candidate's own GPU memory must not be counted against it.

**Found by Gate 2 attempt 1 (2026-08-05), not by any test.** A real chain
aborted on a device holding 5.98 GB, with `foreign_compute_pids: []`, every
compute PID inside `excluded_pids`, and the GPU at 0% utilisation. The window
was classified `foreign_contended`, which made a freshly measured probe
non-blocking and terminated the run.

The classifier compared the DEVICE TOTAL against the contention threshold and
never asked whose memory it was — so a candidate that had merely initialised
its own CUDA context looked like external contention.

Two defects are covered here, and they fail differently:

* **attribution** (`classify_contention_window`) — candidate-owned bytes are
  subtracted before the threshold comparison;
* **capture** (`capture_contention_snapshot`) — without per-process bytes the
  classifier has nothing to attribute WITH, so the query itself is part of
  the contract.

**Scope guard.** This is a bug fix, not an admission-policy change. Only
candidate-owned bytes change treatment. A registered peer's memory, an
unregistered foreign PID and an unattributable residual all keep exactly
today's outcome — deciding that stable external occupancy is acceptable is
PR C's decision (§20.3), and a test here pins that it did NOT happen early.
"""

from __future__ import annotations

import math

from core.runtime_control.calibration_policy import (
    DEFAULT_POLICY,
    classify_contention_window,
)
from core.runtime_control.probe import ContentionSnapshot

VRAM = 80.0
# max(floor, fraction × VRAM) under DEFAULT_POLICY. Derived from the policy
# rather than hardcoded: this suite must not pin a threshold it does not own.
THRESHOLD = max(
    DEFAULT_POLICY.contention_memory_floor_gb,
    DEFAULT_POLICY.contention_memory_fraction * VRAM,
)
OVER = THRESHOLD + 2.0
UNDER = THRESHOLD - 1.0


def _snap(
    *,
    used_gb: float,
    per_process: dict[str, float] | None = None,
    excluded: tuple[int, ...] = (),
    foreign_pids: tuple[int, ...] = (),
    util: float = 0.0,
) -> ContentionSnapshot:
    return ContentionSnapshot(
        telemetry_available=True,
        gpu_memory_used_gb=used_gb,
        gpu_utilization_pct=util,
        compute_process_memory_gb=per_process or {},
        excluded_pids=excluded,
        foreign_compute_pids=foreign_pids,
        foreign_compute_processes=len(foreign_pids),
    )


def _classify(*snaps: ContentionSnapshot, peers: tuple[int, ...] = ()):
    return classify_contention_window(snaps, device_vram_gb=VRAM, expected_peer_pids=peers)


class TestTheGate2Case:
    def test_the_candidates_own_memory_is_not_external_contention(self):
        """MUTATION TARGET: comparing the device total instead of the
        external remainder.

        This is the measured Gate 2 shape, scaled to the threshold: every
        byte on the device belongs to a PID the probe already excluded as
        its own. Before the fix this returned `foreign_contended`.
        """
        identity, reasons = _classify(
            _snap(used_gb=OVER, per_process={"111": OVER}, excluded=(111,)),
        )
        assert identity == "single_candidate_idle", reasons

    def test_a_candidate_owned_device_can_still_carry_blocking_authority(self):
        """The consequence that actually aborted the chain.

        Identity is not the point — `blocking_eligible` is. A window that
        the candidate alone occupies must be able to block, or a correct
        measurement is discarded and the run dies with no usable evidence.
        """
        from core.runtime_control.estimate_types import make_estimate

        identity, _ = _classify(
            _snap(used_gb=OVER, per_process={"111": OVER}, excluded=(111,)),
        )
        estimate = make_estimate(
            provenance="bounded_live_probe",
            confidence="medium",
            expected_seconds=10.0,
            concurrency_identity=identity,
        )
        assert estimate.contended is False
        assert estimate.blocking_eligible is True

    def test_the_candidates_processes_are_summed_not_maxed(self):
        """A candidate with several processes (trainer + dataloader workers)
        owns their SUM. Taking any single one leaves the rest looking
        external.

        The sizes matter and are chosen so the distinction is load-bearing:
        each process holds MORE than the threshold on its own, so summing
        yields a zero remainder (clean) while maxing leaves one whole
        process-worth above the threshold (contended). A first version used
        two half-sized processes and a mutation proved it useless — the
        maxed remainder still fell under the threshold, so both behaviours
        returned the same verdict.
        """
        each = THRESHOLD + 1.0
        identity, reasons = _classify(
            _snap(
                used_gb=each * 2,
                per_process={"111": each, "222": each},
                excluded=(111, 222),
            ),
        )
        assert identity == "single_candidate_idle", reasons


class TestWhatMustNotChange:
    """The scope guard. Each of these was contended before and stays
    contended — a bug fix may not widen admission."""

    def test_an_unregistered_foreign_pid_still_contends(self):
        identity, _ = _classify(
            _snap(used_gb=UNDER, per_process={"999": UNDER}, foreign_pids=(999,)),
        )
        assert identity == "foreign_contended"

    def test_a_registered_peers_memory_still_contends(self):
        """PR C may later decide a stable peer is acceptable. It has not,
        so this must stay contended — otherwise the hotfix would smuggle
        the admission change in (§20.3)."""
        identity, reasons = _classify(
            _snap(used_gb=OVER, per_process={"777": OVER}, excluded=()),
            peers=(777,),
        )
        assert identity == "foreign_contended", reasons
        assert any("registered peer" in r for r in reasons)

    def test_an_empty_attribution_map_is_never_read_as_candidate_owned(self):
        """A producer predating byte capture reports no map at all.

        Absence of evidence must not become evidence of a clean device:
        the bytes stay external and the window stays contended. Legacy
        records therefore keep their admission outcome exactly.
        """
        identity, _ = _classify(_snap(used_gb=OVER, per_process={}))
        assert identity == "unknown_contention"

    def test_a_pid_reported_without_its_size_stays_unattributable(self):
        """The driver named the process but not its memory (NaN). Those
        bytes cannot be credited to the candidate even though the PID is
        excluded."""
        identity, _ = _classify(
            _snap(
                used_gb=OVER,
                per_process={"111": math.nan},
                excluded=(111,),
            ),
        )
        assert identity == "unknown_contention"

    def test_partial_attribution_leaves_the_remainder_external(self):
        """The candidate owns 1 GB of an over-threshold device; the rest is
        unexplained and still blocks."""
        identity, reasons = _classify(
            _snap(
                used_gb=OVER + THRESHOLD,
                per_process={"111": 1.0},
                excluded=(111,),
            ),
        )
        assert identity == "unknown_contention", reasons

    def test_unattributable_memory_is_not_called_foreign(self):
        """It is over the threshold and it is not the candidate's — but no
        foreign PID was reported, so naming it `foreign` would assert
        something unmeasured. Admission is unchanged (both identities are
        contended); only the claim is honest."""
        from core.runtime_control.estimate_types import make_estimate

        identity, _ = _classify(_snap(used_gb=OVER, per_process={}))
        assert identity == "unknown_contention"
        estimate = make_estimate(
            provenance="bounded_live_probe",
            confidence="medium",
            expected_seconds=10.0,
            concurrency_identity=identity,
        )
        assert estimate.contended is True
        assert estimate.blocking_eligible is False

    def test_the_worst_sample_in_the_window_decides(self):
        """One clean sample must not launder a contended window."""
        identity, _ = _classify(
            _snap(used_gb=UNDER, per_process={"111": UNDER}, excluded=(111,)),
            _snap(used_gb=OVER, per_process={}),
        )
        assert identity == "unknown_contention"


class TestTheCaptureContract:
    """Attribution is impossible without per-process bytes, so the query is
    part of the contract — not an implementation detail."""

    def test_the_snapshot_query_asks_for_per_process_memory(self):
        """MUTATION TARGET: reverting the query to `pid` alone.

        Without `used_memory` every map is empty, every window falls into
        the unattributable branch, and the Gate 2 defect returns in a new
        costume — still aborting, now labelled `unknown_contention`. No
        classifier test can catch that, because the classifier would be
        behaving correctly on the evidence it was given.
        """
        import inspect

        from core.runtime_control import probe

        src = inspect.getsource(probe.capture_contention_snapshot)
        assert "--query-compute-apps=pid,used_memory" in src
        assert "nounits" in src, "MiB values must be bare numbers to parse"

    def test_a_pid_without_a_size_is_kept_as_a_foreign_signal(self):
        """A single-column driver response must not drop the PID: the
        foreign-PID check is the other half of the policy, and silently
        losing rows would disable it while looking like a parsing detail."""
        import inspect

        from core.runtime_control import probe

        src = inspect.getsource(probe.capture_contention_snapshot)
        assert 'float("nan")' in src or "float('nan')" in src
