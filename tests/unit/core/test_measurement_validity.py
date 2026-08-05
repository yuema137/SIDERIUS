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


class TestTheBlockingRuleChanged:
    """`blocking = measured and not contended` is gone.

    These assert the ELIGIBILITY consequence, which is what actually
    aborted the chain. A verdict nobody consults would change nothing.
    """

    @staticmethod
    def _estimate(**kw):
        from core.runtime_control.estimate_types import make_estimate

        return make_estimate(
            provenance="bounded_live_probe",
            confidence="medium",
            expected_seconds=10.0,
            **kw,
        )

    def test_a_stable_neighbour_no_longer_blocks_the_measurement(self):
        """MUTATION TARGET: restoring `blocking = measured and not contended`.

        THE regression that PR C exists to prevent. The identity still says
        `foreign_contended` — a neighbour IS present — but the window found
        the conditions valid, and validity is what decides now.
        """
        estimate = self._estimate(
            concurrency_identity="foreign_contended",
            measurement_validity="valid_current_conditions",
        )
        assert estimate.blocking_eligible is True

    @pytest.mark.parametrize(
        "validity",
        ["unstable_external_identity", "unattributed_occupancy_growth", "sampling_incomplete"],
    )
    def test_compromised_evidence_cannot_block_even_on_an_idle_device(self, validity):
        """The converse, and the fail-closed half: an idle-looking identity
        does not rescue a window whose evidence quality failed."""
        estimate = self._estimate(
            concurrency_identity="single_candidate_idle",
            measurement_validity=validity,
        )
        assert estimate.blocking_eligible is False

    def test_a_prior_still_cannot_block_however_valid_the_window(self):
        """Validity is necessary, never sufficient. Provenance still rules:
        a static prior with blocking authority stays unrepresentable."""
        from core.runtime_control.estimate_types import make_estimate

        estimate = make_estimate(
            provenance="static_uncalibrated",
            confidence="low",
            expected_seconds=10.0,
            measurement_validity="valid_current_conditions",
        )
        assert estimate.blocking_eligible is False

    def test_no_window_falls_back_conservatively(self):
        """Legacy producers supply no window. `None` means "no window", not
        "invalid" — but a contended identity still cannot ESTABLISH
        validity, so the pre-PR-C outcome is preserved exactly."""
        assert self._estimate(concurrency_identity="single_candidate_idle").blocking_eligible
        assert not self._estimate(concurrency_identity="foreign_contended").blocking_eligible
        assert not self._estimate(concurrency_identity="unknown_contention").blocking_eligible


class TestTheProducerPathIsWired:
    """Reachability: a verdict nobody produces changes nothing.

    The boundary and the eligibility rule are both correct in isolation and
    still useless if the sampler never builds a window — which is exactly
    how PR C could ship looking complete while every real run kept falling
    back to the conservative rule.
    """

    def test_a_device_makes_the_sampler_produce_a_verdict(self):
        """MUTATION TARGET: dropping `occupancy=` from the returned window."""
        from core.runtime_control.calibration_policy import sample_contention_window
        from core.runtime_control.probe import ContentionSnapshot

        window = sample_contention_window(
            device_vram_gb=80.0,
            device=DEV,
            root_pid=4242,
            account=lambda _root, _dev: _snap(others={999: 20_000}),
            capture=lambda *a, **k: ContentionSnapshot(telemetry_available=True),
            sleep=lambda _s: None,
        )
        assert window.measurement_validity == "valid_current_conditions"
        assert window.occupancy is not None
        assert window.occupancy.max_external_mib == 20_000

    def test_without_a_device_no_window_is_claimed(self):
        """`None` must mean "not observed", never a fabricated verdict."""
        from core.runtime_control.calibration_policy import sample_contention_window
        from core.runtime_control.probe import ContentionSnapshot

        window = sample_contention_window(
            device_vram_gb=80.0,
            capture=lambda *a, **k: ContentionSnapshot(telemetry_available=True),
            sleep=lambda _s: None,
        )
        assert window.occupancy is None
        assert window.measurement_validity is None

    def test_accounting_is_sampled_on_every_tick_not_once(self):
        """A single accounting sample cannot show change, so a one-shot
        reading would make every window trivially 'stable'."""
        from core.runtime_control.calibration_policy import sample_contention_window
        from core.runtime_control.probe import ContentionSnapshot

        calls: list[int] = []

        def _account(_root, _dev):
            calls.append(1)
            return _snap(others={999: 5_000} if len(calls) < 3 else {1234: 5_000})

        window = sample_contention_window(
            device_vram_gb=80.0,
            device=DEV,
            root_pid=1,
            account=_account,
            capture=lambda *a, **k: ContentionSnapshot(telemetry_available=True),
            sleep=lambda _s: None,
        )
        assert len(calls) == 5, "one accounting sample per contention tick"
        assert window.measurement_validity == "unstable_external_identity"

    def test_the_verdict_survives_the_probe_to_estimate_hop(self):
        """MUTATION TARGET: `extrapolate_probe` dropping the field.

        FOUND BY MUTATION — the first version of this suite missed it, and
        the mutant survived. It is the last hop and the one that matters:
        the window can compute a verdict and the probe result can carry it,
        and if the ESTIMATE does not, admission falls back to the
        conservative rule and a stable neighbour still cannot block. The
        whole PR would look complete and change nothing.

        This is the same defect class as PR D's three silent schema drops:
        a value produced, and silently absent at the consumer.
        """
        from core.runtime_control.probe import (
            ContentionSnapshot,
            ProbeCaps,
            ProbeResult,
            RealizedModelProperties,
            extrapolate_probe,
        )

        result = ProbeResult(
            status="ok",
            model_identity="candidate_x",
            realized=RealizedModelProperties(
                parameter_count=1_000,
                trainable_parameter_count=1_000,
                parameter_memory_gb=0.001,
                dtype="float32",
            ),
            setup_seconds=1.0,
            train_ms_per_step=20.0,
            train_ms_spread=(19.0, 21.0),
            inference_ms_per_batch=40.0,
            inference_ms_spread=(39.0, 41.0),
            # A neighbour IS present, and the window found it stable.
            concurrency_identity="foreign_contended",
            measurement_validity="valid_current_conditions",
            contention=ContentionSnapshot(telemetry_available=True),
            caps=ProbeCaps(),
            wall_seconds=10.0,
        )
        estimate = extrapolate_probe(
            result, train_steps=100, inference_batches=10, producer_identity="test@1.0.0"
        )

        assert estimate.measurement_validity == "valid_current_conditions"
        # And the consequence, which is the point of carrying it at all.
        assert estimate.blocking_eligible is True
