"""Step 04a — the implementor's self-check and artifacts derive from the contract.

Design: ``docs/design/generic_framework_upgrade/step_04_candidate_creation_mechanics/
pr_04a_contract_derived_candidate_mechanics.md`` §16 C4, §15.1, §9 failure
classes 2 and 6.

**The defect only this module catches.** Three surfaces inside the implementor
restated the class count independently of the task: the in-process self-check,
the contract comments written into every generated plugin, and the assertions
inside every generated test file. Because all three said ``256`` and the task
said ``256``, nothing could tell agreement from coincidence.

The tests below break the coincidence by declaring **16** and then checking
the artifact that was actually produced — the rendered comment string, the
executed generated test, the tensor the self-check built. §16's binding rule:
assert the observable artifact, never the configuration value.

Generated code is additionally parsed with ``ast.parse``: the plugin and test
templates use ``{{ }}`` escaping, and a new placeholder is exactly the kind of
change that produces a file which looks right in a diff and does not compile.
"""

from __future__ import annotations

import ast
import subprocess
import sys

import pytest

from agent.prompt_templates.implementor.task_blocks import load_implementor_task_blocks
from agent.skills.model_io_probe_skill import ProbeConstructionError
from nodes.ml_model_implementor.ml_model_implementor import (
    _assemble_plugin,
    _assemble_test,
    _render_output_contract,
    _smoke_test_plugin,
)
from tests.helpers.step04a_fixtures import (
    CODE_BY_OUTPUT_TYPE,
    MODEL_NAMES,
    implementor_input,
    regressor_model_io,
    tidmad_model_io,
)

# The frozen LLM contribution builds a 256-class head. For the 16-class cases
# the head must match the declaration, so a parameterized variant is used.
_SIXTEEN_CLASS_CODE = {
    "extra_imports": "",
    "config_fields_code": "    channels: int = Field(default=16, ge=1)",
    "config_validators_code": "",
    "init_body": (
        "self.emb = nn.Embedding(16, config.channels)\n"
        "self.head = nn.Conv1d(config.channels, 16, kernel_size=1)"
    ),
    "forward_body": "out = self.emb(x).permute(0, 2, 1)\nreturn self.head(out)",
}


# ---------------------------------------------------------------------------
# The generated plugin's contract comments
# ---------------------------------------------------------------------------


def test_contract_comments_render_from_the_declaration(tmp_path):
    """Under a 16-class task the generated plugin documents 16, not 256.

    Fails when: either comment string is restated instead of rendered.
    """
    inp = implementor_input(
        "classifier", model_io=tidmad_model_io(num_classes=16), workspace=str(tmp_path)
    )
    source = _assemble_plugin(inp, _SIXTEEN_CLASS_CODE)

    assert "input [B, T] int64 → output [B, 16, T] float32" in source
    assert "[B, 16, T] → 16-class classification" in source
    assert "256" not in source.replace("nn.Embedding(16", ""), (
        "a 256 survived in a generated plugin for a 16-class task"
    )
    ast.parse(source)


def test_a_regressor_task_documents_the_continuous_form(tmp_path):
    """A task with no class alphabet must not have one written into its plugin."""
    inp = implementor_input("regressor", model_io=regressor_model_io(), workspace=str(tmp_path))
    source = _assemble_plugin(inp, CODE_BY_OUTPUT_TYPE["regressor"])

    assert "input [B, T] int64 → output [B, T] float32" in source
    assert "[B, T] → continuous [B, T] output" in source
    ast.parse(source)


def test_a_regressor_candidate_under_a_categorical_task_drops_the_class_axis(tmp_path):
    """The Stage-A precedent, on the generation side.

    A candidate declaring ``regressor`` under the shipped categorical task
    must document ``[B, T]`` — the continuous form of THIS task's output —
    not the task's ``[B, 256, T]``. That is the A3/A4 behaviour, now derived
    rather than tabulated.
    """
    forward, output_type = _render_output_contract(
        "regressor", tidmad_model_io(), load_implementor_task_blocks()
    )
    assert forward == "input [B, T] int64 → output [B, T] float32"
    assert output_type == "[B, T] → continuous [B, T] output"


def test_a_classifier_candidate_under_a_continuous_task_fails_closed():
    """§15.1 row 3 on the generation side, not just the probe side.

    Fails when: generation invents a class count the task never declared —
    which would then be written into the plugin, its description and its
    test, and only surface as a shape rejection much later.
    """
    with pytest.raises(ProbeConstructionError):
        _render_output_contract("classifier", regressor_model_io())


