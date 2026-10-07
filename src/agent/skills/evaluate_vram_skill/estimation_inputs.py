"""Project completed probes and registered objects into provider observations."""

from copy import deepcopy
from typing import Any

from torch import nn

from agent.skills.evaluate_vram_skill.registered_state import inventory_registered_state
from agent.skills.evaluate_vram_skill.structural_probe import ProbeResult
from core.preflight_observations import PhaseObservations
from ml_models.models_format_sandbox import TrainConfig


def observe_phase(
    probe: ProbeResult,
    *,
    model: nn.Module,
    batch_size: int,
    loss_module: nn.Module | None = None,
    training_config: dict[str, Any] | None = None,
) -> PhaseObservations:
    """Keep historical call counts separate from native state inventory."""
    original = deepcopy(training_config if training_config is not None else {})
    return PhaseObservations(
        phase=probe.mode,
        batch_size=batch_size,
        leaf_parameter_bytes=probe.model_forward.total_param_bytes,
        leaf_output_bytes_sum=probe.model_forward.forward_output_bytes_sum,
        leaf_output_bytes_max=probe.model_forward.forward_output_bytes_max,
        input_bytes=probe.input_bytes,
        output_bytes=probe.output_bytes,
        saved_tensor_bytes=probe.autograd_tape.total_saved_bytes if probe.autograd_tape else None,
        model_state=inventory_registered_state(model),
        loss_state=inventory_registered_state(loss_module) if loss_module is not None else None,
        optimizer_type=TrainConfig.model_validate(original).optimizer_type
        if probe.mode == "training"
        else None,
        training_config=original,
    )
