"""Tiny token-identity task matching the built-in pseudo bridge's model contract."""

import json
from pathlib import Path

import torch
from torch.utils.data import TensorDataset

from execute_tools.evaluation_metric import EvaluationMetric
from execute_tools.task_data_path import TaskOutputArtifactInventory
from tests.fixtures.fcov8_declared_naming_task import deliverable_name
from tests.fixtures.tuner_composed_task import TunerComposedTask


def tokens(scope):
    return torch.tensor(
        [
            [(partition * 8 + row + offset) % 256 for offset in range(8)]
            for _, partition, row in scope["rows"]
        ],
        dtype=torch.int64,
    )


class NativeChainTask(TunerComposedTask):
    task_data_path_id = "native_chain_tokens"

    def training_dataset(self, scope, params):
        inputs = tokens(scope)
        return TensorDataset(inputs, inputs.clone())

    def validation_dataset(self, scope, params):
        return self.training_dataset(scope, params)

    def write_deliverable(self, outputs, request):
        predictions = list(outputs)
        if len(predictions) != len(request.task_scope["rows"]):
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
