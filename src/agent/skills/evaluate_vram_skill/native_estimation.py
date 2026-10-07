"""Native static byte arithmetic using registered resident and trainable state.

Activation proxies and calibrated residuals retain their existing meanings.
Saved tensors can overlap resident state; these sums are structural estimates,
not exact live-allocation measurements or universal upper bounds.
"""

from __future__ import annotations

from agent.skills.evaluate_vram_skill.overhead import (
    cuda_context_bytes,
    cudnn_backward_workspace_bytes,
    training_overhead_bytes,
)
from core.preflight_observations import PhaseEstimate, PhaseObservations, RegisteredStateInventory


def _available_state(state: RegisteredStateInventory, owner: str) -> tuple[int, int, int]:
    if state.status != "available":
        raise ValueError(f"Native preflight needs {owner} registered state: {state.reason}")
    assert state.parameter_bytes is not None
    assert state.trainable_parameter_bytes is not None
    assert state.buffer_bytes is not None
    return state.parameter_bytes, state.trainable_parameter_bytes, state.buffer_bytes


def estimate_native_phase(observations: PhaseObservations) -> PhaseEstimate:
    """Price observations without changing execution configuration or admission."""
    params, trainable, buffers = _available_state(observations.model_state, "model")
    breakdown = {"param_bytes": params, "buffer_bytes": buffers}
    if observations.phase == "training":
        assert observations.loss_state is not None
        assert observations.saved_tensor_bytes is not None
        assert observations.optimizer_type is not None
        loss_params, loss_trainable, loss_buffers = _available_state(
            observations.loss_state, "loss"
        )
        breakdown.update(
            {
                "loss_param_bytes": loss_params,
                "loss_buffer_bytes": loss_buffers,
                "autograd_tape_bytes": observations.saved_tensor_bytes,
                "input_bytes": observations.input_bytes,
                "output_bytes": observations.output_bytes,
                "training_overhead_bytes": training_overhead_bytes(
                    trainable, observations.optimizer_type
                ),
                # Production optimizer owns model.parameters(), but backward can
                # also allocate gradients for trainable parameters in the loss.
                "loss_gradient_bytes": loss_trainable,
                "cuda_context_bytes": cuda_context_bytes(),
                "cudnn_backward_bytes": cudnn_backward_workspace_bytes(),
            }
        )
        diagnostic = sum(breakdown.values())
        admission = diagnostic
        estimator = "training_registered_state_v1"
    else:
        breakdown.update(
            {
                "input_bytes": observations.input_bytes,
                "max_output_bytes": max(
                    observations.output_bytes, observations.leaf_output_bytes_max
                ),
                "cuda_context_bytes": cuda_context_bytes(),
            }
        )
        diagnostic = sum(breakdown.values())
        admission = params + buffers + observations.leaf_output_bytes_sum + cuda_context_bytes()
        estimator = "inference_registered_state_v1"
    return PhaseEstimate(
        phase=observations.phase,
        admission_bytes=admission,
        diagnostic_bytes=diagnostic,
        estimator=estimator,
        breakdown=breakdown,
    )
