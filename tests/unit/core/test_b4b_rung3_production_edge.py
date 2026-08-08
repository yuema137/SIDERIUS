"""V21 PR B4b rung 3 — the production admission edge, end to end.

Rung 3's question is not "does the rule work" (rung 1) or "is the counter
real" (rung 2). It is: **does the production path actually carry a measured
peak into the armed threshold and act on it?**

This drives the real `resolve_request_probe` — the same entry point the
tuner calls — with a fake probe runner supplying a known peak. That is the
pattern `core/runtime_control/launch_guard.py` already uses to assert the
runtime-control chain of custody, and it exercises everything except the
model itself:

```text
REQUEST_PROBE
  -> resolve_request_probe (production)
  -> bounded probe runs exactly once
  -> observation persisted
  -> extrapolate_probe rebuilds the estimate, carrying peak_vram_gb
  -> RuntimeDecisionPolicy re-evaluated against the ARMED threshold
  -> terminal decision
```

The V19 wave-1 incident is why this is tested at the edge rather than at
the helpers: *"the estimator existed, the policy existed, the probe existed
— and none of them were on the production path"* (`launch_guard.py`). B3's
own Stage A finding was the same shape one level down: a correct rule that
nothing armed.

Design doc: ``docs/design/v21_priorities/pr_b_resource_budget_semantics.md``
Commit B4b rung 3.
"""

from __future__ import annotations

import pytest

from core.runtime_control.decision_policy import RuntimeBudget, RuntimeMode
from core.runtime_control.probe_lifecycle import ProbeRequest
from core.runtime_control.probe_wiring import resolve_request_probe

_FORMAL = RuntimeMode(phase="formal", candidate_stage="post_implementation")


def _probe_with_peak(peak_vram_gb: float | None):
    """A probe result shaped exactly like a real one, with a chosen peak."""
    from core.runtime_control.probe import (
        ContentionSnapshot,
        ProbeCaps,
        ProbeResult,
        RealizedModelProperties,
    )

    return ProbeResult(
        status="ok",
        model_identity="b4b_rung3",
        realized=RealizedModelProperties(
            parameter_count=1000,
            trainable_parameter_count=1000,
            parameter_memory_gb=0.001,
            dtype="float32",
        ),
        setup_seconds=0.01,
        train_ms_per_step=1.0,
        train_ms_spread=(0.9, 1.1),
        inference_ms_per_batch=1.0,
        inference_ms_spread=(0.9, 1.1),
        peak_vram_gb=peak_vram_gb,
        concurrency_identity="single_candidate_idle",
        contention=ContentionSnapshot(telemetry_available=True, foreign_compute_processes=0),
        caps=ProbeCaps(),
        wall_seconds=0.5,
    )


def _resolve(peak_vram_gb, *, vram_threshold_gb):
    calls: list[object] = []
    persisted: list[object] = []
    resolution = resolve_request_probe(
        request=ProbeRequest(model_identity="b4b_rung3", train_steps=10, inference_batches=2),
        # Time is generous so the VRAM dimension is the only thing under test.
        budget=RuntimeBudget(time_seconds=1_000_000.0, vram_gb=vram_threshold_gb),
        mode=_FORMAL,
        run_probe=lambda req: (calls.append(req), _probe_with_peak(peak_vram_gb))[1],
        persist=lambda result, req: (persisted.append(result), ("sha256:rung3",))[1],
    )
    return resolution, calls, persisted


