"""V20 PR C — external occupancy must not invalidate a calibration.

The defect this boundary corrects aborted a real chain (Gate 2 attempt 1,
2026-08-05): `blocking = measured and not contended`, where `contended` was
true whenever any foreign process held any memory, however steadily. That is
a statement about the device being busy, not about the measurement being
trustworthy.

**T0, as ruled**: identity-and-attribution stability, NOT numerically
constant bytes. The tests are organised around that distinction, because it
is the whole ruling and the easiest thing to regress into a byte comparison.
"""

from __future__ import annotations

import pytest

from core.runtime_control.gpu_accounting import (
    DeviceIdentity,
    GpuAccountingSnapshot,
    ProcessOccupancy,
)
from core.runtime_control.measurement_validity import (
    attribute_measured_failure,
    build_occupancy_window,
    classify_measurement_validity,
)

DEV = DeviceIdentity(uuid="GPU-aaaa", physical_index=0)


def _snap(
    *,
    others: dict[int, int] | None = None,
    own: dict[int, int] | None = None,
    unattributed: int = 0,
    free: int = 40_000,
    available: bool = True,
) -> GpuAccountingSnapshot:
    if not available:
        return GpuAccountingSnapshot(device=DEV, telemetry_available=False)
    others = others or {}
    own = own or {}
    other_procs = tuple(ProcessOccupancy(pid=p, used_mib=m) for p, m in others.items())
    own_procs = tuple(ProcessOccupancy(pid=p, used_mib=m) for p, m in own.items())
    per_pid = sum(others.values()) + sum(own.values())
    used = per_pid + unattributed
    # `free` is expressed by the caller and realised as a device total, since
    # GpuAccountingSnapshot states used+total rather than free.
    return GpuAccountingSnapshot(
        device=DEV,
        telemetry_available=True,
        device_used_mib=used,
        device_total_mib=used + free,
        own_tree_mib=sum(own.values()),
        own_processes=own_procs,
        other_mib=sum(others.values()),
        other_process_count=len(other_procs),
        other_processes=other_procs,
        per_pid_total_mib=per_pid,
        unattributed_mib=unattributed,
        accounting_skew_mib=unattributed,
    )


class TestStableExternalOccupancyIsValid:
    """The ruling's positive half — and the reason this PR exists."""

    def test_a_large_steady_neighbour_does_not_invalidate(self):
        """MUTATION TARGET: reinstating a presence check.

        20 GiB of someone else's memory, present throughout. Under the old
        rule this was `foreign_contended` and could not block. It is now
        valid: the neighbour is simply part of the conditions measured.
        """
        window = [_snap(others={999: 20_000}, own={111: 4_000}) for _ in range(5)]
        validity, reasons = classify_measurement_validity(window)
        assert validity == "valid_current_conditions", reasons

    def test_bytes_may_vary_while_identity_holds(self):
        """MUTATION TARGET: comparing bytes instead of identity.

        THE ruling, in one test. The same neighbour breathing between 8 and
        18 GiB is stable conditions — T0 is an identity rule, not a
        numeric-constancy rule. A byte comparison would reject this.
        """
        window = [
            _snap(others={999: mib}, own={111: 4_000})
            for mib in (8_000, 18_000, 9_500, 17_000, 12_000)
        ]
        validity, reasons = classify_measurement_validity(window)
        assert validity == "valid_current_conditions", reasons

    def test_a_constant_unattributed_baseline_is_not_growth(self):
        """Presence is not growth. A device may carry a steady unattributed
        baseline (driver context, a graphics client) and still be a stable
        environment."""
        window = [_snap(others={999: 5_000}, unattributed=1_200) for _ in range(4)]
        assert classify_measurement_validity(window)[0] == "valid_current_conditions"

    def test_an_empty_device_is_valid(self):
        assert classify_measurement_validity([_snap() for _ in range(3)])[0] == (
            "valid_current_conditions"
        )


