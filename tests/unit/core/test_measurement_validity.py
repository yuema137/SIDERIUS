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

    def test_a_neighbour_arriving_mid_window_does_NOT_invalidate(self):
        """RE-GROUNDED 2026-08-06. This previously asserted
        `unstable_external_identity`. External PID-set change is an
        OBSERVATION, not a defect in the measurement — the candidate's own
        demand is still separable, so the measurement is still trustworthy.
        """
        window = [
            _snap(others={999: 5_000}),
            _snap(others={999: 5_000}),
            _snap(others={999: 5_000, 1234: 2_000}),
        ]
        assert classify_measurement_validity(window)[0] == "valid_current_conditions"

    def test_a_neighbour_leaving_mid_window_does_NOT_invalidate(self):
        """Departure is equally an observation."""
        window = [_snap(others={999: 5_000}), _snap(others={999: 5_000}), _snap(others={})]
        assert classify_measurement_validity(window)[0] == "valid_current_conditions"

    def test_a_neighbour_that_restarts_does_NOT_invalidate(self):
        """MUTATION TARGET: reintroducing a PID-constancy requirement.

        A restarted neighbour changes the PID set and nothing about whether
        the candidate's demand can be measured.
        """
        window = [_snap(others={999: 5_000}), _snap(others={1000: 5_000})]
        assert classify_measurement_validity(window)[0] == "valid_current_conditions"

    def test_growing_unattributed_memory_is_an_ATTRIBUTION_failure(self):
        """RE-GROUNDED: the verdict is `candidate_attribution_failed`, and the
        reason names attribution rather than "a neighbour grew".

        Growth in UNATTRIBUTED bytes invalidates because those bytes belong
        to no enumerated process, so candidate demand can no longer be
        separated — not because the device got busier.
        """
        window = [_snap(unattributed=500), _snap(unattributed=500), _snap(unattributed=9_000)]
        validity, reasons = classify_measurement_validity(window)
        assert validity == "candidate_attribution_failed"
        assert "separated" in reasons[0]

    def test_a_neighbour_growing_its_OWN_attributed_memory_is_valid(self):
        """The distinction that matters: attributed growth is a neighbour
        being busy; unattributed growth is evidence going missing."""
        window = [_snap(others={999: 1_000}), _snap(others={999: 20_000})]
        assert classify_measurement_validity(window)[0] == "valid_current_conditions"

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
        ["candidate_attribution_failed", "sampling_incomplete", "probe_lifecycle_incomplete"],
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
        [
            "candidate_attribution_failed",
            "device_identity_unavailable",
            "sampling_incomplete",
            "probe_lifecycle_incomplete",
            "measurement_invariant_failed",
        ],
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
        # RE-GROUNDED: a changing external PID set is an observation, so the
        # measurement stays valid. The property under test here is that
        # accounting is sampled EVERY tick, which the call count proves.
        assert window.measurement_validity == "valid_current_conditions"

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


class TestTheProductionChainIsConnected:
    """Reachability for the LAST link: the orchestrator must actually pass a
    device identity down, or every real run silently keeps the conservative
    rule and PR C changes nothing in production.

    This is the same failure the `extrapolate_probe` mutation exposed, one
    hop further out — and it cannot be caught by any unit test of the
    boundary itself, because the boundary would be behaving correctly on the
    evidence it was handed.
    """

    def test_run_bounded_probe_forwards_the_identity_to_the_sampler(self):
        """MUTATION TARGET: dropping `device_identity` from the forward."""
        from core.runtime_control.probe import ProbeCaps, run_bounded_probe

        seen: dict = {}

        def _sampler(**kwargs):
            seen.update(kwargs)
            return type(
                "W",
                (),
                {
                    "classification": "single_candidate_idle",
                    "samples": (),
                    "reasons": (),
                    "measurement_validity": "valid_current_conditions",
                    "raw_telemetry": lambda self: {},
                },
            )()

        class _Executors:
            def __getattr__(self, _name):
                raise RuntimeError("probe body not exercised by this test")

        try:
            run_bounded_probe(
                model_identity="c",
                executors=_Executors(),
                caps=ProbeCaps(),
                device_vram_gb=80.0,
                contention_window=_sampler,
                device_identity=DEV,
            )
        except Exception:
            # The probe body is irrelevant here; the window call is not.
            pass

        assert seen.get("device") == DEV, (
            "run_bounded_probe did not pass the device identity to the "
            "contention sampler, so no occupancy window is ever built"
        )

    def test_the_tuner_passes_the_device_identity_it_resolved(self):
        """MUTATION TARGET: the orchestrator resolving an identity and then
        not passing it.

        Structural, because reaching this line needs a real chain round.
        Checked per CALL NODE via AST rather than by substring: a text
        search would pass on the `device_identity=` that appears in the
        sandbox construction nearby.
        """
        import ast
        from pathlib import Path

        tuner = (
            Path(__file__).resolve().parents[3]
            / "nodes"
            / "ml_hyperparameter_tune_agent"
            / "ml_hyperparameter_tune_agent.py"
        )
        tree = ast.parse(tuner.read_text(encoding="utf-8"))
        calls = 0
        undeclared: list[int] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name != "_resolve_time_check_probe_request":
                continue
            calls += 1
            if "device_identity" not in {kw.arg for kw in node.keywords}:
                undeclared.append(node.lineno)

        assert calls >= 1, "the probe-resolution helper is no longer called"
        assert undeclared == [], (
            f"_resolve_time_check_probe_request called without device_identity "
            f"at lines {undeclared}; the probe would then build no occupancy "
            f"window and every measurement would fall back to the "
            f"conservative pre-PR-C rule"
        )