class TestTheProductionEdgeCarriesTheMeasuredPeak:
    def test_a_measured_peak_above_the_armed_threshold_is_refused(self):
        """The whole point of B3, at the production entry point.

        Before Stage B this returned ALLOW for any peak, because
        `budget.vram_gb` was never supplied.
        """
        resolution, calls, persisted = _resolve(20.0, vram_threshold_gb=12.0)
        assert len(calls) == 1, "the bounded probe must run exactly once"
        assert persisted, "the observation must be persisted before it is decided on"
        assert resolution.decision.kind == "REJECT"
        assert any("measured peak VRAM" in r for r in resolution.decision.reasons)

    def test_a_measured_peak_below_the_threshold_is_admitted(self):
        resolution, _, _ = _resolve(4.0, vram_threshold_gb=12.0)
        assert resolution.decision.kind == "ALLOW"

    def test_the_same_peak_with_NO_threshold_is_admitted(self):
        """Pins the pre-B3 behaviour at the edge.

        This is what production did before Stage B, and asserting it here
        means the wiring is demonstrably the thing that changed the
        outcome — not a coincidence of the fixture.
        """
        resolution, _, _ = _resolve(20.0, vram_threshold_gb=None)
        assert resolution.decision.kind == "ALLOW"
        assert not any("VRAM" in r for r in resolution.decision.reasons)

    def test_a_probe_that_measures_no_peak_does_not_get_judged(self):
        """Missing evidence is not favourable evidence — it is no evidence."""
        resolution, _, _ = _resolve(None, vram_threshold_gb=12.0)
        assert resolution.decision.kind == "ALLOW"
        assert not any("VRAM" in r for r in resolution.decision.reasons)

    def test_the_decision_is_backed_by_probe_provenance(self):
        """A REJECT must be attributable to measured evidence.

        If this ever came back as a prior or a static source, the refusal
        would be a forecast blocking a candidate — S1 behaviour that S3
        explicitly does not authorise.
        """
        resolution, _, _ = _resolve(20.0, vram_threshold_gb=12.0)
        assert resolution.decision.evidence_provenance == "bounded_live_probe"
        assert resolution.probe_ran is True
        assert resolution.probe_status == "ok"

    @pytest.mark.parametrize(
        ("peak", "threshold", "expected"),
        [
            (12.0, 12.0, "ALLOW"),  # equality is admitted
            (12.001, 12.0, "REJECT"),  # strictly above
            (11.999, 12.0, "ALLOW"),
        ],
    )
    def test_the_boundary_at_the_edge(self, peak, threshold, expected):
        resolution, _, _ = _resolve(peak, vram_threshold_gb=threshold)
        assert resolution.decision.kind == expected


class TestTheOOMPathPreservesItsMeasurement:
    """A probe that OOMs still measured something; that must not be discarded.

    Added after mutation R3 survived, and classified honestly rather than
    hidden: on the OOM path the decision is already REJECT via
    `measured_failure` **before** the VRAM branch is reached, and the
    estimate is not returned to the caller — so dropping the peak changes
    no decision *today*. It is latent, not harmless: the docstring of
    `_unpriced_probe_estimate` promises it "carries the measured peak VRAM
    when there is one — the measurement that DOES exist — and nothing
    invented", and that promise is what B2/B0 rely on when an OOM is the
    only evidence a candidate ever produced.

    So this pins the documented contract directly rather than through a
    decision that cannot distinguish it.
    """

    def test_an_oom_probe_keeps_the_peak_it_managed_to_measure(self):
        from core.runtime_control.probe_lifecycle import _unpriced_probe_estimate

        result = _probe_with_peak(19.5).model_copy(
            update={"status": "oom", "error": "CUDA out of memory", "train_ms_per_step": None}
        )
        estimate = _unpriced_probe_estimate(result)
        assert estimate.peak_vram_gb == 19.5
        assert estimate.provenance == "bounded_live_probe"

    def test_an_oom_probe_with_no_measurement_invents_nothing(self):
        from core.runtime_control.probe_lifecycle import _unpriced_probe_estimate

        result = _probe_with_peak(None).model_copy(
            update={"status": "oom", "error": "CUDA out of memory", "train_ms_per_step": None}
        )
        assert _unpriced_probe_estimate(result).peak_vram_gb is None

    def test_the_oom_itself_is_what_refuses_the_candidate(self):
        """Not the threshold — the measured failure outranks it.

        Recorded because it bounds what B3 claims: an OOM is refused on the
        strength of the OOM, at a branch that runs before any budget
        comparison. Arming the threshold did not change this path.
        """
        resolution = resolve_request_probe(
            request=ProbeRequest(model_identity="b4b_rung3", train_steps=10, inference_batches=2),
            budget=RuntimeBudget(time_seconds=1_000_000.0, vram_gb=12.0),
            mode=_FORMAL,
            run_probe=lambda req: _probe_with_peak(19.5).model_copy(
                update={"status": "oom", "error": "CUDA OOM", "train_ms_per_step": None}
            ),
            persist=lambda result, req: ("sha256:rung3",),
        )
        assert resolution.decision.kind == "REJECT"
        assert not any("exceeds budget" in r for r in resolution.decision.reasons)


class TestTheEdgeStillHonoursTheTimeDimension:
    """B3 must not have displaced what already worked."""

    def test_an_over_time_candidate_is_still_caught(self):
        resolution, _, _ = _resolve(1.0, vram_threshold_gb=12.0)
        assert resolution.decision.kind == "ALLOW"
        # 10 steps x 1 ms is far under 1e6 s; now squeeze the time budget.
        tight = resolve_request_probe(
            request=ProbeRequest(model_identity="b4b_rung3", train_steps=10, inference_batches=2),
            budget=RuntimeBudget(time_seconds=1e-6, vram_gb=12.0),
            mode=_FORMAL,
            run_probe=lambda req: _probe_with_peak(1.0),
            persist=lambda result, req: ("sha256:rung3",),
        )
        assert tight.decision.kind == "REJECT"
        assert any("VRAM" not in r for r in tight.decision.reasons)