def test_an_unrecognised_output_type_still_raises():
    """C4 negative: the deliberate ValueError survives the rewrite.

    Fails when: the derivation path silently accepts an unknown declaration
    and renders something plausible for it.
    """
    with pytest.raises(ValueError, match="Unknown output_type"):
        _render_output_contract("hybrid", tidmad_model_io())
    with pytest.raises(ValueError, match="Unknown output_type"):
        _render_output_contract("hybrid", None)


# ---------------------------------------------------------------------------
# The generated TEST FILE — executed, not string-matched
# ---------------------------------------------------------------------------


def test_the_generated_test_executes_against_a_16_class_plugin(tmp_path):
    """C4 acceptance: the generated test references 16 AND passes when run.

    Fails when: the class count in the generated test is not derived — the
    assertion then expects ``(2, 256, seg)`` from a 16-class model and the
    candidate fails its own test file. It also fails if the placeholder
    broke the template's ``{{ }}`` escaping, because the file would not run
    at all.
    """
    inp = implementor_input(
        "classifier", model_io=tidmad_model_io(num_classes=16), workspace=str(tmp_path)
    )
    model_name = MODEL_NAMES["classifier"]

    plugin_src = _assemble_plugin(inp, _SIXTEEN_CLASS_CODE)
    test_src = _assemble_test(model_name, tidmad_model_io(num_classes=16))

    assert "(2, 16, config.segmentation_size)" in test_src
    assert "torch.randint(0, 16," in test_src
    ast.parse(test_src)

    (tmp_path / f"{model_name}.py").write_text(plugin_src)
    (tmp_path / f"test_{model_name}.py").write_text(test_src)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", f"test_{model_name}.py", "-q"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"


# ---------------------------------------------------------------------------
# The in-process self-check
# ---------------------------------------------------------------------------


def test_the_self_check_accepts_a_16_class_candidate_under_a_16_class_task(tmp_path):
    """The self-check probe derives its own input and expectation.

    Fails when: the self-check feeds indices up to 255 into a 16-symbol
    embedding (crash), or judges a 16-class head against a 256-class
    expectation (shape mismatch). Both are what the old literals did.
    """
    inp = implementor_input(
        "classifier", model_io=tidmad_model_io(num_classes=16), workspace=str(tmp_path)
    )
    plugin_src = _assemble_plugin(inp, _SIXTEEN_CLASS_CODE)

    assert _smoke_test_plugin(plugin_src, inp.model_name, tidmad_model_io(16)) is None


def test_the_same_candidate_is_rejected_by_the_legacy_self_check(tmp_path):
    """The negative twin — proves the test above needed the contract.

    Under the legacy geometry the probe draws indices up to 255, so a
    16-symbol embedding raises. A green result above therefore required the
    declaration to reach the self-check.
    """
    inp = implementor_input(
        "classifier", model_io=tidmad_model_io(num_classes=16), workspace=str(tmp_path)
    )
    plugin_src = _assemble_plugin(inp, _SIXTEEN_CLASS_CODE)

    error = _smoke_test_plugin(plugin_src, inp.model_name, None)
    assert error is not None


def test_the_self_check_reports_an_unrealizable_contract_as_an_error(tmp_path):
    """A contract that cannot be realized is a repairable error, not a crash.

    ``_smoke_test_plugin`` documents that it never raises: its string return
    feeds the existing repair loop. A ``ProbeConstructionError`` escaping it
    would abort the whole implementor run instead.

    Fails when: the typed error is allowed to propagate.
    """
    inp = implementor_input("classifier", model_io=tidmad_model_io(), workspace=str(tmp_path))
    plugin_src = _assemble_plugin(inp, CODE_BY_OUTPUT_TYPE["classifier"])

    error = _smoke_test_plugin(plugin_src, inp.model_name, regressor_model_io())
    assert error is not None
    assert "task contract" in error


def test_tidmad_self_check_is_unchanged_between_the_two_paths(tmp_path):
    """Stage-A parity for the self-check itself."""
    inp = implementor_input("classifier", model_io=tidmad_model_io(), workspace=str(tmp_path))
    plugin_src = _assemble_plugin(inp, CODE_BY_OUTPUT_TYPE["classifier"])

    assert _smoke_test_plugin(plugin_src, inp.model_name, None) is None
    assert _smoke_test_plugin(plugin_src, inp.model_name, tidmad_model_io()) is None
