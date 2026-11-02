"""Synthetic CPU predictions persisted by the bound task's ordinary codec.

These outputs exercise transport and Health, not a learned scientific model.
No task identifiers, supervision values or Health thresholds choose predictions.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sized
from pathlib import Path

import torch

from agent.schemas.model_io_contract import AxisRole, ModelIOContract
from agent.skills.model_io_probe_skill import ProbeConstructionError
from agent.skills.model_output_geometry import resolve_output_shape
from core.generated_artifact_name import validate_generated_artifact_name
from execute_tools.generic_inference import run_generic_inference
from execute_tools.model_input_dtype import resolve_contract_input_dtype
from execute_tools.task_data_path import (
    DeliverableWriteRequest,
    EvalMaterializationParams,
    TaskDataPath,
    active_task_data_path,
)
from workflows.task_config import run_bound_model_io_contract


class PseudoEvidenceUnsupported(ValueError):
    """The declared task cannot supply synthetic inference evidence."""


class SyntheticPredictionModel(torch.nn.Module):
    """Generate deterministic declared-shape outputs without inspecting labels."""

    def __init__(self, contract: ModelIOContract) -> None:
        super().__init__()
        self.contract = contract
        self.offset = 0
        dtype = getattr(torch, contract.output.dtype.canonical, None)
        if not isinstance(dtype, torch.dtype):
            raise PseudoEvidenceUnsupported("Declared output dtype has no torch representation")
        self.output_dtype = dtype

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        try:
            shape = resolve_output_shape(
                self.contract, self.contract.legacy_output_type, inputs.shape
            )
        except ProbeConstructionError as exc:
            raise PseudoEvidenceUnsupported(str(exc)) from exc
        class_axis = next(
            (i for i, axis in enumerate(self.contract.output.axes) if axis.role is AxisRole.CLASS),
            None,
        )
        if class_axis is None:
            if not self.output_dtype.is_floating_point:
                raise PseudoEvidenceUnsupported(
                    "Continuous pseudo outputs require a floating dtype"
                )
            count = math.prod(shape)
            values = (torch.arange(count) + self.offset) % 257
            self.offset += count
            return (values / 128 - 1).to(self.output_dtype).reshape(shape)
        indices_shape = list(shape)
        indices_shape[class_axis] = 1
        count = math.prod(indices_shape)
        indices = ((torch.arange(count) + self.offset) % shape[class_axis]).reshape(indices_shape)
        self.offset += count
        logits = torch.zeros(shape, dtype=self.output_dtype)
        return logits.scatter_(class_axis, indices, 1)


def _require_bounded_scope(
    task: TaskDataPath, scope: object, *, data_dir: str, max_samples: int | None
) -> None:
    """Refuse a scope the task did not bound to the run's evaluation ceiling."""
    if max_samples is None:
        return
    dataset = task.validation_dataset(scope, EvalMaterializationParams(data_dir=data_dir))
    if not isinstance(dataset, Sized):
        raise TypeError("validation_dataset must return a sized, map-style dataset")
    if len(dataset) > max_samples:
        task_id = getattr(task, "task_data_path_id", type(task).__name__)
        raise PseudoEvidenceUnsupported(
            f"Pseudo inference refused: task data path {task_id!r} materialized "
            f"{len(dataset)} evaluation samples, above validation_max_samples="
            f"{max_samples}. Its build_eval_scope does not honour "
            "ScopeBuildRequest.max_samples, so pseudo cost would follow dataset "
            "size. Implement that ceiling in the task, or pass an explicit "
            f"--validation_max_samples >= {len(dataset)} to accept this cost."
        )


def write_pseudo_deliverable(
    *,
    output_dir: str,
    data_dir: str,
    exp_id: str,
    run_name: str,
    model_type: str,
    task_scopes: object,
    max_samples: int | None = None,
) -> None:
    """Reuse inference iteration, scope identity and task storage on CPU.

    Batch one bounds framework tensor lifetime, not task dataset/writer storage.
    ``max_samples`` is the run's evaluation ceiling, which the task's own
    ``build_eval_scope`` already applied. A scope that still materializes more
    rows is refused before any prediction, so pseudo cost never follows
    dataset size. Legacy calls without an evaluation scope retain their
    artifact-free behavior.
    """
    scope = getattr(task_scopes, "evaluation", None)
    if scope is None:
        return
    validate_generated_artifact_name(exp_id, field="exp_id")
    validate_generated_artifact_name(run_name, field="run_name")
    task = active_task_data_path()
    contract = run_bound_model_io_contract()
    if task is None or contract is None:
        raise PseudoEvidenceUnsupported(
            "Pseudo evidence requires a bound task and Model-I/O contract"
        )
    _require_bounded_scope(task, scope, data_dir=data_dir, max_samples=max_samples)
    outcome = run_generic_inference(
        data_path=task,
        task_scope=scope,
        model=SyntheticPredictionModel(contract).eval(),
        device=torch.device("cpu"),
        data_dir=data_dir,
        batch_size=1,
        input_dtype=resolve_contract_input_dtype(contract.input.dtype),
        write_request=DeliverableWriteRequest(
            output_dir=output_dir,
            exp_id=exp_id,
            run_name=run_name,
            model_type=model_type,
        ),
    )
    provenance = {
        "_pseudo_origin": "stub_sandbox",
        "evaluation_max_samples": max_samples,
        "inference": outcome.model_dump(mode="json"),
    }
    (Path(output_dir) / f"pseudo_inference_{exp_id}_{run_name}.json").write_text(
        json.dumps(provenance, indent=2) + "\n", encoding="utf-8"
    )
