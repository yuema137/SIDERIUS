"""Construct an inference measurement without training-only allocations."""

from __future__ import annotations

from typing import Any

from core.runtime_control.gpu_measurement_identity import build_realized_identity
from core.runtime_control.gpu_measurement_phases import CandidateComponents
from core.runtime_control.gpu_measurement_spec import GpuMeasurementSpec


def build_inference_components(
    spec: GpuMeasurementSpec, trace: Any = None, *, deadline_at: float | None = None
) -> CandidateComponents:
    """Build the model now; open bounded evaluation data in the work phase.

    The loss type may affect model construction, but inference creates no
    criterion, target tensor or optimizer. Missing evaluation transport is
    an unavailable measurement, never permission to substitute training data.
    """
    from agent.skills.training_skill.estimator import require_declared_segmentation_size
    from execute_tools.inference_model import construct_inference_model
    from execute_tools.model_input_dtype import resolve_inference_input_dtype
    from execute_tools.task_probe_batch import task_inference_probe_batches
    from ml_models.models_format_sandbox import LossConfig, TrainConfig

    checkpoint = spec.inference_checkpoint
    if checkpoint is not None and (deadline_at is None or spec.inference_binding is None):
        raise ValueError("checkpoint measurement requires its source binding and worker deadline")
    reference = spec.task_probe_data
    if reference is None or reference.evaluation_scope_payload is None:
        raise ValueError("Inference measurement requires a composed task evaluation scope")
    inference_batch_size = spec.inference_batch_size
    if inference_batch_size is None:
        raise ValueError("Inference measurement requires its production batch size")
    if spec.data_dir != reference.sampling.data_dir:
        raise ValueError("Inference measurement data root differs from the task probe root")
    model_type = spec.request.model_type
    loss_cfg = LossConfig(**spec.loss_config)
    train_cfg = TrainConfig(**spec.train_config)
    model, _ = construct_inference_model(
        model_type,
        spec.model_config_payload,
        model_io_contract=spec.model_io_contract,
        loss_type=loss_cfg.loss_type,
    )
    if trace is not None:
        trace.record(
            "after_model_construction",
            model=model,
            detail="no checkpoint" if checkpoint is None else "checkpoint load pending",
        )
    model = model.to(spec.device)
    if trace is not None:
        trace.record("after_model_to_device", synchronize=True, model=model)
    verified_checkpoint = None
    if checkpoint is not None:
        from execute_tools.inference_checkpoint import load_bound_inference_checkpoint

        assert deadline_at is not None
        model, verified_checkpoint = load_bound_inference_checkpoint(
            model, checkpoint, deadline_at=deadline_at
        )
        if trace is not None:
            trace.record("after_checkpoint_load", synchronize=True, model=model)
    model.eval()
    total = int(sum(p.numel() for p in model.parameters()))
    trainable = int(sum(p.numel() for p in model.parameters() if p.requires_grad))
    applicability = reference.segmentation_applicability
    seg = (
        require_declared_segmentation_size(
            model_type, spec.model_config_payload, consumer="inference measurement"
        )
        if applicability == "temporal"
        else None
    )
    realized = build_realized_identity(
        model_type=model_type,
        optimizer_type=train_cfg.optimizer_type,
        seg_size=seg,
        batch_size=train_cfg.batch_size,
        precision=str(next(model.parameters()).dtype).replace("torch.", ""),
        parameter_count=total,
        trainable_parameter_count=trainable,
        inference_batch_size=inference_batch_size,
        segmentation_applicability=applicability,
    )

    def batches(max_batches: int):
        return task_inference_probe_batches(
            reference, batch_size=inference_batch_size, max_batches=max_batches
        )

    return CandidateComponents(
        model=model,
        verified_checkpoint=verified_checkpoint,
        model_input=None,
        loss_target=None,
        optimizer=None,
        loss_fn=None,
        parameter_count=total,
        trainable_parameter_count=trainable,
        realized_identity=realized,
        inference_batches_factory=batches,
        inference_device=spec.device,
        inference_input_dtype=resolve_inference_input_dtype(model_type, spec.model_io_contract),
    )
