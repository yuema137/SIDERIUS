"""Test-only allocations for successful pipelines using real CPU subprocesses.

A reference invocation starts interface, parameter-validation and execution
workers. These behavior witnesses need cold-start and filesystem headroom;
precise deadline/refusal witnesses declare their own small allocations.
"""

from typing import Final

REAL_WORKER_TIMEOUT_SECONDS: Final[float] = 30.0
REAL_PIPELINE_BUDGET_SECONDS: Final[float] = 120.0
