"""Tiny token-identity task matching the built-in pseudo bridge's model contract."""

import json
from pathlib import Path

import torch
from pydantic import BaseModel, ConfigDict, Field
from torch.utils.data import TensorDataset

from execute_tools.evaluation_metric import EvaluationMetric
from execute_tools.task_data_path import TaskOutputArtifactInventory


class Scope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: list[tuple[int, int]] = Field(min_length=1)


def deliverable_name(request):
    from execute_tools.deliverable_spec import resolve_deliverable_naming

    return resolve_deliverable_naming().name(
        model_type=request.model_type,
        run_name=request.run_name,
        exp_id=request.exp_id,
        input_identity=0,
    )


def tokens(scope):
    return torch.tensor(
        [
            [(partition * 8 + row + offset) % 256 for offset in range(8)]
            for partition, row in scope.rows
        ],
        dtype=torch.int64,
    )


class NativeChainTask:
    task_data_path_id = "native_chain_tokens"

    def _scope(self, request):
        partitions = list(range(20))
        if request.subset_ref:
            partitions = [int(value) for value in request.subset_ref.split(",")]
        if request.selection_strategy == "target":
            partitions = [value for value in request.target_partitions if value in partitions]
        if request.selection_strategy == "anchors":
            partitions = [value for value in (4, 7, 9) if value in partitions]
        count = max(1, round(8 * request.portion))
        rows = [(partition, row) for partition in partitions for row in range(count)]
        if request.max_samples is not None:
            rows = rows[: request.max_samples]
        return Scope(rows=rows)

    def build_training_scope(self, request):
        return self._scope(request)

    def build_eval_scope(self, request):
        return self._scope(request)

    def serialize_scope(self, scope):
        return scope.model_dump_json()

    def deserialize_scope(self, payload):
        return Scope.model_validate_json(payload)

    def training_dataset(self, scope, params):
        inputs = tokens(scope)
        return TensorDataset(inputs, inputs.clone())

    def validation_dataset(self, scope, params):
        return self.training_dataset(scope, params)

    def write_deliverable(self, outputs, request):
        predictions = list(outputs)
        if len(predictions) != len(request.task_scope.rows):
            raise ValueError("prediction count differs from scope")
        payload = []
        for prediction in predictions:
            prediction = torch.as_tensor(prediction)
            if prediction.shape != (256, 8):
                raise ValueError("expected 256 logits for each of eight tokens")
            payload.append(prediction.argmax(dim=0).tolist())
        Path(request.output_dir).mkdir(parents=True, exist_ok=True)
        (Path(request.output_dir) / deliverable_name(request)).write_text(json.dumps(payload))

    def read_evaluation_payload(self, request):
        return json.loads((Path(request.deliverable_dir) / deliverable_name(request)).read_text())

    def enumerate_output_artifacts(self, request):
        name = deliverable_name(request)
        return TaskOutputArtifactInventory(
            run_name=request.run_name,
            exp_id=request.exp_id,
            model_type=request.model_type,
            relative_paths=(name,) if (Path(request.deliverable_dir) / name).exists() else (),
        )


class TokenAccuracy(EvaluationMetric):
    def _compute(self, deliverables, /, *, evaluation_payload=None, task_scope=None, **kwargs):
        actual = torch.tensor(evaluation_payload, dtype=torch.int64)
        expected = tokens(task_scope)
        if actual.shape != expected.shape or actual.numel() == 0:
            raise ValueError("token predictions must cover the exact evaluation scope")
        return float((actual == expected).float().mean()), None, ()
