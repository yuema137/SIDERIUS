"""Test-only allocations for successful pipelines using real CPU subprocesses.

A reference invocation starts interface, parameter-validation and execution
workers. These behavior witnesses need cold-start and filesystem headroom;
precise deadline/refusal witnesses declare their own small allocations.

The values only bound a failure: a passing run never waits for them. They hold
under host load (#1578: CI at load average ~40 ran shards 4-6x slower, and the
former 120 s / 30 s expired in the cooperative deadline at synthesis), so a
behavior verdict never depends on wall-clock speed.
"""

from typing import Final

REAL_WORKER_TIMEOUT_SECONDS: Final[float] = 120.0
REAL_PIPELINE_BUDGET_SECONDS: Final[float] = 600.0