class TestEvidenceQualityFailures:
    """The only things that may remove blocking authority."""

    def test_a_neighbour_arriving_mid_window_is_unstable_identity(self):
        window = [
            _snap(others={999: 5_000}),
            _snap(others={999: 5_000}),
            _snap(others={999: 5_000, 1234: 2_000}),
        ]
        validity, reasons = classify_measurement_validity(window)
        assert validity == "unstable_external_identity"
        assert "1234" in reasons[0]

    def test_a_neighbour_leaving_mid_window_is_unstable_identity(self):
        """Departure matters as much as arrival: the second half of the
        window describes a different machine from the first."""
        window = [_snap(others={999: 5_000}), _snap(others={999: 5_000}), _snap(others={})]
        assert classify_measurement_validity(window)[0] == "unstable_external_identity"

    def test_a_neighbour_that_restarts_changes_identity(self):
        """Same memory, same count, different PID. A totals-only comparison
        would call these identical — which is precisely why the ruling is
        about identity."""
        window = [_snap(others={999: 5_000}), _snap(others={1000: 5_000})]
        assert classify_measurement_validity(window)[0] == "unstable_external_identity"

    def test_growing_unattributed_memory_is_a_failure(self):
        window = [_snap(unattributed=500), _snap(unattributed=500), _snap(unattributed=9_000)]
        validity, reasons = classify_measurement_validity(window)
        assert validity == "unattributed_occupancy_growth"
        assert "500" in reasons[0] and "9000" in reasons[0].replace(",", "")

    def test_shrinking_unattributed_memory_is_not_a_failure(self):
        """Only GROWTH compromises attribution. Bytes becoming explicable
        is not evidence going missing."""
        window = [_snap(unattributed=9_000), _snap(unattributed=500)]
        assert classify_measurement_validity(window)[0] == "valid_current_conditions"

    def test_a_telemetry_gap_is_sampling_incomplete(self):
        window = [_snap(), _snap(available=False), _snap()]
        validity, reasons = classify_measurement_validity(window)
        assert validity == "sampling_incomplete"
        assert "1" in reasons[0]

    def test_an_empty_window_is_unobserved_not_clean(self):
        """MUTATION TARGET: returning valid for an empty window.

        The single most dangerous default in this module: it would grant
        blocking authority to a device nobody looked at.
        """
        assert classify_measurement_validity([])[0] == "sampling_incomplete"

    def test_sampling_completeness_is_decided_before_stability(self):
        """A window that was not fully observed cannot support ANY claim
        about identity — including a claim that identity changed."""
        window = [_snap(others={999: 100}), _snap(available=False), _snap(others={555: 100})]
        assert classify_measurement_validity(window)[0] == "sampling_incomplete"

    def test_every_refusal_states_a_reason(self):
        """An operator reading a refusal must see which fact produced it."""
        for window in (
            [],
            [_snap(available=False)],
            [_snap(others={1: 10}), _snap(others={2: 10})],
            [_snap(unattributed=10), _snap(unattributed=900)],
        ):
            validity, reasons = classify_measurement_validity(window)
            assert validity != "valid_current_conditions"
            assert reasons and reasons[0].strip()


class TestTheConservativeAggregates:
    def test_the_window_reports_worst_case_not_average(self):
        """MUTATION TARGET: using mean, or the last sample.

        A decision made from the mean of a varying environment is a decision
        about a moment that never occurred.
        """
        window = build_occupancy_window(
            [
                _snap(others={999: 5_000}, free=30_000),
                _snap(others={999: 20_000}, free=12_000),
                _snap(others={999: 8_000}, free=25_000),
            ]
        )
        assert window.min_free_mib == 12_000
        assert window.max_external_mib == 20_000
        assert window.blocking_capable is True

    def test_an_unobserved_window_is_not_blocking_capable(self):
        assert build_occupancy_window([]).blocking_capable is False

    def test_aggregates_stay_none_when_telemetry_never_produced_them(self):
        """A gap is not a zero — a `min_free_mib` of 0 would read as a full
        device."""
        window = build_occupancy_window([_snap(available=False)])
        assert window.min_free_mib is None
        assert window.max_external_mib is None


class TestOomAttribution:
    """The operator's OOM boundary. Attribution only — this never turns a
    failure into a pass."""

    def test_an_oom_under_valid_conditions_belongs_to_the_candidate(self):
        assert attribute_measured_failure("valid_current_conditions") == "candidate"

    @pytest.mark.parametrize(
        "validity",
        ["unstable_external_identity", "unattributed_occupancy_growth", "sampling_incomplete"],
    )
    def test_an_oom_under_compromised_evidence_is_not_the_candidates(self, validity):
        """MUTATION TARGET: attributing every OOM to the candidate.

        Charging a candidate for a neighbour's memory rejects a model for
        someone else's behaviour — and the rejection would look exactly like
        a genuine one.
        """
        assert attribute_measured_failure(validity) == "insufficient_evidence"
