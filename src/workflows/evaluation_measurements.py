"""Whether the bound run declares evaluation measurements (#1296).

Reads the run's bound evaluation declaration snapshot (bound once by
``bind_run_task_composition`` and checked by the composition verification
guard); it does not reload the manifest or keep a second binding. A missing
binding means no request is emitted, and a measurement-declaring scoring child
then refuses rather than scoring without its measurements.
"""

from __future__ import annotations

from agent.evaluation_context import active_evaluation_prompt_context
from execute_tools.evaluation_spec import MeasurementComponent


def active_run_declares_measurements() -> bool:
    context = active_evaluation_prompt_context()
    return context is not None and any(
        isinstance(component, MeasurementComponent) for component in context.spec.components
    )
