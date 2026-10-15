"""Terminal evidence shared by workflow execution and its callers."""

from collections.abc import Sequence

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput


def infrastructure_abort_reason(
    results: Sequence[HyperparamTuningOutput] | None,
) -> str | None:
    """Return the failed status when runtime evidence cannot be trusted.

    Candidate rejection and gate exhaustion are not infrastructure aborts.
    Callers must stop their campaign on this signal, even if earlier results
    contain valid scores. Retain the outputs for diagnosis before stopping.
    """
    for output in results or ():
        if getattr(output, "termination_reason", None) == "infrastructure_abort":
            return getattr(output, "status", None) or "infrastructure_abort"
    return None
