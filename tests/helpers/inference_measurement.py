"""Small external task transport with distinct training/evaluation dtypes."""

import json
from pathlib import Path

from execute_tools.task_data_path import EpochSamplingParams, TaskProbeDataSpec
from tests.fixtures.integer_input_inference_task import IntegerInputTaskDataPath
from tests.helpers.composed_manifest import write_complete_manifest
from workflows.task_composition import compose_run_task_bindings


def evaluation_probe(tmp_path: Path, *, rows: int, data_dir: str | None = None):
    implementation = IntegerInputTaskDataPath()
    manifest = write_complete_manifest(
        tmp_path,
        task_data_path={
            "file": str(
                Path(__file__).resolve().parents[1] / "fixtures/integer_input_inference_task.py"
            ),
            "symbol": "IntegerInputTaskDataPath",
            "id": implementation.task_data_path_id,
        },
    )
    composition = compose_run_task_bindings(str(manifest))
    return TaskProbeDataSpec(
        manifest_path=str(manifest),
        semantic_fingerprint=composition.semantic_fingerprint,
        training_scope_payload="not a valid training scope",
        evaluation_scope_payload=json.dumps(
            {"kind": "fcov8_declared_naming_scope_v1", "rows": rows}
        ),
        sampling=EpochSamplingParams(data_dir=data_dir or str(tmp_path)),
        segmentation_applicability="not_applicable",
    )
