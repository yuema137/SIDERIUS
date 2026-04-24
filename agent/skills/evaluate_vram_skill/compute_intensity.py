"""Compute-intensity cap — Phase 6.6 §3.10.

Phase 6.5 Stage 2 observed a ``cudaErrorLaunchTimeout`` on the RTX 5090 at a
``batch_size × segmentation_size`` product above the CUDA kernel watchdog
window. A config can fit in VRAM and still hang a kernel long enough to trip
the driver's timeout — crashing the attempt and, in the worst case, wedging
the host until it is reset.

This module installs a flat pre-flight refusal threshold on the intensity
product. No op-mix modelling, no device specialisation: it is a coarse
gate, not a wall-time predictor. Live detection and recovery stay in
Phase 6.8 (see §3.10.5).

Calibration (locked 2026-04-23 per user sign-off, §3.10.3)
---------------------------------------------------------
- Phase 6.5 Stage 2 failure point: ``batch_size=25, segmentation_size=40000``
  → product = 1,000,000.
- Safety margin (§3.10): 20%.
- → ``_MAX_BATCH_TIMESTEPS = 800_000``.

The threshold is a **design constant**, not a runtime tunable. Changing it
requires a version-controlled edit plus a regression test update. Invented
values are forbidden — the only legitimate refresh path is "observed
failure → documented margin → code + test update in one commit".

Principle 2 invariant
---------------------
This module contains no architecture-family strings. It operates on two
integers (``batch_size``, ``segmentation_size``) and returns ``int`` /
``bool`` / ``str`` — nothing else. The guardrail test
``tests/unit/guardrails/test_no_model_name_branches.py`` (A.12) enforces
this across the whole VRAM stack; the inline test in
``test_compute_intensity.py`` documents the invariant at the module.
"""
from __future__ import annotations

# ── Calibrated constant (Phase 6.5 Stage 2, 20% margin — §3.10.3) ──────────

_MAX_BATCH_TIMESTEPS: int = 800_000


# ── Primitive arithmetic ────────────────────────────────────────────────────

def compute_intensity(batch_size: int, segmentation_size: int) -> int:
    """Raw intensity product. Pure multiplication, no state.

    The product is the order-of-magnitude work per forward pass; the true
    cost depends on op mix (attention is quadratic in T; convs linear). The
    cap is intentionally coarse — see §3.10.4.
    """
    return batch_size * segmentation_size


# ── Acceptance predicate ────────────────────────────────────────────────────

def passes(batch_size: int, segmentation_size: int) -> bool:
    """``True`` iff the config sits **at or below** the heuristic cap.

    Uses ``<=`` — the boundary product exactly equal to the cap is accepted,
    and the test suite pins this explicitly at ``_MAX_BATCH_TIMESTEPS``.
    """
    return compute_intensity(batch_size, segmentation_size) <= _MAX_BATCH_TIMESTEPS


# ── Diagnostic message (consumed by killer_report §3.6 + wrapper §3.10.2) ──

def describe_violation(batch_size: int, segmentation_size: int) -> str:
    """Human-readable violation message.

    Names ``batch_size`` and ``segmentation_size`` verbatim — intensity is a
    *config-shape* problem, not an architecture problem, so the message
    names the dimensions the Proposer can actually tune. No layer names,
    no model-family terms.
    """
    product = compute_intensity(batch_size, segmentation_size)
    return (
        f"Current batch_size × segmentation_size = {batch_size} × "
        f"{segmentation_size} = {product:,}, which exceeds the safety limit "
        f"of {_MAX_BATCH_TIMESTEPS:,} (Phase 6.5 Stage 2 calibration, "
        f"§3.10.3). Reduce batch_size or segmentation_size to bring the "
        f"product at or below the cap."
    )
