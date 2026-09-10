"""Deterministic assembled artifacts for an explicitly synthetic contract.

Retains Step-04a's byte and cross-workspace reproducibility failure classes:
field ordering, contract comments, output-type annotation and code indentation
are not protected merely by executing a generated plugin successfully.

The historical captures are migrated by explicit fixture substitutions only:
7 classes instead of 256, segment length 24 instead of 4000, and a neutral
continuous-output phrase. They are not regenerated from the renderer. Legacy
no-contract/default-science equivalence is intentionally not supported here.
"""

from pathlib import Path

import pytest

from agent.schemas.implementor import ImplementorInput, ImplementorTaskBlocks
from agent.schemas.model_io_contract import ModelIOContract
from agent.schemas.task_config import ForwardContract
from nodes.ml_model_implementor.ml_model_implementor import _assemble_plugin, _assemble_test
from tests.helpers.golden import assert_golden

GOLDENS = Path(__file__).parent / "goldens"


def _model_io() -> ModelIOContract:
    sequence = [
        {"dimension": {"symbolic": "B"}, "role": "batch"},
        {"dimension": {"symbolic": "T"}, "role": "temporal"},
    ]
    return ModelIOContract.model_validate(
        {
            "input": {"axes": sequence, "dtype": {"admissible": ["int64", "int32"]}},
            "output": {
                "axes": [sequence[0], {"dimension": {"fixed": 7}, "role": "class"}, sequence[1]],
                "dtype": {"admissible": ["float32"]},
            },
        }
    )


def _render_plugin(output_type: str, workspace: Path) -> str:
    inp = ImplementorInput(
        model_name=f"s04a_baseline_{output_type}",
        output_type=output_type,
        model_description="Synthetic sequence fixture.",
        mathematical_definition="Embedding -> pointwise projection.",
        task_description="Classify or reconstruct synthetic token sequences.",
        implementor_blocks=ImplementorTaskBlocks(),
        forward_contract=ForwardContract(model_io=_model_io()),
        baseline_config={
            "model_config": {"channels": 16, "segmentation_size": 24},
            "train_config": {"batch_size": 2},
        },
        plugin_dir=str(workspace / "models"),
        test_dir=str(workspace / "tests"),
        loss_dir=str(workspace / "losses"),
    )
    out_channels = 7 if output_type == "classifier" else 1
    suffix = "" if output_type == "classifier" else ".squeeze(1)"
    return _assemble_plugin(
        inp,
        {
            "extra_imports": "",
            "config_fields_code": "    channels: int = Field(default=16, ge=1)",
            "config_validators_code": "",
            "init_body": "self.emb = nn.Embedding(7, config.channels)\n"
            f"self.head = nn.Conv1d(config.channels, {out_channels}, kernel_size=1)",
            "forward_body": "out = self.emb(x).permute(0, 2, 1)\nreturn self.head(out)" + suffix,
        },
    )


@pytest.mark.parametrize("output_type", ["classifier", "regressor"])
def test_generated_plugin_bytes_match_the_explicit_spec(tmp_path, output_type):
    assert_golden(
        _render_plugin(output_type, tmp_path),
        GOLDENS / f"s04a_generated_plugin_{output_type}.txt",
        surface=f"S04a synthetic {output_type} assembly",
    )


@pytest.mark.parametrize("output_type", ["classifier", "regressor"])
def test_generated_plugin_bytes_do_not_depend_on_workspace(tmp_path, output_type):
    assert _render_plugin(output_type, tmp_path / "first") == _render_plugin(
        output_type, tmp_path / "second"
    )


def test_generated_test_bytes_match_the_explicit_spec():
    assert_golden(
        _assemble_test("s04a_baseline_classifier", _model_io()),
        GOLDENS / "s04a_generated_test.txt",
        surface="S04a synthetic generated test",
    )
