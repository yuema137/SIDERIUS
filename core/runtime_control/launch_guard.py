"""C9d — launch invariant and behavioral self-test for runtime control.

Runs at startup, BEFORE any LLM call or scientific trajectory mutation.

The point is not to check that classes exist. Existence was true
throughout the V19 wave-1 incident: the estimator existed, the policy
existed, the probe existed — and none of them were on the production
path. This guard therefore EXERCISES the lifecycle end to end through
the same entry point production uses, with an injected fake probe
runner, and asserts that the chain of custody actually executes:

```text
REQUEST_PROBE
  -> the bounded probe is invoked (exactly once)
  -> the observation is persisted
  -> the estimate is rebuilt from the measurement
  -> the policy is re-evaluated
  -> a terminal decision (ALLOW / REJECT / ABORT) is reached
```

A guard that passed while the production path was unreachable would be
worse than no guard, so the self-test calls
`probe_wiring.resolve_request_probe` — the function the tuner calls —
rather than reimplementing the sequence.

Cost: no GPU, no network, no LLM, no filesystem outside a temp dir.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from core.runtime_control.decision_policy import RuntimeBudget, RuntimeMode
from core.runtime_control.estimator import shared_runtime_components


class LaunchGuardFailure(RuntimeError):
    """The runtime-control subsystem is not safe to launch on."""


class LaunchGuardReport(BaseModel):
    """What the guard proved, for the run manifest."""

    model_config = ConfigDict(frozen=True)

    estimator_identity: str
    policy_identity: str
    checks: tuple[str, ...] = ()
    probe_runner_available: bool = False
    probe_runner_detail: str = ""
    elapsed_seconds: float = Field(default=0.0, ge=0.0)


def run_launch_self_test(*, require_probe_runner: bool) -> LaunchGuardReport:
    """Exercise the runtime-control lifecycle; raise on any breakage.

    Args:
        require_probe_runner: True for a real production launch — the
            environment must be able to build a REAL bounded-probe runner
            (CUDA + dataset). False for pseudo/CPU launches, where the
            wiring is still exercised with a fake runner but a missing
            real one is not fatal.
    """
    import time

    started = time.monotonic()
    checks: list[str] = []

    estimator, policy = shared_runtime_components()
    if shared_runtime_components()[1] is not policy:
        raise LaunchGuardFailure("the shared factory returned two different policies")
    checks.append("shared estimator + policy resolved once per process")

    _assert_static_cannot_block(policy)
    checks.append("static evidence cannot block (advisory only)")

    _assert_measured_can_block(policy)
    checks.append("measured evidence retains blocking authority")

    _assert_formal_prior_requests_a_probe(policy)
    checks.append("formal decision on a prior returns REQUEST_PROBE")

    _assert_request_probe_resolves()
    checks.append("REQUEST_PROBE resolves through the production entry point")

    _assert_probe_runs_exactly_once()
    checks.append("probe runs exactly once; a repeat request ABORTs")

    _assert_infrastructure_failure_aborts()
    checks.append("probe infrastructure failure ABORTs (no static fallback)")

    available, detail = _probe_runner_availability()
    if require_probe_runner and not available:
        raise LaunchGuardFailure(
            "this launch requires a real bounded-probe runner and the "
            f"environment cannot build one: {detail}. A formal runtime "
            "decision would have no measured evidence to resolve to."
        )
    checks.append(f"probe runner availability checked ({detail})")

    return LaunchGuardReport(
        estimator_identity=estimator.identity,
        policy_identity=policy.identity,
        checks=tuple(checks),
        probe_runner_available=available,
        probe_runner_detail=detail,
        elapsed_seconds=round(time.monotonic() - started, 4),
    )


# ── individual behavioral assertions ────────────────────────────────────────


def _static_estimate():
    from core.runtime_control.estimate_types import make_estimate

    return make_estimate(
        provenance="static_uncalibrated", confidence="low", expected_seconds=10_000.0
    )


def _measured_estimate():
    from core.runtime_control.estimate_types import make_estimate

    return make_estimate(
        provenance="real_training_verification",
        confidence="high",
        expected_seconds=10_000.0,
        verification_passed=True,
        steady_state=True,
        concurrency_identity="single_candidate_idle",
    )


def _assert_static_cannot_block(policy) -> None:
    decision = policy.decide(
        _static_estimate(),
        RuntimeBudget(time_seconds=60.0),
        RuntimeMode(phase="trial", candidate_stage="post_implementation"),
    )
    if decision.kind in ("REJECT", "ABORT"):
        raise LaunchGuardFailure(
            f"static evidence produced {decision.kind} — the wave-1 failure mode "
            f"is live again: {decision.reasons}"
        )


def _assert_measured_can_block(policy) -> None:
    decision = policy.decide(
        _measured_estimate(),
        RuntimeBudget(time_seconds=60.0),
        RuntimeMode(phase="formal", candidate_stage="post_implementation"),
    )
    if decision.kind != "REJECT":
        raise LaunchGuardFailure(
            f"measured evidence over budget produced {decision.kind}, not REJECT — "
            "the subsystem has lost its blocking authority"
        )


def _assert_formal_prior_requests_a_probe(policy) -> None:
    decision = policy.decide(
        _static_estimate(),
        RuntimeBudget(time_seconds=1_000_000.0),
        RuntimeMode(phase="formal", candidate_stage="post_implementation"),
        evidence_channel="probe_absent",
    )
    if decision.kind != "REQUEST_PROBE":
        raise LaunchGuardFailure(
            f"a formal decision with no probe produced {decision.kind}, not "
            "REQUEST_PROBE — a formal decision could rest on a prior"
        )


def _fake_ok_probe():
    """A probe result shaped exactly like a real one, with fixed numbers."""
    from core.runtime_control.probe import (
        ContentionSnapshot,
        ProbeCaps,
        ProbeResult,
        RealizedModelProperties,
    )

    return ProbeResult(
        status="ok",
        model_identity="launch_guard_self_test",
        realized=RealizedModelProperties(
            parameter_count=1000,
            trainable_parameter_count=1000,
            parameter_memory_gb=0.001,
            dtype="float32",
        ),
        setup_seconds=0.01,
        train_ms_per_step=10.0,
        train_ms_spread=(9.0, 11.0),
        inference_ms_per_batch=20.0,
        inference_ms_spread=(19.0, 21.0),
        concurrency_identity="single_candidate_idle",
        contention=ContentionSnapshot(telemetry_available=True, foreign_compute_processes=0),
        caps=ProbeCaps(),
        wall_seconds=0.5,
    )


def _self_test_request():
    from core.runtime_control.probe_lifecycle import ProbeRequest

    return ProbeRequest(
        model_identity="launch_guard_self_test", train_steps=10, inference_batches=2
    )


def _assert_request_probe_resolves() -> None:
    """The full production edge, with a fake runner and an in-memory sink."""
    from core.runtime_control.probe_wiring import resolve_request_probe

    calls: list[object] = []
    persisted: list[object] = []

    resolution = resolve_request_probe(
        request=_self_test_request(),
        budget=RuntimeBudget(time_seconds=600.0),
        mode=RuntimeMode(phase="formal", candidate_stage="post_implementation"),
        run_probe=lambda req: (calls.append(req), _fake_ok_probe())[1],
        persist=lambda result, req: (persisted.append(result), ("sha256:selftest",))[1],
    )
    if len(calls) != 1:
        raise LaunchGuardFailure(f"the probe ran {len(calls)} times, expected exactly 1")
    if not persisted:
        raise LaunchGuardFailure("the probe observation was never persisted")
    if resolution.decision.kind != "ALLOW":
        raise LaunchGuardFailure(
            f"a clean in-budget probe resolved to {resolution.decision.kind}, not ALLOW: "
            f"{resolution.decision.reasons}"
        )
    if resolution.estimate is None or resolution.estimate.provenance != "bounded_live_probe":
        raise LaunchGuardFailure(
            "the estimate was not rebuilt from the probe measurement — the "
            "measurement was obtained and then not consumed"
        )
    if resolution.observation_ids != ("sha256:selftest",):
        raise LaunchGuardFailure("persisted observation ids did not reach the resolution")


def _assert_probe_runs_exactly_once() -> None:
    from core.runtime_control.probe_lifecycle import ProbeResolver

    calls: list[object] = []
    _, policy = shared_runtime_components()
    resolver = ProbeResolver(
        policy=policy, run_probe=lambda req: (calls.append(req), _fake_ok_probe())[1]
    )
    args = dict(
        budget=RuntimeBudget(time_seconds=600.0),
        mode=RuntimeMode(phase="formal", candidate_stage="post_implementation"),
    )
    resolver.resolve(_self_test_request(), **args)  # type: ignore[arg-type]
    repeat = resolver.resolve(_self_test_request(), **args)  # type: ignore[arg-type]
    if len(calls) != 1:
        raise LaunchGuardFailure(
            f"a repeated REQUEST_PROBE re-ran the probe ({len(calls)} runs) — an "
            "unresolved probe loop is possible"
        )
    if repeat.decision.kind != "ABORT":
        raise LaunchGuardFailure(
            f"a repeated REQUEST_PROBE resolved to {repeat.decision.kind}, not ABORT"
        )


def _assert_infrastructure_failure_aborts() -> None:
    from core.runtime_control.probe_lifecycle import ProbeInfrastructureError
    from core.runtime_control.probe_wiring import resolve_request_probe

    def _broken(_request):
        raise ProbeInfrastructureError("launch self-test: simulated channel failure")

    resolution = resolve_request_probe(
        request=_self_test_request(),
        budget=RuntimeBudget(time_seconds=600.0),
        mode=RuntimeMode(phase="formal", candidate_stage="post_implementation"),
        run_probe=_broken,
        persist=None,
    )
    if resolution.decision.kind != "ABORT":
        raise LaunchGuardFailure(
            f"a broken probe channel resolved to {resolution.decision.kind}, not "
            "ABORT — the run could fall back to a prior"
        )


def _probe_runner_availability() -> tuple[bool, str]:
    """Can this environment build a REAL bounded-probe runner?"""
    from core.runtime_control.probe_wiring import probe_runner_availability

    return probe_runner_availability()
