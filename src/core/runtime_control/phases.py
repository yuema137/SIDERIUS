"""
core/runtime_control/phases.py

Runtime-phase identifiers for the runtime-control framework (RT2-A).

Design: docs/design/runtime_estimation_and_watchdog.md §1.1/§2.4. The
component model is phase-first: every prediction, measurement, actual
runtime, and observation is keyed by one of these phases, and the total
is DERIVED from components. New scientific phases (data processing,
simulation, analysis, …) extend this vocabulary without changing the
framework.
"""

from __future__ import annotations

from typing import Literal

RuntimePhase = Literal[
    "setup",
    "training",
    # Step 07 / PR 07c C5 (Q-07c-4). The per-epoch R3 pass 07a added is real
    # wall-clock work that the runtime model did not price: 07a's Gate 2 saw 3
    # of 4 attempts killed by the watchdog INSIDE it, and the survivor spent
    # 9 s training against 26.45 s validating under a deadline built from the
    # 9 s alone. Left unpriced that is a BIAS, not merely lost attempts —
    # validation cost grows with model size, so large candidates die in
    # validation while small ones survive and the tuner learns a false
    # regularity.
    #
    # A phase of its own rather than a term folded into training, because
    # `calibration_key` embeds `f"phase={phase}"` (`observation_store.py:78`):
    # a new member creates a NEW key namespace and leaves every existing key
    # byte-identical, whereas widening training's meaning would silently
    # change the values stored under keys that already exist.
    "validation",
    "inference",
    "scoring",
    "orchestration",
]

RUNTIME_PHASES: tuple[RuntimePhase, ...] = (
    "setup",
    "training",
    "validation",
    "inference",
    "scoring",
    "orchestration",
)
