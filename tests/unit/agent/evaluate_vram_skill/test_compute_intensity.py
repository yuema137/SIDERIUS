"""Unit tests for agent/skills/evaluate_vram_skill/compute_intensity.py.

Phase 6.6 §3.10. Pure-Python arithmetic — no torch, no CUDA, no filesystem.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agent.skills.evaluate_vram_skill import compute_intensity as ci
from agent.skills.evaluate_vram_skill.compute_intensity import (
    _MAX_BATCH_TIMESTEPS,
    compute_intensity,
    describe_violation,
    passes,
)


# ── Calibrated constant (regression against §3.10.3 sign-off) ───────────────

def test_cap_matches_calibration():
    """800,000 = Phase 6.5 Stage 2 failure point (1,000,000) × 20% margin.
    Changing this constant is a version-controlled edit per §3.10.3."""
    assert _MAX_BATCH_TIMESTEPS == 800_000


# ── Primitive arithmetic ────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "B, T",
    [(1, 1), (4, 40000), (25, 40000), (1, 800_000), (1000, 1000), (0, 99999)],
)
def test_compute_intensity_is_product(B, T):
    assert compute_intensity(B, T) == B * T


def test_compute_intensity_is_pure():
    """No hidden state — calling twice returns the same answer."""
    assert compute_intensity(10, 20_000) == compute_intensity(10, 20_000)


# ── Acceptance predicate: below / at / above the cap ───────────────────────

@pytest.mark.parametrize(
    "B, T",
    [
        (1, 1),
        (1, 40_000),
        (10, 40_000),     # 400k
        (20, 40_000),     # 800k — exactly the cap, <= accepts
        (4, 100_000),     # 400k
    ],
)
def test_passes_at_or_below_cap(B, T):
    assert passes(B, T) is True


def test_passes_at_exact_boundary_accepts():
    """`<=` not `<`: exactly the cap is accepted. Pin this explicitly so a
    future edit to `<` trips a test instead of silently tightening the gate."""
    assert passes(1, _MAX_BATCH_TIMESTEPS) is True
    assert passes(_MAX_BATCH_TIMESTEPS, 1) is True
    # Other factorisations that land exactly on the cap:
    assert passes(800, 1000) is True     # 800 * 1000 == 800_000
    assert passes(100, 8000) is True     # 100 * 8000 == 800_000


@pytest.mark.parametrize(
    "B, T",
    [
        (25, 40_000),   # 1,000,000 — the actual Phase 6.5 Stage 2 failure
        (21, 40_000),   # 840,000 — just over cap
        (_MAX_BATCH_TIMESTEPS + 1, 1),
        (1, _MAX_BATCH_TIMESTEPS + 1),
    ],
)
def test_passes_above_cap_rejects(B, T):
    assert passes(B, T) is False


def test_passes_at_stage2_failure_point_rejects():
    """Regression: the exact (B=25, T=40000) that tripped cudaErrorLaunchTimeout
    must fail the gate. If this test passes, the cap has drifted above the
    observed failure point — the calibration is broken."""
    assert passes(25, 40_000) is False


# ── Violation message ───────────────────────────────────────────────────────

def test_describe_violation_names_dimensions_verbatim():
    """The message names config levers the Proposer can actually tune."""
    msg = describe_violation(25, 40_000)
    assert "batch_size" in msg
    assert "segmentation_size" in msg


def test_describe_violation_includes_product_and_cap():
    """The Proposer needs to see both the observed value and the limit."""
    msg = describe_violation(25, 40_000)
    # Product appears (comma-separated or plain):
    assert "1,000,000" in msg or "1000000" in msg
    # Cap appears:
    assert "800,000" in msg or "800000" in msg


def test_describe_violation_suggests_a_reduction():
    msg = describe_violation(25, 40_000).lower()
    assert "reduce" in msg
    # Both levers surfaced — the Proposer should see it has two options:
    assert "batch_size" in msg and "segmentation_size" in msg


def test_describe_violation_has_no_architecture_names():
    """Principle 2: intensity is a config-shape problem, not an architecture
    problem. The message must name dimensions only — never a model family,
    layer type, or op class."""
    msg = describe_violation(25, 40_000).lower()
    for banned in [
        "wavenet", "punet", "fcnet", "transformer", "rnn",
        "attention", "conv", "unet", "lstm",
    ]:
        assert banned not in msg, (
            f"architecture term {banned!r} leaked into violation message"
        )


# ── Principle 2 module-source spot-check ───────────────────────────────────

def test_module_source_has_no_architecture_literals():
    """Spot-check that this module's own source contains no model-family
    string literals. The full guardrail test (A.12) covers the whole tree;
    this one documents the invariant inline so a future edit to
    compute_intensity.py that sneaks in a model branch fails close to the edit."""
    source = Path(ci.__file__).read_text().lower()
    for banned in ["wavenet", "punet", "fcnet", "transformer", "rnn"]:
        assert f'"{banned}"' not in source, f"architecture literal {banned!r} found"
        assert f"'{banned}'" not in source, f"architecture literal {banned!r} found"
