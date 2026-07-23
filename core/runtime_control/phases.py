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

RuntimePhase = Literal["setup", "training", "inference", "scoring", "orchestration"]

RUNTIME_PHASES: tuple[RuntimePhase, ...] = (
    "setup",
    "training",
    "inference",
    "scoring",
    "orchestration",
)