class TestExternalActivityIsObservationOnly:
    """Operator ruling, 2026-08-06: external GPU activity is CONTEXT.

    Presence, non-registration, PID-set change, memory fluctuation and
    burstiness are facts about the environment. None of them may decide
    validity, readiness or admission. Registration is provenance only —
    given identical measured facts, a registered and an unregistered
    neighbour must produce identical outcomes.
    """

    @staticmethod
    def _observe(window, registered=()):
        from core.runtime_control.measurement_validity import summarise_external_activity

        return summarise_external_activity(window, registered_pids=registered)

    def test_no_external_workload_is_recorded_as_absent(self):
        obs = self._observe([_snap() for _ in range(3)])
        assert obs.activity == "absent"
        assert obs.present is False
        assert classify_measurement_validity([_snap() for _ in range(3)])[0] == (
            "valid_current_conditions"
        )

    def test_a_stable_unregistered_workload_is_recorded_and_still_valid(self):
        window = [_snap(others={999: 5_000}, own={111: 1_000}) for _ in range(4)]
        obs = self._observe(window)
        assert obs.activity == "stable"
        assert obs.unregistered_pids == (999,)
        assert obs.registered_pids == ()
        assert obs.pid_set_changed is False
        assert classify_measurement_validity(window)[0] == "valid_current_conditions"

    def test_a_variable_memory_workload_is_recorded_and_still_valid(self):
        """MUTATION TARGET: mapping memory variation to invalidity."""
        window = [_snap(others={999: mib}) for mib in (2_000, 18_000, 5_000, 12_000)]
        obs = self._observe(window)
        assert obs.activity == "variable"
        assert obs.external_mib_min == 2_000
        assert obs.external_mib_max == 18_000
        assert obs.external_mib_latest == 12_000
        assert classify_measurement_validity(window)[0] == "valid_current_conditions"

    def test_a_changing_pid_set_is_recorded_and_still_valid(self):
        """MUTATION TARGET: reintroducing a PID-constancy requirement."""
        window = [_snap(others={999: 5_000}), _snap(others={1234: 5_000})]
        obs = self._observe(window)
        assert obs.pid_set_changed is True
        assert obs.activity == "variable"
        assert set(obs.unregistered_pids) == {999, 1234}
        assert classify_measurement_validity(window)[0] == "valid_current_conditions"

    def test_registration_changes_labels_only_not_outcomes(self):
        """MUTATION TARGET: privileging a registered peer.

        THE property the old bootstrap gate violated: it admitted
        `pairwise_expected_peer` and refused an identical unregistered
        process. Same facts must give the same verdict.
        """
        window = [_snap(others={999: 5_000}) for _ in range(3)]

        unregistered = self._observe(window)
        registered = self._observe(window, registered=(999,))

        # Labels differ...
        assert unregistered.unregistered_pids == (999,)
        assert registered.registered_pids == (999,)
        assert registered.unregistered_pids == ()
        # ...and nothing else does.
        assert unregistered.activity == registered.activity
        assert unregistered.external_mib_max == registered.external_mib_max
        assert classify_measurement_validity(window)[0] == "valid_current_conditions"

    def test_unreadable_telemetry_is_unknown_not_absent(self):
        """A gap is not an empty device."""
        assert self._observe([_snap(available=False)]).activity == "unknown"
        assert self._observe([]).activity == "unknown"


class TestIntegrityFailuresSurvive:
    """Validity was RE-GROUNDED, not narrowed: every genuine
    measurement-integrity failure remains grounds for invalidity."""

    def test_missing_candidate_attribution_is_invalid(self):
        from core.runtime_control.gpu_accounting import GpuAccountingSnapshot

        blind = GpuAccountingSnapshot(
            device=DEV,
            telemetry_available=True,
            device_used_mib=10_000,
            device_total_mib=81_920,
            own_tree_mib=None,  # the candidate's own demand is unknown
            other_mib=10_000,
            other_process_count=1,
            per_pid_total_mib=10_000,
            unattributed_mib=0,
            accounting_skew_mib=0,
        )
        validity, reasons = classify_measurement_validity([blind])
        assert validity == "candidate_attribution_failed"
        assert "separated" in reasons[0]

    def test_a_window_spanning_two_devices_is_invalid(self):
        from core.runtime_control.gpu_accounting import DeviceIdentity

        other = DeviceIdentity(uuid="GPU-zzzz", physical_index=1)
        a = _snap()
        b = _snap().model_copy(update={"device": other})
        validity, reasons = classify_measurement_validity([a, b])
        assert validity == "device_identity_unavailable"
        assert "one device" in reasons[0]

    def test_incomplete_sampling_is_invalid(self):
        assert classify_measurement_validity([_snap(), _snap(available=False)])[0] == (
            "sampling_incomplete"
        )

    def test_no_retired_presence_reason_can_be_produced(self):
        """MUTATION TARGET: reintroducing a retired verdict.

        Sweeps the shapes that used to produce one — arriving, departing and
        restarting neighbours, and fluctuating attributed memory — and
        asserts none of them yields a retired reason.
        """
        from core.runtime_control.measurement_validity import RETIRED_PRESENCE_REASONS

        shapes = [
            [_snap(others={1: 100}), _snap(others={1: 100, 2: 100})],
            [_snap(others={1: 100}), _snap(others={})],
            [_snap(others={1: 100}), _snap(others={2: 100})],
            [_snap(others={1: 100}), _snap(others={1: 30_000})],
        ]
        for window in shapes:
            verdict = classify_measurement_validity(window)[0]
            assert verdict not in RETIRED_PRESENCE_REASONS, verdict
