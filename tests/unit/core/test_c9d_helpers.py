"""Shared fixture builders for the C9d suites.

Named ``test_*`` so it sits beside the suite that imports it; it contains
no tests of its own.
"""

from __future__ import annotations

from core.runtime_control.probe import (
    ContentionSnapshot,
    ProbeCaps,
    ProbeResult,
    RealizedModelProperties,
)


def fake_ok_probe(*, train_ms_per_step: float = 10.0) -> ProbeResult:
    """A clean probe result shaped exactly like a production one."""
    spread = (train_ms_per_step * 0.95, train_ms_per_step * 1.05)
    return ProbeResult(
        status="ok",
        model_identity="candidate",
        realized=RealizedModelProperties(
            parameter_count=1000,
            trainable_parameter_count=1000,
            parameter_memory_gb=0.001,
            dtype="float32",
        ),
        setup_seconds=0.01,
        train_ms_per_step=train_ms_per_step,
        train_ms_spread=spread,
        inference_ms_per_batch=20.0,
        inference_ms_spread=(19.0, 21.0),
        concurrency_identity="single_candidate_idle",
        contention=ContentionSnapshot(telemetry_available=True, foreign_compute_processes=0),
        caps=ProbeCaps(),
        wall_seconds=0.5,
    )
