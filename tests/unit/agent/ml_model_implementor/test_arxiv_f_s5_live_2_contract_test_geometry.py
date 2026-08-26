"""arXiv F-S5-LIVE-2 — the generated test's GEOMETRY is contract-derived.

The first live quickstart chain run (S5 witness, 2026-08-24) proved that the
implementor's generated test hardcoded the legacy ``[B, T]`` int geometry
(``torch.randint(0, C, (2, config.segmentation_size))``) while the validator's
direct probe was already contract-aware — so every CORRECT candidate of a
non-legacy ``model_io`` task deterministically failed its own generated test
with ``mat1 and mat2 must have the same dtype, but got Long and Float``
(persisted in the live workspace's ``validation_iter_001.json``), and the
composed propose→implement→validate loop could never pass for such a task.

WHAT ONLY THIS FILE CATCHES: the Step-04a suites pin the TIDMAD/legacy
renderings byte-exactly and the class-count derivation, but no existing test
EXECUTES a generated test file against a NON-legacy contract — which is
precisely the surface the live run broke on. Re-hardcode the input line (the
plant) and ``test_generated_test_executes_against_a_tabular_float_plugin``
reproduces the live failure verbatim while every byte-parity test stays green.
"""

from __future__ import annotations

import ast
import subprocess
import sys

import pytest

from agent.schemas.model_io_contract import (
    AxisRole,
    Dimension,
    DtypeAdmissibility,
    ModelIOContract,
    TensorAxis,
    TensorContract,
)
from agent.skills.model_io_probe_skill import realize_shape
from nodes.ml_model_implementor.ml_model_implementor import (
    _assemble_test,
    _render_axis_extents,
)


def _tabular_classifier_contract() -> ModelIOContract:
    """The quickstart shape: ``[B, 4] float32 -> [B, 2]`` classifier."""
    return ModelIOContract(
        input=TensorContract(
            axes=(
                TensorAxis(dimension=Dimension(symbolic="B"), role=AxisRole.BATCH),
                TensorAxis(dimension=Dimension(fixed=4)),
            ),
            dtype=DtypeAdmissibility(admissible=("float32",)),
        ),
        output=TensorContract(
            axes=(
                TensorAxis(dimension=Dimension(symbolic="B"), role=AxisRole.BATCH),
                TensorAxis(dimension=Dimension(fixed=2), role=AxisRole.CLASS),
            ),
            dtype=DtypeAdmissibility(admissible=("float32",)),
        ),
    )


def _rank4_image_contract() -> ModelIOContract:
    """The Pets shape: ``[B, 3, 144, 144] float32 -> [B, 37]`` classifier."""
    return ModelIOContract(
        input=TensorContract(
            axes=(
                TensorAxis(dimension=Dimension(symbolic="B"), role=AxisRole.BATCH),
                TensorAxis(dimension=Dimension(fixed=3)),
                TensorAxis(dimension=Dimension(fixed=144)),
                TensorAxis(dimension=Dimension(fixed=144)),
            ),
            dtype=DtypeAdmissibility(admissible=("float32",)),
        ),
        output=TensorContract(
            axes=(
                TensorAxis(dimension=Dimension(symbolic="B"), role=AxisRole.BATCH),
                TensorAxis(dimension=Dimension(fixed=37), role=AxisRole.CLASS),
            ),
            dtype=DtypeAdmissibility(admissible=("float32",)),
        ),
    )


_TABULAR_PLUGIN = """\
import torch
from pydantic import BaseModel, Field


class DemoConfig(BaseModel):
    segmentation_size: int = Field(default=4, ge=1)
    batch_size: int = Field(default=2, ge=1)


class DemoModel(torch.nn.Module):
    def __init__(self, config: DemoConfig):
        super().__init__()
        self.linear = torch.nn.Linear(4, 2)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.linear(x)


PLUGIN_MODEL_TYPE = "demo_tabular"
PLUGIN_CONFIG_CLASS = DemoConfig
PLUGIN_MODEL_CLASS = DemoModel
PLUGIN_OUTPUT_TYPE = "classifier"
"""


def test_generated_test_executes_against_a_tabular_float_plugin(tmp_path):
    """A correct ``[B,4] f32 -> [B,2]`` candidate PASSES its generated test.

    HOW THIS FAILS WHEN THE BEHAVIOUR BREAKS: re-hardcode the legacy input
    line in the template (the F-S5-LIVE-2 state) and the generated test feeds
    ``Long`` indices of shape ``(2, segmentation_size)`` to a float Linear —
    pytest exits non-zero with the exact live-run error (``same dtype, but
    got Long and Float``); break the expected-shape rendering instead and the
    shape assertion fails against the rank-2 output.
    """
    contract = _tabular_classifier_contract()
    model_name = "demo_tabular"
    test_src = _assemble_test(model_name, contract)

    assert "torch.rand((2, 4))" in test_src
    assert "(2, 2)" in test_src
    ast.parse(test_src)

    models = tmp_path / "models"
    models.mkdir()
    (models / f"{model_name}.py").write_text(_TABULAR_PLUGIN)
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / f"test_{model_name}.py").write_text(test_src)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", f"test_{model_name}.py", "-q"],
        cwd=tests_dir,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"


def test_rank4_fixed_axes_render_literally():
    """A ``[B,3,144,144]`` input renders its fixed axes as literals.

    HOW THIS FAILS: collapse the renderer back to the 2-D legacy shape and
    the rank-4 tuple disappears from the generated source.
    """
    src = _assemble_test("demo_img", _rank4_image_contract())
    assert "torch.rand((2, 3, 144, 144))" in src
    assert "torch.rand((1, 3, 144, 144))" in src


@pytest.mark.parametrize("contract_fn", [_tabular_classifier_contract, _rank4_image_contract])
def test_renderer_agrees_with_realize_shape(contract_fn):
    """The source-code renderer and ``realize_shape`` realize ONE geometry.

    The renderer deliberately mirrors ``realize_shape``'s three-rule per-axis
    precedence; this test is what makes that mirroring a checked fact instead
    of a docstring claim. HOW THIS FAILS: change either side's precedence
    (e.g. batch-role before fixed) and the evaluated tuples diverge.
    """
    seg = 7
    contract = contract_fn()
    for tensor in (contract.input, contract.output):
        rendered = _render_axis_extents(tensor, batch_literal=2)
        evaluated = tuple(seg if e == "config.segmentation_size" else int(e) for e in rendered)
        assert evaluated == realize_shape(tensor, batch=2, symbolic=seg)
