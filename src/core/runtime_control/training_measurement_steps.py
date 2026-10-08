"""Bound training checks optimizer identity without requiring parameter motion."""

from typing import Any

from core.runtime_control.gpu_measurement_spec import TrainingStepEvidence


def verify_optimizer_ownership(components: Any, counters: dict[str, Any]) -> None:
    """Record one construction fact; repeated passes retain connected-call counts."""
    model_parameters = {id(parameter) for parameter in components.model.parameters()}
    optimizer_parameters = {
        id(parameter)
        for group in components.optimizer.param_groups
        for parameter in group["params"]
    }
    previous = counters.get("training_steps")
    evidence = TrainingStepEvidence(
        optimizer_matches_model_parameters=model_parameters == optimizer_parameters,
        connected_backward_calls=previous.connected_backward_calls if previous else 0,
    )
    counters["training_steps"] = evidence
    if not evidence.optimizer_matches_model_parameters:
        raise ValueError("bound training optimizer parameters differ from the measured model")
