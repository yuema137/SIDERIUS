"""Shared synthetic task declaration for actual native-chain lifecycle witnesses."""

import json

import yaml


def write_native_chain_manifest(root, inputs):
    # The built-in pseudo bridge emits the existing token-model fixture. Give
    # it that declared I/O contract rather than Quickstart's float/tabular one.
    from tests.helpers.composed_manifest import write_complete_manifest

    manifest = write_complete_manifest(
        inputs,
        task_data_path={
            "file": str(root / "tests/fixtures/native_chain_task.py"),
            "symbol": "NativeChainTask",
            "id": "native_chain_tokens",
        },
        metric={
            "declaration": "../../examples/quickstart/declared/metric_accuracy.json",
            "implementation": {
                "file": str(root / "tests/fixtures/native_chain_task.py"),
                "symbol": "TokenAccuracy",
            },
        },
        model_plugins=None,
    )
    (inputs / "examples/quickstart/declared/dataset_profile.json").write_text(
        json.dumps(
            {
                "partition_count": 20,
                "anchor_selection_files": [4, 7, 9],
                "health_peek_files": [4, 7, 9],
                "topology": {
                    "modality": "token_sequence",
                    "class_cardinality": 256,
                    "sequence_length": 8,
                },
            }
        )
    )
    task_config = inputs / "examples/quickstart/declared/task_config.yaml"
    task_config.write_text(
        yaml.safe_dump(
            {
                "task_description": "Synthetic token-model pseudo lifecycle; no scientific data or training.",
                "forward_contract": {
                    "segmentation_applicability": "not_applicable",
                    "model_io": {
                        "input": {
                            "axes": [
                                {"role": "batch", "dimension": {"symbolic": "B"}},
                                {"dimension": {"fixed": 8}},
                            ],
                            "dtype": {"admissible": ["int64"]},
                        },
                        "output": {
                            "axes": [
                                {"role": "batch", "dimension": {"symbolic": "B"}},
                                {"role": "class", "dimension": {"fixed": 256}},
                                {"dimension": {"fixed": 8}},
                            ],
                            "dtype": {"admissible": ["float32"]},
                        },
                    },
                    "input_description": "eight integer tokens",
                    "output_description": "256 logits per token",
                    "task_type": "classification",
                    "output_head_note": "Unnormalized logits.",
                },
            }
        )
    )
    return manifest
